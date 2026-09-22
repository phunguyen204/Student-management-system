# gui/database.py
"""Database connection, schema creation, and basic CRUD operations.

Business-logic rules (enrollment guards, grade checks, payment validation)
have been moved to ``gui.services``.  This module handles:

* MySQL connection and schema bootstrap
* Table creation (Step-2 schema)
* Legacy migration (delegates to ``gui.migration``)
* Data-integrity checks (``ensure_integrity``)
* Simple CRUD helpers used by the UI and services layer
"""

import math
import logging
from contextlib import contextmanager
from decimal import Decimal

import bcrypt
import mysql.connector
from mysql.connector import errorcode

log = logging.getLogger("sms.database")


class ValidationError(ValueError):
    """An operation violates a business rule; no changes were saved."""


# ── Password helpers ─────────────────────────────────────────────────────────

def hash_password(plain_password):
    """Hash a plaintext password using bcrypt and return the hash as a UTF-8 string."""
    return bcrypt.hashpw(plain_password.encode('utf-8'),
                         bcrypt.gensalt()).decode('utf-8')


def check_password(plain_password, hashed_password):
    """Verify a plaintext password against a bcrypt hash. Returns True if match."""
    return bcrypt.checkpw(plain_password.encode('utf-8'),
                          hashed_password.encode('utf-8'))


# ── Database class ───────────────────────────────────────────────────────────

class Database:
    def __init__(self):
        from .config import get_db_connect_config
        server_cfg, self._db_name = get_db_connect_config()
        
        # Validate port
        port = int(server_cfg.get('port', 3306))
        if not (1 <= port <= 65535):
            raise ValueError(f"Port MySQL không hợp lệ: {port}. Port phải nằm trong khoảng 1-65535.")
        server_cfg['port'] = port
        
        self.config = server_cfg
        self.conn = None
        self.cursor = None
        self._migration_ready = False  # True when migration is verified
        try:
            self.connect_server()
            self.create_database()
            self.connect_database()
            self._bootstrap_or_migrate()
            self.ensure_integrity()
            self.create_default_admin()
        except Exception:
            if self.conn is not None:
                self.conn.close()
            raise

    @property
    def is_ready(self):
        """True when the database schema and migration verification pass."""
        if not self._migration_ready:
            return False
        try:
            from .migration import verify_migration_schema_and_data
            ok, _ = verify_migration_schema_and_data(self.cursor)
            return ok
        except Exception:
            return False

    def connect_server(self):
        try:
            self.conn = mysql.connector.connect(**self.config)
            self.cursor = self.conn.cursor(dictionary=True)
            log.info("Kết nối MySQL thành công (%s:%s)",
                     self.config.get('host', 'localhost'),
                     self.config.get('port', 3306))
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_ACCESS_DENIED_ERROR:
                raise RuntimeError(
                    "Không thể đăng nhập MySQL. Kiểm tra tên người dùng và "
                    "mật khẩu trong cấu hình (biến môi trường hoặc config.ini).") from err
            else:
                log.error("Lỗi kết nối MySQL: %s", err)
                raise RuntimeError(
                    "Không thể kết nối MySQL. Kiểm tra MySQL đang chạy và "
                    "cấu hình host/port trong biến môi trường hoặc config.ini.") from err

    def create_database(self):
        try:
            self.cursor.execute(
                "CREATE DATABASE IF NOT EXISTS `%s` CHARACTER SET utf8mb4"
                % self._db_name)
            log.info("Cơ sở dữ liệu '%s' sẵn sàng.", self._db_name)
        except mysql.connector.Error as err:
            if err.errno == errorcode.ER_DB_CREATE_EXISTS:
                log.info("Cơ sở dữ liệu '%s' đã tồn tại.", self._db_name)
            else:
                raise

    def connect_database(self):
        try:
            self.config['database'] = self._db_name
            self.conn.database = self._db_name
            log.info("Đã kết nối cơ sở dữ liệu '%s'.", self._db_name)
        except mysql.connector.Error as err:
            raise RuntimeError(
                f"Không thể mở cơ sở dữ liệu '{self._db_name}'.") from err

    def _bootstrap_or_migrate(self):
        """Migration detection & execution under GET_LOCK before created_table."""
        self.cursor.execute("SELECT GET_LOCK('sms_migration_v2', 10) AS acquired")
        res = self.cursor.fetchone()
        if not res or res['acquired'] != 1:
            raise RuntimeError(
                "Một phiên khác đang thực hiện migration. Vui lòng thử lại sau.")

        try:
            from .migration import (
                _detect_state, run_migration, verify_migration_schema_and_data,
                mark_fresh_install_complete, resolve_coexisting_tables
            )
            ok, reason = resolve_coexisting_tables(self.cursor)
            if not ok:
                raise RuntimeError(reason)
                
            state = _detect_state(self.cursor)
            log.info("Database migration state: %s", state)

            if state in ('step1', 'in_progress'):
                log.info("Bắt đầu thực hiện migration...")
                run_migration(self.cursor, self.conn, dry_run=False)
            elif state == 'fresh':
                self.created_table()
                mark_fresh_install_complete(self.cursor, self.conn)
            else:
                self.created_table()

            ok, reason = verify_migration_schema_and_data(self.cursor)
            if not ok:
                self._migration_ready = False
                raise RuntimeError(f"Cơ sở dữ liệu chưa sẵn sàng sau migration: {reason}")
            
            self._migration_ready = True
        finally:
            self.cursor.execute("SELECT RELEASE_LOCK('sms_migration_v2')")
            self.cursor.fetchone()

    # ── Table creation (Step-2 schema) ───────────────────────────────────

    def created_table(self):
        """Create/update all tables for the Step-2 schema.

        Legacy tables (courses, old enrollments/grades/payments) are handled
        by the migration module — they are NOT created here.
        """
        try:
            # ── Auth tables ──────────────────────────────────────────────
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                username VARCHAR(255) PRIMARY KEY,
                password VARCHAR(255) NOT NULL
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS lecturers (
                username VARCHAR(255) PRIMARY KEY,
                password VARCHAR(255) NOT NULL
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)

            # ── Organization tables ──────────────────────────────────────
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS departments (
                id VARCHAR(20) PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS programs (
                id VARCHAR(20) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                department_id VARCHAR(20),
                FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE RESTRICT
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS admission_batches (
                id VARCHAR(20) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                year INT NOT NULL
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)
            self.cursor.execute("""
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

            # ── Students (may already exist from Step 1) ─────────────────
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS students (
                username VARCHAR(255) PRIMARY KEY,
                password VARCHAR(255) NOT NULL,
                mssv VARCHAR(20) NOT NULL UNIQUE,
                name VARCHAR(255),
                gender VARCHAR(10),
                email VARCHAR(255),
                phone VARCHAR(20),
                address VARCHAR(255),
                admin_class_id VARCHAR(20) NULL,
                academic_status VARCHAR(20) NOT NULL DEFAULT 'Đang học',
                FOREIGN KEY (admin_class_id) REFERENCES admin_classes(id) ON DELETE SET NULL
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)

            # ── Student Status History ───────────────────────────────────
            self.cursor.execute("""
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

            # ensure columns exist for upgrades from older schemas
            for col, spec in [
                ('phone', 'VARCHAR(25) NULL'),
                ('address', 'VARCHAR(255) NULL'),
                ('gender', 'VARCHAR(10) NULL AFTER name'),
                ('admin_class_id', 'VARCHAR(20) NULL'),
                ('academic_status', "VARCHAR(20) NOT NULL DEFAULT 'Đang học'"),
            ]:
                self.cursor.execute(f"SHOW COLUMNS FROM students LIKE '{col}'")
                if not self.cursor.fetchone():
                    self.cursor.execute(
                        f"ALTER TABLE students ADD COLUMN {col} {spec}")

            # ── Academic period tables ───────────────────────────────────
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS academic_years (
                id VARCHAR(20) PRIMARY KEY,
                name VARCHAR(100) NOT NULL UNIQUE,
                start_year INT NULL,
                end_year INT NULL
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS semesters (
                id VARCHAR(20) PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                academic_year_id VARCHAR(20) NOT NULL,
                start_date DATE NULL,
                end_date DATE NULL,
                registration_open TINYINT(1) NOT NULL DEFAULT 0,
                FOREIGN KEY (academic_year_id)
                    REFERENCES academic_years(id) ON DELETE RESTRICT,
                UNIQUE KEY uq_semester (academic_year_id, name)
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)

            # ── Subject catalog ──────────────────────────────────────────
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS subjects (
                id VARCHAR(50) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                credits INT NOT NULL
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)

            # ── Class sections ───────────────────────────────────────────
            self.cursor.execute("""
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
                FOREIGN KEY (lecturer)
                    REFERENCES lecturers(username) ON DELETE SET NULL
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS section_schedules (
                id INT AUTO_INCREMENT PRIMARY KEY,
                section_id VARCHAR(50) NOT NULL,
                weekday TINYINT NOT NULL,
                start_minutes SMALLINT NOT NULL,
                end_minutes SMALLINT NOT NULL,
                FOREIGN KEY (section_id)
                    REFERENCES class_sections(id) ON DELETE CASCADE
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)

            # ── Enrollments (Step-2: keyed by auto-increment id) ─────────
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS enrollments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                mssv VARCHAR(20) NOT NULL,
                section_id VARCHAR(50) NOT NULL,
                enrolled_at DATETIME NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uq_enrollment (mssv, section_id),
                FOREIGN KEY (mssv) REFERENCES students(mssv) ON DELETE RESTRICT,
                FOREIGN KEY (section_id)
                    REFERENCES class_sections(id) ON DELETE RESTRICT
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)

            # ── Grades (Step-2: keyed by enrollment_id) ──────────────────
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS grades (
                enrollment_id INT PRIMARY KEY,
                midterm FLOAT NULL,
                final_score FLOAT NULL,
                FOREIGN KEY (enrollment_id)
                    REFERENCES enrollments(id) ON DELETE RESTRICT
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)

            # ── Payments (Step-2: keyed by enrollment_id) ────────────────
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INT AUTO_INCREMENT PRIMARY KEY,
                enrollment_id INT NOT NULL,
                amount DECIMAL(15,2) NOT NULL,
                status VARCHAR(20) NOT NULL,
                time DATETIME NOT NULL,
                FOREIGN KEY (enrollment_id)
                    REFERENCES enrollments(id) ON DELETE RESTRICT
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)

            # ── ID sequences ────────────────────────────────────────────
            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS id_sequences (
                name VARCHAR(30) PRIMARY KEY,
                next_value BIGINT NOT NULL
            ) ENGINE=InnoDB CHARACTER SET=utf8mb4
            """)

            # ── Upgrade existing FLOAT columns to DECIMAL if needed ──────
            self._upgrade_float_to_decimal()

            self.conn.commit()
            log.info("Tất cả bảng dữ liệu đã sẵn sàng.")
        except mysql.connector.Error as err:
            raise RuntimeError(
                f'Không thể chuẩn bị bảng dữ liệu: {err}') from err

    def _upgrade_float_to_decimal(self):
        """Upgrade FLOAT amount columns to DECIMAL(15,2) for monetary precision."""
        for table, column in [('payments', 'amount'), ('class_sections', 'tuition_per_credit')]:
            try:
                self.cursor.execute(
                    "SELECT COUNT(*) AS n FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s", (table,))
                if self.cursor.fetchone()['n'] == 0:
                    continue
                self.cursor.execute(
                    "SELECT DATA_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
                    (table, column))
                row = self.cursor.fetchone()
                if row and row['DATA_TYPE'].upper() in ('FLOAT', 'DOUBLE', 'INT'):
                    try:
                        if column == 'amount':
                            self.cursor.execute(
                                f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` DECIMAL(15,2) NOT NULL")
                        else:
                            self.cursor.execute(
                                f"ALTER TABLE `{table}` MODIFY COLUMN `{column}` DECIMAL(15,2) NOT NULL DEFAULT 500000")
                        self.conn.commit()
                        log.info("Upgraded %s.%s from %s to DECIMAL(15,2)",
                                 table, column, row['DATA_TYPE'])
                    except mysql.connector.Error as err:
                        raise RuntimeError(
                            f"Nâng cấp kiểu dữ liệu tiền tệ cho {table}.{column} thất bại: {err}"
                        ) from err
            except mysql.connector.Error:
                # Table may not exist yet during migration
                pass


    def _run_migration_if_needed(self):
        """Auto-detect and run legacy migration using version-table-based detection."""
        from .migration import needs_migration, migration_complete, run_migration
        if needs_migration(self.cursor):
            log.info("Phát hiện migration cần chạy — bắt đầu migration.")
            print("Migrating legacy data...")
            results = run_migration(self.cursor, self.conn)
            for step, status in results.items():
                print(f"  {step}: {status}")
            print("Migration complete.")
            self._migration_ready = True
        elif migration_complete(self.cursor):
            self._migration_ready = True
        else:
            # Unknown state — be safe
            self._migration_ready = True

    # ── Integrity checks ─────────────────────────────────────────────────

    def create_default_admin(self):
        self.cursor.execute(
            "SELECT COUNT(*) AS cnt FROM admins WHERE username=%s", ("admin",))
        count = self.cursor.fetchone()
        if count['cnt'] == 0:
            hashed = hash_password("admin123")
            self.cursor.execute(
                "INSERT INTO admins (username, password) VALUES (%s, %s)",
                ("admin", hashed))
            self.conn.commit()

    def ensure_integrity(self):
        """Idempotent schema upgrade; never renumber or delete existing records.

        MySQL DDL commits implicitly. Validate legacy data first; serialize
        upgrades using a connection-level lock and allow safe reruns after failure.
        """
        self.cursor.execute(
            "SELECT GET_LOCK('sms_integrity_v2', 30) AS acquired")
        if self.cursor.fetchone()['acquired'] != 1:
            raise RuntimeError(
                "Một phiên khác đang nâng cấp dữ liệu; vui lòng mở lại sau.")
        try:
            # Check InnoDB
            self.cursor.execute("""
                SELECT TABLE_NAME FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN
                ('students','class_sections','enrollments','grades',
                 'payments','id_sequences','subjects','section_schedules',
                 'semesters','academic_years')
                AND ENGINE <> 'InnoDB'
            """)
            non_innodb = self.cursor.fetchall()
            if non_innodb:
                names = [r['TABLE_NAME'] for r in non_innodb]
                raise ValidationError(
                    f"Các bảng học vụ phải dùng InnoDB: {', '.join(names)}.")

            # Validate MSSV integrity
            self.cursor.execute(
                "SELECT username FROM students "
                "WHERE mssv IS NULL OR TRIM(mssv)='' LIMIT 1")
            if self.cursor.fetchone():
                raise ValidationError(
                    "Dữ liệu cũ có sinh viên thiếu MSSV. "
                    "Cần bổ sung MSSV trước khi mở ứng dụng.")

            self.cursor.execute(
                "SELECT mssv FROM students GROUP BY mssv "
                "HAVING COUNT(*)>1 LIMIT 1")
            duplicate = self.cursor.fetchone()
            if duplicate:
                raise ValidationError(
                    f"Dữ liệu cũ bị trùng MSSV {duplicate['mssv']}; "
                    f"cần đối chiếu hồ sơ, không tự đổi mã.")

            # Ensure MSSV unique index
            self.cursor.execute("SHOW INDEX FROM students")
            indexes = {}
            for index in self.cursor.fetchall():
                if index['Non_unique'] == 0:
                    indexes.setdefault(index['Key_name'], []).append(
                        index['Column_name'])
            if ['mssv'] not in indexes.values():
                try:
                    self.cursor.execute(
                        "ALTER TABLE students "
                        "ADD UNIQUE KEY uq_students_mssv (mssv)")
                except mysql.connector.Error as e:
                    if e.errno != errorcode.ER_DUP_KEYNAME:
                        raise

            # ── Ensure FK on students.admin_class_id ─────────────────
            from .migration import _column_exists, _any_fk_on_column
            if _column_exists(self.cursor, 'students', 'admin_class_id'):
                if not _any_fk_on_column(self.cursor, 'students', 'admin_class_id'):
                    # Check for violations
                    self.cursor.execute("""
                        SELECT s.username, s.admin_class_id FROM students s
                        WHERE s.admin_class_id IS NOT NULL
                          AND s.admin_class_id NOT IN (SELECT id FROM admin_classes)
                    """)
                    violations = self.cursor.fetchall()
                    if violations:
                        viol_str = ", ".join(
                            f"{v['username']}→{v['admin_class_id']}" for v in violations[:5])
                        raise ValidationError(
                            f"Sinh viên có lớp hành chính không tồn tại: {viol_str}. "
                            f"Cần sửa dữ liệu trước khi thêm ràng buộc khóa ngoại.")
                    try:
                        self.cursor.execute(
                            "ALTER TABLE students ADD CONSTRAINT fk_students_admin_class "
                            "FOREIGN KEY (admin_class_id) REFERENCES admin_classes(id) "
                            "ON DELETE SET NULL")
                    except mysql.connector.Error as e:
                        if e.errno != errorcode.ER_FK_DUP_NAME:
                            raise

            # Ensure id_sequences has a row
            self.cursor.execute(
                "SELECT mssv FROM students WHERE mssv REGEXP '^SV[0-9]+$'")
            highest = max(
                (int(row['mssv'][2:]) for row in self.cursor.fetchall()),
                default=0)
            self.cursor.execute("""
                INSERT INTO id_sequences (name, next_value)
                VALUES ('student', %s)
                ON DUPLICATE KEY UPDATE
                    next_value=GREATEST(next_value, VALUES(next_value))
            """, (highest + 1,))

            # Validate FK on enrollments reference class_sections
            self.cursor.execute("""
                SELECT e.mssv, e.section_id FROM enrollments e
                LEFT JOIN students s ON s.mssv = e.mssv
                WHERE s.username IS NULL LIMIT 1
            """)
            orphan = self.cursor.fetchone()
            if orphan:
                raise ValidationError(
                    f"Bảng enrollments có MSSV '{orphan['mssv']}' không liên kết "
                    f"được với sinh viên. Cần đối chiếu trước khi nâng cấp.")

            self.cursor.execute("""
                SELECT e.section_id FROM enrollments e
                LEFT JOIN class_sections cs ON cs.id = e.section_id
                WHERE cs.id IS NULL LIMIT 1
            """)
            orphan = self.cursor.fetchone()
            if orphan:
                raise ValidationError(
                    f"Bảng enrollments có lớp HP '{orphan['section_id']}' không "
                    f"tồn tại. Cần đối chiếu trước khi nâng cấp.")

        finally:
            self.cursor.execute("SELECT RELEASE_LOCK('sms_integrity_v2')")
            self.cursor.fetchone()

    # ── Transaction helper ───────────────────────────────────────────────

    @contextmanager
    def transaction(self):
        """READ COMMITTED transaction scope for the desktop connection."""
        self.conn.start_transaction(isolation_level="READ COMMITTED")
        try:
            yield
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ── User CRUD ────────────────────────────────────────────────────────

    def get_user(self, role, username):
        table = {"Admin": "admins", "Lecturer": "lecturers",
                 "Student": "students"}[role]
        self.cursor.execute(
            f"SELECT * FROM {table} WHERE username=%s", (username,))
        return self.cursor.fetchone()

    def verify_user(self, role, username, password):
        user = self.get_user(role, username)
        if not user:
            return False
        try:
            return check_password(password, user["password"])
        except Exception:
            # Fallback: legacy plaintext comparison
            return user["password"] == password

    def create_lecturer(self, username, password):
        hashed = hash_password(password)
        self.cursor.execute(
            "INSERT INTO lecturers (username, password) VALUES (%s, %s)",
            (username, hashed))
        self.conn.commit()

    # ── MSSV sequence ────────────────────────────────────────────────────

    def next_mssv(self):
        """Reserve a unique MSSV. Unused reservations may leave harmless gaps."""
        with self.transaction():
            return self._reserve_mssv()

    def _reserve_mssv(self):
        self.cursor.execute(
            "SELECT next_value FROM id_sequences "
            "WHERE name='student' FOR UPDATE")
        value = self.cursor.fetchone()['next_value']
        self.cursor.execute(
            "UPDATE id_sequences SET next_value=next_value+1 "
            "WHERE name='student'")
        return f"SV{value:03d}"

    # ── Student CRUD ─────────────────────────────────────────────────────

    def add_student(self, username, password):
        hashed = hash_password(password)
        with self.transaction():
            mssv = self._reserve_mssv()
            self.cursor.execute(
                "INSERT INTO students (username, password, mssv) "
                "VALUES (%s, %s, %s)",
                (username, hashed, mssv))
        return mssv

    def list_students(self, search=None, filters=None, limit=None, offset=None):
        base = """
            SELECT s.*, ac.name AS class_name,
                   p.name AS program_name, p.id AS program_id,
                   ab.name AS batch_name, ab.id AS batch_id,
                   d.name AS department_name, d.id AS department_id
            FROM students s
            LEFT JOIN admin_classes ac ON ac.id = s.admin_class_id
            LEFT JOIN programs p ON p.id = ac.program_id
            LEFT JOIN departments d ON d.id = p.department_id
            LEFT JOIN admission_batches ab ON ab.id = ac.batch_id
            WHERE 1=1
        """
        params = []
        if search and search.strip():
            term = f"%{search.strip()}%"
            base += " AND (s.mssv LIKE %s OR s.name LIKE %s OR s.username LIKE %s)"
            params.extend([term, term, term])
        
        if filters:
            if filters.get('department_id'):
                base += " AND d.id = %s"
                params.append(filters['department_id'])
            if filters.get('program_id'):
                base += " AND p.id = %s"
                params.append(filters['program_id'])
            if filters.get('batch_id'):
                base += " AND ab.id = %s"
                params.append(filters['batch_id'])
            if filters.get('admin_class_id'):
                base += " AND ac.id = %s"
                params.append(filters['admin_class_id'])
            if filters.get('academic_status'):
                base += " AND s.academic_status = %s"
                params.append(filters['academic_status'])

        base += " ORDER BY s.mssv"

        if limit is not None:
            base += " LIMIT %s"
            params.append(limit)
            if offset is not None:
                base += " OFFSET %s"
                params.append(offset)

        self.cursor.execute(base, tuple(params))
        return self.cursor.fetchall()

    def count_students(self, search=None, filters=None):
        base = """
            SELECT COUNT(*) AS cnt
            FROM students s
            LEFT JOIN admin_classes ac ON ac.id = s.admin_class_id
            LEFT JOIN programs p ON p.id = ac.program_id
            LEFT JOIN departments d ON d.id = p.department_id
            LEFT JOIN admission_batches ab ON ab.id = ac.batch_id
            WHERE 1=1
        """
        params = []
        if search and search.strip():
            term = f"%{search.strip()}%"
            base += " AND (s.mssv LIKE %s OR s.name LIKE %s OR s.username LIKE %s)"
            params.extend([term, term, term])
        
        if filters:
            if filters.get('department_id'):
                base += " AND d.id = %s"
                params.append(filters['department_id'])
            if filters.get('program_id'):
                base += " AND p.id = %s"
                params.append(filters['program_id'])
            if filters.get('batch_id'):
                base += " AND ab.id = %s"
                params.append(filters['batch_id'])
            if filters.get('admin_class_id'):
                base += " AND ac.id = %s"
                params.append(filters['admin_class_id'])
            if filters.get('academic_status'):
                base += " AND s.academic_status = %s"
                params.append(filters['academic_status'])

        self.cursor.execute(base, tuple(params))
        return self.cursor.fetchone()['cnt']

    def get_student_profile(self, mssv):
        """Lấy thông tin tổng hợp của sinh viên: info, enrollments, grades, payments."""
        self.cursor.execute("""
            SELECT s.*, ac.name AS class_name,
                   p.name AS program_name, d.name AS department_name,
                   ab.name AS batch_name
            FROM students s
            LEFT JOIN admin_classes ac ON ac.id = s.admin_class_id
            LEFT JOIN programs p ON p.id = ac.program_id
            LEFT JOIN departments d ON d.id = p.department_id
            LEFT JOIN admission_batches ab ON ab.id = ac.batch_id
            WHERE s.mssv = %s
        """, (mssv,))
        info = self.cursor.fetchone()
        if not info:
            return None

        self.cursor.execute("""
            SELECT e.id AS enrollment_id, e.enrolled_at,
                   cs.id AS section_id, cs.semester_id, sem.name AS semester_name,
                   ay.name AS academic_year_name,
                   subj.name AS subject_name, subj.credits
            FROM enrollments e
            JOIN class_sections cs ON cs.id = e.section_id
            JOIN subjects subj ON subj.id = cs.subject_id
            JOIN semesters sem ON sem.id = cs.semester_id
            JOIN academic_years ay ON ay.id = sem.academic_year_id
            WHERE e.mssv = %s
            ORDER BY ay.start_year, sem.start_date, cs.id
        """, (mssv,))
        enrollments = self.cursor.fetchall()

        self.cursor.execute("""
            SELECT g.*
            FROM grades g
            JOIN enrollments e ON e.id = g.enrollment_id
            WHERE e.mssv = %s
        """, (mssv,))
        grades = {r['enrollment_id']: r for r in self.cursor.fetchall()}

        self.cursor.execute("""
            SELECT p.*
            FROM payments p
            JOIN enrollments e ON e.id = p.enrollment_id
            WHERE e.mssv = %s
            ORDER BY p.time
        """, (mssv,))
        payments = self.cursor.fetchall()

        self.cursor.execute("""
            SELECT * FROM student_status_history
            WHERE mssv = %s
            ORDER BY changed_at DESC
        """, (mssv,))
        history = self.cursor.fetchall()

        return {
            'info': info,
            'enrollments': enrollments,
            'grades': grades,
            'payments': payments,
            'history': history
        }

    def get_student_statistics(self):
        """Thống kê tổng hợp số lượng sinh viên (dành cho Admin dashboard)."""
        stats = {}
        self.cursor.execute("SELECT COUNT(DISTINCT mssv) AS cnt FROM students")
        stats['total_students'] = self.cursor.fetchone()['cnt']
        
        self.cursor.execute("SELECT academic_status, COUNT(DISTINCT mssv) AS cnt FROM students GROUP BY academic_status")
        stats['by_status'] = self.cursor.fetchall()

        self.cursor.execute("""
            SELECT IFNULL(d.name, 'Chưa phân khoa') AS name, COUNT(DISTINCT s.mssv) AS cnt
            FROM students s
            LEFT JOIN admin_classes ac ON ac.id = s.admin_class_id
            LEFT JOIN programs p ON p.id = ac.program_id
            LEFT JOIN departments d ON d.id = p.department_id
            GROUP BY d.id, d.name
        """)
        stats['by_department'] = self.cursor.fetchall()

        self.cursor.execute("""
            SELECT IFNULL(p.name, 'Chưa phân ngành') AS name, COUNT(DISTINCT s.mssv) AS cnt
            FROM students s
            LEFT JOIN admin_classes ac ON ac.id = s.admin_class_id
            LEFT JOIN programs p ON p.id = ac.program_id
            GROUP BY p.id, p.name
        """)
        stats['by_program'] = self.cursor.fetchall()
        
        self.cursor.execute("""
            SELECT IFNULL(ab.name, 'Chưa phân khóa') AS name, COUNT(DISTINCT s.mssv) AS cnt
            FROM students s
            LEFT JOIN admin_classes ac ON ac.id = s.admin_class_id
            LEFT JOIN admission_batches ab ON ab.id = ac.batch_id
            GROUP BY ab.id, ab.name
        """)
        stats['by_batch'] = self.cursor.fetchall()
        
        self.cursor.execute("""
            SELECT IFNULL(ac.name, 'Chưa phân lớp') AS name, COUNT(DISTINCT s.mssv) AS cnt
            FROM students s
            LEFT JOIN admin_classes ac ON ac.id = s.admin_class_id
            GROUP BY ac.id, ac.name
        """)
        stats['by_admin_class'] = self.cursor.fetchall()

        return stats

    # Keep old name for compatibility during transition
    def list_student(self, search=None, filters=None, limit=None, offset=None):
        return self.list_students(search, filters, limit, offset)

    def update_student_profile(self, username, name=None, gender=None,
                               email=None, phone=None, address=None,
                               admin_class_id=...):
        """Update student profile fields. Pass admin_class_id=None to clear,
        admin_class_id=... (default) to leave unchanged."""
        parts, params = [], []
        if name is not None:
            parts.append("name=%s"); params.append(name)
        if gender is not None:
            parts.append("gender=%s"); params.append(gender)
        if email is not None:
            parts.append("email=%s"); params.append(email)
        if phone is not None:
            parts.append("phone=%s"); params.append(phone)
        if address is not None:
            parts.append("address=%s"); params.append(address)
        if admin_class_id is not ...:
            parts.append("admin_class_id=%s"); params.append(admin_class_id)
        if not parts:
            return
        params.append(username)
        sql = f"UPDATE students SET {', '.join(parts)} WHERE username=%s"
        self.cursor.execute(sql, tuple(params))
        self.conn.commit()

    # ── Subject CRUD ─────────────────────────────────────────────────────

    def add_subject(self, sid, name, credits):
        self.cursor.execute(
            "INSERT INTO subjects (id, name, credits) VALUES (%s, %s, %s)",
            (sid, name, credits))
        self.conn.commit()

    def list_subjects(self):
        self.cursor.execute("SELECT * FROM subjects ORDER BY id")
        return self.cursor.fetchall()

    def get_subject(self, sid):
        self.cursor.execute("SELECT * FROM subjects WHERE id=%s", (sid,))
        return self.cursor.fetchone()

    def update_subject(self, sid, name=None, credits=None):
        parts, params = [], []
        if name is not None:
            parts.append("name=%s"); params.append(name)
        if credits is not None:
            parts.append("credits=%s"); params.append(credits)
        if not parts:
            return
        params.append(sid)
        self.cursor.execute(
            f"UPDATE subjects SET {', '.join(parts)} WHERE id=%s",
            tuple(params))
        self.conn.commit()

    # ── Academic Year / Semester CRUD ─────────────────────────────────────

    def add_academic_year(self, yid, name, start_year=None, end_year=None):
        self.cursor.execute(
            "INSERT INTO academic_years (id, name, start_year, end_year) "
            "VALUES (%s, %s, %s, %s)", (yid, name, start_year, end_year))
        self.conn.commit()

    def list_academic_years(self):
        self.cursor.execute("SELECT * FROM academic_years ORDER BY id")
        return self.cursor.fetchall()

    def get_academic_year(self, yid):
        self.cursor.execute("SELECT * FROM academic_years WHERE id=%s", (yid,))
        return self.cursor.fetchone()

    def update_academic_year(self, yid, name=None, start_year=None, end_year=None):
        ay = self.get_academic_year(yid)
        if not ay:
            raise ValidationError(f"Năm học '{yid}' không tồn tại.")

        parts, params = [], []
        if name is not None:
            if not str(name).strip():
                raise ValidationError("Tên năm học không được để trống.")
            parts.append("name=%s"); params.append(str(name).strip())
        if start_year is not None:
            parts.append("start_year=%s"); params.append(start_year)
        if end_year is not None:
            parts.append("end_year=%s"); params.append(end_year)

        sy = start_year if start_year is not None else ay.get('start_year')
        ey = end_year if end_year is not None else ay.get('end_year')
        if sy is not None and ey is not None and sy > ey:
            raise ValidationError("Năm bắt đầu phải nhỏ hơn hoặc bằng năm kết thúc.")

        if not parts:
            return
        params.append(yid)
        self.cursor.execute(
            f"UPDATE academic_years SET {', '.join(parts)} WHERE id=%s",
            tuple(params))
        self.conn.commit()

    def add_semester(self, sid, name, academic_year_id, start_date=None,
                     end_date=None, registration_open=0):
        if not name or not str(name).strip():
            raise ValidationError("Tên học kỳ không được để trống.")
        ay = self.get_academic_year(academic_year_id)
        if not ay:
            raise ValidationError(f"Năm học '{academic_year_id}' không tồn tại.")
        if start_date and end_date and str(start_date) > str(end_date):
            raise ValidationError("Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.")
        self.cursor.execute(
            "INSERT INTO semesters "
            "(id, name, academic_year_id, start_date, end_date, registration_open) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (sid, name, academic_year_id, start_date, end_date,
             registration_open))
        self.conn.commit()

    def list_semesters(self, academic_year_id=None):
        if academic_year_id:
            self.cursor.execute(
                "SELECT s.*, ay.name AS year_name FROM semesters s "
                "JOIN academic_years ay ON ay.id = s.academic_year_id "
                "WHERE s.academic_year_id=%s ORDER BY s.id",
                (academic_year_id,))
        else:
            self.cursor.execute(
                "SELECT s.*, ay.name AS year_name FROM semesters s "
                "JOIN academic_years ay ON ay.id = s.academic_year_id "
                "ORDER BY s.id")
        return self.cursor.fetchall()

    def get_semester(self, sid):
        self.cursor.execute(
            "SELECT s.*, ay.name AS year_name FROM semesters s "
            "JOIN academic_years ay ON ay.id = s.academic_year_id "
            "WHERE s.id=%s", (sid,))
        return self.cursor.fetchone()

    def update_semester(self, sid, registration_open=None, name=None,
                        academic_year_id=None, start_date=None, end_date=None,
                        clear_start_date=False, clear_end_date=False):
        sem = self.get_semester(sid)
        if not sem:
            raise ValidationError(f"Học kỳ '{sid}' không tồn tại.")

        parts, params = [], []
        if registration_open is not None:
            parts.append("registration_open=%s")
            params.append(registration_open)
        if name is not None:
            if not str(name).strip():
                raise ValidationError("Tên học kỳ không được để trống.")
            parts.append("name=%s"); params.append(str(name).strip())
        if academic_year_id is not None:
            ay = self.get_academic_year(academic_year_id)
            if not ay:
                raise ValidationError(f"Năm học '{academic_year_id}' không tồn tại.")
            parts.append("academic_year_id=%s"); params.append(academic_year_id)
        if clear_start_date:
            parts.append("start_date=NULL")
        elif start_date is not None:
            parts.append("start_date=%s"); params.append(start_date)
        if clear_end_date:
            parts.append("end_date=NULL")
        elif end_date is not None:
            parts.append("end_date=%s"); params.append(end_date)

        effective_start = None if clear_start_date else (start_date if start_date is not None else sem.get('start_date'))
        effective_end = None if clear_end_date else (end_date if end_date is not None else sem.get('end_date'))
        if effective_start and effective_end and str(effective_start) > str(effective_end):
            raise ValidationError("Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.")

        if not parts:
            return
        params.append(sid)
        self.cursor.execute(
            f"UPDATE semesters SET {', '.join(parts)} WHERE id=%s",
            tuple(params))
        self.conn.commit()

    # ── Department / Program / Batch / AdminClass CRUD ───────────────────

    def add_department(self, did, name):
        if not name or not str(name).strip():
            raise ValidationError("Tên khoa không được để trống.")
        self.cursor.execute(
            "INSERT INTO departments (id, name) VALUES (%s, %s)", (did, name))
        self.conn.commit()

    def list_departments(self):
        self.cursor.execute("SELECT * FROM departments ORDER BY id")
        return self.cursor.fetchall()

    def get_department(self, did):
        self.cursor.execute("SELECT * FROM departments WHERE id=%s", (did,))
        return self.cursor.fetchone()

    def update_department(self, did, name=None):
        if name is None:
            return
        if not str(name).strip():
            raise ValidationError("Tên khoa không được để trống.")
        self.cursor.execute(
            "UPDATE departments SET name=%s WHERE id=%s", (str(name).strip(), did))
        self.conn.commit()

    def add_program(self, pid, name, department_id):
        if not name or not str(name).strip():
            raise ValidationError("Tên ngành không được để trống.")
        dept = self.get_department(department_id)
        if not dept:
            raise ValidationError(f"Khoa '{department_id}' không tồn tại.")
        self.cursor.execute(
            "INSERT INTO programs (id, name, department_id) "
            "VALUES (%s, %s, %s)", (pid, name, department_id))
        self.conn.commit()

    def list_programs(self, department_id=None):
        if department_id:
            self.cursor.execute(
                "SELECT p.*, d.name AS dept_name FROM programs p "
                "JOIN departments d ON d.id = p.department_id "
                "WHERE p.department_id=%s ORDER BY p.id", (department_id,))
        else:
            self.cursor.execute(
                "SELECT p.*, d.name AS dept_name FROM programs p "
                "JOIN departments d ON d.id = p.department_id "
                "ORDER BY p.id")
        return self.cursor.fetchall()

    def get_program(self, pid):
        self.cursor.execute(
            "SELECT p.*, d.name AS dept_name FROM programs p "
            "JOIN departments d ON d.id = p.department_id "
            "WHERE p.id=%s", (pid,))
        return self.cursor.fetchone()

    def update_program(self, pid, name=None, department_id=None):
        prog = self.get_program(pid)
        if not prog:
            raise ValidationError(f"Ngành '{pid}' không tồn tại.")
        parts, params = [], []
        if name is not None:
            if not str(name).strip():
                raise ValidationError("Tên ngành không được để trống.")
            parts.append("name=%s"); params.append(str(name).strip())
        if department_id is not None:
            dept = self.get_department(department_id)
            if not dept:
                raise ValidationError(f"Khoa '{department_id}' không tồn tại.")
            parts.append("department_id=%s"); params.append(department_id)
        if not parts:
            return
        params.append(pid)
        self.cursor.execute(
            f"UPDATE programs SET {', '.join(parts)} WHERE id=%s",
            tuple(params))
        self.conn.commit()

    def add_admission_batch(self, bid, name, year):
        if not name or not str(name).strip():
            raise ValidationError("Tên khóa không được để trống.")
        try:
            yr = int(year)
            if yr <= 1900 or yr > 2100:
                raise ValueError()
        except ValueError:
            raise ValidationError("Năm tuyển sinh không hợp lệ.")
        self.cursor.execute(
            "INSERT INTO admission_batches (id, name, year) "
            "VALUES (%s, %s, %s)", (bid, name, yr))
        self.conn.commit()

    def list_admission_batches(self):
        self.cursor.execute(
            "SELECT * FROM admission_batches ORDER BY year DESC, id")
        return self.cursor.fetchall()

    def get_admission_batch(self, bid):
        self.cursor.execute(
            "SELECT * FROM admission_batches WHERE id=%s", (bid,))
        return self.cursor.fetchone()

    def update_admission_batch(self, bid, name=None, year=None):
        batch = self.get_admission_batch(bid)
        if not batch:
            raise ValidationError(f"Khóa tuyển sinh '{bid}' không tồn tại.")
        parts, params = [], []
        if name is not None:
            if not str(name).strip():
                raise ValidationError("Tên khóa không được để trống.")
            parts.append("name=%s"); params.append(str(name).strip())
        if year is not None:
            try:
                yr = int(year)
                if yr <= 1900 or yr > 2100:
                    raise ValueError()
            except ValueError:
                raise ValidationError("Năm tuyển sinh không hợp lệ.")
            parts.append("year=%s"); params.append(yr)
        if not parts:
            return
        params.append(bid)
        self.cursor.execute(
            f"UPDATE admission_batches SET {', '.join(parts)} WHERE id=%s",
            tuple(params))
        self.conn.commit()

    def add_admin_class(self, cid, name, program_id, batch_id):
        if not name or not str(name).strip():
            raise ValidationError("Tên lớp không được để trống.")
        prog = self.get_program(program_id)
        if not prog:
            raise ValidationError(f"Ngành '{program_id}' không tồn tại.")
        batch = self.get_admission_batch(batch_id)
        if not batch:
            raise ValidationError(f"Khóa '{batch_id}' không tồn tại.")
        self.cursor.execute(
            "INSERT INTO admin_classes (id, name, program_id, batch_id) "
            "VALUES (%s, %s, %s, %s)", (cid, name, program_id, batch_id))
        self.conn.commit()

    def list_admin_classes(self):
        self.cursor.execute("""
            SELECT ac.*, p.name AS program_name, p.department_id, ab.name AS batch_name
            FROM admin_classes ac
            LEFT JOIN programs p ON p.id = ac.program_id
            LEFT JOIN admission_batches ab ON ab.id = ac.batch_id
            ORDER BY ac.id
        """)
        return self.cursor.fetchall()

    def get_admin_class(self, cid):
        self.cursor.execute("""
            SELECT ac.*, p.name AS program_name, ab.name AS batch_name
            FROM admin_classes ac
            LEFT JOIN programs p ON p.id = ac.program_id
            LEFT JOIN admission_batches ab ON ab.id = ac.batch_id
            WHERE ac.id=%s
        """, (cid,))
        return self.cursor.fetchone()

    def update_admin_class(self, cid, name=None, program_id=None, batch_id=None):
        ac = self.get_admin_class(cid)
        if not ac:
            raise ValidationError(f"Lớp hành chính '{cid}' không tồn tại.")
        parts, params = [], []
        if name is not None:
            if not str(name).strip():
                raise ValidationError("Tên lớp không được để trống.")
            parts.append("name=%s"); params.append(str(name).strip())
        if program_id is not None:
            prog = self.get_program(program_id)
            if not prog:
                raise ValidationError(f"Ngành '{program_id}' không tồn tại.")
            parts.append("program_id=%s"); params.append(program_id)
        if batch_id is not None:
            batch = self.get_admission_batch(batch_id)
            if not batch:
                raise ValidationError(f"Khóa '{batch_id}' không tồn tại.")
            parts.append("batch_id=%s"); params.append(batch_id)
        if not parts:
            return
        params.append(cid)
        self.cursor.execute(
            f"UPDATE admin_classes SET {', '.join(parts)} WHERE id=%s",
            tuple(params))
        self.conn.commit()

    # ── Class Section CRUD ───────────────────────────────────────────────

    def get_section(self, section_id):
        self.cursor.execute("""
            SELECT cs.*, sub.name AS subject_name, sub.credits AS subject_credits,
                   sem.name AS semester_name, ay.name AS year_name
            FROM class_sections cs
            JOIN subjects sub ON sub.id = cs.subject_id
            JOIN semesters sem ON sem.id = cs.semester_id
            JOIN academic_years ay ON ay.id = sem.academic_year_id
            WHERE cs.id=%s
        """, (section_id,))
        return self.cursor.fetchone()

    def list_sections(self, semester_id=None, lecturer=None, subject_id=None):
        conditions, params = [], []
        if semester_id:
            conditions.append("cs.semester_id=%s"); params.append(semester_id)
        if lecturer:
            conditions.append("cs.lecturer=%s"); params.append(lecturer)
        if subject_id:
            conditions.append("cs.subject_id=%s"); params.append(subject_id)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        self.cursor.execute(f"""
            SELECT cs.*, sub.name AS subject_name, sub.credits AS subject_credits,
                   sem.name AS semester_name, ay.name AS year_name
            FROM class_sections cs
            JOIN subjects sub ON sub.id = cs.subject_id
            JOIN semesters sem ON sem.id = cs.semester_id
            JOIN academic_years ay ON ay.id = sem.academic_year_id
            {where}
            ORDER BY cs.semester_id, cs.id
        """, tuple(params))
        return self.cursor.fetchall()

    def get_section_schedules(self, section_id):
        self.cursor.execute(
            "SELECT * FROM section_schedules WHERE section_id=%s "
            "ORDER BY weekday, start_minutes", (section_id,))
        return self.cursor.fetchall()

    def count_section_enrollments(self, section_id):
        self.cursor.execute(
            "SELECT COUNT(*) AS cnt FROM enrollments WHERE section_id=%s",
            (section_id,))
        return self.cursor.fetchone()['cnt']

    # ── Enrollment queries ───────────────────────────────────────────────

    def get_enrollments(self, mssv, semester_id=None):
        """Return list of section_ids the student is enrolled in."""
        if semester_id:
            self.cursor.execute("""
                SELECT e.section_id FROM enrollments e
                JOIN class_sections cs ON cs.id = e.section_id
                WHERE e.mssv=%s AND cs.semester_id=%s
            """, (mssv, semester_id))
        else:
            self.cursor.execute(
                "SELECT section_id FROM enrollments WHERE mssv=%s", (mssv,))
        return [r['section_id'] for r in self.cursor.fetchall()]

    def get_enrollment_details(self, mssv, semester_id=None):
        """Return full enrollment details with subject/section info."""
        conditions = ["e.mssv=%s"]
        params = [mssv]
        if semester_id:
            conditions.append("cs.semester_id=%s")
            params.append(semester_id)
        where = " AND ".join(conditions)
        self.cursor.execute(f"""
            SELECT e.*, cs.subject_id, cs.semester_id, cs.lecturer,
                   cs.credits_snapshot, cs.tuition_per_credit,
                   sub.name AS subject_name,
                   sem.name AS semester_name, ay.name AS year_name
            FROM enrollments e
            JOIN class_sections cs ON cs.id = e.section_id
            JOIN subjects sub ON sub.id = cs.subject_id
            JOIN semesters sem ON sem.id = cs.semester_id
            JOIN academic_years ay ON ay.id = sem.academic_year_id
            WHERE {where}
            ORDER BY cs.semester_id, cs.subject_id
        """, tuple(params))
        return self.cursor.fetchall()

    # ── Grade queries ────────────────────────────────────────────────────

    def get_grades(self, mssv, semester_id=None):
        """Return grades with full section/subject context."""
        conditions = ["e.mssv=%s"]
        params = [mssv]
        if semester_id:
            conditions.append("cs.semester_id=%s")
            params.append(semester_id)
        where = " AND ".join(conditions)
        self.cursor.execute(f"""
            SELECT g.*, e.section_id, e.mssv, cs.subject_id,
                   cs.semester_id, cs.credits_snapshot,
                   sub.name AS subject_name,
                   sem.name AS semester_name, ay.name AS year_name
            FROM grades g
            JOIN enrollments e ON e.id = g.enrollment_id
            JOIN class_sections cs ON cs.id = e.section_id
            JOIN subjects sub ON sub.id = cs.subject_id
            JOIN semesters sem ON sem.id = cs.semester_id
            JOIN academic_years ay ON ay.id = sem.academic_year_id
            WHERE {where}
            ORDER BY cs.semester_id, cs.subject_id
        """, tuple(params))
        return self.cursor.fetchall()

    def get_section_students_with_grades(self, section_id):
        """Return enrolled students with grades for a specific section."""
        self.cursor.execute("""
            SELECT e.id AS enrollment_id, e.mssv, s.name AS student_name,
                   g.midterm, g.final_score
            FROM enrollments e
            JOIN students s ON s.mssv = e.mssv
            LEFT JOIN grades g ON g.enrollment_id = e.id
            WHERE e.section_id=%s
            ORDER BY e.mssv
        """, (section_id,))
        return self.cursor.fetchall()

    # ── Payment queries ──────────────────────────────────────────────────

    def list_payments(self, mssv, semester_id=None):
        conditions = ["e.mssv=%s"]
        params = [mssv]
        if semester_id:
            conditions.append("cs.semester_id=%s")
            params.append(semester_id)
        where = " AND ".join(conditions)
        self.cursor.execute(f"""
            SELECT p.*, e.section_id, e.mssv,
                   cs.subject_id, sub.name AS subject_name,
                   sem.name AS semester_name, ay.name AS year_name,
                   cs.credits_snapshot, cs.tuition_per_credit
            FROM payments p
            JOIN enrollments e ON e.id = p.enrollment_id
            JOIN class_sections cs ON cs.id = e.section_id
            JOIN subjects sub ON sub.id = cs.subject_id
            JOIN semesters sem ON sem.id = cs.semester_id
            JOIN academic_years ay ON ay.id = sem.academic_year_id
            WHERE {where}
            ORDER BY p.time DESC
        """, tuple(params))
        return self.cursor.fetchall()

    # ── Dashboard counts ─────────────────────────────────────────────────

    def count_lecturers(self):
        self.cursor.execute("SELECT COUNT(*) AS cnt FROM lecturers")
        return self.cursor.fetchone()['cnt']

    def count_all_enrollments(self):
        self.cursor.execute("SELECT COUNT(*) AS cnt FROM enrollments")
        return self.cursor.fetchone()['cnt']

    def count_students_of_lecturer(self, username):
        self.cursor.execute("""
            SELECT COUNT(*) AS cnt FROM enrollments e
            JOIN class_sections cs ON cs.id = e.section_id
            WHERE cs.lecturer=%s
        """, (username,))
        return self.cursor.fetchone()['cnt']
