# Bản sửa bước 1 — Bảo vệ dữ liệu học vụ

Bản sửa xử lý bốn nhóm lỗi: nhập điểm nhầm môn, MSSV trùng, xóa mất lịch sử và đăng ký vượt sĩ số. Giữ giao diện desktop và mô hình môn học hiện tại; chưa triển khai mô hình học kỳ/lớp học phần của bước 2.

## Các thay đổi

| Phần | Hành vi sau khi sửa |
| --- | --- |
| Nhập điểm | Đổi môn sẽ xóa danh sách cũ và yêu cầu tải lại. Chỉ lưu điểm cho môn đã tải, giảng viên đang phụ trách và sinh viên có đăng ký. Kiểm tra điểm hữu hạn trong khoảng 0–10 tại tầng dữ liệu. |
| MSSV | Cấp số bằng bảng `id_sequences` có khóa dòng trong giao dịch. Có ràng buộc duy nhất trên MSSV. Tiếp tục đúng sau SV999; không đổi MSSV cũ. |
| Xóa sinh viên/môn | Chặn khi có đăng ký, điểm hoặc thanh toán. Chỉ xóa bản ghi chưa có lịch sử, trong một giao dịch. Khóa ngoại RESTRICT bảo vệ cả trường hợp xóa trực tiếp bằng SQL. |
| Đăng ký | Khóa sinh viên rồi khóa môn bằng `FOR UPDATE`; kiểm tra trùng, sĩ số, lịch và INSERT trong cùng giao dịch READ COMMITTED. Hai phiên tranh chỗ không thể cùng lấy chỗ cuối. |
| Hủy đăng ký | Kiểm tra thời hạn chính xác bằng giây trên đồng hồ DB; không hủy khi có điểm hoặc giao dịch học phí. Khóa theo cùng thứ tự với ghi điểm và thanh toán. |
| Lịch học | Không bỏ qua lịch sai hoặc phần dư của chuỗi lịch. Hỗ trợ một buổi/môn: `Thu 2 7h-9h`, `Thứ 2 7h30-9h30`, `CN 8-10`, `Mon 7-9AM`, `Tue 13:00-15:00`. Nhiều buổi/môn cần mô hình ở bước 2. |
| Học phí | Kiểm tra lại đăng ký và thanh toán đã có bên trong giao dịch để tránh dữ liệu giao diện cũ hoặc hai lần bấm đồng thời. Vẫn là mô phỏng ghi nhận Paid, chưa phải thanh toán thật. |
| Khởi động | Chỉ khởi tạo DB một lần; import giao diện không mở DB. Lỗi kết nối/nâng cấp được hiển thị và dừng mở ứng dụng. |
| Dữ liệu mẫu | Dùng MSSV thực tế của tài khoản được tạo, không giả định SV001 luôn là sinh viên đầu tiên trong DB hiện có. Cập nhật lời gọi lưu điểm theo chữ ký mới. |

## Cập nhật trên máy đang có dữ liệu

1. Đóng tất cả phiên ứng dụng cũ. Các máy dùng chung DB phải chuyển sang cùng bản mới; ứng dụng cũ không thực hiện các khóa giao dịch mới.
2. Sao lưu cơ sở dữ liệu trước lần chạy đầu. Trong MySQL Workbench dùng Server → Data Export → chọn `admin_db` → Export to Self-Contained File; giữ cả cấu trúc và dữ liệu. Không chạy dữ liệu mẫu vào cơ sở dữ liệu thật.
3. Giải nén gói mới. Từ thư mục có README, chạy `python -m pip install -r requirements.txt`.
4. Kiểm tra cấu hình MySQL tại `Student Management System/gui/database.py` cho phù hợp máy của bạn. Bản này giữ cơ chế cấu hình sẵn có. Tài khoản nâng cấp cần quyền tạo bảng, chỉ mục và sửa khóa ngoại.
5. Chạy:

```bash
cd "Student Management System"
python main.py
```

Lần mở đầu tự kiểm tra dữ liệu rồi thêm bộ đếm MSSV, chỉ mục duy nhất và khóa ngoại. Các bảng học vụ phải dùng InnoDB. Quá trình không tự đổi mã hoặc xóa dữ liệu cũ. Khi gặp MSSV trùng/thiếu hoặc bản ghi không tìm được sinh viên/môn liên quan, ứng dụng dừng và báo bảng/vấn đề cần đối chiếu. Không xóa bản ghi để vượt qua thông báo khi chưa xác định chủ sở hữu dữ liệu.

DDL của MySQL có commit riêng, nên nâng cấp cấu trúc không phải một giao dịch có thể rollback toàn bộ. Có thể chạy lại sau khi sửa lỗi; các bước đã thực hiện được nhận diện và không được tạo trùng. Nếu cần quay lại hoàn toàn bản trước, dùng cả mã nguồn và bản sao lưu DB trước cập nhật.

## Kiểm thử

Từ thư mục có README:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
```

Kiểm thử logic/giao diện chạy không cần MySQL và không mở cửa sổ. Kiểm thử tích hợp mặc định được bỏ qua nếu chưa cấu hình `SMS_TEST_MYSQL_JSON`.

Để kiểm thử tích hợp trên một MySQL/MariaDB dành riêng cho thử nghiệm, dùng PowerShell:

```powershell
$env:SMS_TEST_MYSQL_JSON='{"host":"127.0.0.1","port":3306,"user":"sms_test","password":"YOUR_TEST_PASSWORD"}'
python -m pytest -q tests
Remove-Item Env:SMS_TEST_MYSQL_JSON
```

Tài khoản thử nghiệm phải được phép CREATE/DROP DATABASE. Bộ test chỉ tạo/xóa database có tiền tố `sms_test_` và tên ngẫu nhiên, không dùng `admin_db`. Mỗi phiên thử đồng thời dùng kết nối riêng.

Các tình huống bao gồm: đổi combobox mà chưa tải lớp; ghi điểm sai giảng viên/sinh viên chưa đăng ký; điểm không hợp lệ; mốc MSSV 999→1000; nhiều phiên tạo MSSV; hai phiên tranh chỗ cuối; cùng sinh viên đăng ký hai môn trùng lịch đồng thời; lỗi làm rollback bộ đếm; chặn xóa lịch sử; nâng cấp khóa ngoại CASCADE cũ; không tự sửa MSSV trùng; thanh toán và hủy đăng ký đồng thời.

Kết quả kiểm tra bản đóng gói: **60 kiểm thử đạt** (50 kiểm thử logic/giao diện không mở cửa sổ, 10 kiểm thử tích hợp). Môi trường: Python 3.12, MariaDB 10.11.14/InnoDB, mysql-connector-python 26.7.0, bcrypt 5.0.0. Kiểm thử tích hợp dùng dữ liệu tổng hợp trong database tạm riêng. Chưa kiểm thử trên Oracle MySQL hoặc dữ liệu thật của bạn.

Gói phát hành bỏ thư mục `.git` và các cache Python/pytest; giữ mã ứng dụng, script chuyển mật khẩu cũ, hướng dẫn và bộ kiểm thử.

## Giới hạn còn lại

- Chưa thay đổi mô hình môn học thành môn học/lớp học phần/học kỳ, chưa bổ sung trạng thái bảo lưu/thôi học hay quy trình rút môn có hoàn phí.
- Khóa dòng bảo vệ các thao tác của bản ứng dụng mới; quản trị viên sửa DB bằng SQL thủ công vẫn phải tuân thủ quy trình. Ràng buộc sĩ số không phải một CHECK constraint độc lập ở DB.
- Kiểm tra giảng viên ở tầng dữ liệu sử dụng danh tính do ứng dụng truyền vào. Client vẫn kết nối DB trực tiếp; chưa có máy chủ xác thực độc lập và phân quyền an toàn trước client bị sửa.
- Cấu hình kết nối viết trong mã, mật khẩu admin mặc định và đăng nhập tương thích mật khẩu cũ vẫn là các hạng mục bảo mật cần xử lý tiếp.
- Chưa xác nhận giao diện trực quan trên Windows hoặc chạy trên DB riêng của người dùng. Cần chạy thử trên bản sao lưu dữ liệu của bạn trước khi thay bản đang sử dụng.
- Báo cáo Word chưa được sửa trong bước này.

## Tệp chính

`gui/database.py`, `gui/interface.py`, `gui/scheduling.py`, `main.py`, `insert_Data.py`, `tests/`, `requirements.txt`, `requirements-dev.txt`.
