import os

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.creative_options import CREATIVE_OPTIONS, normalize_creative_brief
from app.models import KaggleAccount, PlatformCredential, Schedule
from app.scheduler import add_or_update_schedule_job, remove_schedule_job


schedules_bp = Blueprint("schedules", __name__)


def _account_context():
    return {
        "kaggle_accounts": KaggleAccount.query.filter_by(user_id=current_user.id, enabled=True).order_by(KaggleAccount.label.asc()).all(),
        "environment_account_available": bool(current_user.username == os.getenv("ADMIN_USERNAME", "admin") and os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY")),
        "connected_platforms": {
            row.platform for row in PlatformCredential.query.filter_by(user_id=current_user.id).all()
        },
        "creative_options": CREATIVE_OPTIONS,
    }


def _selected_account_id(value):
    if value == "environment":
        if not (current_user.username == os.getenv("ADMIN_USERNAME", "admin") and os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY")):
            raise ValueError("Configure this schedule with a saved Kaggle account.")
        return None
    try:
        account_id = int(value)
    except (TypeError, ValueError):
        raise ValueError("Choose an enabled Kaggle account for this schedule.")
    account = KaggleAccount.query.filter_by(id=account_id, user_id=current_user.id, enabled=True).first()
    if account is None:
        raise ValueError("Choose an enabled Kaggle account for this schedule.")
    return account.id


def _selected_platforms():
    platforms = list(dict.fromkeys(request.form.getlist("platforms")))
    connected = {
        row.platform for row in PlatformCredential.query.filter_by(user_id=current_user.id).all()
    }
    if not set(platforms) <= {"youtube", "tiktok"} or not set(platforms) <= connected:
        raise ValueError("Connect each selected publishing account in Settings first.")
    return platforms


@schedules_bp.route("/schedules", methods=["GET", "POST"])
@login_required
def list_schedules():
    if request.method == "POST":
        try:
            account_id = _selected_account_id(request.form.get("kaggle_account_id", ""))
            selected_platforms = _selected_platforms()
            duration = int(request.form.get("duration_seconds") or 30)
            chunk_seconds = int(request.form.get("chunk_seconds") or 10)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("schedules.html", schedules=Schedule.query.filter_by(user_id=current_user.id).order_by(Schedule.id.desc()).all(), **_account_context()), 400
        if not 5 <= duration <= 60 or not 5 <= chunk_seconds <= 15:
            flash("Use a total duration from 5 to 60 seconds and a clip length from 5 to 15 seconds.", "error")
            return render_template("schedules.html", schedules=Schedule.query.filter_by(user_id=current_user.id).order_by(Schedule.id.desc()).all(), **_account_context()), 400
        schedule = Schedule(
            user_id=current_user.id,
            name=request.form.get("name") or "New Schedule",
            niche=(request.form.get("niche") or "cinematic lifestyle").strip(),
            style_notes=request.form.get("style_notes") or None,
            creative_brief=normalize_creative_brief(request.form),
            kaggle_account_id=account_id,
            time_of_day=request.form.get("time_of_day") or "09:00",
            timezone=request.form.get("timezone") or "UTC",
            enabled=bool(request.form.get("enabled")),
            target_platforms=selected_platforms,
            resolution_preset=request.form.get(
                "resolution_preset") or "Custom",
            custom_width=(int(request.form.get("custom_width"))
                          if request.form.get("custom_width") else None),
            custom_height=(int(request.form.get("custom_height"))
                           if request.form.get("custom_height") else None),
            duration_seconds=duration,
            chunk_seconds=chunk_seconds,
            use_turbo_lora=request.form.get("use_turbo_lora", "on") == "on",
            turbo_steps=int(request.form.get("turbo_steps") or 4),
            video_crf=int(request.form.get("video_crf") or 18),
            video_preset=request.form.get("video_preset") or "slow",
        )
        db.session.add(schedule)
        db.session.commit()
        add_or_update_schedule_job(current_app, schedule)
        flash("Schedule created.", "success")
        return redirect(url_for("schedules.detail", schedule_id=schedule.id))

    schedules = Schedule.query.filter_by(user_id=current_user.id).order_by(Schedule.id.desc()).all()
    return render_template("schedules.html", schedules=schedules, **_account_context())


@schedules_bp.route("/schedules/<int:schedule_id>", methods=["GET", "POST"])
@login_required
def detail(schedule_id: int):
    schedule = Schedule.query.filter_by(id=schedule_id, user_id=current_user.id).first_or_404()
    if request.method == "POST":
        try:
            account_id = _selected_account_id(request.form.get("kaggle_account_id", "environment"))
            selected_platforms = _selected_platforms()
            duration = int(request.form.get("duration_seconds") or schedule.duration_seconds)
            chunk_seconds = int(request.form.get("chunk_seconds") or schedule.chunk_seconds or 10)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("schedule_edit.html", schedule=schedule, **_account_context()), 400
        if not 5 <= duration <= 60 or not 5 <= chunk_seconds <= 15:
            flash("Use a total duration from 5 to 60 seconds and a clip length from 5 to 15 seconds.", "error")
            return render_template("schedule_edit.html", schedule=schedule, **_account_context()), 400
        schedule.name = request.form.get("name") or schedule.name
        schedule.niche = (request.form.get("niche") or schedule.niche).strip()
        schedule.style_notes = request.form.get("style_notes") or None
        schedule.creative_brief = normalize_creative_brief(request.form)
        schedule.kaggle_account_id = account_id
        schedule.time_of_day = request.form.get(
            "time_of_day") or schedule.time_of_day
        schedule.timezone = request.form.get("timezone") or schedule.timezone
        schedule.enabled = bool(request.form.get("enabled"))
        schedule.target_platforms = selected_platforms
        schedule.resolution_preset = request.form.get(
            "resolution_preset") or schedule.resolution_preset
        schedule.custom_width = (int(request.form.get(
            "custom_width")) if request.form.get("custom_width") else None)
        schedule.custom_height = (int(request.form.get(
            "custom_height")) if request.form.get("custom_height") else None)
        schedule.duration_seconds = duration
        schedule.chunk_seconds = chunk_seconds
        schedule.use_turbo_lora = request.form.get("use_turbo_lora") == "on"
        schedule.turbo_steps = int(request.form.get(
            "turbo_steps") or schedule.turbo_steps or 4)
        schedule.video_crf = int(request.form.get(
            "video_crf") or schedule.video_crf or 18)
        schedule.video_preset = request.form.get(
            "video_preset") or schedule.video_preset or "slow"
        db.session.commit()
        add_or_update_schedule_job(current_app, schedule)
        flash("Schedule updated.", "success")
        return redirect(url_for("schedules.detail", schedule_id=schedule.id))

    return render_template("schedule_edit.html", schedule=schedule, **_account_context())


@schedules_bp.route("/schedules/<int:schedule_id>/delete", methods=["POST"])
@login_required
def delete(schedule_id: int):
    schedule = Schedule.query.filter_by(id=schedule_id, user_id=current_user.id).first_or_404()
    for job in schedule.jobs:
        job.schedule_id = None
    name = schedule.name
    db.session.delete(schedule)
    db.session.commit()
    remove_schedule_job(schedule_id)
    flash(f"Schedule {name} and its saved prompt were deleted. Generated job history was kept.", "success")
    return redirect(url_for("schedules.list_schedules"))
