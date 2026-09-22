# 🛠️ Báo cáo Sửa lỗi và Hoàn thiện Bước 2 (Student Management System)

Tài liệu này ghi nhận chi tiết các lỗi đã khắc phục, phương pháp xử lý, kết quả kiểm thử và phạm vi ranh giới của **Bước 2** trong dự án Quản lý Sinh viên.

---

## 1. Danh sách các Lỗi đã khắc phục

### 1. Sửa Khả năng Khôi phục Migration & An toàn Khởi động
- **Vấn đề trước đây**: `Database.__init__` gọi `created_table()` trước khi thực hiện migration. Quá trình đổi tên bảng diễn ra theo từng bước riêng lẻ. Nếu ứng dụng bị ngắt giữa chừng (khi bảng cũ đã đổi tên sang `_legacy_*` nhưng bảng `*_v2` chưa đổi tên sang chính thức), lần khởi động sau `created_table()` tạo lại bảng rỗng chính thức. `step_rename_v2_tables()` bỏ qua vì bảng đích đã tồn tại, dẫn tới migration bị ghi nhận nhầm là `done` trong khi dữ liệu gốc nằm ở `*_v2`.
- **Giải pháp**:
  - resolve_coexisting_tables() chỉ đọc trạng thái để phát hiện xung đột.
    Khi bảng chính thức và bảng *_v2 cùng tồn tại, migration dừng và
    báo lỗi; không tự xóa bảng hoặc tắt kiểm tra khóa ngoại. 
  - Khóa migration toàn cục bằng `GET_LOCK('sms_migration_lock', 10)` trong suốt quá trình kiểm tra & thay đổi DDL.
  - Chuyển `_bootstrap_or_migrate()` lên trước `created_table()` trong `Database.__init__`.
  - Hàm `verify_migration_schema_and_data()` kiểm tra đủ từng `step_name` bắt buộc trong `STEP_ORDER`, xác minh sự tồn tại của khóa ngoại (`fk_enrollments_v2_section`, `fk_payments_v2_enrollment`), kiểu dữ liệu `DECIMAL(15,2)`, và phát hiện bản ghi mồ côi.
  - Loại bỏ nhánh mặc định `is_ready = True` khi chưa xác minh rõ ràng; nếu migration chưa thực sự hoàn tất, giao diện ứng dụng sẽ bị chặn và hiển thị thông báo chi tiết.

### 2. Hoàn thiện Đối soát Thanh toán & Chuyển đổi Tiền tệ
- **Vấn đề trước đây**: `step_migrate_payments()` chỉ kiểm tra số lượng giao dịch; tổng tiền chỉ ghi vào log mà chưa dùng để đối soát. Chuyển đổi từ `FLOAT` sang `DECIMAL` dễ sinh sai số làm sai lệch tổng tiền.
- **Giải pháp**:
  - Giữ nguyên ID giao dịch cũ khi chuyển sang `payments_v2`.
  - Hai giao dịch khác ID nhưng cùng số tiền, thời gian và lượt đăng ký vẫn được giữ riêng làm 2 giao dịch độc lập.
  - Khi ID đã tồn tại ở bảng đích, đối chiếu chi tiết nội dung (ID, enrollment_id, amount, status, paid_at). Nếu sai lệch nội dung, dừng migration và báo lỗi.
  - Quy đổi tiền tệ chính xác bằng `Decimal(str(r['amount'])).quantize(Decimal('0.01'))`.
  - Đối soát nghiêm ngặt 3 chỉ số: Tập hợp ID (`set(payment_ids)`), Tổng số lượng (`count`), và Tổng tiền (`sum(amount)`).
  - Các giao dịch mồ côi (không tìm được `enrollment_id` tương ứng) được ghi nhận chi tiết bằng ID và lý do vào `migration_versions.details`, giữ nguyên dữ liệu gốc, loại riêng khỏi tổng tiền đối soát và không tạo đăng ký giả.
  - Không nuốt lỗi `ALTER TABLE` khi nâng cấp kiểu dữ liệu.

### 3. Chuẩn hóa Hiển thị Học kỳ trên Giao diện
- **Vấn đề trước đây**: `_sem_display()` lấy ID giao dịch hoặc ID lớp làm tên học kỳ khi bản ghi chứa trường `id`, dẫn tới các chuỗi hiển thị sai lệch như "42 (2025-2026)".
- **Giải pháp**:
  - Ưu tiên đọc `semester_name` và `year_name` từ bản ghi nghiệp vụ (hoặc `semester_display`).
  - Chuẩn hóa định dạng hiển thị học kỳ duy nhất dạng: `"HK1 (2025-2026)"`.
  - Kiểm tra và đảm bảo hiển thị đúng trên tất cả màn hình: Bảng điểm, Lịch học, Học phí, Lịch sử thanh toán, Môn giảng viên phụ trách và Nhập điểm.
  - Bộ lọc học kỳ phân biệt chính xác các học kỳ cùng tên thuộc các năm học khác nhau (`semester_id`).

### 4. Hoàn thiện Chức năng Sửa Danh mục & Refresh Tức thì
- **Vấn đề trước đây**: Một số nút sửa danh mục Admin chỉ đổi được tên mà không chỉnh sửa được các thuộc tính liên quan (như khoa, ngành, năm học, ngày bắt đầu/kết thúc). UI không tự refresh sau khi chỉnh sửa.
- **Giải pháp**:
  - Nâng cấp modal chỉnh sửa đầy đủ cho: Ngành (`Program`), Khóa tuyển sinh (`Batch`), Lớp hành chính (`Admin Class`), Năm học (`Academic Year`), và Học kỳ (`Semester`).
  - Tải đúng giá trị hiện tại lên form sửa; giữ nguyên ID định danh.
  - Kiểm tra ràng buộc thời gian (ngày bắt đầu < ngày kết thúc, năm bắt đầu < năm kết thúc) và ràng buộc tham chiếu ở tầng dữ liệu `database.py`.
  - Bổ sung hàm `refresh_all_admin_comboboxes()` cập nhật ngay lập tức các danh sách và combobox phụ thuộc sau khi lưu, giữ lại lựa chọn hợp lệ mà không yêu cầu khởi động lại ứng dụng.

---

## 2. Kết quả Kiểm thử (Test Execution Results)

Kết quả chạy trên máy phát triển với MySQL được cấu hình qua
SMS_TEST_MYSQL_JSON:

Lệnh: python -m pytest -q
Tổng: 101 test
Passed: 101
Failed: 0
Skipped: 0
Thời gian: 12.90 giây

Bao gồm 76 test unit/regression và 25 test tích hợp MySQL.
Kết quả này xác nhận các kịch bản kiểm thử tự động hiện có;
kiểm tra thao tác giao diện được thực hiện riêng.

### Lệnh chạy kiểm thử với MySQL thực tế (PowerShell trên Windows)
Dùng thông tin kết nối mẫu sau để cấp quyền cho test suite chạy trên MySQL thật (lưu ý không dùng mật khẩu thật trong tài liệu):

```powershell
$env:SMS_TEST_MYSQL_JSON='{"user":"root","password":"<your_password>","host":"localhost"}'
python -m pytest
```

### Các kịch bản kiểm thử (đã lập trình nhưng chưa kiểm chứng thực tế trên MySQL trong lần chạy này):
1. `test_migration_dry_run_is_readonly`: Xác minh `dry-run` hoàn toàn chỉ đọc, báo cáo xung đột nhưng không thực thi bất kỳ thay đổi nào.
2. `test_migration_empty_target_with_v2_data_raises`: Bảng đích rỗng cùng tồn tại với `*_v2` có dữ liệu: dừng rõ ràng, không tự xóa bảng.
3. `test_migration_both_target_and_v2_have_data_raises`: Bảng đích và `*_v2` đều có dữ liệu: không ghi đè hoặc xóa.
4. `test_migration_interrupted_after_rename`: Khôi phục an toàn (so sánh toàn bộ nội dung sinh viên, đăng ký, điểm, thanh toán, khóa ngoại đích) qua luồng bootstrap thực tế khi migration bị ngắt sau khi đổi tên bảng.
5. `test_payment_migration_time_comparison`: Kiểm tra khắt khe cả trường `time`. Giao dịch cùng ID nhưng khác thời gian lập tức bị phát hiện và dừng migration.
6. `test_migration_idempotency_multiple_runs`: Chạy migration nhiều lần liên tiếp bảo tồn kết quả, không sinh trùng lặp.
7. `test_payment_migration_discrepancy_raises_error`: Phát hiện và dừng migration khi nội dung giao dịch đích trùng ID nhưng sai khác thông tin.
8. `test_payment_migration_duplicate_amount_and_unmapped`: Giao dịch không có lượt đăng ký được ghi log đầy đủ kèm ID và lý do. Hai giao dịch khác ID nhưng cùng thông tin vẫn được giữ đủ. Khóa ngoại trên bảng chính thức được xác minh đích đến.

---

## 3. Phạm vi & Giới hạn còn lại (Boundaries & Remaining Scope)

1. **Phạm vi giữ nguyên**:
   - Hệ thống giữ nguyên framework Tkinter/ttk và kết nối MySQL.
   - Giữ nguyên kiến trúc 3 vai trò (Admin, Lecturer, Student).
   - Không chuyển sang Web hay Framework ngoài phạm vi.
2. **Thanh toán Học phí**:
   - Chức năng thanh toán hiện tại là **Mô phỏng Giao dịch (Simulated Payment)** nhằm quản lý công nợ và lưu vết đối soát đào tạo. Chưa tích hợp cổng thanh toán trực tuyến thực tế (VNPay, MoMo, Banking API).
3. **Chưa triển khai Bước 3**:
   - Chưa mở rộng sang các tính năng nâng cao của Bước 3 (như xếp thời khóa biểu tự động, đăng ký nguyện vọng linh hoạt hay phân tích học tập dự báo).

---

## 4. Hướng dẫn Kiểm tra Thủ công trên Giao diện (Manual GUI Checklist)

1. **Khởi chạy ứng dụng**:
   ```bash
   cd "Student Management System"
   python main.py
   ```
2. **Đăng nhập Admin (`admin` / `admin123`)**:
   - Mở màn hình **Quản lý Ngành/Khóa/Lớp hành chính**: Nhấn Sửa Lớp hành chính -> Thay đổi Tên, Ngành hoặc Khóa tuyển sinh -> Nhấn Lưu. Xác nhận thông tin trên bảng và combobox cập nhật tức thì.
   - Mở màn hình **Quản lý Năm học / Học kỳ**: Nhấn Sửa Học kỳ -> Thay đổi ngày bắt đầu/kết thúc hoặc trạng thái đăng ký -> Nhấn Lưu.
3. **Đăng nhập Sinh viên (`sv01` / `123456` hoặc tài khoản đã tạo)**:
   - Kiểm tra **Bảng điểm**, **Lịch học**, và **Học phí**: Xác nhận tên học kỳ hiển thị dạng `HK1 (2025-2026)`, không bị biến thành số nguyên ID.
   - Đăng ký học phần: Chọn lớp học phần -> Thử đăng ký 2 lớp trùng lịch hoặc cùng môn -> Confirm ứng dụng hiển thị thông báo chặn chính xác.
