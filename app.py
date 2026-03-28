"""
Tethered AI Photography Pipeline
Main application — handles capture, API calls, archiving, and display server.
"""

import asyncio
import argparse
import base64
import io
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

from google import genai
from google.genai import types

import config

# ──────────────────────────────────────────────
# FOLDER SETUP
# ──────────────────────────────────────────────

archive_folder = Path(config.ARCHIVE_FOLDER)
ai_output_folder = Path(config.AI_OUTPUT_FOLDER)
selects_folder = Path(config.SELECTS_FOLDER)

for folder in [archive_folder, ai_output_folder, selects_folder]:
    folder.mkdir(parents=True, exist_ok=True)

print(f"Archive (originals + RAW): {archive_folder}")
print(f"AI output: {ai_output_folder}")
print(f"Selects: {selects_folder}")

# ──────────────────────────────────────────────
# GEMINI CLIENT
# ──────────────────────────────────────────────

gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)

# ──────────────────────────────────────────────
# IMAGE HISTORY (in-memory state)
# ──────────────────────────────────────────────

# Each entry: {"id": str, "original": path, "ai": path, "timestamp": float,
#   "selected": bool, "prompt": str, "parent_id": str|None, "edit_prompt": str|None}
image_history: list[dict] = []
current_index: int = -1

# Active prompt (can be changed from the browser UI)
active_prompt: str = config.API_PROMPT

# Session tracking
session_start_time: float = time.time()


def save_manifest():
    """Save session state to a JSON manifest file."""
    manifest = {
        "session_start": session_start_time,
        "active_prompt": active_prompt,
        "images": image_history,
    }
    Path(config.SESSION_MANIFEST).write_text(json.dumps(manifest, indent=2))

# ──────────────────────────────────────────────
# WEBSOCKET CONNECTIONS
# ──────────────────────────────────────────────

connected_clients: set[WebSocket] = set()


async def broadcast(message: dict):
    """Send a message to all connected browser clients."""
    data = json.dumps(message)
    disconnected = set()
    for ws in connected_clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.add(ws)
    connected_clients.difference_update(disconnected)


# ──────────────────────────────────────────────
# IMAGE PROCESSING
# ──────────────────────────────────────────────

def resize_for_api(image_path: Path) -> bytes:
    """Resize a JPEG to the configured resolution for API submission."""
    img = Image.open(image_path)
    img.thumbnail(
        (config.API_SEND_RESOLUTION, config.API_SEND_RESOLUTION),
        Image.LANCZOS,
    )
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=config.API_SEND_QUALITY)
    return buffer.getvalue()


# ──────────────────────────────────────────────
# GEMINI API CLIENT
# ──────────────────────────────────────────────

async def send_to_api(image_path: Path) -> Optional[bytes]:
    """
    Send a photo to Gemini's Nano Banana image generation API.
    Returns the generated image as bytes, or None on failure.

    Uses the official Google Gen AI SDK — sends a PIL Image directly
    alongside the text prompt, and extracts the image from the response.
    """
    try:
        # Open the resized JPEG as a PIL Image
        pil_image = Image.open(image_path)

        # Build the contents: prompt text + input image
        contents = [active_prompt, pil_image]

        # Call the API (this is synchronous in the SDK, so we run it in a thread)
        response = await asyncio.to_thread(
            gemini_client.models.generate_content,
            model=config.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(),
            ),
        )

        # Extract the generated image from the response
        for part in response.parts:
            if part.text is not None:
                print(f"    Gemini text: {part.text[:100]}...")
            elif part.inline_data is not None:
                # The SDK returns image data as bytes via inline_data
                image_data = part.inline_data.data
                if isinstance(image_data, str):
                    # base64 encoded string
                    return base64.b64decode(image_data)
                else:
                    # raw bytes
                    return bytes(image_data)

        print("    Gemini returned no image in response")
        return None

    except Exception as e:
        print(f"    Gemini API error: {e}")
        return None


async def send_edit_to_api(image_bytes: bytes, edit_prompt: str) -> Optional[bytes]:
    """
    Send an annotated/composite image back to Gemini with an edit instruction.
    Same API pattern as send_to_api but takes raw bytes instead of a file path.
    """
    try:
        pil_image = Image.open(io.BytesIO(image_bytes))
        contents = [edit_prompt, pil_image]

        response = await asyncio.to_thread(
            gemini_client.models.generate_content,
            model=config.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
                image_config=types.ImageConfig(),
            ),
        )

        for part in response.parts:
            if part.text is not None:
                print(f"    Gemini edit text: {part.text[:100]}...")
            elif part.inline_data is not None:
                image_data = part.inline_data.data
                if isinstance(image_data, str):
                    return base64.b64decode(image_data)
                else:
                    return bytes(image_data)

        print("    Gemini returned no image for edit")
        return None

    except Exception as e:
        print(f"    Gemini edit API error: {e}")
        return None


# ──────────────────────────────────────────────
# CORE PIPELINE
# ──────────────────────────────────────────────

async def process_new_photo(image_path: Path):
    """
    Main pipeline: take a new photo path, process it, move original to archive,
    save AI result to ai-output, and push to display.
    """
    global current_index

    shot_id = datetime.now().strftime("%H%M%S_%f")
    ext = image_path.suffix.lower()
    print(f"\n>>> New image detected: {image_path.name}")

    # --- Handle RAW files: move to archive, don't send to API ---
    if ext in config.RAW_EXTENSIONS:
        dest = archive_folder / f"{shot_id}{ext}"
        shutil.move(str(image_path), dest)
        print(f"    RAW moved to archive: {dest.name}")
        return

    # --- Handle JPEGs: process, then move original to archive ---
    if ext in config.JPEG_EXTENSIONS:
        # Resize for API and save to temp file (before moving original)
        start = time.time()
        jpeg_bytes = resize_for_api(image_path)
        resized_path = archive_folder / f"_temp_resized_{shot_id}.jpg"
        resized_path.write_bytes(jpeg_bytes)
        print(f"    Resized for API ({len(jpeg_bytes) // 1024}KB) in {time.time() - start:.2f}s")

        # Move original from ai-incoming to archive
        original_dest = archive_folder / f"{shot_id}.jpg"
        shutil.move(str(image_path), original_dest)
        print(f"    Original moved to archive: {original_dest.name}")

        # Notify display that processing has started
        await broadcast({
            "type": "processing",
            "original": f"/images/original/{original_dest.name}",
        })

        # Send to Gemini API
        start = time.time()
        result_bytes = await send_to_api(resized_path)
        api_time = time.time() - start

        # Clean up temp resized file
        resized_path.unlink(missing_ok=True)

        if result_bytes:
            # Save AI result to ai-output folder
            ai_dest = ai_output_folder / f"{shot_id}.jpg"
            ai_dest.write_bytes(result_bytes)
            print(f"    AI result saved to ai-output: {ai_dest.name} (API took {api_time:.2f}s)")

            # Add to history
            ai_path = f"/images/ai/{ai_dest.name}"
            entry = {
                "id": shot_id,
                "original": f"/images/original/{original_dest.name}",
                "ai": ai_path,
                "timestamp": time.time(),
                "selected": False,
                "prompt": active_prompt,
                "parent_id": None,
                "edit_prompt": None,
            }
            image_history.append(entry)
            current_index = len(image_history) - 1
            save_manifest()

            # Push to display
            await broadcast({"type": "new_image", **entry, "index": current_index})
        else:
            print(f"    API returned no result (took {api_time:.2f}s)")
            await broadcast({"type": "error", "message": "API returned no result"})


async def process_edit(image_index: int, composite_b64: str, edit_prompt: str):
    """Process an edit request: composite image + prompt -> new standalone entry."""
    global current_index

    if image_index < 0 or image_index >= len(image_history):
        await broadcast({"type": "error", "message": "Invalid image index for edit"})
        return

    parent_entry = image_history[image_index]
    edit_id = datetime.now().strftime("%H%M%S_%f")

    composite_bytes = base64.b64decode(composite_b64)

    await broadcast({"type": "processing"})

    start = time.time()
    result_bytes = await send_edit_to_api(composite_bytes, edit_prompt)
    api_time = time.time() - start

    if result_bytes:
        ai_dest = ai_output_folder / f"{edit_id}.jpg"
        ai_dest.write_bytes(result_bytes)
        ai_path = f"/images/ai/{ai_dest.name}"

        new_entry = {
            "id": edit_id,
            "original": parent_entry["original"],
            "ai": ai_path,
            "timestamp": time.time(),
            "selected": False,
            "prompt": parent_entry["prompt"],
            "parent_id": parent_entry["id"],
            "edit_prompt": edit_prompt,
        }

        image_history.append(new_entry)
        current_index = len(image_history) - 1
        save_manifest()

        print(f"    Edit saved as new entry: {ai_dest.name} (API took {api_time:.2f}s)")

        await broadcast({
            "type": "edit_result",
            "index": current_index,
            **new_entry,
        })
    else:
        print(f"    Edit API returned no result (took {api_time:.2f}s)")
        await broadcast({"type": "error", "message": "Edit API returned no result"})


# ──────────────────────────────────────────────
# FOLDER WATCHER (polling-based, reliable on all platforms)
# ──────────────────────────────────────────────

async def poll_folder():
    """Poll the watch folder for new image files every second."""
    watch_path = Path(config.WATCH_FOLDER)
    watch_path.mkdir(parents=True, exist_ok=True)
    seen = set()

    # Record any files already present so we don't process them
    for f in watch_path.iterdir():
        seen.add(f.name)

    print(f"Watching folder: {watch_path}")
    print(f"    ({len(seen)} existing files ignored)")

    while True:
        try:
            for f in watch_path.iterdir():
                if f.name.startswith(".") or f.name.startswith("_"):
                    continue
                if f.name in seen:
                    continue
                ext = f.suffix.lower()
                if ext in config.JPEG_EXTENSIONS | config.RAW_EXTENSIONS:
                    seen.add(f.name)
                    print(f"    [watcher] Detected: {f.name}")
                    # Small delay to ensure file is fully written
                    await asyncio.sleep(0.5)
                    await process_new_photo(f)
        except Exception as e:
            print(f"    [watcher] Error: {e}")

        await asyncio.sleep(1)  # Poll every second


# ──────────────────────────────────────────────
# GPHOTO2 CAPTURE (direct mode)
# ──────────────────────────────────────────────

async def start_gphoto2_capture():
    """
    Continuously wait for camera captures via gphoto2.
    Each capture pulls the image directly into memory.
    """
    try:
        import gphoto2 as gp
    except ImportError:
        print("ERROR: python-gphoto2 not installed. Install it or use --mode watch")
        return

    camera = gp.Camera()
    camera.init()
    print(f"Camera connected: {camera.get_summary()}")

    # Configure camera to shoot RAW+JPEG if desired
    # (This is camera-specific; you may need to adjust)

    print("Waiting for captures... (press shutter on camera)")

    while True:
        # Wait for a capture event from the camera
        event_type, event_data = camera.wait_for_event(1000)  # 1s timeout

        if event_type == gp.GP_EVENT_FILE_ADDED:
            cam_path = event_data
            filename = cam_path.name
            folder = cam_path.folder
            ext = Path(filename).suffix.lower()

            print(f"    Camera file: {folder}/{filename}")

            # Pull file from camera into memory
            cam_file = camera.file_get(folder, filename, gp.GP_FILE_TYPE_NORMAL)
            data = cam_file.get_data_and_size()

            # Save to a temp file so our pipeline can process it
            temp_path = archive_folder / f"_temp_{filename}"
            temp_path.write_bytes(bytes(data))

            await process_new_photo(temp_path)

            # Clean up temp file
            temp_path.unlink(missing_ok=True)

            # Optionally delete from camera to free card space
            # camera.file_delete(folder, filename)

        await asyncio.sleep(0.01)  # Yield to event loop


# ──────────────────────────────────────────────
# WEB SERVER
# ──────────────────────────────────────────────

app = FastAPI()

# Serve images from archive (originals), ai-output, and selects
app.mount("/images/original", StaticFiles(directory=str(archive_folder)), name="originals")
app.mount("/images/ai", StaticFiles(directory=str(ai_output_folder)), name="ai_results")
app.mount("/images/selects", StaticFiles(directory=str(selects_folder)), name="selects")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global current_index, active_prompt

    await websocket.accept()
    connected_clients.add(websocket)
    print(f"Display connected ({len(connected_clients)} total)")

    # Send current state to newly connected client
    await websocket.send_text(json.dumps({
        "type": "prompt",
        "prompt": active_prompt,
    }))
    if image_history:
        await websocket.send_text(json.dumps({
            "type": "history",
            "images": image_history,
            "current_index": current_index,
        }))

    try:
        while True:
            # Listen for commands from the browser
            data = await websocket.receive_text()
            msg = json.loads(data)

            if msg.get("type") == "navigate":
                direction = msg.get("direction")
                if direction == "prev" and current_index > 0:
                    current_index -= 1
                elif direction == "next" and current_index < len(image_history) - 1:
                    current_index += 1
                await broadcast({
                    "type": "show",
                    "index": current_index,
                    **image_history[current_index],
                })

            elif msg.get("type") == "set_prompt":
                active_prompt = msg.get("prompt", "").strip()
                print(f"    Prompt updated: {active_prompt[:80]}...")
                save_manifest()
                # Confirm to all clients
                await broadcast({"type": "prompt", "prompt": active_prompt})

            elif msg.get("type") == "edit_image":
                idx = msg.get("index")
                composite_b64 = msg.get("image", "")
                edit_prompt = msg.get("prompt", "").strip()
                if idx is not None and composite_b64 and edit_prompt:
                    asyncio.create_task(process_edit(idx, composite_b64, edit_prompt))
                else:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": "edit_image requires index, image, and prompt",
                    }))

            elif msg.get("type") == "toggle_select":
                idx = msg.get("index")
                if idx is not None and 0 <= idx < len(image_history):
                    entry = image_history[idx]
                    entry["selected"] = not entry["selected"]

                    filename = Path(entry["ai"]).name
                    if entry["selected"]:
                        src = ai_output_folder / filename
                        if src.exists():
                            dest = selects_folder / filename
                            shutil.copy2(str(src), str(dest))
                            print(f"    Select: copied {filename} to selects")
                    else:
                        target = selects_folder / filename
                        if target.exists():
                            target.unlink()
                            print(f"    Deselect: removed {filename} from selects")

                    save_manifest()
                    await broadcast({
                        "type": "select_updated",
                        "index": idx,
                        "selected": entry["selected"],
                    })

            elif msg.get("type") == "sync_view":
                # Relay photographer's view state to all clients (for stage display)
                await broadcast({
                    "type": "sync_view",
                    "view_mode": msg.get("view_mode", "ai"),
                    "edit_mode": msg.get("edit_mode", False),
                    "edit_src": msg.get("edit_src", ""),
                })

    except WebSocketDisconnect:
        connected_clients.discard(websocket)
        print(f"Display disconnected ({len(connected_clients)} total)")


# ──────────────────────────────────────────────
# STARTUP
# ──────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    mode = getattr(app.state, "capture_mode", config.CAPTURE_MODE)

    if mode == "gphoto2":
        asyncio.create_task(start_gphoto2_capture())
    else:
        asyncio.create_task(poll_folder())


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description="Tethered AI Photography Pipeline")
    parser.add_argument("--mode", choices=["gphoto2", "watch"], default=config.CAPTURE_MODE)
    parser.add_argument("--watch-folder", default=config.WATCH_FOLDER)
    parser.add_argument("--port", type=int, default=config.PORT)
    args = parser.parse_args()

    # Override config with CLI args
    config.CAPTURE_MODE = args.mode
    config.WATCH_FOLDER = args.watch_folder
    app.state.capture_mode = args.mode

    print(f"\n{'='*50}")
    print(f"  Tethered AI Photography Pipeline")
    print(f"  Mode: {args.mode}")
    if args.mode == "watch":
        print(f"  Watch folder: {args.watch_folder}")
    print(f"  Display: http://localhost:{args.port}")
    print(f"{'='*50}\n")

    uvicorn.run(app, host=config.HOST, port=args.port)


if __name__ == "__main__":
    main()
