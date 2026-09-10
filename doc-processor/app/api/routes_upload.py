"""Browser-upload endpoint — an alternative to typing a server-side
folder path (spec section 1's original assumption), useful whenever the
tool runs on a different machine than the user's own (e.g. a hosted
demo). Accepts .pdf / .zip / .xlsx / .xls; anything else is skipped
rather than rejected outright, so one stray file type in a multi-select
doesn't block the rest.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, UploadFile

from app.core.config_loader import get_settings
from app.core.logging_config import get_logger
from app.zip_utils import extract_zip_flat

log = get_logger("api.upload")
router = APIRouter(prefix="/api")

_ALLOWED_SUFFIXES = {".pdf", ".zip", ".xlsx", ".xls"}


def _unique_path(dest_dir: Path, filename: str) -> Path:
    target = dest_dir / filename
    if not target.exists():
        return target
    stem, suffix = Path(filename).stem, Path(filename).suffix
    n = 2
    while (dest_dir / f"{stem}__{n}{suffix}").exists():
        n += 1
    return dest_dir / f"{stem}__{n}{suffix}"


@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)) -> dict:
    uploads_root = Path(get_settings().get("uploads_dir", "UPLOADS"))
    batch_dir = uploads_root / str(uuid.uuid4())
    batch_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    skipped: list[str] = []

    for upload in files:
        filename = Path(upload.filename or "unnamed").name  # strip any client-side path
        suffix = Path(filename).suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            skipped.append(filename)
            await upload.close()
            continue

        target = _unique_path(batch_dir, filename)
        try:
            with open(target, "wb") as out:
                shutil.copyfileobj(upload.file, out)
        except OSError as exc:
            log.warning("Không lưu được file upload %s: %s", filename, exc)
            skipped.append(filename)
            continue
        finally:
            await upload.close()
        saved.append(target.name)

        if suffix == ".zip":
            extract_zip_flat(target, batch_dir / target.stem)

    log.info(
        "Upload batch %s: %d file lưu, %d file bỏ qua (định dạng không hỗ trợ)",
        batch_dir, len(saved), len(skipped),
    )
    return {"input_dir": str(batch_dir), "files_received": saved, "skipped": skipped}
