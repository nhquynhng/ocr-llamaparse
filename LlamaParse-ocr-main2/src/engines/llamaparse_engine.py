from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from llama_cloud import LlamaCloud


@dataclass
class RawParseOptions:
    tier: str = "agentic"
    version: str = "latest"
    output_format: str = "markdown"   # markdown | text
    language: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    page_separator: str = "blank"
    disable_cache: bool = False
    output_tables_as_markdown: bool = True


@dataclass
class ParsedPage:
    page_number: int
    text: str


class LlamaParseRawEngine:
    def __init__(self) -> None:
        self.client = LlamaCloud()

    def parse_pages(self, input_path: str | Path, options: RawParseOptions) -> list[ParsedPage]:
        uploaded_file = self.client.files.create(
            file=str(input_path),
            purpose="parse",
        )

        parse_kwargs = {
            "file_id": uploaded_file.id,
            "tier": options.tier,
            "version": options.version,
            "expand": [options.output_format],
        }

        if options.language:
            parse_kwargs["processing_options"] = {
                "language": options.language,
            }

        result = self.client.parsing.parse(**parse_kwargs)

        pages: list[ParsedPage] = []

        if options.output_format == "markdown":
            raw_pages = getattr(result.markdown, "pages", []) or []
            for i, page in enumerate(raw_pages, start=1):
                pages.append(
                    ParsedPage(
                        page_number=i,
                        text=(page.markdown or "").strip(),
                    )
                )
        else:
            raw_pages = getattr(result.text, "pages", []) or []
            for i, page in enumerate(raw_pages, start=1):
                pages.append(
                    ParsedPage(
                        page_number=i,
                        text=(page.text or "").strip(),
                    )
                )

        # cắt theo khoảng trang nếu có
        if options.page_start is not None or options.page_end is not None:
            start = options.page_start or 1
            end = options.page_end or len(pages)
            pages = [p for p in pages if start <= p.page_number <= end]

        return pages

    def parse_file(self, input_path: str | Path, options: RawParseOptions) -> str:
        pages = self.parse_pages(input_path, options)
        return "\n\n".join(page.text for page in pages if page.text)


def supported_input_files(path: str | Path):
    path = Path(path)

    exts = {
        ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
        ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".html", ".txt", ".csv", ".md",
    }

    if path.is_file() and path.suffix.lower() in exts:
        yield path
        return

    if path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.is_file() and p.suffix.lower() in exts:
                yield p