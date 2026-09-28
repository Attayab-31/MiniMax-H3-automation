from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db, login_manager
from app.models import User

auth_bp = Blueprint("auth", __name__)


@login_manager.user_loader
def load_user(user_id: str):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if len(username) < 3 or len(username) > 80 or not username.replace("_", "").replace("-", "").isalnum():
            flash("Username must be 3–80 letters, numbers, underscores, or hyphens.", "error")
        elif len(password) < 12:
            flash("Use a password with at least 12 characters.", "error")
        elif User.query.filter(db.func.lower(User.username) == username.lower()).first():
            flash("That username is already taken.", "error")
        else:
            user = User(username=username, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Your account is ready. Add one or more Kaggle accounts in Settings.", "success")
            return redirect(url_for("settings.settings"))
    return render_template("login.html", signup=True)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter(db.func.lower(User.username) == username.lower()).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard.index"))
        flash("Invalid username or password.", "error")
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("login.html", signup=False)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
