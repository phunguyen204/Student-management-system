# 🎓 Student Management System - Bước 3 (Hoàn thiện)

> **Tài liệu hoàn thiện Bước 3:** Chi tiết các sửa đổi, tính năng mới, phân quyền phiên bản desktop và đối soát được ghi tại [IMPLEMENTATION_STEP_3.md](IMPLEMENTATION_STEP_3.md).  
> **Tài liệu hoàn thiện Bước 2:** Chi tiết các sửa lỗi và đối soát được ghi tại [FIXES_STEP_2.md](FIXES_STEP_2.md).  
> **Lưu ý đối với Bước 1:** [FIXES_STEP_1.md](FIXES_STEP_1.md) ghi lại các sửa lỗi ban đầu của Bước 1.

---

## 📋 Mục lục

- [Giới thiệu](#giới-thiệu)
- [Kiến trúc Mô hình dữ liệu Bước 2](#kiến-trúc-mô-hình-dữ-liệu-bước-2)
- [Cấu trúc Cơ sở dữ liệu & Quan hệ](#cơ-sở-dữ-liệu--quan-hệ)
- [Tính năng chính](#tính-năng-chính)
- [Hướng dẫn Cài đặt & Khởi chạy](#hướng-dẫn-cài-đặt--khởi-chạy)
- [Hướng dẫn Nâng cấp & Khôi phục Migration](#hướng-dẫn-nâng-cấp--khôi-phục-migration)
- [Hướng dẫn Chạy Kiểm thử (Testing)](#hướng-dẫn-chạy-kiểm-thử-testing)
- [Lưu ý về Học phí & Thanh toán](#lưu-ý-về-học-phí--thanh-toán)

---

## Giới thiệu

**Student Management System (Bước 2)** là ứng dụng desktop quản lý đào tạo tín chỉ, sinh viên, học phần, đăng ký môn, điểm số và thanh toán học phí bằng Python (Tkinter/ttk) và MySQL.

Ở Bước 2, kiến trúc hệ thống được nâng cấp toàn diện nhằm giải quyết triệt để các hạn chế của mô hình Step-1:
- **Tách biệt Môn học (Subjects) và Lớp học phần (Class Sections)**: Môn học đóng vai trò khung đào tạo (mã môn, tên môn, số tín chỉ, học phí mỗi tín chỉ). Lớp học phần đại diện cho lớp được mở theo từng học kỳ (mã lớp, môn học, giảng viên, lịch học, sức chứa).
- **Phân biệt Lớp hành chính (Administrative Classes) và Lớp học phần**: Sinh viên thuộc về một Lớp hành chính (ví dụ: CNTT K65) do Ngành và Khóa tuyển sinh quản lý.
- **Quản lý Năm học & Học kỳ chuyên sâu**: Hệ thống theo dõi chính xác thời gian đăng ký, năm học và định dạng hiển thị học kỳ (dạng `HK1 (2025-2026)`).
- **Lịch sử Học tập độc lập & Bảo vệ dữ liệu**: Sinh viên có thể học lại môn học ở các học kỳ khác nhau; điểm số và thanh toán được liên kết chặt chẽ theo từng lượt đăng ký (`enrollment_id`).

---

## Kiến trúc Mô hình dữ liệu Bước 2

| Thực thể | Vai trò & Đặc điểm |
|---|---|
| **Môn học (Subject)** | Mã môn (`id`), Tên môn, Số tín chỉ, Học phí/tín chỉ. Không chứa thông tin giảng viên hay lịch học. |
| **Lớp học phần (Class Section)** | Thuộc một môn học trong một Học kỳ cụ thể. Có Mã lớp (`id`), Giảng viên phụ trách, Lịch học (`schedule`), Sĩ số tối đa (`max_students`). |
| **Lớp hành chính (Admin Class)** | Lớp quản lý hành chính sinh viên (ví dụ: `2021-CNTT-01`). Thuộc một Ngành (`Program`) và Khóa tuyển sinh (`Admission Batch`). |
| **Lượt đăng ký (Enrollment)** | Liên kết 1 Sinh viên với 1 Lớp học phần (`section_id`). Lưu trạng thái đăng ký, ngày đăng ký, điểm giữa kỳ, điểm cuối kỳ và tổng điểm. |
| **Giao dịch Thanh toán (Payment)** | Liên kết chính xác tới 1 Lượt đăng ký (`enrollment_id`), bảo đảm lịch sử tài chính độc lập cho mỗi lần học. |

---

## Cơ sở dữ liệu & Quan hệ

Cơ sở dữ liệu **`admin_db`** ở Bước 2 bao gồm các bảng sau:

```
[Faculties] ──< [Programs] ──< [Admin Classes] ──< [Students]
                     │                                   │
[Admission Batches] ─┘                                   │
                                                         │
[Academic Years] ──< [Semesters]                         │
                           │                             │
[Subjects] ──────────< [Class Sections]                  │
                           │                             │
                     [Enrollments] >─────────────────────┘
                           │
                     [Payments]
                           │
                     [Grades] (Lịch sử điểm)
```

### Chi tiết các bảng chính:
- `faculties`: Khoa đào tạo (`id`, `name`, `code`).
- `programs`: Ngành học (`id`, `name`, `faculty_id`).
- `admission_batches`: Khóa tuyển sinh (`id`, `name`, `academic_year`).
- `admin_classes`: Lớp hành chính (`id`, `name`, `program_id`, `batch_id`).
- `academic_years`: Năm học (`id`, `name`, `start_year`, `end_year`).
- `semesters`: Học kỳ (`id`, `name`, `year_id`, `start_date`, `end_date`, `registration_open`).
- `subjects`: Môn học (`id`, `name`, `credits`, `tuition_fee_per_credit`).
- `class_sections`: Lớp học phần (`id`, `subject_id`, `semester_id`, `lecturer_username`, `schedule`, `max_students`).
- `enrollments_v2` / `enrollments`: Lượt đăng ký (`id`, `mssv`, `section_id`, `enrolled_at`, `midterm_score`, `final_score`, `total_score`).
- `payments_v2` / `payments`: Lịch sử giao dịch (`id`, `enrollment_id`, `mssv`, `amount` DECIMAL(15,2), `status`, `paid_at`).
- `migration_versions`: Lưu vết tiến trình migration và các cảnh báo/báo cáo dữ liệu (`step_name`, `status`, `applied_at`, `details`).

---

## Tính năng chính

### 1. Phân quyền & Quản trị (Admin)
- Quản lý Cơ cấu Tổ chức: Khoa, Ngành, Khóa tuyển sinh, Lớp hành chính.
- Quản lý Đào tạo: Năm học, Học kỳ, Danh mục Môn học, Lớp học phần.
- Quản lý Trạng thái Sinh viên: Tích hợp cơ chế Phiên (Session) đăng nhập. Admin mới có quyền cập nhật trạng thái học tập của sinh viên (Bảo lưu, Thôi học...). Lưu ý: Phân quyền này thuộc tầng ứng dụng desktop, ngăn chặn việc sử dụng tài khoản Sinh viên/Giảng viên thực hiện thao tác sai quyền, nhưng không ngăn được việc chỉnh sửa trực tiếp trên cơ sở dữ liệu MySQL.
- Thống kê Hệ thống: Giao diện Dashboard hiển thị số lượng sinh viên chi tiết theo Trạng thái, Khoa, Ngành học, Khóa tuyển sinh, và Lớp hành chính.
- Bộ lọc Danh sách: Bộ lọc thông minh tự động điều chỉnh Lớp hành chính phụ thuộc theo Khoa hoặc Ngành đang được chọn.

### 2. Nghiệp vụ Giảng viên (Lecturer)
- Xem danh sách Lớp học phần phụ trách.
- Nhập điểm Giữa kỳ và Cuối kỳ. Hệ thống bảo vệ tuyệt đối không bị nhập nhầm lớp khi thay đổi combobox.

### 3. Nghiệp vụ Sinh viên (Student)
- Đăng ký Lớp học phần trực quan với kiểm tra ràng buộc thời gian thực:
  - Chống đăng ký vượt sĩ số tối đa của lớp.
  - Chống đăng ký trùng môn học trong cùng một học kỳ.
  - Chống trùng lịch học giữa các lớp học phần.
- Xem Lịch học & Thời khóa biểu.
- Xem Bảng điểm học tập tích lũy.
- Thanh toán Học phí theo lượt đăng ký và xem Lịch sử Giao dịch chi tiết.

---

## Hướng dẫn Cài đặt & Khởi chạy

### 1. Yêu cầu hệ thống
- Python 3.8 trở lên (đã test trên Python 3.12).
- MySQL Server 5.7 hoặc 8.x.
- Thư viện Python: `mysql-connector-python`, `bcrypt`, `pytest`.

### 2. Cài đặt phụ thuộc
```bash
pip install -r requirements.txt
```

### 3. Cấu hình Kết nối MySQL
Sao chép file mẫu và điền thông tin MySQL của bạn:
```bash
copy config.ini.example config.ini
```
Mở `config.ini` và điền thông số:
```ini
[mysql]
host = localhost
port = 3306
user = your_user
password = your_password
database = admin_db
```
Hoặc dùng biến môi trường (PowerShell):
```powershell
$env:SMS_DB_USER = "your_user"
$env:SMS_DB_PASSWORD = "your_password"
```

### 4. Khởi chạy Ứng dụng
```bash
cd "c:\Users\Admin\Downloads\Student-management-system"
python "Student Management System\main.py"
```

### 5. Khởi tạo Dữ liệu Mẫu (Tùy chọn)
> **Lưu ý**: Script chỉ chạy với database có tên chứa `demo` hoặc `test`. Thêm `--force` để bỏ qua kiểm tra.
```bash
cd "c:\Users\Admin\Downloads\Student-management-system"
python "Student Management System\insert_Data.py"
```

---

## Hướng dẫn Nâng cấp & Khôi phục Migration

Hệ thống tích hợp cơ chế **Migration tự động, an toàn và có khả năng phục hồi tự động (Fault-tolerant Migration Engine)** từ schema Step-1 sang Step-2.

### 1. Nguyên lý Migration Bước 2
- **Tự động phát hiện trạng thái**: Phân biệt Cài mới (`fresh_install`), Schema cũ (`step1`), Migration dở dang (`in_progress`), và Migration hoàn tất (`done`).
- **Xử lý Bảng dở dang**: Hệ thống hoán đổi bảng bằng một lệnh `RENAME TABLE` nguyên tử. Nếu phát hiện bảng xung đột (cả bảng cũ và bảng `*_v2` cùng tồn tại có dữ liệu), migration sẽ lập tức dừng và báo lỗi, không tự xóa dữ liệu để đảm bảo an toàn. Tương tự, nếu thiếu khóa ngoại hoặc sai cột đích, hệ thống sẽ phát hiện và chặn trạng thái `ready`.
- **Đối soát Thanh toán chặt chẽ**:
  - Giữ nguyên ID giao dịch cũ.
  - Chuyển đổi chính xác sang `DECIMAL(15,2)` bằng `Decimal('0.01')`.
  - Đối soát chi tiết tổng số tiền và tập hợp ID giao dịch.
  - Giao dịch mồ côi (không tìm thấy lượt đăng ký) được ghi nhận chi tiết vào bảng `migration_versions.details` và giữ nguyên dữ liệu gốc, không tự động tạo đăng ký giả.

### 2. Sao lưu và Xem Báo cáo Migration
- **Khuyến nghị Sao lưu**: Trước khi nâng cấp database sản xuất, nên chạy lệnh dump:
  ```bash
  mysqldump -u root -p admin_db > backup_step1.sql
  ```
- **Xem nhật ký & cảnh báo migration**:
  Có thể kiểm tra báo cáo chi tiết trong MySQL:
  ```sql
  SELECT step_name, status, applied_at, details FROM admin_db.migration_versions;
  ```

---

## Hướng dẫn Chạy Kiểm thử (Testing)

Bản sửa ngày 19/09/2026 có 130 test: 76 regression, 16 test phiên/đăng xuất và 38 MySQL integration. Đã chạy trên Python 3.12, MySQL 8.0.46: **130 passed, 0 failed, 0 skipped trong 12.52 giây**. Kết quả áp dụng cho các kịch bản đã kiểm thử, không thay thế kiểm tra giao diện thủ công.

### 1. Chạy Unit tests & Regression tests
```bash
python -m pytest tests/test_regressions.py tests/test_session.py
```

### 2. Chạy MySQL Integration Tests (DDL, FK & Migration)
Để chạy các bài kiểm thử thao tác cơ sở dữ liệu thật, hãy cung cấp chuỗi kết nối test qua biến môi trường `SMS_TEST_MYSQL_JSON`:

#### Trên Windows PowerShell:
```powershell
$env:SMS_TEST_MYSQL_JSON='{"user":"root","password":"<your_password>","host":"localhost"}'
python -m pytest tests/test_mysql_integration.py
```

#### Chạy toàn bộ Test Suite:
Khi chưa đặt `SMS_TEST_MYSQL_JSON`, 38 bài MySQL bị bỏ qua. Nếu đã đặt biến nhưng cấu hình kết nối sai, test báo lỗi, không âm thầm skip. Tài khoản kiểm thử cần quyền tạo/xóa database `sms_test_*`; hai bài tranh chấp khóa cần đọc `performance_schema.data_lock_waits` và `performance_schema.threads` trên MySQL 8. Mỗi test dùng database riêng, không dùng `admin_db`.
```powershell
$env:SMS_TEST_MYSQL_JSON='{"user":"root","password":"<your_password>","host":"localhost"}'
python -m pytest tests/
```

---

## Lưu ý về Học phí & Thanh toán

> [!NOTE]
> Chức năng Thanh toán Học phí hiện tại là **Mô phỏng Giao dịch (Simulated Payment System)** phục vụ quản lý đào tạo và đối soát dữ liệu nội bộ. Hệ thống ghi nhận lịch sử giao dịch, số tiền, trạng thái (`Paid` / `Pending`) và mã lượt đăng ký mà không thực hiện kết nối cổng thanh toán ngân hàng thực tế.

## Bản sửa phiên đăng nhập bước 3 (19/09/2026)

- `session.login(db, username, password, role)` gọi `Database.verify_user` trước khi tạo phiên. Đăng nhập sai hoặc lỗi DB hủy phiên cũ; không giữ mật khẩu.
- Cả ba vai trò đều hủy phiên khi đăng xuất; đóng cửa sổ cũng hủy phiên. Service đổi trạng thái không nhận username/role do bên gọi tự khai.
- Migration chỉ thay FK lịch sử tới sinh viên bằng một câu ALTER, giữ dữ liệu và các FK khác. FK đã đúng RESTRICT/NO ACTION không bị sửa lại.
- Giải nén bản sửa và chạy `python "Student Management System/main.py"` từ thư mục gốc. Không cần reset database hay chạy lại seed. Sao lưu database trước khi nâng cấp.
- Chi tiết kiểm thử và kiểm tra thủ công: `IMPLEMENTATION_STEP_3.md`.
