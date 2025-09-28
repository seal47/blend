# README.md

# Image Blender (FastAPI + Vanilla Web)

A minimalist single-page app to upload multiple images, blend them on a Python
backend, preview the result, and download as `blended.png`.

- Frontend: vanilla HTML/CSS/JS (served by FastAPI)
- Backend: FastAPI
- Integration: Tries to call your `blend.py` (project root). If not found or
  incompatible, it falls back to an internal average-blending implementation.

## Requirements

- Python 3.9+ recommended
- pip

## Quick start

```bash
pip install -r requirements.txt
uvicorn server:app --reload
```

Open http://127.0.0.1:8000

## Usage

- Click “Upload images” or drag-and-drop 2–10 images (PNG/JPEG/WebP, ≤15 MB
  each).
- Wait for the “Blending…” indicator to finish.
- Preview appears; click “Download image” to save `blended.png`.
- Footer text is clickable and copies to clipboard, showing a brief “Copied”
  toast.

## Adapting to your blend.py

The backend attempts integration in this order:

1) In-memory API (preferred)
   - Define this in `blend.py`:
     ```python
     from PIL import Image
     from io import BytesIO
     def blend_images_from_files(files: list[bytes]) -> Image.Image:
         # Return a Pillow image built from the given raw image bytes
         ...
     ```

2) File-path API
   - Define this in `blend.py`:
     ```python
     from PIL import Image
     def blend_images(paths: list[str]) -> Image.Image | str:
         # Return a Pillow image, or a file path to the blended image
         ...
     ```

3) CLI API
   - The server runs (see exact code line below):
     ```
     python blend.py in1.png in2.png ... -o out.png
     ```
   - If your CLI differs, edit the command marked with:
     `TODO(blend-cli)` in `server.py`.
     - File: `server.py`
     - Search: `TODO(blend-cli)`
     - Location: inside `_try_blend_via_user_script(...)` where `cmd = [...]`
       is defined. Modify args to match your script’s CLI.

Notes:

- If your existing script currently expects a folder (e.g., scans `images/`),
  either implement one of the functions above, or adjust the CLI command at the
  `TODO(blend-cli)` to match your interface.
- Regardless of the integration path, the API returns a PNG.

## Project structure

- `server.py` — FastAPI server and integration with `blend.py`; also serves the
  frontend.
- `web/index.html`, `web/styles.css`, `web/app.js` — The single-page frontend.
- `requirements.txt` — Python dependencies.
- `.gitignore` — Common excludes.

## Security and notes

- Filenames are sanitized and re-written to a private temporary directory.
- Each file is size-checked (≤15 MB) and type-checked (PNG/JPEG/WebP).
- Temporary files are cleaned up after each request.

