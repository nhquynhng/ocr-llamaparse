from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


SUPPORTED_INPUT_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".html",
    ".txt",
    ".csv",
    ".md",
}

PAGE_SEPARATORS = {"blank", "html-comment", "none"}


@dataclass(frozen=True)
class RawParseOptions:
    """Cấu hình duy nhất dùng cho request LlamaParse và cách ghép output text."""

    tier: str = "agentic"
    version: str = "latest"
    output_format: str = "markdown"
    language: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    page_separator: str = "blank"
    disable_cache: bool = False
    output_tables_as_markdown: bool = True


@dataclass(frozen=True)
class ParsedPage:
    """Nội dung một trang kèm số trang gốc dùng để render page marker."""

    page_number: int
    text: str


def build_processing_options(options: RawParseOptions) -> dict[str, Any] | None:
    """Đổi mã ngôn ngữ CLI sang cấu trúc OCR mà Llama Cloud API yêu cầu."""

    if not options.language:
        return None
    return {"ocr_parameters": {"languages": [options.language]}}


def build_output_options(options: RawParseOptions) -> dict[str, Any] | None:
    """Tạo cấu hình định dạng bảng khi request output Markdown."""

    if options.output_format != "markdown":
        return None
    return {
        "markdown": {
            "tables": {
                "output_tables_as_markdown": options.output_tables_as_markdown,
            }
        }
    }


def build_parse_kwargs(file_id: str, options: RawParseOptions) -> dict[str, Any]:
    """Dựng payload cho `client.parsing.parse()` và bỏ các nhóm option rỗng."""

    kwargs: dict[str, Any] = {
        "file_id": file_id,
        "tier": options.tier,
        "version": options.version,
        "expand": [options.output_format],
        "disable_cache": options.disable_cache,
    }

    processing_options = build_processing_options(options)
    if processing_options:
        kwargs["processing_options"] = processing_options

    output_options = build_output_options(options)
    if output_options:
        kwargs["output_options"] = output_options

    return kwargs


def extract_result_pages(result: Any, output_format: str) -> list[ParsedPage]:
    """Chuẩn hóa page object của SDK thành `ParsedPage` cho Markdown hoặc text."""

    result_group = getattr(result, output_format, None)
    raw_pages = getattr(result_group, "pages", []) or []
    content_field = "markdown" if output_format == "markdown" else "text"
    pages: list[ParsedPage] = []

    for position, page in enumerate(raw_pages, start=1):
        page_number = int(getattr(page, "page_number", position) or position)
        content = getattr(page, content_field, "") or ""
        pages.append(ParsedPage(page_number=page_number, text=str(content).strip()))

    return pages


def filter_page_range(pages: list[ParsedPage], options: RawParseOptions) -> list[ParsedPage]:
    """Giữ các trang thuộc khoảng `page_start`–`page_end`, tính từ 1."""

    start = options.page_start or 1
    end = options.page_end
    if start < 1 or (end is not None and end < start):
        raise ValueError("Khoảng trang không hợp lệ: cần 1 <= page_start <= page_end")
    return [
        page
        for page in pages
        if page.page_number >= start and (end is None or page.page_number <= end)
    ]


def join_parsed_pages(pages: list[ParsedPage], separator: str) -> str:
    """Ghép output text theo blank line, HTML page comment hoặc không separator."""

    if separator not in PAGE_SEPARATORS:
        raise ValueError(f"page_separator không hợp lệ: {separator}")

    non_empty_pages = [page for page in pages if page.text]
    if separator == "none":
        return "".join(page.text for page in non_empty_pages)
    if separator == "html-comment":
        return "\n\n".join(
            f"<!-- page: {page.page_number} -->\n\n{page.text}"
            for page in non_empty_pages
        )
    return "\n\n".join(page.text for page in non_empty_pages)


class LlamaParseRawEngine:
    """Adapter mỏng quanh Llama Cloud SDK để upload, parse và chuẩn hóa trang."""

    def __init__(self, client: Any | None = None) -> None:
        """Nhận client giả khi test; chỉ import SDK thật khi chạy OCR."""

        if client is None:
            from llama_cloud import LlamaCloud

            client = LlamaCloud()
        self.client = client

    def parse_pages(
        self,
        input_path: str | Path,
        options: RawParseOptions,
    ) -> list[ParsedPage]:
        """Upload một file, gọi LlamaParse và trả danh sách trang đã lọc."""

        uploaded_file = self.client.files.create(file=Path(input_path), purpose="parse")
        result = self.client.parsing.parse(
            **build_parse_kwargs(uploaded_file.id, options)
        )
        pages = extract_result_pages(result, options.output_format)
        return filter_page_range(pages, options)

    def parse_file(self, input_path: str | Path, options: RawParseOptions) -> str:
        """Parse một file và ghép page text theo `page_separator`."""

        pages = self.parse_pages(input_path, options)
        return join_parsed_pages(pages, options.page_separator)


def supported_input_files(path: str | Path) -> Iterator[Path]:
    """Yield file đầu vào được hỗ trợ; thư mục được quét đệ quy theo tên."""

    input_path = Path(path)
    if input_path.is_file():
        if input_path.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS:
            yield input_path
        return

    if input_path.is_dir():
        yield from (
            candidate
            for candidate in sorted(input_path.rglob("*"))
            if candidate.is_file()
            and candidate.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS
        )
