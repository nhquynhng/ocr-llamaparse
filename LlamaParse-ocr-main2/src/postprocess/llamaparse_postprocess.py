from __future__ import annotations

"""
Postprocess Markdown do LlamaParse sinh ra.

File này chỉ giữ các luật hậu xử lý văn bản/heading chung.
Tất cả luật liên quan đến bảng đã được tách sang `table_postprocess.py`.

Các lỗi đang xử lý:
1. Heading không đồng nhất: cùng là `Điều 1`, `Điều 2` nhưng lúc là ##, lúc là bold.
2. Dòng list bị bọc bold toàn dòng: **2. ...** trong khi PDF chỉ là mục đánh số thường.
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


def is_numbered_heading(text: str) -> bool:
    """Nhận diện heading dạng 1. ..., 2. ... nếu dòng đang được đánh heading."""

    return bool(re.match(r"^\d+[\.)]\s+\S+", text.strip()))


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

    if level == 1 and is_numbered_heading(clean_text):
        return make_heading(2, clean_text)

    if looks_like_long_sentence(clean_text):
        return clean_text

    return line


def promote_bold_article_lines(markdown: str) -> str:
    """Đổi các dòng `**Điều n...**` thành heading H2.

    LlamaParse hay để các điều ở cuối trang dưới dạng bold thường, ví dụ:
        **Điều 5. Điều kiện hỗ trợ làm việc và quyền lợi**
        **Điều 6. Khen thưởng và kỷ luật** về công tác cố vấn học tập...

    Các dòng này là heading cấu trúc, nên cần chuẩn hóa thành:
        ## Điều 5. Điều kiện hỗ trợ làm việc và quyền lợi
        ## Điều 6. Khen thưởng và kỷ luật về công tác cố vấn học tập...
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

        # Không đụng vào Điều; phần này đã được promote thành H2 trước đó.
        if is_article_heading(strip_inline_markdown(s)):
            out.append(line)
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


def collapse_excess_blank_lines(markdown: str) -> str:
    """Gộp nhiều hơn 2 dòng trắng liên tiếp để Markdown gọn và ổn định."""

    markdown = re.sub(r"\n{4,}", "\n\n\n", markdown)
    return markdown.strip() + "\n"


def postprocess_llamaparse_markdown(markdown: str) -> str:
    """Hàm chính để hậu xử lý Markdown raw của LlamaParse."""

    frontmatter, body = split_yaml_frontmatter(markdown)

    body = normalize_existing_headings(body)
    body = promote_bold_article_lines(body)
    body = demote_bold_numbered_lines(body)
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
