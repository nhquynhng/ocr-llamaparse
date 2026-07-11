from __future__ import annotations

"""
Postprocess Markdown do LlamaParse sinh ra.

File này chỉ giữ các luật hậu xử lý văn bản/heading chung.
Tất cả luật liên quan đến bảng đã được tách sang `table_postprocess.py`.

Các lỗi đang xử lý:
1. Heading không đồng nhất: cùng là `Điều 1`, `Điều 2` nhưng lúc là ##, lúc là bold.
2. Dòng list/khoản dưới `Điều ...` bị bọc bold hoặc bị promote thành heading: **2. ...** trong khi đây chỉ là nội dung con.
3. Chuẩn hóa bảng qua module `table_postprocess`.
4. Cleanup dòng trắng.
"""

import argparse
import re
import unicodedata
from pathlib import Path

try:
    from src.postprocess.table_postprocess import (
        convert_html_tables_to_markdown,
        fix_html_table_page_continuations,
        is_table_line,
        merge_continued_tables,
        normalize_tables,
        split_html_tables_at_embedded_page_markers,
    )
except ModuleNotFoundError:  # Cho phép chạy trực tiếp file này bằng python path/to/file.py
    from table_postprocess import (
        convert_html_tables_to_markdown,
        fix_html_table_page_continuations,
        is_table_line,
        merge_continued_tables,
        normalize_tables,
        split_html_tables_at_embedded_page_markers,
    )


EXACT_MAJOR_TITLES = {
    "quyet dinh",
    "quy che",
    "quy dinh",
    "noi quy",
    "ke hoach",
    "thong bao",
    "cong van",
    "huong dan",
    "phu luc",
    "bieu mau",
    "quy trinh",
}


ARTICLE_HEADING_RE = re.compile(
    r"^Điều\s+\d+[.:]?\s+\S+",
    flags=re.IGNORECASE,
)

BOLD_ARTICLE_LINE_RE = re.compile(
    r"^\s*\*\*(Điều\s+\d+[.:]?\s+.*?)\*\*\s*(.*)$",
    flags=re.IGNORECASE,
)


ARTICLE_PREFIX_RE = re.compile(
    r"^\s*Điều\s+\d+[.:]?\s+\S+",
    flags=re.IGNORECASE,
)


DECIMAL_SECTION_RE = re.compile(
    r"^\s*\d+(?:\.\d+)+(?:[\.)])?\s+\S+",
    flags=re.IGNORECASE,
)


DECIMAL_PREFIX_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)+(?:[\.)])?)\s+(.+?)\s*$",
    flags=re.IGNORECASE,
)


CLAUSE_CUE_RE = re.compile(
    r"\b("
    r"phai|duoc|khong\s+duoc|co\s+trach\s+nhiem|chiu\s+trach\s+nhiem|"
    r"thuc\s+hien|nop|bao\s+cao|bao\s+ngay|cung\s+cap|xac\s+nhan|"
    r"truong\s+hop|neu|khi|doi\s+voi|theo\s+quy\s+dinh|nghiem\s+cam|"
    r"cho\s+phep|khong|tuy\s+muc\s+do"
    r")\b",
    flags=re.IGNORECASE,
)


NUMBER_SECTION_RE = re.compile(
    # 1. ..., 1) ..., 1/ ... nhưng không ăn 1.1 ...
    r"^\s*\d{1,2}(?:[\.)/])\s+\S+",
    flags=re.IGNORECASE,
)


UPPER_ALPHA_SECTION_RE = re.compile(
    # A. ..., A) ..., A/ ...; chỉ nhận chữ in hoa để tránh biến a), b) trong đoạn thường thành heading.
    r"^\s*[A-ZĐ](?:[\.)/])\s+\S+",
)


FORM_DOCUMENT_CUE_RE = re.compile(
    r"\b("
    r"don\s+(xin|de\s+nghi|dang\s+ky)|mau\s+don|bieu\s+mau|phieu\s+(dang\s+ky|yeu\s+cau|de\s+nghi)|"
    r"kinh\s+g(?:ui|oi)"
    r")\b",
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




def is_form_like_document(markdown: str) -> bool:
    """Nhận diện văn bản dạng đơn/biểu mẫu để bật luật sửa lỗi form-field.

    LlamaParse hay suy diễn nhầm nhãn trường trong mẫu đơn DOCX thành bold và
    bullet list dù file Word gốc chỉ là dòng văn bản có dấu chấm điền thông tin.
    Chỉ bật luật này khi tài liệu có cue rõ ràng như `ĐƠN...`, `BIỂU MẪU`,
    `PHIẾU...` hoặc dòng `Kính gửi/gởi` để tránh ảnh hưởng văn bản quy định.
    """

    sample = markdown[:6000]
    key = strip_accents(sample).lower()
    key = re.sub(r"[^a-z0-9\s]+", " ", key)
    key = re.sub(r"\s+", " ", key).strip()
    return bool(FORM_DOCUMENT_CUE_RE.search(key))


def looks_like_form_field_label(label: str) -> bool:
    """Ước lượng một cụm trước dấu `:` có phải nhãn trường của mẫu đơn hay không."""

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
    """Gỡ `**...**` quanh nhãn trường form nhưng không đụng các dòng nhấn mạnh khác."""

    def replace_bold_label_before_colon(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        if looks_like_form_field_label(label):
            return f"{strip_inline_markdown(label)}:"
        return match.group(0)

    def replace_bold_label_with_colon(match: re.Match[str]) -> str:
        raw_label = match.group(1).strip()
        label = raw_label[:-1].strip() if raw_label.endswith(":") else raw_label
        if looks_like_form_field_label(label):
            return f"{strip_inline_markdown(label)}:"
        return match.group(0)

    # Dạng phổ biến từ LlamaParse: **Tôi tên**:
    text = re.sub(
        r"\*\*([^*\n:]{1,120}?)\*\*\s*:",
        replace_bold_label_before_colon,
        text,
    )

    # Dạng khác có thể gặp: **Tôi tên:**
    text = re.sub(
        r"\*\*([^*\n]{1,120}?:)\*\*",
        replace_bold_label_with_colon,
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
    """Nhận diện cả dòng biểu mẫu chứa một hoặc nhiều nhãn trước dấu hai chấm."""

    clean = strip_inline_markdown(text).strip()
    if not clean or ":" not in clean:
        return False

    # Trường một nhãn dài có ngoặc/phẩy bên trong, ví dụ:
    # `Là sinh viên thuộc diện ... (tàn tật, mồ côi cha mẹ, hộ nghèo):`
    # phải xét toàn bộ phần trước dấu `:` đầu tiên, không tách cứng theo dấu phẩy.
    first_prefix = clean.split(":", 1)[0]
    if looks_like_form_field_label(first_prefix):
        return True

    # Trường nhiều nhãn trên cùng dòng, ví dụ:
    # `Tôi tên: ..., Mã số sinh viên: ...`
    labels = re.findall(r"[,;]\s*([^,;:\n]{1,120}?)\s*:", clean)
    return any(looks_like_form_field_label(label) for label in labels)


def normalize_form_document_lines(markdown: str) -> str:
    """Sửa lỗi OCR phổ biến trong mẫu đơn/DOCX.

    Các lỗi được sửa:
    - `- **Tôi tên**:` -> `Tôi tên:` vì Word gốc không in đậm nhãn trường.
    - `- **Họ và tên cha**:` -> `Họ và tên cha:`.
    - Dòng ghi chú như `- (Kèm theo...)` bị nhận nhầm bullet list -> bỏ bullet.
    - `### Kính gửi/gởi ...` trong đơn -> không coi là heading cấu trúc.
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

        found = unwrap_heading(line)
        if found:
            _, heading_text = found
            clean_heading = strip_inline_markdown(heading_text).strip()
            if SALUTATION_RE.match(clean_heading):
                out.append(clean_heading)
                continue
            out.append(line)
            continue

        stripped = line.strip()
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


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt để phục vụ so khớp luật heading ổn định."""

    text = text.replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_key(text: str) -> str:
    """Chuẩn hóa chuỗi để so khớp: bỏ Markdown cơ bản, bỏ dấu, lowercase."""

    text = re.sub(r"^#+\s*", "", text.strip())
    text = text.strip("*_` \t")
    text = re.sub(r"<[^>]+>", "", text)
    text = strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9/.\-\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_inline_markdown(text: str) -> str:
    """Gỡ markup nhấn mạnh đơn giản nhưng giữ nguyên nội dung."""

    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"\1", text)
    text = re.sub(r"_(.*?)_", r"\1", text)
    return text.strip()


def split_yaml_frontmatter(markdown: str) -> tuple[str, str]:
    """Tách YAML front matter để postprocess không sửa nhầm metadata."""

    lines = markdown.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", markdown

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "".join(lines[: idx + 1]), "".join(lines[idx + 1 :])

    return "", markdown


def is_comment_line(line: str) -> bool:
    """Bỏ qua HTML comment do pipeline hoặc LlamaParse chèn vào."""

    return line.strip().startswith("<!--") and line.strip().endswith("-->")


def unwrap_heading(line: str) -> tuple[int, str] | None:
    """Nếu dòng là Markdown heading thì trả về (level, nội dung heading)."""

    m = re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
    if not m:
        return None
    return len(m.group(1)), m.group(2).strip()


def make_heading(level: int, text: str) -> str:
    """Tạo Markdown heading với level hợp lệ từ 1 đến 6."""

    level = min(max(level, 1), 6)
    return f"{'#' * level} {strip_inline_markdown(text)}"


def is_major_title(text: str) -> bool:
    """Kiểm tra dòng có phải tiêu đề lớn độc lập như QUYẾT ĐỊNH, QUY CHẾ."""

    return normalize_key(text).rstrip(":") in EXACT_MAJOR_TITLES


def is_article_heading(text: str) -> bool:
    """Nhận diện heading dạng Điều 1. ..., Điều 2. ..."""

    return bool(ARTICLE_HEADING_RE.match(strip_inline_markdown(text)))


def is_roman_heading(text: str) -> bool:
    """Nhận diện heading dạng I. ..., II. ..., III. ..."""

    return bool(re.match(r"^[IVXLCDM]{1,8}\.\s+\S+", text.strip(), re.IGNORECASE))


def is_luu_do_heading(text: str) -> bool:
    """Nhận diện heading 'LƯU ĐỒ 1', 'LƯU ĐỒ 2'."""

    return bool(re.match(r"^luu do\s+\d+", normalize_key(text)))


def split_decimal_section(text: str) -> tuple[str, str] | None:
    """Tách dòng dạng `2.1. Nội dung` thành (prefix, body)."""

    clean = strip_inline_markdown(text).strip()
    m = DECIMAL_PREFIX_RE.match(clean)
    if not m:
        return None
    return m.group(1), m.group(2).strip()


def is_decimal_section_marker(text: str) -> bool:
    """Chỉ kiểm tra dòng có mở đầu bằng số thập phân như `2.1`, `2.2.1`."""

    return bool(DECIMAL_SECTION_RE.match(strip_inline_markdown(text)))


def looks_like_clause_not_heading(text: str) -> bool:
    """Nhận diện `2.1`, `2.2` là câu/khoản nội dung, không phải tiêu đề.

    Lỗi thường gặp của OCR là promote mọi dòng `2.1. ...` thành heading. Trong
    tài liệu hành chính, nhiều dòng thập phân thực chất là điều khoản con: có chủ
    ngữ + động từ quy định/nghĩa vụ và là một câu đầy đủ. Khi đó phải giữ dạng
    paragraph/list item, dù dòng khá dài hoặc được in đậm trong PDF.
    """

    clean = strip_inline_markdown(text).strip()
    decimal = split_decimal_section(clean)
    body = decimal[1] if decimal else clean
    body = body.strip()
    if not body:
        return False

    body_key = normalize_key(body)
    word_count = len(re.findall(r"\w+", body_key, flags=re.UNICODE))
    has_clause_cue = bool(CLAUSE_CUE_RE.search(body_key))
    starts_like_subject = bool(re.match(
        r"^(sv|sinh vien|hoc vien|nguoi|ca nhan|tap the|don vi|phong|khoa|"
        r"trung tam|truong|giang vien|can bo|phu huynh|truong hop|khi|neu|doi voi)\b",
        body_key,
    ))

    if len(body) >= 120:
        return True
    if has_clause_cue and word_count >= 12:
        return True
    if starts_like_subject and has_clause_cue:
        return True
    if has_clause_cue and re.search(r"[.;]\s*$", body):
        return True
    if body.count(",") >= 2 or ";" in body:
        return True

    return False


def is_decimal_section_heading(text: str) -> bool:
    """Nhận diện mục thập phân dạng 1.1, 2.4 là heading H4 khi thật sự giống đề mục."""

    decimal = split_decimal_section(text)
    if not decimal:
        return False

    _, body = decimal
    if looks_like_clause_not_heading(text):
        return False

    # Ưu tiên an toàn: chỉ promote các dòng ngắn/giống cụm tiêu đề.
    if len(body) <= 100:
        return True

    # Dòng dài nhưng kết thúc bằng dấu hai chấm thường là nhãn đề dẫn vào danh sách.
    return len(body) <= 130 and body.rstrip().endswith(":")


def is_numbered_heading(text: str) -> bool:
    """Nhận diện mục số cấp H3 dạng 1. ..., 2) ..., 3/ ...; loại trừ mục thập phân."""

    clean = strip_inline_markdown(text).strip()
    return bool(NUMBER_SECTION_RE.match(clean)) and not is_decimal_section_heading(clean)


def is_upper_alpha_heading(text: str) -> bool:
    """Nhận diện mục chữ cái cấp H3 dạng A. ..., B) ..., C/ ...."""

    return bool(UPPER_ALPHA_SECTION_RE.match(strip_inline_markdown(text).strip()))


def looks_like_long_sentence(text: str) -> bool:
    """Ước lượng dòng giống đoạn văn thường hơn là tiêu đề."""

    plain = strip_inline_markdown(text)
    if len(plain) >= 140:
        return True
    if len(plain) >= 90 and re.search(r"[.;,)]$", plain):
        return True
    if re.match(r"^(Nội quy|Quy định|Quy chế|Quyết định|Kế hoạch|Thông báo)\s+này\b", plain, re.I):
        return True
    return False


def normalize_heading_line(line: str) -> str:
    """Chuẩn hóa một dòng Markdown heading đã tồn tại từ LlamaParse."""

    found = unwrap_heading(line)
    if not found:
        return line

    level, text = found
    clean_text = strip_inline_markdown(text)

    if is_major_title(clean_text):
        return make_heading(1, clean_text)

    if normalize_key(clean_text).rstrip(":") == "quyet dinh":
        return make_heading(1, clean_text)

    # Các `Điều n...` trong cùng một văn bản phải cùng cấp H4.
    if is_article_heading(clean_text):
        return make_heading(4, clean_text)

    if is_roman_heading(clean_text):
        return make_heading(2, clean_text)

    if is_luu_do_heading(clean_text):
        return make_heading(2, clean_text)

    # Quy tắc cấp heading theo spec:
    # - H3: mục số 1., 2), 3/ hoặc mục chữ cái A., B), C/
    # - H4: mục thập phân 1.1, 2.4 hoặc Điều ...
    if is_decimal_section_marker(clean_text):
        if looks_like_clause_not_heading(clean_text):
            return clean_text
        if is_decimal_section_heading(clean_text):
            return make_heading(4, clean_text)

    if is_numbered_heading(clean_text) or is_upper_alpha_heading(clean_text):
        return make_heading(3, clean_text)

    if looks_like_long_sentence(clean_text):
        return clean_text

    return line


def is_full_line_bold(line: str) -> str | None:
    """Nếu cả dòng là bold Markdown thì trả về nội dung bên trong, ngược lại None."""

    m = re.match(r"^\s*\*\*(.+?)\*\*\s*$", line.strip())
    if not m:
        return None
    return m.group(1).strip()


def structural_heading_level(text: str) -> int | None:
    """Trả về cấp heading theo spec, hoặc None nếu dòng không phải heading cấu trúc."""

    clean = strip_inline_markdown(text).strip()
    if not clean:
        return None

    if is_major_title(clean):
        return 1
    if is_roman_heading(clean) or is_luu_do_heading(clean):
        return 2
    if is_numbered_heading(clean) or is_upper_alpha_heading(clean):
        return 3
    if is_decimal_section_marker(clean):
        return 4 if is_decimal_section_heading(clean) else None
    if is_article_heading(clean):
        return 4

    return None


def promote_structural_heading_lines(markdown: str) -> str:
    """Chuẩn hóa các dòng chưa có marker heading nhưng là mục cấu trúc.

    Xử lý các trường hợp OCR hay sinh không đồng nhất:
    - `1. ...`, `2) ...`, `3/ ...` -> H3
    - `A. ...`, `B) ...`, `C/ ...` -> H3
    - `1.1 ...`, `2.4 ...`, `Điều ...` -> H4
    - `**1/ Mục đích:**`, `**A/ Nội dung:**` -> gỡ bold và đưa về đúng cấp
    """

    out: list[str] = []
    in_fence = False

    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue

        if in_fence or is_table_line(line) or is_comment_line(line) or unwrap_heading(line):
            out.append(line)
            continue

        stripped = line.strip()
        bold_content = is_full_line_bold(stripped)
        candidate = bold_content if bold_content is not None else stripped
        level = structural_heading_level(candidate)

        if level is not None:
            out.append(make_heading(level, candidate))
            continue

        out.append(line)

    return "\n".join(out)


def promote_bold_article_lines(markdown: str) -> str:
    """Đổi các dòng `**Điều n...**` hoặc `Điều n...` thành heading H4.

    Giữ hàm này để tương thích với pipeline cũ; logic tổng quát hơn nằm ở
    `promote_structural_heading_lines`.
    """

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

        stripped = line.strip()
        match = BOLD_ARTICLE_LINE_RE.match(stripped)
        if match:
            heading_text = f"{match.group(1)} {match.group(2)}".strip()
            out.append(make_heading(4, heading_text))
            continue

        # Trường hợp dòng bắt đầu bằng Điều nhưng không có marker heading/bold.
        if ARTICLE_PREFIX_RE.match(strip_inline_markdown(stripped)) and not unwrap_heading(stripped):
            out.append(make_heading(4, stripped))
            continue

        out.append(line)

    return "\n".join(out)


def normalize_existing_headings(markdown: str) -> str:
    """Chuẩn hóa các heading đã có sẵn trong Markdown raw của LlamaParse."""

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

        out.append(normalize_heading_line(line))

    return "\n".join(out)


def demote_bold_numbered_lines(markdown: str) -> str:
    """Gỡ bold toàn dòng cho các khoản đánh số thường bị hiểu nhầm là nhấn mạnh."""

    lines = markdown.splitlines()
    out: list[str] = []

    for line in lines:
        s = line.strip()

        # Không đụng vào Điều; phần này đã được promote thành H4 trước đó.
        if is_article_heading(strip_inline_markdown(s)):
            out.append(line)
            continue

        m = re.match(r"^\*\*((?:\d+\.)+\d+[\.)]?\s+.{20,})\*\*\s*$", s)
        if m and looks_like_clause_not_heading(m.group(1)):
            out.append(m.group(1).strip())
            continue

        m = re.match(r"^\*\*(\d+[\.)]\s+.{20,})\*\*\s*$", s)
        if m:
            out.append(m.group(1).strip())
            continue

        m = re.match(r"^\*\*([a-zđ][\.)]\s+.{20,})\*\*\s*$", s, flags=re.IGNORECASE)
        if m:
            out.append(m.group(1).strip())
            continue

        out.append(line)

    return "\n".join(out)


def demote_clause_headings_inside_articles(markdown: str) -> str:
    """Hạ cấp các khoản `1.`, `2.`, `A.` nằm bên trong `Điều ...` về văn bản thường.

    LlamaParse thường nhận nhầm các khoản ngắn dưới mỗi Điều thành heading do PDF in đậm
    hoặc do dòng đứng riêng. Trong văn bản quy phạm/quy chế, `Điều n...` mới là heading;
    các dòng `1.`, `2.`, `3.` ngay sau Điều là khoản/nội dung con, không phải đề mục.

    Quy tắc ngữ cảnh:
    - Khi gặp heading `Điều ...` thì bật ngữ cảnh trong Điều.
    - Trong ngữ cảnh này, heading dạng `1. ...`, `2) ...`, `A. ...` sẽ bị gỡ dấu `#`.
    - Page marker, comment, dòng trắng và bảng không làm mất ngữ cảnh Điều.
    - Khi gặp tiêu đề lớn/La Mã/phụ lục hoặc heading không phải khoản thì thoát ngữ cảnh.
    """

    out: list[str] = []
    in_fence = False
    in_article = False

    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue

        if in_fence:
            out.append(line)
            continue

        if is_comment_line(line) or is_table_line(line) or not line.strip():
            out.append(line)
            continue

        found = unwrap_heading(line)
        if not found:
            out.append(line)
            continue

        level, text = found
        clean_text = strip_inline_markdown(text).strip()

        if is_article_heading(clean_text):
            in_article = True
            out.append(make_heading(4, clean_text))
            continue

        if in_article and (
            is_numbered_heading(clean_text)
            or is_upper_alpha_heading(clean_text)
            or (is_decimal_section_marker(clean_text) and looks_like_clause_not_heading(clean_text))
        ):
            out.append(clean_text)
            continue

        # Các heading cấu trúc cấp cao mở sang phần mới, không còn nằm trong Điều hiện tại.
        if level <= 2 or is_major_title(clean_text) or is_roman_heading(clean_text) or is_luu_do_heading(clean_text):
            in_article = False

        out.append(line)

    return "\n".join(out)


def demote_clause_like_decimal_headings(markdown: str) -> str:
    """Gỡ heading cho các dòng `2.1`, `2.2` là khoản/câu nội dung.

    Hàm này chạy sau bước promote/normalize để bắt cả 2 nguồn lỗi:
    - LlamaParse sinh sẵn `### 2.1. Sinh viên phải ...`;
    - postprocess cũ từng promote dòng plain/bold `2.1. ...` thành heading.
    """

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

        found = unwrap_heading(line)
        if found:
            _, text = found
            clean_text = strip_inline_markdown(text).strip()
            if is_decimal_section_marker(clean_text) and looks_like_clause_not_heading(clean_text):
                out.append(clean_text)
                continue

        out.append(line)

    return "\n".join(out)


def collapse_excess_blank_lines(markdown: str) -> str:
    """Gộp nhiều hơn 2 dòng trắng liên tiếp để Markdown gọn và ổn định."""

    markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)
    return markdown.strip() + "\n"


def postprocess_llamaparse_markdown(markdown: str) -> str:
    """Hàm chính để hậu xử lý Markdown raw của LlamaParse."""

    frontmatter, body = split_yaml_frontmatter(markdown)

    body = normalize_existing_headings(body)
    body = promote_structural_heading_lines(body)
    body = promote_bold_article_lines(body)
    body = demote_clause_headings_inside_articles(body)
    body = demote_clause_like_decimal_headings(body)
    body = demote_bold_numbered_lines(body)
    body = normalize_form_document_lines(body)
    body = split_html_tables_at_embedded_page_markers(body)
    body = fix_html_table_page_continuations(body)
    body = convert_html_tables_to_markdown(body)
    body = normalize_tables(body)
    body = merge_continued_tables(body)
    body = collapse_excess_blank_lines(body)

    if frontmatter:
        return frontmatter.rstrip() + "\n\n" + body
    return body


def process_file(input_path: str | Path, output_path: str | Path | None = None) -> Path:
    """Đọc một file Markdown, chạy postprocess, ghi ra output_path hoặc ghi đè input."""

    inp = Path(input_path)
    out = Path(output_path) if output_path is not None else inp

    markdown = inp.read_text(encoding="utf-8")
    fixed = postprocess_llamaparse_markdown(markdown)
    out.write_text(fixed, encoding="utf-8")
    return out


def build_parser() -> argparse.ArgumentParser:
    """Tạo CLI parser để chạy file này độc lập từ command line."""

    parser = argparse.ArgumentParser(description="Postprocess Markdown raw từ LlamaParse.")
    parser.add_argument("input", help="File Markdown đầu vào")
    parser.add_argument("-o", "--output", default=None, help="File Markdown đầu ra; bỏ trống để ghi đè")
    return parser


def main() -> int:
    """Entry point CLI."""

    args = build_parser().parse_args()
    out = process_file(args.input, args.output)
    print(f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
