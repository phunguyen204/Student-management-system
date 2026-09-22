# HƯỚNG DẪN CÀI ĐẶT VÀ TRỂN KHAI (DEPLOYMENT GUIDE)

Tài liệu hướng dẫn thiết lập môi trường, cấu hình cơ sở dữ liệu MySQL, thực hiện migration và khởi chạy hệ thống Quản lý Sinh viên trên Windows.

---

## 1. Yêu cầu Môi trường

- **Hệ điều hành**: Windows 10 / 11 (hoặc tương đương).
- **Python**: Version 3.10 trở lên.
- **MySQL Server**: Version 8.0 trở lên.
- **Thư viện Python phụ thuộc**:
  - `mysql-connector-python`
  - `pytest` (để chạy kiểm thử)

---

## 2. Cài đặt Phụ thuộc Python

Mở Terminal (PowerShell / Command Prompt) và chạy:

```bash
cd "c:\Users\Admin\Downloads\Student-management-system"
python -m pip install -r requirements-dev.txt
```

---

## 3. Cấu hình Kết nối MySQL

Cấu hình thông tin kết nối MySQL qua file `config.ini` hoặc **Biến môi trường (Environment Variables)**.

### Cách 1: Sử dụng file `config.ini` (Khuyên dùng cho local)

Sao chép file mẫu `config.ini.example` thành `config.ini`:

```bash
copy config.ini.example config.ini
```

Mở file `config.ini` và chỉnh sửa các tham số phù hợp với MySQL trên máy của bạn:

```ini
[mysql]
host = 127.0.0.1
port = 3306
user = root
password = Mật_Khẩu_MySQL_Của_Bạn
database = student_management
```

> **Lưu ý**: File `config.ini` đã được thêm vào `.gitignore` để không bị push mật khẩu thực lên repository.

### Cách 2: Sử dụng Biến môi trường (Khuyên dùng cho Server / CI/CD)

Thiết lập các biến môi trường sau trong hệ thống:

```cmd
set SMS_DB_HOST=127.0.0.1
set SMS_DB_PORT=3306
set SMS_DB_USER=root
set SMS_DB_PASSWORD=Mật_Khẩu_MySQL_Của_Bạn
set SMS_DB_NAME=student_management
```

---

## 4. Tạo Database và Thực hiện Migration

### Bước 4.1: Tạo Cơ sở dữ liệu và Schema cơ sở
Đảm bảo dịch vụ MySQL đang chạy, sau đó chạy ứng dụng để nó tự động tạo và migrate database:

```bash
cd "c:\Users\Admin\Downloads\Student-management-system"
python "Student Management System\main.py"
```
*(Lưu ý: Mở lên thấy giao diện đăng nhập thì có thể tắt đi, database đã được tạo và migrate tự động).*

### Bước 4.2: Nạp Dữ liệu Mẫu (Seed Data)
Tạo dữ liệu thử nghiệm (khoa, ngành, môn học, tài khoản mẫu, sinh viên, giảng viên):
> **Lưu ý**: Script chỉ chạy với database có tên chứa `demo` hoặc `test`. Thêm `--force` để bỏ qua kiểm tra.

```bash
cd "c:\Users\Admin\Downloads\Student-management-system"
python "Student Management System\insert_Data.py"
```

---

## 5. Khởi chạy Ứng dụng

Chạy ứng dụng bằng lệnh:

```bash
cd "c:\Users\Admin\Downloads\Student-management-system"
python "Student Management System\main.py"
```

---

## 6. Chạy Kiểm thử Tự động (Automated Testing)

Hệ thống có bộ test suite đầy đủ kiểm tra từ schema, trigger, procedure đến nghiệp vụ đăng ký và bảo vệ dữ liệu.

Chạy toàn bộ 130+ bài kiểm thử bằng `pytest`:

```bash
cd "c:\Users\Admin\Downloads\Student-management-system"
python -m pytest tests/ -v
```

---

## 7. Các Lưu ý Vận hành & Bảo mật

1. **Mật khẩu người dùng**: Tất cả mật khẩu trong hệ thống đã được mã hóa theo chuẩn **bcrypt** trước khi lưu vào MySQL.
2. **Bảo vệ Lịch sử**: Trạng thái học tập và học phí của sinh viên được lưu vết qua các bảng lịch sử (`student_status_history`, `payments`). Không tự ý xóa trực tiếp các bảng này trong MySQL.
3. **Cấu hình Tránh Hardcode**: Tuyệt đối không lưu mật khẩu MySQL vào code. Luôn cập nhật thông qua `config.ini` hoặc biến môi trường.
