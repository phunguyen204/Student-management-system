"""Dữ liệu mẫu cho hệ thống Quản lý Sinh viên (schema Step-2).

Script này tạo dữ liệu minh họa:
- 1 khoa, 2 ngành học
- 1 khóa tuyển sinh, 2 lớp hành chính
- 2 năm học với 3 học kỳ
- 10 môn học, 15 lớp học phần
- 6 giảng viên, 15 sinh viên
- Đăng ký, điểm, thanh toán mẫu
- 1 sinh viên học lại môn ở học kỳ sau (giữ điểm cũ)
- 1 sinh viên đổi trạng thái Bảo lưu (minh họa lịch sử)

Chạy lại nhiều lần an toàn – không sinh trùng, không xóa dữ liệu cũ.

LƯU Ý:
- Script chỉ nạp vào database có tên chứa 'demo' hoặc 'test'.
- Thêm cờ --force để bỏ qua kiểm tra tên database.
- Đây là TÀI KHOẢN MẪu dùng cho DEMO, không phải tài khoản thật.
"""

from gui.database import Database
from gui import services
from gui.scheduling import parse_multi_schedule
import random

_warn_count = 0


def _warn(msg):
    global _warn_count
    _warn_count += 1
    print(f"  ⚠️  CẢNH BÁO: {msg}")


def main():
    import sys
    from gui.config import get_db_connect_config
    cfg, db_name = get_db_connect_config()
    if "test" not in db_name.lower() and "demo" not in db_name.lower():
        if "--force" not in sys.argv:
            print(f"CẢNH BÁO: Database '{db_name}' có thể là dữ liệu thật.")
            print("Thêm cờ --force để tiếp tục nạp dữ liệu demo.")
            sys.exit(1)
            
    db = Database()

    # ═══════════════ 1. ORGANIZATION ═══════════════
    if not db.get_department("CNTT"): db.add_department("CNTT", "Công nghệ Thông tin")
    if not db.get_program("CNPM"): db.add_program("CNPM", "Công nghệ Phần mềm", "CNTT")
    if not db.get_program("HTTT"): db.add_program("HTTT", "Hệ thống Thông tin", "CNTT")

    # ═══════════════ 2. ADMISSION BATCH & ADMIN CLASSES ═══════════════
    if not db.get_admission_batch("K2023"): db.add_admission_batch("K2023", "Khóa 2023", 2023)
    if not db.get_admin_class("CNPM23A"): db.add_admin_class("CNPM23A", "CNPM23A", "CNPM", "K2023")
    if not db.get_admin_class("HTTT23A"): db.add_admin_class("HTTT23A", "HTTT23A", "HTTT", "K2023")

    # ═══════════════ 3. ACADEMIC YEARS & SEMESTERS ═══════════════
    if not db.get_academic_year("2025-2026"): db.add_academic_year("2025-2026", "Năm học 2025-2026", 2025, 2026)
    if not db.get_academic_year("2026-2027"): db.add_academic_year("2026-2027", "Năm học 2026-2027", 2026, 2027)
    if not db.get_semester("HK1-2526"): db.add_semester("HK1-2526", "Học kỳ 1", "2025-2026", "2025-09-01", "2026-01-15", registration_open=1)
    if not db.get_semester("HK2-2526"): db.add_semester("HK2-2526", "Học kỳ 2", "2025-2026", "2026-02-01", "2026-06-15", registration_open=1)
    if not db.get_semester("HK1-2627"): db.add_semester("HK1-2627", "Học kỳ 1", "2026-2027", "2026-09-01", "2027-01-15", registration_open=1)

    # ═══════════════ 4. LECTURERS ═══════════════
    lecturers = ["gv001", "gv002", "gv003", "gv004", "gv005", "gv006"]
    for gv in lecturers:
        if not db.get_user("Lecturer", gv):
            db.create_lecturer(gv, "123")

    # ═══════════════ 5. SUBJECTS (catalog) ═══════════════
    subjects = [
        ("PYTHON", "Lập trình Python", 3),
        ("CSDL", "Cơ sở dữ liệu", 3),
        ("GIAITICH", "Giải tích", 4),
        ("CTDL", "Cấu trúc dữ liệu", 3),
        ("AI", "Trí tuệ nhân tạo", 3),
        ("MANG", "Mạng máy tính", 3),
        ("HDH", "Hệ điều hành", 3),
        ("WEB", "Lập trình Web", 3),
        ("CNPM", "Công nghệ phần mềm", 3),
        ("KNM", "Kỹ năng mềm", 2),
    ]
    for sid, name, credits in subjects:
        if not db.get_subject(sid):
            db.add_subject(sid, name, credits)

    # ═══════════════ 6. CLASS SECTIONS ═══════════════
    # HK1-2526: 10 sections including 2 groups of CSDL
    sections_hk1 = [
        ("PYTHON-HK1-01", "PYTHON", "HK1-2526", "gv001", 50, "Thu 2 7h-9h; Thu 4 7h-9h"),
        ("CSDL-HK1-01", "CSDL", "HK1-2526", "gv002", 50, "Thu 3 9h-11h; Thu 5 9h-11h"),
        ("CSDL-HK1-02", "CSDL", "HK1-2526", "gv003", 45, "Thu 2 13h-15h; Thu 4 13h-15h"),
        ("GIAITICH-HK1-01", "GIAITICH", "HK1-2526", "gv001", 50, "Thu 5 7h-9h"),
        ("CTDL-HK1-01", "CTDL", "HK1-2526", "gv003", 45, "Thu 6 9h-11h"),
        ("AI-HK1-01", "AI", "HK1-2526", "gv004", 40, "Thu 6 13h-15h"),
        ("MANG-HK1-01", "MANG", "HK1-2526", "gv005", 50, "Thu 2 9h-11h"),
        ("HDH-HK1-01", "HDH", "HK1-2526", "gv006", 45, "Thu 3 7h-9h; Thu 5 13h-15h"),
        ("WEB-HK1-01", "WEB", "HK1-2526", "gv002", 50, "Thu 4 9h-11h"),
        ("KNM-HK1-01", "KNM", "HK1-2526", "gv006", 100, "Thu 7 9h-11h"),
    ]

    # HK2-2526: 5 sections, CSDL reopened (for retakes)
    sections_hk2 = [
        ("CNPM-HK2-01", "CNPM", "HK2-2526", "gv004", 40, "Thu 2 7h-9h; Thu 4 7h-9h"),
        ("CSDL-HK2-01", "CSDL", "HK2-2526", "gv002", 50, "Thu 3 7h-9h; Thu 5 7h-9h"),
        ("PYTHON-HK2-01", "PYTHON", "HK2-2526", "gv001", 50, "Thu 2 13h-15h"),
        ("AI-HK2-01", "AI", "HK2-2526", "gv004", 40, "Thu 6 9h-11h"),
        ("WEB-HK2-01", "WEB", "HK2-2526", "gv002", 50, "Thu 4 9h-11h; Thu 6 13h-15h"),
    ]

    for sid, subj_id, sem_id, lect, max_s, sched_str in sections_hk1 + sections_hk2:
        if db.get_section(sid):
            continue
        schedules = parse_multi_schedule(sched_str) or []
        try:
            services.create_class_section(db, sid, subj_id, sem_id, lect,
                                          max_s, schedules)
        except Exception as e:
            _warn(f"Tạo lớp HP {sid} thất bại: {e}")

    # ═══════════════ 7. STUDENTS ═══════════════
    student_ids = {}
    for i in range(1, 16):
        uname = f"sv{i:03d}"
        existing = db.get_user("Student", uname)
        if existing:
            student_ids[uname] = existing['mssv']
        else:
            student_ids[uname] = db.add_student(uname, "123")
            # Assign admin class
            class_id = "CNPM23A" if i <= 8 else "HTTT23A"
            try:
                services.assign_admin_class(db, uname, class_id)
            except Exception as e:
                _warn(f"Gán lớp HC cho {uname} thất bại: {e}")
            # Update profile
            names = [
                "Nguyễn Văn An", "Trần Thị Bình", "Lê Văn Cường",
                "Phạm Thị Dung", "Hoàng Văn Em", "Vũ Thị Phương",
                "Đặng Văn Giang", "Bùi Thị Hoa", "Ngô Văn Ích",
                "Đỗ Thị Kim", "Lý Văn Long", "Mai Thị Mai",
                "Trương Văn Nam", "Đinh Thị Oanh", "Cao Văn Phúc",
            ]
            db.update_student_profile(
                uname, name=names[i - 1],
                gender="Nam" if i % 2 else "Nữ",
                email=f"{uname}@university.edu.vn",
                phone=f"09{random.randint(10000000, 99999999)}")

    # ═══════════════ 8. ENROLLMENTS (HK1) ═══════════════
    hk1_enrollments = [
        ("sv001", "PYTHON-HK1-01"), ("sv001", "CSDL-HK1-01"),
        ("sv001", "AI-HK1-01"), ("sv001", "KNM-HK1-01"),
        ("sv002", "PYTHON-HK1-01"), ("sv002", "GIAITICH-HK1-01"),
        ("sv002", "MANG-HK1-01"),
        ("sv003", "GIAITICH-HK1-01"), ("sv003", "CTDL-HK1-01"),
        ("sv003", "HDH-HK1-01"),
        ("sv004", "CTDL-HK1-01"), ("sv004", "AI-HK1-01"),
        ("sv004", "WEB-HK1-01"),
        ("sv005", "PYTHON-HK1-01"), ("sv005", "CTDL-HK1-01"),
        ("sv005", "CSDL-HK1-02"),  # SV005 in CSDL group 2
    ]
    for uname, sec_id in hk1_enrollments:
        mssv = student_ids[uname]
        if sec_id not in db.get_enrollments(mssv, semester_id="HK1-2526"):
            try:
                services.enroll_student(db, mssv, sec_id)
            except Exception as e:
                _warn(f"Đăng ký {uname}→{sec_id} thất bại: {e}")

    # SV006-SV015: random 3 sections from HK1
    hk1_section_ids = [s[0] for s in sections_hk1]
    for i in range(6, 16):
        uname = f"sv{i:03d}"
        mssv = student_ids[uname]
        enrolled = db.get_enrollments(mssv, semester_id="HK1-2526")
        if len(enrolled) >= 3:
            continue
        # Pick sections that won't cause subject duplicates
        available = [s for s in hk1_section_ids if s not in enrolled]
        random.shuffle(available)
        enrolled_subjects = set()
        for sid in enrolled:
            sec = db.get_section(sid)
            if sec:
                enrolled_subjects.add(sec['subject_id'])
        count = 0
        for sid in available:
            if count >= 3 - len(enrolled):
                break
            sec = db.get_section(sid)
            if sec and sec['subject_id'] not in enrolled_subjects:
                try:
                    services.enroll_student(db, mssv, sid)
                    enrolled_subjects.add(sec['subject_id'])
                    count += 1
                except Exception as e:
                    _warn(f"Đăng ký {sid} cho {uname} thất bại: {e}")

    # ═══════════════ 9. GRADES (HK1) ═══════════════
    hk1_grades = [
        ("sv001", "PYTHON-HK1-01", 8.5, 9.0),
        ("sv001", "CSDL-HK1-01", 7.0, 8.0),
        ("sv001", "AI-HK1-01", 8.5, 8.0),
        ("sv001", "KNM-HK1-01", 9.0, 9.5),
        ("sv002", "PYTHON-HK1-01", 6.5, 7.5),
        ("sv002", "GIAITICH-HK1-01", 7.0, 7.0),
        ("sv003", "GIAITICH-HK1-01", 9.0, 9.5),
        ("sv003", "CTDL-HK1-01", 6.0, 6.5),
        ("sv004", "CTDL-HK1-01", 8.0, 8.5),
        ("sv004", "AI-HK1-01", 9.0, 9.5),
        ("sv005", "PYTHON-HK1-01", 7.5, 8.0),
        ("sv005", "CSDL-HK1-02", 3.0, 4.0),  # SV005 fails CSDL → will retake in HK2
    ]
    for uname, sec_id, mid, fin in hk1_grades:
        mssv = student_ids[uname]
        sec = db.get_section(sec_id)
        if sec:
            try:
                db.cursor.execute("SELECT midterm, final_score FROM grades g JOIN enrollments e ON g.enrollment_id = e.id WHERE e.mssv=%s AND e.section_id=%s", (mssv, sec_id))
                if not db.cursor.fetchone():
                    services.set_grade(db, mssv, sec_id, mid, fin,
                                       lecturer_username=sec['lecturer'])
            except Exception as e:
                _warn(f"Nhập điểm {uname}/{sec_id} thất bại: {e}")

    # ═══════════════ 10. HK2 ENROLLMENTS (retake scenario) ═══════════════
    # SV005 retakes CSDL in HK2 (different section, same subject)
    mssv_sv005 = student_ids["sv005"]
    if "CSDL-HK2-01" not in db.get_enrollments(mssv_sv005, semester_id="HK2-2526"):
        try:
            services.enroll_student(db, mssv_sv005, "CSDL-HK2-01")
        except Exception as e:
            _warn(f"Học lại {mssv_sv005} thất bại: {e}")

    # SV001 takes CNPM in HK2
    mssv_sv001 = student_ids["sv001"]
    if "CNPM-HK2-01" not in db.get_enrollments(mssv_sv001, semester_id="HK2-2526"):
        try:
            services.enroll_student(db, mssv_sv001, "CNPM-HK2-01")
        except Exception as e:
            _warn(f"Đăng ký HK2 cho SV001 thất bại: {e}")

    # ═══════════════ 11. GRADES (HK2 - retake) ═══════════════
    # SV005 gets better score on CSDL retake
    sec = db.get_section("CSDL-HK2-01")
    if sec:
        try:
            db.cursor.execute("SELECT midterm FROM grades g JOIN enrollments e ON g.enrollment_id = e.id WHERE e.mssv=%s AND e.section_id=%s", (mssv_sv005, "CSDL-HK2-01"))
            if not db.cursor.fetchone():
                services.set_grade(db, mssv_sv005, "CSDL-HK2-01", 7.5, 8.0,
                                   lecturer_username=sec['lecturer'])
        except Exception as e:
            _warn(f"Nhập điểm học lại thất bại: {e}")

    # ═══════════════ 12. SAMPLE PAYMENTS ═══════════════
    # SV001 pays for PYTHON-HK1-01
    try:
        sec = db.get_section("PYTHON-HK1-01")
        if sec:
            amt = sec['credits_snapshot'] * sec['tuition_per_credit']
            services.create_payment(db, student_ids["sv001"], "PYTHON-HK1-01",
                                    amt, status="Paid")
    except Exception as e:
        _warn(f"Tạo thanh toán mẫu thất bại: {e}")

    # ═══════════════ 13. ĐỔI TRẠNG THÁI MẪu (DEMO) ═══════════════
    # SV010 bảo lưu – minh họa lịch sử trạng thái
    # Đảm bảo tài khoản admin tồn tại (có bcrypt hash) trước khi gọi service.
    # create_default_admin() là idempotent và luôn dùng bcrypt.
    try:
        db.create_default_admin()
        mssv_sv010 = student_ids.get("sv010")
        if mssv_sv010:
            db.cursor.execute(
                "SELECT academic_status FROM students WHERE mssv=%s",
                (mssv_sv010,))
            row = db.cursor.fetchone()
            if row and row['academic_status'] == 'Đang học':
                with db.transaction():
                    db.cursor.execute("""
                        UPDATE students SET academic_status=%s WHERE mssv=%s
                    """, ("Bảo lưu", mssv_sv010))
                    
                    # Ghi lịch sử trạng thái
                    db.cursor.execute("""
                        INSERT INTO student_status_history
                            (mssv, old_status, new_status, reason, changed_by)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (mssv_sv010, "Đang học", "Bảo lưu",
                           "Lý do cá nhân (dữ liệu mẫu demo)", "admin"))
                print("  SV010 đã chuyển sang Bảo lưu")
            else:
                print("  SV010 đã ở trạng thái Bảo lưu hoặc không tìm thấy – bỏ qua.")
    except Exception as e:
        _warn(f"Đổi trạng thái SV010 thất bại: {e}")

    # ═══════════════ KẾT QUẢ ═══════════════
    if _warn_count == 0:
        print("\n✅ Dữ liệu mẫu đã được tạo thành công!")
    else:
        print(f"\n⚠️  Hoàn thành với {_warn_count} cảnh báo (xem chi tiết bên trên).")
    print("\n─── TÀI KHOẢN MẪu (DEMO) ───")
    print("   Admin  : admin / admin123")
    print("   GV     : gv001–gv006 / 123")
    print("   SV     : sv001–sv015 / 123")
    print("\n─── DỮ LIỆU MINH HỌA ───")
    print("   2 năm học, 3 học kỳ")
    print("   10 môn, 15 lớp HP (CSDL mở 2 nhóm HK1, mở lại HK2)")
    print("   15 sinh viên, 6 giảng viên")
    print("   SV005 học lại CSDL ở HK2 với điểm mới (điểm cũ vẫn giữ)")
    print("   SV010 đổi trạng thái Bảo lưu (xem lịch sử trong hồ sơ)")
    print("   SV001 đã thanh toán PYTHON-HK1-01")


if __name__ == "__main__":
    main()