# LlamaParse OCR Raw

Source tối giản để lấy trực tiếp kết quả OCR/parse từ LlamaParse và ghi ra file, không chạy hậu xử lý, không sửa heading, không sửa bảng, không áp từ điển, không route hybrid.

## Cài đặt

```bash
python -m pip install -r requirements.txt
```

Tạo `.env` từ `.env.example`:

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

## Tùy chọn

```bash
python main.py "input.pdf" -o output --tier agentic --language vi
python main.py "input.pdf" -o output --page-start 1 --page-end 3
python main.py "input.pdf" -o output --format text
python main.py "input.pdf" -o output --page-separator html-comment
python main.py "input.pdf" -o output --disable-cache
```

## Luồng xử lý

```text
PDF/ảnh đầu vào
→ upload lên LlamaCloud
→ LlamaParse parse
→ lấy result.markdown.pages hoặc result.text.pages
→ ghi thẳng ra file
```

Không có `common_fix`, `markdown_layout`, `table_form_postprocess`, `final_postprocess` hoặc bất kỳ bước hậu xử lý nội dung nào.
