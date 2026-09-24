import os

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from app import login_manager


auth_bp = Blueprint("auth", __name__)


class AdminUser(UserMixin):
    def __init__(self, username: str):
        self.id = username

    @property
    def username(self) -> str:
        return self.id


@login_manager.user_loader
def load_user(user_id: str):
    expected_username = os.getenv("ADMIN_USERNAME", "admin")
    if user_id == expected_username:
        return AdminUser(user_id)
    return None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        expected_username = os.getenv("ADMIN_USERNAME", "")
        expected_password = os.getenv("ADMIN_PASSWORD", "")
        valid = bool(expected_username and expected_password) and username == expected_username and password == expected_password

        if valid:
            login_user(AdminUser(username))
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard.index"))

        flash("Invalid username or password.", "error")

    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    return render_template("login.html")


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
