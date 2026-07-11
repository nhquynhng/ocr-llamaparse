from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

from src.engines.llamaparse_engine import (
    LlamaParseRawEngine,
    RawParseOptions,
    supported_input_files,
)

from src.postprocess.llamaparse_postprocess import postprocess_llamaparse_markdown
from src.postprocess.page_formatter import (
    pages_from_llamaparse_result_pages,
    render_page_blocks,
)
from src.validation.attach_metadata import gan_metadata_vao_markdown_llama

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OCR/parse raw bằng LlamaParse và ghi thẳng output ra file."
    )
    parser.add_argument("input", help="File hoặc thư mục đầu vào")
    parser.add_argument("-o", "--output", default="output", help="Thư mục output")
    parser.add_argument("--tier", default="agentic", help="LlamaParse tier, mặc định: agentic")
    parser.add_argument("--version", default="latest", help="LlamaParse version, mặc định: latest")
    parser.add_argument(
        "--format",
        choices=["markdown", "text"],
        default="markdown",
        help="Output lấy từ result.markdown hoặc result.text",
    )
    parser.add_argument("--language", default=None, help="Ngôn ngữ OCR, ví dụ: vi, en")
    parser.add_argument("--page-start", type=int, default=None, help="Trang bắt đầu, tính từ 1")
    parser.add_argument("--page-end", type=int, default=None, help="Trang kết thúc")
    parser.add_argument(
        "--page-separator",
        choices=["blank", "html-comment", "none"],
        default="blank",
        help="Cách ghép các trang khi ghi file",
    )
    parser.add_argument("--disable-cache", action="store_true", help="Không dùng cache của LlamaParse")
    parser.add_argument(
        "--no-markdown-tables",
        action="store_true",
        help="Không yêu cầu LlamaParse xuất bảng dạng Markdown table",
    )
    parser.add_argument(
        "--no-postprocess",
        action="store_true",
        help="Không chạy postprocess sau LlamaParse",
    )

    return parser


def dataset_root_for(input_file: Path) -> Path | None:
    """Trả về thư mục Dataset chứa file đầu vào.

    Ví dụ:
        D:/Code/CTU_Student_Service/Dataset/02_Attachments/...
        -> D:/Code/CTU_Student_Service/Dataset

    Không dùng PROJECT_ROOT hard-code vì source code có thể được đặt ở thư
    mục khác, còn đường dẫn đúng phải đi theo chính file đầu vào.
    """

    parts = input_file.resolve().parts
    lowered = [p.lower() for p in parts]
    if "dataset" not in lowered:
        return None

    dataset_idx = lowered.index("dataset")
    return Path(*parts[: dataset_idx + 1])


def auto_output_dir_for(input_file: Path) -> Path | None:
    """Suy ra thư mục output tương ứng theo cấu trúc Dataset.

    Quy ước hiện dùng:
        Dataset/02_Attachments/PDFs/<GROUP>/<Category>/file.pdf
            -> Dataset/06_Processing/01_OCR_Output/PDFs_<GROUP>/<Category>/

        Dataset/02_Attachments/DOCX/<GROUP>/<Category>/file.docx
            -> Dataset/06_Processing/01_OCR_Output/DOCX/<GROUP>/<Category>/

    Lý do DOCX không ghép thành DOCX_CTSV: thư mục DOCX là nhóm output
    chính, còn CTSV/PDT/... được giữ như nhánh con để thống nhất khi xử lý
    nhiều nhóm văn bản Word.

    Trả về None nếu file gốc không nằm trong .../Dataset/02_Attachments/...
    để caller fallback về thư mục output do người dùng chỉ định.
    """

    resolved = input_file.resolve()
    parts = resolved.parts
    lowered = [p.lower() for p in parts]
    if "02_attachments" not in lowered:
        return None

    dataset_root = dataset_root_for(resolved)
    if dataset_root is None:
        return None

    idx = lowered.index("02_attachments")
    # Cần ít nhất <TYPE> và <GROUP> ngay sau "02_Attachments".
    if idx + 2 >= len(parts):
        return None

    file_type = parts[idx + 1]
    group = parts[idx + 2]
    ocr_output_root = dataset_root / "06_Processing" / "01_OCR_Output"

    if file_type.lower() == "docx":
        # DOCX giữ cấu trúc DOCX/<GROUP>/... thay vì DOCX_<GROUP>/...
        category_parts = parts[idx + 2 : -1]
        return ocr_output_root.joinpath(file_type, *category_parts)

    # PDF và các loại khác giữ quy ước cũ <TYPE>_<GROUP>/...
    category_parts = parts[idx + 3 : -1]
    return ocr_output_root.joinpath(f"{file_type}_{group}", *category_parts)


def output_path_for(input_file: Path, output_dir: Path, output_format: str) -> Path:
    suffix = ".md" if output_format == "markdown" else ".txt"
    target_dir = auto_output_dir_for(input_file) or output_dir
    return target_dir / f"{input_file.stem}_llp{suffix}"


def main() -> int:
    load_dotenv()

    if not os.getenv("LLAMA_CLOUD_API_KEY"):
        raise RuntimeError("Thiếu LLAMA_CLOUD_API_KEY. Hãy tạo .env từ .env.example.")

    args = build_parser().parse_args()

    input_path = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    options = RawParseOptions(
        tier=args.tier,
        version=args.version,
        output_format=args.format,
        language=args.language,
        page_start=args.page_start,
        page_end=args.page_end,
        page_separator=args.page_separator,
        disable_cache=args.disable_cache,
        output_tables_as_markdown=not args.no_markdown_tables,
    )

    engine = LlamaParseRawEngine()

    files = list(supported_input_files(input_path))
    if not files:
        raise FileNotFoundError(f"Không tìm thấy file đầu vào hợp lệ trong: {input_path}")

    for file_path in files:
        print(f"Parsing: {file_path}")

        out_path = output_path_for(file_path, output_dir, args.format)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if args.format == "markdown":
            # 1. Lấy từng trang từ LlamaParse.
            pages = engine.parse_pages(file_path, options)

            # 2. Render page marker trước, theo đúng ranh giới trang PDF.
            #    Không postprocess từng trang, vì bảng có thể bị cắt qua nhiều trang.
            page_blocks = pages_from_llamaparse_result_pages(pages)
            rendered_output = render_page_blocks(
                page_blocks,
                include_page_1_marker=True,
                include_page_number_line=True,
            )

            # 3. Postprocess toàn bộ document một lần.
            #    Bước này mới có đủ ngữ cảnh để merge bảng nối trang.
            if not args.no_postprocess:
                processed_output = postprocess_llamaparse_markdown(rendered_output)
                parser_name = "llamaparse_postprocessed"
            else:
                processed_output = rendered_output
                parser_name = "llamaparse_raw"

            # 4. Gắn metadata vào đầu file sau cùng.
            final_output = gan_metadata_vao_markdown_llama(
                markdown=processed_output,
                output_path=out_path,
                source_file=file_path,
                cau_hinh=options,
                document_type=None,
                parser_name=parser_name,
                ocr_engine="LlamaParse API",
            )

            out_path.write_text(final_output, encoding="utf-8")

        else:
            raw_output = engine.parse_file(file_path, options)
            out_path.write_text(raw_output, encoding="utf-8")

        print(f"Wrote: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())