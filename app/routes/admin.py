from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash
)

from flask_login import (
    current_user,
    login_required
)

from app import db

from app.models import (
    Admin,
    User,
    GenerationJob,
    Schedule,
    KaggleAccount,
    PlatformCredential,
    utcnow
)


adminpanel_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin"
)


@adminpanel_bp.route("/")
@login_required
def adminpanel():

    if not isinstance(current_user, Admin):
        return "Access denied", 403

    total_users = User.query.count()
    total_jobs = GenerationJob.query.count()
    total_schedules = Schedule.query.count()
    total_kaggle_accounts = KaggleAccount.query.count()
    total_platform_accounts = PlatformCredential.query.count()

    users = User.query.order_by(
        User.created_at.desc()
    ).all()

    return render_template(
        "adminpanel.html",
        total_users=total_users,
        total_jobs=total_jobs,
        total_schedules=total_schedules,
        total_kaggle_accounts=total_kaggle_accounts,
        total_platform_accounts=total_platform_accounts,
        users=users
    )


@adminpanel_bp.route(
    "/user/<int:user_id>/suspend",
    methods=["POST"]
)
@login_required
def suspend_user(user_id):

    if not isinstance(current_user, Admin):
        return "Access denied", 403

    user = db.session.get(
        User,
        user_id
    )

    if not user:
        flash(
            "User not found.",
            "error"
        )

        return redirect(
            url_for("admin.adminpanel")
        )

    reason = (
        request.form.get("reason") or ""
    ).strip()

    user.status = "suspended"

    user.suspension_reason = (
        reason or "Suspended by administrator"
    )

    user.suspended_at = utcnow()

    db.session.commit()

    flash(
        f"User '{user.username}' has been suspended.",
        "success"
    )

    return redirect(
        url_for("admin.adminpanel")
    )


@adminpanel_bp.route(
    "/user/<int:user_id>/unsuspend",
    methods=["POST"]
)
@login_required
def unsuspend_user(user_id):

    if not isinstance(current_user, Admin):
        return "Access denied", 403

    user = db.session.get(
        User,
        user_id
    )

    if not user:
        flash(
            "User not found.",
            "error"
        )

        return redirect(
            url_for("admin.adminpanel")
        )

    user.status = "active"
    user.suspension_reason = None
    user.suspended_at = None

    db.session.commit()

    flash(
        f"User '{user.username}' has been unsuspended.",
        "success"
    )

    return redirect(
        url_for("admin.adminpanel")
    )
