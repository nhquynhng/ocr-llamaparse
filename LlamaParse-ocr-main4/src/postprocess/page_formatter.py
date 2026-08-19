from __future__ import annotations

"""Định dạng lại output LlamaParse theo ranh giới trang PDF gốc.

File này chỉ chịu trách nhiệm chuẩn hóa page marker, không sửa nội dung OCR.
Các hàm ở đây vẫn gắn marker cho trang 1 nhưng không đặt dấu `---` trước trang 1
để không xung đột YAML front matter khi metadata được gắn vào đầu file Markdown.
"""

import re
from dataclasses import dataclass
from typing import Any

PAGE_MARKER_RE = re.compile(r"<!--\s*page\s*:\s*(\d+)\s*-->", flags=re.IGNORECASE)
EXTRACTION_MARKER_RE = re.compile(r"<!--\s*extraction\s*:\s*[^>]+-->", flags=re.IGNORECASE)
PAGE_BREAK_RE = re.compile(r"<!--\s*page-break\s*-->", flags=re.IGNORECASE)


@dataclass
class ParsedPageBlock:
    """Đại diện cho một trang đã tách/chuẩn hóa từ output LlamaParse."""

    page_number: int
    text: str
    extraction: str


def detect_extraction_label(text: str) -> str:
    """Nhận diện trang thường hay trang có bảng để gắn extraction marker.

    Hàm chỉ dựa trên dấu hiệu cấu trúc trong Markdown/HTML, không sửa text.
    """

    lower = text.lower()
    if "<table" in lower or "</table>" in lower:
        return "llamaparse_table_page"

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    md_table_lines = [
        line
        for line in lines
        if line.startswith("|") and line.endswith("|") and line.count("|") >= 2
    ]
    if len(md_table_lines) >= 2:
        return "llamaparse_table_page"

    return "llamaparse_text_page"


def strip_page_markers(markdown: str) -> str:
    """Xóa marker trang/extraction cũ khỏi một page block.

    Dùng trước khi render lại để tránh lặp marker hoặc giữ nhầm số trang sai.
    """

    text = PAGE_BREAK_RE.sub("", markdown)
    text = PAGE_MARKER_RE.sub("", text)
    text = EXTRACTION_MARKER_RE.sub("", text)
    text = re.sub(r"^\s*\d+\s*\n+", "", text)
    return text.strip()


def make_page_block(
    page_number: int,
    content: str,
    extraction: str | None = None,
    include_page_number_line: bool = True,
    leading_rule: bool = True,
) -> str:
    """Tạo block Markdown cho một trang theo format phân trang cũ.

    Trang 2 trở đi thường có:
        ---
        <!-- page: N -->
        <!-- extraction: ... -->
        N
        <content>

    Caller nên truyền `leading_rule=False` cho trang đầu tiên để không tạo
    `---` ngay đầu body, tránh bị metadata/frontmatter xử lý nhầm.
    """

    clean_content = strip_page_markers(content)
    label = extraction or detect_extraction_label(clean_content)

    parts: list[str] = []
    if leading_rule:
        parts.extend(["---", ""])

    parts.extend([f"<!-- page: {page_number} -->", "", f"<!-- extraction: {label} -->", ""])

    if include_page_number_line:
        parts.extend([str(page_number), ""])

    parts.append(clean_content)
    return "\n".join(parts).rstrip()


def pages_from_llamaparse_result_pages(
    pages: list[Any],
    expected_pages: list[int] | None = None,
) -> list[ParsedPageBlock]:
    """Chuyển danh sách page từ LlamaParse SDK thành ParsedPageBlock.

    Hỗ trợ cả object có `.text` lẫn `.markdown`. Nếu `expected_pages` được truyền,
    hàm ưu tiên số trang này để giữ đúng số trang PDF gốc khi parse page range.
    """

    blocks: list[ParsedPageBlock] = []
    for index, page in enumerate(pages):
        if expected_pages and index < len(expected_pages):
            page_no = expected_pages[index]
        else:
            page_no = int(getattr(page, "page_number", index + 1) or index + 1)

        content = (
            getattr(page, "text", None)
            or getattr(page, "markdown", None)
            or getattr(page, "content", None)
            or ""
        )
        clean = strip_page_markers(str(content))
        blocks.append(
            ParsedPageBlock(
                page_number=page_no,
                text=clean,
                extraction=detect_extraction_label(clean),
            )
        )

    return blocks


def split_llama_markdown_by_page(markdown: str, expected_pages: list[int]) -> dict[int, ParsedPageBlock]:
    """Tách Markdown LlamaParse theo page marker và gán lại số trang nếu cần.

    Một số phiên bản SDK trả marker theo số trang gốc, một số có thể trả thứ tự
    trong page range. Hàm ưu tiên marker khớp `expected_pages`; nếu không khớp
    thì map theo thứ tự `expected_pages` để không làm lệch trang khi ghép output.
    """

    markers = list(PAGE_MARKER_RE.finditer(markdown))
    if not expected_pages:
        return {}

    if not markers:
        page_no = expected_pages[0]
        clean = strip_page_markers(markdown)
        return {
            page_no: ParsedPageBlock(
                page_number=page_no,
                text=clean,
                extraction=detect_extraction_label(clean),
            )
        }

    raw_blocks: list[tuple[int, str]] = []
    for i, marker in enumerate(markers):
        page_no = int(marker.group(1))
        start = marker.start()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(markdown)
        raw_blocks.append((page_no, markdown[start:end].strip()))

    result: dict[int, ParsedPageBlock] = {}
    marker_pages = [page_no for page_no, _ in raw_blocks]

    if set(marker_pages).intersection(expected_pages):
        for page_no, block in raw_blocks:
            if page_no not in expected_pages:
                continue
            clean = strip_page_markers(block)
            result[page_no] = ParsedPageBlock(
                page_number=page_no,
                text=clean,
                extraction=detect_extraction_label(clean),
            )
        return result

    for page_no, (_, block) in zip(expected_pages, raw_blocks):
        clean = strip_page_markers(block)
        result[page_no] = ParsedPageBlock(
            page_number=page_no,
            text=clean,
            extraction=detect_extraction_label(clean),
        )

    return result


def render_page_blocks(
    blocks: list[ParsedPageBlock] | dict[int, ParsedPageBlock],
    include_page_1_marker: bool = True,
    include_page_number_line: bool = True,
) -> str:
    """Render các page block thành Markdown có phân trang rõ.

    - Page 1 cũng có marker `<!-- page: 1 -->` và `<!-- extraction: ... -->`.
    - Không đặt `---` trước page 1, để tránh xung đột YAML metadata.
    - Page 2 trở đi dùng `---` như format OCR cũ.
    """

    if isinstance(blocks, dict):
        ordered_blocks = [blocks[key] for key in sorted(blocks)]
    else:
        ordered_blocks = sorted(blocks, key=lambda item: item.page_number)

    chunks: list[str] = []
    for index, block in enumerate(ordered_blocks):
        is_first = index == 0

        if is_first and not include_page_1_marker:
            parts: list[str] = []
            if include_page_number_line:
                parts.extend([str(block.page_number), ""])
            parts.append(block.text.strip())
            chunks.append("\n".join(parts).rstrip())
            continue

        chunks.append(
            make_page_block(
                page_number=block.page_number,
                content=block.text,
                extraction=block.extraction,
                include_page_number_line=include_page_number_line,
                leading_rule=not is_first,
            )
        )

    return "\n\n".join(chunks).rstrip() + "\n"


# Alias tương thích với code cũ.
def render_pages_as_markdown(pages: list[Any], extraction_label: str | None = None) -> str:
    """Hàm tương thích cũ: nhận pages và render thành Markdown phân trang."""

    blocks = pages_from_llamaparse_result_pages(pages)
    if extraction_label:
        for block in blocks:
            block.extraction = extraction_label
    return render_page_blocks(blocks, include_page_1_marker=True)
