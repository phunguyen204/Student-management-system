"""Centralized MySQL configuration for the Student Management System.

Configuration is read from (in order of priority):
1. Environment variables: SMS_DB_HOST, SMS_DB_PORT, SMS_DB_USER, SMS_DB_PASSWORD, SMS_DB_NAME
2. A ``config.ini`` file located next to the project root
3. Falls back to sensible defaults for host/port/database, but NEVER
   provides a default password — the user must configure it explicitly.

Test database configuration is read from SMS_TEST_MYSQL_JSON (unchanged).
"""
import os
import logging
from pathlib import Path

log = logging.getLogger("sms.config")

# Locate config.ini: look in the project root (parent of 'gui/' package)
_PACKAGE_DIR = Path(__file__).resolve().parent          # gui/
_PROJECT_DIR = _PACKAGE_DIR.parent                       # Student Management System/
_REPO_ROOT = _PROJECT_DIR.parent                         # repository root

_CONFIG_SEARCH_PATHS = [
    _PROJECT_DIR / "config.ini",
    _REPO_ROOT / "config.ini",
]


def _read_ini_config():
    """Try to read config.ini and return a dict of DB settings, or {}."""
    try:
        import configparser
    except ImportError:
        return {}

    for path in _CONFIG_SEARCH_PATHS:
        if path.is_file():
            parser = configparser.ConfigParser(interpolation=None)
            parser.read(str(path), encoding="utf-8")
            if parser.has_section("mysql"):
                result = {}
                for key in ("host", "port", "user", "password", "database"):
                    if parser.has_option("mysql", key):
                        result[key] = parser.get("mysql", key)
                log.info("Đọc cấu hình MySQL từ %s", path)
                return result
    return {}


def get_db_config():
    """Return a dict suitable for ``mysql.connector.connect(**config)``.

    Raises ``RuntimeError`` with a user-friendly message if the password
    is not configured.
    """
    ini = _read_ini_config()

    host = os.environ.get("SMS_DB_HOST") or ini.get("host", "localhost")
    port_str = os.environ.get("SMS_DB_PORT") or ini.get("port", "3306")
    user = os.environ.get("SMS_DB_USER") or ini.get("user", "")
    password = os.environ.get("SMS_DB_PASSWORD") or ini.get("password", "")
    database = os.environ.get("SMS_DB_NAME") or ini.get("database", "admin_db")

    try:
        port = int(port_str) if port_str else 3306
    except (ValueError, TypeError):
        raise ValueError(f"Cổng kết nối (port) không hợp lệ: '{port_str}'. Phải là một số nguyên.")

    if not user or not password:
        raise RuntimeError(
            "Chưa cấu hình kết nối MySQL.\n\n"
            "Cách 1 – Biến môi trường (PowerShell):\n"
            '  $env:SMS_DB_USER = "your_user"\n'
            '  $env:SMS_DB_PASSWORD = "your_password"\n\n'
            "Cách 2 – Tạo file config.ini (xem config.ini.example):\n"
            "  [mysql]\n"
            "  user = your_user\n"
            "  password = your_password\n\n"
            "Không sử dụng tài khoản root cho môi trường sản xuất."
        )

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
        "autocommit": True,
    }


def get_db_connect_config():
    """Return config dict WITHOUT the database key (for initial server connect)."""
    cfg = get_db_config()
    db_name = cfg.pop("database", "admin_db")
    return cfg, db_name
