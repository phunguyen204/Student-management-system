# HƯỚNG DẪN SỬ DỤNG HỆ THỐNG QUẢN LÝ SINH VIÊN

Hệ thống Quản lý Sinh viên (Student Management System) hỗ trợ 3 vai trò người dùng chính: **Quản trị viên (Admin)**, **Giảng viên (Lecturer)**, và **Sinh viên (Student)**.

---

## 1. Yêu cầu Hệ thống & Đăng nhập

### 1.1 Khởi động Ứng dụng
- Đảm bảo MySQL Server đang chạy và file `config.ini` (hoặc biến môi trường) đã được cấu hình đúng.
- Chạy lệnh sau trong Terminal / Command Prompt:
  ```bash
  cd "Student Management System"
  python main.py
  ```

### 1.2 Đăng nhập
1. Chọn **Vai trò**: `Sinh viên`, `Giảng viên`, hoặc `Quản trị viên`.
2. Nhập **Tên đăng nhập** và **Mật khẩu**.
3. Bấm nút **ĐĂNG NHẬP**.

*Tài khoản mẫu mặc định:*
- **Quản trị viên**: `admin` / `admin123`
- **Giảng viên**: `gv_nguyenvana` / `lecturer123`
- **Sinh viên**: `sv_nguyenvanb` / `student123`

---

## 2. Dành cho Quản trị viên (Admin)

Giao diện Quản trị viên gồm 8 phân hệ chính trên thanh điều hướng bên trái:

### 2.1 Tổng quan
- Hiển thị các thẻ thống kê: Tổng số môn học, Sinh viên, Giảng viên, Lượt đăng ký.
- Các bảng chi tiết số lượng sinh viên phân loại theo: Trạng thái học tập, Khoa, Ngành, Khóa tuyển sinh, Lớp hành chính.

### 2.2 Quản lý Khoa / Ngành
- **Khoa**: Thêm mới Mã khoa + Tên khoa; Chỉnh sửa thông tin khoa.
- **Ngành**: Thêm mới Mã ngành + Tên ngành thuộc Khoa; Chỉnh sửa thông tin ngành.

### 2.3 Năm học & Học kỳ
- Tạo Năm học (Ví dụ: `2025-2026`).
- Tạo Học kỳ thuộc Năm học (Ví dụ: `HK1`, `HK2`, `HK3`).
- Đóng/Mở đợt đăng ký môn học cấp Học kỳ.

### 2.4 Khóa TS & Lớp HC
- Tạo Khóa tuyển sinh (Ví dụ: `K2023`, `K2024`).
- Tạo Lớp hành chính gắn với Ngành và Khóa TS.

### 2.5 Danh mục Môn học
- Thêm môn học mới (Mã môn, Tên môn, Số tín chỉ).
- Sửa thông tin môn học hoặc xóa môn chưa có lớp học phần.

### 2.6 Quản lý Lớp học phần (HP)
- Tạo lớp học phần gắn với Môn học, Học kỳ, Giảng viên phụ trách, Sĩ số tối đa và Lịch học (VD: `Thu 2 7h-9h; Thu 4 13h-15h`).
- Đóng / Mở đợt đăng ký riêng cho từng lớp HP.
- Sửa sĩ số tối đa hoặc xóa lớp HP.

### 2.7 Tạo tài khoản Giảng viên
- Tạo tài khoản đăng nhập cho Giảng viên mới (Username, Mật khẩu, Họ tên, Email, Khoa phụ trách).

### 2.8 Quản lý Sinh viên
- **Tìm kiếm & Lọc**: Tìm theo Tên/MSSV/Username; Lọc theo Trạng thái học tập, Khoa, Ngành, Khóa TS, Lớp HC.
- **Phân trang**: Xem danh sách theo trang (50 sinh viên/trang).
- **Tạo tài khoản SV**: Nhập Username, Mật khẩu và Lớp HC để cấp tài khoản.
- **Chức năng bổ sung**:
  - *Xem hồ sơ*: Chi tiết lý lịch, lớp, ngành.
  - *Sửa thông tin*: Cập nhật Họ tên, Giới tính, Email, Phone, Địa chỉ, Lớp HC.
  - *Đổi trạng thái*: Cập nhật trạng thái (`Đang học`, `Bảo lưu`, `Thôi học`, `Tốt nghiệp`) kèm Lý do và lưu vào lịch sử.
  - *Đổi mật khẩu*: Reset mật khẩu cho sinh viên.
  - *Xuất CSV*: Xuất danh sách sinh viên đang lọc ra file Excel/CSV.

---

## 3. Dành cho Giảng viên (Lecturer)

### 3.1 Lớp giảng dạy
- Xem danh sách các lớp học phần được phân công giảng dạy.
- Xem danh sách sinh viên đăng ký trong từng lớp.

### 3.2 Nhập điểm
- Chọn lớp học phần và sinh viên cần nhập điểm.
- Nhập điểm Quá trình (Giữa kỳ) và điểm Thi (Cuối kỳ) theo thang điểm 10 (chấp nhận 1 chữ số thập phân, VD: `8.5`).
- Hệ thống tự động tính điểm tổng kết và xếp loại.

---

## 4. Dành cho Sinh viên (Student)

### 4.1 Tổng quan
- Xem thông tin cá nhân (Họ tên, MSSV, Lớp HC, Ngành).
- Tóm tắt số lớp đã đăng ký, Điểm trung bình (GPA), Tổng học phí đã thanh toán.

### 4.2 Đăng ký Môn học
- Chọn Học kỳ đang mở đăng ký để xem danh sách lớp học phần khả dụng.
- **Đăng ký**: Nhấp đôi (double-click) vào lớp HP muốn đăng ký.
- **Hủy đăng ký**: Chọn lớp đã đăng ký và bấm Hủy đăng ký (chỉ hủy được trong thời hạn cho phép).
- Hệ thống tự động kiểm tra: Trùng lịch học, vượt sĩ số tối đa, lớp đóng ĐK, môn học trùng.

### 4.3 Thời khóa biểu
- Xem danh sách các môn học đã đăng ký thành công trong học kỳ.
- Chi tiết thời gian, thứ trong tuần, phòng/lịch học và giảng viên.

### 4.4 Bảng điểm
- Xem kết quả học tập từng môn: Điểm quá trình, Điểm cuối kỳ, Điểm tổng kết, Điểm chữ và Trạng thái Đạt/KĐạt.

### 4.5 Học phí & Thanh toán
- Xem danh sách lớp HP và tính toán học phí snapshot (Số TC × Đơn giá/TC).
- Thực hiện **Thanh toán mô phỏng** để ghi nhận giao dịch vào lịch sử.

---

## 5. Lưu ý Bảo mật
- Tất cả mật khẩu trong hệ thống (Quản trị viên, Giảng viên, Sinh viên) đều được mã hóa bằng thuật toán **bcrypt** bảo mật cao trước khi lưu vào cơ sở dữ liệu.
- Quản trị viên chỉ có thể reset (đặt lại) mật khẩu chứ không thể xem được mật khẩu gốc của người dùng.

---

## 6. Kịch bản Demo Nhanh (5-10 phút)
Kịch bản này giúp thuyết trình viên trình bày đầy đủ các tính năng chính của hệ thống một cách trôi chảy:

**Bước 1: Khởi động và Đăng nhập Admin (2 phút)**
- Mở Terminal/CMD, di chuyển vào thư mục `Student Management System` và chạy `python main.py`.
- Đăng nhập bằng quyền Admin (`admin` / `admin123`).
- Giới thiệu màn hình Dashboard (Tổng quan số liệu sinh viên, khoa, ngành).
- Mở tab **Sinh viên**, tìm kiếm sinh viên và thực hiện đổi trạng thái học tập (ví dụ từ "Đang học" sang "Bảo lưu").

**Bước 2: Vai trò Sinh viên - Đăng ký môn và Thanh toán (4 phút)**
- Đăng xuất Admin, đăng nhập bằng tài khoản Sinh viên (`sv_nguyenvanb` / `student123`).
- Vào phần **Đăng ký học phần**, chọn một lớp để đăng ký (cho thấy tính năng kiểm tra trùng lịch/vượt sĩ số).
- Chuyển sang phần **Thời khóa biểu** để xem lịch học vừa đăng ký.
- Chuyển sang phần **Thanh toán**, thực hiện thanh toán học phí cho học kỳ hiện tại.

**Bước 3: Vai trò Giảng viên - Nhập điểm (3 phút)**
- Đăng xuất Sinh viên, đăng nhập bằng Giảng viên (`gv_nguyenvana` / `lecturer123`).
- Vào phần **Quản lý lớp**, chọn lớp học phần mà sinh viên vừa đăng ký (nếu có).
- Nhập điểm (Quá trình, Cuối kỳ) cho sinh viên và nhấn Lưu.

**Bước 4: Xác nhận kết quả (1 phút)**
- Đăng nhập lại bằng tài khoản Sinh viên.
- Vào phần **Bảng điểm** để kiểm tra điểm vừa được giảng viên nhập và điểm tổng kết đã tính tự động. Kết thúc demo.
