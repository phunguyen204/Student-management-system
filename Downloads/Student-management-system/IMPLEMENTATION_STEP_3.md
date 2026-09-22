# Hoàn thiện bước 3 — bản sửa ngày 19/09/2026

## Phiên đăng nhập và quyền

`session.login(db, username, password, role)` kiểm tra thông tin bằng `Database.verify_user` trước khi tạo danh tính. Sai mật khẩu, vai trò không hợp lệ hoặc lỗi truy vấn đều không giữ phiên cũ. Không có API cấp phiên chỉ bằng tên/role; thuộc tính công khai chỉ đọc, không lưu mật khẩu. Tạo một SessionManager riêng không cấp quyền cho service dùng singleton.

`change_student_status()` lấy một bản chụp danh tính nhất quán từ phiên, kiểm tra Admin và tài khoản vẫn tồn tại trước khi đổi trạng thái. Cả ba Dashboard đều hủy phiên khi đăng xuất; callback đóng cửa sổ cũng hủy phiên. Trạng thái/lý do hợp lệ và lịch sử trong transaction được giữ như bản trước.

Đây là kiểm soát quyền của ứng dụng desktop. Không tuyên bố chống được người có toàn quyền sửa Python hoặc truy cập trực tiếp MySQL.

## Giao diện, bộ lọc và CSV

Giữ năm tab thống kê theo trạng thái, khoa, ngành, khóa và lớp hành chính của bản (8), bộ lọc lớp theo khoa, phân trang và xuất CSV theo toàn bộ kết quả lọc. CSV có UTF-8 BOM và xử lý tiền tố công thức. Không bổ sung chức năng ngoài phạm vi sửa lỗi này.

## Migration

`step_change_history_fk_restrict` đọc metadata từ KEY_COLUMN_USAGE kết hợp REFERENTIAL_CONSTRAINTS. Chỉ thay FK cột mssv bằng một câu ALTER TABLE gồm DROP FOREIGN KEY và ADD CONSTRAINT; giữ FK khác, không xóa bảng, không tắt FOREIGN_KEY_CHECKS. FK đúng RESTRICT/NO ACTION được giữ nguyên.

Test nâng cấp dựng bảng CASCADE có hai dòng lịch sử và trạng thái sinh viên cố định. Dry-run giữ nguyên schema, dữ liệu và migration_versions; bootstrap nâng cấp giữ nguyên sinh viên/lịch sử, FK chuyển đúng sang students.mssv RESTRICT. Chạy lại không thay đổi dữ liệu; xóa trực tiếp bị MySQL chặn bằng lỗi FK 1451.

## Kiểm thử thực tế

Đã chạy trên Python 3.12 và MySQL 8.0.46, database kiểm thử riêng:

```text
python -m pytest -q tests --tb=short
130 passed in 12.52s
```

- 76 regression, 16 test phiên/đăng xuất, 38 MySQL integration.
- Không có bài lỗi hoặc bị bỏ qua trong lần chạy có MySQL.
- Khi không cấu hình MySQL: 92 passed, 38 skipped.
- Phiên: verifier mật khẩu thật; sai mật khẩu/role, API cũ, gán thuộc tính công khai, phiên tự tạo và phiên sau logout không cấp quyền service.
- Handler đăng xuất được kiểm tra cho cả ba vai trò và callback đóng cửa sổ, không cần mở Tkinter.
- Transaction: lỗi INSERT lịch sử sau UPDATE trạng thái rollback cả hai thay đổi.
- Đồng thời: hai kết nối thực sự tranh chấp khóa sinh viên; test quan sát performance_schema.data_lock_waits rồi mới thả khóa. Dùng lớp SEC-A có thật trong seed. Kiểm tra cả hai thứ tự, kết quả đăng ký, trạng thái cuối và người ghi lịch sử.
- Giữ các test lọc theo khoa, thống kê chưa phân lớp và xuất CSV.

Hai test khóa cần quyền đọc performance_schema.data_lock_waits và performance_schema.threads trên MySQL 8. Tài khoản test cần tạo/xóa database sms_test_*. Không sử dụng admin_db.

### Chạy trên Windows PowerShell

```powershell
python -m pip install -r requirements-dev.txt
$env:SMS_TEST_MYSQL_JSON='{"user":"root","password":"<your_password>","host":"localhost"}'
python -m pytest -q
```

Nếu chưa đặt biến, test MySQL skip; nếu đã đặt nhưng kết nối sai, test báo lỗi kết nối. Không coi lần chạy skip là kiểm chứng MySQL.

## Kiểm tra thủ công và giới hạn

Chưa thao tác trực quan trên Windows trong lần sửa này. Sau giải nén:

1. Đăng nhập đúng/sai cả ba vai trò, đăng xuất rồi đổi tài khoản.
2. Admin đổi trạng thái, kiểm tra người ghi lịch sử. Sinh viên Bảo lưu thử đăng ký mới.
3. Mở các tab thống kê, thử bộ lọc khoa/ngành/lớp, xuất CSV.
4. Đóng ứng dụng bằng nút X, mở lại phải đăng nhập lại.

Không reset database hoặc chạy lại seed. Sao lưu dữ liệu trước nâng cấp.

Script trung gian tests/add_tests.py không có trong gói vì nó chèn lại các test cũ, không phải bài kiểm thử cần chạy.
