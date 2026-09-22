# Hướng dẫn Kiểm tra và Bàn giao (DEMO SCRIPT)

Tài liệu này hướng dẫn cách chạy hệ thống và nghiệm thu các tính năng đã được sửa chữa trong đợt bảo trì.

## 1. Chuẩn bị Môi trường

1. Mở PowerShell hoặc Terminal.
2. Thiết lập biến môi trường cấu hình database thử nghiệm:
```powershell
$env:SMS_DB_HOST="localhost"
$env:SMS_DB_PORT="3306"
$env:SMS_DB_USER="root"
$env:SMS_DB_PASSWORD="<mật_khẩu_mysql_của_bạn>"
$env:SMS_DB_NAME="sms_demo_db"
```
3. Chạy file chính để hệ thống tự động khởi tạo database và thực hiện migration:
```bash
cd "c:\Users\Admin\Downloads\Student-management-system"
python "Student Management System\main.py"
```
*(Nếu hiện lên bảng đăng nhập, hãy đóng cửa sổ lại để tiếp tục bước sau).*

## 2. Nạp Dữ liệu Mẫu và Kiểm tra Lỗi Câm (Silent Errors)

Chạy file tạo dữ liệu mẫu:
```bash
cd "c:\Users\Admin\Downloads\Student-management-system"
python "Student Management System\insert_Data.py"
```

**Kỳ vọng (Nghiệm thu nhóm 2):**
- Script chạy thành công từ đầu đến cuối.
- Quá trình chuyển trạng thái của sinh viên `sv010` sang "Bảo lưu" diễn ra thành công (in ra dòng chữ `SV010 đã chuyển sang Bảo lưu`).
- Nếu có lỗi trong quá trình tạo dữ liệu (vd: thiếu bảng, trùng ID), script sẽ in ra cảnh báo `⚠️ CẢNH BÁO: ...` thay vì bỏ qua một cách im lặng. Cuối script sẽ tổng hợp số lượng cảnh báo.
- Script sử dụng `bcrypt` (thông qua `create_default_admin()`) để tạo tài khoản admin thay vì dùng câu lệnh SQL plain-text, đảm bảo tài khoản admin hoạt động được ngay lập tức.

## 3. Kiểm tra Các Giao diện (Nghiệm thu nhóm 3)

Khởi động lại ứng dụng:
```bash
python "Student Management System\main.py"
```

### 3.1 Đăng nhập
Thử đăng nhập với các tài khoản:
- **Admin**: `admin` / `admin123`
- **Giảng viên**: `gv001` / `123`
- **Sinh viên**: `sv001` / `123`

### 3.2 Giao diện Admin - Lỗi thông báo tiếng Việt
1. Đăng nhập quyền **Admin**.
2. Thử tạo một Khoa hoặc Lớp Hành chính với mã **đã tồn tại** (ví dụ tạo khoa có mã `CNTT`).
3. **Kỳ vọng:** Sẽ hiện thông báo lỗi bằng Tiếng Việt "Dữ liệu này đã tồn tại (trùng mã). Vui lòng kiểm tra lại." (Title: "Lỗi").

### 3.3 Giao diện Admin - Cập nhật thanh cuộn (Scrollbars)
1. Truy cập các mục:
   - **Môn học**
   - **Lớp học phần**
   - **Quản lý sinh viên**
2. **Kỳ vọng:** Các bảng danh sách (Treeview) đều đã có thanh cuộn dọc (Scrollbar) ở bên phải, giúp xem dữ liệu dài dễ dàng hơn.

### 3.4 Giao diện Sinh viên - Trạng thái Bảng trống
1. Đăng nhập bằng một sinh viên chưa đăng ký môn học nào (vd: `sv015`).
2. Vào tab **Thời khóa biểu** hoặc **Bảng điểm** hoặc **Học phí**.
3. **Kỳ vọng:** Nếu chưa có dữ liệu, bảng sẽ hiển thị một dòng thông báo thân thiện như *"Chưa đăng ký lớp học phần nào"* hoặc *"Chưa có dữ liệu điểm"* thay vì một bảng hoàn toàn trống rỗng không có dấu hiệu gì.

## 4. Kiểm tra Xử lý Lỗi Kết nối Cơ sở dữ liệu (Nghiệm thu nhóm 3)

1. Tắt hoàn toàn ứng dụng.
2. Đổi mật khẩu trong biến môi trường thành mật khẩu **SAI**:
```powershell
$env:SMS_DB_PASSWORD="wrong_password"
```
3. Chạy lại ứng dụng:
```bash
python "Student Management System\main.py"
```
4. **Kỳ vọng:** Ứng dụng sẽ hiện lên một hộp thoại cảnh báo với tiêu đề **"Lỗi kết nối"** và thông báo *"Sai tên đăng nhập hoặc mật khẩu MySQL. Vui lòng kiểm tra cấu hình kết nối."* thay vì chỉ hiện dòng chữ tiếng Anh khó hiểu hoặc thoát đột ngột.

## 5. Tài liệu Khắc phục (Nghiệm thu nhóm 1 & 4)

Bạn có thể đọc file `README.md` và `DEPLOYMENT_GUIDE.md` để thấy rằng:
- Hướng dẫn cấu hình đã đổi sang `config.ini` thay vì sửa hardcode trong file Python.
- Mật khẩu mã hóa được đính chính lại là dùng thuật toán **bcrypt** (không phải SHA-256).
- Các lệnh chạy đã được bổ sung đường dẫn đầy đủ để tiện copy/paste.
