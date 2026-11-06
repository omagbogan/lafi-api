from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile

from ..config import MAX_UPLOAD_BYTES, UPLOAD_DIR

router = APIRouter()
ALLOWED = {".jpg", ".jpeg", ".png", ".webp"}


@router.post("/uploads")
async def upload_photo(file: UploadFile):
    extension = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    if extension not in ALLOWED:
        raise HTTPException(400, "Format d'image non accepté (jpg, png ou webp)")
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image trop lourde (5 Mo maximum)")
    name = f"{uuid4().hex}{extension}"
    (UPLOAD_DIR / name).write_bytes(content)
    return {"url": f"/uploads/{name}"}