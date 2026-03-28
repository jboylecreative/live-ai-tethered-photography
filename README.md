# Tethered AI Photography Pipeline

A local Python app that watches a folder for new photos, sends them to the Gemini API for AI image transformation, and displays the results on a fullscreen web-based display — designed for live tethered shooting.

## How It Works

```
Camera → Tethering software → ai-incoming folder/ ──► JPEG → Gemini API → WebSocket → Browser Display
                                              └──► Original → Archive folder
```

Your camera's tethering utility (e.g. Canon EOS Utility, Nikon Camera Control) saves photos directly to the `ai-incoming` folder. The app detects new files, sends them to Gemini, and displays the AI-transformed result on screen in near real-time.

## Setup

### 1. Install Python dependencies

```bash
cd tethered-ai
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### 2. Configure your Gemini API key

Copy `.env.example` to `.env` and add your key:

```bash
cp .env.example .env
```

Then edit `.env`:
```
GEMINI_API_KEY=your-api-key-here
```

### 3. Configure your camera and tethering software

In your camera's tethering utility (Canon EOS Utility, Nikon Camera Control, Capture One, etc.):

- Set the **destination folder** for captured images to the `ai-incoming/` folder in this project
- Set the **output format to JPEG** (not RAW) — RAW files are ignored by the pipeline
- Set the camera to a **smaller JPEG resolution** (e.g. S1 or medium) for faster processing and upload — full resolution is rarely needed for the AI transformation

### 4. Configure the app

Edit `config.py` to set:
- `WATCH_FOLDER` — path to your `ai-incoming` folder
- `API_PROMPT` — the transformation prompt sent with each image
- `GEMINI_MODEL` — model to use (see comments in config.py)
- Archive and output folder paths

### 5. Run

```bash
python app.py
```

Open a browser to `http://localhost:8000` and fullscreen it on your display monitor.

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Space | Toggle between AI result and original photo |
| ← / → | Navigate through previous shots |
| S | Toggle side-by-side view |
| F | Toggle fullscreen |

## Troubleshooting

**Gemini returns text but no image, or throws a model error**

The Gemini model name in `config.py` may be deprecated. Google periodically retires preview and experimental models. If you see errors like `404 NOT_FOUND`, `invalid model`, or the API responds with text describing what it *would* do instead of returning an image, the model name likely needs to be updated.

Check the current list of available image generation models in the [Google Gemini API documentation](https://ai.google.dev/gemini-api/docs) and update `GEMINI_MODEL` in `config.py` accordingly.
