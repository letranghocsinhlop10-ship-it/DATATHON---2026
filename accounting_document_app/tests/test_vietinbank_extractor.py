"""Test classify + extract cho VIETINBANK_DEBIT_ADVICE.

Dùng ``make_content``/``make_context`` (text thuần, không cần PDF thật) —
đủ để kiểm tra logic regex/classify, không phải hành vi copy file vật lý
(xem ``tests/test_debit_advice_splitter.py`` cho phần đó).

LƯU Ý: dự án chưa có file mẫu VietinBank thật — dữ liệu dưới đây là GIẢ,
mô phỏng đúng cấu trúc mô tả trong yêu cầu nghiệp vụ (nhãn song ngữ VN/EN,
"Phí GD..." cho phí, "GD thanh toan tai FACEBK..." cho thanh toán chính).
"""

from __future__ import annotations

from decimal import Decimal

from app.core.document_classifier import DocumentClassifier
from app.models.enums import DocumentType
from helpers import make_content, make_context

_MAIN_PAGE = [
    "GIẤY BÁO NỢ / Debit Advice",
    "Số giao dịch / Transaction number: 9001",
    "Ngày thực hiện / Transaction date: 31-08-2026 15:38:12",
    "Số tiền bằng số / Amount in figures: 13,066,610 VND",
    "Nội dung / Remarks: GD thanh toan tai FACEBK *ABCD1234EF",
    "From account: 102030405060",
]

_FEE_PAGE = [
    "GIẤY BÁO NỢ / Debit Advice",
    "Số giao dịch / Transaction number: 9000",
    "Ngày thực hiện / Transaction date: 31-08-2026 15:38:12",
    "Số tiền bằng số / Amount in figures: 114,986 VND",
    "Nội dung / Remarks: Phi GD thanh toan tai FACEBK *ABCD1234EF",
    "From account: 102030405060",
]

_UNRELATED_PAGE = [
    "GIẤY BÁO NỢ / Debit Advice",
    "Số giao dịch / Transaction number: 9002",
    "Ngày thực hiện / Transaction date: 31-08-2026 09:00:00",
    "Số tiền bằng số / Amount in figures: 500,000 VND",
    "Nội dung / Remarks: Thanh toan tien dien nuoc",
]


class TestClassify:
    def test_trang_that_duoc_xep_dung_loai(self, classifier_config):
        classifier = DocumentClassifier(classifier_config)
        text = "\n".join(_MAIN_PAGE)
        result = classifier.classify(text)
        assert result.document_type is DocumentType.VIETINBANK_DEBIT_ADVICE
        assert result.score >= 2

    def test_khong_co_field_chinh_thi_diem_thap(self, classifier_config):
        """Chỉ có tiêu đề song ngữ (khớp cả 2 must_have_any) nhưng KHÔNG có
        field mạnh nào -> điểm dừng ở 2, dưới ngưỡng tách của
        ``DebitAdviceSplitter`` (min_score=3) — không tách trang rỗng."""
        classifier = DocumentClassifier(classifier_config)
        result = classifier.classify("GIẤY BÁO NỢ / Debit Advice — không có gì khác")
        assert result.document_type is DocumentType.VIETINBANK_DEBIT_ADVICE
        assert result.score == 2


class TestExtract:
    def test_main_payment_extract_du_truong(self, extraction_config, app_settings, registry):
        content = make_content(["\n".join(_MAIN_PAGE)], name="advice.pdf")
        extractor = registry.get(DocumentType.VIETINBANK_DEBIT_ADVICE)
        fields = extractor.extract(
            make_context(content, DocumentType.VIETINBANK_DEBIT_ADVICE, extraction_config, app_settings)
        )
        assert fields.value("transaction_number") == "9001"
        assert fields.value("total_amount") == Decimal("13066610")
        assert fields.value("currency") == "VND"
        assert fields.value("facebook_reference") == "ABCD1234EF"
        assert fields.value("payment_role") == "MAIN_PAYMENT"

    def test_fee_page_duoc_gan_bank_fee(self, extraction_config, app_settings, registry):
        content = make_content(["\n".join(_FEE_PAGE)], name="advice_fee.pdf")
        extractor = registry.get(DocumentType.VIETINBANK_DEBIT_ADVICE)
        fields = extractor.extract(
            make_context(content, DocumentType.VIETINBANK_DEBIT_ADVICE, extraction_config, app_settings)
        )
        assert fields.value("payment_role") == "BANK_FEE"
        assert fields.value("facebook_reference") == "ABCD1234EF"
        assert fields.value("total_amount") == Decimal("114986")

    def test_khong_lien_quan_facebook_thi_khong_co_reference(
        self, extraction_config, app_settings, registry
    ):
        content = make_content(["\n".join(_UNRELATED_PAGE)], name="advice_unrelated.pdf")
        extractor = registry.get(DocumentType.VIETINBANK_DEBIT_ADVICE)
        fields = extractor.extract(
            make_context(content, DocumentType.VIETINBANK_DEBIT_ADVICE, extraction_config, app_settings)
        )
        assert fields.value("facebook_reference") is None
        assert fields.value("payment_role") == "MAIN_PAYMENT"  # không "Phi" -> mặc định MAIN
