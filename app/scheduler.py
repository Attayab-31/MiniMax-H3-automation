from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import db
from app.models import GenerationJob, KaggleAccount, Schedule, utcnow
from app.pipeline import run_pipeline_in_app_context


_scheduler = None


def _safe_timezone(name: str):
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def init_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler()
    scheduler.start()
    app.config["SCHEDULER"] = scheduler
    _scheduler = scheduler

    with app.app_context():
        for schedule in Schedule.query.filter_by(enabled=True).all():
            add_or_update_schedule_job(app, schedule)

    return scheduler


def add_or_update_schedule_job(app, schedule: Schedule):
    if _scheduler is None:
        init_scheduler(app)
    tzinfo = _safe_timezone(schedule.timezone)
    if tzinfo is None:
        tzinfo = ZoneInfo("UTC")
    hour, minute = (schedule.time_of_day or "09:00").split(":", 1)

    cron = CronTrigger(hour=int(hour), minute=int(minute), timezone=tzinfo)
    _scheduler.add_job(
        _fire_schedule,
        trigger=cron,
        id=f"schedule-{schedule.id}",
        replace_existing=True,
        args=[app, schedule.id],
    )


def remove_schedule_job(schedule_id: int):
    if _scheduler is not None:
        try:
            _scheduler.remove_job(f"schedule-{schedule_id}")
        except Exception:
            pass


def _fire_schedule(app, schedule_id: int):
    with app.app_context():
        schedule = Schedule.query.get(schedule_id)
        if schedule is None or not schedule.enabled:
            return
        if schedule.kaggle_account_id is not None:
            account = db.session.get(KaggleAccount, schedule.kaggle_account_id)
            if account is None or not account.enabled:
                return
        preset_sizes = {
            "Portrait vertical · 352×608": (352, 608),
            "Fast preview · 512×288": (512, 288),
            "Kaggle safe · 608×352": (608, 352),
            "Detailed preview · 736×416": (736, 416),
        }
        preset_width, preset_height = preset_sizes.get(
            schedule.resolution_preset, (schedule.custom_width or 352, schedule.custom_height or 608)
        )
        creative_brief = dict(schedule.creative_brief or {})
        creative_brief["aspect_ratio"] = "9:16 portrait" if preset_height > preset_width else "16:9 landscape"
        job = GenerationJob(
            mode="scheduled",
            schedule_id=schedule.id,
            kaggle_account_id=schedule.kaggle_account_id,
            kaggle_account_name=(schedule.kaggle_account.label if schedule.kaggle_account else "Environment account"),
            niche=schedule.niche,
            prompt_text=schedule.style_notes or "",
            generation_params={
                "niche": schedule.niche,
                "style_notes": schedule.style_notes,
                "creative_brief": creative_brief,
                "resolution_preset": ("Custom" if schedule.resolution_preset == "Portrait vertical · 352×608" else schedule.resolution_preset),
                "custom_width": preset_width,
                "custom_height": preset_height,
                "duration_seconds": schedule.duration_seconds,
                "chunk_seconds": schedule.chunk_seconds,
                "max_single_shot_seconds": schedule.chunk_seconds,
                "use_turbo_lora": schedule.use_turbo_lora,
                "turbo_steps": schedule.turbo_steps,
                "video_crf": schedule.video_crf,
                "video_preset": schedule.video_preset,
                "target_platforms": schedule.target_platforms,
            },
            target_platforms=schedule.target_platforms or [],
            status="queued",
        )
        db.session.add(job)
        db.session.commit()
        app.config["EXECUTOR"].submit(
            run_pipeline_in_app_context, app, job.id)
        schedule.last_run_at = utcnow()
        schedule.last_job_id = job.job_id
        db.session.commit()
