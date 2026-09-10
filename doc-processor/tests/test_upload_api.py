import io
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.fixtures.generate_sample_pdfs import make_facebook_bill, make_vat_invoice

client = TestClient(app)


def test_upload_accepts_pdf_and_returns_input_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # uploads_dir in settings.yaml is relative — keep test writes out of the real repo
    pdf_path = make_facebook_bill(tmp_path / "fb.pdf", reference="UPLOADREF1")
    with open(pdf_path, "rb") as f:
        resp = client.post("/api/upload", files=[("files", ("fb.pdf", f, "application/pdf"))])

    assert resp.status_code == 200
    data = resp.json()
    assert data["files_received"] == ["fb.pdf"]
    assert data["skipped"] == []
    assert (Path(data["input_dir"]) / "fb.pdf").exists()


def test_upload_extracts_zip_bundle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf_path = tmp_path / "1_K26TSA_001.pdf"
    xml_path = tmp_path / "1_K26TSA_001.xml"
    make_vat_invoice(pdf_path, xml_path, reference_code="UPLOADZIP1")

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.write(pdf_path, arcname="1_K26TSA_001.pdf")
        zf.write(xml_path, arcname="1_K26TSA_001.xml")
    zip_buffer.seek(0)

    resp = client.post("/api/upload", files=[("files", ("invoice.zip", zip_buffer, "application/zip"))])
    assert resp.status_code == 200
    data = resp.json()
    assert data["files_received"] == ["invoice.zip"]

    extracted_dir = Path(data["input_dir"]) / "invoice"
    assert (extracted_dir / "1_K26TSA_001.pdf").exists()
    assert (extracted_dir / "1_K26TSA_001.xml").exists()


def test_upload_skips_unsupported_extension(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    resp = client.post(
        "/api/upload",
        files=[("files", ("notes.txt", io.BytesIO(b"hello"), "text/plain"))],
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["files_received"] == []
    assert data["skipped"] == ["notes.txt"]


def test_upload_then_process_full_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf_path = make_facebook_bill(tmp_path / "fb.pdf", reference="UPLOADFLOW1")
    with open(pdf_path, "rb") as f:
        upload_resp = client.post("/api/upload", files=[("files", ("fb.pdf", f, "application/pdf"))])
    input_dir = upload_resp.json()["input_dir"]

    process_resp = client.post("/api/process", json={"input_dir": input_dir, "output_dir": str(tmp_path / "OUTPUT")})
    assert process_resp.status_code == 200
    job_id = process_resp.json()["job_id"]

    deadline = time.time() + 15
    job = None
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            break
        time.sleep(0.1)

    assert job["status"] == "done"
    assert job["summary"]["total_files"] == 1
