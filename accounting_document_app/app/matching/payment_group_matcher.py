"""Ghép ``PaymentCase`` từ Meta Bill, chứng từ ngân hàng (VPBank/VietinBank),
hoá đơn GTGT và sao kê.

THUẦN, không I/O, không phụ thuộc DB/GUI (giống ``ReferenceMatcher`` của
Phase 3) — nhận danh sách ``Document``/``BankTransaction`` đã trích xuất,
trả về danh sách ``PaymentCase``.

BANK-AGNOSTIC: matcher không bao giờ giả định một ngân hàng cụ thể. Chứng
từ ngân hàng CHÍNH có thể là ``VPBANK_DEBIT_NOTE`` hoặc
``VIETINBANK_DEBIT_ADVICE`` — cả hai đi qua CÙNG một đường logic qua ba hàm
``bank_name_of``/``bank_doc_facebook_reference``/``bank_doc_role``/``bank_doc_txn_id``
bên dưới. Parser trích xuất field vẫn RIÊNG theo từng ngân hàng (layout PDF
khác nhau thật) — chỉ tầng matching này là chung.

Thang tín hiệu ưu tiên:
    LEVEL 1  reference chuẩn hoá TUYỆT ĐỐI bằng nhau — mạnh nhất.
    LEVEL 2  expected_bank (suy từ 4 số cuối thẻ, config/bank_mapping.yaml)
             khớp ngân hàng thực tế — CHỈ hạ độ tin cậy khi lệch, không tự
             loại liên kết đã khớp reference.
    LEVEL 3  transaction_id / transaction_number tuyệt đối bằng nhau.
    LEVEL 4  4 số cuối thẻ.
    LEVEL 5  ngày/giờ giao dịch.
    LEVEL 6  số tiền.

Reference khớp tuyệt đối THÌ CHO PHÉP số tiền khác nhau — không bao giờ
reject một liên kết chỉ vì amount lệch khi reference đã khớp. Ngược lại,
không có reference thì CHỈ fallback theo amount+ngày khi đó là ứng viên
DUY NHẤT — nhiều ứng viên cùng thoả -> NEEDS_REVIEW, không bao giờ tự chọn
(đúng tinh thần "không đoán" xuyên suốt cả dự án).

Cùng một reference xuất hiện ở NHIỀU ngày khác nhau -> tách thành các case
riêng theo khoá ``(reference, ngày)``, không gộp chung.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.core.bank_mapping import BankMappingConfig, load_bank_mapping_config
from app.core.bank_statement_parser import BankTransaction
from app.core.text_normalizer import classify_bank_remark_role
from app.models.document import Document
from app.models.enums import DocumentType, PaymentGroupStatus
from app.models.payment_case import PaymentCase

__all__ = [
    "PaymentGroupMatchResult",
    "PaymentGroupMatcher",
    "BANK_DOCUMENT_TYPES",
    "bank_name_of",
    "bank_doc_facebook_reference",
    "bank_doc_role",
    "bank_doc_txn_id",
]

logger = logging.getLogger(__name__)

#: Loại chứng từ được coi là "chứng từ thanh toán ngân hàng" — CHÍNH hoặc
#: PHÍ, bất kể ngân hàng nào. Thêm ngân hàng mới: thêm một dòng vào đây VÀ
#: vào ``_BANK_NAME_BY_DOCUMENT_TYPE``, không sửa logic bên dưới.
BANK_DOCUMENT_TYPES = (DocumentType.VPBANK_DEBIT_NOTE, DocumentType.VIETINBANK_DEBIT_ADVICE)

_BANK_NAME_BY_DOCUMENT_TYPE = {
    DocumentType.VPBANK_DEBIT_NOTE: "VPBANK",
    DocumentType.VPBANK_VAT_INVOICE: "VPBANK",
    DocumentType.VIETINBANK_DEBIT_ADVICE: "VIETINBANK",
}


def bank_name_of(doc: Document) -> str | None:
    """Ngân hàng THỰC TẾ phát hành một chứng từ, suy từ ``document_type``.

    Đây là nguồn chân lý DUY NHẤT cho việc "chứng từ này của ngân hàng nào"
    — matcher/UI/organizer đều gọi hàm này thay vì tự so sánh
    ``document_type is DocumentType.VIETINBANK_DEBIT_ADVICE`` rải rác.
    """
    return _BANK_NAME_BY_DOCUMENT_TYPE.get(doc.document_type)


@dataclass
class PaymentGroupMatchResult:
    """Kết quả một lượt ghép payment case."""

    groups: list[PaymentCase] = field(default_factory=list)


def bank_doc_facebook_reference(doc: Document) -> str | None:
    """Reference Meta/Facebook của một chứng từ ngân hàng, bất kể ngân hàng nào.

    ``VPBANK_DEBIT_NOTE``/``VPBANK_VAT_INVOICE`` đã có sẵn field
    ``meta_reference`` (Phase 3, bóc qua ``extract_merchant_reference``);
    ``VIETINBANK_DEBIT_ADVICE`` có field ``facebook_reference`` riêng. Union
    hai nguồn ở một chỗ để phần còn lại của matcher không cần biết tới sự
    khác biệt này — CÙNG một hàm chuẩn hoá (``normalize_facebook_reference``/
    ``normalize_reference``) đã chạy ở tầng extractor cho cả hai.
    """
    if doc.document_type is DocumentType.VIETINBANK_DEBIT_ADVICE:
        return doc.value_of("facebook_reference")
    return doc.meta_reference


def bank_doc_role(doc: Document) -> str:
    """``"BANK_FEE"``/``"MAIN_PAYMENT"`` — dùng field có sẵn nếu extractor đã
    tính (VietinBank), ngược lại tự suy ra từ diễn giải (VPBank)."""
    role = doc.value_of("payment_role")
    if role is not None:
        return role
    return classify_bank_remark_role(doc.value_of("payment_detail"))


def bank_doc_txn_id(doc: Document) -> str | None:
    """Mã/số giao dịch của chứng từ ngân hàng — tên field khác nhau theo loại."""
    if doc.document_type is DocumentType.VIETINBANK_DEBIT_ADVICE:
        return doc.value_of("transaction_number")
    return doc.transaction_code


@dataclass
class _Bucket:
    """Một nhóm chứng từ cùng ``(reference, ngày)`` trước khi hoàn thiện
    thành ``PaymentCase``."""

    reference: str
    txn_date: date | None
    main_candidates: list[Document] = field(default_factory=list)
    fees: list[Document] = field(default_factory=list)
    bill_candidates: list[Document] = field(default_factory=list)
    vat_candidates: list[Document] = field(default_factory=list)


class PaymentGroupMatcher:
    """Ghép Meta Bill + chứng từ ngân hàng (mọi ngân hàng) + hoá đơn GTGT +
    dòng sao kê thành ``PaymentCase``.

    Args:
        bank_mapping: Ánh xạ thẻ -> ngân hàng kỳ vọng, mặc định nạp từ
            ``config/bank_mapping.yaml``.
    """

    def __init__(self, bank_mapping: BankMappingConfig | None = None) -> None:
        self._bank_mapping = bank_mapping or load_bank_mapping_config()

    def match(
        self,
        documents: list[Document],
        bank_transactions: list[BankTransaction] | None = None,
    ) -> PaymentGroupMatchResult:
        """Ghép toàn bộ chứng từ của một lô.

        Args:
            documents: Toàn bộ ``Document`` đã trích xuất trong lô
                (``META_INVOICE``, ``VPBANK_DEBIT_NOTE``,
                ``VIETINBANK_DEBIT_ADVICE``, ``VPBANK_VAT_INVOICE`` được
                xét — loại khác bị bỏ qua).
            bank_transactions: Dòng sao kê đã parse (có thể rỗng).

        Returns:
            ``PaymentGroupMatchResult``.
        """
        bank_transactions = bank_transactions or []
        bills = [d for d in documents if d.document_type is DocumentType.META_INVOICE]
        bank_docs = [d for d in documents if d.document_type in BANK_DOCUMENT_TYPES]
        vat_docs = [d for d in documents if d.document_type is DocumentType.VPBANK_VAT_INVOICE]

        buckets = self._build_buckets(bank_docs)
        self._attach_bills(buckets, bills)
        self._attach_vat_invoices(buckets, vat_docs)

        groups: list[PaymentCase] = []
        used_bill_ids: set[int] = set()
        for bucket in buckets.values():
            case = self._finalize_bucket(bucket)
            groups.append(case)
            if case.meta_bill is not None and case.meta_bill.document_id is not None:
                used_bill_ids.add(case.meta_bill.document_id)

        orphan_bills = [
            b for b in bills if b.document_id is None or b.document_id not in used_bill_ids
        ]
        fallback_groups, matched_orphan_ids = self._fallback_amount_date_match(orphan_bills, bank_docs)
        groups.extend(fallback_groups)

        remaining_bills = [b for b in orphan_bills if id(b) not in matched_orphan_ids]
        groups.extend(self._orphan_bill_groups(remaining_bills))

        self._attach_statement_rows(groups, bank_transactions)

        logger.info(
            "Ghép payment case xong: %d case (%d MATCHED_HIGH, %d MATCHED, %d NEEDS_REVIEW, %d UNMATCHED)",
            len(groups),
            sum(1 for g in groups if g.status is PaymentGroupStatus.MATCHED_HIGH),
            sum(1 for g in groups if g.status is PaymentGroupStatus.MATCHED),
            sum(1 for g in groups if g.status is PaymentGroupStatus.NEEDS_REVIEW),
            sum(1 for g in groups if g.status is PaymentGroupStatus.UNMATCHED),
        )
        return PaymentGroupMatchResult(groups=groups)

    # ------------------------------------------------------------- bucket

    @staticmethod
    def _build_buckets(bank_docs: list[Document]) -> dict[tuple[str, date | None], _Bucket]:
        buckets: dict[tuple[str, date | None], _Bucket] = {}
        for doc in bank_docs:
            ref = bank_doc_facebook_reference(doc)
            if ref is None:
                continue
            key = (ref, doc.transaction_date)
            bucket = buckets.setdefault(key, _Bucket(reference=ref, txn_date=doc.transaction_date))
            if bank_doc_role(doc) == "BANK_FEE":
                bucket.fees.append(doc)
            else:
                bucket.main_candidates.append(doc)
        return buckets

    @staticmethod
    def _attach_bills(buckets: dict[tuple[str, date | None], _Bucket], bills: list[Document]) -> None:
        for bill in bills:
            ref = bill.reference_number
            if ref is None:
                continue
            key = (ref, bill.document_date)
            bucket = buckets.get(key)
            if bucket is not None:
                bucket.bill_candidates.append(bill)

    @staticmethod
    def _attach_vat_invoices(buckets: dict[tuple[str, date | None], _Bucket], vat_docs: list[Document]) -> None:
        """Ghép hoá đơn GTGT bằng ĐÚNG cơ chế exact reference (+ ngày) như
        Meta Bill — KHÔNG bao giờ ghép chỉ vì trùng amount/date (§6 yêu cầu
        nghiệp vụ). VAT không có reference -> bỏ qua ở đây, không có đường
        fallback amount/date/vendor riêng cho VAT trong bản này (xem README)."""
        for vat in vat_docs:
            ref = vat.meta_reference  # Document.meta_reference cũng bao phủ VAT_INVOICE
            if ref is None:
                continue
            key = (ref, vat.transaction_date)
            bucket = buckets.get(key)
            if bucket is not None:
                bucket.vat_candidates.append(vat)

    def _finalize_bucket(self, bucket: _Bucket) -> PaymentCase:
        ambiguous = (
            len(bucket.main_candidates) > 1
            or len(bucket.bill_candidates) > 1
            or len(bucket.vat_candidates) > 1
        )
        main = bucket.main_candidates[0] if len(bucket.main_candidates) == 1 else None
        bill = bucket.bill_candidates[0] if len(bucket.bill_candidates) == 1 else None
        vat = bucket.vat_candidates[0] if len(bucket.vat_candidates) == 1 else None
        expected_bank = self._bank_mapping.expected_bank_for(bill.card_last4) if bill else None

        case = PaymentCase(
            group_code=self._group_code(bucket.reference, bucket.txn_date),
            reference=bucket.reference,
            transaction_date=bucket.txn_date,
            expected_bank=expected_bank,
            meta_bill=bill,
            main_payment=main,
            fees=list(bucket.fees),
            vat_invoice=vat,
            ambiguous_candidates=(
                max(0, len(bucket.main_candidates) - 1)
                + max(0, len(bucket.bill_candidates) - 1)
                + max(0, len(bucket.vat_candidates) - 1)
            ),
        )

        if ambiguous:
            case.status = PaymentGroupStatus.NEEDS_REVIEW
            case.confidence = "LOW"
            case.reason = (
                f"Nhiều ứng viên cùng reference {bucket.reference} ở cùng ngày "
                f"({len(bucket.main_candidates)} thanh toán chính, {len(bucket.bill_candidates)} hoá đơn, "
                f"{len(bucket.vat_candidates)} hoá đơn GTGT) — cần kiểm tra thủ công, không tự chọn."
            )
            return case

        has_bank = main is not None or bucket.fees
        if bill is not None and has_bank:
            case.status = PaymentGroupStatus.MATCHED_HIGH
            case.confidence = "HIGH"
            case.reason = f"Reference khớp tuyệt đối: {bucket.reference}"
        elif bill is not None or has_bank:
            case.status = PaymentGroupStatus.MATCHED
            case.confidence = "MEDIUM"
            missing = "chứng từ ngân hàng" if bill is not None else "Meta Bill"
            case.reason = f"Reference {bucket.reference} khớp nhưng thiếu {missing}"
        else:  # pragma: no cover - bucket luôn có ít nhất 1 bank doc khi tạo
            case.status = PaymentGroupStatus.UNMATCHED
            case.reason = "Không có chứng từ nào"

        # LEVEL 2 — expected_bank lệch với ngân hàng thực tế: hạ về
        # NEEDS_REVIEW nhưng KHÔNG xoá main_payment/fees đã ghép (§3 yêu cầu
        # nghiệp vụ: "không tự loại").
        if case.bank_mismatch:
            case.status = PaymentGroupStatus.NEEDS_REVIEW
            case.confidence = "LOW"
            case.reason += (
                f" — NHƯNG thẻ trên Meta Bill kỳ vọng ngân hàng {case.expected_bank}, "
                f"chứng từ ngân hàng thực tế lại là {case.bank_name}: cần kiểm tra thủ công."
            )
        return case

    # ------------------------------------------------------------ fallback

    def _fallback_amount_date_match(
        self,
        orphan_bills: list[Document],
        bank_docs: list[Document],
    ) -> tuple[list[PaymentCase], set[int]]:
        """LEVEL 6 — fallback amount+ngày khi KHÔNG có reference, CHỈ khi
        duy nhất một ứng viên ("chỉ auto-match nếu duy nhất một candidate...
        nhiều candidate -> NEEDS_REVIEW")."""
        no_ref_bank_docs = [d for d in bank_docs if bank_doc_facebook_reference(d) is None]
        no_ref_bills = [b for b in orphan_bills if b.reference_number is None]
        if not no_ref_bank_docs or not no_ref_bills:
            return [], set()

        by_key: dict[tuple, list[tuple[str, Document]]] = defaultdict(list)
        for bill in no_ref_bills:
            if bill.total_amount is None or bill.document_date is None:
                continue
            by_key[(bill.total_amount, bill.document_date)].append(("bill", bill))
        for doc in no_ref_bank_docs:
            if doc.total_amount is None or doc.transaction_date is None:
                continue
            by_key[(doc.total_amount, doc.transaction_date)].append(("bank", doc))

        groups: list[PaymentCase] = []
        matched_orphan_ids: set[int] = set()
        for (amount, txn_date), items in by_key.items():
            bills_here = [d for kind, d in items if kind == "bill"]
            banks_here = [d for kind, d in items if kind == "bank"]
            if len(bills_here) != 1 or len(banks_here) != 1:
                # Chỉ thực sự "mơ hồ" khi có CẢ HAI phía cùng cạnh tranh ghép
                # đôi (vd. 2 bill trùng số tiền+ngày nhưng KHÔNG có bank doc
                # nào ở khoá này thì không phải ambiguity fallback — chỉ là
                # không có gì để ghép, để rơi xuống nhánh orphan bình thường).
                if bills_here and banks_here:
                    for _, doc in items:
                        groups.append(self._ambiguous_fallback_group(doc, amount, txn_date, len(items)))
                        if any(doc is b for b in bills_here):
                            matched_orphan_ids.add(id(doc))
                continue

            bill, bank_doc = bills_here[0], banks_here[0]
            case = PaymentCase(
                group_code=self._group_code(None, txn_date, fallback_hint=str(id(bill))),
                reference=None,
                transaction_date=txn_date,
                expected_bank=self._bank_mapping.expected_bank_for(bill.card_last4),
                meta_bill=bill,
                main_payment=bank_doc if bank_doc_role(bank_doc) != "BANK_FEE" else None,
                fees=[bank_doc] if bank_doc_role(bank_doc) == "BANK_FEE" else [],
                status=PaymentGroupStatus.MATCHED,
                confidence="LOW",
                reason=(
                    f"Không có reference — khớp theo số tiền {amount} và ngày "
                    f"{txn_date:%d/%m/%Y} (duy nhất một ứng viên mỗi bên)."
                ),
            )
            groups.append(case)
            matched_orphan_ids.add(id(bill))

        return groups, matched_orphan_ids

    @staticmethod
    def _ambiguous_fallback_group(doc: Document, amount, txn_date, candidate_count: int) -> PaymentCase:
        is_bill = doc.document_type is DocumentType.META_INVOICE
        return PaymentCase(
            group_code=f"NEEDS_REVIEW_{id(doc)}",
            reference=None,
            transaction_date=txn_date,
            meta_bill=doc if is_bill else None,
            main_payment=doc if not is_bill else None,
            status=PaymentGroupStatus.NEEDS_REVIEW,
            confidence="LOW",
            ambiguous_candidates=candidate_count - 1,
            reason=(
                f"Không có reference, {candidate_count} chứng từ cùng trùng số tiền "
                f"{amount} và ngày {txn_date:%d/%m/%Y} — không đủ để tự chọn."
            ),
        )

    @staticmethod
    def _orphan_bill_groups(bills: list[Document]) -> list[PaymentCase]:
        groups = []
        for bill in bills:
            ref = bill.reference_number
            reason = (
                f"Meta Bill có reference {ref} nhưng không tìm thấy chứng từ ngân hàng nào khớp"
                if ref
                else "Meta Bill không có reference và không có ứng viên số tiền+ngày duy nhất để fallback"
            )
            groups.append(
                PaymentCase(
                    group_code=f"{bill.document_date or 'NODATE'}_{ref}" if ref else f"NOREF_{id(bill)}",
                    reference=ref,
                    transaction_date=bill.document_date,
                    expected_bank=None,
                    meta_bill=bill,
                    status=PaymentGroupStatus.UNMATCHED,
                    confidence="NONE",
                    reason=reason,
                )
            )
        return groups

    # --------------------------------------------------------- statement

    @staticmethod
    def _attach_statement_rows(groups: list[PaymentCase], bank_transactions: list[BankTransaction]) -> None:
        by_txn_id: dict[str, list[BankTransaction]] = defaultdict(list)
        by_ref_date: dict[tuple[str, date | None], list[BankTransaction]] = defaultdict(list)
        for txn in bank_transactions:
            if txn.transaction_id:
                by_txn_id[txn.transaction_id].append(txn)
            if txn.facebook_reference:
                by_ref_date[(txn.facebook_reference, txn.value_date)].append(txn)

        for case in groups:
            rows: list[BankTransaction] = []
            if case.main_payment is not None:
                txn_id = bank_doc_txn_id(case.main_payment)
                if txn_id and txn_id in by_txn_id:
                    rows.extend(by_txn_id[txn_id])
            if not rows and case.reference is not None:
                rows.extend(by_ref_date.get((case.reference, case.transaction_date), ()))
            case.statement_rows = rows
            if rows and case.status is PaymentGroupStatus.MATCHED_HIGH:
                case.reason += f" + mã giao dịch sao kê khớp: {rows[0].transaction_id}"

    @staticmethod
    def _group_code(reference: str | None, txn_date: date | None, *, fallback_hint: str = "") -> str:
        if reference is None:
            return f"NOREF_{fallback_hint or 'X'}"
        date_part = txn_date.isoformat() if txn_date else "NODATE"
        return f"{date_part}_{reference}"
