# api/server.py
from __future__ import annotations

import importlib
import io
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Union

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from PIL import Image

# ASGI app that Vercel runs as a Serverless Function
app = FastAPI(title="Image Blender API", version="1.0.0")

# Limits and validation (note: Vercel body size is limited; see notes below)
MIN_FILES = 2
MAX_FILES = 15
MAX_FILE_MB = 4
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
ACCEPTED_MEDIA_TYPES = {"image/png", "image/jpeg", "image/webp"}
ACCEPTED_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


def _sanitize_filename(name: str) -> str:
    base = os.path.basename(name or "")
    stem, ext = os.path.splitext(base)
    ext = ext.lower() if ext.lower() in ACCEPTED_EXTS else ".png"
    safe_stem = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem
    )[:40]
    token = secrets.token_hex(4)
    return f"{safe_stem or 'img'}_{token}{ext}"


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
                    detail=(
                        f"File '{upload.filename}' exceeds {MAX_FILE_MB} MB limit."
                    ),
                )
            f_out.write(chunk)
    with dest.open("rb") as f_in:
        return f_in.read()


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
    pil_images = [Image.open(p).convert("RGBA") for p in paths]
    if not pil_images:
        raise ValueError("No images to blend.")
    w, h = pil_images[0].size
    pil_images = [im.resize((w, h), Image.LANCZOS) for im in pil_images]
    arrays = np.array([np.array(im, dtype=np.float32) for im in pil_images])
    avg = np.mean(arrays, axis=0).astype(np.uint8)
    return Image.fromarray(avg, mode="RGBA")


def _try_blend_via_user_script(
    file_bytes: List[bytes],
    file_paths: List[Path],
    temp_dir: Path,
) -> Optional[Image.Image]:
    # Ensure this folder (api/) is importable
    here = Path(__file__).parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))

    try:
        blend_mod = importlib.import_module("blend")
    except ModuleNotFoundError:
        blend_mod = None

    # 1) In-memory API
    if blend_mod and hasattr(blend_mod, "blend_images_from_files"):
        try:
            result = blend_mod.blend_images_from_files(file_bytes)
            return _ensure_pillow_image(result)
        except Exception:
            pass

    # 2) File-path API
    if blend_mod and hasattr(blend_mod, "blend_images"):
        try:
            result = blend_mod.blend_images([str(p) for p in file_paths])
            try:
                return _ensure_pillow_image(result)
            except Exception:
                if isinstance(result, str) and os.path.exists(result):
                    return Image.open(result)
        except Exception:
            pass

    # 3) CLI fallback (works only if your blend.py supports it)
    try:
        out_path = temp_dir / "out.png"
        cmd = [
            sys.executable,
            "blend.py",
            *[str(p) for p in file_paths],
            "-o",
            str(out_path),
        ]
        # TODO(blend-cli): adjust flags if your CLI differs.
        proc = subprocess.run(
            cmd, captureOutput=True, text=True, cwd=str(here)
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"blend.py CLI failed ({proc.returncode}): {proc.stderr.strip()}"
            )
        if not out_path.exists():
            raise FileNotFoundError("Output image not found after CLI run.")
        return Image.open(out_path)
    except Exception:
        return None


@app.post("/")

@app.get("/")
def health():
return {"status": "ok"}
    
async def blend_endpoint(files: List[UploadFile] = File(...)) -> Response:
    if not files or len(files) < MIN_FILES or len(files) > MAX_FILES:
        raise HTTPException(
            status_code=422,
            detail=f"Please upload between {MIN_FILES} and {MAX_FILES} images.",
        )

    for uf in files:
        content_type = (uf.content_type or "").lower()
        ext_ok = Path(uf.filename or "").suffix.lower() in ACCEPTED_EXTS
        if content_type not in ACCEPTED_MEDIA_TYPES and not ext_ok:
            raise HTTPException(
                status_code=415,
                detail="Only PNG, JPEG, or WebP images are allowed.",
            )

    try:
        # Vercel allows writing to /tmp
        with tempfile.TemporaryDirectory(dir="/tmp", prefix="blend_") as td:
            temp_dir = Path(td)
            file_bytes: List[bytes] = []
            file_paths: List[Path] = []

            for uf in files:
                safe_name = _sanitize_filename(uf.filename or "image.png")
                dest = temp_dir / safe_name
                data = await _save_and_read(uf, dest)
                file_bytes.append(data)
                file_paths.append(dest)

            image = _try_blend_via_user_script(file_bytes, file_paths, temp_dir)
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
        return JSONResponse(
            status_code=500, content={"detail": f"Blending failed: {str(exc)}"}
        )
