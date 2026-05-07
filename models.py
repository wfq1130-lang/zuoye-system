"""SQLite database operations — no ORM, simple and direct."""

import sqlite3
from datetime import datetime

DB_PATH = "zuoye.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            homeroom_teacher_id INTEGER REFERENCES users(id),
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            realname TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('teacher', 'student')),
            class_id INTEGER REFERENCES classes(id)
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            teacher_id INTEGER NOT NULL REFERENCES users(id),
            class_id INTEGER NOT NULL REFERENCES classes(id),
            deadline TEXT NOT NULL,
            file_path TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id),
            student_id INTEGER NOT NULL REFERENCES users(id),
            content TEXT DEFAULT '',
            file_path TEXT DEFAULT '',
            submitted_at TEXT DEFAULT (datetime('now','localtime')),
            grade INTEGER,
            feedback TEXT DEFAULT '',
            graded_at TEXT,
            UNIQUE(assignment_id, student_id)
        );
    """)
    conn.commit()

    # Migration: add homeroom_teacher_id for existing DBs
    try:
        conn.execute("ALTER TABLE classes ADD COLUMN homeroom_teacher_id INTEGER REFERENCES users(id)")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Migration: add file_path for assignments
    try:
        conn.execute("ALTER TABLE assignments ADD COLUMN file_path TEXT DEFAULT ''")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    # Seed data if empty
    if not conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0]:
        _seed(conn)
    conn.close()


def _seed(conn):
    # Create teachers first
    conn.execute(
        "INSERT INTO users (username, password, realname, role) VALUES (?, ?, ?, 'teacher')",
        ("teacher", "123456", "刘老师")
    )
    conn.execute(
        "INSERT INTO users (username, password, realname, role) VALUES (?, ?, ?, 'teacher')",
        ("teacher2", "123456", "王老师")
    )

    # Create classes with homeroom teachers
    conn.execute(
        "INSERT INTO classes (name, homeroom_teacher_id) VALUES (?, 1)",
        ("软件技术2201班",)
    )
    conn.execute(
        "INSERT INTO classes (name, homeroom_teacher_id) VALUES (?, 2)",
        ("网络技术2202班",)
    )
    conn.execute(
        "INSERT INTO classes (name, homeroom_teacher_id) VALUES (?, 1)",
        ("人工智能2301班",)
    )

    # Students
    students = [
        ("student01", "123456", "王小明", 1),
        ("student02", "123456", "李小芳", 1),
        ("student03", "123456", "张大伟", 1),
        ("student04", "123456", "陈静怡", 1),
        ("student05", "123456", "赵子龙", 1),
        ("student06", "123456", "钱晓燕", 1),
        ("student07", "123456", "孙浩然", 2),
        ("student08", "123456", "周晓敏", 2),
        ("student09", "123456", "吴嘉豪", 2),
        ("student10", "123456", "郑雨晴", 2),
    ]
    for username, pwd, name, cid in students:
        conn.execute(
            "INSERT INTO users (username, password, realname, role, class_id) VALUES (?,?,?, 'student',?)",
            (username, pwd, name, cid)
        )

    # Sample assignment
    conn.execute(
        "INSERT INTO assignments (title, description, teacher_id, class_id, deadline) VALUES (?,?,1,1,?)",
        ("Python循环练习", "用for循环打印九九乘法表，并写注释说明每一步的作用。", "2026-05-15 23:59")
    )

    conn.commit()
