"""File Organizer stage.

Physically lays out OUTPUT/<category>/<reference>/ per spec section 6.
Hard safety rules (spec section 13):
- INPUT is only ever read/copied from, never modified or moved.
- Re-running the tool must not duplicate files/folders — tracked via a
  small JSON manifest (OUTPUT/.manifest/state.json) keyed by source file
  hash + destination.
- Nothing is auto-deleted. If a set's category changes between runs
  (e.g. a missing file was added), the stale old folder is marked with
  a `.stale` file and logged — actual deletion needs a human/CLI flag.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

from app.core.logging_config import get_logger
from app.models.schema import DocumentSet, ExtractedDocument
from app.pdf.reader import sha256_of_file

log = get_logger("organizer")

_SLOTS: list[tuple[str, str, str]] = [
    # (attribute on DocumentSet, filename prefix, human label)
    ("facebook", "01", "Facebook"),
    ("vat_invoice", "02", "VAT_Invoice"),
    ("bank_debit", "03", "Bank_Debit"),
]


def sanitize_folder_name(name: str) -> str:
    bad = '<>:"/\\|?*'
    cleaned = "".join("_" if ch in bad else ch for ch in name).strip().strip(".")
    return cleaned or "UNKNOWN"


class Manifest:
    """Tiny idempotency ledger. Not a database — a demo-scale JSON file is
    plenty for the expected batch sizes, and it's trivially inspectable."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict = {"copied": [], "reference_categories": {}}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Không đọc được manifest %s (%s) — bắt đầu manifest mới", path, exc)
        self.data.setdefault("copied", [])
        self.data.setdefault("reference_categories", {})
        self._copied_set: set[str] = set(self.data["copied"])

    def already_copied(self, file_hash: str, dest_path: Path) -> bool:
        return f"{file_hash}:{dest_path}" in self._copied_set

    def mark_copied(self, file_hash: str, dest_path: Path) -> None:
        key = f"{file_hash}:{dest_path}"
        self._copied_set.add(key)
        self.data["copied"] = sorted(self._copied_set)

    def category_for(self, reference: str) -> Optional[str]:
        return self.data["reference_categories"].get(reference)

    def set_category_for(self, reference: str, category: str) -> None:
        self.data["reference_categories"][reference] = category

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def _safe_copy(src: str, dest: Path, manifest: Manifest, file_hash: Optional[str]) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if file_hash and manifest.already_copied(file_hash, dest):
        return  # already placed here in a previous run — never re-copy/overwrite
    if dest.exists():
        # Something else occupies this exact path without a matching
        # manifest entry — don't silently clobber it; version instead.
        n = 2
        candidate = dest
        while candidate.exists():
            candidate = dest.with_name(f"{dest.stem}__v{n}{dest.suffix}")
            n += 1
        dest = candidate
        log.warning("Đích đã tồn tại ngoài manifest, ghi vào bản thay thế: %s", dest)
    shutil.copy2(src, dest)
    if file_hash:
        manifest.mark_copied(file_hash, dest)
    log.info("Đã copy %s -> %s", src, dest)


def _write_missing_marker(dest_folder: Path, prefix: str, label: str) -> None:
    marker = dest_folder / f"MISSING_{prefix}_{label}.txt"
    if not marker.exists():
        marker.write_text(
            f"Thiếu chứng từ: {label}\n"
            f"Bộ chứng từ này chưa có file {label} tương ứng.\n",
            encoding="utf-8",
        )


def _copy_doc(doc: ExtractedDocument, dest_folder: Path, filename_stem: str, manifest: Manifest) -> None:
    _safe_copy(doc.source_file, dest_folder / f"{filename_stem}.pdf", manifest, doc.file_hash)
    if doc.used_xml_sidecar and doc.xml_sidecar_path:
        try:
            xml_hash = sha256_of_file(doc.xml_sidecar_path)
        except OSError as exc:
            log.warning("Không hash được XML sidecar %s (%s) — vẫn copy nhưng mất idempotency", doc.xml_sidecar_path, exc)
            xml_hash = None
        _safe_copy(doc.xml_sidecar_path, dest_folder / f"{filename_stem}.xml", manifest, xml_hash)


def organize_document_set(ds: DocumentSet, output_dir: Path, manifest: Manifest) -> Path:
    safe_ref = sanitize_folder_name(ds.reference)
    category = ds.category or "08_OTHER_ERROR"
    dest_folder = output_dir / category / safe_ref
    ds.output_folder = str(dest_folder)

    prev_category = manifest.category_for(ds.reference)
    if prev_category and prev_category != category:
        stale_folder = output_dir / prev_category / safe_ref
        if stale_folder.exists():
            (stale_folder / ".stale").write_text(
                f"Bộ chứng từ này đã chuyển sang category '{category}' ở lần chạy sau.\n"
                f"Thư mục này KHÔNG bị xoá tự động — cần xác nhận thủ công để dọn dẹp.\n",
                encoding="utf-8",
            )
            log.warning("Category đổi cho %s: %s -> %s (đã đánh dấu .stale, không xoá)", ds.reference, prev_category, category)
    manifest.set_category_for(ds.reference, category)

    # ERROR sets: just drop the offending file(s) + reason, no 3-slot layout.
    if ds.error_files:
        dest_folder.mkdir(parents=True, exist_ok=True)
        for doc in ds.error_files:
            src_name = Path(doc.source_file).name
            _safe_copy(doc.source_file, dest_folder / src_name, manifest, doc.file_hash)
            (dest_folder / "ERROR_REASON.txt").write_text(
                f"File: {doc.source_file}\nLý do lỗi: {doc.error_reason or 'Không xác định'}\n",
                encoding="utf-8",
            )
        return dest_folder

    for attr, prefix, label in _SLOTS:
        doc: Optional[ExtractedDocument] = getattr(ds, attr)
        if doc is not None:
            _copy_doc(doc, dest_folder, f"{prefix}_{label}", manifest)
        else:
            dest_folder.mkdir(parents=True, exist_ok=True)
            _write_missing_marker(dest_folder, prefix, label)

        for n, dup in enumerate(getattr(ds, f"duplicate_{attr}"), start=2):
            _copy_doc(dup, dest_folder, f"DUPLICATE_{prefix}_{label}_{n}", manifest)

    return dest_folder


def organize_all(document_sets: list[DocumentSet], output_dir: str | Path) -> None:
    output_dir = Path(output_dir)
    manifest_path = output_dir / ".manifest" / "state.json"
    manifest = Manifest(manifest_path)

    for ds in document_sets:
        try:
            organize_document_set(ds, output_dir, manifest)
        except Exception:  # pragma: no cover - defensive; one bad set shouldn't kill the batch
            log.exception("Lỗi khi tạo thư mục output cho reference=%s", ds.reference)

    manifest.save()
