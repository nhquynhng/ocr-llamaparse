# LlamaParse OCR + Postprocess

Source dùng LlamaParse để OCR/parse PDF/ảnh/tài liệu sang Markdown, sau đó hậu xử lý để chuẩn hóa page marker, heading và bảng.

## Cài đặt

```bash
python -m pip install -r requirements.txt
```

Tạo file `.env` ở thư mục project:

```env
LLAMA_CLOUD_API_KEY=llx-...
```

## Chạy một file

```bash
python main.py "input.pdf" -o output
```

## Chạy một thư mục

```bash
python main.py "./pdfs" -o output
```

## Tùy chọn thường dùng

```bash
python main.py "input.pdf" -o output --tier agentic --language vi
python main.py "input.pdf" -o output --page-start 1 --page-end 3
python main.py "input.pdf" -o output --format text
python main.py "input.pdf" -o output --format text --page-separator html-comment
python main.py "input.pdf" -o output --disable-cache
python main.py "input.pdf" -o output --no-markdown-tables
python main.py "input.pdf" -o output --no-postprocess
```

`--page-separator` chỉ áp dụng cho `--format text`. Output Markdown luôn giữ
`<!-- page: N -->` để pipeline chunking truy vết đúng trang.

`--disable-cache` và `--no-markdown-tables` được truyền trực tiếp vào cấu hình
Llama Cloud API; post-process vẫn có thể chuẩn hóa HTML table về Markdown sau đó.

## Luồng xử lý Markdown

```text
PDF/ảnh đầu vào
→ upload lên LlamaCloud
→ LlamaParse parse theo từng trang
→ render page marker
→ postprocess toàn document
→ gắn metadata
→ ghi file .md
```

## Quy tắc heading chính

| Cấp | Áp dụng |
|---|---|
| H1 | Tiêu đề lớn đầu văn bản: QUYẾT ĐỊNH, HƯỚNG DẪN, THÔNG BÁO, NỘI QUY, QUY CHẾ, KẾ HOẠCH... |
| H2 | Mục La Mã: I, II, III... |
| H3 | Dạng mơ hồ `1.`, `1/`, `A.` chỉ khi ngắn, có body riêng và có thêm tín hiệu sibling/định dạng/heading cha |
| H4 | Mục thập phân: 1.1, 2.4... hoặc `Điều ...` nằm trong mục |

Các dạng `1)`, `A)`, `A/`, `a)`, `a/` mặc định là list item và không được gắn `#`.
`a.` cũng mặc định là item, chỉ nâng thành heading khi có bằng chứng cấu trúc rất rõ.
Khi không chắc chắn, post-process giữ nguyên item để ưu tiên precision.

Rule heading không chạy trong YAML front matter, bảng, HTML comment và code fence.
