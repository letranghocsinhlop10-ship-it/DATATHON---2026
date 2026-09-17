"""Xây dựng ``Dossier`` từ kết quả gom nhóm của ``ReferenceMatcher``.

Thuật toán hai bước, đúng theo xác nhận nghiệp vụ (§2.2 phụ lục Phase 1):

1. Gom nhóm CHÍNH theo ``match_key`` (Meta.reference_number == Debit/VAT
   .meta_reference — khoá K2). Đây là bước ``ReferenceMatcher`` làm.
2. "Cứu" hoá đơn GTGT bị lạc nhóm: nếu ``meta_reference`` của nó không đọc
   được (hoặc không khớp K2 với nhóm nào), nhưng ``bank_transaction_code``
   (khoá K1, tách từ chính ``Số tham chiếu`` của hoá đơn VPBank) trùng với
   ``transaction_code`` của MỘT debit note duy nhất trong một nhóm — gắn hoá
   đơn đó vào nhóm ấy, kèm cờ ``META_REF_NOT_IN_VAT`` (K2 thất bại, chỉ K1
   khớp).

Trong mỗi nhóm đã có VAT qua K2, nếu K1 lại KHÔNG khớp debit của chính nhóm
đó — không gỡ ra (K2 là bằng chứng match tuyệt đối), nhưng gắn cờ
``FT_CODE_NOT_IN_VAT`` mức INFO.

Nếu một hoá đơn GTGT có K2 trỏ vào nhóm này nhưng K1 lại trỏ RÕ RÀNG vào một
debit note Ở NHÓM KHÁC (hai bằng chứng mâu thuẫn nhau) — gắn cờ BLOCKING
``VAT_KEY_CONFLICT`` lên chính dossier đó, ép về ``NEEDS_REVIEW`` dù đủ ba
chứng từ. Không có ký tự nào bị suy đoán hay sửa — chỉ là gắn cờ để người
dùng xem lại, đúng nguyên tắc "nghi ngờ thì NEEDS_REVIEW, không tự VALID".

Mọi cờ phát sinh trong quá trình ghép được gắn thành ``DossierIssue`` có
kiểu ngay trên dossier — không mã hoá vào ``Document.notes`` bằng chuỗi ma
thuật, để tầng xuất báo cáo (sheet CHECK_ERROR) đọc trực tiếp được.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.matching.reference_matcher import MatchResult, ReferenceGroup, ReferenceMatcher
from app.models.document import Document
from app.models.dossier import Dossier, DossierIssue
from app.models.enums import DocumentType, DossierStatus, MatchSource, Severity

__all__ = ["BuildResult", "DossierBuilder"]

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """Kết quả dựng dossier từ một lô chứng từ.

    Attributes:
        dossiers: Danh sách dossier đã dựng, đánh số theo thứ tự khoá.
        unmatched: Chứng từ không thuộc dossier nào (không có khoá, và
            không cứu được bằng K1).
    """

    dossiers: list[Dossier] = field(default_factory=list)
    unmatched: list[Document] = field(default_factory=list)


class DossierBuilder:
    """Dựng danh sách ``Dossier`` từ danh sách ``Document`` của một lô.

    Args:
        matcher: Bộ gom nhóm theo khoá; mặc định ``ReferenceMatcher()``.
        code_prefix: Tiền tố mã hồ sơ, mặc định ``"HS"``.
        code_digits: Số chữ số đệm của mã hồ sơ.
    """

    def __init__(
        self,
        matcher: ReferenceMatcher | None = None,
        *,
        code_prefix: str = "HS",
        code_digits: int = 6,
    ) -> None:
        self._matcher = matcher or ReferenceMatcher()
        self._code_prefix = code_prefix
        self._code_digits = code_digits

    def build(self, documents: list[Document]) -> BuildResult:
        """Dựng toàn bộ dossier từ danh sách chứng từ đã trích xuất.

        Args:
            documents: Toàn bộ chứng từ của một lô xử lý.

        Returns:
            ``BuildResult`` — dossier đã đánh số ổn định + chứng từ lạc loài.
        """
        result = self._matcher.match(documents)

        extra_issues: dict[str, list[DossierIssue]] = {key: [] for key in result.groups}
        self._rescue_orphan_vats(result, extra_issues)
        self._flag_k1_not_confirmed(result, extra_issues)
        self._flag_cross_group_conflicts(result, extra_issues)

        dossiers: list[Dossier] = []
        # Sắp theo khoá để đánh số ổn định giữa các lần chạy trên cùng dữ liệu.
        for index, key in enumerate(sorted(result.groups), start=1):
            dossiers.append(self._build_one(index, result.groups[key], extra_issues[key]))

        return BuildResult(dossiers=dossiers, unmatched=result.unmatched)

    # ------------------------------------------------------------ K1 rescue

    def _rescue_orphan_vats(
        self, result: MatchResult, extra_issues: dict[str, list[DossierIssue]]
    ) -> None:
        """Gắn hoá đơn GTGT bị lạc (K2 thất bại) vào nhóm đúng qua K1."""
        orphan_vats = [
            doc for doc in result.unmatched if doc.document_type is DocumentType.VPBANK_VAT_INVOICE
        ]
        if not orphan_vats:
            return

        code_to_groups = self._debit_code_index(result)

        remaining: list[Document] = []
        for vat in orphan_vats:
            code = vat.value_of("bank_transaction_code")
            targets = code_to_groups.get(code, []) if code else []
            if code and len(targets) == 1:
                key = targets[0]
                result.groups[key].vats.append(vat)
                extra_issues[key].append(
                    DossierIssue(
                        code="META_REF_NOT_IN_VAT",
                        severity=Severity.INFO,
                        description=(
                            "Hoá đơn GTGT phí ngân hàng không đọc được (hoặc không khớp) "
                            "reference Meta trong Nội dung thanh toán; đã ghép vào bộ này "
                            "nhờ Mã giao dịch (Số tham chiếu ngân hàng) khớp với Debit Note."
                        ),
                        document_id=vat.document_id,
                        suggested_action="Kiểm tra lại Nội dung thanh toán trên hoá đơn GTGT",
                    )
                )
                logger.info(
                    "Cứu hoá đơn GTGT %s vào nhóm %s qua K1 (meta_reference đọc thất bại)",
                    vat.file_name,
                    key,
                )
            else:
                if code and len(targets) > 1:
                    logger.warning(
                        "Hoá đơn GTGT %s có bank_transaction_code %s trùng ở %d nhóm — không tự chọn",
                        vat.file_name,
                        code,
                        len(targets),
                    )
                remaining.append(vat)

        result.unmatched = [
            doc for doc in result.unmatched if doc.document_type is not DocumentType.VPBANK_VAT_INVOICE
        ] + remaining

    # -------------------------------------------------- K1 không xác nhận

    def _flag_k1_not_confirmed(
        self, result: MatchResult, extra_issues: dict[str, list[DossierIssue]]
    ) -> None:
        """VAT khớp qua K2 (đã trong nhóm) nhưng K1 không xác nhận được.

        Chỉ kiểm tra khi nhóm có ĐÚNG MỘT debit (nhiều debit là
        DUPLICATE_DEBIT, không có "mã giao dịch của nhóm" duy nhất để so).
        """
        for key, group in result.groups.items():
            if len(group.debits) != 1:
                continue
            debit_code = group.debits[0].value_of("transaction_code")
            if not debit_code:
                continue
            for vat in group.vats:
                vat_code = vat.value_of("bank_transaction_code")
                if vat_code and vat_code != debit_code:
                    extra_issues[key].append(
                        DossierIssue(
                            code="FT_CODE_NOT_IN_VAT",
                            severity=Severity.INFO,
                            description=(
                                "Số tham chiếu ngân hàng trên hoá đơn GTGT "
                                f"({vat_code}) không khớp Mã giao dịch của Debit Note "
                                f"({debit_code}), dù reference Meta đã khớp."
                            ),
                            document_id=vat.document_id,
                            suggested_action="Đối chiếu lại Số tham chiếu trên hoá đơn GTGT",
                        )
                    )

    # ---------------------------------------------------------- K1 xung đột

    def _flag_cross_group_conflicts(
        self, result: MatchResult, extra_issues: dict[str, list[DossierIssue]]
    ) -> None:
        """Phát hiện VAT có K2 trỏ nhóm này nhưng K1 trỏ RÕ nhóm khác.

        Chỉ xét khi nhóm K1-đích có ĐÚNG MỘT debit (tránh nhập nhằng do
        DUPLICATE_DEBIT), và mã đó KHÁC với mọi debit trong chính nhóm K2.
        """
        code_to_key: dict[str, str] = {}
        for key, group in result.groups.items():
            if len(group.debits) == 1:
                code = group.debits[0].value_of("transaction_code")
                if code:
                    code_to_key[code] = key

        for key, group in result.groups.items():
            own_codes = {
                d.value_of("transaction_code") for d in group.debits if d.value_of("transaction_code")
            }
            for vat in group.vats:
                vat_code = vat.value_of("bank_transaction_code")
                if not vat_code or vat_code in own_codes:
                    continue
                other_key = code_to_key.get(vat_code)
                if other_key and other_key != key:
                    extra_issues[key].append(
                        DossierIssue(
                            code="VAT_KEY_CONFLICT",
                            severity=Severity.BLOCKING,
                            description=(
                                "Hoá đơn GTGT khớp reference Meta với bộ này (K2), nhưng Số "
                                f"tham chiếu ngân hàng lại khớp Debit Note của bộ khác ({other_key})."
                            ),
                            document_id=vat.document_id,
                            suggested_action="Kiểm tra thủ công — hai bằng chứng ghép mâu thuẫn nhau",
                        )
                    )
                    logger.warning(
                        "%s: K2 trỏ nhóm %s nhưng K1 (%s) trỏ nhóm %s — mâu thuẫn",
                        vat.file_name,
                        key,
                        vat_code,
                        other_key,
                    )

    @staticmethod
    def _debit_code_index(result: MatchResult) -> dict[str, list[str]]:
        """Ánh xạ ``transaction_code`` -> danh sách khoá nhóm chứa nó."""
        index: dict[str, list[str]] = {}
        for key, group in result.groups.items():
            for debit in group.debits:
                code = debit.value_of("transaction_code")
                if code:
                    index.setdefault(code, []).append(key)
        return index

    # --------------------------------------------------------------- dựng

    def _build_one(self, index: int, group: ReferenceGroup, issues: list[DossierIssue]) -> Dossier:
        code = f"{self._code_prefix}{index:0{self._code_digits}d}"

        primary_meta = group.metas[0] if len(group.metas) == 1 else None
        primary_debit = group.debits[0] if len(group.debits) == 1 else None
        primary_vat = group.vats[0] if len(group.vats) == 1 else None

        all_ids = [doc.document_id for doc in group.all_documents if doc.document_id is not None]

        card = self._first_value(group, "card_last4")
        transaction_date = self._first_value(group, "transaction_date") or self._first_value(
            group, "document_date"
        )

        dossier = Dossier(
            dossier_code=code,
            reference=group.key,
            meta_document_id=primary_meta.document_id if primary_meta else None,
            debit_document_id=primary_debit.document_id if primary_debit else None,
            vat_document_id=primary_vat.document_id if primary_vat else None,
            meta_count=len(group.metas),
            debit_count=len(group.debits),
            vat_count=len(group.vats),
            extra_documents=tuple(all_ids),
            card_last4=card,
            transaction_date=transaction_date,
            status=DossierStatus.NEEDS_REVIEW,  # validator sẽ quyết định lại
            match_source=MatchSource.AUTO_EXACT,
        )
        dossier.issues.extend(issues)
        return dossier

    @staticmethod
    def _first_value(group: ReferenceGroup, field_name: str):
        for doc in group.all_documents:
            value = doc.value_of(field_name)
            if value:
                return value
        return None
