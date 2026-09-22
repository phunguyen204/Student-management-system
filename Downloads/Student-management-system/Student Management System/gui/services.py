"""Business-logic services for the Student Management System.

All transactional rules — enrollment validation, grade entry checks, payment
guards — live here so they can be tested independently of the UI.  Each
service method receives a ``Database`` instance and performs its work inside a
DB transaction (using ``db.transaction()``).
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import List, Optional, Tuple

from .scheduling import schedule_conflicts, sessions_overlap

VALID_STATUSES = {"Đang học", "Bảo lưu", "Thôi học", "Tốt nghiệp"}


class ValidationError(ValueError):
    """An operation violates a business rule; no changes were saved."""


# ── helpers ──────────────────────────────────────────────────────────────────

def _lock_student(db, mssv):
    """Lock the student row for the duration of the current transaction."""
    db.cursor.execute(
        "SELECT username FROM students WHERE mssv=%s FOR UPDATE", (mssv,))
    if not db.cursor.fetchone():
        raise ValidationError("Sinh viên không còn tồn tại.")


def _lock_section(db, section_id):
    """Lock a class section and return its row dict, or raise."""
    db.cursor.execute(
        "SELECT * FROM class_sections WHERE id=%s FOR UPDATE", (section_id,))
    section = db.cursor.fetchone()
    if not section:
        raise ValidationError("Lớp học phần không còn tồn tại.")
    return section


def _count_section_enrollments(db, section_id):
    db.cursor.execute(
        "SELECT COUNT(*) AS cnt FROM enrollments WHERE section_id=%s", (section_id,))
    return db.cursor.fetchone()['cnt']


def _get_section_schedules(db, section_id):
    """Return list of (weekday, start_minutes, end_minutes) for a section."""
    db.cursor.execute(
        "SELECT weekday, start_minutes, end_minutes FROM section_schedules "
        "WHERE section_id=%s", (section_id,))
    return [(r['weekday'], r['start_minutes'], r['end_minutes'])
            for r in db.cursor.fetchall()]


def _validate_schedule_entries(schedules):
    """Validate individual schedule entries and check for self-overlap.

    Raises ValidationError for invalid weekday, times, or overlapping sessions.
    """
    for i, (weekday, start_min, end_min) in enumerate(schedules):
        if not isinstance(weekday, int) or weekday < 2 or weekday > 8:
            raise ValidationError(
                f"Buổi {i+1}: thứ {weekday} không hợp lệ (phải từ 2 đến 8, 8=CN).")
        if not isinstance(start_min, int) or not isinstance(end_min, int):
            raise ValidationError(f"Buổi {i+1}: giờ phải là số nguyên.")
        if start_min < 0 or end_min < 0 or start_min >= 1440 or end_min > 1440:
            raise ValidationError(
                f"Buổi {i+1}: giờ phải từ 0 đến 1440 phút.")
        if start_min >= end_min:
            raise ValidationError(
                f"Buổi {i+1}: giờ bắt đầu ({start_min}) phải trước giờ kết thúc ({end_min}).")

    # Check for self-overlap within the section's own sessions
    for i in range(len(schedules)):
        for j in range(i + 1, len(schedules)):
            if sessions_overlap(schedules[i], schedules[j]):
                raise ValidationError(
                    f"Buổi {i+1} và buổi {j+1} chồng lấn nhau.")


# ── Enrollment Service ───────────────────────────────────────────────────────

def enroll_student(db, mssv: str, section_id: str):
    """Enroll a student in a class section.

    Checks performed inside a single READ COMMITTED transaction:
    1. Student exists (locked).
    2. Section exists (locked) and is open for registration.
    3. Semester is open for registration.
    4. Student not already enrolled in this section.
    5. Student not already enrolled in another section of the *same subject*
       in the *same semester*.
    6. Capacity not exceeded.
    7. Section must have a valid schedule (at least one session).
    8. No schedule conflict with any of the student's existing enrollments
       (checks ALL sessions of both sections).
    """
    with db.transaction():
        _lock_student(db, mssv)
        
        # Check student status
        db.cursor.execute("SELECT academic_status FROM students WHERE mssv=%s", (mssv,))
        student_row = db.cursor.fetchone()
        if student_row and student_row.get('academic_status', 'Đang học') != 'Đang học':
            raise ValidationError(
                f"Sinh viên không ở trạng thái 'Đang học' (hiện tại: {student_row['academic_status']}). "
                "Không thể đăng ký học phần mới."
            )

        section = _lock_section(db, section_id)

        # Registration open checks
        if not section['registration_open']:
            raise ValidationError("Lớp học phần này đã đóng đăng ký.")

        db.cursor.execute(
            "SELECT registration_open FROM semesters WHERE id=%s",
            (section['semester_id'],))
        sem = db.cursor.fetchone()
        if not sem or not sem['registration_open']:
            raise ValidationError("Học kỳ này chưa mở đăng ký.")

        # Already enrolled in this exact section?
        db.cursor.execute(
            "SELECT id FROM enrollments WHERE mssv=%s AND section_id=%s",
            (mssv, section_id))
        if db.cursor.fetchone():
            raise ValidationError("Bạn đã đăng ký lớp học phần này.")

        # Already enrolled in another section of the same subject this semester?
        db.cursor.execute("""
            SELECT cs.id FROM enrollments e
            JOIN class_sections cs ON cs.id = e.section_id
            WHERE e.mssv=%s AND cs.subject_id=%s AND cs.semester_id=%s
        """, (mssv, section['subject_id'], section['semester_id']))
        if db.cursor.fetchone():
            raise ValidationError(
                "Bạn đã đăng ký một nhóm khác của cùng môn học trong học kỳ này.")

        # Capacity
        if _count_section_enrollments(db, section_id) >= section['max_students']:
            raise ValidationError("Lớp đã đủ sĩ số. Vui lòng chọn lớp khác.")

        # Schedule: section MUST have a valid schedule
        new_schedule = _get_section_schedules(db, section_id)
        if not new_schedule:
            raise ValidationError(
                "Lớp học phần chưa có lịch học. Không thể đăng ký.")

        # Schedule conflict (check ALL sessions)
        # Get all enrolled sections' schedules in the SAME semester
        db.cursor.execute("""
            SELECT e.section_id, cs.semester_id
            FROM enrollments e
            JOIN class_sections cs ON cs.id = e.section_id
            WHERE e.mssv=%s AND cs.semester_id=%s
        """, (mssv, section['semester_id']))
        enrolled_sections = db.cursor.fetchall()

        for es in enrolled_sections:
            old_schedule = _get_section_schedules(db, es['section_id'])
            if not old_schedule:
                # Already-enrolled section has no schedule — flag this
                raise ValidationError(
                    f"Lớp đã đăng ký {es['section_id']} thiếu dữ liệu lịch. "
                    f"Cần xử lý trước khi đăng ký thêm.")
            conflict = schedule_conflicts(new_schedule, old_schedule)
            if conflict:
                # Get section name for error message
                db.cursor.execute(
                    "SELECT s.name FROM class_sections cs "
                    "JOIN subjects s ON s.id = cs.subject_id "
                    "WHERE cs.id=%s", (es['section_id'],))
                name_row = db.cursor.fetchone()
                conflict_name = name_row['name'] if name_row else es['section_id']
                raise ValidationError(
                    f"Trùng lịch với lớp {conflict_name} ({es['section_id']}).")

        db.cursor.execute(
            "INSERT INTO enrollments (mssv, section_id, enrolled_at) "
            "VALUES (%s, %s, NOW())", (mssv, section_id))


def unenroll_student(db, mssv: str, section_id: str, deadline_days: int = 7):
    """Remove a student's enrollment if within the allowed period."""
    with db.transaction():
        _lock_student(db, mssv)
        _lock_section(db, section_id)

        db.cursor.execute("""
            SELECT id, enrolled_at,
                   TIMESTAMPDIFF(SECOND, enrolled_at, NOW()) AS age_seconds
            FROM enrollments WHERE mssv=%s AND section_id=%s FOR UPDATE
        """, (mssv, section_id))
        row = db.cursor.fetchone()
        if not row:
            raise ValidationError("Bạn chưa đăng ký lớp học phần này.")
        if (row['age_seconds'] is None or row['age_seconds'] < 0
                or row['age_seconds'] > deadline_days * 86400):
            raise ValidationError(
                "Đã quá hạn hủy hoặc ngày đăng ký không hợp lệ.")

        eid = row['id']
        # Check for grades or payments
        db.cursor.execute(
            "SELECT 1 FROM grades WHERE enrollment_id=%s LIMIT 1", (eid,))
        if db.cursor.fetchone():
            raise ValidationError(
                "Không thể hủy lớp đã có điểm; cần xử lý học vụ trước.")
        db.cursor.execute(
            "SELECT 1 FROM payments WHERE enrollment_id=%s LIMIT 1", (eid,))
        if db.cursor.fetchone():
            raise ValidationError(
                "Không thể hủy lớp đã có giao dịch học phí; cần xử lý học vụ trước.")

        db.cursor.execute("DELETE FROM enrollments WHERE id=%s", (eid,))


# ── Grade Service ────────────────────────────────────────────────────────────

def set_grade(db, mssv: str, section_id: str, midterm: float, final: float,
              *, lecturer_username: str):
    """Record or update grades for a student in a specific section.

    Validates:
    - Scores are finite numbers in [0, 10].
    - The lecturer is assigned to this section.
    - The student is enrolled in this section.
    """
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 10
           for v in (midterm, final)):
        raise ValidationError("Điểm phải là số hữu hạn từ 0 đến 10.")

    with db.transaction():
        _lock_student(db, mssv)
        section = _lock_section(db, section_id)

        if section['lecturer'] != lecturer_username:
            raise ValidationError(
                "Giảng viên không được phân công cho lớp học phần này.")

        db.cursor.execute(
            "SELECT id FROM enrollments WHERE mssv=%s AND section_id=%s FOR UPDATE",
            (mssv, section_id))
        enrollment = db.cursor.fetchone()
        if not enrollment:
            raise ValidationError(
                "Sinh viên chưa đăng ký lớp học phần này; không thể ghi điểm.")

        eid = enrollment['id']
        db.cursor.execute("""
            INSERT INTO grades (enrollment_id, midterm, final_score)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE midterm=VALUES(midterm), final_score=VALUES(final_score)
        """, (eid, midterm, final))


# ── Payment Service ──────────────────────────────────────────────────────────

def create_payment(db, mssv: str, section_id: str, amount=None,
                   status: str = "Pending"):
    """Record a tuition payment for a student's enrollment in a section.

    This is a simulation — no real payment gateway is integrated.

    The tuition amount is calculated from ``credits_snapshot × tuition_per_credit``
    stored on the class section.  If *amount* is provided, it must match the
    calculated tuition; otherwise the service calculates it.
    """
    with db.transaction():
        _lock_student(db, mssv)
        section = _lock_section(db, section_id)

        db.cursor.execute(
            "SELECT id FROM enrollments WHERE mssv=%s AND section_id=%s FOR UPDATE",
            (mssv, section_id))
        enrollment = db.cursor.fetchone()
        if not enrollment:
            raise ValidationError("Bạn chưa đăng ký lớp học phần này.")
        eid = enrollment['id']

        db.cursor.execute(
            "SELECT 1 FROM payments WHERE enrollment_id=%s AND status='Paid' LIMIT 1",
            (eid,))
        if db.cursor.fetchone():
            raise ValidationError("Lớp học phần này đã được thanh toán.")

        # Calculate expected tuition from section data
        credits = section['credits_snapshot']
        price_per_credit = section['tuition_per_credit']
        expected_amount = Decimal(str(credits)) * Decimal(str(price_per_credit))

        if amount is not None:
            # Validate the provided amount matches expected
            try:
                provided = Decimal(str(amount))
            except (InvalidOperation, ValueError):
                raise ValidationError("Số tiền không hợp lệ.")
            if provided <= 0:
                raise ValidationError("Số tiền phải lớn hơn 0.")
            if provided != expected_amount:
                raise ValidationError(
                    f"Số tiền ({provided:,.0f}) không khớp học phí phải đóng "
                    f"({expected_amount:,.0f} = {credits} TC × {price_per_credit:,.0f}/TC).")
            final_amount = provided
        else:
            final_amount = expected_amount

        db.cursor.execute(
            "INSERT INTO payments (enrollment_id, amount, status, time) "
            "VALUES (%s, %s, %s, NOW())", (eid, final_amount, status))
        return db.cursor.lastrowid


# ── Section Management ───────────────────────────────────────────────────────

def create_class_section(db, section_id: str, subject_id: str, semester_id: str,
                         lecturer: Optional[str], max_students: int,
                         schedules: List[Tuple[int, int, int]],
                         tuition_per_credit: int = 500_000):
    """Create a new class section with its schedule sessions.

    The entire operation (section + all schedule entries) runs inside a single
    transaction.  An error at any point rolls back everything.

    If no schedules are provided, the section is created as a draft with
    registration_open = 0.
    """
    # ── Input validation (before transaction) ────────────────────────
    if not section_id or not section_id.strip():
        raise ValidationError("Mã lớp học phần không được để trống.")
    if not subject_id or not subject_id.strip():
        raise ValidationError("Mã môn học không được để trống.")
    if not semester_id or not semester_id.strip():
        raise ValidationError("Mã học kỳ không được để trống.")

    if not isinstance(max_students, int) or max_students <= 0:
        raise ValidationError("Sĩ số tối đa phải là số dương.")

    try:
        tpc = Decimal(str(tuition_per_credit))
    except (InvalidOperation, ValueError):
        raise ValidationError("Đơn giá mỗi tín chỉ không hợp lệ.")
    if tpc < 0:
        raise ValidationError("Đơn giá mỗi tín chỉ phải >= 0.")

    # Validate schedule entries
    if schedules:
        _validate_schedule_entries(schedules)

    # Draft mode: no schedule → closed for registration
    is_draft = not schedules
    reg_open = 0 if is_draft else 1

    with db.transaction():
        # Validate subject exists
        db.cursor.execute("SELECT credits FROM subjects WHERE id=%s", (subject_id,))
        subj = db.cursor.fetchone()
        if not subj:
            raise ValidationError("Môn học không tồn tại.")
        credits_val = subj['credits']
        if not isinstance(credits_val, int) or credits_val <= 0:
            raise ValidationError("Số tín chỉ của môn học không hợp lệ.")

        # Validate semester exists
        db.cursor.execute("SELECT id FROM semesters WHERE id=%s", (semester_id,))
        if not db.cursor.fetchone():
            raise ValidationError("Học kỳ không tồn tại.")

        # Validate lecturer exists (if specified)
        if lecturer:
            db.cursor.execute("SELECT username FROM lecturers WHERE username=%s", (lecturer,))
            if not db.cursor.fetchone():
                raise ValidationError("Giảng viên không tồn tại.")

        credits_snapshot = credits_val

        db.cursor.execute(
            "INSERT INTO class_sections "
            "(id, subject_id, semester_id, lecturer, max_students, "
            " registration_open, credits_snapshot, tuition_per_credit) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (section_id, subject_id, semester_id, lecturer, max_students,
             reg_open, credits_snapshot, tpc))

        for weekday, start_min, end_min in schedules:
            db.cursor.execute(
                "INSERT INTO section_schedules (section_id, weekday, start_minutes, end_minutes) "
                "VALUES (%s, %s, %s, %s)",
                (section_id, weekday, start_min, end_min))


def update_class_section(db, section_id: str, *, lecturer: Optional[str] = None,
                         max_students: Optional[int] = None,
                         registration_open: Optional[int] = None,
                         schedules: Optional[List[Tuple[int, int, int]]] = None):
    """Update a class section. Blocks changes that would corrupt history."""
    with db.transaction():
        section = _lock_section(db, section_id)
        has_enrollments = _count_section_enrollments(db, section_id) > 0

        parts, params = [], []
        if lecturer is not None:
            if has_enrollments and lecturer != section['lecturer']:
                raise ValidationError(
                    "Không thể đổi giảng viên khi lớp đã có sinh viên đăng ký.")
            if lecturer:
                db.cursor.execute(
                    "SELECT username FROM lecturers WHERE username=%s", (lecturer,))
                if not db.cursor.fetchone():
                    raise ValidationError("Giảng viên không tồn tại.")
            parts.append("lecturer=%s"); params.append(lecturer)

        if max_students is not None:
            if not isinstance(max_students, int) or max_students <= 0:
                raise ValidationError("Sĩ số tối đa phải là số dương.")
            current_count = _count_section_enrollments(db, section_id)
            if max_students < current_count:
                raise ValidationError(
                    f"Sĩ số tối đa ({max_students}) không thể nhỏ hơn "
                    f"số đã đăng ký ({current_count}).")
            parts.append("max_students=%s"); params.append(max_students)

        if registration_open is not None:
            # Block opening registration for draft sections (no schedule)
            if registration_open == 1:
                current_scheds = _get_section_schedules(db, section_id)
                if not current_scheds and (schedules is None or not schedules):
                    raise ValidationError(
                        "Không thể mở đăng ký cho lớp chưa có lịch học.")
            parts.append("registration_open=%s"); params.append(registration_open)

        if parts:
            params.append(section_id)
            db.cursor.execute(
                f"UPDATE class_sections SET {', '.join(parts)} WHERE id=%s",
                tuple(params))

        if schedules is not None:
            if has_enrollments:
                raise ValidationError(
                    "Không thể đổi lịch học khi lớp đã có sinh viên đăng ký.")
            _validate_schedule_entries(schedules)
            db.cursor.execute(
                "DELETE FROM section_schedules WHERE section_id=%s", (section_id,))
            for weekday, start_min, end_min in schedules:
                db.cursor.execute(
                    "INSERT INTO section_schedules "
                    "(section_id, weekday, start_minutes, end_minutes) "
                    "VALUES (%s, %s, %s, %s)",
                    (section_id, weekday, start_min, end_min))


def delete_class_section(db, section_id: str):
    """Delete a class section only if it has no enrollment history."""
    with db.transaction():
        _lock_section(db, section_id)
        if _count_section_enrollments(db, section_id) > 0:
            raise ValidationError(
                "Không thể xóa lớp học phần đã có đăng ký. Cần giữ lịch sử.")
        db.cursor.execute(
            "DELETE FROM section_schedules WHERE section_id=%s", (section_id,))
        db.cursor.execute(
            "DELETE FROM class_sections WHERE id=%s", (section_id,))


# ── Subject Management ───────────────────────────────────────────────────────

def delete_subject(db, subject_id: str):
    """Delete a subject only if no class sections reference it."""
    with db.transaction():
        db.cursor.execute(
            "SELECT id FROM subjects WHERE id=%s FOR UPDATE", (subject_id,))
        if not db.cursor.fetchone():
            raise ValidationError("Môn học không tồn tại.")
        db.cursor.execute(
            "SELECT 1 FROM class_sections WHERE subject_id=%s LIMIT 1", (subject_id,))
        if db.cursor.fetchone():
            raise ValidationError(
                "Không thể xóa môn học đã có lớp học phần. Cần giữ lịch sử.")
        db.cursor.execute("DELETE FROM subjects WHERE id=%s", (subject_id,))


# ── Student Admin Class Assignment ───────────────────────────────────────────

def assign_admin_class(db, username: str, admin_class_id: Optional[str]):
    """Assign (or clear) a student's administrative class."""
    if admin_class_id:
        db.cursor.execute(
            "SELECT id, program_id, batch_id FROM admin_classes WHERE id=%s",
            (admin_class_id,))
        if not db.cursor.fetchone():
            raise ValidationError("Lớp hành chính không tồn tại.")
    db.cursor.execute(
        "UPDATE students SET admin_class_id=%s WHERE username=%s",
        (admin_class_id, username))
    db.conn.commit()


# ── Delete Guards for Catalog Entities ───────────────────────────────────────

def delete_student(db, username: str):
    """Delete a student only if they have no enrollment history."""
    with db.transaction():
        db.cursor.execute(
            "SELECT mssv FROM students WHERE username=%s FOR UPDATE", (username,))
        student = db.cursor.fetchone()
        if not student:
            raise ValidationError("Sinh viên không còn tồn tại.")
        # Check enrollments
        db.cursor.execute(
            "SELECT 1 FROM enrollments WHERE mssv=%s LIMIT 1", (student['mssv'],))
        if db.cursor.fetchone():
            raise ValidationError(
                "Không thể xóa sinh viên đã có đăng ký. Cần giữ lịch sử.")
        
        # Check status history
        db.cursor.execute(
            "SELECT 1 FROM student_status_history WHERE mssv=%s LIMIT 1", (student['mssv'],))
        if db.cursor.fetchone():
            raise ValidationError(
                "Không thể xóa sinh viên đã có lịch sử thay đổi trạng thái.")
                
        db.cursor.execute("DELETE FROM students WHERE username=%s", (username,))


def delete_department(db, dept_id: str):
    """Delete a department only if no programs reference it."""
    with db.transaction():
        db.cursor.execute(
            "SELECT id FROM departments WHERE id=%s FOR UPDATE", (dept_id,))
        if not db.cursor.fetchone():
            raise ValidationError("Khoa không tồn tại.")
        db.cursor.execute(
            "SELECT 1 FROM programs WHERE department_id=%s LIMIT 1", (dept_id,))
        if db.cursor.fetchone():
            raise ValidationError("Không thể xóa khoa đã có ngành học.")
        db.cursor.execute("DELETE FROM departments WHERE id=%s", (dept_id,))


def delete_program(db, program_id: str):
    """Delete a program only if no admin classes reference it."""
    with db.transaction():
        db.cursor.execute(
            "SELECT id FROM programs WHERE id=%s FOR UPDATE", (program_id,))
        if not db.cursor.fetchone():
            raise ValidationError("Ngành không tồn tại.")
        db.cursor.execute(
            "SELECT 1 FROM admin_classes WHERE program_id=%s LIMIT 1", (program_id,))
        if db.cursor.fetchone():
            raise ValidationError("Không thể xóa ngành đã có lớp hành chính.")
        db.cursor.execute("DELETE FROM programs WHERE id=%s", (program_id,))


def delete_admission_batch(db, batch_id: str):
    """Delete an admission batch only if no admin classes reference it."""
    with db.transaction():
        db.cursor.execute(
            "SELECT id FROM admission_batches WHERE id=%s FOR UPDATE", (batch_id,))
        if not db.cursor.fetchone():
            raise ValidationError("Khóa tuyển sinh không tồn tại.")
        db.cursor.execute(
            "SELECT 1 FROM admin_classes WHERE batch_id=%s LIMIT 1", (batch_id,))
        if db.cursor.fetchone():
            raise ValidationError("Không thể xóa khóa đã có lớp hành chính.")
        db.cursor.execute("DELETE FROM admission_batches WHERE id=%s", (batch_id,))


def delete_admin_class(db, class_id: str):
    """Delete an admin class only if no students are assigned to it."""
    with db.transaction():
        db.cursor.execute(
            "SELECT id FROM admin_classes WHERE id=%s FOR UPDATE", (class_id,))
        if not db.cursor.fetchone():
            raise ValidationError("Lớp hành chính không tồn tại.")
        db.cursor.execute(
            "SELECT 1 FROM students WHERE admin_class_id=%s LIMIT 1", (class_id,))
        if db.cursor.fetchone():
            raise ValidationError("Không thể xóa lớp hành chính đã có sinh viên.")
        db.cursor.execute("DELETE FROM admin_classes WHERE id=%s", (class_id,))

# ── Student Status Management ────────────────────────────────────────────────

def change_student_status(db, mssv: str, new_status: str, reason: str):
    """Change the academic status of a student and record the change in history.
    
    Must be performed within a single transaction.
    If the status is the same, ValidationError is raised.
    """
    from .session import session
    identity = session.get_identity()
    if identity is None:
        raise ValidationError("Chưa đăng nhập.")
    current_username, current_role = identity

    if current_role != "Admin":
        raise ValidationError("Chỉ Admin mới có quyền đổi trạng thái sinh viên.")
        
    db.cursor.execute("SELECT username FROM admins WHERE username=%s", (current_username,))
    if not db.cursor.fetchone():
        raise ValidationError("Không xác định được danh tính Admin.")

    new_status = new_status.strip() if new_status else ""
    reason = reason.strip() if reason else ""

    if not new_status:
        raise ValidationError("Trạng thái mới không được để trống.")
    if new_status not in VALID_STATUSES:
        raise ValidationError(f"Trạng thái '{new_status}' không hợp lệ.")
    if not reason:
        raise ValidationError("Lý do thay đổi bắt buộc phải nhập.")

    with db.transaction():
        # lock student
        _lock_student(db, mssv)
        
        db.cursor.execute("SELECT academic_status FROM students WHERE mssv=%s", (mssv,))
        row = db.cursor.fetchone()
        if not row:
            raise ValidationError("Sinh viên không tồn tại.")
            
        old_status = row.get('academic_status', 'Đang học')
        if old_status == new_status:
            raise ValidationError(f"Trạng thái hiện tại đã là '{new_status}'. Không có thay đổi nào.")
            
        # Update status
        db.cursor.execute(
            "UPDATE students SET academic_status=%s WHERE mssv=%s",
            (new_status, mssv)
        )
        
        # Record history
        db.cursor.execute(
            """INSERT INTO student_status_history 
               (mssv, old_status, new_status, changed_by, reason) 
               VALUES (%s, %s, %s, %s, %s)""",
            (mssv, old_status, new_status, current_username, reason)
        )

# ── CSV Export ───────────────────────────────────────────────────────────────

def export_students_csv(db, search_term: str, filters: dict, file_path: str):
    """Export student data to CSV file.
    
    Extracts all matching records from the database, escapes potential Excel formula
    injections, and writes them with UTF-8 BOM to a CSV file.
    """
    import csv
    
    rows = db.list_students(search=search_term, filters=filters)
    if not rows:
        return 0
        
    def escape_formula(value):
        if value is None:
            return ""
        val_str = str(value)
        # Check if starts with =, +, -, @ or a space/control char followed by them
        if val_str and val_str.lstrip().startswith(('=', '+', '-', '@')):
            return "'" + val_str
        return val_str

    with open(file_path, mode='w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(["MSSV", "Họ tên", "Khoa", "Ngành", "Khóa tuyển sinh", "Lớp hành chính", "Trạng thái", "Email", "Điện thoại"])
        for r in rows:
            writer.writerow([
                escape_formula(r['mssv']),
                escape_formula(r.get('name', '')),
                escape_formula(r.get('department_name', '')),
                escape_formula(r.get('program_name', '')),
                escape_formula(r.get('batch_name', '')),
                escape_formula(r.get('class_name', '')),
                escape_formula(r.get('academic_status', 'Đang học')),
                escape_formula(r.get('email', '')),
                escape_formula(r.get('phone', ''))
            ])
            
    return len(rows)
