"""Versioned, idempotent migration from the Step-1 schema to Step-2.

Each migration step is tracked in the ``migration_versions`` table so the
script can be re-run safely.  MySQL DDL auto-commits, so structural changes
cannot be rolled back.  **Always back up before running.**

State detection:
  - Fresh install: no ``courses`` table AND no ``migration_versions`` table
  - Step-1 data: ``courses`` table exists, no ``migration_versions``
  - Migration in-progress: ``migration_versions`` exists with incomplete steps
  - Migration complete: all steps in STEP_ORDER marked 'done'

Usage (standalone):
    cd "Student Management System"
    python -m gui.migration          # dry-run report
    python -m gui.migration --apply  # actually migrate

The migration is also invoked automatically by ``Database.__init__`` on
application startup when it detects a migration is needed.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from decimal import Decimal

from .scheduling import parse_schedule

log = logging.getLogger("sms.migration")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _table_exists(cursor, table_name):
    cursor.execute(
        "SELECT COUNT(*) AS n FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table_name,))
    return cursor.fetchone()['n'] > 0


def _column_exists(cursor, table_name, column_name):
    cursor.execute("SHOW COLUMNS FROM `%s` LIKE %%s" % table_name, (column_name,))
    return cursor.fetchone() is not None


def _fk_exists(cursor, table_name, fk_name):
    """Check whether a foreign key constraint with the given name exists."""
    cursor.execute(
        "SELECT COUNT(*) AS n FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s "
        "AND CONSTRAINT_NAME=%s AND CONSTRAINT_TYPE='FOREIGN KEY'",
        (table_name, fk_name))
    return cursor.fetchone()['n'] > 0


def _any_fk_on_column(cursor, table_name, column_name):
    """Check whether any FK exists on the given column."""
    cursor.execute(
        "SELECT COUNT(*) AS n FROM information_schema.KEY_COLUMN_USAGE "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s "
        "AND COLUMN_NAME=%s AND REFERENCED_TABLE_NAME IS NOT NULL",
        (table_name, column_name))
    return cursor.fetchone()['n'] > 0


def _step_done(cursor, step_name):
    """Check whether *step_name* has been recorded as completed."""
    if not _table_exists(cursor, 'migration_versions'):
        return False
    cursor.execute("SELECT 1 FROM migration_versions WHERE step_name=%s AND status='done'",
                   (step_name,))
    return cursor.fetchone() is not None


def _mark_done(cursor, conn, step_name, details=None):
    """Record a step as done. Uses INSERT ON DUPLICATE KEY to be safe."""
    cursor.execute(
        "INSERT INTO migration_versions (step_name, status, applied_at, details) "
        "VALUES (%s, 'done', NOW(), %s) "
        "ON DUPLICATE KEY UPDATE status='done', applied_at=NOW(), "
        "details=CASE WHEN VALUES(details) IS NOT NULL THEN "
        "  CONCAT(COALESCE(details, ''), '\\n', VALUES(details)) "
        "  ELSE details END",
        (step_name, details))
    conn.commit()


def _save_warning(cursor, conn, step_name, detail):
    """Append warning details to a migration step using INSERT ... ON DUPLICATE KEY.

    Never UPDATEs a row that doesn't exist yet. Appends to existing details.
    """
    cursor.execute(
        "INSERT INTO migration_versions (step_name, status, applied_at, details) "
        "VALUES (%s, 'in_progress', NOW(), %s) "
        "ON DUPLICATE KEY UPDATE "
        "details=CONCAT(COALESCE(details, ''), '\\n', VALUES(details))",
        (step_name, detail))
    conn.commit()


# ---------------------------------------------------------------------------
# Migration steps
# ---------------------------------------------------------------------------

STEP_ORDER = [
    "create_migration_table",
    "create_org_tables",
    "create_academic_tables",
    "create_subject_table",
    "create_section_tables",
    "create_enrollment_v2",
    "create_grades_v2",
    "create_payments_v2",
    "add_student_admin_class",
    "migrate_courses_to_subjects",
    "migrate_enrollments",
    "migrate_grades",
    "migrate_payments",
    "rename_legacy_tables",
    "rename_v2_tables",
    "update_id_sequences_fk",
    "add_student_status",
    "create_student_status_history",
    "change_history_fk_restrict",
]


def step_create_migration_table(cursor, conn):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS migration_versions (
        step_name VARCHAR(100) PRIMARY KEY,
        status VARCHAR(20) NOT NULL DEFAULT 'pending',
        applied_at DATETIME NULL,
        details TEXT NULL
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    conn.commit()


def step_create_org_tables(cursor, conn):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS departments (
        id VARCHAR(20) PRIMARY KEY,
        name VARCHAR(255) NOT NULL UNIQUE
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS programs (
        id VARCHAR(20) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        department_id VARCHAR(20),
        FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admission_batches (
        id VARCHAR(20) PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        year INT NOT NULL
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS admin_classes (
        id VARCHAR(20) PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        program_id VARCHAR(20),
        batch_id VARCHAR(20),
        FOREIGN KEY (program_id) REFERENCES programs(id) ON DELETE RESTRICT,
        FOREIGN KEY (batch_id) REFERENCES admission_batches(id) ON DELETE RESTRICT,
        UNIQUE KEY uq_admin_class (program_id, batch_id, name)
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    conn.commit()


def step_create_academic_tables(cursor, conn):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS academic_years (
        id VARCHAR(20) PRIMARY KEY,
        name VARCHAR(100) NOT NULL UNIQUE,
        start_year INT NULL,
        end_year INT NULL
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS semesters (
        id VARCHAR(20) PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        academic_year_id VARCHAR(20) NOT NULL,
        start_date DATE NULL,
        end_date DATE NULL,
        registration_open TINYINT(1) NOT NULL DEFAULT 0,
        FOREIGN KEY (academic_year_id) REFERENCES academic_years(id) ON DELETE RESTRICT,
        UNIQUE KEY uq_semester (academic_year_id, name)
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    conn.commit()


def step_create_subject_table(cursor, conn):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subjects (
        id VARCHAR(50) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        credits INT NOT NULL
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    conn.commit()


def step_create_section_tables(cursor, conn):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS class_sections (
        id VARCHAR(50) PRIMARY KEY,
        subject_id VARCHAR(50) NOT NULL,
        semester_id VARCHAR(20) NOT NULL,
        lecturer VARCHAR(255) NULL,
        max_students INT NOT NULL DEFAULT 40,
        registration_open TINYINT(1) NOT NULL DEFAULT 1,
        credits_snapshot INT NOT NULL,
        tuition_per_credit DECIMAL(15,2) NOT NULL DEFAULT 500000,
        FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE RESTRICT,
        FOREIGN KEY (semester_id) REFERENCES semesters(id) ON DELETE RESTRICT,
        FOREIGN KEY (lecturer) REFERENCES lecturers(username) ON DELETE SET NULL
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS section_schedules (
        id INT AUTO_INCREMENT PRIMARY KEY,
        section_id VARCHAR(50) NOT NULL,
        weekday TINYINT NOT NULL,
        start_minutes SMALLINT NOT NULL,
        end_minutes SMALLINT NOT NULL,
        FOREIGN KEY (section_id) REFERENCES class_sections(id) ON DELETE CASCADE
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    conn.commit()


def step_create_enrollment_v2(cursor, conn):
    if _table_exists(cursor, 'enrollments_v2') or (_table_exists(cursor, 'enrollments') and _column_exists(cursor, 'enrollments', 'section_id')):
        return
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS enrollments_v2 (
        id INT AUTO_INCREMENT PRIMARY KEY,
        mssv VARCHAR(20) NOT NULL,
        section_id VARCHAR(50) NOT NULL,
        enrolled_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_enrollment (mssv, section_id),
        FOREIGN KEY (mssv) REFERENCES students(mssv) ON DELETE RESTRICT,
        FOREIGN KEY (section_id) REFERENCES class_sections(id) ON DELETE RESTRICT
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    conn.commit()


def step_create_grades_v2(cursor, conn):
    if _table_exists(cursor, 'grades_v2') or (_table_exists(cursor, 'grades') and _column_exists(cursor, 'grades', 'enrollment_id')):
        return
    ref_table = 'enrollments_v2' if _table_exists(cursor, 'enrollments_v2') else 'enrollments'
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS grades_v2 (
        enrollment_id INT PRIMARY KEY,
        midterm FLOAT NULL,
        final_score FLOAT NULL,
        FOREIGN KEY (enrollment_id) REFERENCES `{ref_table}`(id) ON DELETE RESTRICT
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    conn.commit()


def step_create_payments_v2(cursor, conn):
    if _table_exists(cursor, 'payments_v2') or (_table_exists(cursor, 'payments') and _column_exists(cursor, 'payments', 'enrollment_id')):
        return
    ref_table = 'enrollments_v2' if _table_exists(cursor, 'enrollments_v2') else 'enrollments'
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS payments_v2 (
        id INT AUTO_INCREMENT PRIMARY KEY,
        enrollment_id INT NOT NULL,
        amount DECIMAL(15,2) NOT NULL,
        status VARCHAR(20) NOT NULL,
        time DATETIME NOT NULL,
        FOREIGN KEY (enrollment_id) REFERENCES `{ref_table}`(id) ON DELETE RESTRICT
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    conn.commit()


def step_add_student_admin_class(cursor, conn):
    """Add admin_class_id column AND FK independently."""
    # Step A: add column if missing
    if not _column_exists(cursor, 'students', 'admin_class_id'):
        cursor.execute(
            "ALTER TABLE students ADD COLUMN admin_class_id VARCHAR(20) NULL")
        conn.commit()

    # Step B: add FK if missing (independent of column creation)
    if not _any_fk_on_column(cursor, 'students', 'admin_class_id'):
        # Check for data that would violate the FK
        cursor.execute("""
            SELECT s.username, s.admin_class_id
            FROM students s
            WHERE s.admin_class_id IS NOT NULL
              AND s.admin_class_id NOT IN (SELECT id FROM admin_classes)
        """)
        violations = cursor.fetchall()
        if violations:
            detail_lines = [
                f"Student '{v['username']}' has admin_class_id='{v['admin_class_id']}' "
                f"which does not exist in admin_classes"
                for v in violations
            ]
            detail = "; ".join(detail_lines)
            log.warning("FK violation in students.admin_class_id: %s", detail)
            _save_warning(cursor, conn, 'add_student_admin_class', detail)
            # NULL out invalid references so FK can be created
            # Do NOT do this — user asked not to silently fix data.
            # Instead, raise so the step fails and user must fix.
            raise RuntimeError(
                f"Không thể thêm khóa ngoại admin_class_id: {len(violations)} sinh viên "
                f"có lớp hành chính không tồn tại. Cần sửa dữ liệu trước: {detail}")

        cursor.execute(
            "ALTER TABLE students ADD CONSTRAINT fk_students_admin_class "
            "FOREIGN KEY (admin_class_id) REFERENCES admin_classes(id) ON DELETE SET NULL")
        conn.commit()


def _get_legacy_table(cursor, main_name, legacy_name, step1_col):
    """Return the table name containing step-1 legacy data, or None if not present."""
    if _table_exists(cursor, legacy_name):
        return legacy_name
    if _table_exists(cursor, main_name) and _column_exists(cursor, main_name, step1_col):
        return main_name
    return None


def step_migrate_courses_to_subjects(cursor, conn):
    """Copy each legacy course into subjects + class_sections + section_schedules."""
    tbl = _get_legacy_table(cursor, 'courses', '_legacy_courses', 'name')
    if not tbl:
        log.info("No legacy courses table; nothing to migrate.")
        return

    # Create default academic year + semester for legacy data
    cursor.execute(
        "INSERT IGNORE INTO academic_years (id, name, start_year, end_year) "
        "VALUES ('LEGACY', 'Dữ liệu cũ', NULL, NULL)")
    cursor.execute(
        "INSERT IGNORE INTO semesters (id, name, academic_year_id, start_date, end_date, registration_open) "
        "VALUES ('LEGACY-SEM', 'Dữ liệu cũ — chưa xác định học kỳ', 'LEGACY', NULL, NULL, 0)")
    conn.commit()

    cursor.execute(f"SELECT * FROM `{tbl}`")
    courses = cursor.fetchall()
    warnings = []

    for c in courses:
        cid = c['id']
        cursor.execute(
            "INSERT IGNORE INTO subjects (id, name, credits) VALUES (%s, %s, %s)",
            (cid, c['name'], c['credits']))

        cursor.execute(
            "SELECT id FROM class_sections WHERE id=%s", (cid,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO class_sections "
                "(id, subject_id, semester_id, lecturer, max_students, "
                " registration_open, credits_snapshot, tuition_per_credit) "
                "VALUES (%s, %s, 'LEGACY-SEM', %s, %s, 0, %s, 500000)",
                (cid, cid, c.get('lecturer'), c.get('max_students', 40), c['credits']))

        cursor.execute(
            "SELECT COUNT(*) AS n FROM section_schedules WHERE section_id=%s", (cid,))
        if cursor.fetchone()['n'] == 0:
            sched = parse_schedule(c.get('schedule', ''))
            if sched:
                cursor.execute(
                    "INSERT INTO section_schedules (section_id, weekday, start_minutes, end_minutes) "
                    "VALUES (%s, %s, %s, %s)",
                    (cid, sched[0], sched[1], sched[2]))
            else:
                warnings.append(f"Course {cid}: lịch '{c.get('schedule')}' không parse được, bỏ qua lịch.")

    conn.commit()
    if warnings:
        detail = "; ".join(warnings)
        log.warning("Migration warnings: %s", detail)
        _save_warning(cursor, conn, 'migrate_courses_to_subjects', detail)


def step_migrate_enrollments(cursor, conn):
    """Copy legacy enrollments into enrollments_v2."""
    tbl = _get_legacy_table(cursor, 'enrollments', '_legacy_enrollments', 'course_id')
    if not tbl:
        return

    has_enrolled_at = _column_exists(cursor, tbl, 'enrolled_at')
    enrolled_at_expr = "e.enrolled_at" if has_enrolled_at else "NULL AS enrolled_at"
    cursor.execute(f"""
        SELECT e.mssv, e.course_id, {enrolled_at_expr}
        FROM `{tbl}` e
        INNER JOIN students s ON s.mssv = e.mssv
        INNER JOIN class_sections cs ON cs.id = e.course_id
    """)
    rows = cursor.fetchall()
    warnings = []

    for r in rows:
        cursor.execute(
            "SELECT id FROM enrollments_v2 WHERE mssv=%s AND section_id=%s",
            (r['mssv'], r['course_id']))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO enrollments_v2 (mssv, section_id, enrolled_at) "
                "VALUES (%s, %s, %s)",
                (r['mssv'], r['course_id'], r.get('enrolled_at')))

    cursor.execute(f"""
        SELECT e.mssv, e.course_id FROM `{tbl}` e
        LEFT JOIN students s ON s.mssv = e.mssv
        LEFT JOIN class_sections cs ON cs.id = e.course_id
        WHERE s.username IS NULL OR cs.id IS NULL
    """)
    orphans = cursor.fetchall()
    for o in orphans:
        warnings.append(f"Enrollment ({o['mssv']}, {o['course_id']}): không liên kết được, giữ trong bảng legacy.")

    conn.commit()
    if warnings:
        detail = "; ".join(warnings)
        log.warning("Enrollment migration warnings: %s", detail)
        _save_warning(cursor, conn, 'migrate_enrollments', detail)


def step_migrate_grades(cursor, conn):
    """Copy legacy grades into grades_v2 via enrollment_id lookup."""
    tbl = _get_legacy_table(cursor, 'grades', '_legacy_grades', 'course_id')
    if not tbl:
        return

    cursor.execute(f"SELECT * FROM `{tbl}`")
    rows = cursor.fetchall()
    warnings = []

    for r in rows:
        cursor.execute(
            "SELECT id FROM enrollments_v2 WHERE mssv=%s AND section_id=%s",
            (r['mssv'], r['course_id']))
        enrollment = cursor.fetchone()
        if not enrollment:
            warnings.append(
                f"Grade ({r['mssv']}, {r['course_id']}): không có đăng ký tương ứng, giữ trong bảng legacy.")
            continue
        eid = enrollment['id']
        cursor.execute("SELECT enrollment_id FROM grades_v2 WHERE enrollment_id=%s", (eid,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO grades_v2 (enrollment_id, midterm, final_score) VALUES (%s, %s, %s)",
                (eid, r.get('midterm'), r.get('final')))

    conn.commit()
    if warnings:
        detail = "; ".join(warnings)
        log.warning("Grade migration warnings: %s", detail)
        _save_warning(cursor, conn, 'migrate_grades', detail)


def step_migrate_payments(cursor, conn):
    """Copy legacy payments into payments_v2 via enrollment_id lookup."""
    tbl = _get_legacy_table(cursor, 'payments', '_legacy_payments', 'course_id')
    if not tbl:
        return

    cursor.execute(f"SELECT * FROM `{tbl}` ORDER BY id")
    rows = cursor.fetchall()
    
    skipped_payments = []  # list of (id, mssv, course_id, amount_dec, reason)
    eligible_rows = []     # list of dicts with mapped enrollment_id and Decimal amount
    
    legacy_total_dec = Decimal('0.00')
    skipped_total_dec = Decimal('0.00')
    eligible_total_dec = Decimal('0.00')
    eligible_ids = set()

    for r in rows:
        old_id = r['id']
        amt_raw = r['amount']
        if amt_raw is None:
            amt_dec = Decimal('0.00')
        else:
            amt_dec = Decimal(str(amt_raw)).quantize(Decimal('0.01'))
        legacy_total_dec += amt_dec

        cursor.execute(
            "SELECT id FROM enrollments_v2 WHERE mssv=%s AND section_id=%s",
            (r['mssv'], r['course_id']))
        enrollment = cursor.fetchone()
        if not enrollment:
            reason = (f"Không tìm thấy lượt đăng ký tương ứng cho sinh viên '{r['mssv']}' "
                      f"và môn '{r['course_id']}'")
            skipped_payments.append((old_id, r['mssv'], r['course_id'], amt_dec, reason))
            skipped_total_dec += amt_dec
            continue

        eid = enrollment['id']
        status = r.get('status', 'Pending') or 'Pending'
        pay_time = r.get('time')

        eligible_rows.append({
            'id': old_id,
            'enrollment_id': eid,
            'amount': amt_dec,
            'status': status,
            'time': pay_time
        })
        eligible_total_dec += amt_dec
        eligible_ids.add(old_id)

    # Reconcile existing records in payments_v2 and insert missing ones
    for item in eligible_rows:
        old_id = item['id']
        cursor.execute("SELECT id, enrollment_id, amount, status, time FROM payments_v2 WHERE id=%s", (old_id,))
        existing = cursor.fetchone()
        if existing:
            ex_amt = Decimal(str(existing['amount'])).quantize(Decimal('0.01'))
            ex_time = existing['time'].replace(microsecond=0) if existing['time'] else None
            item_time = item['time'].replace(microsecond=0) if item['time'] else None
            if (existing['enrollment_id'] != item['enrollment_id'] or
                ex_amt != item['amount'] or
                existing['status'] != item['status'] or
                ex_time != item_time):
                raise RuntimeError(
                    f"Sai lệch nội dung giao dịch id={old_id} trong payments_v2: "
                    f"gốc (enrollment_id={item['enrollment_id']}, amount={item['amount']}, status={item['status']}, time={item_time}) vs "
                    f"v2 hiện tại (enrollment_id={existing['enrollment_id']}, amount={ex_amt}, status={existing['status']}, time={ex_time})"
                )
        else:
            cursor.execute(
                "INSERT INTO payments_v2 (id, enrollment_id, amount, status, time) "
                "VALUES (%s, %s, %s, %s, %s)",
                (old_id, item['enrollment_id'], item['amount'], item['status'], item['time']))

    conn.commit()

    # Fix AUTO_INCREMENT
    cursor.execute("SELECT MAX(id) AS max_id FROM payments_v2")
    max_row = cursor.fetchone()
    if max_row and max_row['max_id'] is not None:
        next_id = max_row['max_id'] + 1
        cursor.execute(f"ALTER TABLE payments_v2 AUTO_INCREMENT = {next_id}")
        conn.commit()

    # ── Reconciliation ──────────────────────────────────────────────────
    cursor.execute("SELECT id, amount FROM payments_v2")
    v2_rows = cursor.fetchall()
    v2_ids = {r['id'] for r in v2_rows}
    v2_total_dec = sum((Decimal(str(r['amount'])).quantize(Decimal('0.01')) for r in v2_rows), Decimal('0.00'))

    if eligible_ids != v2_ids:
        missing_ids = eligible_ids - v2_ids
        extra_ids = v2_ids - eligible_ids
        raise RuntimeError(
            f"Đối soát tập ID giao dịch KHÔNG KHỚP: thiếu {missing_ids}, thừa {extra_ids}."
        )

    if eligible_total_dec != v2_total_dec:
        raise RuntimeError(
            f"Đối soát tổng tiền KHÔNG KHỚP: tổng đủ điều kiện={eligible_total_dec}, "
            f"tổng trong payments_v2={v2_total_dec}."
        )

    warnings = []
    if skipped_payments:
        skipped_lines = [
            f"ID {sp[0]} (MSSV: {sp[1]}, Môn: {sp[2]}, Tiền: {sp[3]} VND): {sp[4]}"
            for sp in skipped_payments
        ]
        warnings.append(
            f"Có {len(skipped_payments)} giao dịch không được chuyển đổi (tổng {skipped_total_dec} VND):\n" +
            "\n".join(skipped_lines)
        )

    recon_msg = (
        f"Bảng gốc: {len(rows)} giao dịch, tổng={legacy_total_dec} VND. "
        f"Chuyển đổi thành công: {len(eligible_rows)} giao dịch, tổng={eligible_total_dec} VND. "
        f"Bỏ qua (không có lượt ĐK): {len(skipped_payments)} giao dịch, tổng={skipped_total_dec} VND. "
        f"Bảng payments_v2 hiện tại: {len(v2_rows)} giao dịch, tổng={v2_total_dec} VND."
    )
    log.info("Payment reconciliation OK: %s", recon_msg)

    detail_content = recon_msg
    if warnings:
        detail_content = "\n".join(warnings) + "\n" + recon_msg
    _save_warning(cursor, conn, 'migrate_payments', detail_content)


def step_rename_legacy_tables(cursor, conn):
    """Rename old tables to _legacy_* and _v2 tables to their final names atomically.
    Uses a single RENAME TABLE statement to prevent interrupted states.
    """
    renames = []
    
    if _table_exists(cursor, 'courses') and not _table_exists(cursor, '_legacy_courses'):
        renames.append("`courses` TO `_legacy_courses`")
        
    table_map = [
        ('enrollments', '_legacy_enrollments', 'enrollments_v2', 'section_id'),
        ('grades', '_legacy_grades', 'grades_v2', 'enrollment_id'),
        ('payments', '_legacy_payments', 'payments_v2', 'enrollment_id'),
    ]
    
    for old, legacy, v2, step2_col in table_map:
        if _table_exists(cursor, old):
            if not _column_exists(cursor, old, step2_col):
                if not _table_exists(cursor, legacy):
                    renames.append(f"`{old}` TO `{legacy}`")
                if _table_exists(cursor, v2):
                    renames.append(f"`{v2}` TO `{old}`")
        else:
            if _table_exists(cursor, v2):
                renames.append(f"`{v2}` TO `{old}`")

    if renames:
        rename_clauses = ", ".join(renames)
        cursor.execute(f"RENAME TABLE {rename_clauses}")
        conn.commit()


def step_rename_v2_tables(cursor, conn):
    """Fallback step in case legacy tables were renamed but v2 were not.
    Uses a single RENAME TABLE statement for atomicity.
    """
    renames = []
    for old, new in [('enrollments_v2', 'enrollments'), ('grades_v2', 'grades'), ('payments_v2', 'payments')]:
        if _table_exists(cursor, old) and not _table_exists(cursor, new):
            renames.append(f"`{old}` TO `{new}`")

    if renames:
        rename_clauses = ", ".join(renames)
        cursor.execute(f"RENAME TABLE {rename_clauses}")
        conn.commit()


def step_update_id_sequences_fk(cursor, conn):
    """Ensure FK references on the new enrollments/grades/payments point correctly."""
    if not _table_exists(cursor, 'id_sequences'):
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS id_sequences "
            "(name VARCHAR(30) PRIMARY KEY, next_value BIGINT NOT NULL) ENGINE=InnoDB")
    conn.commit()


def step_add_student_status(cursor, conn):
    if not _column_exists(cursor, 'students', 'academic_status'):
        cursor.execute(
            "ALTER TABLE students ADD COLUMN academic_status VARCHAR(20) NOT NULL DEFAULT 'Đang học'")
        conn.commit()


def step_create_student_status_history(cursor, conn):
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS student_status_history (
        id INT AUTO_INCREMENT PRIMARY KEY,
        mssv VARCHAR(20) NOT NULL,
        old_status VARCHAR(20) NOT NULL,
        new_status VARCHAR(20) NOT NULL,
        changed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        changed_by VARCHAR(255) NOT NULL,
        reason TEXT NOT NULL,
        FOREIGN KEY (mssv) REFERENCES students(mssv) ON DELETE RESTRICT
    ) ENGINE=InnoDB CHARACTER SET=utf8mb4
    """)
    conn.commit()


def step_change_history_fk_restrict(cursor, conn):
    """Replace only the student FK, in one atomic ALTER; preserve other FKs."""
    if not _table_exists(cursor, 'student_status_history'):
        return
    cursor.execute("""
        SELECT k.CONSTRAINT_NAME, k.REFERENCED_TABLE_NAME,
               k.REFERENCED_COLUMN_NAME, r.DELETE_RULE
        FROM information_schema.KEY_COLUMN_USAGE k
        JOIN information_schema.REFERENTIAL_CONSTRAINTS r
          ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA
         AND r.TABLE_NAME=k.TABLE_NAME AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME
        WHERE k.TABLE_SCHEMA=DATABASE() AND k.TABLE_NAME='student_status_history'
          AND k.COLUMN_NAME='mssv' AND k.REFERENCED_TABLE_NAME IS NOT NULL
    """)
    rows = cursor.fetchall()
    if len(rows) == 1:
        fk = rows[0]
        if (fk['REFERENCED_TABLE_NAME'] == 'students'
                and fk['REFERENCED_COLUMN_NAME'] == 'mssv'
                and fk['DELETE_RULE'] in ('RESTRICT', 'NO ACTION')):
            return
    clauses = []
    for row in rows:
        name = row['CONSTRAINT_NAME'].replace('`', '``')
        clauses.append(f"DROP FOREIGN KEY `{name}`")
    clauses.append("ADD CONSTRAINT fk_status_history_student "
                   "FOREIGN KEY (mssv) REFERENCES students(mssv) ON DELETE RESTRICT")
    cursor.execute("ALTER TABLE student_status_history " + ", ".join(clauses))
    conn.commit()


# ---------------------------------------------------------------------------
# State Resolution & Verification
# ---------------------------------------------------------------------------

def resolve_coexisting_tables(cursor):
    """Inspect target tables and *_v2 tables / legacy tables for conflicts.

    Returns (True, None) if state is safe to proceed.
    Returns (False, reason) if there is an unrecoverable conflict.
    DOES NOT modify the database.
    """
    table_map = [
        ('enrollments', 'enrollments_v2', '_legacy_enrollments', 'section_id', 'course_id'),
        ('grades', 'grades_v2', '_legacy_grades', 'enrollment_id', 'mssv'),
        ('payments', 'payments_v2', '_legacy_payments', 'enrollment_id', 'mssv'),
    ]

    for target, v2, legacy, step2_col, step1_col in table_map:
        target_exists = _table_exists(cursor, target)
        v2_exists = _table_exists(cursor, v2)
        legacy_exists = _table_exists(cursor, legacy)

        if target_exists:
            # Check if target table is step-1 schema
            if _column_exists(cursor, target, step1_col) and not _column_exists(cursor, target, step2_col):
                if legacy_exists:
                    return False, f"Xung đột bảng: Cả '{target}' (schema cũ) và '{legacy}' cùng tồn tại. Vui lòng kiểm tra và khôi phục thủ công."
            elif _column_exists(cursor, target, step2_col):
                if v2_exists:
                    cursor.execute(f"SELECT COUNT(*) AS cnt FROM `{target}`")
                    target_cnt = cursor.fetchone()['cnt']
                    cursor.execute(f"SELECT COUNT(*) AS cnt FROM `{v2}`")
                    v2_cnt = cursor.fetchone()['cnt']
                    return False, f"Xung đột bảng: Cả '{target}' ({target_cnt} dòng) và '{v2}' ({v2_cnt} dòng) cùng tồn tại và đều chứa dữ liệu theo schema mới. Vui lòng kiểm tra thủ công, không tự động xóa hoặc ghi đè."

    return True, None


def verify_migration_schema_and_data(cursor):
    """Verify that final tables exist, have correct columns, FKs, and data integrity.

    Returns (True, "OK message") or (False, "Reason details").
    """
    try:
        if _table_exists(cursor, 'migration_versions'):
            cursor.execute("SELECT step_name FROM migration_versions WHERE status='done'")
            done_steps = {r['step_name'] for r in cursor.fetchall()}
            missing_steps = [s for s in STEP_ORDER if s not in done_steps]
            if missing_steps:
                return False, f"Chưa hoàn tất đủ các bước migration: thiếu {missing_steps}"

        required_tables = [
            'departments', 'programs', 'admission_batches', 'admin_classes',
            'academic_years', 'semesters', 'subjects', 'class_sections',
            'section_schedules', 'enrollments', 'grades', 'payments',
            'student_status_history'
        ]
        for tbl in required_tables:
            if not _table_exists(cursor, tbl):
                return False, f"Bảng chính thức '{tbl}' chưa tồn tại."

        if not _column_exists(cursor, 'enrollments', 'section_id'):
            return False, "Bảng 'enrollments' chưa có cột section_id (chưa nâng cấp Step-2)."
        if not _column_exists(cursor, 'grades', 'enrollment_id'):
            return False, "Bảng 'grades' chưa có cột enrollment_id (chưa nâng cấp Step-2)."
        if not _column_exists(cursor, 'payments', 'enrollment_id'):
            return False, "Bảng 'payments' chưa có cột enrollment_id (chưa nâng cấp Step-2)."
        if not _column_exists(cursor, 'students', 'academic_status'):
            return False, "Bảng 'students' chưa có cột academic_status (chưa nâng cấp Step-3)."
        if not _table_exists(cursor, 'student_status_history'):
            return False, "Bảng 'student_status_history' chưa tồn tại (chưa nâng cấp Step-3)."

        cursor.execute(
            "SELECT DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='payments' AND COLUMN_NAME='amount'")
        row = cursor.fetchone()
        if not row or row['DATA_TYPE'].lower() != 'decimal':
            return False, "Cột 'payments.amount' chưa được nâng cấp sang DECIMAL."

        for tbl, fk_col in [('enrollments', 'section_id'), ('grades', 'enrollment_id'), ('payments', 'enrollment_id')]:
            cursor.execute(
                "SELECT REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s "
                "AND COLUMN_NAME=%s AND REFERENCED_TABLE_NAME IS NOT NULL",
                (tbl, fk_col))
            fk_info = cursor.fetchone()
            if not fk_info:
                return False, f"Thiếu khóa ngoại trên cột '{tbl}.{fk_col}'."
            
            # Verify FK target is correct for step 2
            expected_ref_table = 'class_sections' if tbl == 'enrollments' else 'enrollments'
            expected_ref_column = 'id'
            if fk_info['REFERENCED_TABLE_NAME'] != expected_ref_table:
                return False, f"Khóa ngoại trên '{tbl}.{fk_col}' trỏ sai bảng ({fk_info['REFERENCED_TABLE_NAME']} thay vì {expected_ref_table})."
            if fk_info['REFERENCED_COLUMN_NAME'] != expected_ref_column:
                return False, f"Khóa ngoại trên '{tbl}.{fk_col}' trỏ sai cột ({fk_info['REFERENCED_COLUMN_NAME']} thay vì {expected_ref_column})."

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM enrollments WHERE section_id NOT IN (SELECT id FROM class_sections)")
        if cursor.fetchone()['cnt'] > 0:
            return False, "Bảng 'enrollments' chứa đăng ký mồ côi (lớp học phần không tồn tại)."

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM grades WHERE enrollment_id NOT IN (SELECT id FROM enrollments)")
        if cursor.fetchone()['cnt'] > 0:
            return False, "Bảng 'grades' chứa điểm mồ côi (lượt đăng ký không tồn tại)."

        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM payments WHERE enrollment_id NOT IN (SELECT id FROM enrollments)")
        if cursor.fetchone()['cnt'] > 0:
            return False, "Bảng 'payments' chứa thanh toán mồ côi (lượt đăng ký không tồn tại)."

        return True, "Cấu trúc schema và dữ liệu hợp lệ."
    except Exception as exc:
        return False, f"Lỗi kiểm tra cơ sở dữ liệu: {exc}"


def mark_fresh_install_complete(cursor, conn):
    """Mark all migration steps as completed for a fresh installation."""
    step_create_migration_table(cursor, conn)
    for step in STEP_ORDER:
        _mark_done(cursor, conn, step, "Fresh install bootstrap")


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_STEP_FUNCS = {
    "create_migration_table": step_create_migration_table,
    "create_org_tables": step_create_org_tables,
    "create_academic_tables": step_create_academic_tables,
    "create_subject_table": step_create_subject_table,
    "create_section_tables": step_create_section_tables,
    "create_enrollment_v2": step_create_enrollment_v2,
    "create_grades_v2": step_create_grades_v2,
    "create_payments_v2": step_create_payments_v2,
    "add_student_admin_class": step_add_student_admin_class,
    "migrate_courses_to_subjects": step_migrate_courses_to_subjects,
    "migrate_enrollments": step_migrate_enrollments,
    "migrate_grades": step_migrate_grades,
    "migrate_payments": step_migrate_payments,
    "rename_legacy_tables": step_rename_legacy_tables,
    "rename_v2_tables": step_rename_v2_tables,
    "update_id_sequences_fk": step_update_id_sequences_fk,
    "add_student_status": step_add_student_status,
    "create_student_status_history": step_create_student_status_history,
    "change_history_fk_restrict": step_change_history_fk_restrict,
}


def _detect_state(cursor):
    """Detect the current database migration state."""
    has_migration_table = _table_exists(cursor, 'migration_versions')
    has_courses = _table_exists(cursor, 'courses')
    has_legacy_courses = _table_exists(cursor, '_legacy_courses')
    has_enrollments_v2 = _table_exists(cursor, 'enrollments_v2')
    has_grades_v2 = _table_exists(cursor, 'grades_v2')
    has_payments_v2 = _table_exists(cursor, 'payments_v2')

    if has_courses and _column_exists(cursor, 'courses', 'schedule'):
        return 'step1'

    if has_enrollments_v2 or has_grades_v2 or has_payments_v2:
        return 'in_progress'

    if has_migration_table:
        cursor.execute("SELECT step_name FROM migration_versions WHERE status='done'")
        done_steps = {r['step_name'] for r in cursor.fetchall()}
        if all(step in done_steps for step in STEP_ORDER):
            return 'complete'
        return 'in_progress'

    if has_legacy_courses:
        return 'in_progress'

    if _table_exists(cursor, 'enrollments') and _column_exists(cursor, 'enrollments', 'section_id'):
        return 'v2_ready'

    return 'fresh'


def needs_migration(cursor):
    state = _detect_state(cursor)
    return state in ('step1', 'in_progress')


def migration_complete(cursor):
    state = _detect_state(cursor)
    return state in ('complete', 'v2_ready')


def run_migration(cursor, conn, *, dry_run=False):
    """Execute all pending migration steps in order.
    Acquires a MySQL named lock to prevent concurrent migrations during apply.
    """
    if dry_run:
        ok, reason = resolve_coexisting_tables(cursor)
        if not ok:
            return {"resolve_conflicts": f"error: {reason}"}
        return _run_migration_inner(cursor, conn, dry_run=True)

    cursor.execute("SELECT GET_LOCK('sms_migration_v2', 10) AS acquired")
    res = cursor.fetchone()
    if not res or res['acquired'] != 1:
        raise RuntimeError(
            "Một phiên khác đang thực hiện migration. "
            "Vui lòng đợi hoàn tất hoặc kiểm tra kết nối cũ.")

    try:
        ok, reason = resolve_coexisting_tables(cursor)
        if not ok:
            raise RuntimeError(reason)
            
        results = _run_migration_inner(cursor, conn, dry_run=False)
        ok, reason = verify_migration_schema_and_data(cursor)
        if not ok:
            raise RuntimeError(f"Xác minh sau migration thất bại: {reason}")
        return results
    finally:
        cursor.execute("SELECT RELEASE_LOCK('sms_migration_v2')")
        cursor.fetchone()


def _run_migration_inner(cursor, conn, *, dry_run=False):
    results = {}
    for step_name in STEP_ORDER:
        if _step_done(cursor, step_name):
            results[step_name] = "skipped"
            log.info("Step %s: already done, skipping.", step_name)
            continue
        if dry_run:
            results[step_name] = "would-run"
            log.info("Step %s: would run (dry-run).", step_name)
            continue
        func = _STEP_FUNCS[step_name]
        try:
            log.info("Step %s: running...", step_name)
            func(cursor, conn)
            _mark_done(cursor, conn, step_name)
            results[step_name] = "done"
            log.info("Step %s: done.", step_name)
        except Exception as exc:
            results[step_name] = f"error: {exc}"
            log.error("Step %s FAILED: %s", step_name, exc)
            try:
                cursor.execute(
                    "INSERT INTO migration_versions (step_name, status, applied_at, details) "
                    "VALUES (%s, 'failed', NOW(), %s) "
                    "ON DUPLICATE KEY UPDATE status='failed', "
                    "details=CONCAT(COALESCE(details,''), '\\nFAILED: ', VALUES(details))",
                    (step_name, str(exc)))
                conn.commit()
            except Exception:
                pass
            raise RuntimeError(
                f"Migration thất bại ở bước '{step_name}': {exc}. "
                f"Dữ liệu gốc không bị xóa. Vui lòng kiểm tra và chạy lại."
            ) from exc
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    import mysql.connector
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    from gui.config import get_db_config
    try:
        config = get_db_config()
    except Exception as e:
        print(f"Lỗi cấu hình: {e}")
        return
    dry_run = '--apply' not in sys.argv
    if dry_run:
        print("=== DRY RUN (thêm --apply để thực hiện) ===\n")
    else:
        print("=== APPLYING MIGRATION ===\n")

    conn = mysql.connector.connect(**config)
    cursor = conn.cursor(dictionary=True)
    try:
        state = _detect_state(cursor)
        print(f"Database state: {state}")
        if state in ('complete', 'v2_ready', 'fresh'):
            print("Migration không cần thiết.")
            return
        results = run_migration(cursor, conn, dry_run=dry_run)
        print("\nKết quả:")
        for step, status in results.items():
            print(f"  {step}: {status}")
    finally:
        cursor.close()
        conn.close()


if __name__ == '__main__':
    main()
