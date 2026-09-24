import uuid
from datetime import datetime, timezone

from app import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GenerationJob(db.Model):
    __tablename__ = "generation_jobs"

    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(64), unique=True,
                       nullable=False, default=lambda: str(uuid.uuid4()))
    mode = db.Column(db.String(32), nullable=False, default="manual")
    schedule_id = db.Column(db.Integer, db.ForeignKey(
        "schedules.id"), nullable=True)
    kaggle_account_id = db.Column(db.Integer, db.ForeignKey(
        "kaggle_accounts.id", ondelete="SET NULL"), nullable=True)
    kaggle_account_name = db.Column(db.String(120), nullable=True)
    niche = db.Column(db.String(255), nullable=True)
    prompt_text = db.Column(db.Text, nullable=True)
    generation_params = db.Column(db.JSON, nullable=False, default=dict)
    status = db.Column(
        db.String(32),
        nullable=False,
        default="queued",
    )
    kaggle_kernel_version = db.Column(db.Integer, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    log_tail = db.Column(db.Text, nullable=True)
    manifest_json = db.Column(db.JSON, nullable=True)
    video_storage_path = db.Column(db.String(512), nullable=True, index=True)
    target_platforms = db.Column(db.JSON, nullable=False, default=list)
    post_results = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    schedule = db.relationship("Schedule", back_populates="jobs")
    kaggle_account = db.relationship("KaggleAccount")


class Schedule(db.Model):
    __tablename__ = "schedules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    niche = db.Column(db.String(255), nullable=False)
    style_notes = db.Column(db.Text, nullable=True)
    creative_brief = db.Column(db.JSON, nullable=False, default=dict)
    kaggle_account_id = db.Column(db.Integer, db.ForeignKey(
        "kaggle_accounts.id", ondelete="SET NULL"), nullable=True)
    time_of_day = db.Column(db.String(20), nullable=False, default="09:00")
    timezone = db.Column(db.String(80), nullable=False, default="UTC")
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    target_platforms = db.Column(db.JSON, nullable=False, default=list)
    resolution_preset = db.Column(
        db.String(80), nullable=False, default="Custom")
    custom_width = db.Column(db.Integer, nullable=True, default=352)
    custom_height = db.Column(db.Integer, nullable=True, default=608)
    duration_seconds = db.Column(db.Integer, nullable=False, default=30)
    chunk_seconds = db.Column(db.Integer, nullable=False, default=10)
    use_turbo_lora = db.Column(db.Boolean, nullable=False, default=True)
    turbo_steps = db.Column(db.Integer, nullable=False, default=4)
    video_crf = db.Column(db.Integer, nullable=False, default=18)
    video_preset = db.Column(db.String(16), nullable=False, default="slow")
    last_run_at = db.Column(db.DateTime, nullable=True)
    last_job_id = db.Column(db.String(64), nullable=True)

    jobs = db.relationship("GenerationJob", back_populates="schedule")
    kaggle_account = db.relationship("KaggleAccount")


class KaggleAccount(db.Model):
    __tablename__ = "kaggle_accounts"

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(120), nullable=False, unique=True)
    username = db.Column(db.String(120), nullable=False, unique=True)
    api_key_encrypted = db.Column(db.Text, nullable=False)
    kernel_id = db.Column(db.String(255), nullable=False, unique=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class PlatformCredential(db.Model):
    __tablename__ = "platform_credentials"

    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(32), nullable=False)
    account_label = db.Column(db.String(200), nullable=False)
    access_token_encrypted = db.Column(db.Text, nullable=True)
    refresh_token_encrypted = db.Column(db.Text, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    scopes = db.Column(db.JSON, nullable=False, default=list)

    __table_args__ = (db.UniqueConstraint("platform", "account_label"),)


__all__ = ["GenerationJob", "Schedule", "KaggleAccount", "PlatformCredential", "utcnow"]
