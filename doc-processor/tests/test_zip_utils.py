import zipfile
from pathlib import Path

from app.ingest import discover_pdf_files, process_pdf_file
from app.zip_utils import extract_zip_flat, extract_zips_in_place
from tests.fixtures.generate_sample_pdfs import make_vat_invoice


def _make_invoice_zip(dest_dir, src_root, zip_name="invoice_bundle.zip", reference="ZIPREF001"):
    """Builds a zip in `dest_dir` from source files staged under
    `src_root` (kept OUTSIDE dest_dir so discover_pdf_files scans on
    dest_dir don't also pick up the un-zipped staging copies)."""
    pdf_path = src_root / "1_K26TSA_001.pdf"
    xml_path = src_root / "1_K26TSA_001.xml"
    src_root.mkdir(parents=True, exist_ok=True)
    make_vat_invoice(pdf_path, xml_path, reference_code=reference)

    zip_path = dest_dir / zip_name
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(pdf_path, arcname="1_K26TSA_001.pdf")
        zf.write(xml_path, arcname="1_K26TSA_001.xml")
        zf.writestr("nested/readme.txt", "should be ignored")  # non pdf/xml, nested path
    return zip_path


def test_extract_zip_flat_extracts_pdf_and_xml_and_skips_other_files(tmp_path):
    zip_path = _make_invoice_zip(tmp_path, tmp_path / "_src")
    dest = tmp_path / "extracted"

    extracted = extract_zip_flat(zip_path, dest)

    names = sorted(p.name for p in extracted)
    assert names == ["1_K26TSA_001.pdf", "1_K26TSA_001.xml"]
    assert not (dest / "nested").exists()
    assert not (dest / "readme.txt").exists()


def test_extract_zip_flat_handles_corrupt_zip_gracefully(tmp_path):
    bad_zip = tmp_path / "bad.zip"
    bad_zip.write_bytes(b"not actually a zip file")
    extracted = extract_zip_flat(bad_zip, tmp_path / "out")
    assert extracted == []


def test_extract_zips_in_place_is_idempotent(tmp_path):
    input_dir = tmp_path / "INPUT" / "vat"
    input_dir.mkdir(parents=True)
    _make_invoice_zip(input_dir, tmp_path / "_src", reference="ZIPREF002")

    n1 = extract_zips_in_place(tmp_path / "INPUT")
    assert n1 == 1
    extracted_dir = input_dir / "invoice_bundle"
    assert (extracted_dir / "1_K26TSA_001.pdf").exists()
    assert (extracted_dir / "1_K26TSA_001.xml").exists()

    n2 = extract_zips_in_place(tmp_path / "INPUT")
    assert n2 == 0  # already extracted — not re-done


def test_discover_pdf_files_finds_pdfs_extracted_from_zip(tmp_path):
    input_dir = tmp_path / "INPUT"
    vat_dir = input_dir / "vat"
    vat_dir.mkdir(parents=True)
    _make_invoice_zip(vat_dir, tmp_path / "_src", reference="ZIPREF003")

    extract_zips_in_place(input_dir)
    files = discover_pdf_files(input_dir)

    assert len(files) == 1
    path, role = files[0]
    assert path.endswith("1_K26TSA_001.pdf")
    assert role == "vat"

    doc = process_pdf_file(path, role)
    assert not doc.is_error
    assert doc.used_xml_sidecar is True
    assert "ZIPREF003" in doc.reference_candidates


def test_nested_uppercase_zip_and_pdf_are_discovered(tmp_path):
    input_dir = tmp_path / "messy"
    input_dir.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    pdf = staging / "INVOICE.PDF"
    make_vat_invoice(pdf, staging / "INVOICE.xml", reference_code="NESTED001")

    inner_zip = staging / "INNER.ZIP"
    with zipfile.ZipFile(inner_zip, "w") as zf:
        zf.write(pdf, arcname="deep/random/INVOICE.PDF")
    outer_zip = input_dir / "OUTER.ZIP"
    with zipfile.ZipFile(outer_zip, "w") as zf:
        zf.write(inner_zip, arcname="unhelpful/folder/INNER.ZIP")

    assert extract_zips_in_place(input_dir) == 2
    files = discover_pdf_files(input_dir)
    assert len(files) == 1
    assert Path(files[0][0]).name == "INVOICE.PDF"


def test_zip_keeps_distinct_files_with_same_basename(tmp_path):
    zip_path = tmp_path / "duplicates.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("a/document.pdf", b"first")
        zf.writestr("b/document.pdf", b"second")

    dest = tmp_path / "out"
    extracted = extract_zip_flat(zip_path, dest)
    assert sorted(p.name for p in extracted) == ["document.pdf", "document__2.pdf"]
    assert extract_zip_flat(zip_path, dest) == []  # rerun stays idempotent
