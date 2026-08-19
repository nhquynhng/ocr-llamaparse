from __future__ import annotations

"""
Postprocess Markdown do LlamaParse sinh ra.

File này chỉ giữ các luật hậu xử lý văn bản/heading chung.
Tất cả luật liên quan đến bảng đã được tách sang `table_postprocess.py`.

Các lỗi đang xử lý:
1. Heading không đồng nhất: cùng là `Điều 1`, `Điều 2` nhưng lúc là ##, lúc là bold.
2. Dòng list/khoản dưới `Điều ...` bị bọc bold hoặc bị promote thành heading: **2. ...** trong khi đây chỉ là nội dung con.
3. Chuẩn hóa form/đơn/giấy qua module `form_postprocess`.
4. Chuẩn hóa bảng qua module `table_postprocess`.
5. Cleanup dòng trắng.
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


SINGLE_LIST_MARKER_RE = re.compile(
    # Chỉ nhận marker một cấp; `1.1` được xử lý riêng như mục thập phân.
    r"^\s*(?P<marker>(?:\d{1,2}|[A-Za-zĐđ])(?P<delimiter>[\.)/]))\s+(?P<body>\S.*?)\s*$",
)


LIST_INTRO_CUE_RE = re.compile(
    r"\b(luu y|bao gom|cu the|ho so gom)\b",
    flags=re.IGNORECASE,
)


try:
    from src.postprocess.form_postprocess import normalize_form_document_lines
except ModuleNotFoundError:  # Cho phép chạy trực tiếp file này bằng python path/to/file.py
    from form_postprocess import normalize_form_document_lines


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
    """Nhận diện heading La Mã viết HOA; không nhầm item chữ thường `i.`."""

    return bool(re.match(r"^[IVXLCDM]{1,8}\.\s+\S+", text.strip()))


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


def split_single_list_marker(text: str) -> tuple[str, str, str] | None:
    """Tách marker một cấp thành `(marker, delimiter, body)` để phân loại item/heading."""

    clean = strip_inline_markdown(text).strip()
    match = SINGLE_LIST_MARKER_RE.match(clean)
    if not match:
        return None
    return match.group("marker"), match.group("delimiter"), match.group("body").strip()


def is_numbered_marker(text: str) -> bool:
    """Kiểm tra dòng có marker số một cấp như `1.`, `1)` hoặc `1/`."""

    parsed = split_single_list_marker(text)
    return bool(parsed and parsed[0][0].isdigit())


def is_upper_alpha_marker(text: str) -> bool:
    """Kiểm tra dòng có marker chữ cái in hoa như `A.`, `A)` hoặc `A/`."""

    parsed = split_single_list_marker(text)
    return bool(parsed and parsed[0][0].isalpha() and parsed[0][0].isupper())


def is_definite_list_item(text: str) -> bool:
    """Nhận diện marker mà PDF quy định mặc định phải giữ là list item.

    `1)`, chữ cái với `)`/`/`, và chữ cái thường đều không được tự động
    tạo parent heading. Riêng `a.` sẽ được xét ngoại lệ ở bộ phân loại ngữ cảnh.
    """

    parsed = split_single_list_marker(text)
    if not parsed:
        return False

    marker, delimiter, _ = parsed
    first = marker[0]
    if first.isdigit():
        return delimiter == ")"
    if first.islower():
        return delimiter in {")", "/"}
    return delimiter in {")", "/"}


def contextual_marker_kind(text: str) -> tuple[str, str] | None:
    """Trả về loại marker mơ hồ và nội dung cần xét bằng ngữ cảnh tài liệu."""

    parsed = split_single_list_marker(text)
    if not parsed:
        return None

    marker, delimiter, body = parsed
    first = marker[0]
    if first.isdigit() and delimiter in {".", "/"}:
        return ("number_dot" if delimiter == "." else "number_slash"), body
    if first.isupper() and delimiter == ".":
        return "upper_dot", body
    if first.islower() and delimiter == ".":
        return "lower_dot", body
    return None


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

    # Mục thập phân có luật riêng. Marker một cấp (`1.`, `1)`, `A.`...)
    # được để nguyên tại đây và phân loại sau bằng ngữ cảnh toàn tài liệu.
    if is_decimal_section_marker(clean_text):
        if looks_like_clause_not_heading(clean_text):
            return clean_text
        if is_decimal_section_heading(clean_text):
            return make_heading(4, clean_text)

    if looks_like_long_sentence(clean_text):
        return clean_text

    return line


def is_full_line_bold(line: str) -> str | None:
    """Nếu cả dòng là bold Markdown thì trả về nội dung bên trong, ngược lại None."""

    m = re.match(r"^\s*\*\*(.+?)\*\*\s*$", line.strip())
    if not m:
        return None
    return m.group(1).strip()


def structural_line_content(line: str) -> tuple[str, bool, bool]:
    """Lấy nội dung thuần của dòng cùng tín hiệu heading/bold do OCR tạo."""

    found = unwrap_heading(line)
    content = found[1] if found else line.strip()
    bold_content = is_full_line_bold(content)
    if bold_content is not None:
        content = bold_content
    return strip_inline_markdown(content).strip(), found is not None, bold_content is not None


def build_contextual_marker_index(
    lines: list[str],
) -> tuple[dict[int, tuple[str, str]], set[int]]:
    """Lập chỉ mục marker mơ hồ, đồng thời loại code fence, table và comment."""

    candidates: dict[int, tuple[str, str]] = {}
    eligible_lines: set[int] = set()
    in_fence = False

    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or is_table_line(line) or is_comment_line(line):
            continue

        eligible_lines.add(index)
        content, _, _ = structural_line_content(line)
        candidate = contextual_marker_kind(content)
        if candidate is not None:
            candidates[index] = candidate

    return candidates, eligible_lines


def has_contextual_sibling(
    lines: list[str],
    index: int,
    kind: str,
    candidates: dict[int, tuple[str, str]],
    eligible_lines: set[int],
) -> bool:
    """Tìm sibling cùng dạng marker trong phạm vi section gần nhất."""

    for direction in (-1, 1):
        stop = max(-1, index - 60) if direction < 0 else min(len(lines), index + 61)
        for other in range(index + direction, stop, direction):
            if other not in eligible_lines:
                continue
            candidate = candidates.get(other)
            if candidate and candidate[0] == kind:
                return True

            found = unwrap_heading(lines[other])
            if found and other not in candidates and found[0] <= 2:
                break

    return False


def has_own_body_below(
    lines: list[str],
    index: int,
    candidates: dict[int, tuple[str, str]],
) -> bool:
    """Kiểm tra sau candidate có paragraph, list, table hoặc code làm body riêng hay không."""

    for other in range(index + 1, min(len(lines), index + 16)):
        line = lines[other]
        stripped = line.strip()
        if not stripped or is_comment_line(line):
            continue
        if other in candidates or unwrap_heading(line):
            return False
        if stripped.startswith("```") or is_table_line(line):
            return True
        content, _, _ = structural_line_content(line)
        if content.rstrip().endswith(":") and LIST_INTRO_CUE_RE.search(normalize_key(content)):
            return False
        return True
    return False


def is_under_higher_heading(
    lines: list[str],
    index: int,
    candidates: dict[int, tuple[str, str]],
) -> bool:
    """Tìm heading cha H1/H2 gần candidate để bổ sung tín hiệu cấu trúc."""

    for other in range(index - 1, max(-1, index - 60), -1):
        line = lines[other]
        if not line.strip() or is_comment_line(line) or is_table_line(line):
            continue
        if other in candidates:
            continue
        found = unwrap_heading(line)
        if found:
            return found[0] <= 2
    return False


def follows_list_intro(lines: list[str], index: int) -> bool:
    """Phát hiện candidate đứng sau `Lưu ý`, `Bao gồm`, `Cụ thể`, `Hồ sơ gồm`."""

    for other in range(index - 1, max(-1, index - 8), -1):
        line = lines[other]
        if not line.strip() or is_comment_line(line):
            continue
        content, _, _ = structural_line_content(line)
        return bool(LIST_INTRO_CUE_RE.search(normalize_key(content)))
    return False


def looks_like_contextual_item(body: str, lines: list[str], index: int) -> bool:
    """Loại candidate có dấu hiệu câu hoàn chỉnh hoặc phần tử của một danh sách."""

    clean = body.strip()
    key = normalize_key(clean)
    word_count = len(re.findall(r"\w+", key, flags=re.UNICODE))

    if follows_list_intro(lines, index):
        return True
    if len(clean) > 100 or word_count > 18:
        return True
    if re.search(r"[.;!?]\s*$", clean):
        return True
    if looks_like_clause_not_heading(clean):
        return True
    if clean.count(",") >= 2 or ";" in clean:
        return True
    return False


def is_visually_title_like(body: str) -> bool:
    """Nhận diện tín hiệu trình bày: in hoa toàn cụm hoặc kết thúc bằng dấu hai chấm."""

    letters = [char for char in body if char.isalpha()]
    is_upper = bool(letters) and all(not char.islower() for char in letters)
    return is_upper or body.rstrip().endswith(":")


def should_promote_contextual_candidate(
    lines: list[str],
    index: int,
    candidate: tuple[str, str],
    candidates: dict[int, tuple[str, str]],
    eligible_lines: set[int],
    was_heading: bool,
    was_bold: bool,
) -> bool:
    """Quyết định marker mơ hồ có đủ nhiều tín hiệu để trở thành H3 hay không.

    Precision được ưu tiên: candidate bắt buộc phải có body riêng, không giống
    câu/list item, và phải có thêm tín hiệu sibling, kiểu chữ hoặc heading cha.
    Chữ thường `a.` cần bằng chứng mạnh hơn các dạng còn lại.
    """

    kind, body = candidate
    key = normalize_key(body)
    word_count = len(re.findall(r"\w+", key, flags=re.UNICODE))
    if not body or len(body) > 90 or word_count > 14:
        return False
    if looks_like_contextual_item(body, lines, index):
        return False
    if not has_own_body_below(lines, index, candidates):
        return False

    score = 1  # Dòng ngắn và giống tên section.
    if has_contextual_sibling(lines, index, kind, candidates, eligible_lines):
        score += 1
    if was_heading or was_bold or is_visually_title_like(body):
        score += 1
    if is_under_higher_heading(lines, index, candidates):
        score += 1

    return score >= (3 if kind == "lower_dot" else 2)


def structural_heading_level(text: str) -> int | None:
    """Trả cấp cho heading chắc chắn; marker một cấp được xét ở hàm ngữ cảnh."""

    clean = strip_inline_markdown(text).strip()
    if not clean:
        return None

    if is_major_title(clean):
        return 1
    if is_roman_heading(clean) or is_luu_do_heading(clean):
        return 2
    if is_decimal_section_marker(clean):
        return 4 if is_decimal_section_heading(clean) else None
    if is_article_heading(clean):
        return 4

    return None


def promote_structural_heading_lines(markdown: str) -> str:
    """Chuẩn hóa heading chắc chắn và phân loại marker mơ hồ bằng ngữ cảnh.

    Hàm cũng hạ heading sai do OCR tạo sẵn cho các marker mặc định là item.
    Các vùng code, table và HTML comment được giữ nguyên tuyệt đối.
    """

    lines = markdown.splitlines()
    candidates, eligible_lines = build_contextual_marker_index(lines)
    out: list[str] = []
    in_fence = False

    for index, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue

        if in_fence or is_table_line(line) or is_comment_line(line):
            out.append(line)
            continue

        content, was_heading, was_bold = structural_line_content(line)
        if not content:
            out.append(line)
            continue

        # Các marker chắc chắn là item phải được gỡ `#`/bold nếu OCR nhận sai.
        if is_definite_list_item(content):
            out.append(content if was_heading or was_bold else line)
            continue

        contextual_candidate = candidates.get(index)
        if contextual_candidate is not None:
            if should_promote_contextual_candidate(
                lines,
                index,
                contextual_candidate,
                candidates,
                eligible_lines,
                was_heading,
                was_bold,
            ):
                out.append(make_heading(3, content))
            else:
                out.append(content if was_heading or was_bold else line)
            continue

        if was_heading:
            out.append(line)
            continue

        level = structural_heading_level(content)

        if level is not None:
            out.append(make_heading(level, content))
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
    """Gỡ bold sai quanh khoản đánh số, nhưng không sửa code/table/comment."""

    lines = markdown.splitlines()
    out: list[str] = []
    in_fence = False

    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue

        if in_fence or is_table_line(line) or is_comment_line(line):
            out.append(line)
            continue

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
            is_numbered_marker(clean_text)
            or is_upper_alpha_marker(clean_text)
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
