from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from models import db, User, Category, Issue   # replace your existing models import
import os
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"  # we'll add this route in step 3


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/")
def home():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if not name or not email or len(password) < 6:
            flash("Fill all fields. Password must be at least 6 characters.", "error")
        elif User.query.filter_by(email=email).first():
            flash("That email is already registered.", "error")
        else:
            user = User(name=name, email=email,
                        password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            flash("Account created. Please log in.", "success")
            return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("home"))
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            if user.role == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("home"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/report", methods=["GET", "POST"])
@login_required
def report_issue():
    categories = Category.query.order_by(Category.name).all()

    if request.method == "POST":
        title = request.form["title"].strip()
        description = request.form["description"].strip()
        location = request.form["location"].strip()
        category_id = request.form.get("category_id")
        file = request.files.get("image")

        if not title or not description or not location or not category_id:
            flash("Please fill in all required fields.", "error")
            return render_template("report.html", categories=categories)

        image_name = None
        if file and file.filename:
            if not allowed_file(file.filename):
                flash("Only png, jpg, jpeg, gif or webp images are allowed.", "error")
                return render_template("report.html", categories=categories)
            ext = file.filename.rsplit(".", 1)[1].lower()
            image_name = f"{uuid.uuid4().hex}.{ext}"
            os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], image_name))

        issue = Issue(
            title=title,
            description=description,
            location=location,
            category_id=int(category_id),
            image_path=image_name,
            user_id=current_user.id,
        )
        db.session.add(issue)
        db.session.commit()
        flash("Issue reported successfully.", "success")
        return redirect(url_for("my_reports"))

    return render_template("report.html", categories=categories)

@app.route("/my-reports")
@login_required
def my_reports():
    issues = (Issue.query
              .filter_by(user_id=current_user.id)
              .order_by(Issue.created_at.desc())
              .all())
    return render_template("my_reports.html", issues=issues)

def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.role != "admin":
            abort(403)
        return f(*args, **kwargs)
    return wrapper


VALID_STATUSES = ["Pending", "In Progress", "Resolved"]


@app.route("/admin")
@admin_required
def admin_dashboard():
    status = request.args.get("status", "")
    category_id = request.args.get("category_id", "")

    query = Issue.query
    if status in VALID_STATUSES:
        query = query.filter_by(status=status)
    if category_id.isdigit():
        query = query.filter_by(category_id=int(category_id))

    issues = query.order_by(Issue.created_at.desc()).all()
    categories = Category.query.order_by(Category.name).all()
    counts = {s: Issue.query.filter_by(status=s).count() for s in VALID_STATUSES}

    return render_template(
        "admin.html",
        issues=issues,
        categories=categories,
        statuses=VALID_STATUSES,
        counts=counts,
        selected_status=status,
        selected_category=category_id,
    )


@app.route("/admin/update/<int:issue_id>", methods=["POST"])
@admin_required
def update_status(issue_id):
    issue = db.session.get(Issue, issue_id)
    if not issue:
        abort(404)
    new_status = request.form.get("status")
    if new_status in VALID_STATUSES:
        issue.status = new_status
        db.session.commit()
        flash(f"Issue #{issue.id} marked as {new_status}.", "success")
    return redirect(request.referrer or url_for("admin_dashboard"))
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403,
                           message="You don't have permission to view this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404,
                           message="That page doesn't exist."), 404


@app.errorhandler(413)
def too_large(e):
    flash("That file is too large. Maximum size is 2 MB.", "error")
    return redirect(url_for("report_issue"))

def seed_data():
    """Add default categories and an admin account if the DB is empty."""
    if Category.query.count() == 0:
        for name in ["Electricity", "Water", "Wi-Fi", "Hostel", "Classroom", "Roads", "Other"]:
            db.session.add(Category(name=name))
    if not User.query.filter_by(email="admin@campusfix.com").first():
        db.session.add(User(
            name="Admin",
            email="admin@campusfix.com",
            password_hash=generate_password_hash("Myadmin@69"),
            role="admin",
        ))
    db.session.commit()


with app.app_context():
    db.create_all()
    seed_data()


if __name__ == "__main__":
    app.run(debug=False)