import pytest
import os
import subprocess
import tkinter as tk
from tkinter import ttk
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "Student Management System"

# -- Mock config --
from gui import config
from gui import interface

def test_database_port_validation(monkeypatch):
    from gui.database import Database
    # Mock get_db_connect_config to return an invalid port
    def mock_get_config():
        return ({'host': 'localhost', 'user': 'root', 'password': '', 'port': '70000'}, 'test_db')
    
    monkeypatch.setattr(config, 'get_db_connect_config', mock_get_config)
    
    with pytest.raises(ValueError) as excinfo:
        db = Database()
    
    assert "Port MySQL không hợp lệ" in str(excinfo.value)
    assert "70000" in str(excinfo.value)


def test_seed_idempotency(monkeypatch):
    """Test that running insert_Data.py multiple times does not crash."""
    env = os.environ.copy()
    if 'SMS_TEST_MYSQL_JSON' not in env:
        pytest.skip("Bỏ qua test seed idempotency vì không có SMS_TEST_MYSQL_JSON.")
    
    import json
    db_config = json.loads(env['SMS_TEST_MYSQL_JSON'])
    
    test_env = env.copy()
    test_env["PYTHONIOENCODING"] = "utf-8"
    test_env["SMS_DB_PORT"] = str(db_config.get("port", 3306))
    test_env['SMS_DB_HOST'] = db_config.get('host', 'localhost')
    test_env['SMS_DB_USER'] = db_config.get('user', 'root')
    test_env['SMS_DB_PASSWORD'] = db_config.get('password', '')
    test_env['SMS_DB_NAME'] = 'sms_test_seed_db'
    
    try:
        import mysql.connector
        conn = mysql.connector.connect(host=test_env['SMS_DB_HOST'], user=test_env['SMS_DB_USER'], password=test_env['SMS_DB_PASSWORD'], port=int(test_env["SMS_DB_PORT"]))
        cursor = conn.cursor()
        cursor.execute("DROP DATABASE IF EXISTS sms_test_seed_db")
        conn.commit()
        cursor.close()
        conn.close()
    except:
        pass
    
    # Database() thực sự tạo database, bảng và thực hiện bootstrap/migration.
    bootstrap_code = """
    from gui.database import Database

    db = Database()
    try:
        assert db.is_ready, "Database chưa sẵn sàng sau khởi tạo"
    finally:
        db.cursor.close()
        db.conn.close()
    """

    subprocess.run(
        [sys.executable, "-c", bootstrap_code],
        cwd=APP_DIR,
        env=test_env,
        check=True,
    )

    seed_command = [
        sys.executable,
        str(APP_DIR / "insert_Data.py"),
    ]

    result1 = subprocess.run(
        seed_command,
        cwd=APP_DIR,
        env=test_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result1.returncode == 0, result1.stdout + result1.stderr

    result2 = subprocess.run(
        seed_command,
        cwd=APP_DIR,
        env=test_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result2.returncode == 0, result2.stdout + result2.stderr

def test_check_empty_treeview():
    root = tk.Tk()
    tree = ttk.Treeview(root, columns=("col1", "col2"))
    tree.insert("", "end", values=("1", "2"))
    
    interface.check_empty_treeview(tree, "No data")
    items = tree.get_children()
    assert len(items) == 1
    assert str(tree.item(items[0])['values'][0]) == '1'
    
    tree.delete(items[0])
    interface.check_empty_treeview(tree, "Chưa có dữ liệu")
    items_after = tree.get_children()
    assert len(items_after) == 1
    assert str(tree.item(items_after[0])['values'][0]) == "Chưa có dữ liệu"
    
    root.destroy()
