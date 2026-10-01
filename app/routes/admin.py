from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app
)

from flask_login import (
    current_user,
    login_required
)

from supabase import create_client

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


# ---------------------------------------------------------
# ADDITION: Delete user's videos from Supabase Storage
# ---------------------------------------------------------

def delete_user_videos(storage_paths):

    if not storage_paths:
        return

    supabase_url = current_app.config.get(
        "SUPABASE_URL"
    )

    service_role_key = current_app.config.get(
        "SUPABASE_SERVICE_ROLE_KEY"
    )

    bucket = current_app.config.get(
        "SUPABASE_STORAGE_BUCKET"
    )

    if not supabase_url:
        raise RuntimeError(
            "SUPABASE_URL is not configured."
        )

    if not service_role_key:
        raise RuntimeError(
            "SUPABASE_SERVICE_ROLE_KEY is not configured."
        )

    if not bucket:
        raise RuntimeError(
            "SUPABASE_STORAGE_BUCKET is not configured."
        )

    supabase = create_client(
        supabase_url,
        service_role_key
    )

    paths = list(
        dict.fromkeys(
            path.strip()
            for path in storage_paths
            if isinstance(path, str)
            and path.strip()
        )
    )

    # Supabase Storage supports batches.
    for start in range(
        0,
        len(paths),
        1000
    ):

        batch = paths[
            start:start + 1000
        ]

        supabase.storage.from_(
            bucket
        ).remove(batch)


# ---------------------------------------------------------
# ADDITION: Permanently delete user and all related data
# ---------------------------------------------------------

@adminpanel_bp.route(
    "/user/<int:user_id>/delete",
    methods=["POST"]
)
@login_required
def delete_user(user_id):

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

    username = user.username

    try:

        # Get all generation jobs BEFORE deleting them.
        generation_jobs = GenerationJob.query.filter_by(
            user_id=user_id
        ).all()

        # Collect stored video paths.
        storage_paths = [
            job.video_storage_path
            for job in generation_jobs
            if job.video_storage_path
        ]

        # Delete physical video files from Supabase Storage.
        delete_user_videos(
            storage_paths
        )

        # Remove scheduled APScheduler jobs.
        schedules = Schedule.query.filter_by(
            user_id=user_id
        ).all()

        for schedule in schedules:

            try:

                from app.scheduler import remove_schedule_job

                remove_schedule_job(
                    schedule.id
                )

            except Exception:
                pass

        # Delete GenerationJob records.
        GenerationJob.query.filter_by(
            user_id=user_id
        ).delete(
            synchronize_session=False
        )

        # Delete Schedule records.
        Schedule.query.filter_by(
            user_id=user_id
        ).delete(
            synchronize_session=False
        )

        # Delete Kaggle accounts.
        KaggleAccount.query.filter_by(
            user_id=user_id
        ).delete(
            synchronize_session=False
        )

        # Delete Platform accounts.
        PlatformCredential.query.filter_by(
            user_id=user_id
        ).delete(
            synchronize_session=False
        )

        # Finally delete the user.
        db.session.delete(
            user
        )

        db.session.commit()

    except Exception as exc:

        db.session.rollback()

        current_app.logger.exception(
            "Failed to permanently delete user %s",
            user_id
        )

        flash(
            "User deletion failed. Database changes were rolled back.",
            "error"
        )

        return redirect(
            url_for("admin.adminpanel")
        )

    flash(
        f"User '{username}' and all associated data have been permanently deleted.",
        "success"
    )

    return redirect(
        url_for("admin.adminpanel")
    )
