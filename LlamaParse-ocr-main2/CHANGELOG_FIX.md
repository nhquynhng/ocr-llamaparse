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
