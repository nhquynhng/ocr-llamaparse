from __future__ import annotations

"""Postprocess riêng cho tài liệu dạng đơn/giấy/biểu mẫu.

Module này chỉ chứa các luật định dạng thường gặp ở DOCX biểu mẫu sau khi OCR
bằng LlamaParse. Mục tiêu là không trộn các rule form-field vào
`llamaparse_postprocess.py`, tương tự cách các rule bảng được tách sang
`table_postprocess.py`.

Nhóm lỗi đang xử lý:
1. Tiêu ngữ quốc gia bị OCR không đồng nhất: lúc là heading, lúc plain text,
   lúc có underline HTML sai.
2. Tiêu đề form như `ĐƠN XIN...`, `GIẤY XÁC NHẬN...`, `PHIẾU...` bị mất H1
   hoặc bị gắn underline/bold không cần thiết.
3. Dòng `Kính gửi/gởi...` bị hạ thành text thường, trong khi mẫu DOCX thường
   in đậm toàn dòng.
4. Các nhãn trường như `Tôi tên`, `Ngày sinh`, `Mã số sinh viên` bị LlamaParse
   bọc `**...**` hoặc biến thành bullet list dù Word gốc là text thường.
"""

import re
import unicodedata


FORM_DOCUMENT_CUE_RE = re.compile(
    r"\b("
    r"don\s+(xin|de\s+nghi|dang\s+ky)|mau\s+don|bieu\s+mau|"
    r"giay\s+(xac\s+nhan|de\s+nghi|gioi\s+thieu|uy\s+quyen|cam\s+ket)|"
    r"phieu\s+(dang\s+ky|yeu\s+cau|de\s+nghi|khao\s+sat|thu\s+thap)|"
    r"kinh\s+g(?:ui|oi)"
    r")\b",
    flags=re.IGNORECASE,
)

FORM_TITLE_RE = re.compile(
    r"^("
    r"ĐƠN\s+(XIN|ĐỀ\s+NGHỊ|ĐĂNG\s+KÝ|CAM\s+KẾT|KHIẾU\s+NẠI|TỐ\s+CÁO)|"
    r"GIẤY\s+(XÁC\s+NHẬN|ĐỀ\s+NGHỊ|GIỚI\s+THIỆU|ỦY\s+QUYỀN|CAM\s+KẾT)|"
    r"PHIẾU\s+(ĐĂNG\s+KÝ|YÊU\s+CẦU|ĐỀ\s+NGHỊ|KHẢO\s+SÁT|THU\s+THẬP)|"
    r"MẪU\s+(ĐƠN|PHIẾU|GIẤY)"
    r")\b.*$",
    flags=re.IGNORECASE,
)

FORM_FIELD_CUE_RE = re.compile(
    r"\b("
    r"toi\s+ten|ho\s+va\s+ten|ho\s+ten|ten|ngay\s+sinh|noi\s+sinh|gioi\s+tinh|dan\s+toc|ton\s+giao|"
    r"ma\s+so|mssv|sinh\s+vien|hoc\s+vien|nganh|lop|khoa|nien\s+khoa|nam\s+hoc|"
    r"cha|me|ho\s+khau|thuong\s+tru|tam\s+tru|dia\s+chi|dien\s+thoai|email|cccd|cmnd|"
    r"thuoc\s+dien|doi\s+tuong|hoan\s+canh|ly\s+do|noi\s+dung|khoa\s+hoc|don\s+vi|ngan\s+hang|"
    r"tai\s+khoan|nguoi\s+lien\s+he|quan\s+he|so\s+the|ngay|thang|nam"
    r")\b",
    flags=re.IGNORECASE,
)

FORM_NOTE_RE = re.compile(
    r"^\(?\s*(kem\s+theo|ghi\s+chu|ho\s+so\s+kem\s+theo)\b",
    flags=re.IGNORECASE,
)

SALUTATION_RE = re.compile(r"^Kính\s+g(?:ửi|ởi|ui|oi)\s*:", flags=re.IGNORECASE)

NATIONAL_HEADER_RE = re.compile(
    r"^CỘNG\s+H[ÒO]A\s+X[ÃA]\s+HỘI\s+CHỦ\s+NGHĨA\s+VIỆT\s+NAM\s*$",
    flags=re.IGNORECASE,
)

NATIONAL_MOTTO_RE = re.compile(
    r"^Độc\s+lập\s*[-–—]\s*Tự\s+do\s*[-–—]\s*Hạnh\s+phúc\s*$",
    flags=re.IGNORECASE,
)


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt để so khớp ổn định."""

    text = text.replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def strip_inline_markdown(text: str) -> str:
    """Gỡ markup inline cơ bản nhưng giữ nguyên nội dung."""

    text = re.sub(r"<\/?u>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"_(.*?)_", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    return text.strip()


def normalize_spaces(text: str) -> str:
    """Chuẩn hóa khoảng trắng, giữ khoảng trắng trước/sau dấu hai chấm dễ đọc."""

    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;])", r"\1", text)
    text = re.sub(r"\s*:\s*", " : ", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def unwrap_heading(line: str) -> tuple[int, str] | None:
    """Nếu dòng là Markdown heading thì trả về (level, nội dung)."""

    match = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def is_comment_line(line: str) -> bool:
    """Bỏ qua HTML comment do pipeline chèn vào."""

    stripped = line.strip()
    return stripped.startswith("<!--") and stripped.endswith("-->")


def is_table_line(line: str) -> bool:
    """Ước lượng dòng bảng để rule form không sửa nhầm bảng."""

    stripped = line.strip().lower()
    if not stripped:
        return False
    return (
        stripped.startswith("|")
        or stripped.startswith("<table")
        or stripped.startswith("<tr")
        or stripped.startswith("<th")
        or stripped.startswith("<td")
        or stripped.startswith("</table")
        or stripped.startswith("</tr")
    )


def is_form_like_document(markdown: str) -> bool:
    """Nhận diện tài liệu dạng đơn/giấy/phiếu/biểu mẫu."""

    sample = markdown[:8000]
    key = strip_accents(strip_inline_markdown(sample)).lower()
    key = re.sub(r"[^a-z0-9\s]+", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    return bool(FORM_DOCUMENT_CUE_RE.search(key))


def looks_like_form_title(text: str) -> bool:
    """Nhận diện tiêu đề chính của đơn/giấy/phiếu để chuẩn hóa H1."""

    clean = strip_inline_markdown(text)
    clean = re.sub(r"<[^>]+>", "", clean).strip(" -–—:\t")
    if not clean:
        return False
    return bool(FORM_TITLE_RE.match(clean))


def looks_like_national_header(text: str) -> bool:
    """Nhận diện dòng quốc hiệu."""

    return bool(NATIONAL_HEADER_RE.match(strip_inline_markdown(text)))


def looks_like_national_motto(text: str) -> bool:
    """Nhận diện dòng tiêu ngữ."""

    return bool(NATIONAL_MOTTO_RE.match(strip_inline_markdown(text)))


def looks_like_salutation(text: str) -> bool:
    """Nhận diện dòng Kính gửi/gởi."""

    return bool(SALUTATION_RE.match(strip_inline_markdown(text)))


def clean_display_line(text: str) -> str:
    """Gỡ markdown/underline rồi chuẩn hóa khoảng trắng cho các dòng form."""

    return normalize_spaces(strip_inline_markdown(text))


def normalize_national_or_title_line(line: str) -> str | None:
    """Chuẩn hóa các dòng đầu form: quốc hiệu, tiêu ngữ, tiêu đề, kính gửi."""

    found = unwrap_heading(line)
    content = found[1] if found else line.strip()
    clean = clean_display_line(content)

    if looks_like_national_header(clean):
        return f"**{clean}**"

    if looks_like_national_motto(clean):
        # Trong mẫu DOCX đang xét dòng này có bold, không có underline.
        return f"**{clean}**"

    if looks_like_form_title(clean):
        # Tiêu đề form là H1; không giữ <u>, ** hoặc __ do OCR tự thêm.
        return f"# {clean}"

    if looks_like_salutation(clean):
        # Dòng kính gửi/gởi trong mẫu đơn thường in đậm toàn dòng, nhưng không là heading.
        return f"**{clean}**"

    return None


def looks_like_form_field_label(label: str) -> bool:
    """Ước lượng cụm trước dấu `:` có phải nhãn trường biểu mẫu hay không."""

    clean = strip_inline_markdown(label)
    clean = re.sub(r"<[^>]+>", "", clean).strip(" -–—:\t")
    if not clean:
        return False

    key = strip_accents(clean).lower()
    key = re.sub(r"[^a-z0-9\s/().-]+", " ", key)
    key = re.sub(r"\s+", " ", key).strip()

    if len(clean) > 120:
        return False
    if re.search(r"[.;!?]$", clean):
        return False
    if key.startswith(("dieu ", "chuong ", "muc ", "phan ")):
        return False

    return bool(FORM_FIELD_CUE_RE.search(key))


def unbold_form_field_labels(text: str) -> str:
    """Gỡ `**...**` quanh nhãn trường, không đụng các dòng nhấn mạnh thật."""

    def replace_bold_label_before_colon(match: re.Match[str]) -> str:
        """Gỡ bold khi dấu hai chấm nằm ngoài cặp `**...**`."""

        label = match.group(1).strip()
        if looks_like_form_field_label(label):
            return f"{strip_inline_markdown(label)}:"
        return match.group(0)

    def replace_bold_label_with_colon(match: re.Match[str]) -> str:
        """Gỡ bold khi dấu hai chấm nằm bên trong cặp `**...:**`."""

        raw_label = match.group(1).strip()
        label = raw_label[:-1].strip() if raw_label.endswith(":") else raw_label
        if looks_like_form_field_label(label):
            return f"{strip_inline_markdown(label)}:"
        return match.group(0)

    # `**Tôi tên**:`
    text = re.sub(
        r"\*\*([^*\n:]{1,120}?)\*\*\s*:",
        replace_bold_label_before_colon,
        text,
    )

    # `**Tôi tên:**`
    text = re.sub(
        r"\*\*([^*\n]{1,120}?:)\*\*",
        replace_bold_label_with_colon,
        text,
    )

    # LlamaParse đôi khi sinh markdown lỗi kiểu `*Tôi tên**:`.
    # Khi dòng bị nhận nhầm là bullet, phần đưa vào hàm này còn lại `Tôi tên**:`.
    text = re.sub(
        r"(?<!\*)\*([^*\n:]{1,120}?)\*\*\s*:",
        replace_bold_label_before_colon,
        text,
    )
    text = re.sub(
        r"(?<!\*)\b([^*\n:]{1,120}?)\*\*\s*:",
        replace_bold_label_before_colon,
        text,
    )

    return text


def is_placeholder_or_empty(text: str) -> bool:
    """Dòng chỉ còn phần chấm/khoảng trắng để điền thông tin."""

    stripped = strip_inline_markdown(text).strip()
    if not stripped:
        return True
    placeholder_chars = set(". …_-,，:;()[]{} ")
    return all(ch in placeholder_chars for ch in stripped)


def looks_like_form_field_line(text: str) -> bool:
    """Nhận diện dòng chứa một hoặc nhiều nhãn trường form."""

    clean = strip_inline_markdown(text).strip()
    if not clean or ":" not in clean:
        return False

    first_prefix = clean.split(":", 1)[0]
    if looks_like_form_field_label(first_prefix):
        return True

    labels = re.findall(r"[,;]\s*([^,;:\n]{1,120}?)\s*:", clean)
    return any(looks_like_form_field_label(label) for label in labels)


def normalize_form_document_lines(markdown: str) -> str:
    """Sửa lỗi OCR phổ biến trong mẫu đơn/giấy/phiếu DOCX.

    Chỉ chạy khi tài liệu có dấu hiệu rõ ràng là form để tránh ảnh hưởng văn bản
    quy định/quy chế thông thường.
    """

    if not is_form_like_document(markdown):
        return markdown

    out: list[str] = []
    in_fence = False

    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue

        if in_fence or is_table_line(line) or is_comment_line(line):
            out.append(line)
            continue

        fixed_top_line = normalize_national_or_title_line(line)
        if fixed_top_line is not None:
            out.append(fixed_top_line)
            continue

        bullet = re.match(r"^[-*•]\s*(.*)$", line.lstrip())
        if bullet:
            content = bullet.group(1)
            fixed_content = unbold_form_field_labels(content).strip()
            content_key = strip_accents(strip_inline_markdown(fixed_content)).lower().strip()

            if (
                looks_like_form_field_line(fixed_content)
                or is_placeholder_or_empty(fixed_content)
                or FORM_NOTE_RE.match(content_key)
            ):
                out.append(fixed_content)
                continue

        out.append(unbold_form_field_labels(line))

    return "\n".join(out)
