from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core import job_manager
from app.core.logging_config import get_logger
from app.models.schema import CompletenessStatus, DocumentStatus

log = get_logger("api")
router = APIRouter(prefix="/api")


class ProcessRequest(BaseModel):
    input_dir: str = "INPUT"
    output_dir: str = "OUTPUT"


class ProcessResponse(BaseModel):
    job_id: str


@router.post("/process", response_model=ProcessResponse)
def start_processing(req: ProcessRequest) -> ProcessResponse:
    if not Path(req.input_dir).is_dir():
        raise HTTPException(status_code=400, detail=f"Không tìm thấy thư mục input: {req.input_dir}")
    job = job_manager.create_job(req.input_dir, req.output_dir)
    return ProcessResponse(job_id=job.id)


@router.get("/jobs/{job_id}")
def get_job_status(job_id: str) -> dict:
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    return {
        "job_id": job.id,
        "status": job.status,
        "processed": job.processed,
        "total": job.total,
        "stage": job.stage,
        "error": job.error,
        "output_dir": job.output_dir,
        "summary": job.summary.model_dump() if job.summary else None,
    }


def _row_for(ds) -> dict:
    total_amount = None
    for role in ("vat_invoice", "facebook", "bank_debit"):
        doc = getattr(ds, role, None)
        if doc is not None and doc.total_amount is not None:
            total_amount = float(doc.total_amount)
            break
    return {
        "reference": ds.reference,
        "status": ds.document_status.value if hasattr(ds.document_status, "value") else ds.document_status,
        "completeness": ds.completeness.value if hasattr(ds.completeness, "value") else ds.completeness,
        "category": ds.category,
        "issue": "; ".join(ds.issues) if ds.issues else "-",
        "amount": total_amount,
        "folder": ds.output_folder,
    }


@router.get("/jobs/{job_id}/preview")
def get_preview(job_id: str, errors_only: bool = False) -> list[dict]:
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    sets = job.document_sets
    if errors_only:
        sets = [ds for ds in sets if ds.completeness == CompletenessStatus.ERROR or ds.document_status == DocumentStatus.INVALID]
    return [_row_for(ds) for ds in sets]


def _export_path(job, filename: str) -> Path:
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    if job.status != "done":
        raise HTTPException(status_code=409, detail=f"Job chưa hoàn tất (trạng thái: {job.status})")
    path = Path(job.output_dir) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Không tìm thấy file: {path}")
    return path


@router.get("/jobs/{job_id}/export/misa")
def export_misa(job_id: str) -> FileResponse:
    path = _export_path(job_manager.get_job(job_id), "misa_import.xlsx")
    return FileResponse(path, filename="misa_import.xlsx")


@router.get("/jobs/{job_id}/export/reconciliation")
def export_reconciliation(job_id: str) -> FileResponse:
    path = _export_path(job_manager.get_job(job_id), "reconciliation_report.xlsx")
    return FileResponse(path, filename="reconciliation_report.xlsx")


@router.get("/jobs/{job_id}/export/extracted")
def export_extracted(job_id: str) -> FileResponse:
    path = _export_path(job_manager.get_job(job_id), "extracted_data.xlsx")
    return FileResponse(path, filename="extracted_data.xlsx")


@router.post("/jobs/{job_id}/open-folder")
def open_folder(job_id: str) -> dict:
    """Best-effort: try to open the output folder in the server's own file
    explorer (only meaningful when the tool runs on the user's own
    machine). Always returns the absolute path so the UI can show/copy it
    even when this can't succeed (e.g. running in a remote/headless env)."""
    job = job_manager.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy job")
    abs_path = str(Path(job.output_dir).resolve())
    opened = False
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["explorer", abs_path])
            opened = True
        elif system == "Darwin":
            subprocess.Popen(["open", abs_path])
            opened = True
        else:
            subprocess.Popen(["xdg-open", abs_path])
            opened = True
    except Exception as exc:
        log.info("Không thể tự mở folder (%s) — trả về đường dẫn để UI hiển thị", exc)
    return {"path": abs_path, "opened": opened}
