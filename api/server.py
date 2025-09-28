from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pathlib import Path
from typing import List, Optional, Union
from PIL import Image
import io
import os
import secrets
import tempfile
import importlib
import sys

app = FastAPI(title="Image Blender API", version="1.0.0")

# Small limits for Vercel
MIN_FILES = 2
MAX_FILES = 15
MAX_FILE_MB = 4
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
ACCEPTED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
ACCEPTED_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "")
    stem, ext = os.path.splitext(base)
    ext = ext.lower() if ext.lower() in ACCEPTED_EXTS else ".png"
    stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem)
    return f"{(stem or 'img')[:40]}_{secrets.token_hex(4)}{ext}"


async def _save_and_read(upload: UploadFile, dest: Path) -> bytes:
    total = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f_out:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"File '{upload.filename}' exceeds {MAX_FILE_MB} MB limit.",
                )
            f_out.write(chunk)
    return dest.read_bytes()


def _ensure_pillow_image(obj: Union[Image.Image, str, bytes, io.BytesIO]) -> Image.Image:
    if isinstance(obj, Image.Image):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        return Image.open(io.BytesIO(obj))
    if isinstance(obj, io.BytesIO):
        obj.seek(0)
        return Image.open(obj)
    if isinstance(obj, str) and os.path.exists(obj):
        return Image.open(obj)
    raise TypeError("Could not interpret blend result as an image.")


def _blend_internal_average(paths: List[Path]) -> Image.Image:
    # PIL-only incremental average (works on Vercel, no NumPy).
    images = [Image.open(p).convert("RGBA") for p in paths]
    if not images:
        raise ValueError("No images to blend.")
    w, h = images[0].size
    images = [im.resize((w, h), Image.LANCZOS) for im in images]
    out = images[0]
    for i, im in enumerate(images[1:], start=2):
        out = Image.blend(out, im, 1.0 / i)
    return out


def _try_user_blend(file_bytes: List[bytes], file_paths: List[Path]) -> Optional[Image.Image]:
    # Optional: if api/blend.py exists with blend_images_from_files or blend_images.
    here = Path(__file__).parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    try:
        blend_mod = importlib.import_module("blend")
    except ModuleNotFoundError:
        return None

    if hasattr(blend_mod, "blend_images_from_files"):
        try:
            return _ensure_pillow_image(blend_mod.blend_images_from_files(file_bytes))
        except Exception:
            pass

    if hasattr(blend_mod, "blend_images"):
        try:
            result = blend_mod.blend_images([str(p) for p in file_paths])
            return _ensure_pillow_image(result)
        except Exception:
            pass
    return None


# Health: make both paths work
@app.get("/")
@app.get("/api/server")
def health():
    return {"status": "ok"}


# Blend: accept both paths
@app.post("/")
@app.post("/api/server")
async def blend_endpoint(files: List[UploadFile] = File(...)) -> Response:
    if not files or len(files) < MIN_FILES or len(files) > MAX_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"Please upload between {MIN_FILES} and {MAX_FILES} images.",
        )

    for uf in files:
        ctype = (uf.content_type or "").lower()
        ext_ok = Path(uf.filename or "").suffix.lower() in ACCEPTED_EXTS
        if ctype not in ACCEPTED_MEDIA_TYPES and not ext_ok:
            raise HTTPException(
                status_code=415, detail="Only PNG, JPEG, or WebP images are allowed."
            )

    try:
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="blend_") as td:
            temp_dir = Path(td)
            file_bytes: List[bytes] = []
            file_paths: List[Path] = []

            for uf in files:
                safe = _sanitize_filename(uf.filename or "image.png")
                dest = temp_dir / safe
                data = await _save_and_read(uf, dest)
                file_bytes.append(data)
                file_paths.append(dest)

            image = _try_user_blend(file_bytes, file_paths)
            if image is None:
                image = _blend_internal_average(file_paths)

            buf = io.BytesIO()
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")
            image.save(buf, format="PNG")
            buf.seek(0)
            return Response(content=buf.getvalue(), media_type="image/png")
    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse(status_code=500, content={"detail": f"Blending failed: {exc}"})