from app.ingest import process_pdf_file
from app.matching.reference_matcher import match_documents
from app.models.schema import CompletenessStatus, DocType, ExtractedDocument
from tests.fixtures.generate_sample_pdfs import (
    make_bank_debit_note,
    make_corrupt_pdf,
    make_facebook_bill,
    make_vat_invoice,
)


def _process_set(tmp_path, ref="76NQZZMDK2", bank_ref="76NQZZMDK2", suffix="", bank_txn_code="FT26205136372705"):
    fb = process_pdf_file(make_facebook_bill(tmp_path / f"fb{suffix}.pdf", reference=ref))
    pdf_p = tmp_path / f"vat{suffix}.pdf"
    xml_p = tmp_path / f"vat{suffix}.xml"
    make_vat_invoice(pdf_p, xml_p, reference_code=ref, bank_ref_code=f"FT26205034015973_2026072{suffix or 4}")
    vat = process_pdf_file(pdf_p)
    bank = process_pdf_file(
        make_bank_debit_note(tmp_path / f"bank{suffix}.pdf", reference_code=bank_ref, transaction_code=bank_txn_code)
    )
    return fb, vat, bank


def test_complete_set_groups_correctly(tmp_path):
    fb, vat, bank = _process_set(tmp_path)
    sets = match_documents([fb, vat, bank])

    assert len(sets) == 1
    ds = sets[0]
    assert ds.completeness == CompletenessStatus.COMPLETE
    assert ds.facebook is not None
    assert ds.vat_invoice is not None
    assert ds.bank_debit is not None
    assert ds.reference == "76NQZZMDK2"


def test_incomplete_set_missing_one_doc(tmp_path):
    fb, vat, _bank = _process_set(tmp_path)
    sets = match_documents([fb, vat])

    assert len(sets) == 1
    ds = sets[0]
    assert ds.completeness == CompletenessStatus.INCOMPLETE
    assert ds.bank_debit is None
    assert "INCOMPLETE" in ds.issues


def test_duplicate_detected_for_same_role_same_reference(tmp_path):
    fb1 = process_pdf_file(make_facebook_bill(tmp_path / "fb1.pdf", reference="DUPREF001"))
    fb2 = process_pdf_file(make_facebook_bill(tmp_path / "fb2.pdf", reference="DUPREF001"))
    sets = match_documents([fb1, fb2])

    assert len(sets) == 1
    ds = sets[0]
    assert ds.completeness == CompletenessStatus.DUPLICATE
    assert len(ds.duplicate_facebook) == 1
    assert "DUPLICATE" in ds.issues


def test_two_independent_references_stay_separate(tmp_path):
    fb1, vat1, bank1 = _process_set(
        tmp_path, ref="REFONE0001", bank_ref="REFONE0001", suffix="1", bank_txn_code="FT11111111111"
    )
    fb2, vat2, bank2 = _process_set(
        tmp_path, ref="REFTWO0002", bank_ref="REFTWO0002", suffix="2", bank_txn_code="FT22222222222"
    )
    sets = match_documents([fb1, vat1, bank1, fb2, vat2, bank2])

    refs = {s.reference for s in sets}
    assert refs == {"REFONE0001", "REFTWO0002"}
    assert all(s.completeness == CompletenessStatus.COMPLETE for s in sets)


def test_error_file_gets_its_own_set(tmp_path):
    bad = process_pdf_file(make_corrupt_pdf(tmp_path / "bad.pdf"))
    fb, vat, bank = _process_set(tmp_path)
    sets = match_documents([bad, fb, vat, bank])

    error_sets = [s for s in sets if s.completeness == CompletenessStatus.ERROR]
    assert len(error_sets) == 1
    assert error_sets[0].error_files[0].source_file.endswith("bad.pdf")
    # the good set must be unaffected by the bad file
    good_sets = [s for s in sets if s.completeness == CompletenessStatus.COMPLETE]
    assert len(good_sets) == 1


def test_missing_reference_document_isolated():
    doc = ExtractedDocument(doc_type=DocType.FACEBOOK, source_file="/tmp/no_ref.pdf", reference_candidates=[])
    sets = match_documents([doc])

    assert len(sets) == 1
    assert sets[0].completeness == CompletenessStatus.INCOMPLETE
    assert "MISSING_REFERENCE" in sets[0].issues


def test_fuzzy_match_links_near_identical_reference_strings():
    doc_a = ExtractedDocument(
        doc_type=DocType.FACEBOOK, source_file="/tmp/a.pdf", reference_candidates=["76NQZZMDK2"]
    )
    # simulates a minor OCR misread of the same code (1 char swapped)
    doc_b = ExtractedDocument(
        doc_type=DocType.BANK_DEBIT, source_file="/tmp/b.pdf", reference_candidates=["76NQZZMDKZ"]
    )
    sets = match_documents([doc_a, doc_b])
    assert len(sets) == 1
    assert sets[0].facebook is not None and sets[0].bank_debit is not None
