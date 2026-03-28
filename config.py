# config.py — All settings for the tethered AI pipeline

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()  # Loads variables from .env file in the project root

# ──────────────────────────────────────────────
# CAPTURE MODE: "gphoto2" or "watch"
# ──────────────────────────────────────────────
CAPTURE_MODE = "watch"  # Start with "watch" for easy testing; switch to "gphoto2" when ready

# Folder to watch (only used in "watch" mode)
# Point your camera's tethering software (EOS Utility, etc.) at this folder
WATCH_FOLDER = "/Users/sboyle/Desktop/Tethered-AI/ai-incoming"

# ──────────────────────────────────────────────
# API SETTINGS (Google Gemini / Nano Banana)
# ──────────────────────────────────────────────
# Set your API key here or as an environment variable: GEMINI_API_KEY
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "your-api-key-here")

# Model to use for image generation/editing
# Options:
#   "gemini-2.5-flash-image"      — faster, lower latency (recommended for live use)
#   "gemini-3-pro-image-preview"  — higher quality, uses thinking/reasoning (slower)
GEMINI_MODEL = "gemini-3.1-flash-image-preview"

# Prompt sent with each captured image
API_PROMPT = "Restyle this image so it looks futuristic. Preserve the exact body position and facial expression of the persons in the image, but change the background, and change the lighting on the person to match the background."

# Timeout for API calls (seconds) — adjust based on typical generation time
API_TIMEOUT = 60

# ──────────────────────────────────────────────
# GEMINI OUTPUT IMAGE SETTINGS
# ──────────────────────────────────────────────
# Aspect ratio for generated images
# Options: "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"
GEMINI_ASPECT_RATIO = "4:3"

# Output resolution for generated images
# Options: "1K", "2K", "4K" (must be uppercase K)
# Note: higher resolution = slower generation, especially with gemini-3-pro-image-preview
GEMINI_OUTPUT_RESOLUTION = "1K"

# ──────────────────────────────────────────────
# IMAGE PROCESSING
# ──────────────────────────────────────────────
# Resolution to resize JPEGs before sending to API (longest edge in pixels)
# Lower = faster upload, less detail. Higher = more detail, slower.
API_SEND_RESOLUTION = 2000

# JPEG quality for the resized image sent to API (1-100)
API_SEND_QUALITY = 100

# ──────────────────────────────────────────────
# ARCHIVE / STORAGE
# ──────────────────────────────────────────────
# Where original JPEGs and RAW files are moved after processing
# Files are moved (not copied) from ai-incoming to here
ARCHIVE_FOLDER = "/Users/sboyle/Desktop/Tethered-AI/tethered-ai-archive"

# Dedicated folder for AI-generated output images (flat, easy to browse)
AI_OUTPUT_FOLDER = "/Users/sboyle/Desktop/Tethered-AI/ai-output"

# Folder for selected/favorited images
SELECTS_FOLDER = "/Users/sboyle/Desktop/Tethered-AI/selects"

# Session manifest — saves prompt + metadata for each image
SESSION_MANIFEST = "/Users/sboyle/Desktop/Tethered-AI/session.json"

# ──────────────────────────────────────────────
# SERVER
# ──────────────────────────────────────────────
HOST = "0.0.0.0"
PORT = 8000

# ──────────────────────────────────────────────
# FILE EXTENSIONS
# ──────────────────────────────────────────────
RAW_EXTENSIONS = {".cr2", ".cr3", ".nef", ".arw", ".raf", ".dng", ".orf", ".rw2"}
JPEG_EXTENSIONS = {".jpg", ".jpeg"}
