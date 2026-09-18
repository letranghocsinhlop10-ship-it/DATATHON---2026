"""Zip auto-extraction.

Vietnamese e-invoices are frequently delivered zipped (PDF + XML
sidecar together, as seen in real bank e-invoice exports). Rather than
asking users to unzip manually before dropping files into INPUT/, the
tool extracts any .zip it finds — whether it's sitting in a local
INPUT/ folder or came from a browser upload.

Extraction is flat (each zip's own file entries go straight into a
`<zip_stem>/` sibling folder, ignoring the zip's internal directory
structure), recursive (nested zip files are unpacked too), and idempotent.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from app.core.logging_config import get_logger

log = get_logger("zip_utils")

# Only these extensions come out of a zip — anything else (readme, images,
# signature blobs, ...) is skipped rather than dumped into INPUT/.
_ALLOWED_EXTRACT_SUFFIXES = {".pdf", ".xml", ".zip"}


def _same_bytes(path: Path, content: bytes) -> bool:
    try:
        return path.read_bytes() == content
    except OSError:
        return False


def _unique_target(dest_dir: Path, filename: str, content: bytes) -> tuple[Path, bool]:
    """Return a collision-safe destination and whether it already exists
    with identical content. Distinct files with the same basename are kept
    as ``name__2.pdf``, while reruns do not create endless copies."""
    original = dest_dir / filename
    candidate = original
    n = 2
    while candidate.exists():
        if _same_bytes(candidate, content):
            return candidate, True
        candidate = original.with_name(f"{original.stem}__{n}{original.suffix}")
        n += 1
    return candidate, False


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
                with zf.open(info) as src:
                    content = src.read()
                target, already_present = _unique_target(dest_dir, name, content)
                if already_present:
                    continue
                with open(target, "wb") as out:
                    out.write(content)
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
    processed: set[Path] = set()
    while True:
        # Case-insensitive suffix handling matters when batches originate on
        # Windows and contain names such as INVOICE.ZIP.
        zip_paths = sorted(
            p for p in root_dir.rglob("*")
            if p.is_file() and p.suffix.lower() == ".zip" and p not in processed
        )
        if not zip_paths:
            break
        for zip_path in zip_paths:
            processed.add(zip_path)
            dest_dir = zip_path.parent / zip_path.stem
            if extract_zip_flat(zip_path, dest_dir):
                newly_extracted += 1
    return newly_extracted
