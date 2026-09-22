"""Headless regressions; no application database is opened by these tests.

Updated for Step-2 schema: class_sections, section_schedules, enrollment by
section_id, grades by enrollment_id.  Includes tests for transactional
create_class_section, schedule validation, payment amount verification, and
draft section behavior.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest
from gui.database import Database, ValidationError
from gui.scheduling import (parse_schedule, parse_multi_schedule,
                            schedule_conflicts, format_schedule_list,
                            sessions_overlap)
from gui import services, interface


def database(one=(), many=()):
    """Create a mock Database with pre-programmed cursor responses."""
    db = Database.__new__(Database)
    db.conn = MagicMock()
    db.cursor = MagicMock()
    db.cursor.fetchone.side_effect = list(one)
    db.cursor.fetchall.side_effect = list(many)
    return db


def sql(db):
    return '\n'.join(c.args[0] for c in db.cursor.execute.call_args_list)


# ══════════════════════════════════════════════════════════════════════════
# SCHEDULING TESTS
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('text,expected', [
    ('Thu 2 7h-9h', (2, 420, 540)), ('Thu 2 7-9h', (2, 420, 540)),
    ('Thứ 3 7h30-9h30', (3, 450, 570)), ('CN 8h-10h', (8, 480, 600)),
    ('Mon 7-9AM', (2, 420, 540)), ('Tue 13:00-15:00', (3, 780, 900)),
    ('Sun 12-1AM', (8, 0, 60)), ('Mon 1-3PM', (2, 780, 900)),
    ('Thu 9 25h-26h', None), ('Thu 2 7h-9h; Thu 4 7h-9h', None),
    ('Thu 2 10h-9h', None), ('Thu 2 7h60-9h', None), ('', None),
])
def test_schedule(text, expected):
    assert parse_schedule(text) == expected


def test_multi_schedule_valid():
    result = parse_multi_schedule("Thu 2 7h-9h; Thu 4 13h-15h")
    assert result == [(2, 420, 540), (4, 780, 900)]


def test_multi_schedule_single():
    result = parse_multi_schedule("Thu 2 7h-9h")
    assert result == [(2, 420, 540)]


def test_multi_schedule_invalid_part():
    assert parse_multi_schedule("Thu 2 7h-9h; bad") is None


def test_multi_schedule_empty():
    assert parse_multi_schedule("") is None
    assert parse_multi_schedule(None) is None


def test_schedule_conflicts_overlap():
    a = [(2, 420, 540)]  # Thu 2 7h-9h
    b = [(2, 480, 600)]  # Thu 2 8h-10h — overlaps
    assert schedule_conflicts(a, b) is not None


def test_schedule_conflicts_adjacent():
    a = [(2, 420, 540)]  # Thu 2 7h-9h
    b = [(2, 540, 660)]  # Thu 2 9h-11h — adjacent, no overlap
    assert schedule_conflicts(a, b) is None


def test_schedule_conflicts_different_day():
    a = [(2, 420, 540)]
    b = [(3, 420, 540)]
    assert schedule_conflicts(a, b) is None


def test_schedule_conflicts_second_session():
    """Conflict should be detected even in the second session."""
    a = [(2, 420, 540), (4, 780, 900)]  # Thu 2 7-9, Thu 4 13-15
    b = [(3, 420, 540), (4, 780, 900)]  # Thu 3 7-9, Thu 4 13-15 — overlaps on Thu 4
    assert schedule_conflicts(a, b) is not None


def test_format_schedule_list():
    result = format_schedule_list([(2, 420, 540), (5, 780, 900)])
    assert "Thứ 2" in result
    assert "Thứ 5" in result


def test_sessions_overlap_same_day():
    assert sessions_overlap((2, 420, 540), (2, 480, 600))


def test_sessions_overlap_different_day():
    assert not sessions_overlap((2, 420, 540), (3, 420, 540))


# ══════════════════════════════════════════════════════════════════════════
# GRADE ENTRY UI TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_changed_dropdown_cannot_write_grade(monkeypatch):
    """If the section combobox changes after loading, block grade entry."""
    monkeypatch.setattr(interface, 'db', MagicMock())
    monkeypatch.setattr(interface, 'messagebox', MagicMock())
    obj = interface.LecturerDashboard.__new__(interface.LecturerDashboard)
    obj.grade_tree = MagicMock()
    obj.grade_tree.selection.return_value = ['row-A']
    obj.loaded_section_id = 'SECTION_A'
    obj.section_var = SimpleNamespace(get=lambda: 'SECTION_B - Môn B')
    obj.username = 'gv1'
    obj.enter_grade(None)
    interface.messagebox.showerror.assert_called_once()


def test_dropdown_clears_previous_roster():
    obj = interface.LecturerDashboard.__new__(interface.LecturerDashboard)
    obj.grade_tree = MagicMock()
    obj.grade_tree.get_children.return_value = ['a', 'b']
    obj.loaded_section_id = 'A'
    obj._section_changed()
    assert obj.loaded_section_id is None
    assert obj.grade_tree.delete.call_count == 2


def test_grade_uses_loaded_section_and_lecturer(monkeypatch):
    mock_services = MagicMock()
    monkeypatch.setattr(interface, 'db', MagicMock())
    monkeypatch.setattr(interface, 'messagebox', MagicMock())
    monkeypatch.setattr(interface, 'services', mock_services)
    dialog = MagicMock()
    dialog.askfloat.side_effect = [8.0, 9.0]
    monkeypatch.setattr(interface, 'simpledialog', dialog)

    obj = interface.LecturerDashboard.__new__(interface.LecturerDashboard)
    obj.grade_tree = MagicMock()
    obj.grade_tree.selection.return_value = ['row']
    obj.grade_tree.item.return_value = {'values': ['SV001', 'Name', '', '']}
    obj.loaded_section_id = 'SEC-A'
    obj.username = 'gv1'
    obj.section_var = SimpleNamespace(get=lambda: 'SEC-A - Môn A')
    obj.load_students = MagicMock()
    obj.enter_grade(None)
    mock_services.set_grade.assert_called_once_with(
        interface.db, 'SV001', 'SEC-A', 8.0, 9.0, lecturer_username='gv1')


# ══════════════════════════════════════════════════════════════════════════
# SERVICES LAYER TESTS (mock DB)
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('value', [-1, 11, float('nan'), float('inf'), '8'])
def test_invalid_grade_does_not_start_transaction(value):
    db = database()
    with pytest.raises(services.ValidationError):
        services.set_grade(db, 'SV001', 'SEC-A', value, 9,
                           lecturer_username='gv1')
    db.conn.start_transaction.assert_not_called()


def test_grade_requires_lecturer_assignment():
    """Grade rejected if lecturer doesn't match section."""
    db = database(
        [{'username': 'sv'}, {'id': 'SEC-A', 'lecturer': 'other', 'subject_id': 'S1',
          'semester_id': 'HK1', 'max_students': 40, 'registration_open': 1,
          'credits_snapshot': 3, 'tuition_per_credit': 500000}]
    )
    with pytest.raises(services.ValidationError, match='phân công'):
        services.set_grade(db, 'SV001', 'SEC-A', 8, 9, lecturer_username='gv1')
    db.conn.commit.assert_not_called()
    db.conn.rollback.assert_called_once()


def test_grade_requires_enrollment():
    """Grade rejected if student not enrolled."""
    db = database(
        [{'username': 'sv'},
         {'id': 'SEC-A', 'lecturer': 'gv1', 'subject_id': 'S1',
          'semester_id': 'HK1', 'max_students': 40, 'registration_open': 1,
          'credits_snapshot': 3, 'tuition_per_credit': 500000},
         None]  # no enrollment found
    )
    with pytest.raises(services.ValidationError, match='chưa đăng ký'):
        services.set_grade(db, 'SV001', 'SEC-A', 8, 9, lecturer_username='gv1')
    db.conn.commit.assert_not_called()


def test_grade_saves_with_on_duplicate_key():
    db = database(
        [{'username': 'sv'},
         {'id': 'SEC-A', 'lecturer': 'gv1', 'subject_id': 'S1',
          'semester_id': 'HK1', 'max_students': 40, 'registration_open': 1,
          'credits_snapshot': 3, 'tuition_per_credit': 500000},
         {'id': 42}]  # enrollment found
    )
    services.set_grade(db, 'SV001', 'SEC-A', 8, 9, lecturer_username='gv1')
    assert 'ON DUPLICATE KEY UPDATE' in sql(db)
    db.conn.commit.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════
# ENROLLMENT TESTS (mock DB)
# ══════════════════════════════════════════════════════════════════════════

def section(max_students=1, registration_open=1, subject_id='S1', semester_id='HK1'):
    return {'id': 'SEC-A', 'max_students': max_students,
            'registration_open': registration_open,
            'subject_id': subject_id, 'semester_id': semester_id,
            'lecturer': 'gv1', 'credits_snapshot': 3,
            'tuition_per_credit': 500000}


def test_enrollment_closed_section():
    db = database(
        [{'username': 'sv'}, {'academic_status': 'Đang học'}, section(registration_open=0)]
    )
    with pytest.raises(services.ValidationError, match='đóng đăng ký'):
        services.enroll_student(db, 'SV001', 'SEC-A')


def test_enrollment_closed_semester():
    db = database(
        [{'username': 'sv'}, {'academic_status': 'Đang học'}, section(), {'registration_open': 0}]
    )
    with pytest.raises(services.ValidationError, match='chưa mở'):
        services.enroll_student(db, 'SV001', 'SEC-A')


def test_enrollment_duplicate_section():
    db = database(
        [{'username': 'sv'}, {'academic_status': 'Đang học'}, section(), {'registration_open': 1}, {'id': 1}]
    )
    with pytest.raises(services.ValidationError, match='đã đăng ký'):
        services.enroll_student(db, 'SV001', 'SEC-A')


def test_enrollment_same_subject_same_semester():
    """Block enrolling in 2 sections of same subject in same semester."""
    db = database(
        [{'username': 'sv'}, {'academic_status': 'Đang học'}, section(), {'registration_open': 1},
         None,  # not enrolled in this section
         {'id': 'SEC-B'}],  # but enrolled in another section of same subject
    )
    with pytest.raises(services.ValidationError, match='nhóm khác'):
        services.enroll_student(db, 'SV001', 'SEC-A')


def test_enrollment_full_capacity():
    db = database(
        [{'username': 'sv'}, {'academic_status': 'Đang học'}, section(max_students=1), {'registration_open': 1},
         None, None, {'cnt': 1}],  # cnt == max
    )
    with pytest.raises(services.ValidationError, match='sĩ số'):
        services.enroll_student(db, 'SV001', 'SEC-A')


def test_enrollment_no_schedule_rejects():
    """Block enrollment if section has no schedule sessions."""
    db = database(
        [{'username': 'sv'}, {'academic_status': 'Đang học'}, section(max_students=10), {'registration_open': 1},
         None, None, {'cnt': 0}],
    )
    db.cursor.fetchall.side_effect = [[]]  # no schedules
    with pytest.raises(services.ValidationError, match='chưa có lịch'):
        services.enroll_student(db, 'SV001', 'SEC-A')


# ══════════════════════════════════════════════════════════════════════════
# DELETE GUARDS
# ══════════════════════════════════════════════════════════════════════════

def test_delete_student_with_enrollment():
    db = database([{'mssv': 'SV001'}, {'1': 1}])
    with pytest.raises(services.ValidationError, match='đã có đăng ký'):
        services.delete_student(db, 'sv')
    assert 'DELETE FROM students' not in sql(db)


def test_delete_student_without_history():
    db = database([{'mssv': 'SV001'}, None, None])
    services.delete_student(db, 'sv')
    assert 'DELETE FROM students' in sql(db)
    db.conn.commit.assert_called_once()


def test_delete_section_with_enrollment():
    db = database(
        [{'id': 'SEC-A', 'max_students': 40, 'registration_open': 1,
          'subject_id': 'S1', 'semester_id': 'HK1', 'lecturer': 'gv1',
          'credits_snapshot': 3, 'tuition_per_credit': 500000},
         {'cnt': 1}]
    )
    with pytest.raises(services.ValidationError, match='đã có đăng ký'):
        services.delete_class_section(db, 'SEC-A')


def test_delete_subject_with_sections():
    db = database([{'id': 'S1'}, {'id': 'SEC-A'}])
    with pytest.raises(services.ValidationError, match='lớp học phần'):
        services.delete_subject(db, 'S1')


def test_delete_subject_no_sections():
    db = database([{'id': 'S1'}, None])
    services.delete_subject(db, 'S1')
    assert 'DELETE FROM subjects' in sql(db)


# ══════════════════════════════════════════════════════════════════════════
# MSSV SEQUENCE TESTS
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('number', [999, 1000, 1001, 10000])
def test_mssv_crosses_digit_boundary(number, monkeypatch):
    monkeypatch.setattr('gui.database.hash_password', lambda _: 'test-hash')
    db = database([{'next_value': number}])
    assert db.add_student('new', 'pw') == f'SV{number:03d}'
    assert 'FOR UPDATE' in sql(db)
    db.conn.commit.assert_called_once()


def test_failed_student_insert_rolls_back_counter(monkeypatch):
    monkeypatch.setattr('gui.database.hash_password', lambda _: 'test-hash')
    db = database([{'next_value': 1000}])

    def execute(statement, args=()):
        if statement.startswith('INSERT INTO students'):
            raise RuntimeError('duplicate username')
    db.cursor.execute.side_effect = execute
    with pytest.raises(RuntimeError):
        db.add_student('existing', 'pw')
    db.conn.commit.assert_not_called()
    db.conn.rollback.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════
# PAYMENT TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_payment_requires_enrollment():
    db = database(
        [{'username': 'sv'},
         section(),
         None]  # no enrollment
    )
    with pytest.raises(services.ValidationError, match='chưa đăng ký'):
        services.create_payment(db, 'SV001', 'SEC-A', 500000, 'Paid')


def test_payment_amount_mismatch():
    """Payment is rejected if amount doesn't match credits * tuition_per_credit."""
    db = database(
        [{'username': 'sv'},
         section(),  # credits_snapshot=3, tuition_per_credit=500000 → 1,500,000
         {'id': 42},  # enrollment found
         None]  # no existing paid
    )
    with pytest.raises(services.ValidationError, match='không khớp'):
        services.create_payment(db, 'SV001', 'SEC-A', 999999, 'Paid')


def test_payment_correct_amount():
    """Payment succeeds when amount matches expected tuition."""
    db = database(
        [{'username': 'sv'},
         section(),  # 3 credits × 500000 = 1,500,000
         {'id': 42},
         None]
    )
    pid = services.create_payment(db, 'SV001', 'SEC-A', 1500000, 'Paid')
    db.conn.commit.assert_called_once()


def test_payment_auto_calculates_when_amount_none():
    """Payment auto-calculates when amount is None."""
    db = database(
        [{'username': 'sv'},
         section(),  # 3 credits × 500000 = 1,500,000
         {'id': 42},
         None]
    )
    services.create_payment(db, 'SV001', 'SEC-A', status='Paid')
    db.conn.commit.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════
# ADMIN CLASS ASSIGNMENT TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_assign_nonexistent_admin_class():
    db = database([None])
    with pytest.raises(services.ValidationError, match='không tồn tại'):
        services.assign_admin_class(db, 'sv001', 'FAKE-CLASS')


def test_assign_valid_admin_class():
    db = database([{'id': 'CLS1', 'program_id': 'P1', 'batch_id': 'B1'}])
    services.assign_admin_class(db, 'sv001', 'CLS1')
    assert 'UPDATE students' in sql(db)


# ══════════════════════════════════════════════════════════════════════════
# UNENROLL TESTS
# ══════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize('age', [604801, None, -1])
def test_unenroll_exact_deadline(age):
    db = database(
        [{'username': 'sv'}, section(),
         {'id': 1, 'enrolled_at': None, 'age_seconds': age}]
    )
    with pytest.raises(services.ValidationError):
        services.unenroll_student(db, 'SV001', 'SEC-A')
    assert 'DELETE FROM enrollments' not in sql(db)


def test_unenroll_preserves_grade_history():
    db = database(
        [{'username': 'sv'}, section(),
         {'id': 1, 'enrolled_at': None, 'age_seconds': 10},
         {'enrollment_id': 1}]  # has grade
    )
    with pytest.raises(services.ValidationError, match='đã có điểm'):
        services.unenroll_student(db, 'SV001', 'SEC-A')


def test_unenroll_preserves_payment_history():
    db = database(
        [{'username': 'sv'}, section(),
         {'id': 1, 'enrolled_at': None, 'age_seconds': 10},
         None,  # no grade
         {'id': 99}]  # has payment
    )
    with pytest.raises(services.ValidationError, match='giao dịch'):
        services.unenroll_student(db, 'SV001', 'SEC-A')


# ══════════════════════════════════════════════════════════════════════════
# SECTION MANAGEMENT TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_update_section_blocks_lecturer_change_with_enrollments():
    db = database(
        [section(), {'cnt': 1}]
    )
    with pytest.raises(services.ValidationError, match='đổi giảng viên'):
        services.update_class_section(db, 'SEC-A', lecturer='gv2')


def test_update_section_blocks_schedule_change_with_enrollments():
    db = database(
        [section(), {'cnt': 1}]
    )
    with pytest.raises(services.ValidationError, match='đổi lịch'):
        services.update_class_section(db, 'SEC-A', schedules=[(2, 540, 660)])


def test_update_section_blocks_max_below_enrolled():
    db = database(
        [section(max_students=40), {'cnt': 30}, {'cnt': 30}]
    )
    with pytest.raises(services.ValidationError, match='nhỏ hơn'):
        services.update_class_section(db, 'SEC-A', max_students=20)


# ══════════════════════════════════════════════════════════════════════════
# CREATE CLASS SECTION TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_create_section_validates_max_students():
    db = database()
    with pytest.raises(services.ValidationError, match='số dương'):
        services.create_class_section(db, 'SEC-A', 'S1', 'HK1', 'gv1',
                                       0, [(2, 420, 540)])


def test_create_section_validates_schedule_weekday():
    db = database()
    with pytest.raises(services.ValidationError, match='không hợp lệ'):
        services.create_class_section(db, 'SEC-A', 'S1', 'HK1', 'gv1',
                                       40, [(1, 420, 540)])  # weekday 1 invalid


def test_create_section_validates_schedule_self_overlap():
    db = database()
    with pytest.raises(services.ValidationError, match='chồng lấn'):
        services.create_class_section(db, 'SEC-A', 'S1', 'HK1', 'gv1',
                                       40, [(2, 420, 540), (2, 480, 600)])


def test_create_section_draft_no_schedule():
    """Section without schedule is created as draft (registration_open=0)."""
    db = database(
        [{'credits': 3}, {'id': 'HK1'}, {'username': 'gv1'}]
    )
    services.create_class_section(db, 'SEC-A', 'S1', 'HK1', 'gv1', 40, [])
    s = sql(db)
    assert 'INSERT INTO class_sections' in s
    # No INSERT INTO section_schedules since schedules is empty
    assert 'INSERT INTO section_schedules' not in s


def test_create_section_validates_tuition_negative():
    db = database()
    with pytest.raises(services.ValidationError, match='>= 0'):
        services.create_class_section(db, 'SEC-A', 'S1', 'HK1', 'gv1',
                                       40, [(2, 420, 540)],
                                       tuition_per_credit=-100)


# ══════════════════════════════════════════════════════════════════════════
# DELETE GUARDS FOR CATALOG ENTITIES
# ══════════════════════════════════════════════════════════════════════════

def test_delete_department_with_programs():
    db = database([{'id': 'D1'}, {'id': 'P1'}])
    with pytest.raises(services.ValidationError, match='ngành'):
        services.delete_department(db, 'D1')


def test_delete_program_with_classes():
    db = database([{'id': 'P1'}, {'id': 'C1'}])
    with pytest.raises(services.ValidationError, match='lớp hành chính'):
        services.delete_program(db, 'P1')


def test_delete_admin_class_with_students():
    db = database([{'id': 'C1'}, {'admin_class_id': 'C1'}])
    with pytest.raises(services.ValidationError, match='sinh viên'):
        services.delete_admin_class(db, 'C1')


# ══════════════════════════════════════════════════════════════════════════
# SEMESTER DISPLAY & CATALOG VALIDATION TESTS
# ══════════════════════════════════════════════════════════════════════════

def test_sem_display_formatting():
    """Verify _sem_display formats semester_name / year_name correctly and never displays transaction IDs."""
    # Semester dict from list_semesters
    s1 = {'id': 'SEM1', 'name': 'HK1', 'year_name': '2025-2026'}
    assert interface._sem_display(s1) == "HK1 (2025-2026)"

    # Business record (grade/payment row) with semester_name & year_name
    g1 = {'id': 42, 'enrollment_id': 10, 'semester_name': 'HK2', 'year_name': '2025-2026'}
    assert interface._sem_display(g1) == "HK2 (2025-2026)"

    # Payment row with id=99, semester_name missing, but academic_year_name present
    p1 = {'id': 99, 'academic_year_name': '2024-2025'}
    assert interface._sem_display(p1) == "2024-2025"

    # None or empty
    assert interface._sem_display({}) == ""
    assert interface._sem_display(None) == ""


def test_catalog_update_validations():
    """Verify catalog update methods raise ValidationError on invalid data or relationships."""
    db = Database.__new__(Database)
    db.cursor = MagicMock()
    db.conn = MagicMock()

    # Academic year validation: start_year > end_year
    db.get_academic_year = MagicMock(return_value={'id': 'AY1', 'start_year': 2025, 'end_year': 2026})
    with pytest.raises(ValidationError, match='bắt đầu'):
        db.update_academic_year('AY1', start_year=2027, end_year=2026)

    # Semester validation: start_date > end_date
    db.get_semester = MagicMock(return_value={'id': 'SEM1', 'name': 'HK1', 'academic_year_id': 'AY1'})
    with pytest.raises(ValidationError, match='bắt đầu'):
        db.update_semester('SEM1', start_date='2025-09-01', end_date='2025-05-01')

    # Program validation: invalid department
    db.get_program = MagicMock(return_value={'id': 'P1', 'name': 'CNTT'})
    db.get_department = MagicMock(return_value=None)
    with pytest.raises(ValidationError, match='Khoa'):
        db.update_program('P1', department_id='INVALID_DEPT')

    # Batch validation: invalid year
    db.get_admission_batch = MagicMock(return_value={'id': 'K20'})
    with pytest.raises(ValidationError, match='Năm tuyển sinh'):
        db.update_admission_batch('K20', year=1800)

    # Admin class validation: invalid program
    db.get_program = MagicMock(return_value=None)
    with pytest.raises(ValidationError, match='Ngành'):
        db.update_admin_class('C1', program_id='INVALID_PROG')

def test_verify_migration_schema_detects_wrong_fk_column():
    """Verify that verify_migration_schema_and_data detects FK pointing to the wrong column."""
    from gui.migration import verify_migration_schema_and_data
    cursor = MagicMock()
    def execute_side_effect(q, p=None):
        q_upper = q.upper()
        if "MIGRATION_VERSIONS" in q_upper and "INFORMATION_SCHEMA.TABLES" in q_upper:
            cursor._mock_result = {'n': 1}
        elif "STEP_NAME FROM MIGRATION_VERSIONS" in q_upper:
            from gui.migration import STEP_ORDER
            cursor._mock_all = [{'step_name': s} for s in STEP_ORDER]
        elif "INFORMATION_SCHEMA.TABLES" in q_upper:
            cursor._mock_result = {'n': 1}
        elif "SHOW COLUMNS" in q_upper:
            cursor._mock_result = {'Field': 'some_col'}
        elif "DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS" in q_upper:
            cursor._mock_result = {'DATA_TYPE': 'decimal'}
        elif "REFERENCED_TABLE_NAME" in q_upper:
            if p and 'enrollments' in p:
                cursor._mock_result = {'REFERENCED_TABLE_NAME': 'class_sections', 'REFERENCED_COLUMN_NAME': 'wrong_column'}
            else:
                cursor._mock_result = {'REFERENCED_TABLE_NAME': 'class_sections', 'REFERENCED_COLUMN_NAME': 'id'}
        else:
            cursor._mock_result = {'cnt': 0}
            
    cursor.execute.side_effect = execute_side_effect
    cursor.fetchone.side_effect = lambda: cursor._mock_result
    cursor.fetchall.side_effect = lambda: getattr(cursor, '_mock_all', [])
    
    ok, reason = verify_migration_schema_and_data(cursor)
    assert not ok
    assert "trỏ sai cột (wrong_column thay vì id)" in reason


