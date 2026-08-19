from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.postprocess.llamaparse_postprocess import postprocess_llamaparse_markdown
from src.postprocess.page_formatter import split_llama_markdown_by_page


class HeadingRulesTest(unittest.TestCase):
    """Kiểm tra hồi quy các quy tắc heading/list đã chốt trong PDF."""

    def process(self, markdown: str) -> str:
        """Chạy đúng entry point post-process mà `main.py` sử dụng."""

        return postprocess_llamaparse_markdown(markdown).strip()

    def test_canonical_pdf_sample_keeps_numbered_items(self) -> None:
        """`1/` và `1)` trong ví dụ canonical phải giữ nguyên là item."""

        source = """## Hướng dẫn sinh viên
1/ Những điều sinh viên cần biết...
2/ Ký túc xá sinh viên...

Lưu ý:
1) Không áp dụng chế độ miễn, giảm học phí...
2) Các đối tượng thuộc diện miễn, giảm học phí...
"""
        result = self.process(source)

        self.assertNotIn("### 1/", result)
        self.assertNotIn("### 1)", result)
        self.assertIn("1/ Những điều sinh viên cần biết...", result)
        self.assertIn("1) Không áp dụng chế độ miễn, giảm học phí...", result)

    def test_definite_item_markers_are_demoted_from_existing_headings(self) -> None:
        """Heading sai có marker `1)`, `A)`, `A/`, `a)` phải bị hạ thành item."""

        source = """### 1) Mục số
### A) Mục chữ hoa
### A/ Mục chữ hoa gạch chéo
### a) Mục chữ thường
"""
        expected = """1) Mục số
A) Mục chữ hoa
A/ Mục chữ hoa gạch chéo
a) Mục chữ thường"""
        self.assertEqual(self.process(source), expected)

    def test_false_lowercase_dot_headings_are_demoted(self) -> None:
        """Các câu `a.`/`b.` mà OCR gắn H3 phải trở lại lettered item."""

        source = """### a. Sinh viên phải nộp hồ sơ đầy đủ.
### b. Hồ sơ phải có xác nhận của đơn vị.
"""
        result = self.process(source)

        self.assertNotIn("### a.", result)
        self.assertNotIn("### b.", result)

    def test_lowercase_i_is_not_a_roman_heading(self) -> None:
        """`i.` chữ thường là lettered item, không phải số La Mã H2."""

        source = "i. Sinh viên phải nộp hồ sơ đầy đủ."
        self.assertEqual(self.process(source), source)

    def test_number_dot_is_promoted_when_it_has_body_and_sibling(self) -> None:
        """`1.`/`2.` ngắn, có sibling và body riêng được xác nhận là H3."""

        source = """## Nội dung
1. MỤC ĐÍCH
Đây là phần mô tả mục đích.

2. PHẠM VI
Đây là phần mô tả phạm vi.
"""
        result = self.process(source)

        self.assertIn("### 1. MỤC ĐÍCH", result)
        self.assertIn("### 2. PHẠM VI", result)

    def test_upper_dot_without_body_stays_item(self) -> None:
        """Chuỗi `A.`/`B.` không có body riêng không đủ điều kiện thành heading."""

        source = """A. Nhóm đối tượng thứ nhất
B. Nhóm đối tượng thứ hai
"""
        result = self.process(source)

        self.assertNotIn("### A.", result)
        self.assertNotIn("### B.", result)

    def test_complete_number_dot_sentence_stays_item(self) -> None:
        """Câu quy định hoàn chỉnh bắt đầu bằng `1.` không được tạo parent heading."""

        source = "1. Sinh viên phải nộp hồ sơ đầy đủ theo quy định của nhà trường."
        self.assertEqual(self.process(source), source)

    def test_decimal_clause_stays_item(self) -> None:
        """Khoản thập phân mang tính quy định phải giữ là nội dung thường."""

        source = "2.1. Sinh viên phải nộp hồ sơ đầy đủ theo quy định của nhà trường."
        self.assertEqual(self.process(source), source)

    def test_fenced_code_is_unchanged(self) -> None:
        """Mọi rule heading/list phải bỏ qua hoàn toàn fenced code block."""

        source = """```markdown
**1) This is a numbered item with enough content**
### A) This line is sample code
```"""
        self.assertEqual(self.process(source), source)

    def test_markdown_table_is_unchanged_by_heading_rules(self) -> None:
        """Marker trong cell bảng không được promote hoặc demote như dòng văn bản."""

        source = """| Dạng | Nội dung |
|---|---|
| 1) | Không phải heading |
"""
        result = self.process(source)

        self.assertIn("| 1) | Không phải heading |", result)
        self.assertNotIn("### 1)", result)

    def test_partial_page_marker_match_does_not_drop_a_page(self) -> None:
        """Marker chỉ khớp một phần page range phải được map lại theo thứ tự."""

        source = """<!-- page: 1 -->
Nội dung trang đầu

<!-- page: 6 -->
Nội dung trang sau
"""
        blocks = split_llama_markdown_by_page(source, expected_pages=[5, 6])

        self.assertEqual(sorted(blocks), [5, 6])
        self.assertIn("Nội dung trang đầu", blocks[5].text)
        self.assertIn("Nội dung trang sau", blocks[6].text)


if __name__ == "__main__":
    unittest.main()
