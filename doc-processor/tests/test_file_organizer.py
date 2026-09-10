from pathlib import Path

from app.ingest import process_pdf_file
from app.matching.reference_matcher import match_documents
from app.organizing.categorizer import categorize
from app.organizing.file_organizer import organize_all, sanitize_folder_name
from app.validation.engine import validate_and_score
from tests.fixtures.generate_sample_pdfs import (
    make_bank_debit_note,
    make_corrupt_pdf,
    make_facebook_bill,
    make_vat_invoice,
)


def _run_full_pipeline(docs) -> list:
    sets = match_documents(docs)
    return [categorize(validate_and_score(ds)) for ds in sets]


def test_complete_valid_set_creates_three_files(tmp_path):
    fb = process_pdf_file(make_facebook_bill(tmp_path / "fb.pdf", reference="OKREF001"))
    vat_pdf, vat_xml = tmp_path / "vat.pdf", tmp_path / "vat.xml"
    make_vat_invoice(
        vat_pdf, vat_xml, reference_code="OKREF001", bank_ref_code="FT26205034015973_20260724",
        amount_before_vat="57.579", vat_amount="5.758", total_amount="63.337",
    )
    vat = process_pdf_file(vat_pdf)
    bank = process_pdf_file(make_bank_debit_note(tmp_path / "bank.pdf", reference_code="OKREF001"))

    sets = _run_full_pipeline([fb, vat, bank])
    output_dir = tmp_path / "OUTPUT"
    organize_all(sets, output_dir)

    ref_folder = output_dir / "01_VALID" / "OKREF001"
    assert (ref_folder / "01_Facebook.pdf").exists()
    assert (ref_folder / "02_VAT_Invoice.pdf").exists()
    assert (ref_folder / "02_VAT_Invoice.xml").exists()
    assert (ref_folder / "03_Bank_Debit.pdf").exists()


def test_incomplete_set_writes_missing_marker(tmp_path):
    fb = process_pdf_file(make_facebook_bill(tmp_path / "fb.pdf", reference="INCREF002"))
    vat_pdf, vat_xml = tmp_path / "vat.pdf", tmp_path / "vat.xml"
    # match facebook's default total (63.337) so amount reconciliation
    # doesn't ALSO flag a MISMATCH — this test isolates INCOMPLETE only.
    make_vat_invoice(
        vat_pdf, vat_xml, reference_code="INCREF002",
        amount_before_vat="57.579", vat_amount="5.758", total_amount="63.337",
    )
    vat = process_pdf_file(vat_pdf)

    sets = _run_full_pipeline([fb, vat])
    output_dir = tmp_path / "OUTPUT"
    organize_all(sets, output_dir)

    ref_folder = output_dir / "06_INCOMPLETE_DOCUMENT" / "INCREF002"
    assert (ref_folder / "01_Facebook.pdf").exists()
    assert (ref_folder / "02_VAT_Invoice.pdf").exists()
    assert (ref_folder / "MISSING_03_Bank_Debit.txt").exists()


def test_duplicate_set_keeps_both_copies(tmp_path):
    fb1 = process_pdf_file(make_facebook_bill(tmp_path / "fb1.pdf", reference="DUPREF003"))
    fb2 = process_pdf_file(make_facebook_bill(tmp_path / "fb2.pdf", reference="DUPREF003", total_amount="99.999"))

    sets = _run_full_pipeline([fb1, fb2])
    output_dir = tmp_path / "OUTPUT"
    organize_all(sets, output_dir)

    ref_folder = output_dir / "07_DUPLICATE" / "DUPREF003"
    assert (ref_folder / "01_Facebook.pdf").exists()
    assert (ref_folder / "DUPLICATE_01_Facebook_2.pdf").exists()


def test_error_file_lands_in_other_error_with_reason(tmp_path):
    bad_path = make_corrupt_pdf(tmp_path / "corrupt_invoice.pdf")
    bad_doc = process_pdf_file(bad_path)

    sets = _run_full_pipeline([bad_doc])
    output_dir = tmp_path / "OUTPUT"
    organize_all(sets, output_dir)

    error_dirs = list((output_dir / "08_OTHER_ERROR").glob("*"))
    assert len(error_dirs) == 1
    assert (error_dirs[0] / "corrupt_invoice.pdf").exists()
    assert (error_dirs[0] / "ERROR_REASON.txt").exists()
    assert "corrupt_invoice.pdf" not in Path(bad_path).read_text(errors="ignore")  # sanity: input untouched


def test_rerun_is_idempotent_no_duplicate_files(tmp_path):
    fb = process_pdf_file(make_facebook_bill(tmp_path / "fb.pdf", reference="IDEMREF004"))
    output_dir = tmp_path / "OUTPUT"

    sets1 = _run_full_pipeline([fb])
    organize_all(sets1, output_dir)
    ref_folder = output_dir / "06_INCOMPLETE_DOCUMENT" / "IDEMREF004"
    files_after_first = sorted(p.name for p in ref_folder.iterdir())

    # re-process the same input file (simulating a second run) and organize again
    fb_again = process_pdf_file(tmp_path / "fb.pdf")
    sets2 = _run_full_pipeline([fb_again])
    organize_all(sets2, output_dir)
    files_after_second = sorted(p.name for p in ref_folder.iterdir())

    assert files_after_first == files_after_second
    assert not any("__v2" in f for f in files_after_second)


def test_input_files_never_modified(tmp_path):
    src = make_facebook_bill(tmp_path / "fb.pdf", reference="SAFEREF005")
    original_bytes = Path(src).read_bytes()
    doc = process_pdf_file(src)
    sets = _run_full_pipeline([doc])
    organize_all(sets, tmp_path / "OUTPUT")
    assert Path(src).read_bytes() == original_bytes


def test_sanitize_folder_name_strips_bad_chars():
    assert sanitize_folder_name('A/B\\C:D*E?F"G<H>I|J') == "A_B_C_D_E_F_G_H_I_J"
