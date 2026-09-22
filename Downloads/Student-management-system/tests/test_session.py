"""Session lifecycle and UI logout tests; no display or MySQL server needed."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import bcrypt
import pytest

from gui.database import Database
from gui.session import SessionManager, session
from gui import services, interface


@pytest.fixture(autouse=True)
def clean_session():
    session.logout()
    yield
    session.logout()


@pytest.fixture
def auth_db():
    # Exercise the real password verifier against a small account store.
    hashed = bcrypt.hashpw(b'correct', bcrypt.gensalt(rounds=4)).decode()
    db = Database.__new__(Database)
    accounts = {('Admin', 'admin1'), ('Lecturer', 'teacher1'), ('Student', 'student1')}
    db.get_user = MagicMock(side_effect=lambda role, username:
                            {'username': username, 'password': hashed}
                            if (role, username) in accounts else None)
    db.cursor = MagicMock()
    return db


@pytest.mark.parametrize('username,password,role', [
    ('admin1', 'wrong', 'Admin'), ('missing', 'correct', 'Admin'),
    ('student1', 'correct', 'Admin'), ('admin1', '', 'Admin'),
    ('', 'correct', 'Admin'), ('admin1', 'correct', 'Unknown'),
])
def test_failed_login_does_not_keep_previous_identity(auth_db, username, password, role):
    assert session.login(auth_db, 'admin1', 'correct', 'Admin')
    assert not session.login(auth_db, username, password, role)
    assert session.get_identity() is None
    with pytest.raises(services.ValidationError, match='Chưa đăng nhập'):
        services.change_student_status(auth_db, 'SV001', 'Bảo lưu', 'Test')
    auth_db.cursor.execute.assert_not_called()


def test_database_error_during_login_clears_session(auth_db):
    assert session.login(auth_db, 'admin1', 'correct', 'Admin')
    auth_db.get_user.side_effect = RuntimeError('DB unavailable')
    with pytest.raises(RuntimeError, match='DB unavailable'):
        session.login(auth_db, 'admin1', 'correct', 'Admin')
    assert not session.is_logged_in()


@pytest.mark.parametrize('username,role', [('student1', 'Student'), ('teacher1', 'Lecturer')])
def test_authenticated_non_admin_cannot_change_status(auth_db, username, role):
    assert session.login(auth_db, username, 'correct', role)
    with pytest.raises(services.ValidationError, match='Chỉ Admin'):
        services.change_student_status(auth_db, 'SV001', 'Bảo lưu', 'Test')
    auth_db.cursor.execute.assert_not_called()


def test_caller_cannot_create_identity_with_old_api_or_public_fields(auth_db):
    with pytest.raises(TypeError):
        session.login('admin1', 'Admin')
    with pytest.raises(AttributeError):
        session.current_user = 'admin1'
    with pytest.raises(AttributeError):
        session.current_role = 'Admin'
    with pytest.raises(TypeError):
        services.change_student_status(auth_db, 'SV001', 'Bảo lưu', 'Test',
                                       current_username='admin1', current_role='Admin')
    assert not session.is_logged_in()
    auth_db.cursor.execute.assert_not_called()


def test_separately_created_manager_does_not_authenticate_service(auth_db):
    other = SessionManager()
    assert other.login(auth_db, 'admin1', 'correct', 'Admin')
    with pytest.raises(services.ValidationError, match='Chưa đăng nhập'):
        services.change_student_status(auth_db, 'SV001', 'Bảo lưu', 'Test')
    auth_db.cursor.execute.assert_not_called()


def test_logout_invalidates_service_access(auth_db):
    assert session.login(auth_db, 'admin1', 'correct', 'Admin')
    session.logout()
    session.logout()  # idempotent
    assert session.get_current_user() is None
    assert session.get_current_role() is None
    with pytest.raises(services.ValidationError, match='Chưa đăng nhập'):
        services.change_student_status(auth_db, 'SV001', 'Bảo lưu', 'Test')
    auth_db.cursor.execute.assert_not_called()


@pytest.mark.parametrize('dashboard', [interface.AdminDashboard,
                                     interface.StudentDashboard,
                                     interface.LecturerDashboard])
def test_every_dashboard_logout_invalidates_session(auth_db, monkeypatch, dashboard):
    assert session.login(auth_db, 'admin1', 'correct', 'Admin')
    monkeypatch.setattr(interface.messagebox, 'askyesno', lambda *args: True)
    open_login = MagicMock()
    monkeypatch.setattr(interface, 'LoginWindow', open_login)
    root = MagicMock()
    dashboard.logout(SimpleNamespace(root=root))
    assert not session.is_logged_in()
    root.destroy.assert_called_once()
    open_login.assert_called_once()


def test_window_close_invalidates_session(auth_db):
    assert session.login(auth_db, 'admin1', 'correct', 'Admin')
    root = MagicMock()
    interface._close_session_window(root)
    assert not session.is_logged_in()
    root.destroy.assert_called_once()
