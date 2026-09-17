"""Test tuỳ chọn chạy trên PDF THẬT.

Kho mã này là repo công khai nên không chứa chứng từ thật. Đặt biến môi
trường ``ACCOUNTING_SAMPLE_DIR`` trỏ tới thư mục chứa PDF thật để chạy:

    ACCOUNTING_SAMPLE_DIR=C:\\KETOAN\\MAU  pytest tests/test_real_samples.py

Không đặt biến -> toàn bộ test trong file này được bỏ qua.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.document_classifier import DocumentClassifier
from app.core.pdf_reader import PDFReader
from app.extractors.rule_engine import ExtractionContext
from app.models.enums import DocumentType, TextSource
from app.utils.file_utils import iter_pdf_files

SAMPLE_DIR = os.environ.get("ACCOUNTING_SAMPLE_DIR")

pytestmark = pytest.mark.skipif(
    not SAMPLE_DIR, reason="Chưa đặt ACCOUNTING_SAMPLE_DIR — bỏ qua test trên PDF thật"
)


@pytest.fixture(scope="module")
def processed(classifier_config, extraction_config, app_settings, registry):
    """Đọc, phân loại và trích xuất toàn bộ PDF trong thư mục mẫu."""
    reader = PDFReader(
        min_chars_per_page=app_settings.min_chars_per_page,
        labels_to_locate=extraction_config.all_labels,
    )
    classifier = DocumentClassifier(classifier_config)
    results = []
    for path in iter_pdf_files(Path(SAMPLE_DIR)):
        content = reader.read(path)
        classification = classifier.classify(content.flat)
        extractor = registry.get(classification.document_type)
        fields = None
        if extractor is not None:
            fields = extractor.extract(
                ExtractionContext(
                    content=content,
                    document_type=classification.document_type,
                    money_format=extraction_config.money_format_for(
                        classification.document_type
                    ),
                    reference_pattern=app_settings.reference_pattern,
                    strip_inner_whitespace=app_settings.strip_inner_whitespace,
                )
            )
        results.append((path, content, classification, fields, extractor))
    return results


def test_co_file_de_kiem_tra(processed):
    assert processed, f"Không tìm thấy PDF nào trong {SAMPLE_DIR}"


def test_khong_file_nao_bi_phan_loai_unknown(processed):
    unknown = [p.name for p, _, c, _, _ in processed if c.document_type is DocumentType.UNKNOWN]
    assert not unknown, f"Các file chưa phân loại được: {unknown}"


def test_khong_file_nao_can_ocr(processed):
    need_ocr = [p.name for p, c, _, _, _ in processed if c.text_source is not TextSource.TEXT_LAYER]
    assert not need_ocr, f"Các file thiếu lớp text: {need_ocr}"


def test_khong_thieu_truong_bat_buoc(processed):
    problems = {
        path.name: extractor.missing_required(fields)
        for path, _, _, fields, extractor in processed
        if fields is not None and extractor.missing_required(fields)
    }
    assert not problems, f"Thiếu trường bắt buộc: {problems}"


def test_moi_chung_tu_deu_co_khoa_ghep(processed):
    missing_key = []
    for path, _, classification, fields, _ in processed:
        if fields is None:
            continue
        if classification.document_type is DocumentType.META_INVOICE:
            key = fields.value("reference_number")
        else:
            key = fields.value("meta_reference")
        if not key:
            missing_key.append(path.name)
    assert not missing_key, f"Không đọc được khoá ghép: {missing_key}"
