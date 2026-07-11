# LlamaParse OCR Pipeline

README này mô tả source code OCR dùng LlamaParse để xử lý PDF, ảnh và nhiều định dạng tài liệu sang Markdown/Text, sau đó chuẩn hóa phân trang, heading, bảng, form và metadata để phục vụ các bước xử lý tiếp theo như review, chunking hoặc RAG.

## 1. Mục đích của project

Project này dùng để:

- Nhận đầu vào là **một file** hoặc **một thư mục nhiều file**.
- Upload từng file lên **Llama Cloud / LlamaParse API**.
- Parse/OCR nội dung theo từng trang.
- Xuất kết quả ra `.md` hoặc `.txt`.
- Với Markdown, tự động:
  - giữ marker trang `<!-- page: N -->`;
  - chuẩn hóa heading/list theo quy tắc đã chốt;
  - xử lý bảng Markdown/HTML table;
  - xử lý lỗi OCR thường gặp trong đơn/giấy/biểu mẫu;
  - gắn YAML metadata chuẩn ở đầu file;
  - validate metadata trước khi ghi output.

Kết quả chính của pipeline là file OCR dạng:

```text
<tên_file_gốc>_llp.md
```

hoặc nếu chọn text:

```text
<tên_file_gốc>_llp.txt
```

## 2. Luồng xử lý tổng quát

Luồng chính nằm trong `main.py`.

```text
Input file/thư mục
        ↓
Đọc CLI arguments
        ↓
Load .env và kiểm tra LLAMA_CLOUD_API_KEY
        ↓
Tìm danh sách file hợp lệ
        ↓
Tạo RawParseOptions
        ↓
Khởi tạo LlamaParseRawEngine
        ↓
Xử lý tuần tự từng file
        ↓
Upload file lên Llama Cloud
        ↓
Gọi LlamaParse API
        ↓
Lọc page range nếu có --page-start / --page-end
        ↓
Nếu output text:
    Ghép trang theo page_separator
    Ghi .txt

Nếu output markdown:
    Render page marker
    Chạy postprocess
    Gắn metadata YAML
    Validate metadata
    Ghi .md
```

## 3. Cấu trúc thư mục chính

```text
.
├── main.py
├── requirements.txt
├── README.md
├── CHANGELOG_FIX.md
├── src/
│   ├── engines/
│   │   └── llamaparse_engine.py
│   ├── postprocess/
│   │   ├── llamaparse_postprocess.py
│   │   ├── page_formatter.py
│   │   ├── table_postprocess.py
│   │   └── form_postprocess.py
│   └── validation/
│       ├── attach_metadata.py
│       ├── apply_metadata.py
│       └── validate_metadata.py
└── tests/
    ├── test_engine_options.py
    └── test_heading_rules.py
```

## 4. Vai trò từng vùng trong source code

### `main.py`

Đây là entry point của chương trình.

Vai trò chính:

- Khai báo CLI arguments.
- Load biến môi trường từ `.env`.
- Kiểm tra `LLAMA_CLOUD_API_KEY`.
- Nhận input là file hoặc thư mục.
- Tìm các file có đuôi được hỗ trợ.
- Tạo cấu hình `RawParseOptions`.
- Gọi engine OCR.
- Tạo đường dẫn output.
- Điều phối postprocess và metadata.
- Ghi file kết quả.

Các hàm quan trọng:

- `build_parser()` khai báo CLI.
- `supported_input_files()` được gọi để lấy danh sách file hợp lệ.
- `parse_options_from_args()` chuyển CLI args thành config engine.
- `render_markdown_document()` xử lý riêng luồng Markdown.
- `process_input_file()` xử lý một file.
- `main()` xử lý toàn bộ input.

### `src/engines/llamaparse_engine.py`

Đây là lớp adapter kết nối với Llama Cloud SDK.

Vai trò chính:

- Định nghĩa các định dạng file được hỗ trợ.
- Định nghĩa cấu hình OCR qua `RawParseOptions`.
- Upload file lên Llama Cloud.
- Gọi `client.parsing.parse()`.
- Lấy kết quả theo trang.
- Lọc khoảng trang.
- Ghép text nếu output là `.txt`.

Các thành phần quan trọng:

- `SUPPORTED_INPUT_EXTENSIONS`: danh sách đuôi file được nhận.
- `RawParseOptions`: cấu hình parse gồm tier, version, format, language, page range, cache, table option.
- `ParsedPage`: object nội bộ đại diện một trang.
- `build_parse_kwargs()`: dựng payload gửi vào LlamaParse API.
- `LlamaParseRawEngine.parse_pages()`: upload + parse + lọc trang.
- `LlamaParseRawEngine.parse_file()`: parse rồi ghép trang thành text.
- `supported_input_files()`: nhận file hoặc quét thư mục đệ quy.

### `src/postprocess/page_formatter.py`

Module này chỉ xử lý định dạng phân trang, không sửa nội dung OCR.

Vai trò chính:

- Xóa marker trang cũ nếu LlamaParse sinh ra.
- Xóa marker extraction cũ.
- Chuẩn hóa mỗi trang thành block Markdown rõ ràng.
- Đảm bảo output Markdown có `<!-- page: N -->`.
- Giữ số trang đúng khi parse một khoảng trang.

Output Markdown được render theo hướng:

```markdown
---

1

<!-- page: 1 -->

Nội dung trang 1

---

2

<!-- page: 2 -->

Nội dung trang 2
```

### `src/postprocess/llamaparse_postprocess.py`

Đây là pipeline hậu xử lý Markdown chính.

Vai trò chính:

- Chuẩn hóa heading lớn như `QUYẾT ĐỊNH`, `THÔNG BÁO`, `HƯỚNG DẪN`, `QUY CHẾ`, `KẾ HOẠCH`.
- Chuẩn hóa mục La Mã viết hoa `I.`, `II.`, `III.` thành heading phù hợp.
- Chuẩn hóa `Điều n...`.
- Phân biệt heading thật với list item.
- Tránh promote nhầm các dòng như `1)`, `A)`, `a)`, `a/` thành heading.
- Không sửa nội dung trong YAML front matter, HTML comment, Markdown table và fenced code block.
- Gọi module xử lý form.
- Gọi module xử lý table.
- Dọn dòng trắng thừa.

Entry chính:

```python
postprocess_llamaparse_markdown(markdown)
```

### `src/postprocess/table_postprocess.py`

Module chuyên xử lý bảng.

Vai trò chính:

- Nhận diện Markdown table.
- Chuẩn hóa số cột trong bảng.
- Xóa cột rỗng cuối bảng.
- Xử lý cell lặp do OCR mô phỏng colspan/rowspan.
- Gộp bảng bị tách qua page marker.
- Xử lý HTML table do LlamaParse sinh ra.
- Chuyển HTML table sang Markdown table.
- Xử lý các bảng đặc thù như bảng vi phạm/kỷ luật hoặc bảng điểm chuẩn.

### `src/postprocess/form_postprocess.py`

Module chuyên xử lý tài liệu dạng đơn, giấy, phiếu, biểu mẫu.

Vai trò chính:

- Nhận diện tài liệu dạng form qua các cue như đơn, giấy, phiếu, biểu mẫu, kính gửi.
- Chuẩn hóa quốc hiệu và tiêu ngữ.
- Chuẩn hóa tiêu đề form thành H1.
- Gỡ heading sai ở dòng `Kính gửi/gởi`.
- Gỡ bullet sai ở các dòng field form.
- Gỡ bold sai quanh nhãn trường như `Họ và tên`, `Mã số sinh viên`, `Ngày sinh`, `Hộ khẩu thường trú`.

### `src/validation/attach_metadata.py`

Module trung gian để gắn metadata cho output từ LlamaParse.

Vai trò chính:

- Xác định `file_type` theo đuôi file nguồn.
- Lấy ngôn ngữ OCR từ config.
- Gọi `ap_dung_va_xac_thuc_metadata()` để thêm YAML metadata.

Hàm chính:

```python
gan_metadata_vao_markdown_llama(...)
```

### `src/validation/apply_metadata.py`

Module tạo metadata chuẩn cho Markdown.

Vai trò chính:

- Tách YAML front matter cũ nếu có.
- Sinh các trường metadata tự động.
- Tính checksum.
- Suy luận source path, canonical markdown path, document key, version key.
- Gộp metadata cũ và metadata mới.
- Dump YAML front matter theo thứ tự trường cố định.
- Gọi validate metadata trước khi trả output.

Một số trường metadata quan trọng:

```yaml
document_key:
version_key:
title:
document_type:
ocr_status:
review_status:
rag_status:
source_path:
canonical_markdown_path:
file_type:
language:
checksum:
parser:
ocr_engine:
created_at:
updated_at:
```

### `src/validation/validate_metadata.py`

Module kiểm tra metadata.

Vai trò chính:

- Kiểm tra field bắt buộc.
- Kiểm tra enum hợp lệ.
- Kiểm tra checksum SHA256.
- Kiểm tra ngày theo format `YYYY-MM-DD`.
- Cảnh báo nếu `document_type` là `unknown`.
- Chặn trạng thái metadata không hợp lệ, ví dụ `rag_status: published` nhưng OCR chưa done hoặc review chưa approved.

### `tests/`

Chứa unit test để bảo vệ các rule quan trọng.

- `test_engine_options.py`: kiểm tra CLI options có được truyền đúng vào engine/API payload không.
- `test_heading_rules.py`: kiểm tra các rule heading/list/postprocess để tránh sửa sai tài liệu.

## 5. Quy trình OCR một file

### Bước 1: Cài dependency

```bash
python -m pip install -r requirements.txt
```

### Bước 2: Tạo file `.env`

Tạo file `.env` ở thư mục project:

```env
LLAMA_CLOUD_API_KEY=llx-...
```

### Bước 3: Chạy OCR một file

Ví dụ OCR một PDF sang Markdown:

```bash
python main.py "input.pdf" -o output
```

Ví dụ chỉ OCR một khoảng trang:

```bash
python main.py "input.pdf" -o output --page-start 1 --page-end 3
```

Ví dụ chỉ định ngôn ngữ OCR tiếng Việt:

```bash
python main.py "input.pdf" -o output --language vi
```

Ví dụ xuất text thay vì Markdown:

```bash
python main.py "input.pdf" -o output --format text
```

### Luồng xử lý khi OCR một file Markdown

```text
input.pdf
  ↓
main.py nhận argument
  ↓
LlamaParseRawEngine.parse_pages()
  ↓
Upload file lên Llama Cloud
  ↓
client.parsing.parse()
  ↓
extract_result_pages()
  ↓
filter_page_range()
  ↓
pages_from_llamaparse_result_pages()
  ↓
render_page_blocks()
  ↓
postprocess_llamaparse_markdown()
  ↓
gan_metadata_vao_markdown_llama()
  ↓
write_text()
  ↓
output/input_llp.md
```

### Luồng xử lý khi OCR một file text

```text
input.pdf
  ↓
main.py nhận argument
  ↓
LlamaParseRawEngine.parse_file()
  ↓
Upload file lên Llama Cloud
  ↓
client.parsing.parse()
  ↓
extract_result_pages()
  ↓
filter_page_range()
  ↓
join_parsed_pages()
  ↓
write_text()
  ↓
output/input_llp.txt
```

Lưu ý: với `--format text`, pipeline không chạy postprocess Markdown và không gắn YAML metadata.

## 6. Quy trình OCR nhiều file

Có thể truyền vào một thư mục thay vì một file.

```bash
python main.py "./input_folder" -o output
```

Khi input là thư mục:

1. `supported_input_files()` quét đệ quy toàn bộ thư mục.
2. Chỉ nhận file có đuôi nằm trong `SUPPORTED_INPUT_EXTENSIONS`.
3. Danh sách file được sort theo đường dẫn.
4. Chương trình xử lý tuần tự từng file.
5. Mỗi file được ghi ra một output riêng.

Ví dụ:

```text
input_folder/
├── a.pdf
├── b.docx
└── sub/
    └── c.png
```

Chạy:

```bash
python main.py "input_folder" -o output
```

Có thể tạo:

```text
output/
├── a_llp.md
├── b_llp.md
└── c_llp.md
```

Nếu file input nằm trong cấu trúc Dataset đặc biệt, output có thể không nằm trực tiếp trong thư mục `-o`, mà được tự suy ra theo quy tắc ở `auto_output_dir_for()`.

## 7. Quy tắc output theo cấu trúc Dataset

Nếu input nằm trong:

```text
Dataset/02_Attachments/PDFs/<GROUP>/<Category>/file.pdf
```

output sẽ được ghi vào:

```text
Dataset/06_Processing/01_OCR_Output/PDFs_<GROUP>/<Category>/file_llp.md
```

Nếu input nằm trong:

```text
Dataset/02_Attachments/DOCX/<GROUP>/<Category>/file.docx
```

output sẽ được ghi vào:

```text
Dataset/06_Processing/01_OCR_Output/DOCX/<GROUP>/<Category>/file_llp.md
```

Nếu input không thuộc cấu trúc `Dataset/02_Attachments/...`, output sẽ ghi vào thư mục truyền qua `-o`.

## 8. Các định dạng file được hỗ trợ

Source hiện hỗ trợ các đuôi:

```text
.pdf
.png
.jpg
.jpeg
.tif
.tiff
.bmp
.webp
.doc
.docx
.ppt
.pptx
.xls
.xlsx
.html
.txt
.csv
.md
```

## 9. Các tùy chọn CLI quan trọng

```bash
python main.py <input> -o <output_dir>
```

Các option chính:

| Option                            | Ý nghĩa                                                    |
| --------------------------------- | ------------------------------------------------------------ |
| `--tier`                        | Tier LlamaParse, mặc định`agentic`                      |
| `--version`                     | Version LlamaParse, mặc định`latest`                    |
| `--format markdown`             | Xuất Markdown, mặc định                                  |
| `--format text`                 | Xuất text thuần                                            |
| `--language vi`                 | Chỉ định ngôn ngữ OCR                                   |
| `--page-start N`                | Trang bắt đầu, tính từ 1                                |
| `--page-end N`                  | Trang kết thúc                                             |
| `--page-separator blank`        | Ghép text bằng dòng trắng                                |
| `--page-separator html-comment` | Ghép text kèm`<!-- page: N -->`                          |
| `--page-separator none`         | Ghép text liền nhau                                        |
| `--disable-cache`               | Không dùng cache của LlamaParse                           |
| `--no-markdown-tables`          | Không yêu cầu LlamaParse xuất bảng dạng Markdown table |
| `--no-postprocess`              | Không chạy hậu xử lý Markdown                           |

Ví dụ:

```bash
python main.py "input.pdf" -o output --tier agentic --language vi
python main.py "input.pdf" -o output --page-start 2 --page-end 5
python main.py "input.pdf" -o output --format text --page-separator html-comment
python main.py "input.pdf" -o output --disable-cache
python main.py "input.pdf" -o output --no-markdown-tables
python main.py "input.pdf" -o output --no-postprocess
```

## 10. Lưu ý quan trọng

- Bắt buộc phải có biến môi trường `LLAMA_CLOUD_API_KEY` trong `.env` hoặc môi trường hệ thống.
- `--disable-cache` được truyền thẳng vào Llama Cloud API qua tham số `disable_cache`.
- `--no-markdown-tables` chỉ ảnh hưởng request gửi lên LlamaParse; sau đó postprocess vẫn có thể xử lý/chuẩn hóa bảng nếu output có bảng.
- Các rule heading/list có nhiều heuristic để tránh biến list item thành heading sai.
- Các dòng trong fenced code block, HTML comment, YAML front matter và table được hạn chế sửa để tránh phá nội dung.
- Khi input là thư mục, chương trình xử lý tuần tự từng file, chưa có xử lý song song.
- Nếu file không có đuôi thuộc danh sách hỗ trợ, chương trình sẽ bỏ qua.
- Nếu không tìm thấy file hợp lệ, chương trình báo `FileNotFoundError`.
- Nếu `page_start > page_end`, chương trình báo lỗi khoảng trang không hợp lệ.
- Metadata có thể cảnh báo `document_type: unknown`; đây là tín hiệu cần review thủ công.
- Khi `rag_status: published`, metadata bắt buộc phải có `ocr_status: done` và `review_status: approved`.
- Unit test không gọi thật Llama Cloud; test engine dùng fake client để kiểm tra payload và logic nội bộ.

## 11. Chạy test

Chạy toàn bộ test:

```bash
python -m unittest discover -s tests
```

Test nên được chạy lại khi sửa các phần:

- CLI options.
- LlamaParse payload.
- Page range.
- Heading/list rules.
- Table postprocess.
- Form postprocess.
- Metadata validation.

## 12. Tóm tắt nhanh

```text
main.py
  Điều phối toàn bộ CLI OCR.

src/engines/llamaparse_engine.py
  Upload file, gọi LlamaParse API, lấy page result.

src/postprocess/page_formatter.py
  Chuẩn hóa page marker và render trang.

src/postprocess/llamaparse_postprocess.py
  Chuẩn hóa Markdown tổng quát.

src/postprocess/table_postprocess.py
  Xử lý bảng Markdown/HTML.

src/postprocess/form_postprocess.py
  Xử lý đơn/giấy/phiếu/biểu mẫu.

src/validation/attach_metadata.py
  Cầu nối gắn metadata cho output LlamaParse.

src/validation/apply_metadata.py
  Sinh YAML metadata chuẩn.

src/validation/validate_metadata.py
  Kiểm tra metadata.

tests/
  Test hồi quy cho engine options và heading rules.
```
