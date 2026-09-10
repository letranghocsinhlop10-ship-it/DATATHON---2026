"""End-to-end tests: a realistic mixed batch (valid / incomplete /
duplicate / error / amount-mismatch / missing-tax-code sets processed
together) run through the full `run_pipeline` orchestrator."""
from openpyxl import load_workbook

from app.pipeline import run_pipeline
from tests.fixtures.generate_sample_pdfs import (
    make_bank_debit_note,
    make_corrupt_pdf,
    make_facebook_bill,
    make_scanned_blank_pdf,
    make_vat_invoice,
)


def _setup_mixed_batch(tmp_path):
    input_dir = tmp_path / "INPUT"
    fb_dir, vat_dir, bank_dir = input_dir / "facebook", input_dir / "vat", input_dir / "bank"
    for d in (fb_dir, vat_dir, bank_dir):
        d.mkdir(parents=True)

    # NOTE: each set below is given its own unique bank FT-style code
    # (both for the VAT invoice's bank_ref_code and the bank debit note's
    # transaction_code) — those are exact-match candidate keys for the
    # reference matcher, and real bank transaction codes are always
    # unique, so reusing the fixture defaults across sets here would
    # wrongly merge otherwise-independent sets.

    # 1. A fully valid, complete set.
    make_facebook_bill(fb_dir / "valid_fb.pdf", reference="VALIDSET1", buyer_tax_id="0110382640")
    make_vat_invoice(
        vat_dir / "valid_vat.pdf", vat_dir / "valid_vat.xml", reference_code="VALIDSET1",
        bank_ref_code="FT10000000000001_20260701",
        amount_before_vat="57.579", vat_amount="5.758", total_amount="63.337", buyer_tax_code="0110382640",
    )
    make_bank_debit_note(bank_dir / "valid_bank.pdf", reference_code="VALIDSET1", transaction_code="FT20000000000001")

    # 2. Incomplete: missing the bank debit note.
    make_facebook_bill(fb_dir / "inc_fb.pdf", reference="INCSET2")
    make_vat_invoice(
        vat_dir / "inc_vat.pdf", vat_dir / "inc_vat.xml", reference_code="INCSET2",
        bank_ref_code="FT10000000000002_20260701",
        amount_before_vat="57.579", vat_amount="5.758", total_amount="63.337",
    )

    # 3. Duplicate: two Facebook bills claim the same reference.
    make_facebook_bill(fb_dir / "dup_fb_1.pdf", reference="DUPSET3")
    make_facebook_bill(fb_dir / "dup_fb_2.pdf", reference="DUPSET3", total_amount="1.000")

    # 4. Amount mismatch: complete set but bank amount is way off.
    make_facebook_bill(fb_dir / "mismatch_fb.pdf", reference="MISMATCHSET4", buyer_tax_id="0110382640")
    make_vat_invoice(
        vat_dir / "mismatch_vat.pdf", vat_dir / "mismatch_vat.xml", reference_code="MISMATCHSET4",
        bank_ref_code="FT10000000000004_20260701",
        amount_before_vat="57.579", vat_amount="5.758", total_amount="63.337", buyer_tax_code="0110382640",
    )
    make_bank_debit_note(
        bank_dir / "mismatch_bank.pdf", reference_code="MISMATCHSET4", amount="999,999,999",
        transaction_code="FT20000000000004",
    )

    # 5. Unreadable file -> ERROR bucket, must not crash the batch.
    make_corrupt_pdf(bank_dir / "corrupt.pdf")

    # 6. Scanned/no-text-layer file with no OCR available -> also ERROR,
    #    must not crash the batch either.
    make_scanned_blank_pdf(fb_dir / "scanned_blank.pdf")

    return input_dir


def test_mixed_batch_end_to_end(tmp_path):
    input_dir = _setup_mixed_batch(tmp_path)
    output_dir = tmp_path / "OUTPUT"

    seen_progress = []
    document_sets, summary = run_pipeline(
        input_dir, output_dir, progress_cb=lambda done, total, stage: seen_progress.append((done, total, stage))
    )

    assert seen_progress, "progress callback should have fired at least once"
    assert seen_progress[-1][0] == seen_progress[-1][1]  # finishes at done == total

    # facebook/: valid_fb, inc_fb, dup_fb_1, dup_fb_2, mismatch_fb, scanned_blank = 6
    # vat/: valid_vat, inc_vat, mismatch_vat = 3 (sidecar .xml files aren't counted)
    # bank/: valid_bank, mismatch_bank, corrupt = 3
    assert summary.total_files == 12
    assert summary.complete_sets == 2  # VALIDSET1 + MISMATCHSET4 (3 docs each)
    assert summary.incomplete_sets == 1  # INCSET2
    assert summary.valid_sets == 1  # only VALIDSET1 is fully clean
    assert summary.duplicate_sets == 1  # DUPSET3
    assert summary.error_files == 2  # corrupt.pdf + scanned_blank.pdf

    by_ref = {ds.reference: ds for ds in document_sets if not ds.reference.startswith(("ERROR__", "NOREF__"))}
    assert by_ref["VALIDSET1"].category == "01_VALID"
    assert by_ref["INCSET2"].category == "06_INCOMPLETE_DOCUMENT"
    assert by_ref["DUPSET3"].category == "07_DUPLICATE"
    assert by_ref["MISMATCHSET4"].category == "05_AMOUNT_MISMATCH"

    # folder layout sanity checks
    assert (output_dir / "01_VALID" / "VALIDSET1" / "01_Facebook.pdf").exists()
    assert (output_dir / "01_VALID" / "VALIDSET1" / "02_VAT_Invoice.pdf").exists()
    assert (output_dir / "01_VALID" / "VALIDSET1" / "03_Bank_Debit.pdf").exists()
    assert (output_dir / "06_INCOMPLETE_DOCUMENT" / "INCSET2" / "MISSING_03_Bank_Debit.txt").exists()
    assert (output_dir / "07_DUPLICATE" / "DUPSET3" / "DUPLICATE_01_Facebook_2.pdf").exists()
    error_dirs = list((output_dir / "08_OTHER_ERROR").glob("*"))
    assert len(error_dirs) == 2
    for d in error_dirs:
        assert (d / "ERROR_REASON.txt").exists()

    # Excel outputs exist and carry every set (rows = number of DocumentSets)
    assert (output_dir / "misa_import.xlsx").exists()
    assert (output_dir / "reconciliation_report.xlsx").exists()
    wb = load_workbook(output_dir / "reconciliation_report.xlsx")
    all_sets_rows = list(wb["All Sets"].iter_rows(min_row=2))
    assert len(all_sets_rows) == len(document_sets)


def test_rerunning_full_pipeline_is_idempotent(tmp_path):
    input_dir = _setup_mixed_batch(tmp_path)
    output_dir = tmp_path / "OUTPUT"

    run_pipeline(input_dir, output_dir)
    first_run_files = sorted(str(p.relative_to(output_dir)) for p in output_dir.rglob("*") if p.is_file())

    run_pipeline(input_dir, output_dir)
    second_run_files = sorted(str(p.relative_to(output_dir)) for p in output_dir.rglob("*") if p.is_file())

    assert first_run_files == second_run_files
    assert not any("__v2" in f for f in second_run_files)


def test_unexpected_exception_on_one_file_does_not_crash_the_batch(tmp_path, monkeypatch):
    """Simulates a bug/edge-case slipping past process_pdf_file's own
    try/except (e.g. a bad config) — the pipeline-level safety net must
    still turn that into one ERROR set instead of raising."""
    import app.pipeline as pipeline_module

    input_dir = tmp_path / "INPUT" / "facebook"
    input_dir.mkdir(parents=True)
    make_facebook_bill(input_dir / "ok1.pdf", reference="SAFEA")
    boom_path = make_facebook_bill(input_dir / "boom.pdf", reference="SAFEB")
    make_facebook_bill(input_dir / "ok2.pdf", reference="SAFEC")

    real_process = pipeline_module.process_pdf_file

    def flaky_process(path, role=None):
        if str(path) == str(boom_path):
            raise RuntimeError("simulated unexpected crash")
        return real_process(path, role)

    monkeypatch.setattr(pipeline_module, "process_pdf_file", flaky_process)

    document_sets, summary = run_pipeline(input_dir.parent, tmp_path / "OUTPUT")

    assert summary.total_files == 3
    assert summary.error_files == 1
    error_sets = [ds for ds in document_sets if ds.reference.startswith("ERROR__")]
    assert len(error_sets) == 1
    assert "simulated unexpected crash" in error_sets[0].error_files[0].error_reason
