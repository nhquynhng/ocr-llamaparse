# Fix 2026-06-27

## Heading
- Chuẩn hóa các dòng `Điều n...` thành `## Điều n...` dù LlamaParse trả về dạng heading, bold hoặc plain text.
- Xử lý trường hợp inline bold như `**Điều 6. Khen thưởng và kỷ luật** về ...` thành một heading H2 đầy đủ.
- Không còn để `Điều 4/5/6` ở cuối trang là bold text thường trong khi các điều trước là heading.

## Table postprocess
- `llamaparse_postprocess.py` chỉ còn orchestration và text/heading rules.
- Các hàm nhận diện/chỉnh Markdown table được gom vào `table_postprocess.py`.
- Giữ các rule đã có: convert HTML table sang pipe table, xử lý colspan/rowspan, compact heading cell lặp, ép bảng điểm chuẩn về 3 cột.

## Files
- Đã chạy thử lại 2 file output:
  - `output/17_llp.md`
  - `output/14-11-2025_QD_Covan_HT_2025signedsignedsignedsigned_llp.md`

Lưu ý: `.env` không được đóng gói trong bản zip. Hãy dùng lại file `.env` hiện có trên máy local.

# Fix 2026-07-06

## Heading theo spec mới
- Chuẩn hóa `## 2. ...`, `## 3. ...` và các mục số tương tự về `### 2. ...`, `### 3. ...`.
- Thêm nhận diện dòng mục số chưa có heading như `1. ...`, `7. ...`, `1/ Mục đích:` -> H3.
- Thêm nhận diện mục chữ cái in hoa `A. ...`, `A/ ...`, `B) ...` -> H3.
- Thêm nhận diện mục thập phân `1.1 ...`, `2.4 ...`, `3.2.1 ...` -> H4.
- Giữ `Điều n...` luôn là H4 theo quy tắc đã chốt.
- Không áp dụng rule heading trong table, HTML comment, code fence và YAML front matter.

## File kiểm thử
- Đã chạy thử với `02_1470KHTH_06-05-2024_llp.md`: các mục `1/`, `A/`, `B/`, `1. ...` đến `7. ...` đều được chuẩn hóa về H3; các mục La Mã vẫn là H2.

## Fix table merge Phụ lục KTX

- Cập nhật `src/postprocess/table_postprocess.py` để nhận diện bảng `TT | Nội dung vi phạm | Lần 1 | Lần 2 | Lần 3 | Ghi chú`.
- Không compact các cell lặp của data row bảng vi phạm/kỷ luật vì đây là cách mô phỏng `colspan` trong Markdown.
- Bổ sung luật phục hồi ô xử lý merge ngang qua `Lần 1`, `Lần 2`, `Lần 3`; ví dụ STT `01` được lặp nội dung xử lý ở cả 3 cột thay vì chỉ nằm ở cột `Lần 1`.
- Hỗ trợ trường hợp footnote `(1)` bị OCR tách nhầm sang cột kế bên: gộp lại vào nội dung xử lý trước khi lặp qua 3 cột.

## Fix decimal clause heading false-positive

- Thêm heuristic phân biệt `2.1`, `2.2`, `2.3` là tiểu mục thật hay chỉ là khoản/câu nội dung.
- Không promote heading cho các dòng thập phân có dấu hiệu câu quy phạm: `phải`, `được`, `không được`, `có trách nhiệm`, `trường hợp`, `khi`, `nếu`, `theo quy định`, v.v.
- Gỡ heading nếu LlamaParse đã sinh sẵn `### 2.1. ...` nhưng nội dung phía sau là câu/khoản dài.
- Vẫn giữ heading H4 cho các tiểu mục ngắn, giống cụm tiêu đề: `2.1. Điều kiện xét duyệt`, `2.2. Hồ sơ đăng ký`.

## Fix đường dẫn DOCX output và canonical metadata

- Sửa `main.py` để suy ra `Dataset` từ chính đường dẫn file input thay vì phụ thuộc vị trí source code.
- Giữ quy ước PDF: `02_Attachments/PDFs/<GROUP>/...` -> `01_OCR_Output/PDFs_<GROUP>/...`.
- Sửa quy ước DOCX: `02_Attachments/DOCX/<GROUP>/...` -> `01_OCR_Output/DOCX/<GROUP>/...`, không còn bị ép thành `DOCX_<GROUP>`.
- Sửa `canonical_markdown_path` trong metadata để dùng đúng `output_path` thực tế, tránh lệch giữa file được ghi và đường dẫn trong YAML.

# Fix 2026-07-08

## Fix mẫu đơn DOCX bị OCR nhầm bold/bullet
- Bổ sung `normalize_form_document_lines()` trong `src/postprocess/llamaparse_postprocess.py`.
- Chỉ bật rule khi tài liệu có dấu hiệu là đơn/biểu mẫu/phiếu hoặc có dòng `Kính gửi/gởi`, tránh ảnh hưởng văn bản quy định thông thường.
- Gỡ bold sai quanh nhãn trường điền thông tin trong mẫu đơn: `**Tôi tên**:`, `**Mã số sinh viên**:`, `**Ngày sinh**:`, `**Họ và tên cha**:`, `**Hộ khẩu thường trú**:`...
- Gỡ bullet sai do LlamaParse tự thêm ở các dòng trường biểu mẫu: `- **Tôi tên**:` -> `Tôi tên:`.
- Gỡ bullet sai ở dòng ghi chú form như `- (Kèm theo hồ sơ...)`.
- Demote dòng `### Kính gửi/gởi ...` trong mẫu đơn về văn bản thường vì đây không phải heading cấu trúc.

## File kiểm thử
- Đã chạy thử với `11_don_xin_xet_tro_cap_xa_hoi_llp.md` và đối chiếu với `11_don_xin_xet_tro_cap_xa_hoi.docx`.

## Fix bổ sung 2026-07-08: tách hậu xử lý đơn/giấy/biểu mẫu
- Tách toàn bộ luật xử lý mẫu đơn/giấy/phiếu sang `src/postprocess/form_postprocess.py`, để `llamaparse_postprocess.py` chỉ còn gọi module này trong pipeline chính, tương tự `table_postprocess.py`.
- Chuẩn hóa quốc hiệu `CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM` thành text thường in đậm, không promote thành heading.
- Chuẩn hóa tiêu ngữ `Độc lập - Tự do - Hạnh phúc` thành text thường in đậm và loại bỏ underline HTML `<u>...</u>` do OCR sinh sai. Đối chiếu file DOCX mẫu: dòng này có bold, không có underline.
- Chuẩn hóa tiêu đề form như `ĐƠN XIN...`, `GIẤY XÁC NHẬN...`, `PHIẾU...` thành heading H1, đồng thời gỡ underline/bold thừa quanh tiêu đề.
- Chuẩn hóa dòng `Kính gửi/gởi : ...` thành text thường in đậm toàn dòng, không coi là heading cấu trúc.
- Giữ các luật cũ cho field form: gỡ bullet sai và gỡ bold sai quanh nhãn trường như `Tôi tên`, `Mã số sinh viên`, `Ngày sinh`, `Họ và tên`, `Hộ khẩu thường trú`.

# Fix 2026-07-10

## Đồng bộ heading/list theo tài liệu chốt

- Giữ `1)`, `A)`, `A/`, `a)`, `a/` là list item; nếu OCR đã gắn heading thì tự động hạ về item.
- Chỉ promote `1.`, `1/`, `A.` khi dòng ngắn, có body riêng và có thêm tín hiệu sibling, định dạng hoặc heading cha.
- `a.` mặc định là item và cần bằng chứng mạnh hơn mới được promote.
- Chỉ nhận số La Mã viết hoa; `i.` chữ thường không còn bị nhận nhầm thành H2.
- Hạ các heading sai có sẵn từ LlamaParse thay vì chỉ kiểm tra dòng plain text.
- Không còn sửa bold/list item bên trong fenced code block.
- Bổ sung test hồi quy theo ví dụ đúng/sai và output canonical trong PDF quy tắc.

## Fix CLI options và làm gọn engine

- Truyền `--disable-cache` vào đúng tham số `disable_cache` của Llama Cloud API.
- Truyền `--no-markdown-tables` vào `output_options.markdown.tables.output_tables_as_markdown`.
- Truyền ngôn ngữ OCR theo schema mới `processing_options.ocr_parameters.languages`.
- Áp dụng đủ ba chế độ ghép trang cho output text: `blank`, `html-comment`, `none`.
- Markdown tiếp tục luôn giữ page marker theo contract OCR/backend.
- Tách các hàm build payload, extract/filter/join page để code ngắn, dễ test và không gọi mạng khi unit test.
- Lazy-load `llama_cloud` khi khởi tạo engine; CLI `--help` không còn phụ thuộc API key hay SDK runtime.
- Giữ nguyên toàn bộ logic metadata.
