"""Run this once to initialize the database."""
from models import init_db

if __name__ == "__main__":
    init_db()
    print("Database initialized. Accounts:")
    print("  老师: teacher / 123456")
    print("  学生: student01 ~ student10 / 123456")
