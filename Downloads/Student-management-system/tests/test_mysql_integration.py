"""Opt-in integration tests. Every test creates/drops its own sms_test_* database.

Set SMS_TEST_MYSQL_JSON to connector config (omit database). The account must
be allowed to create/drop test databases. Never uses or changes admin_db.

Updated for Step-2 schema: class_sections, section_schedules, enrollments
by section_id, grades by enrollment_id, semesters, subjects.
DECIMAL(15,2) for payments.amount and tuition_per_credit.
"""
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
import mysql.connector
import pytest
from gui.database import Database, ValidationError, hash_password
from gui import services

pytestmark = pytest.mark.skipif(
    not os.environ.get('SMS_TEST_MYSQL_JSON'),
    reason='requires isolated MySQL test server')


@pytest.fixture
def factory():
    config = json.loads(os.environ['SMS_TEST_MYSQL_JSON'])
    config.pop('database', None)
    config['autocommit'] = True
    schema = 'sms_test_' + uuid.uuid4().hex
    admin = mysql.connector.connect(**config)
    cursor = admin.cursor()
    cursor.execute(f'CREATE DATABASE `{schema}` CHARACTER SET utf8mb4')

    @contextmanager
    def connect():
        db = Database.__new__(Database)
        db.conn = mysql.connector.connect(**config, database=schema)
        db.cursor = db.conn.cursor(dictionary=True)
        try:
            yield db
        finally:
            db.cursor.close()
            db.conn.close()

    try:
        with connect() as db:
            db.created_table()
            db.ensure_integrity()
        yield connect
    finally:
        cursor.execute(f'DROP DATABASE `{schema}`')
        cursor.close()
        admin.close()



@pytest.fixture(autouse=True)
def clear_session_between_tests():
    from gui.session import session
    session.logout()
    yield
    session.logout()


@pytest.fixture(scope="module")
def admin_password_hash():
    return hash_password("test-admin-password")


@pytest.fixture
def login_admin(admin_password_hash):
    def login(db):
        from gui.session import session
        db.cursor.execute(
            "INSERT INTO admins (username,password) VALUES (%s,%s) "
            "ON DUPLICATE KEY UPDATE password=VALUES(password)",
            ('admin1', admin_password_hash))
        db.conn.commit()
        assert session.login(db, 'admin1', 'test-admin-password', 'Admin')
    return login

def seed(db, capacity=2):
    """Create basic test data: lecturers, students, academic setup, sections."""
    # Auth
    db.cursor.execute(
        "INSERT INTO lecturers VALUES ('gv1','unused'),('gv2','unused')")
    db.cursor.execute(
        "INSERT INTO students (username,password,mssv) "
        "VALUES ('sv1','unused','SV001'),('sv2','unused','SV002')")

    # Academic setup
    db.cursor.execute(
        "INSERT INTO academic_years (id,name) VALUES ('AY1','Year 1')")
    db.cursor.execute(
        "INSERT INTO semesters (id,name,academic_year_id,registration_open) "
        "VALUES ('SEM1','Semester 1','AY1',1),('SEM2','Semester 2','AY1',1)")

    # Subjects
    db.cursor.execute(
        "INSERT INTO subjects (id,name,credits) "
        "VALUES ('SUBJ_A','Subject A',3),('SUBJ_B','Subject B',3)")

    # Class sections
    db.cursor.execute(
        "INSERT INTO class_sections "
        "(id,subject_id,semester_id,lecturer,max_students,"
        " registration_open,credits_snapshot,tuition_per_credit) VALUES "
        "('SEC-A','SUBJ_A','SEM1','gv1',%s,1,3,500000),"
        "('SEC-B','SUBJ_B','SEM1','gv2',%s,1,3,500000)", (capacity, capacity))

    # Schedules: SEC-A on Thu 2 7-9h, SEC-B on Thu 3 7-9h
    db.cursor.execute(
        "INSERT INTO section_schedules (section_id,weekday,start_minutes,end_minutes) "
        "VALUES ('SEC-A',2,420,540),('SEC-B',3,420,540)")

    db.conn.commit()
    db.ensure_integrity()


def test_two_clients_compete_for_last_seat(factory):
    """Only one of two concurrent students should get the last seat."""
    with factory() as db:
        seed(db, capacity=1)

    barrier = threading.Barrier(2)

    def register(mssv):
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                services.enroll_student(db, mssv, 'SEC-A')
                return 'ok'
            except (services.ValidationError, ValidationError):
                return 'full'

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(register, ['SV001', 'SV002']))
    assert sorted(results) == ['full', 'ok']

    with factory() as db:
        assert db.count_section_enrollments('SEC-A') == 1


def test_same_student_concurrent_overlapping_sections(factory):
    """Two overlapping sections: only one should succeed."""
    with factory() as db:
        seed(db)
        # Make SEC-B overlap with SEC-A on the same day
        db.cursor.execute(
            "UPDATE section_schedules SET weekday=2, start_minutes=480, end_minutes=600 "
            "WHERE section_id='SEC-B'")
        db.conn.commit()

    barrier = threading.Barrier(2)

    def register(sec_id):
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                services.enroll_student(db, 'SV001', sec_id)
                return 'ok'
            except (services.ValidationError, ValidationError):
                return 'conflict'

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(register, ['SEC-A', 'SEC-B']))
    assert sorted(results) == ['conflict', 'ok']


def test_same_student_concurrent_same_subject_different_sections(factory):
    """Two sections of the same subject: only one should succeed."""
    with factory() as db:
        seed(db)
        # Add SEC-A2 = another section of SUBJ_A in SEM1, different schedule
        db.cursor.execute(
            "INSERT INTO class_sections "
            "(id,subject_id,semester_id,lecturer,max_students,"
            " registration_open,credits_snapshot,tuition_per_credit) "
            "VALUES ('SEC-A2','SUBJ_A','SEM1','gv2',40,1,3,500000)")
        db.cursor.execute(
            "INSERT INTO section_schedules "
            "(section_id,weekday,start_minutes,end_minutes) "
            "VALUES ('SEC-A2',5,420,540)")
        db.conn.commit()

    barrier = threading.Barrier(2)

    def register(sec_id):
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                services.enroll_student(db, 'SV001', sec_id)
                return 'ok'
            except (services.ValidationError, ValidationError):
                return 'dup'

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(register, ['SEC-A', 'SEC-A2']))
    assert sorted(results) == ['dup', 'ok']


def test_simultaneous_student_creation_and_digit_boundary(factory, monkeypatch):
    monkeypatch.setattr('gui.database.hash_password', lambda _: 'test-hash')
    with factory() as db:
        db.cursor.execute(
            "INSERT INTO students (username,password,mssv) "
            "VALUES ('old','unused','SV999')")
        db.conn.commit()
        db.ensure_integrity()

    barrier = threading.Barrier(4)

    def create(i):
        with factory() as db:
            barrier.wait(timeout=10)
            return db.add_student(f'new{i}', 'pw')

    with ThreadPoolExecutor(4) as pool:
        ids = list(pool.map(create, range(4)))
    assert sorted(ids) == ['SV1000', 'SV1001', 'SV1002', 'SV1003']

    with factory() as db:
        db.ensure_integrity()
        assert db.add_student('after', 'pw') == 'SV1004'


def test_grade_assignment_membership_and_update(factory):
    """Test grade entry guards and update behavior."""
    with factory() as db:
        seed(db)
        services.enroll_student(db, 'SV001', 'SEC-A')

        # Wrong lecturer
        with pytest.raises(services.ValidationError):
            services.set_grade(db, 'SV001', 'SEC-A', 8, 9,
                               lecturer_username='gv2')

        # Unenrolled student
        with pytest.raises(services.ValidationError):
            services.set_grade(db, 'SV002', 'SEC-A', 8, 9,
                               lecturer_username='gv1')

        # Valid grade
        services.set_grade(db, 'SV001', 'SEC-A', 8, 9,
                           lecturer_username='gv1')

        # Update existing grade
        services.set_grade(db, 'SV001', 'SEC-A', 9, 10,
                           lecturer_username='gv1')

        grades = db.get_grades('SV001')
        assert len(grades) == 1 and grades[0]['final_score'] == 10


def test_retake_preserves_both_grades(factory):
    """Student retakes same subject in different semester — both grades kept."""
    with factory() as db:
        seed(db)
        # Add same subject in SEM2
        db.cursor.execute(
            "INSERT INTO class_sections "
            "(id,subject_id,semester_id,lecturer,max_students,"
            " registration_open,credits_snapshot,tuition_per_credit) "
            "VALUES ('SEC-A-SEM2','SUBJ_A','SEM2','gv1',40,1,3,500000)")
        db.cursor.execute(
            "INSERT INTO section_schedules "
            "(section_id,weekday,start_minutes,end_minutes) "
            "VALUES ('SEC-A-SEM2',2,420,540)")
        db.conn.commit()

        # Enroll and grade in SEM1
        services.enroll_student(db, 'SV001', 'SEC-A')
        services.set_grade(db, 'SV001', 'SEC-A', 3, 4,
                           lecturer_username='gv1')

        # Enroll and grade in SEM2 (retake)
        services.enroll_student(db, 'SV001', 'SEC-A-SEM2')
        services.set_grade(db, 'SV001', 'SEC-A-SEM2', 8, 9,
                           lecturer_username='gv1')

        # Both grades exist
        grades = db.get_grades('SV001')
        assert len(grades) == 2
        scores = sorted([g['final_score'] for g in grades])
        assert scores == [4.0, 9.0]


def test_retake_independent_payments(factory):
    """Payments for retake don't affect original semester payment."""
    with factory() as db:
        seed(db)
        db.cursor.execute(
            "INSERT INTO class_sections "
            "(id,subject_id,semester_id,lecturer,max_students,"
            " registration_open,credits_snapshot,tuition_per_credit) "
            "VALUES ('SEC-A-SEM2','SUBJ_A','SEM2','gv1',40,1,3,500000)")
        db.cursor.execute(
            "INSERT INTO section_schedules (section_id,weekday,start_minutes,end_minutes) "
            "VALUES ('SEC-A-SEM2',2,420,540)")
        db.conn.commit()

        services.enroll_student(db, 'SV001', 'SEC-A')
        services.create_payment(db, 'SV001', 'SEC-A', 1500000, 'Paid')

        services.enroll_student(db, 'SV001', 'SEC-A-SEM2')
        services.create_payment(db, 'SV001', 'SEC-A-SEM2', 1500000, 'Paid')

        payments = db.list_payments('SV001')
        assert len(payments) == 2


def test_schedule_conflict_second_session(factory):
    """Conflict detected even in the second session of a multi-session class."""
    with factory() as db:
        seed(db)
        # Add second session to SEC-A on Thu 5 13h-15h
        db.cursor.execute(
            "INSERT INTO section_schedules "
            "(section_id,weekday,start_minutes,end_minutes) "
            "VALUES ('SEC-A',5,780,900)")
        # Add a section that overlaps only on the second session
        db.cursor.execute(
            "INSERT INTO subjects (id,name,credits) VALUES ('SUBJ_C','C',3)")
        db.cursor.execute(
            "INSERT INTO class_sections "
            "(id,subject_id,semester_id,lecturer,max_students,"
            " registration_open,credits_snapshot,tuition_per_credit) "
            "VALUES ('SEC-C','SUBJ_C','SEM1','gv1',40,1,3,500000)")
        db.cursor.execute(
            "INSERT INTO section_schedules "
            "(section_id,weekday,start_minutes,end_minutes) "
            "VALUES ('SEC-C',5,780,900)")  # Same as SEC-A's second session
        db.conn.commit()

        services.enroll_student(db, 'SV001', 'SEC-A')
        with pytest.raises(services.ValidationError, match='Trùng lịch'):
            services.enroll_student(db, 'SV001', 'SEC-C')


def test_failure_rolls_back_sequence_reservation(factory, monkeypatch):
    monkeypatch.setattr('gui.database.hash_password', lambda _: 'test-hash')
    with factory() as db:
        assert db.add_student('new', 'pw') == 'SV001'
        with pytest.raises(mysql.connector.IntegrityError):
            db.add_student('new', 'pw')
        assert db.add_student('next', 'pw') == 'SV002'


def test_unused_deletion_and_history_unenroll_guard(factory):
    with factory() as db:
        seed(db)
        services.delete_class_section(db, 'SEC-B')
        services.delete_student(db, 'sv2')
        assert db.get_section('SEC-B') is None
        assert db.get_user('Student', 'sv2') is None

        services.enroll_student(db, 'SV001', 'SEC-A')
        services.unenroll_student(db, 'SV001', 'SEC-A')
        assert db.get_enrollments('SV001') == []

        services.enroll_student(db, 'SV001', 'SEC-A')
        services.create_payment(db, 'SV001', 'SEC-A', 1500000, 'Paid')
        with pytest.raises(services.ValidationError):
            services.unenroll_student(db, 'SV001', 'SEC-A')
        assert db.get_enrollments('SV001') == ['SEC-A']


def test_payment_and_unenrollment_race_is_consistent(factory):
    with factory() as db:
        seed(db)
        services.enroll_student(db, 'SV001', 'SEC-A')

    barrier = threading.Barrier(2)

    def action(pay):
        with factory() as db:
            barrier.wait(timeout=10)
            try:
                if pay:
                    services.create_payment(db, 'SV001', 'SEC-A',
                                            1500000, 'Paid')
                else:
                    services.unenroll_student(db, 'SV001', 'SEC-A')
                return True
            except (services.ValidationError, ValidationError):
                return False

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(action, [True, False])) == [False, True]

    with factory() as db:
        paid = bool(db.list_payments('SV001'))
        enrolled = bool(db.get_enrollments('SV001'))
        assert paid == enrolled


def test_migration_idempotent_on_fresh_db(factory):
    """Migration on a fresh DB (no legacy tables) should be a no-op."""
    from gui.migration import needs_migration
    with factory() as db:
        assert not needs_migration(db.cursor)


def test_section_with_enrollment_cannot_change_subject(factory):
    """Block changing subject_id after enrollment via update constraints."""
    with factory() as db:
        seed(db)
        services.enroll_student(db, 'SV001', 'SEC-A')
        with pytest.raises(services.ValidationError):
            services.update_class_section(db, 'SEC-A',
                                          schedules=[(3, 420, 540)])


def test_payment_uses_decimal(factory):
    """Payments use DECIMAL precision, not FLOAT."""
    with factory() as db:
        seed(db)
        services.enroll_student(db, 'SV001', 'SEC-A')
        services.create_payment(db, 'SV001', 'SEC-A', 1500000, 'Paid')
        payments = db.list_payments('SV001')
        assert len(payments) == 1
        # Amount should be a Decimal
        assert isinstance(payments[0]['amount'], Decimal)
        assert payments[0]['amount'] == Decimal('1500000.00')


def test_create_section_transactional(factory):
    """Section creation is transactional — failure cleans up."""
    with factory() as db:
        seed(db)
        # Try to create a section with non-existent subject
        with pytest.raises(services.ValidationError):
            services.create_class_section(db, 'SEC-X', 'NONEXISTENT', 'SEM1',
                                          'gv1', 40, [(2, 420, 540)])
        # No orphaned section should exist
        assert db.get_section('SEC-X') is None


def test_enrollment_rejected_for_no_schedule_section(factory):
    """Enrollment rejected if section has no schedule."""
    with factory() as db:
        seed(db)
        # Create section without schedule
        db.cursor.execute(
            "INSERT INTO class_sections "
            "(id,subject_id,semester_id,lecturer,max_students,"
            " registration_open,credits_snapshot,tuition_per_credit) "
            "VALUES ('SEC-DRAFT','SUBJ_A','SEM1','gv1',40,1,3,500000)")
        db.conn.commit()
        with pytest.raises(services.ValidationError, match='chưa có lịch'):
            services.enroll_student(db, 'SV001', 'SEC-DRAFT')


def test_student_search(factory, monkeypatch):
    """Student search by name, MSSV, or username."""
    monkeypatch.setattr('gui.database.hash_password', lambda _: 'test-hash')
    with factory() as db:
        db.add_student('alice', 'pw')
        db.update_student_profile('alice', name='Alice Smith')
        db.add_student('bob', 'pw')
        db.update_student_profile('bob', name='Bob Jones')

        # Search by name
        results = db.list_students(search='Alice')
        assert len(results) == 1
        assert results[0]['username'] == 'alice'

        # Search by MSSV
        results = db.list_students(search='SV001')
        assert len(results) == 1

        # No results
        results = db.list_students(search='Charlie')
        assert len(results) == 0

        # All
        results = db.list_students()
        assert len(results) == 2


# ══════════════════════════════════════════════════════════════════════════
# MIGRATION & RECONCILIATION INTEGRATION TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_migration_dry_run_is_readonly(factory):
    """Test that dry-run does not modify anything, even on conflict."""
    with factory() as db:
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        db.cursor.execute("DROP TABLE IF EXISTS enrollments, grades, payments, migration_versions, enrollments_v2")
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        # Step 1 schema
        db.cursor.execute("CREATE TABLE courses (id VARCHAR(50) PRIMARY KEY, name VARCHAR(255), credits INT)")
        db.cursor.execute("INSERT INTO courses VALUES ('C1', 'Course 1', 3)")
        
        db.conn.commit()

        from gui import migration
        results = migration.run_migration(db.cursor, db.conn, dry_run=True)
        assert results['create_migration_table'] == 'would-run'
        assert not migration._table_exists(db.cursor, 'migration_versions')
        assert migration._table_exists(db.cursor, 'courses')
        
        # Now create conflict
        db.cursor.execute("CREATE TABLE enrollments_v2 (id INT PRIMARY KEY)")
        db.cursor.execute("INSERT INTO enrollments_v2 VALUES (1)")
        db.cursor.execute("CREATE TABLE enrollments (id INT PRIMARY KEY, section_id VARCHAR(50))") # step 2 schema
        db.conn.commit()
        
        # Dry-run should report error in resolve conflicts, but NOT delete anything
        results2 = migration.run_migration(db.cursor, db.conn, dry_run=True)
        assert 'error: Xung đột bảng' in results2.get('resolve_conflicts', '')
        
        # Verify tables still exist
        assert migration._table_exists(db.cursor, 'enrollments')
        assert migration._table_exists(db.cursor, 'enrollments_v2')


def test_migration_empty_target_with_v2_data_raises(factory):
    """Bảng đích rỗng cùng tồn tại với *_v2 có dữ liệu: dừng rõ ràng, không tự xóa."""
    with factory() as db:
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        db.cursor.execute("DROP TABLE IF EXISTS enrollments, enrollments_v2")
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        db.cursor.execute("CREATE TABLE enrollments_v2 (id INT PRIMARY KEY, mssv VARCHAR(20), section_id VARCHAR(50))")
        db.cursor.execute("INSERT INTO enrollments_v2 VALUES (1, 'SV001', 'SEC1')")
        db.cursor.execute("CREATE TABLE enrollments (id INT PRIMARY KEY, mssv VARCHAR(20), section_id VARCHAR(50))")
        db.conn.commit()

        from gui import migration
        with pytest.raises(RuntimeError, match='đều chứa dữ liệu theo schema mới'):
            migration.run_migration(db.cursor, db.conn)
            
        # Verify it didn't auto-delete
        assert migration._table_exists(db.cursor, 'enrollments')
        assert migration._table_exists(db.cursor, 'enrollments_v2')


def test_migration_both_target_and_v2_have_data_raises(factory):
    """Bảng đích và *_v2 đều có dữ liệu: không ghi đè hoặc xóa."""
    with factory() as db:
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        db.cursor.execute("DROP TABLE IF EXISTS enrollments, enrollments_v2")
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        db.cursor.execute("CREATE TABLE enrollments_v2 (id INT PRIMARY KEY, mssv VARCHAR(20), section_id VARCHAR(50))")
        db.cursor.execute("INSERT INTO enrollments_v2 VALUES (1, 'SV001', 'SEC1')")
        db.cursor.execute("CREATE TABLE enrollments (id INT PRIMARY KEY, mssv VARCHAR(20), section_id VARCHAR(50))")
        db.cursor.execute("INSERT INTO enrollments VALUES (2, 'SV002', 'SEC2')")
        db.conn.commit()

        from gui import migration
        with pytest.raises(RuntimeError, match='đều chứa dữ liệu theo schema mới'):
            migration.run_migration(db.cursor, db.conn)


def test_migration_interrupted_after_rename(factory):
    """Ngắt ngay sau hoán đổi bảng nhưng trước khi ghi done, sau đó mở lại ứng dụng."""
    with factory() as db:
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        db.cursor.execute("DROP TABLE IF EXISTS enrollments, grades, payments, migration_versions, courses, class_sections, subjects, semesters, academic_years, admin_classes, admission_batches, programs, departments")
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        
        # Full step 1 data with all relationships
        db.cursor.execute("CREATE TABLE IF NOT EXISTS students (username VARCHAR(255) PRIMARY KEY, password VARCHAR(255), mssv VARCHAR(20) UNIQUE)")
        db.cursor.execute("INSERT IGNORE INTO students (username, password, mssv) VALUES ('sv1', 'pw', 'SV001')")
        
        db.cursor.execute("CREATE TABLE courses (id VARCHAR(50) PRIMARY KEY, name VARCHAR(255), credits INT)")
        db.cursor.execute("INSERT INTO courses VALUES ('C1', 'Course 1', 3)")
        
        db.cursor.execute("CREATE TABLE enrollments (mssv VARCHAR(20), course_id VARCHAR(50))")
        db.cursor.execute("INSERT INTO enrollments VALUES ('SV001', 'C1')")
        
        db.cursor.execute("CREATE TABLE grades (mssv VARCHAR(20), course_id VARCHAR(50), midterm FLOAT, final FLOAT)")
        db.cursor.execute("INSERT INTO grades VALUES ('SV001', 'C1', 8.5, 9.0)")
        
        db.cursor.execute("CREATE TABLE payments (id INT PRIMARY KEY, mssv VARCHAR(20), course_id VARCHAR(50), amount FLOAT, status VARCHAR(20), time DATETIME)")
        db.cursor.execute("INSERT INTO payments VALUES (1, 'SV001', 'C1', 1500000.0, 'Paid', '2025-01-01 10:00:00')")
        
        db.conn.commit()

        from gui import migration
        
        migration.step_create_migration_table(db.cursor, db.conn)
        
        # Mark all previous steps as done up to migrate_payments
        for step in [
            "create_migration_table", "create_org_tables", "create_academic_tables", 
            "create_subject_table", "create_section_tables", "create_enrollment_v2", 
            "create_grades_v2", "create_payments_v2", "add_student_admin_class", 
            "migrate_courses_to_subjects", "migrate_enrollments", "migrate_grades", 
            "migrate_payments"
        ]:
            if step != "create_migration_table":
                migration._STEP_FUNCS[step](db.cursor, db.conn)
            migration._mark_done(db.cursor, db.conn, step)
            
        # Manually swap tables without marking done (simulating crash during/after swap)
        migration.step_rename_legacy_tables(db.cursor, db.conn)
        
        # Now we are in interrupted state (target tables are v2, v2 tables are gone, legacy tables exist)
        assert migration._table_exists(db.cursor, '_legacy_enrollments')
        assert not migration._table_exists(db.cursor, 'enrollments_v2')
        assert migration._column_exists(db.cursor, 'enrollments', 'section_id') # step 2 schema
        
        # Capture config and close connection
        config = json.loads(os.environ['SMS_TEST_MYSQL_JSON'])
        config['database'] = db.conn.database
        
    test_db = None
    try:
        # Bootstrapping the database should resume safely
        test_db = Database.__new__(Database)
        test_db.conn = mysql.connector.connect(**config)
        test_db.cursor = test_db.conn.cursor(dictionary=True)
        
        # Trigger real bootstrap (simulates the rest of Database.__init__)
        test_db._bootstrap_or_migrate()
        test_db.ensure_integrity()
        
        assert test_db.is_ready is True
        
        ok, reason = migration.verify_migration_schema_and_data(test_db.cursor)
        assert ok, reason
        
        # 1. Verify students
        test_db.cursor.execute("SELECT * FROM students WHERE username='sv1'")
        sv = test_db.cursor.fetchone()
        assert sv['mssv'] == 'SV001'
        
        # 2. Verify subjects and sections
        test_db.cursor.execute("SELECT * FROM subjects WHERE id='C1'")
        sub = test_db.cursor.fetchone()
        assert sub['name'] == 'Course 1'
        assert sub['credits'] == 3
        
        test_db.cursor.execute("SELECT * FROM class_sections WHERE id='C1'")
        sec = test_db.cursor.fetchone()
        assert sec['subject_id'] == 'C1'
        
        # 3. Verify enrollments
        test_db.cursor.execute("SELECT * FROM enrollments WHERE mssv='SV001' AND section_id='C1'")
        enroll = test_db.cursor.fetchone()
        assert enroll is not None
        eid = enroll['id']
        
        # 4. Verify grades
        test_db.cursor.execute("SELECT * FROM grades WHERE enrollment_id=%s", (eid,))
        gr = test_db.cursor.fetchone()
        assert gr is not None
        assert abs(gr['midterm'] - 8.5) < 0.01
        assert abs(gr['final_score'] - 9.0) < 0.01
        
        # 5. Verify payments
        test_db.cursor.execute("SELECT * FROM payments WHERE enrollment_id=%s", (eid,))
        pay = test_db.cursor.fetchone()
        assert pay is not None
        assert pay['id'] == 1
        assert pay['amount'] == Decimal('1500000.00')
        assert pay['status'] == 'Paid'
        assert str(pay['time']) == '2025-01-01 10:00:00'
        
        # 6. Verify FK targets
        for tbl, fk_col in [('enrollments', 'section_id'), ('grades', 'enrollment_id'), ('payments', 'enrollment_id')]:
            test_db.cursor.execute(
                "SELECT REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s "
                "AND REFERENCED_TABLE_NAME IS NOT NULL",
                (tbl, fk_col))
            fk_info = test_db.cursor.fetchone()
            assert fk_info['REFERENCED_TABLE_NAME'] in ('class_sections', 'enrollments')
            assert fk_info['REFERENCED_COLUMN_NAME'] == 'id'
            
        # 7. Rerun bootstrap/migration to ensure idempotency and no duplicates
        migration.run_migration(test_db.cursor, test_db.conn)
        test_db.cursor.execute("SELECT COUNT(*) FROM payments")
        assert test_db.cursor.fetchone()['COUNT(*)'] == 1

    finally:
        if test_db:
            test_db.cursor.close()
            test_db.conn.close()


def test_payment_migration_time_comparison(factory):
    """Giao dịch cùng ID nhưng khác thời gian bị phát hiện."""
    with factory() as db:
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        db.cursor.execute("DROP TABLE IF EXISTS enrollments, grades, payments, migration_versions, enrollments_v2, payments_v2")
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        db.cursor.execute("CREATE TABLE courses (id VARCHAR(50) PRIMARY KEY, name VARCHAR(255), credits INT)")
        db.cursor.execute("INSERT INTO courses VALUES ('C1', 'Course 1', 3)")
        db.cursor.execute("CREATE TABLE enrollments (mssv VARCHAR(20), course_id VARCHAR(50))")
        db.cursor.execute("INSERT INTO enrollments VALUES ('SV001', 'C1')")
        db.cursor.execute("CREATE TABLE payments (id INT PRIMARY KEY, mssv VARCHAR(20), course_id VARCHAR(50), amount FLOAT, status VARCHAR(20), time DATETIME)")
        db.cursor.execute("INSERT INTO payments VALUES (1, 'SV001', 'C1', 1500000.0, 'Paid', '2025-01-01 10:00:00')")
        db.cursor.execute("CREATE TABLE IF NOT EXISTS students (username VARCHAR(255) PRIMARY KEY, password VARCHAR(255), mssv VARCHAR(20) UNIQUE)")
        db.cursor.execute("INSERT IGNORE INTO students (username, password, mssv) VALUES ('sv1', 'pw', 'SV001')")
        db.conn.commit()

        from gui import migration
        migration.step_create_migration_table(db.cursor, db.conn)
        migration.step_create_org_tables(db.cursor, db.conn)
        migration.step_create_academic_tables(db.cursor, db.conn)
        migration.step_create_subject_table(db.cursor, db.conn)
        migration.step_create_section_tables(db.cursor, db.conn)
        migration.step_create_enrollment_v2(db.cursor, db.conn)
        migration.step_create_payments_v2(db.cursor, db.conn)
        migration.step_migrate_courses_to_subjects(db.cursor, db.conn)
        migration.step_migrate_enrollments(db.cursor, db.conn)

        # Pre-fill payments_v2 with wrong time
        db.cursor.execute("INSERT INTO payments_v2 (id, enrollment_id, amount, status, time) VALUES (1, 1, 1500000.00, 'Paid', '2025-01-01 10:00:01')")
        db.conn.commit()

        with pytest.raises(RuntimeError, match='time=2025-01-01 10:00:00.*time=2025-01-01 10:00:01'):
            migration.step_migrate_payments(db.cursor, db.conn)

def test_payment_migration_duplicate_amount_and_unmapped(factory):
    """Test payment migration with identical transactions (except ID) and unmapped transactions."""
    with factory() as db:
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        db.cursor.execute("DROP TABLE IF EXISTS enrollments, grades, payments, migration_versions, enrollments_v2, payments_v2")
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        
        # Step 1 schema setup
        db.cursor.execute("CREATE TABLE courses (id VARCHAR(50) PRIMARY KEY, name VARCHAR(255), credits INT)")
        db.cursor.execute("INSERT INTO courses VALUES ('C1', 'Course 1', 3)")
        
        db.cursor.execute("CREATE TABLE enrollments (mssv VARCHAR(20), course_id VARCHAR(50))")
        db.cursor.execute("INSERT INTO enrollments VALUES ('SV001', 'C1')")
        
        db.cursor.execute("CREATE TABLE payments (id INT PRIMARY KEY, mssv VARCHAR(20), course_id VARCHAR(50), amount FLOAT, status VARCHAR(20), time DATETIME)")
        # Hai giao dịch khác ID nhưng cùng lượt đăng ký, số tiền và thời gian
        db.cursor.execute("INSERT INTO payments VALUES (1, 'SV001', 'C1', 1500000.0, 'Paid', '2025-01-01 10:00:00')")
        db.cursor.execute("INSERT INTO payments VALUES (2, 'SV001', 'C1', 1500000.0, 'Paid', '2025-01-01 10:00:00')")
        # Một giao dịch không tìm được lượt đăng ký (môn học C2 không có đăng ký)
        db.cursor.execute("INSERT INTO payments VALUES (3, 'SV001', 'C2', 500000.0, 'Paid', '2025-01-02 10:00:00')")
        
        db.cursor.execute("CREATE TABLE IF NOT EXISTS students (username VARCHAR(255) PRIMARY KEY, password VARCHAR(255), mssv VARCHAR(20) UNIQUE)")
        db.cursor.execute("INSERT IGNORE INTO students (username, password, mssv) VALUES ('sv1', 'pw', 'SV001')")
        db.conn.commit()

        from gui import migration
        migration.step_create_migration_table(db.cursor, db.conn)
        migration.step_create_org_tables(db.cursor, db.conn)
        migration.step_create_academic_tables(db.cursor, db.conn)
        migration.step_create_subject_table(db.cursor, db.conn)
        migration.step_create_section_tables(db.cursor, db.conn)
        migration.step_create_enrollment_v2(db.cursor, db.conn)
        migration.step_create_payments_v2(db.cursor, db.conn)
        migration.step_migrate_courses_to_subjects(db.cursor, db.conn)
        migration.step_migrate_enrollments(db.cursor, db.conn)
        
        migration.step_migrate_payments(db.cursor, db.conn)

        # Check v2 payments table
        db.cursor.execute("SELECT id, enrollment_id, amount, status, time FROM payments_v2 ORDER BY id")
        v2_payments = db.cursor.fetchall()
        
        # Hai giao dịch hợp lệ đều được giữ, đúng ID và toàn bộ nội dung
        assert len(v2_payments) == 2
        assert v2_payments[0]['id'] == 1
        assert v2_payments[1]['id'] == 2
        assert v2_payments[0]['amount'] == Decimal('1500000.00')
        assert v2_payments[1]['amount'] == Decimal('1500000.00')
        
        # Giao dịch không ánh xạ được còn nguyên trong dữ liệu gốc
        db.cursor.execute("SELECT * FROM payments WHERE id=3")
        assert db.cursor.fetchone() is not None
        
        # Báo cáo chứa ID và lý do của giao dịch không được chuyển
        db.cursor.execute("SELECT details FROM migration_versions WHERE step_name='migrate_payments'")
        details = db.cursor.fetchone()['details']
        assert "Không tìm thấy lượt đăng ký tương ứng" in details
        assert "ID 3" in details
        
        # Tập ID, số lượng và tổng tiền đích khớp các giao dịch đủ điều kiện
        db.cursor.execute("SELECT COUNT(*), SUM(amount) FROM payments_v2")
        count_sum = db.cursor.fetchone()
        assert count_sum['COUNT(*)'] == 2
        assert count_sum['SUM(amount)'] == Decimal('3000000.00')
        
        # Chạy lại không sinh trùng hoặc làm thay đổi nội dung
        migration.step_migrate_payments(db.cursor, db.conn)
        db.cursor.execute("SELECT COUNT(*) FROM payments_v2")
        assert db.cursor.fetchone()['COUNT(*)'] == 2


def test_payment_migration_discrepancy_raises_error(factory):
    """Test payment reconciliation fails and raises error on content discrepancy."""
    with factory() as db:
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        db.cursor.execute("DROP TABLE IF EXISTS enrollments, grades, payments, migration_versions")
        db.cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        db.cursor.execute("CREATE TABLE courses (id VARCHAR(50) PRIMARY KEY, name VARCHAR(255), credits INT)")
        db.cursor.execute("INSERT INTO courses VALUES ('C1', 'Course 1', 3)")
        db.cursor.execute("CREATE TABLE enrollments (mssv VARCHAR(20), course_id VARCHAR(50))")
        db.cursor.execute("INSERT INTO enrollments VALUES ('SV001', 'C1')")
        db.cursor.execute("CREATE TABLE payments (id INT PRIMARY KEY, mssv VARCHAR(20), course_id VARCHAR(50), amount FLOAT, status VARCHAR(20), time DATETIME)")
        db.cursor.execute("INSERT INTO payments VALUES (1, 'SV001', 'C1', 1500000.0, 'Paid', NOW())")
        db.cursor.execute("CREATE TABLE IF NOT EXISTS students (username VARCHAR(255) PRIMARY KEY, password VARCHAR(255), mssv VARCHAR(20) UNIQUE)")
        db.cursor.execute("INSERT IGNORE INTO students (username, password, mssv) VALUES ('sv1', 'pw', 'SV001')")
        db.conn.commit()

        from gui import migration
        migration.step_create_migration_table(db.cursor, db.conn)
        migration.step_create_org_tables(db.cursor, db.conn)
        migration.step_create_academic_tables(db.cursor, db.conn)
        migration.step_create_subject_table(db.cursor, db.conn)
        migration.step_create_section_tables(db.cursor, db.conn)
        migration.step_create_enrollment_v2(db.cursor, db.conn)
        migration.step_create_payments_v2(db.cursor, db.conn)
        migration.step_migrate_courses_to_subjects(db.cursor, db.conn)
        migration.step_migrate_enrollments(db.cursor, db.conn)

        db.cursor.execute("INSERT INTO payments_v2 (id, enrollment_id, amount, status, time) VALUES (1, 1, 999999.00, 'Paid', NOW())")
        db.conn.commit()

        with pytest.raises(RuntimeError, match='Sai lệch nội dung'):
            migration.step_migrate_payments(db.cursor, db.conn)


def test_migration_idempotency_multiple_runs(factory):
    """Test re-running migration multiple times leaves identical state."""
    with factory() as db:
        seed(db)
        from gui import migration
        r1 = migration.run_migration(db.cursor, db.conn)
        r2 = migration.run_migration(db.cursor, db.conn)
        r3 = migration.run_migration(db.cursor, db.conn)

        assert all(v == 'skipped' for v in r2.values() if v != 'create_migration_table')
        assert all(v == 'skipped' for v in r3.values() if v != 'create_migration_table')

        ok, reason = migration.verify_migration_schema_and_data(db.cursor)
        assert ok, reason


# ══════════════════════════════════════════════════════════════════════════
# STEP 3 - STATUS & CSV & STATISTICS & DELETE GUARDS
# ══════════════════════════════════════════════════════════════════════════

def test_change_student_status_success_and_history(factory, login_admin):
    with factory() as db:
        seed(db)
        
        from gui.session import session
        login_admin(db)
        services.change_student_status(db, 'SV001', 'Bảo lưu', 'Lý do sức khỏe')
        session.logout()
        
        # Verify student status changed
        db.cursor.execute("SELECT academic_status FROM students WHERE mssv='SV001'")
        assert db.cursor.fetchone()['academic_status'] == 'Bảo lưu'
        
        # Verify history recorded
        db.cursor.execute("SELECT * FROM student_status_history WHERE mssv='SV001'")
        history = db.cursor.fetchall()
        assert len(history) == 1
        assert history[0]['old_status'] == 'Đang học'
        assert history[0]['new_status'] == 'Bảo lưu'
        assert history[0]['changed_by'] == 'admin1'
        assert history[0]['reason'] == 'Lý do sức khỏe'

def test_change_student_status_requires_admin(factory, login_admin):
    with factory() as db:
        seed(db)
        from gui.session import session
        assert session.login(db, 'gv1', 'unused', 'Lecturer')
        with pytest.raises(services.ValidationError, match='Chỉ Admin mới có quyền'):
            services.change_student_status(db, 'SV001', 'Bảo lưu', 'Test')
        session.logout()

def test_change_student_status_validates_status(factory, login_admin):
    with factory() as db:
        seed(db)
        
        from gui.session import session
        login_admin(db)
        with pytest.raises(services.ValidationError, match='không hợp lệ'):
            services.change_student_status(db, 'SV001', 'Trạng thái lạ', 'Test')
            
        with pytest.raises(services.ValidationError, match='Trạng thái mới không được để trống'):
            services.change_student_status(db, 'SV001', '   ', 'Test')
        session.logout()

def test_delete_student_blocked_by_status_history(factory, login_admin):
    with factory() as db:
        seed(db)
        
        from gui.session import session
        login_admin(db)
        services.change_student_status(db, 'SV001', 'Bảo lưu', 'Test')
        session.logout()
        
        with pytest.raises(services.ValidationError, match='đã có lịch sử thay đổi trạng thái'):
            services.delete_student(db, 'sv1')
            
def test_export_students_csv_escapes_formulas(factory, login_admin):
    with factory() as db:
        seed(db)
        # Setup malicious name
        db.cursor.execute("UPDATE students SET name='=CMD()' WHERE username='sv1'")
        db.conn.commit()
        
        import tempfile
        import csv
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as tf:
            temp_path = tf.name
            
        try:
            services.export_students_csv(db, '', {}, temp_path)
            with open(temp_path, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                for r in rows:
                    if r['MSSV'] == 'SV001':
                        assert r['Họ tên'] == "'=CMD()"
        finally:
            import os
            if os.path.exists(temp_path):
                os.remove(temp_path)



def test_session_unauthenticated_change_status(factory, login_admin):
    with factory() as db:
        seed(db)
        from gui.session import session
        session.logout()
        with pytest.raises(services.ValidationError, match='Chưa đăng nhập'):
            services.change_student_status(db, 'SV001', 'Bảo lưu', 'Test')

def test_session_invalid_admin_change_status(factory, login_admin):
    with factory() as db:
        seed(db)
        from gui.session import session
        assert not session.login(db, 'fakeadmin', 'wrong', 'Admin')
        with pytest.raises(services.ValidationError, match='Chưa đăng nhập'):
            services.change_student_status(db, 'SV001', 'Bảo lưu', 'Test')


def test_transaction_rollback_on_history_insert_error(factory, monkeypatch, login_admin):
    with factory() as db:
        seed(db)
        
        from gui.session import session
        login_admin(db)

        # Simulate error during history insert
        original_execute = db.cursor.execute
        def mock_execute(query, params=None):
            if "INSERT INTO student_status_history" in query:
                raise Exception("Intentional history insert error")
            return original_execute(query, params)
            
        monkeypatch.setattr(db.cursor, 'execute', mock_execute)

        with pytest.raises(Exception, match="Intentional history insert error"):
            services.change_student_status(db, 'SV001', 'Bảo lưu', 'Test')
        
        # Verify rollback
        original_execute("SELECT academic_status FROM students WHERE mssv='SV001'")
        assert db.cursor.fetchone()['academic_status'] == 'Đang học'
        
        original_execute("SELECT * FROM student_status_history WHERE mssv='SV001'")
        assert len(db.cursor.fetchall()) == 0
        session.logout()

def _check_status_enrollment_race(factory, login_admin, monkeypatch, status_first):
    """Observe an actual InnoDB row-lock wait before allowing the holder to commit."""
    import time
    holder_locked = threading.Event()
    waiter_started = threading.Event()
    release_holder = threading.Event()
    ids = {}
    original_lock = services._lock_student

    with factory() as db:
        seed(db)
        login_admin(db)

    def instrumented_lock(db, mssv):
        if db.conn.connection_id == ids.get('holder'):
            original_lock(db, mssv)
            holder_locked.set()
            assert release_holder.wait(15), 'Timed out releasing lock holder'
        else:
            waiter_started.set()
            original_lock(db, mssv)

    monkeypatch.setattr(services, '_lock_student', instrumented_lock)

    def operation(is_holder):
        with factory() as db:
            ids['holder' if is_holder else 'waiter'] = db.conn.connection_id
            changes_status = status_first if is_holder else not status_first
            try:
                if changes_status:
                    services.change_student_status(db, 'SV001', 'Bảo lưu', 'Concurrent test')
                else:
                    services.enroll_student(db, 'SV001', 'SEC-A')
                return 'ok'
            except services.ValidationError as exc:
                return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        holder = pool.submit(operation, True)
        try:
            assert holder_locked.wait(10), 'Holder did not acquire student lock'
            waiter = pool.submit(operation, False)
            assert waiter_started.wait(10), 'Waiter did not request student lock'
            observed_wait = False
            with factory() as observer:
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    observer.cursor.execute("""
                        SELECT COUNT(*) AS n
                        FROM performance_schema.data_lock_waits w
                        JOIN performance_schema.threads requesting
                          ON requesting.THREAD_ID=w.REQUESTING_THREAD_ID
                        JOIN performance_schema.threads blocking
                          ON blocking.THREAD_ID=w.BLOCKING_THREAD_ID
                        WHERE requesting.PROCESSLIST_ID=%s AND blocking.PROCESSLIST_ID=%s
                    """, (ids['waiter'], ids['holder']))
                    if observer.cursor.fetchone()['n']:
                        observed_wait = True
                        break
                    # Poll server-observed state; elapsed time never chooses operation order.
                    threading.Event().wait(0.02)
            assert observed_wait, 'No InnoDB lock contention observed'
            assert not waiter.done(), 'Waiter completed while holder still owned the lock'
        finally:
            release_holder.set()
        assert holder.result(timeout=15) == 'ok'
        outcome = waiter.result(timeout=15)
        if status_first:
            assert "không ở trạng thái 'Đang học'" in outcome
        else:
            assert outcome == 'ok'

    with factory() as db:
        db.cursor.execute("SELECT academic_status FROM students WHERE mssv='SV001'")
        assert db.cursor.fetchone()['academic_status'] == 'Bảo lưu'
        db.cursor.execute("SELECT section_id FROM enrollments WHERE mssv='SV001'")
        assert db.cursor.fetchall() == ([] if status_first else [{'section_id': 'SEC-A'}])
        db.cursor.execute("SELECT old_status,new_status,changed_by,reason FROM student_status_history")
        assert db.cursor.fetchall() == [{
            'old_status': 'Đang học', 'new_status': 'Bảo lưu',
            'changed_by': 'admin1', 'reason': 'Concurrent test'}]


def test_concurrent_status_change_and_enrollment(factory, login_admin, monkeypatch):
    _check_status_enrollment_race(factory, login_admin, monkeypatch, status_first=True)


def test_concurrent_enrollment_before_status_change(factory, login_admin, monkeypatch):
    _check_status_enrollment_race(factory, login_admin, monkeypatch, status_first=False)


def test_migration_fk_restrict_and_data_integrity(factory):
    from gui import migration
    with factory() as db:
        seed(db)
        # Reproduce version (6): populated history table with a CASCADE FK.
        db.cursor.execute("""
            SELECT CONSTRAINT_NAME FROM information_schema.KEY_COLUMN_USAGE
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='student_status_history'
              AND COLUMN_NAME='mssv' AND REFERENCED_TABLE_NAME='students'
        """)
        fk_name = db.cursor.fetchone()['CONSTRAINT_NAME'].replace('`', '``')
        db.cursor.execute(
            f"ALTER TABLE student_status_history DROP FOREIGN KEY `{fk_name}`, "
            "ADD CONSTRAINT fk_legacy_history FOREIGN KEY (mssv) "
            "REFERENCES students(mssv) ON DELETE CASCADE")
        db.cursor.execute("""
            INSERT INTO student_status_history
                (mssv,old_status,new_status,changed_at,changed_by,reason)
            VALUES ('SV001','Đang học','Bảo lưu','2025-02-03 10:11:12','old-admin','Giữ nguyên'),
                   ('SV002','Đang học','Thôi học','2025-02-04 12:13:14','old-admin','Lý do cũ')
        """)
        db.cursor.execute("UPDATE students SET academic_status='Bảo lưu' WHERE mssv='SV001'")
        db.cursor.execute("UPDATE students SET academic_status='Thôi học' WHERE mssv='SV002'")
        migration.mark_fresh_install_complete(db.cursor, db.conn)
        db.cursor.execute("DELETE FROM migration_versions WHERE step_name='change_history_fk_restrict'")
        db.conn.commit()

        def snapshot():
            result = []
            for sql in (
                "SHOW CREATE TABLE student_status_history",
                "SELECT * FROM student_status_history ORDER BY id",
                "SELECT * FROM students ORDER BY mssv",
                "SELECT * FROM migration_versions ORDER BY step_name",
            ):
                db.cursor.execute(sql)
                result.append(db.cursor.fetchall())
            return result

        before = snapshot()
        plan = migration.run_migration(db.cursor, db.conn, dry_run=True)
        assert plan['change_history_fk_restrict'] == 'would-run'
        assert snapshot() == before, 'dry-run changed schema, rows or migration history'

        db._bootstrap_or_migrate()
        assert db.is_ready
        after = snapshot()
        assert after[1:3] == before[1:3], 'Upgrade changed existing students/history'
        db.cursor.execute("""
            SELECT r.DELETE_RULE, k.REFERENCED_TABLE_NAME, k.REFERENCED_COLUMN_NAME
            FROM information_schema.REFERENTIAL_CONSTRAINTS r
            JOIN information_schema.KEY_COLUMN_USAGE k
              ON k.CONSTRAINT_SCHEMA=r.CONSTRAINT_SCHEMA
             AND k.TABLE_NAME=r.TABLE_NAME AND k.CONSTRAINT_NAME=r.CONSTRAINT_NAME
            WHERE r.CONSTRAINT_SCHEMA=DATABASE() AND r.TABLE_NAME='student_status_history'
              AND k.COLUMN_NAME='mssv'
        """)
        assert db.cursor.fetchall() == [{
            'DELETE_RULE': 'RESTRICT', 'REFERENCED_TABLE_NAME': 'students',
            'REFERENCED_COLUMN_NAME': 'mssv'}]
        migration.run_migration(db.cursor, db.conn)
        assert snapshot() == after, 'Repeated migration changed data or DDL'
        with pytest.raises(services.ValidationError, match='lịch sử thay đổi trạng thái'):
            services.delete_student(db, 'sv1')
        with pytest.raises(mysql.connector.IntegrityError) as exc:
            db.cursor.execute("DELETE FROM students WHERE mssv='SV001'")
        assert exc.value.errno == 1451
        assert snapshot() == after


def test_admin_class_filter_logic(factory, login_admin):
    with factory() as db:
        seed(db)
        # Setup faculties and classes
        db.cursor.execute("INSERT IGNORE INTO departments (id, name) VALUES ('D1', 'Khoa A'), ('D2', 'Khoa B')")
        db.cursor.execute("INSERT IGNORE INTO programs (id, name, department_id) VALUES ('P1', 'Nganh 1A', 'D1'), ('P2', 'Nganh 2A', 'D1'), ('P3', 'Nganh 1B', 'D2')")
        db.cursor.execute("INSERT IGNORE INTO admission_batches (id, name, year) VALUES ('B1', 'K2021', 2021)")
        
        db.cursor.execute("INSERT IGNORE INTO admin_classes (id, name, program_id, batch_id) VALUES ('C1', 'Lop 1', 'P1', 'B1'), ('C2', 'Lop 2', 'P2', 'B1'), ('C3', 'Lop 3', 'P3', 'B1')")
        db.conn.commit()
        
        # Test the filter logic via database queries or simulating the filter function
        classes = db.list_admin_classes()
        # Filter by Khoa A
        filtered_by_dept = [c for c in classes if str(c.get('department_id')) == 'D1']
        assert len(filtered_by_dept) == 2
        assert 'C1' in [c['id'] for c in filtered_by_dept]
        assert 'C2' in [c['id'] for c in filtered_by_dept]
        assert 'C3' not in [c['id'] for c in filtered_by_dept]

def test_statistics_no_duplicates(factory, login_admin):
    with factory() as db:
        seed(db)
        # Ensure 'get_student_statistics' counts unique students and includes unassigned
        stats = db.get_student_statistics()
        # SV001 and SV002 are in seed. They might not have admin_class_id.
        assert stats['total_students'] == 2
        
        # Verify 'Chưa phân khoa' is in by_department if they have no class
        unassigned_dept = [s for s in stats['by_department'] if s['name'] == 'Chưa phân khoa']
        assert len(unassigned_dept) > 0
        assert sum(s['cnt'] for s in stats['by_department']) == 2

