from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.engines.llamaparse_engine import (
    LlamaParseRawEngine,
    ParsedPage,
    RawParseOptions,
    build_parse_kwargs,
    filter_page_range,
    join_parsed_pages,
)


class FakeFiles:
    """Ghi nhận upload để test engine mà không gọi Llama Cloud."""

    def __init__(self) -> None:
        """Khởi tạo danh sách lưu các lần gọi upload."""

        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        """Giả lập `files.create()` và trả file ID ổn định."""

        self.calls.append(kwargs)
        return SimpleNamespace(id="file-test")


class FakeParsing:
    """Ghi nhận parse payload và trả hai trang Markdown giả."""

    def __init__(self) -> None:
        """Khởi tạo danh sách lưu các lần gọi parse."""

        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        """Giả lập `parsing.parse()` để kiểm tra cấu hình request."""

        self.calls.append(kwargs)
        pages = [
            SimpleNamespace(page_number=1, markdown="Trang 1"),
            SimpleNamespace(page_number=2, markdown="Trang 2"),
        ]
        return SimpleNamespace(markdown=SimpleNamespace(pages=pages))


class FakeClient:
    """Client tối thiểu có hai resource mà engine sử dụng."""

    def __init__(self) -> None:
        """Khởi tạo resource upload và parsing giả."""

        self.files = FakeFiles()
        self.parsing = FakeParsing()


class EngineOptionsTest(unittest.TestCase):
    """Kiểm tra các CLI option được chuyển đúng vào SDK và output text."""

    def test_parse_kwargs_include_cache_language_and_table_options(self) -> None:
        """Cache, OCR language và Markdown table phải nằm đúng nhánh API."""

        options = RawParseOptions(
            language="vi",
            disable_cache=True,
            output_tables_as_markdown=False,
        )
        kwargs = build_parse_kwargs("file-1", options)

        self.assertTrue(kwargs["disable_cache"])
        self.assertEqual(
            kwargs["processing_options"],
            {"ocr_parameters": {"languages": ["vi"]}},
        )
        self.assertEqual(
            kwargs["output_options"],
            {"markdown": {"tables": {"output_tables_as_markdown": False}}},
        )

    def test_text_request_does_not_send_markdown_output_options(self) -> None:
        """Output text không gửi nhóm cấu hình chỉ dành cho Markdown."""

        kwargs = build_parse_kwargs(
            "file-1",
            RawParseOptions(output_format="text"),
        )
        self.assertNotIn("output_options", kwargs)

    def test_engine_passes_options_to_sdk_client(self) -> None:
        """Engine phải dùng payload đã build thay vì bỏ quên CLI options."""

        client = FakeClient()
        engine = LlamaParseRawEngine(client=client)
        options = RawParseOptions(
            language="vi",
            disable_cache=True,
            output_tables_as_markdown=False,
        )

        pages = engine.parse_pages("input.pdf", options)

        self.assertEqual([page.page_number for page in pages], [1, 2])
        self.assertTrue(client.parsing.calls[0]["disable_cache"])
        self.assertIsInstance(client.files.calls[0]["file"], Path)

    def test_page_range_uses_original_page_numbers(self) -> None:
        """Page range phải lọc theo số trang gốc thay vì vị trí trong list."""

        pages = [ParsedPage(4, "Bốn"), ParsedPage(5, "Năm"), ParsedPage(6, "Sáu")]
        result = filter_page_range(
            pages,
            RawParseOptions(page_start=5, page_end=6),
        )
        self.assertEqual([page.page_number for page in result], [5, 6])

    def test_invalid_page_range_is_rejected(self) -> None:
        """Khoảng trang đảo ngược phải báo lỗi rõ ràng."""

        with self.assertRaises(ValueError):
            filter_page_range([], RawParseOptions(page_start=4, page_end=2))

    def test_blank_page_separator(self) -> None:
        """Chế độ blank ghép các trang text bằng một dòng trắng."""

        pages = [ParsedPage(1, "Một"), ParsedPage(2, "Hai")]
        self.assertEqual(join_parsed_pages(pages, "blank"), "Một\n\nHai")

    def test_html_comment_page_separator(self) -> None:
        """Chế độ html-comment giữ số trang trong marker HTML."""

        pages = [ParsedPage(3, "Ba"), ParsedPage(4, "Bốn")]
        result = join_parsed_pages(pages, "html-comment")
        self.assertIn("<!-- page: 3 -->\n\nBa", result)
        self.assertIn("<!-- page: 4 -->\n\nBốn", result)

    def test_none_page_separator(self) -> None:
        """Chế độ none nối text trực tiếp, không tự chèn ký tự."""

        pages = [ParsedPage(1, "A"), ParsedPage(2, "B")]
        self.assertEqual(join_parsed_pages(pages, "none"), "AB")


if __name__ == "__main__":
    unittest.main()
