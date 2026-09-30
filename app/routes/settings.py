import os
import re

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.kaggle_accounts import encrypt_api_key
from app.models import GenerationJob, KaggleAccount, PlatformCredential, Schedule
from app.scheduler import remove_schedule_job

settings_bp = Blueprint("settings", __name__)


@settings_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        label = (request.form.get("label") or "").strip()
        username = (request.form.get("username") or "").strip()
        api_key = (request.form.get("api_key") or "").strip()
        slug = (re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-") or "account")[:30]
        kernel_id = (request.form.get("kernel_id") or f"{username}/h3-automation-{slug}").strip()
        if not label or len(label) > 120 or not username or len(username) > 120 or not api_key:
            flash("Enter an account label, Kaggle username, and API key.", "error")
            return redirect(url_for("settings.settings"))
        if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_-]+", kernel_id) or kernel_id.split("/", 1)[0].lower() != username.lower():
            flash("Kernel ID must use this account's Kaggle username, such as username/h3-automation-work.", "error")
            return redirect(url_for("settings.settings"))
        env_kernel_id = (os.getenv("KAGGLE_KERNEL_ID") or "").strip()
        env_username = (os.getenv("KAGGLE_USERNAME") or "").strip()
        if env_username and username.lower() == env_username.lower():
            flash("This username already belongs to the environment account.", "error")
            return redirect(url_for("settings.settings"))
        if env_kernel_id and kernel_id.lower() == env_kernel_id.lower():
            flash("Use a unique kernel ID for each Kaggle account.", "error")
            return redirect(url_for("settings.settings"))
        try:
            encrypted_key = encrypt_api_key(api_key)
        except RuntimeError as exc:
            flash(str(exc), "error")
            return redirect(url_for("settings.settings"))
        if KaggleAccount.query.filter(KaggleAccount.user_id == current_user.id,
            (KaggleAccount.label == label)
            | (KaggleAccount.kernel_id == kernel_id)
            | (KaggleAccount.username.ilike(username))
        ).first():
            flash("That account label or kernel ID is already registered.", "error")
            return redirect(url_for("settings.settings"))
        db.session.add(KaggleAccount(
            user_id=current_user.id,
            label=label,
            username=username,
            api_key_encrypted=encrypted_key,
            kernel_id=kernel_id,
            enabled=True,
        ))
        db.session.commit()
        flash(f"Kaggle account {label} added.", "success")
        return redirect(url_for("settings.settings"))

    accounts = KaggleAccount.query.filter_by(user_id=current_user.id).order_by(KaggleAccount.label.asc()).all()
    platform_connections = {
        credential.platform: credential
        for credential in PlatformCredential.query.filter_by(user_id=current_user.id).all()
    }
    configured = {
        "Kaggle": bool(any(a.enabled for a in accounts) or (
            current_user.username == os.getenv("ADMIN_USERNAME", "admin")
            and os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY")
        )),
        "Gemini": "gemini" in platform_connections or bool(
            current_user.username == os.getenv("ADMIN_USERNAME", "admin")
            and os.getenv("GEMINI_API_KEY")
        ),
        "YouTube": "youtube" in platform_connections,
        "TikTok": "tiktok" in platform_connections,
    }
    return render_template("settings.html", configured=configured, accounts=accounts, platform_connections=platform_connections)


@settings_bp.route("/settings/platform-credentials", methods=["POST"])
@login_required
def save_platform_credentials():
    platform = (request.form.get("platform") or "").strip().lower()
    account_label = "default"
    token_value = ((request.form.get("api_key") or "") if platform == "gemini"
                   else (request.form.get("refresh_token") or "")).strip()
    if platform not in {"gemini", "youtube", "tiktok"} or not token_value:
        flash("Choose a supported service and enter its API key or refresh token.", "error")
        return redirect(url_for("settings.settings"))
    try:
        encrypted_token = encrypt_api_key(token_value)
    except RuntimeError as exc:
        flash(str(exc), "error")
        return redirect(url_for("settings.settings"))
    credential = PlatformCredential.query.filter_by(
        user_id=current_user.id, platform=platform, account_label=account_label
    ).first()
    if credential is None:
        credential = PlatformCredential(
            user_id=current_user.id,
            platform=platform,
            account_label=account_label,
            scopes=(["generate_content"] if platform == "gemini" else
                    ["youtube.upload"] if platform == "youtube" else ["video.publish"]),
        )
        db.session.add(credential)
    credential.refresh_token_encrypted = None if platform == "gemini" else encrypted_token
    credential.access_token_encrypted = encrypted_token if platform == "gemini" else None
    credential.expires_at = None
    db.session.commit()
    flash(f"{platform.title()} connection saved for this workspace.", "success")
    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/platform-credentials/<platform>/<account_label>/delete", methods=["POST"])
@login_required
def delete_platform_credentials(platform: str, account_label: str):
    credential = PlatformCredential.query.filter_by(
        user_id=current_user.id, platform=platform, account_label=account_label
    ).first_or_404()
    db.session.delete(credential)
    db.session.commit()
    flash(f"{platform.title()} connection removed from this workspace.", "success")
    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/kaggle-accounts/<int:account_id>/toggle", methods=["POST"])
@login_required
def toggle_kaggle_account(account_id: int):
    account = KaggleAccount.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    account.enabled = not account.enabled
    paused_schedules = []
    if not account.enabled:
        paused_schedules = Schedule.query.filter_by(
            kaggle_account_id=account.id, enabled=True
        ).all()
        for schedule in paused_schedules:
            schedule.enabled = False
    db.session.commit()
    for schedule in paused_schedules:
        remove_schedule_job(schedule.id)
    message = f"Kaggle account {account.label} {'enabled' if account.enabled else 'disabled'}."
    if paused_schedules:
        message += f" Paused {len(paused_schedules)} schedule(s) assigned to this account."
    flash(message, "success")
    return redirect(url_for("settings.settings"))


@settings_bp.route("/settings/kaggle-accounts/<int:account_id>/delete", methods=["POST"])
@login_required
def delete_kaggle_account(account_id: int):
    account = KaggleAccount.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    active_jobs = GenerationJob.query.filter(
        GenerationJob.kaggle_account_id == account.id,
        GenerationJob.status.in_(("queued", "pushing", "running", "downloading", "posting")),
    ).count()
    if active_jobs:
        flash("Wait for this account's active jobs to finish before deleting its credentials.", "error")
        return redirect(url_for("settings.settings"))

    schedules = Schedule.query.filter_by(kaggle_account_id=account.id).all()
    for schedule in schedules:
        schedule.enabled = False
        schedule.kaggle_account_id = None
        remove_schedule_job(schedule.id)
    GenerationJob.query.filter_by(kaggle_account_id=account.id).update(
        {GenerationJob.kaggle_account_id: None}, synchronize_session=False
    )
    label = account.label
    db.session.delete(account)
    db.session.commit()
    flash(f"Kaggle credentials for {label} were deleted. Its schedules were paused; job history was kept.", "success")
    return redirect(url_for("settings.settings"))
