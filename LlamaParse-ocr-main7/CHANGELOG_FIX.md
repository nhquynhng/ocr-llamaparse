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
