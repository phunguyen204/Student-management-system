"""
migrate_passwords.py
====================
One-time migration script: scans admins, lecturers, and students tables
and hashes any password that is still stored as plaintext.

Usage:
    cd "Student Management System"
    python migrate_passwords.py

A bcrypt hash always starts with '$2b$' (or '$2a$'/'$2y$').
Any password value that does NOT match this pattern is treated as plaintext
and will be hashed in-place.

Cấu hình MySQL: dùng biến môi trường SMS_DB_* hoặc file config.ini
(xem config.ini.example).
"""

import mysql.connector
import bcrypt


def hash_password(plain_password: str) -> str:
    """Hash a plaintext password using bcrypt and return a UTF-8 string."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def is_bcrypt_hash(value: str) -> bool:
    """Return True if the value looks like an existing bcrypt hash."""
    return value.startswith(("$2b$", "$2a$", "$2y$"))


def migrate_table(cursor, conn, table: str, pk_column: str = "username"):
    """Migrate all plaintext passwords in *table* to bcrypt hashes."""
    cursor.execute(f"SELECT {pk_column}, password FROM {table}")
    rows = cursor.fetchall()
    migrated = 0
    for row in rows:
        pk_value = row[pk_column]
        pwd = row["password"]
        if not pwd or is_bcrypt_hash(pwd):
            continue  # already hashed or empty
        hashed = hash_password(pwd)
        cursor.execute(
            f"UPDATE {table} SET password = %s WHERE {pk_column} = %s",
            (hashed, pk_value),
        )
        migrated += 1
    conn.commit()
    return migrated, len(rows)


def main():
    from gui.config import get_db_config
    config = get_db_config()

    conn = mysql.connector.connect(**config)
    cursor = conn.cursor(dictionary=True)

    tables = ["admins", "lecturers", "students"]
    print("=" * 50)
    print("  Password Migration — plaintext -> bcrypt")
    print("=" * 50)

    for table in tables:
        migrated, total = migrate_table(cursor, conn, table)
        print(f"  [{table}] {migrated}/{total} passwords hashed.")

    cursor.close()
    conn.close()
    print("=" * 50)
    print("  Migration complete!")
    print("=" * 50)


if __name__ == "__main__":
    main()
