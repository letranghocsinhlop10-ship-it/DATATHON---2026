"""Zip auto-extraction.

Vietnamese e-invoices are frequently delivered zipped (PDF + XML
sidecar together, as seen in real bank e-invoice exports). Rather than
asking users to unzip manually before dropping files into INPUT/, the
tool extracts any .zip it finds — whether it's sitting in a local
INPUT/ folder or came from a browser upload.

Extraction is flat (each zip's own file entries go straight into a
`<zip_stem>/` sibling folder, ignoring the zip's internal directory
structure) and idempotent (skipped if that folder already exists), so
re-running the tool doesn't re-extract or duplicate anything.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from app.core.logging_config import get_logger

log = get_logger("zip_utils")

# Only these extensions come out of a zip — anything else (readme, images,
# signature blobs, ...) is skipped rather than dumped into INPUT/.
_ALLOWED_EXTRACT_SUFFIXES = {".pdf", ".xml"}


def extract_zip_flat(zip_path: str | Path, dest_dir: str | Path) -> list[Path]:
    """Extract the .pdf/.xml entries of one zip file into dest_dir (created
    if needed), flattening any internal folder structure. Returns the list
    of extracted file paths. Never raises for a corrupt/unsupported zip —
    logs a warning and returns an empty list instead (a bad zip must not
    crash the batch, same principle as a bad PDF)."""
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir)
    extracted: list[Path] = []
    try:
        with zipfile.ZipFile(zip_path) as zf:
            dest_dir.mkdir(parents=True, exist_ok=True)
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = Path(info.filename).name  # flatten: drop any internal path
                if not name or Path(name).suffix.lower() not in _ALLOWED_EXTRACT_SUFFIXES:
                    continue
                target = dest_dir / name
                if target.exists():
                    log.info("Bỏ qua entry trùng tên khi giải nén %s: %s đã tồn tại", zip_path, target)
                    continue
                with zf.open(info) as src, open(target, "wb") as out:
                    out.write(src.read())
                extracted.append(target)
    except (zipfile.BadZipFile, OSError) as exc:
        log.warning("Không giải nén được %s: %s", zip_path, exc)
        return []
    log.info("Đã giải nén %s -> %s (%d file)", zip_path, dest_dir, len(extracted))
    return extracted


def extract_zips_in_place(root_dir: str | Path) -> int:
    """Recursively finds every .zip under root_dir and extracts each one
    (once — skipped on subsequent calls/reruns) into a sibling folder
    named after the zip's stem. Returns how many zips were newly
    extracted this call."""
    root_dir = Path(root_dir)
    if not root_dir.is_dir():
        return 0

    newly_extracted = 0
    for zip_path in sorted(root_dir.rglob("*.zip")):
        dest_dir = zip_path.parent / zip_path.stem
        if dest_dir.exists():
            continue  # already extracted in a previous run
        if extract_zip_flat(zip_path, dest_dir):
            newly_extracted += 1
    return newly_extracted
