from __future__ import annotations

"""
Hậu xử lý bảng cho Markdown do LlamaParse sinh ra.

Module này tách riêng các luật liên quan đến table khỏi
`llamaparse_postprocess.py` để file chính chỉ còn orchestration và các luật
text/heading chung.

Quy ước khi chuyển HTML table sang Markdown pipe table:
- Markdown pipe table không hỗ trợ colspan/rowspan thật.
- colspan được mô phỏng bằng cách mở rộng thành nhiều ô và lặp lại nội dung
  vào toàn bộ vùng span.
- rowspan được mô phỏng bằng cách lặp lại nội dung ở các hàng tiếp theo.
"""

import html as html_lib
import re
import unicodedata
from typing import Sequence


def strip_accents(text: str) -> str:
    """Bỏ dấu tiếng Việt để phục vụ so khớp table/header ổn định."""

    text = text.replace("Đ", "D").replace("đ", "d")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_key(text: str) -> str:
    """Chuẩn hóa chuỗi để so khớp: bỏ Markdown/HTML cơ bản, bỏ dấu, lowercase."""

    text = re.sub(r"^#+\s*", "", text.strip())
    text = text.strip("*_` \t")
    text = re.sub(r"<[^>]+>", "", text)
    text = strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9/.\-\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def is_comment_line(line: str) -> bool:
    """Bỏ qua HTML comment do pipeline hoặc LlamaParse chèn vào."""

    return line.strip().startswith("<!--") and line.strip().endswith("-->")


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


def is_generated_placeholder_header(cell: str) -> bool:
    """Nhận diện header giả do code tự sinh khi bảng bị phình cột, ví dụ `Cột 5`."""

    return bool(re.fullmatch(r"\s*Cột\s+\d+\s*", cell or "", flags=re.IGNORECASE))


def remove_empty_trailing_columns(rows: list[list[str]]) -> list[list[str]]:
    """
    Xóa các cột rỗng hoàn toàn ở cuối bảng do LlamaParse sinh thừa.

    Khi xét rỗng, hàm bỏ qua:
    - dấu gạch ở dòng separator;
    - header giả dạng `Cột 5`, `Cột 6` nếu toàn bộ dữ liệu phía dưới rỗng.

    Điều này sửa lỗi bảng bị phình thành nhiều cột chỉ vì width tạm thời
    được tính từ colspan/rowspan hoặc từ một dòng OCR lỗi.
    """

    if not rows:
        return rows

    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]

    def meaningful(row_idx: int, cell: str) -> bool:
        if not cell.strip() or is_separator_cell(cell):
            return False
        if row_idx == 0 and is_generated_placeholder_header(cell):
            return False
        return True

    while width > 1:
        if all(not meaningful(row_idx, row[width - 1]) for row_idx, row in enumerate(normalized)):
            width -= 1
            normalized = [row[:width] for row in normalized]
        else:
            break

    return normalized


def is_section_or_heading_cell(cell: str) -> bool:
    """Nhận diện cell dạng tiêu đề/mục trong bảng để mô phỏng merge cell."""

    raw = cell.strip()
    key = normalize_key(raw)
    if not key:
        return False

    return (
        raw.startswith("**")
        or bool(re.match(r"^[a-zđ]\.\s+", key))
        or bool(re.match(r"^\d+\.\s+", key))
        or key.startswith("dieu ")
        or "khung diem" in key
        or "danh gia ve" in key
        or "tieu chi de xac dinh" in key
    )


def should_compact_repeated_cell(cell: str, repeat_count: int) -> bool:
    """Quyết định có gôm các cell lặp do colspan/rowspan giả về 1 ô hay không.

    Markdown pipe table không merge thật được. Với các dòng tiêu đề/mục dài
    như `Điều 8...` hoặc `a. Ý thức...`, nếu lặp nội dung sang 2-4 cột thì
    preview rất xấu. Hàm này chỉ gôm các cell có khả năng là tiêu đề/mục dài.

    Các cụm xử lý ngắn như `Buộc ra khỏi KTX` vẫn có thể được lặp lại theo
    kiểu expand merge cũ, vì đó thường là thông tin áp dụng cho nhiều cột.
    """

    key = normalize_key(cell)
    if not key or is_separator_cell(cell):
        return False
    if re.fullmatch(r"\d+(?:[.,]\d+)?", key):
        return False

    if is_section_or_heading_cell(cell):
        return True

    # OCR các dòng dài bị colspan lặp 3-4 lần: gôm lại để tránh phình bảng.
    return repeat_count >= 3 and len(key) >= 25


def compact_repeated_span_cells(row: list[str]) -> list[str]:
    """Gôm các cell giống nhau liên tiếp về một cell, tùy trường hợp.

    Ví dụ:
    [Điều 8, Điều 8, Điều 8, '', ''] -> [Điều 8, '', '']
    [a. Ý thức..., a. Ý thức..., a. Ý thức..., '', ''] -> [a. Ý thức..., '', '']
    [Buộc ra khỏi KTX, Buộc ra khỏi KTX, Buộc ra khỏi KTX] được giữ nguyên
    nếu là cụm ngắn, để mô phỏng `colspan` áp dụng cho nhiều cột.
    """

    compacted: list[str] = []
    i = 0
    while i < len(row):
        cell = row[i]
        key = normalize_key(cell)
        j = i + 1
        while j < len(row) and key and normalize_key(row[j]) == key:
            j += 1

        repeat_count = j - i
        if repeat_count > 1 and should_compact_repeated_cell(cell, repeat_count):
            compacted.append(cell)
        else:
            compacted.extend(row[i:j])

        i = j

    return compacted


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





def is_standard_score_table_header(cells: list[str]) -> bool:
    """Nhận diện bảng đánh giá chuẩn có 3 cột: Nội dung đánh giá / Mức điểm / Ghi chú."""

    keys = [normalize_key(cell) for cell in cells]
    joined = " | ".join(keys)
    return (
        "noi dung danh gia" in joined
        and "muc diem" in joined
        and "ghi chu" in joined
    )


def is_numeric_like_cell(cell: str) -> bool:
    """Nhận diện ô điểm/số ngắn để gom về cột Mức điểm khi bảng bị phình cột."""

    key = normalize_key(cell).replace(" ", "")
    return bool(re.fullmatch(r"\**\d+(?:[.,]\d+)?\**", key))


def collapse_standard_score_table_to_three_columns(rows: list[list[str]]) -> list[list[str]]:
    """Ép bảng đánh giá chuẩn về đúng 3 cột để không lệch size qua trang.

    LlamaParse có thể sinh thêm cột vì gặp colspan/rowspan hoặc vì một vài dòng
    bị OCR thành nhiều cột, ví dụ page 5 có header:
        Nội dung đánh giá | Mức điểm | Ghi chú | Ghi chú | Cột 5 | Cột 6

    Với loại bảng này, schema thật cần giữ ổn định là 3 cột:
        Nội dung đánh giá | Mức điểm | Ghi chú

    Quy tắc:
    - Các ô lặp lại nội dung cột 1 do colspan giả sẽ bị bỏ.
    - Ô số ngắn đầu tiên sau nội dung được đưa về cột Mức điểm.
    - Các ô còn lại được nối vào Ghi chú bằng `; ` để không mất dữ liệu.
    """

    if not rows or not is_standard_score_table_header(rows[0]):
        return rows

    collapsed: list[list[str]] = []
    for row_idx, row in enumerate(rows):
        if row_idx == 0:
            collapsed.append(["Nội dung đánh giá (Thông tư 16)", "Mức điểm", "Ghi chú"])
            continue

        if row and all(is_separator_cell(cell) or not cell.strip() for cell in row):
            collapsed.append(["---", "---", "---"])
            continue

        cells = [cell.strip() for cell in row]
        content = cells[0] if cells else ""
        content_key = normalize_key(content)

        tail: list[str] = []
        for cell in cells[1:]:
            if not cell.strip():
                continue
            # Bỏ các ô lặp lại nội dung cột 1 do colspan giả.
            if content_key and normalize_key(cell) == content_key:
                continue
            # Bỏ header trùng/gia sinh nếu lẫn vào data.
            if is_generated_placeholder_header(cell):
                continue
            tail.append(cell)

        score = ""
        note_parts: list[str] = []

        for cell in tail:
            if not score and is_numeric_like_cell(cell):
                score = cell
            elif not score and normalize_key(cell).startswith("muc diem"):
                continue
            elif normalize_key(cell).startswith("ghi chu"):
                continue
            else:
                note_parts.append(cell)

        # Nếu không có ô numeric rõ ràng, lấy ô tail đầu tiên làm điểm nếu nó ngắn.
        if not score and tail:
            first = tail[0]
            if len(normalize_key(first)) <= 12:
                score = first
                note_parts = tail[1:]
            else:
                note_parts = tail

        # Tránh ghi chú bị lặp y hệt nhau.
        unique_notes: list[str] = []
        seen: set[str] = set()
        for part in note_parts:
            key = normalize_key(part)
            if not key or key in seen:
                continue
            seen.add(key)
            unique_notes.append(part)

        collapsed.append([content, score, "; ".join(unique_notes)])

    return collapsed


def normalize_single_table(block: list[str]) -> list[str]:
    """Chuẩn hóa một block Markdown table: đều cột, bỏ cột rỗng thừa, sửa header lặp prefix."""

    rows = [split_table_row(line) for line in block]
    if not rows:
        return block

    rows = [compact_repeated_span_cells(row) for row in rows]
    rows = collapse_standard_score_table_to_three_columns(rows)
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


def html_attr_int(attrs: str, name: str, default: int = 1) -> int:
    """Đọc thuộc tính số nguyên như colspan/rowspan trong th/td."""

    m = re.search(rf"\b{name}\s*=\s*['\"]?(\d+)", attrs or "", flags=re.IGNORECASE)
    if not m:
        return default
    try:
        return max(int(m.group(1)), 1)
    except ValueError:
        return default


def clean_html_cell_text(cell_html: str) -> str:
    """Chuyển nội dung một ô HTML table sang text an toàn cho Markdown pipe table."""

    # Giữ line break trong cell bằng placeholder để TAG_RE không xóa nhầm <br>.
    text = re.sub(r"<br\s*/?>", "[[BR]]", cell_html, flags=re.IGNORECASE)
    text = re.sub(r"</?(strong|b)\b[^>]*>", "**", text, flags=re.IGNORECASE)
    text = re.sub(r"</?(em|i)\b[^>]*>", "*", text, flags=re.IGNORECASE)
    text = re.sub(r"</?u\b[^>]*>", "", text, flags=re.IGNORECASE)
    text = TAG_RE.sub(" ", text)
    text = html_lib.unescape(text)
    text = text.replace("|", "\\|")
    text = re.sub(r"\s*\[\[BR\]\]\s*", "<br>", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


def should_blank_rowspan_continuation(col_idx: int, value: str) -> bool:
    """Quyết định có để trống các dòng tiếp theo của rowspan hay không.

    Markdown pipe table không merge cell thật được. Với các ô định danh ở cột
    đầu như `TT`, nếu lặp lại giá trị rowspan xuống dòng dưới thì preview sẽ
    nhìn thành 2 dòng độc lập cùng số thứ tự, ví dụ `12` xuất hiện hai lần.
    Vì vậy các rowspan ở cột đầu có giá trị dạng mã/số thứ tự sẽ chỉ giữ ở
    dòng đầu, các dòng tiếp theo để trống để mô phỏng rowspan bằng Markdown.

    Các rowspan ở cột nội dung/xử lý vẫn được lặp lại để không mất thông tin.
    """

    if col_idx != 0:
        return False

    key = normalize_key(value)
    return bool(re.fullmatch(r"[0-9]{1,4}[a-z]?", key))


def parse_html_table_rows(section_html: str) -> list[list[str]]:
    """Parse các hàng HTML table, expand colspan/rowspan để pipe table có số cột ổn định.

    Markdown pipe table không hỗ trợ colspan/rowspan. Vì vậy theo cách 1:
    - colspan được mở rộng thành nhiều cột và lặp lại nội dung ở toàn bộ vùng span;
    - rowspan ở cột nội dung được lặp lại ở các hàng tiếp theo để không mất dữ liệu;
    - rowspan ở cột định danh đầu bảng, ví dụ `TT`, chỉ giữ giá trị ở dòng đầu
      và để trống các dòng tiếp theo để tránh lỗi nhìn như trùng số thứ tự.
    """

    rows: list[list[str]] = []
    pending_rowspans: dict[int, tuple[int, str]] = {}

    for tr_match in TR_RE.finditer(section_html):
        tr_html = tr_match.group(0)
        cell_matches = list(re.finditer(r"<(td|th)\b([^>]*)>(.*?)</\1>", tr_html, flags=re.IGNORECASE | re.DOTALL))
        if not cell_matches:
            continue

        row: list[str] = []
        col = 0

        def flush_pending_until(target_col: int | None = None) -> None:
            nonlocal col
            while col in pending_rowspans and (target_col is None or col < target_col):
                remaining, value = pending_rowspans[col]
                row.append(value)
                if remaining <= 1:
                    pending_rowspans.pop(col, None)
                else:
                    pending_rowspans[col] = (remaining - 1, value)
                col += 1

        for cell_match in cell_matches:
            flush_pending_until(None)
            attrs = cell_match.group(2) or ""
            value = clean_html_cell_text(cell_match.group(3) or "")
            colspan = html_attr_int(attrs, "colspan", 1)
            rowspan = html_attr_int(attrs, "rowspan", 1)

            for _ in range(colspan):
                # Markdown không merge ô được, nên mô phỏng colspan bằng cách
                # lặp lại nội dung vào từng cột bị span. Cách này giúp bảng
                # giữ đủ số cột và không mất ý nghĩa khi preview/RAG.
                cell_value = value
                row.append(cell_value)
                if rowspan > 1:
                    continuation_value = "" if should_blank_rowspan_continuation(col, cell_value) else cell_value
                    pending_rowspans[col] = (rowspan - 1, continuation_value)
                col += 1

        # Bổ sung các rowspan còn lại ở cuối hàng nếu có.
        while col in pending_rowspans:
            remaining, value = pending_rowspans[col]
            row.append(value)
            if remaining <= 1:
                pending_rowspans.pop(col, None)
            else:
                pending_rowspans[col] = (remaining - 1, value)
            col += 1

        rows.append(row)

    return rows


def flatten_header_rows(header_rows: list[list[str]], width: int) -> list[str]:
    """Gộp header nhiều tầng của HTML table thành một hàng header Markdown."""

    if not header_rows:
        return []

    normalized = [row + [""] * (width - len(row)) for row in header_rows]
    flattened: list[str] = []
    for col_idx in range(width):
        parts: list[str] = []
        for row in normalized:
            value = row[col_idx].strip()
            if value and value not in parts:
                parts.append(value)
        flattened.append(" / ".join(parts).strip() or f"Cột {col_idx + 1}")
    return flattened


def rows_to_markdown_table(header: list[str], data_rows: list[list[str]]) -> str:
    """Render header + data rows thành Markdown pipe table có số cột bằng nhau."""

    width = max([len(header), *(len(row) for row in data_rows)] or [0])
    if width == 0:
        return ""

    if not header:
        header = [f"Cột {idx + 1}" for idx in range(width)]

    header = (header + [""] * (width - len(header)))[:width]
    normalized_rows = [(row + [""] * (width - len(row)))[:width] for row in data_rows]

    lines = [build_table_row(header), build_table_row(["---"] * width)]
    lines.extend(build_table_row(row) for row in normalized_rows)
    return "\n".join(lines)


def html_table_to_markdown(table_html: str, inherited_header: list[str] | None = None) -> tuple[str, list[str] | None]:
    """Chuyển một HTML table sang Markdown pipe table.

    Nếu table tiếp nối trang không có `<thead>`, hàm dùng header của bảng trước
    để kích thước bảng giữa các trang đồng nhất hơn.
    """

    thead_match = THEAD_RE.search(table_html)
    tbody_match = TBODY_RE.search(table_html)

    header_rows = parse_html_table_rows(thead_match.group(0)) if thead_match else []
    body_source = tbody_match.group(1) if tbody_match else table_html
    data_rows = parse_html_table_rows(body_source)

    width = max([*(len(row) for row in header_rows), *(len(row) for row in data_rows)] or [0])
    header = flatten_header_rows(header_rows, width) if header_rows else []

    if not header and inherited_header:
        header = inherited_header[:]
        width = max(width, len(header))

    markdown_table = rows_to_markdown_table(header, data_rows)
    return markdown_table, (header if header else inherited_header)


def convert_html_tables_to_markdown(markdown: str) -> str:
    """Đổi toàn bộ HTML table sang Markdown pipe table.

    Bước này chạy sau khi đã sửa fake thead/nối chữ qua trang. Header của table
    đầu tiên được tái sử dụng cho các table tiếp nối ở trang sau để tránh lỗi
    bảng đầu trang bị lệch cột hoặc không dính cấu trúc với bảng gốc.
    """

    matches = list(HTML_TABLE_RE.finditer(markdown))
    if not matches:
        return markdown

    out: list[str] = []
    pos = 0
    last_header: list[str] | None = None

    for match in matches:
        out.append(markdown[pos : match.start()])
        md_table, last_header = html_table_to_markdown(match.group(0), inherited_header=last_header)
        out.append(md_table)
        pos = match.end()

    out.append(markdown[pos:])
    return "".join(out)

