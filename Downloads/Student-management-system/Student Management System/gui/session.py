"""Authenticated desktop session, not a boundary against arbitrary Python code.

Only login() creates an identity after Database.verify_user succeeds. Passwords
are never retained. A separate SessionManager does not authenticate the singleton.
"""
from threading import RLock


class SessionManager:
    __slots__ = ("__identity", "__lock")

    def __init__(self):
        self.__identity = None
        self.__lock = RLock()

    def login(self, db, username, password, role):
        """Authenticate credentials. Failure, including DB errors, clears session."""
        with self.__lock:
            self.__identity = None
            if role not in ("Admin", "Lecturer", "Student"):
                return False
            username = username.strip() if isinstance(username, str) else ""
            if not username or not isinstance(password, str) or not password:
                return False
            if db.verify_user(role, username, password) is not True:
                return False
            self.__identity = (username, role)
            return True

    def logout(self):
        with self.__lock:
            self.__identity = None

    def get_identity(self):
        """Return one consistent, immutable snapshot or None."""
        with self.__lock:
            return self.__identity

    @property
    def current_user(self):
        identity = self.get_identity()
        return identity[0] if identity else None

    @property
    def current_role(self):
        identity = self.get_identity()
        return identity[1] if identity else None

    def get_current_user(self):
        return self.current_user

    def get_current_role(self):
        return self.current_role

    def is_logged_in(self):
        return self.get_identity() is not None


session = SessionManager()
