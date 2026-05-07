"""实训作业提交+批改系统"""

import os
import re
from datetime import datetime
from functools import wraps

from flask import Flask, g, jsonify, redirect, render_template, request, send_file, session, url_for

from models import get_db, init_db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "zuoye-system-secret-key-2026")
TEACHER_SECRET_CODE = os.environ.get("TEACHER_CODE", "zuoye2026")  # 只有老师知道的注册密钥

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ── Global template variables ───────────────────────────────────────────────

@app.context_processor
def inject_globals():
    return {
        "now": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "all_classes": get_db().execute(
            "SELECT c.*, u.realname as homeroom_name FROM classes c LEFT JOIN users u ON c.homeroom_teacher_id=u.id ORDER BY c.id"
        ).fetchall(),
    }

# ── Auth helpers ────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def teacher_only(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "teacher":
            return "老师才能访问", 403
        return f(*args, **kwargs)
    return decorated


def get_teacher_class_ids():
    """返回当前班主任管理的所有班级ID列表"""
    db = get_db()
    rows = db.execute(
        "SELECT id FROM classes WHERE homeroom_teacher_id=?", (session["user_id"],)
    ).fetchall()
    return [r["id"] for r in rows]


def homeroom_only(f):
    """确保当前老师是班主任，且只能操作自己班级"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("role") != "teacher":
            return "老师才能访问", 403
        class_ids = get_teacher_class_ids()
        if not class_ids:
            return "你不是任何班级的班主任，无法进行此操作", 403
        return f(*args, **kwargs)
    return decorated


def current_user():
    if "user_id" not in session:
        return None
    db = get_db()
    return db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()


# ── Login ───────────────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (request.form["username"], request.form["password"])
        ).fetchone()
        if user:
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            session["realname"] = user["realname"]
            return redirect("/teacher/home" if user["role"] == "teacher" else "/student/home")
        error = "账号或密码错误"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ── Teacher Routes ──────────────────────────────────────────────────────────

@app.route("/teacher/home")
@login_required
@teacher_only
def teacher_home():
    db = get_db()
    user = current_user()
    class_ids = get_teacher_class_ids()
    assignments = []
    if class_ids:
        placeholders = ",".join("?" * len(class_ids))
        assignments = db.execute(
            f"""SELECT a.*, c.name as class_name,
               (SELECT COUNT(*) FROM submissions WHERE assignment_id=a.id) as submitted_count,
               (SELECT COUNT(*) FROM users WHERE class_id=a.class_id AND role='student') as total_students
               FROM assignments a JOIN classes c ON a.class_id=c.id
               WHERE a.teacher_id=? AND a.class_id IN ({placeholders})
               ORDER BY a.created_at DESC""",
            (user["id"], *class_ids)
        ).fetchall()
    return render_template("teacher_home.html", user=user, assignments=assignments)


@app.route("/teacher/assignment/create", methods=["GET", "POST"])
@login_required
@teacher_only
def create_assignment():
    db = get_db()
    user = current_user()
    class_ids = get_teacher_class_ids()

    if request.method == "POST":
        selected_class = request.form["class_id"]
        if int(selected_class) not in class_ids:
            return "只能给自己管理的班级发布作业", 403

        # Handle file upload (Word, text, etc.)
        file_path = ""
        uploaded = request.files.get("assignment_file")
        if uploaded and uploaded.filename:
            filename = f"assignment_{user['id']}_{uploaded.filename}"
            uploaded.save(os.path.join(UPLOAD_DIR, filename))
            file_path = filename

        db.execute(
            "INSERT INTO assignments (title, description, teacher_id, class_id, deadline, file_path) VALUES (?,?,?,?,?,?)",
            (request.form["title"], request.form["description"], user["id"],
             selected_class, request.form["deadline"], file_path)
        )
        db.commit()
        return redirect("/teacher/home")

    if class_ids:
        placeholders = ",".join("?" * len(class_ids))
        classes = db.execute(
            f"SELECT * FROM classes WHERE id IN ({placeholders})", class_ids
        ).fetchall()
    else:
        classes = []
    return render_template("create_assignment.html", user=user, classes=classes)


# ── Teacher: Class Management ───────────────────────────────────────────────

@app.route("/teacher/classes")
@login_required
@teacher_only
def teacher_classes():
    db = get_db()
    user = current_user()
    class_ids = get_teacher_class_ids()
    if class_ids:
        placeholders = ",".join("?" * len(class_ids))
        classes = db.execute(
            f"""SELECT c.*, u.realname as homeroom_name,
               (SELECT COUNT(*) FROM users WHERE class_id=c.id AND role='student') as student_count
               FROM classes c LEFT JOIN users u ON c.homeroom_teacher_id=u.id
               WHERE c.id IN ({placeholders})
               ORDER BY c.id""",
            class_ids
        ).fetchall()
    else:
        classes = []
    teachers = db.execute(
        "SELECT * FROM users WHERE role='teacher' ORDER BY realname"
    ).fetchall()
    return render_template("teacher_classes.html", user=user, classes=classes, teachers=teachers)


@app.route("/teacher/classes/create", methods=["POST"])
@login_required
@teacher_only
def create_class():
    db = get_db()
    user = current_user()
    name = request.form["name"].strip()

    if not name:
        return redirect("/teacher/classes")

    db.execute(
        "INSERT INTO classes (name, homeroom_teacher_id) VALUES (?,?)",
        (name, user["id"])
    )
    db.commit()
    return redirect("/teacher/classes")


@app.route("/teacher/classes/delete/<int:class_id>", methods=["POST"])
@login_required
@teacher_only
def delete_class(class_id):
    db = get_db()
    # Only allow deleting if teacher is the homeroom teacher
    if class_id not in get_teacher_class_ids():
        return "只能删除自己管理的班级", 403
    # Only delete if no students are in it
    student_count = db.execute(
        "SELECT COUNT(*) FROM users WHERE class_id=? AND role='student'",
        (class_id,)
    ).fetchone()[0]
    if student_count == 0:
        db.execute("DELETE FROM classes WHERE id=?", (class_id,))
        db.commit()
    return redirect("/teacher/classes")


@app.route("/teacher/grade/<int:assignment_id>")
@login_required
@teacher_only
def grade_list(assignment_id):
    db = get_db()
    user = current_user()
    assignment = db.execute(
        "SELECT a.*, c.name as class_name FROM assignments a JOIN classes c ON a.class_id=c.id WHERE a.id=?",
        (assignment_id,)
    ).fetchone()

    if assignment is None or assignment["class_id"] not in get_teacher_class_ids():
        return "只能批改自己班级的作业", 403

    students = db.execute(
        "SELECT * FROM users WHERE class_id=? AND role='student' ORDER BY username",
        (assignment["class_id"],)
    ).fetchall()

    results = []
    for s in students:
        sub = db.execute(
            "SELECT * FROM submissions WHERE assignment_id=? AND student_id=?",
            (assignment_id, s["id"])
        ).fetchone()
        results.append({
            "student": s,
            "submission": sub,
            "submitted": sub is not None,
        })

    return render_template("grade_list.html", user=user, assignment=assignment, results=results)


@app.route("/teacher/grade/<int:submission_id>/save", methods=["POST"])
@login_required
@teacher_only
def grade_save(submission_id):
    db = get_db()
    # Verify this submission belongs to the teacher's class
    sub = db.execute(
        "SELECT a.class_id FROM submissions s JOIN assignments a ON s.assignment_id=a.id WHERE s.id=?",
        (submission_id,)
    ).fetchone()
    if sub is None or sub["class_id"] not in get_teacher_class_ids():
        return jsonify({"ok": False, "error": "只能批改自己班级的作业"}), 403

    grade = int(request.form.get("grade", 0))
    feedback = request.form.get("feedback", "")
    db.execute(
        "UPDATE submissions SET grade=?, feedback=?, graded_at=? WHERE id=?",
        (grade, feedback, datetime.now().strftime("%Y-%m-%d %H:%M"), submission_id)
    )
    db.commit()
    return jsonify({"ok": True})


@app.route("/teacher/stats/<int:assignment_id>")
@login_required
@teacher_only
def stats(assignment_id):
    db = get_db()
    assignment = db.execute(
        "SELECT a.*, c.name as class_name FROM assignments a JOIN classes c ON a.class_id=c.id WHERE a.id=?",
        (assignment_id,)
    ).fetchone()

    if assignment is None or assignment["class_id"] not in get_teacher_class_ids():
        return "只能查看自己班级的统计", 403

    total_students = db.execute(
        "SELECT COUNT(*) FROM users WHERE class_id=? AND role='student'",
        (assignment["class_id"],)
    ).fetchone()[0]

    subs = db.execute(
        "SELECT s.*, u.realname FROM submissions s JOIN users u ON s.student_id=u.id WHERE s.assignment_id=?",
        (assignment_id,)
    ).fetchall()

    grades = [s["grade"] for s in subs if s["grade"] is not None]
    stats_data = {
        "total": total_students,
        "submitted": len(subs),
        "not_submitted": total_students - len(subs),
        "avg": round(sum(grades) / len(grades), 1) if grades else 0,
        "max_grade": max(grades) if grades else 0,
        "min_grade": min(grades) if grades else 0,
        "pass_rate": round(len([g for g in grades if g >= 60]) / len(grades) * 100, 1) if grades else 0,
        "excellent": len([g for g in grades if g >= 90]),
        "good": len([g for g in grades if 80 <= g < 90]),
        "fair": len([g for g in grades if 60 <= g < 80]),
        "fail": len([g for g in grades if g < 60]),
        "distribution": [
            len([g for g in grades if g >= 90]),
            len([g for g in grades if 80 <= g < 90]),
            len([g for g in grades if 70 <= g < 80]),
            len([g for g in grades if 60 <= g < 70]),
            len([g for g in grades if g < 60]),
        ],
    }
    return render_template("stats.html", user=current_user(), assignment=assignment,
                         stats=stats_data, subs=subs)


@app.route("/teacher/export/<int:assignment_id>")
@login_required
@teacher_only
def export_excel(assignment_id):
    import openpyxl
    from io import BytesIO

    db = get_db()
    assignment = db.execute("SELECT * FROM assignments WHERE id=?", (assignment_id,)).fetchone()

    if assignment is None or assignment["class_id"] not in get_teacher_class_ids():
        return "只能导出自己班级的成绩", 403

    students = db.execute(
        "SELECT * FROM users WHERE class_id=? AND role='student' ORDER BY username",
        (assignment["class_id"],)
    ).fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = assignment["title"][:31]
    ws.append(["学号", "姓名", "是否提交", "提交时间", "分数", "评语", "状态"])

    for s in students:
        sub = db.execute(
            "SELECT * FROM submissions WHERE assignment_id=? AND student_id=?",
            (assignment_id, s["id"])
        ).fetchone()

        if sub:
            status = "已批改" if sub["grade"] is not None else "待批改"
            ws.append([s["username"], s["realname"], "已提交", sub["submitted_at"],
                       sub["grade"] if sub["grade"] is not None else "-",
                       sub["feedback"] or "", status])
        else:
            ws.append([s["username"], s["realname"], "未提交", "-", "-", "-", "缺交"])

    # Adjust column widths
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = 15

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    filename = f"{assignment['title']}_成绩.xlsx"
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name=filename)


# ── Student Routes ──────────────────────────────────────────────────────────

@app.route("/student/home")
@login_required
def student_home():
    if session.get("role") != "student":
        return redirect("/teacher/home")
    db = get_db()
    user = current_user()

    # Refresh user data (class might have changed)
    user = db.execute("SELECT u.*, c.name as class_name FROM users u LEFT JOIN classes c ON u.class_id=c.id WHERE u.id=?", (session["user_id"],)).fetchone()

    assignments = db.execute(
        """SELECT a.*, u.realname as teacher_name,
           (SELECT COUNT(*) FROM submissions WHERE assignment_id=a.id AND student_id=?) as submitted,
           (SELECT grade FROM submissions WHERE assignment_id=a.id AND student_id=?) as grade,
           (SELECT feedback FROM submissions WHERE assignment_id=a.id AND student_id=?) as feedback
           FROM assignments a JOIN users u ON a.teacher_id=u.id
           WHERE a.class_id=? OR a.class_id IS NULL
           ORDER BY a.deadline ASC""",
        (user["id"], user["id"], user["id"], user["class_id"])
    ).fetchall()

    return render_template("student_home.html", user=user, assignments=assignments)


@app.route("/register", methods=["GET", "POST"])
def register():
    """Student and Teacher self-registration."""
    db = get_db()
    error = ""

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        realname = request.form.get("realname", "").strip()
        role = request.form.get("role", "").strip()
        class_id = request.form.get("class_id", "").strip()
        class_name = request.form.get("class_name", "").strip()

        teacher_code = request.form.get("teacher_code", "").strip()

        # Validate
        if not username or not password or not realname or role not in ("teacher", "student"):
            error = "所有字段都必须填写"
        elif not re.match(r"^[a-zA-Z0-9_]{3,20}$", username):
            error = "账号只能包含字母、数字、下划线，3-20位"
        elif len(password) < 4:
            error = "密码至少4位"
        elif role == "student" and not class_id:
            error = "请选择要加入的班级"
        elif role == "teacher" and teacher_code != TEACHER_SECRET_CODE:
            error = "老师注册密钥错误，无法注册为老师"
        elif role == "teacher" and not class_name:
            error = "请填写班级名称"
        else:
            existing = db.execute(
                "SELECT id FROM users WHERE username=?", (username,)
            ).fetchone()
            if existing:
                error = "账号已被占用，换一个"
            else:
                if role == "teacher":
                    # Create teacher account
                    db.execute(
                        "INSERT INTO users (username, password, realname, role) VALUES (?,?,?, 'teacher')",
                        (username, password, realname)
                    )
                    teacher_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                    # Create class with this teacher as homeroom
                    db.execute(
                        "INSERT INTO classes (name, homeroom_teacher_id) VALUES (?,?)",
                        (class_name, teacher_id)
                    )
                    db.commit()
                    session["user_id"] = teacher_id
                    session["role"] = "teacher"
                    session["realname"] = realname
                    return redirect("/teacher/home")
                else:
                    db.execute(
                        "INSERT INTO users (username, password, realname, role, class_id) VALUES (?,?,?, 'student',?)",
                        (username, password, realname, class_id)
                    )
                    db.commit()
                    user = db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
                    session["user_id"] = user["id"]
                    session["role"] = "student"
                    session["realname"] = user["realname"]
                    return redirect("/student/home")

    classes = db.execute(
        """SELECT c.*, u.realname as homeroom_name
           FROM classes c LEFT JOIN users u ON c.homeroom_teacher_id=u.id
           ORDER BY c.id"""
    ).fetchall()
    return render_template("register.html", error=error, classes=classes)


@app.route("/student/change-class", methods=["POST"])
@login_required
def change_class():
    """Student switches to a different class."""
    if session.get("role") != "student":
        return redirect("/")
    db = get_db()
    class_id = request.form.get("class_id")
    if class_id:
        db.execute(
            "UPDATE users SET class_id=? WHERE id=?",
            (class_id, session["user_id"])
        )
        db.commit()
    return redirect("/student/home")


@app.route("/student/submit/<int:assignment_id>", methods=["GET", "POST"])
@login_required
def submit(assignment_id):
    if session.get("role") != "student":
        return redirect("/teacher/home")
    db = get_db()
    user = current_user()
    assignment = db.execute(
        "SELECT a.*, u.realname as teacher_name FROM assignments a JOIN users u ON a.teacher_id=u.id WHERE a.id=?",
        (assignment_id,)
    ).fetchone()

    existing = db.execute(
        "SELECT * FROM submissions WHERE assignment_id=? AND student_id=?",
        (assignment_id, user["id"])
    ).fetchone()

    if request.method == "POST":
        content = request.form.get("content", "")

        # Handle file upload
        file_path = existing["file_path"] if existing else ""
        uploaded = request.files.get("file")
        if uploaded and uploaded.filename:
            if file_path:
                old_file = os.path.join(UPLOAD_DIR, file_path)
                if os.path.exists(old_file):
                    os.remove(old_file)
            filename = f"{user['username']}_{assignment_id}_{uploaded.filename}"
            uploaded.save(os.path.join(UPLOAD_DIR, filename))
            file_path = filename

        if existing:
            db.execute(
                "UPDATE submissions SET content=?, file_path=?, submitted_at=? WHERE id=?",
                (content, file_path, datetime.now().strftime("%Y-%m-%d %H:%M"), existing["id"])
            )
        else:
            db.execute(
                "INSERT INTO submissions (assignment_id, student_id, content, file_path) VALUES (?,?,?,?)",
                (assignment_id, user["id"], content, file_path)
            )
        db.commit()
        return redirect("/student/home")

    return render_template("student_home.html", user=user, assignment=assignment,
                         existing=existing, show_submit=True)


# ── Download submitted file ─────────────────────────────────────────────────

@app.route("/download/<path:filename>")
@login_required
def download_file(filename):
    filepath = os.path.join(UPLOAD_DIR, filename)
    if not os.path.exists(filepath):
        return "文件不存在", 404
    return send_file(filepath, as_attachment=True, download_name=filename.split("_", 2)[-1])


# ── Start ───────────────────────────────────────────────────────────────────

# Auto-init DB on import (for gunicorn) and on direct run
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("DEBUG", "").lower() == "true"

    if debug:
        print("\n  [开发模式] 作业提交批改系统启动!")
        print(f"  打开浏览器: http://127.0.0.1:{port}")
        print(f"  学生注册: http://127.0.0.1:{port}/register")
        print("  老师: teacher / 123456")
        print("  学生: student01~student10 / 123456\n")
        app.run(debug=True, host="127.0.0.1", port=port)
    else:
        from waitress import serve
        import socket
        hostname = socket.gethostname()
        ip = socket.gethostbyname(hostname)
        print(f"\n  [生产模式] 作业提交批改系统启动!")
        print(f"  本机访问: http://127.0.0.1:{port}")
        print(f"  局域网访问: http://{ip}:{port}")
        print(f"  学生注册: http://{ip}:{port}/register")
        print(f"  老师注册密钥: {TEACHER_SECRET_CODE}")
        print("  默认账号: teacher / 123456")
        print("  默认学生: student01~student10 / 123456")
        print("  按 Ctrl+C 停止服务\n")
        serve(app, host="0.0.0.0", port=port)
