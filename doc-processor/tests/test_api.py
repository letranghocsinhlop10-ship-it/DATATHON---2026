import time

from fastapi.testclient import TestClient

from app.main import app
from tests.fixtures.generate_sample_pdfs import make_bank_debit_note, make_facebook_bill, make_vat_invoice

client = TestClient(app)


def _wait_for_job(job_id: str, timeout: float = 15.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200
        data = resp.json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.1)
    raise TimeoutError("job did not finish in time")


def _make_input_tree(tmp_path):
    (tmp_path / "INPUT" / "facebook").mkdir(parents=True)
    (tmp_path / "INPUT" / "vat").mkdir(parents=True)
    (tmp_path / "INPUT" / "bank").mkdir(parents=True)

    make_facebook_bill(tmp_path / "INPUT" / "facebook" / "fb.pdf", reference="APIREF001", buyer_tax_id="0110382640")
    vat_pdf = tmp_path / "INPUT" / "vat" / "vat.pdf"
    vat_xml = tmp_path / "INPUT" / "vat" / "vat.xml"
    make_vat_invoice(
        vat_pdf, vat_xml, reference_code="APIREF001",
        amount_before_vat="57.579", vat_amount="5.758", total_amount="63.337",
    )
    make_bank_debit_note(tmp_path / "INPUT" / "bank" / "bank.pdf", reference_code="APIREF001")


def test_index_page_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Process Documents" in resp.text or "processBtn" in resp.text


def test_full_process_flow_via_api(tmp_path):
    _make_input_tree(tmp_path)
    input_dir = str(tmp_path / "INPUT")
    output_dir = str(tmp_path / "OUTPUT")

    resp = client.post("/api/process", json={"input_dir": input_dir, "output_dir": output_dir})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    job = _wait_for_job(job_id)
    assert job["status"] == "done"
    assert job["summary"]["total_files"] == 3
    assert job["summary"]["complete_sets"] == 1
    assert job["summary"]["valid_sets"] == 1

    preview = client.get(f"/api/jobs/{job_id}/preview").json()
    assert len(preview) == 1
    assert preview[0]["reference"] == "APIREF001"

    misa_resp = client.get(f"/api/jobs/{job_id}/export/misa")
    assert misa_resp.status_code == 200
    assert misa_resp.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml"
    )

    recon_resp = client.get(f"/api/jobs/{job_id}/export/reconciliation")
    assert recon_resp.status_code == 200


def test_process_rejects_missing_input_dir(tmp_path):
    resp = client.post("/api/process", json={"input_dir": str(tmp_path / "does_not_exist"), "output_dir": str(tmp_path / "OUTPUT")})
    assert resp.status_code == 400


def test_unknown_job_returns_404():
    resp = client.get("/api/jobs/nonexistent-id")
    assert resp.status_code == 404


def test_errors_only_preview_filters_correctly(tmp_path):
    (tmp_path / "INPUT" / "facebook").mkdir(parents=True)
    make_facebook_bill(tmp_path / "INPUT" / "facebook" / "fb_ok.pdf", reference="OKREF900")
    (tmp_path / "INPUT" / "bank").mkdir(parents=True)
    (tmp_path / "INPUT" / "bank" / "corrupt.pdf").write_bytes(b"%PDF-1.4 not really a pdf")

    input_dir = str(tmp_path / "INPUT")
    output_dir = str(tmp_path / "OUTPUT")
    resp = client.post("/api/process", json={"input_dir": input_dir, "output_dir": output_dir})
    job_id = resp.json()["job_id"]
    job = _wait_for_job(job_id)
    assert job["status"] == "done"

    # "errors_only" surfaces every set needing attention: hard read/parse
    # errors AND sets that failed validation (e.g. incomplete) — not just
    # the strict ERROR completeness bucket.
    errors_only = client.get(f"/api/jobs/{job_id}/preview?errors_only=true").json()
    assert len(errors_only) == 2
    completeness_values = {row["completeness"] for row in errors_only}
    assert completeness_values == {"ERROR", "INCOMPLETE"}
