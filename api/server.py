
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
	
	from fastapi import FastAPI, File, HTTPException, UploadFile
	from fastapi.responses import JSONResponse, Response
	from PIL import Image
	
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
	    return dest.read_bytes()
	
	
	def _ensure_pillow_image(
	    obj: Union[Image.Image, str, bytes, io.BytesIO]
	) -> Image.Image:
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
	    # PIL-only average, no NumPy (safer on Vercel)
	    images = [Image.open(p).convert("RGBA") for p in paths]
	    if not images:
	        raise ValueError("No images to blend.")
	    w, h = images[0].size
	    images = [im.resize((w, h), Image.LANCZOS) for im in images]
	    out = images[0]
	    # Weighted incremental average keeps equal weights for all inputs
	    for i, im in enumerate(images[1:], start=2):
	        out = Image.blend(out, im, 1.0 / i)
	    return out
	
	
	def _try_blend_via_user_script(
	    file_bytes: List[bytes], file_paths: List[Path], temp_dir: Path
	) -> Optional[Image.Image]:
	    here = Path(__file__).parent
	    if str(here) not in sys.path:
	        sys.path.insert(0, str(here))
	    try:
	        blend_mod = importlib.import_module("blend")
	    except ModuleNotFoundError:
	        blend_mod = None
	
	    if blend_mod and hasattr(blend_mod, "blend_images_from_files"):
	        try:
	            result = blend_mod.blend_images_from_files(file_bytes)
	            return _ensure_pillow_image(result)
	        except Exception:
	            pass
	
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
	            cmd, capture_output=True, text=True, cwd=str(here)
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
	
	
	# Register both paths so it works whether Vercel trims the base path or not
	@app.get("/")
	@app.get("/api/server")
	def health():
	    return {"status": "ok"}
	
	
	@app.post("/")
	@app.post("/api/server")
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