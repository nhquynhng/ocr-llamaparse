from __future__ import annotations

"""
Postprocess Markdown do LlamaParse sinh ra.

Mục tiêu của file này:
- Chỉ sửa các lỗi cấu trúc phổ biến do LlamaParse/OCR gây ra.
- Không viết riêng cho một loại văn bản cụ thể.
- Không OCR lại PDF, không gọi LlamaParse, không can thiệp metadata validation.
- Có thể gọi từ main.py sau khi nhận raw markdown từ LlamaParse.

Các lỗi đang xử lý:
1. Heading không đồng nhất: cùng là "Điều 1", "Điều 2" nhưng lúc là ##, lúc là #.
2. Dòng list bị bọc bold toàn dòng: **2. ...** trong khi PDF chỉ là mục đánh số thường.
3. Bảng bị tách qua trang và lặp header hoặc sinh header giả.
4. Bảng có cột rỗng thừa do LlamaParse nhận nhầm colspan/rowspan.
5. Header bảng bị lặp tiền tố dài ở mọi cột, ví dụ "3. Đối với...<br/>Bước".
"""

import argparse
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


# Các tiêu đề độc lập thường gặp trong văn bản hành chính/trường học.
# Chỉ so khớp toàn dòng sau khi chuẩn hóa, không dùng startswith để tránh phóng to câu thường.
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


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt để phục vụ so khớp luật heading một cách ổn định."""

    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_key(text: str) -> str:
    """Chuẩn hóa chuỗi để so khớp: bỏ Markdown cơ bản, bỏ dấu, lowercase, gộp khoảng trắng."""

    text = re.sub(r"^#+\s*", "", text.strip())
    text = text.strip("*_` \t")
    text = re.sub(r"<[^>]+>", "", text)
    text = strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9/.\-\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_yaml_frontmatter(markdown: str) -> tuple[str, str]:
    """Tách YAML front matter để postprocess không sửa nhầm metadata ở đầu file."""

    lines = markdown.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return "", markdown

    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            return "".join(lines[: idx + 1]), "".join(lines[idx + 1 :])

    return "", markdown


def is_table_line(line: str) -> bool:
    """Nhận diện một dòng thuộc Markdown table."""

    s = line.strip()
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 2


def is_table_separator(line: str) -> bool:
    """Nhận diện dòng separator của Markdown table, ví dụ | --- | --- |."""

    if not is_table_line(line):
        return False
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r"\s*:?-{2,}:?\s*", cell or "") for cell in cells)


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
    return f"{'#' * level} {text.strip()}"


def is_major_title(text: str) -> bool:
    """Kiểm tra dòng có phải tiêu đề lớn độc lập như QUYẾT ĐỊNH, QUY CHẾ, NỘI QUY."""

    return normalize_key(text) in EXACT_MAJOR_TITLES


def is_article_heading(text: str) -> bool:
    """Nhận diện heading dạng Điều 1. ..., Điều 2. ..."""

    return bool(re.match(r"^Điều\s+\d+[.:]?\s+\S+", text.strip(), re.IGNORECASE))


def is_roman_heading(text: str) -> bool:
    """Nhận diện heading dạng I. ..., II. ..., III. ..."""

    return bool(re.match(r"^[IVXLCDM]{1,8}\.\s+\S+", text.strip(), re.IGNORECASE))


def is_luu_do_heading(text: str) -> bool:
    """Nhận diện heading 'LƯU ĐỒ 1', 'LƯU ĐỒ 2' có thể có HTML underline."""

    key = normalize_key(text)
    return bool(re.match(r"^luu do\s+\d+", key))


def is_numbered_heading(text: str) -> bool:
    """Nhận diện heading dạng 1. ..., 2. ... nếu dòng đang được đánh heading."""

    return bool(re.match(r"^\d+[\.)]\s+\S+", text.strip()))


def looks_like_long_sentence(text: str) -> bool:
    """Ước lượng dòng giống đoạn văn thường hơn là tiêu đề."""

    plain = re.sub(r"[*_`]+", "", text).strip()
    if len(plain) >= 140:
        return True
    if len(plain) >= 90 and re.search(r"[.;,)]$", plain):
        return True
    # Các câu mở đầu kiểu "Nội quy này...", "Quy định này..." không phải heading.
    if re.match(r"^(Nội quy|Quy định|Quy chế|Quyết định|Kế hoạch|Thông báo)\s+này\b", plain, re.I):
        return True
    return False


def normalize_heading_line(line: str) -> str:
    """Chuẩn hóa một dòng heading Markdown đã tồn tại từ LlamaParse."""

    found = unwrap_heading(line)
    if not found:
        return line

    level, text = found
    clean_text = text.strip()

    # Tiêu đề văn bản độc lập giữ H1.
    if is_major_title(clean_text):
        return make_heading(1, clean_text)

    # "QUYẾT ĐỊNH:" ở giữa văn bản quyết định cũng có thể là heading lớn.
    if normalize_key(clean_text).rstrip(":") == "quyet dinh":
        return make_heading(1, clean_text)

    # Các "Điều n. ..." trong cùng một văn bản phải cùng cấp.
    if is_article_heading(clean_text):
        return make_heading(2, clean_text)

    # Các mục La Mã trong văn bản hành chính thường là cấp 2.
    if is_roman_heading(clean_text):
        return make_heading(2, clean_text)

    # Lưu đồ nằm dưới phần quy trình, không nên thành H1.
    if is_luu_do_heading(clean_text):
        return make_heading(2, clean_text)

    # Heading bắt đầu bằng số mà bị H1 thì hạ xuống H2 để tránh phá cây mục.
    if level == 1 and is_numbered_heading(clean_text):
        return make_heading(2, clean_text)

    # Nếu LlamaParse phóng to một câu dài thành heading thì hạ về đoạn văn thường.
    if looks_like_long_sentence(clean_text):
        return clean_text

    return line


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
    """Gỡ bold toàn dòng cho các khoản đánh số thường bị LlamaParse hiểu nhầm là nhấn mạnh."""

    lines = markdown.splitlines()
    out: list[str] = []

    for idx, line in enumerate(lines):
        s = line.strip()

        # Ví dụ: **2. Việc đăng ký nội trú ...** -> 2. Việc đăng ký nội trú ...
        m = re.match(r"^\*\*(\d+[\.)]\s+.{20,})\*\*\s*$", s)
        if m:
            out.append(m.group(1).strip())
            continue

        # Ví dụ: **a. Nội dung ...** -> a. Nội dung ...
        m = re.match(r"^\*\*([a-zđ][\.)]\s+.{20,})\*\*\s*$", s, flags=re.IGNORECASE)
        if m:
            out.append(m.group(1).strip())
            continue

        out.append(line)

    return "\n".join(out)


def split_table_row(line: str) -> list[str]:
    """Tách một dòng Markdown table thành danh sách cell, xử lý đơn giản dấu | hai đầu."""

    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [cell.strip() for cell in s.split("|")]


def build_table_row(cells: Sequence[str]) -> str:
    """Ghép danh sách cell thành một dòng Markdown table."""

    return "| " + " | ".join(cell.strip() for cell in cells) + " |"


def table_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """Trả về danh sách block table theo khoảng [start, end)."""

    blocks: list[tuple[int, int]] = []
    i = 0

    while i < len(lines):
        if not is_table_line(lines[i]):
            i += 1
            continue

        start = i
        while i < len(lines) and is_table_line(lines[i]):
            i += 1
        blocks.append((start, i))

    return blocks


def is_separator_cell(cell: str) -> bool:
    """Kiểm tra một cell chỉ chứa dấu gạch của dòng separator table."""

    return bool(re.fullmatch(r"\s*:?-{1,}:?\s*", cell or ""))


def remove_empty_trailing_columns(rows: list[list[str]]) -> list[list[str]]:
    """
    Xóa các cột rỗng hoàn toàn ở cuối bảng do LlamaParse sinh thừa.

    Khi xét rỗng, hàm bỏ qua dấu gạch ở dòng separator vì các cell "---"
    không phải dữ liệu thật.
    """

    if not rows:
        return rows

    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]

    def meaningful(cell: str) -> bool:
        return bool(cell.strip()) and not is_separator_cell(cell)

    while width > 1:
        if all(not meaningful(row[width - 1]) for row in normalized):
            width -= 1
            normalized = [row[:width] for row in normalized]
        else:
            break

    return normalized


def drop_repeated_separator_rows(rows: list[list[str]]) -> list[list[str]]:
    """
    Bỏ các dòng separator thừa nằm giữa bảng.

    LlamaParse đôi khi cắt bảng qua trang rồi để lại một dòng kiểu
    "| -- | --- | ..." giữa data rows. Dòng này làm Markdown table hỏng.
    """

    if len(rows) <= 2:
        return rows

    cleaned: list[list[str]] = []
    for idx, row in enumerate(rows):
        is_sep = row and all(is_separator_cell(cell) or not cell.strip() for cell in row)
        if is_sep and idx != 1:
            continue
        cleaned.append(row)
    return cleaned


def remove_common_header_prefix(cells: list[str]) -> list[str]:
    """
    Xóa tiền tố lặp trong header bảng.

    Ví dụ LlamaParse có thể sinh:
    "3. Đối với ...<br/>Bước",
    "3. Đối với ...<br/>Lưu đồ",
    ...
    Hàm này giữ phần sau <br/> cuối cùng nếu mọi header đều có cùng tiền tố.
    """

    if len(cells) < 2:
        return cells

    if not all("<br" in cell.lower() for cell in cells if cell.strip()):
        return cells

    suffixes: list[str] = []
    prefixes: list[str] = []

    for cell in cells:
        parts = re.split(r"<br\s*/?>", cell, flags=re.IGNORECASE)
        if len(parts) < 2:
            return cells
        prefixes.append("<br/>".join(parts[:-1]).strip())
        suffixes.append(parts[-1].strip())

    # Nếu phần đầu giống nhau đáng kể thì bỏ prefix.
    if prefixes and len(set(prefixes)) == 1 and len(prefixes[0]) >= 20:
        return suffixes

    return cells


def normalize_single_table(block: list[str]) -> list[str]:
    """Chuẩn hóa một block Markdown table: đều cột, bỏ cột rỗng thừa, sửa header lặp prefix."""

    rows = [split_table_row(line) for line in block]
    if not rows:
        return block

    rows = remove_empty_trailing_columns(rows)
    rows = drop_repeated_separator_rows(rows)

    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]

    if rows:
        rows[0] = remove_common_header_prefix(rows[0])

    # Đảm bảo dòng thứ 2 là separator nếu block có header.
    if len(rows) >= 2:
        if is_table_separator(block[1]):
            rows[1] = ["---"] * width
        elif not any(cell.strip() for cell in rows[1]):
            rows.insert(1, ["---"] * width)

    return [build_table_row(row) for row in rows]


def normalize_tables(markdown: str) -> str:
    """Chuẩn hóa hình thức các Markdown table trong toàn bộ văn bản."""

    lines = markdown.splitlines()
    blocks = table_blocks(lines)
    if not blocks:
        return markdown

    out: list[str] = []
    last = 0

    for start, end in blocks:
        out.extend(lines[last:start])
        out.extend(normalize_single_table(lines[start:end]))
        last = end

    out.extend(lines[last:])
    return "\n".join(out)


def header_signature(header_line: str) -> tuple[str, ...]:
    """Tạo chữ ký header bảng để phát hiện header lặp ở bảng nối trang."""

    cells = split_table_row(header_line)
    return tuple(normalize_key(cell) for cell in cells if normalize_key(cell))



def is_continuation_data_row(row_line: str) -> bool:
    """Nhận diện block table bắt đầu bằng data row, ví dụ "| 05 | ..." sau khi qua trang."""

    cells = split_table_row(row_line)
    if not cells:
        return False
    first = normalize_key(cells[0])
    return bool(re.fullmatch(r"\d{1,3}", first)) or first == ""


def is_suspicious_continuation_header(header_line: str) -> bool:
    """Nhận diện header giả ở đầu bảng nối trang, thường chứa mảnh chữ của dòng trước."""

    cells = split_table_row(header_line)
    non_empty = [c for c in cells if c.strip()]
    if not non_empty:
        return True

    key = " ".join(normalize_key(c) for c in non_empty)
    suspicious_fragments = {
        "cao toan ktx",
        "canh cao",
        "buoc ra khoi ktx",
        "nhac nho",
        "khien trach",
    }

    if any(fragment in key for fragment in suspicious_fragments) and len(non_empty) <= 4:
        return True

    # Header thật thường có các từ như TT, Nội dung, Lần, Ghi chú, Bước, Lưu đồ...
    real_header_words = {"tt", "noi dung", "lan", "ghi chu", "buoc", "luu do", "nguoi thuc hien", "thoi gian"}
    if not any(word in key for word in real_header_words) and len(key) < 80:
        return True

    return False


def merge_continued_tables(markdown: str) -> str:
    """
    Gộp các bảng bị LlamaParse tách qua trang.

    Heuristic:
    - Hai block table gần nhau, chỉ cách bằng dòng trắng/heading trang/comment.
    - Bảng sau có header trùng bảng trước hoặc header giả đáng ngờ.
    - Khi gộp thì bỏ header/separator của bảng sau.
    """

    lines = markdown.splitlines()
    i = 0
    out: list[str] = []

    while i < len(lines):
        if not is_table_line(lines[i]):
            out.append(lines[i])
            i += 1
            continue

        # Lấy block table hiện tại.
        current: list[str] = []
        while i < len(lines) and is_table_line(lines[i]):
            current.append(lines[i])
            i += 1

        current = normalize_single_table(current)

        # Thử gộp liên tiếp các block table sau đó.
        while True:
            gap_start = i
            gap: list[str] = []
            while i < len(lines) and not is_table_line(lines[i]):
                # Cho phép bỏ qua khoảng trắng và comment/page marker giữa 2 bảng.
                if lines[i].strip() and not is_comment_line(lines[i]):
                    break
                gap.append(lines[i])
                i += 1

            if i >= len(lines) or not is_table_line(lines[i]):
                # Không có bảng kế tiếp, trả lại gap.
                out.extend(current)
                out.extend(gap)
                break

            next_block: list[str] = []
            while i < len(lines) and is_table_line(lines[i]):
                next_block.append(lines[i])
                i += 1

            next_block = normalize_single_table(next_block)
            can_merge = False

            continuation_data = bool(next_block) and is_continuation_data_row(next_block[0])

            if len(current) >= 2 and len(next_block) >= 1:
                same_header = len(next_block) >= 2 and header_signature(current[0]) == header_signature(next_block[0])
                suspicious_header = is_suspicious_continuation_header(next_block[0])
                can_merge = same_header or suspicious_header or continuation_data

            if can_merge:
                if continuation_data:
                    # Bảng sau bắt đầu bằng data row thật, giữ dòng đầu và chỉ bỏ separator thừa.
                    next_rows = [split_table_row(row) for row in next_block]
                    next_rows = drop_repeated_separator_rows(next_rows)
                    data_rows = [build_table_row(row) for row in next_rows if not all(is_separator_cell(c) or not c.strip() for c in row)]
                else:
                    # Bảng sau có header lặp/header giả, bỏ header + separator.
                    data_rows = next_block[2:] if len(next_block) >= 2 and is_table_separator(next_block[1]) else next_block

                current.extend(data_rows)
                current = normalize_single_table(current)
                continue

            # Không gộp được: ghi current, gap, rồi xử lý next_block ở vòng ngoài bằng cách push trực tiếp.
            out.extend(current)
            out.extend(gap)
            current = next_block
            # tiếp tục while để xét next_block với bảng sau nữa

        # while inner đã ghi current trong các nhánh break.

    return "\n".join(out)



HTML_TABLE_RE = re.compile(r"<table\b.*?</table>", flags=re.IGNORECASE | re.DOTALL)
THEAD_RE = re.compile(r"<thead\b.*?</thead>", flags=re.IGNORECASE | re.DOTALL)
TBODY_RE = re.compile(r"<tbody\b[^>]*>(.*?)</tbody>", flags=re.IGNORECASE | re.DOTALL)
TR_RE = re.compile(r"<tr\b.*?</tr>", flags=re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")


def strip_html_tags(html: str) -> str:
    """Xóa HTML tag để lấy text thô phục vụ nhận diện header/table continuation."""

    text = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def is_page_marker_gap(gap: str) -> bool:
    """Kiểm tra phần nằm giữa hai table có chỉ là marker phân trang hay không.

    Cho phép các dòng:
    - dòng trắng;
    - `---`;
    - HTML comment `<!-- page: N -->`, `<!-- extraction: ... -->`;
    - dòng chỉ chứa số trang.
    Nếu có nội dung thật thì không merge table qua gap này.
    """

    for line in gap.splitlines():
        s = line.strip()
        if not s:
            continue
        if s == "---":
            continue
        if s.startswith("<!--") and s.endswith("-->"):
            continue
        if re.fullmatch(r"\d+", s):
            continue
        return False
    return True


def extract_page_comments(gap: str) -> str:
    """Giữ lại page/extraction comment khi merge table, bỏ `---` và dòng số trang.

    Comment được đặt bên trong `<tbody>` để vẫn tra được ranh giới trang nhưng
    không làm hỏng HTML table như khi chèn Markdown horizontal rule `---`.
    """

    comments: list[str] = []
    for line in gap.splitlines():
        s = line.strip()
        if s.startswith("<!--") and s.endswith("-->"):
            comments.append(f"  {s}")
    return "\n".join(comments)


def html_table_has_real_header(table_html: str) -> bool:
    """Nhận diện một HTML table có header thật hay chỉ là header giả do cắt trang.

    Header thật thường chứa các từ khóa như TT, Nội dung, Lần, Ghi chú, Bước.
    Header giả thường chỉ có một mảnh chữ bị cắt từ dòng cuối trang trước, ví dụ
    `cáo toàn KTX`.
    """

    m = THEAD_RE.search(table_html)
    if not m:
        return False

    header_text = normalize_key(strip_html_tags(m.group(0)))
    if not header_text:
        return False

    real_header_words = {
        "tt",
        "noi dung",
        "lan",
        "ghi chu",
        "buoc",
        "luu do",
        "nguoi thuc hien",
        "thoi gian",
        "hinh thuc xu ly",
    }
    return any(word in header_text for word in real_header_words)


def html_table_is_continuation(table_html: str) -> bool:
    """Xác định table HTML có phải phần tiếp nối của bảng trước hay không.

    Dấu hiệu continuation:
    - Không có `<thead>` nhưng có `<tbody>`;
    - Có `<thead>` nhưng header không giống header thật;
    - Dòng dữ liệu đầu tiên bắt đầu bằng số thứ tự như 05, 20.
    """

    tbody = TBODY_RE.search(table_html)
    if not tbody:
        return False

    if not THEAD_RE.search(table_html):
        return True

    if not html_table_has_real_header(table_html):
        return True

    rows = TR_RE.findall(tbody.group(1))
    if not rows:
        return False
    first_row_text = normalize_key(strip_html_tags(rows[0]))
    return bool(re.match(r"^\d{1,3}\b", first_row_text))


def fake_thead_fragment(table_html: str) -> str:
    """Lấy text trong fake `<thead>` nếu header đó là mảnh bị cắt qua trang."""

    m = THEAD_RE.search(table_html)
    if not m or html_table_has_real_header(table_html):
        return ""

    fragment = strip_html_tags(m.group(0))
    fragment = re.sub(r"\s+", " ", fragment).strip()
    return fragment


def append_fragment_to_previous_broken_cell(table_html: str, fragment: str) -> str:
    """Nối mảnh text ở đầu trang sau vào cell bị cắt ở cuối trang trước.

    Ví dụ cụ thể thường gặp:
    `<td colspan="2">Truy thu tiền, cảnh</td>` + fake header `cáo toàn KTX`
    thành `<td colspan="2">Truy thu tiền, cảnh cáo toàn KTX</td>`.
    """

    if not fragment:
        return table_html

    # Case phổ biến: một cell kết thúc bằng "cảnh" và fragment là "cáo ...".
    if normalize_key(fragment).startswith("cao "):
        matches = list(re.finditer(r"(<td\b[^>]*>)(.*?cảnh)\s*(</td>)", table_html, flags=re.IGNORECASE | re.DOTALL))
        if matches:
            m = matches[-1]
            replacement = f"{m.group(1)}{m.group(2)} {fragment}{m.group(3)}"
            return table_html[: m.start()] + replacement + table_html[m.end() :]

    return table_html


def tbody_inner(table_html: str) -> str:
    """Trả về phần bên trong `<tbody>` của một HTML table."""

    m = TBODY_RE.search(table_html)
    return m.group(1).strip() if m else ""


def replace_tbody_inner(table_html: str, new_inner: str) -> str:
    """Thay nội dung `<tbody>` của HTML table bằng `new_inner`."""

    return TBODY_RE.sub(lambda m: f"<tbody>\n{new_inner.rstrip()}\n  </tbody>", table_html, count=1)


def merge_two_html_tables(first_table: str, gap: str, second_table: str) -> str:
    """Gộp table HTML thứ hai vào table thứ nhất nếu chúng là cùng một bảng.

    Hàm giữ page marker dưới dạng HTML comment bên trong tbody và bỏ wrapper
    `<table>...</table>` của bảng tiếp nối.
    """

    fragment = fake_thead_fragment(second_table)
    first_table = append_fragment_to_previous_broken_cell(first_table, fragment)

    first_body = tbody_inner(first_table)
    second_body = tbody_inner(second_table)
    comments = extract_page_comments(gap)

    pieces = [first_body.rstrip()]
    if comments:
        pieces.append(comments)
    if second_body:
        pieces.append(second_body.lstrip())

    return replace_tbody_inner(first_table, "\n".join(pieces))



EMBEDDED_PAGE_MARKER_RE = re.compile(
    r"\s*<!--\s*page\s*:\s*(\d+)\s*-->\s*<!--\s*extraction\s*:\s*([^>]+?)\s*-->\s*",
    flags=re.IGNORECASE,
)


def build_table_from_tbody(tbody_content: str, thead_html: str = "") -> str:
    """Tạo HTML table từ phần tbody đã có.

    Hàm dùng khi cần tách một bảng HTML đã bị merge nhầm qua nhiều trang
    thành nhiều bảng riêng theo đúng ranh giới page PDF.
    """

    pieces = ["<table>"]
    if thead_html.strip():
        pieces.append(thead_html.strip())
    pieces.append("  <tbody>")
    pieces.append(tbody_content.strip())
    pieces.append("  </tbody>")
    pieces.append("</table>")
    return "\n".join(pieces)


def split_html_tables_at_embedded_page_markers(markdown: str) -> str:
    """Tách lại HTML table nếu page marker đang nằm bên trong `<tbody>`.

    Lỗi này xảy ra khi bước postprocess trước đó merge bảng page 4, 5, 6
    thành một `<table>` duy nhất và nhét `<!-- page: 5 -->`, `<!-- page: 6 -->`
    vào trong table. Khi xem Markdown preview sẽ không thấy cắt trang, đồng thời
    đánh số trang từ page 4 trở đi bị sai cảm giác vì toàn bộ bảng nằm trong một
    khối HTML lớn.

    Hàm này phục hồi cách trình bày giống PDF gốc:
    - page 4: table riêng chứa các dòng nằm trên page 4;
    - page 5: table riêng chứa các dòng nằm trên page 5;
    - page 6: table riêng chứa các dòng nằm trên page 6;
    - page marker `---`, `<!-- page: N -->`, dòng số trang được đặt BÊN NGOÀI
      table, không nằm trong `<tbody>`.
    """

    matches = list(HTML_TABLE_RE.finditer(markdown))
    if not matches:
        return markdown

    out: list[str] = []
    pos = 0

    for match in matches:
        table_html = match.group(0)
        out.append(markdown[pos : match.start()])
        pos = match.end()

        if not EMBEDDED_PAGE_MARKER_RE.search(table_html):
            out.append(table_html)
            continue

        tbody_match = TBODY_RE.search(table_html)
        if not tbody_match:
            out.append(table_html)
            continue

        thead_match = THEAD_RE.search(table_html)
        thead_html = thead_match.group(0) if thead_match else ""
        tbody = tbody_match.group(1)

        parts = EMBEDDED_PAGE_MARKER_RE.split(tbody)
        # parts = [tbody_truoc_marker, page_no_1, extraction_1, tbody_sau_marker_1, ...]
        first_body = parts[0].strip()
        rebuilt: list[str] = []
        if first_body:
            rebuilt.append(build_table_from_tbody(first_body, thead_html=thead_html))

        idx = 1
        while idx + 2 < len(parts):
            page_no = parts[idx].strip()
            extraction = parts[idx + 1].strip()
            page_body = parts[idx + 2].strip()
            if page_body:
                rebuilt.append(
                    "\n\n---\n\n"
                    f"<!-- page: {page_no} -->\n\n"
                    f"<!-- extraction: {extraction} -->\n\n"
                    f"{page_no}\n\n"
                    + build_table_from_tbody(page_body, thead_html="")
                )
            idx += 3

        out.append("\n\n".join(piece.rstrip() for piece in rebuilt if piece.strip()))

    out.append(markdown[pos:])
    return "".join(out)


def remove_fake_thead(table_html: str) -> str:
    """Xóa `<thead>` giả ở đầu table tiếp nối trang sau.

    LlamaParse đôi khi đưa phần chữ bị cắt ở cuối trang trước vào `<thead>`
    của trang sau, ví dụ `cáo toàn KTX`. Header này không phải header thật
    của bảng trong PDF, nên cần xóa để bảng trang sau bắt đầu trực tiếp bằng
    các dòng dữ liệu còn lại.
    """

    m = THEAD_RE.search(table_html)
    if not m or html_table_has_real_header(table_html):
        return table_html
    return table_html[: m.start()] + table_html[m.end() :]


def fix_html_table_page_continuations(markdown: str) -> str:
    """Sửa lỗi table bị cắt qua page nhưng vẫn giữ ranh giới trang PDF.

    Khác với `merge_html_tables_across_page_markers`, hàm này KHÔNG gộp các
    bảng của nhiều trang thành một `<table>` duy nhất. Mục tiêu là giữ output
    giống PDF gốc: page 4 có bảng của page 4, page 5 có bảng của page 5,
    page 6 có bảng của page 6.

    Hàm chỉ xử lý lỗi nối chữ qua trang, ví dụ:
    - cuối page 5: `<td colspan="2">Truy thu tiền, cảnh</td>`
    - đầu page 6 bị nhận nhầm thành fake `<thead>`: `cáo toàn KTX`

    Kết quả:
    - ô cuối page 5 thành `Truy thu tiền, cảnh cáo toàn KTX`;
    - fake `<thead>` ở page 6 bị xóa;
    - marker `---`, `<!-- page: 6 -->`, dòng số trang vẫn nằm ngoài table,
      nên khi xem Markdown vẫn thấy bảng được cắt theo từng trang PDF.
    """

    matches = list(HTML_TABLE_RE.finditer(markdown))
    if len(matches) < 2:
        return markdown

    tables = [m.group(0) for m in matches]

    for idx in range(len(matches) - 1):
        gap = markdown[matches[idx].end() : matches[idx + 1].start()]
        if not is_page_marker_gap(gap):
            continue

        fragment = fake_thead_fragment(tables[idx + 1])
        if not fragment:
            continue

        tables[idx] = append_fragment_to_previous_broken_cell(tables[idx], fragment)
        tables[idx + 1] = remove_fake_thead(tables[idx + 1])

    out: list[str] = []
    pos = 0
    for match, table in zip(matches, tables):
        out.append(markdown[pos : match.start()])
        out.append(table)
        pos = match.end()
    out.append(markdown[pos:])
    return "".join(out)


def merge_html_tables_across_page_markers(markdown: str) -> str:
    """Gộp HTML table qua page marker khi thực sự cần bảng liền mạch.

    Hàm này được giữ lại để tương thích, nhưng pipeline mặc định KHÔNG gọi nó
    vì người dùng đang cần giữ phân trang giống PDF gốc. Nếu một pipeline khác
    muốn ưu tiên bảng liền mạch thay vì phân trang, có thể gọi hàm này riêng.
    """

    matches = list(HTML_TABLE_RE.finditer(markdown))
    if len(matches) < 2:
        return markdown

    out: list[str] = []
    pos = 0
    i = 0

    while i < len(matches):
        current = matches[i].group(0)
        out.append(markdown[pos : matches[i].start()])
        pos = matches[i].end()
        i += 1

        while i < len(matches):
            gap = markdown[pos : matches[i].start()]
            nxt = matches[i].group(0)

            if not is_page_marker_gap(gap) or not html_table_is_continuation(nxt):
                break

            current = merge_two_html_tables(current, gap, nxt)
            pos = matches[i].end()
            i += 1

        out.append(current)

    out.append(markdown[pos:])
    return "".join(out)

def collapse_excess_blank_lines(markdown: str) -> str:
    """Gộp nhiều hơn 2 dòng trắng liên tiếp để Markdown gọn và ổn định."""

    markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)
    return markdown.strip() + "\n"


def postprocess_llamaparse_markdown(markdown: str) -> str:
    """
    Hàm chính để hậu xử lý Markdown raw của LlamaParse.

    Thứ tự xử lý:
    1. Tách YAML metadata để không sửa nhầm.
    2. Sửa heading sai cấp.
    3. Gỡ bold toàn dòng cho list item bị nhận nhầm.
    4. Chuẩn hóa bảng.
    5. Sửa lỗi table nối trang nhưng vẫn giữ ranh giới trang PDF.
    6. Cleanup dòng trắng.
    """

    frontmatter, body = split_yaml_frontmatter(markdown)

    body = normalize_existing_headings(body)
    body = demote_bold_numbered_lines(body)
    body = split_html_tables_at_embedded_page_markers(body)
    body = fix_html_table_page_continuations(body)
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
