"""Chuẩn hoá text và — quan trọng nhất — chuẩn hoá SỐ THAM CHIẾU.

``normalize_reference`` là hàm được bảo vệ nghiêm ngặt nhất trong dự án.
Toàn bộ tính đúng đắn của việc ghép bộ hồ sơ phụ thuộc vào nó.

CẤM TUYỆT ĐỐI trong hàm này (xem PHASE1_ARCHITECTURE.md §6.1):
    * thay ký tự nhìn giống nhau: O->0, I->1, l->1, B->8, S->5, Z->2
    * bỏ dấu tiếng Việt trên reference
    * cắt bớt hoặc đệm thêm ký tự
    * fuzzy match: Levenshtein, difflib, rapidfuzz...
    * bất kỳ lời gọi AI/LLM nào

Hàm thuần, không I/O, không logging — để test được tuyệt đối.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = [
    "DEFAULT_REFERENCE_PATTERN",
    "NormalizedReference",
    "normalize_unicode",
    "flatten_whitespace",
    "normalize_reference",
    "normalize_tax_code",
    "references_match",
    "normalize_facebook_reference",
    "classify_bank_remark_role",
]

#: Ký tự vô hình cần loại bỏ trước khi so sánh.
_INVISIBLE_CHARS = "​‌‍﻿­"

#: Dấu câu chỉ bị bóc ở HAI ĐẦU chuỗi, không bao giờ bóc ở giữa.
_SURROUNDING_PUNCT = ".,;:()[]{}\"'`*-–—_/\\|"

#: Pattern mặc định: mẫu thật quan sát được là 10 ký tự [A-Z0-9];
#: nới thành 8..16 để an toàn, có thể ghi đè trong ``app_settings.yaml``.
DEFAULT_REFERENCE_PATTERN = r"^[A-Z0-9]{8,16}$"


@dataclass(frozen=True)
class NormalizedReference:
    """Kết quả chuẩn hoá một số tham chiếu.

    Attributes:
        value: Chuỗi đã chuẩn hoá, ``None`` nếu đầu vào rỗng/không có gì.
        raw: Chuỗi gốc trước khi chuẩn hoá.
        is_valid_format: Có khớp pattern cấu hình hay không. Khi ``False``,
            giá trị VẪN được giữ nguyên (không bị sửa) nhưng hồ sơ sẽ mang
            trạng thái ``INVALID_REFERENCE`` để người dùng kiểm tra.
    """

    value: str | None
    raw: str | None
    is_valid_format: bool

    @property
    def found(self) -> bool:
        return self.value is not None


def normalize_unicode(text: str) -> str:
    """Chuẩn hoá unicode cho text thô đọc từ PDF.

    Dùng NFC (giữ nguyên chữ tiếng Việt có dấu), loại ký tự vô hình và
    thống nhất ký tự xuống dòng.

    Args:
        text: Text thô từ PDF.

    Returns:
        Text đã chuẩn hoá, an toàn để đưa vào regex.
    """
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ")
    for ch in _INVISIBLE_CHARS:
        text = text.replace(ch, "")
    return text


def flatten_whitespace(text: str) -> str:
    """Gộp mọi khoảng trắng (kể cả xuống dòng) thành một dấu cách duy nhất.

    Bắt buộc dùng khi regex cần bắc cầu qua nhiều dòng — ví dụ phần
    ``Diễn giải`` của debit note bị PDF ngắt dòng giữa chừng::

        Diễn giải/Details: So the 1111xxxx1234 GD thanh toan
        tai FACEBK <REF> DUBLIN IE

    Args:
        text: Text đầu vào.

    Returns:
        Text một dòng, các khoảng trắng đã gộp, đã strip hai đầu.
    """
    return re.sub(r"\s+", " ", normalize_unicode(text)).strip()


def normalize_reference(
    raw: str | None,
    *,
    pattern: str = DEFAULT_REFERENCE_PATTERN,
    strip_inner_whitespace: bool = True,
) -> NormalizedReference:
    """Chuẩn hoá số tham chiếu theo đúng 10 bước đặc tả ở PHASE1 §6.1.

    Các bước: NFKC -> bỏ ký tự vô hình -> strip -> bóc dấu câu hai đầu ->
    gộp khoảng trắng -> xoá khoảng trắng -> uppercase -> kiểm tra pattern.

    Hàm KHÔNG thay thế bất kỳ ký tự nào nhìn giống nhau. ``"ABCI23"`` và
    ``"ABC123"`` là hai reference KHÁC NHAU và phải mãi mãi khác nhau.

    Args:
        raw: Chuỗi reference thô đọc từ PDF, có thể ``None``.
        pattern: Regex kiểm tra định dạng hợp lệ.
        strip_inner_whitespace: Xoá khoảng trắng bên trong chuỗi. Mặc định
            ``True`` vì mẫu thật không chứa khoảng trắng; đặt ``False`` nếu
            phát hiện nhà cung cấp dùng reference có dấu cách.

    Returns:
        ``NormalizedReference``. ``value is None`` khi đầu vào rỗng.

    Examples:
        >>> normalize_reference(" 76nqzzmdk2 ").value
        '76NQZZMDK2'
        >>> normalize_reference("ABC123").value == normalize_reference("abc123").value
        True
        >>> normalize_reference("ABCI23").value == normalize_reference("ABC123").value
        False
    """
    if raw is None:
        return NormalizedReference(value=None, raw=None, is_valid_format=False)

    text = unicodedata.normalize("NFKC", raw)
    for ch in _INVISIBLE_CHARS:
        text = text.replace(ch, "")
    text = text.replace(" ", " ").strip()
    text = text.strip(_SURROUNDING_PUNCT).strip()
    text = re.sub(r"\s+", " ", text)
    if strip_inner_whitespace:
        text = text.replace(" ", "")
    text = text.upper()

    if not text:
        return NormalizedReference(value=None, raw=raw, is_valid_format=False)

    return NormalizedReference(
        value=text,
        raw=raw,
        is_valid_format=bool(re.match(pattern, text)),
    )


def normalize_tax_code(raw: str | None) -> str | None:
    """Chuẩn hoá mã số thuế về dạng chỉ-chữ-số để đối chiếu.

    Cần thiết vì cùng một MST được in khác nhau trên từng chứng từ:
    hoá đơn Meta ghi ``01-0000000-1``, hoá đơn VPBank ghi ``0100000001``.

    CẢNH BÁO: hàm này TUYỆT ĐỐI KHÔNG được áp dụng cho ``reference``.
    Reference không bao giờ bị bóc bỏ ký tự.

    Args:
        raw: MST thô, có thể chứa dấu gạch ngang, chấm, khoảng trắng.

    Returns:
        Chuỗi chỉ gồm chữ số, hoặc ``None`` nếu không còn chữ số nào.
    """
    if raw is None:
        return None
    digits = re.sub(r"\D", "", raw)
    return digits or None


def references_match(left: str | None, right: str | None) -> bool:
    """So sánh hai reference ĐÃ chuẩn hoá.

    Đây là phép so sánh DUY NHẤT được phép dùng để quyết định ghép chứng từ
    trong toàn bộ hệ thống: so sánh chuỗi tuyệt đối. Không fuzzy, không
    prefix, không bỏ qua hoa thường (việc uppercase đã làm ở bước chuẩn hoá).

    Args:
        left: Reference đã chuẩn hoá của chứng từ thứ nhất.
        right: Reference đã chuẩn hoá của chứng từ thứ hai.

    Returns:
        ``True`` chỉ khi cả hai đều có giá trị và bằng nhau tuyệt đối.
        Hai giá trị ``None`` KHÔNG khớp nhau.
    """
    if left is None or right is None:
        return False
    return left == right


#: Nhãn nhà cung cấp Facebook/Meta xuất hiện trong diễn giải ngân hàng —
#: xem thêm ``app/extractors/merchant_reference.py`` (dùng cùng danh sách
#: này qua ``config/extraction_rules.yaml: merchant.anchors``).
_FACEBOOK_ANCHOR_RE = re.compile(r"\bFACEBO?O?K\b", re.IGNORECASE)
#: Sau anchor có thể có khoảng trắng, dấu ``*`` (ký hiệu che một phần chuỗi
#: trên một số sao kê), rồi mới tới reference thật.
_FACEBOOK_AFTER_ANCHOR_RE = re.compile(r"[\s*]*([A-Za-z0-9]{4,24})")
#: Khi KHÔNG có anchor, chấp nhận đầu vào là chính reference nếu nó là MỘT
#: token liền (không khoảng trắng) — tránh nuốt nhầm cả câu diễn giải.
_BARE_REFERENCE_RE = re.compile(r"^[A-Za-z0-9]{4,24}$")


def normalize_facebook_reference(text: str | None) -> str | None:
    """Tìm và chuẩn hoá reference Facebook/Meta nằm trong một đoạn diễn giải tự do.

    Diễn giải ngân hàng thật viết reference theo nhiều cách khác nhau::

        ABCD1234EF
        FACEBK ABCD1234EF
        FACEBK *ABCD1234EF
        GD thanh toan tai FACEBK *ABCD1234EF, the 2260

    Hàm này CHỈ bóc tách + chuẩn hoá vỏ chuỗi (case-insensitive, bỏ tiền tố
    ``FACEBK``/``FACEBOOK``, bỏ dấu ``*``, bỏ dấu phẩy/khoảng trắng thừa) —
    giống mọi hàm khác trong module này, KHÔNG bao giờ đoán hay sửa ký tự
    bên trong reference, KHÔNG fuzzy match. Không cố định một độ lang cụ thể
    (thực tế đã thấy cả 10 và 11 ký tự) — chỉ giới hạn 4..24 ký tự chữ/số làm
    biên an toàn.

    Args:
        text: Đoạn text tự do có thể chứa reference, hoặc chính là reference.

    Returns:
        Reference đã chuẩn hoá (uppercase, không khoảng trắng), hoặc
        ``None`` nếu không tìm thấy gì hợp lý.

    Examples:
        >>> normalize_facebook_reference("FACEBK *ABCD1234EF, the 2260")
        'ABCD1234EF'
        >>> normalize_facebook_reference("GD thanh toan tai FACEBK ABCD1234EF DUBLIN IE")
        'ABCD1234EF'
        >>> normalize_facebook_reference("ABCD1234EF")
        'ABCD1234EF'
        >>> normalize_facebook_reference("khong co reference o day") is None
        True
    """
    if not text:
        return None

    flat = flatten_whitespace(text)
    if not flat:
        return None

    anchor = _FACEBOOK_ANCHOR_RE.search(flat)
    if anchor is not None:
        match = _FACEBOOK_AFTER_ANCHOR_RE.match(flat[anchor.end() :])
        if match is None:
            return None
        candidate = match.group(1)
    elif _BARE_REFERENCE_RE.match(flat):
        candidate = flat
    else:
        return None

    return normalize_reference(candidate, pattern=r".*").value


#: "Phi GD..."/"Phí GD..." — CHỈ khớp khi đứng ở ĐẦU diễn giải, để không
#: nhầm với "GD thanh toan tai" (thanh toán chính) của một giao dịch khác
#: vô tình chứa chữ "phi" ở giữa câu.
_BANK_FEE_PREFIX_RE = re.compile(r"^\s*ph[íi]\b", re.IGNORECASE)


def classify_bank_remark_role(text: str | None) -> str:
    """Phân loại một dòng diễn giải ngân hàng là phí hay thanh toán chính.

    Dùng cho cả ``VPBANK_DEBIT_NOTE`` (``payment_detail``) và
    ``VIETINBANK_DEBIT_ADVICE`` (``remarks``) — §F yêu cầu nghiệp vụ: diễn
    giải bắt đầu bằng "Phí GD..."/"Phi GD..." là phí giao dịch ngân hàng đi
    kèm một khoản thanh toán chính, KHÔNG phải một khoản thanh toán Facebook
    độc lập.

    Args:
        text: Diễn giải thô (chưa cần flatten trước).

    Returns:
        ``"BANK_FEE"`` hoặc ``"MAIN_PAYMENT"`` (mặc định khi không rõ hoặc
        rỗng — một dòng không xác định được vẫn phải có vai trò để tham gia
        matching, tín hiệu tham chiếu Facebook mới là yếu tố quyết định gộp
        nhóm, không phải trường này).
    """
    if not text:
        return "MAIN_PAYMENT"
    return "BANK_FEE" if _BANK_FEE_PREFIX_RE.match(flatten_whitespace(text)) else "MAIN_PAYMENT"
