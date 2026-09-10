from tests.fixtures.generate_sample_pdfs import make_corrupt_pdf, make_facebook_bill, make_scanned_blank_pdf

from app.pdf.reader import PdfReadError, find_sibling_xml, read_pdf


def test_read_pdf_extracts_text(tmp_path):
    path = make_facebook_bill(tmp_path / "fb.pdf")
    content = read_pdf(path)
    assert content.any_text_layer
    assert "Số tham chiếu" in content.full_text


def test_read_pdf_detects_no_text_layer(tmp_path):
    path = make_scanned_blank_pdf(tmp_path / "scan.pdf")
    content = read_pdf(path)
    assert content.any_text_layer is False


def test_read_pdf_raises_on_corrupt_file(tmp_path):
    path = make_corrupt_pdf(tmp_path / "bad.pdf")
    try:
        read_pdf(path)
        assert False, "expected PdfReadError"
    except PdfReadError:
        pass


def test_find_sibling_xml(tmp_path):
    pdf_path = tmp_path / "invoice.pdf"
    xml_path = tmp_path / "invoice.xml"
    pdf_path.write_bytes(b"%PDF-1.4")
    xml_path.write_text("<a/>", encoding="utf-8")
    found = find_sibling_xml(pdf_path)
    assert found == xml_path


def test_find_sibling_xml_missing(tmp_path):
    pdf_path = tmp_path / "invoice2.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    assert find_sibling_xml(pdf_path) is None
