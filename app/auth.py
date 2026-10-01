from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db, login_manager
from app.models import User, Admin
import os
from dotenv import load_dotenv

load_dotenv()


auth_bp = Blueprint("auth", __name__)


@login_manager.user_loader
def load_user(user_id: str):

    if not user_id:
        return None

    try:
        account_type, account_id = user_id.split(":", 1)
        account_id = int(account_id)
    except (ValueError, AttributeError):
        return None

    if account_type == "admin":
        return db.session.get(Admin, account_id)

    if account_type == "user":
        return db.session.get(User, account_id)

    return None
# endpoint addedby ahsan


@auth_bp.route("/admin/signup", methods=["GET", "POST"])
def admin_signup():

    # Only one admin is allowed
    admin_exists = Admin.query.first()

    if admin_exists:
        flash(
            "Admin signup is disabled because an admin account already exists.",
            "error"
        )
        return redirect(url_for("auth.login"))

    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        admin_code = request.form.get("admin_code") or ""

        # Check admin secret code
        if admin_code != os.getenv("ADMIN_CODE"):

            flash(
                "Invalid admin code.",
                "error"
            )

        elif (
            len(username) < 3
            or len(username) > 80
            or not username.replace("_", "").replace("-", "").isalnum()
        ):

            flash(
                "Username must be 3–80 letters, numbers, underscores, or hyphens.",
                "error"
            )

        elif len(password) < 12:

            flash(
                "Use a password with at least 12 characters.",
                "error"
            )

        elif Admin.query.filter(
            db.func.lower(Admin.username) == username.lower()
        ).first():

            flash(
                "That admin username is already taken.",
                "error"
            )

        else:

            admin = Admin(
                username=username,
                password_hash=generate_password_hash(password)
            )

            db.session.add(admin)
            db.session.commit()

            flash(
                "Admin account created successfully. Please login.",
                "success"
            )

            return redirect(
                url_for("auth.login")
            )

    return render_template(
        "admin_signup.html"
    )

# endpoint added by ahsan


@auth_bp.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""

        admin = Admin.query.filter(
            db.func.lower(Admin.username) == username.lower()
        ).first()

        user = User.query.filter(
            db.func.lower(User.username) == username.lower()
        ).first()

        # Admin login
        if admin and check_password_hash(
            admin.password_hash,
            password
        ):
            login_user(admin)

            flash(
                "Admin login successful.",
                "success"
            )

            return redirect(
                url_for("admin.adminpanel")
            )

        # User login
        if user and check_password_hash(
            user.password_hash,
            password
        ):

            if user.status == "suspended":

                flash(
                    "XXYouXr acX4couXXnt hXXas beXXen suXspXXXended. PlXXXXeaXse conXXXtacXt tXXXhe aXXdmiXXniXXstraXXtorXX.",
                    "error"
                )

                admin_exists = Admin.query.first() is not None

                return render_template(
                    "login.html",
                    signup=False,
                    admin_exists=admin_exists
                )

            login_user(user)

            flash(
                "User login successful.",
                "success"
            )

            return redirect(
                url_for("dashboard.index")
            )

        flash(
            "Invalid username or password.",
            "error"
        )

    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    admin_exists = Admin.query.first() is not None

    return render_template(
        "login.html",
        signup=False,
        admin_exists=admin_exists
    )


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if len(username) < 3 or len(username) > 80 or not username.replace("_", "").replace("-", "").isalnum():
            flash(
                "Username must be 3–80 letters, numbers, underscores, or hyphens.", "error")
        elif len(password) < 12:
            flash("Use a password with at least 12 characters.", "error")
        elif User.query.filter(db.func.lower(User.username) == username.lower()).first():
            flash("That username is already taken.", "error")
        else:
            user = User(username=username,
                        password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash(
                "Your account is ready. Add one or more Kaggle accounts in Settings.", "success")
            return redirect(url_for("settings.settings"))
    return render_template("login.html", signup=True)


"""@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = User.query.filter(db.func.lower(
            User.username) == username.lower()).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard.index"))
        flash("Invalid username or password.", "error")
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))
    return render_template("login.html", signup=False)
"""


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))
