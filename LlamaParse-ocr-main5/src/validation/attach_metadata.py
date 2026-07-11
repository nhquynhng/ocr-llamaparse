from __future__ import annotations

from pathlib import Path
from typing import Any

from src.validation.apply_metadata import ap_dung_va_xac_thuc_metadata


DUOI_ANH = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
}


def file_type_metadata(path: str | Path) -> str:
    """Chuẩn hóa file_type theo schema validation metadata."""

    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        return "pdf"

    if ext in DUOI_ANH:
        return "image"

    if ext in {
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".txt",
        ".md",
        ".html",
        ".csv",
    }:
        return ext.lstrip(".")

    return ext.lstrip(".") or "md"


def lay_ngon_ngu_ocr(cau_hinh: Any) -> str:
    """
    Lấy ngôn ngữ OCR, tương thích cả config cũ và RawParseOptions mới.

    Config cũ:
        cau_hinh.ngon_ngu_ocr

    RawParseOptions mới:
        cau_hinh.language
    """

    return (
        getattr(cau_hinh, "ngon_ngu_ocr", None)
        or getattr(cau_hinh, "language", None)
        or "vi"
    )


def gan_metadata_vao_markdown_llama(
    markdown: str,
    output_path: str | Path,
    source_file: str | Path,
    cau_hinh: Any,
    document_type: str | None = None,
    parser_name: str | None = "llamaparse_raw",
    ocr_engine: str | None = "LlamaParse API",
) -> str:
    """
    Gắn YAML metadata chuẩn vào Markdown raw của LlamaParse
    và chạy validation metadata trước khi ghi file.

    Lưu ý:
    - Không sửa nội dung OCR bên dưới YAML.
    - Có thêm YAML front matter ở đầu file, nên output không còn là raw tuyệt đối.
    """

    return ap_dung_va_xac_thuc_metadata(
        markdown=markdown,
        output_path=output_path,
        source_file=source_file,
        language=lay_ngon_ngu_ocr(cau_hinh),
        ocr_status="done",
        file_type=file_type_metadata(source_file),
        document_type=document_type,
        parser=parser_name,
        ocr_engine=ocr_engine,
        overwrite_auto=True,
    )


