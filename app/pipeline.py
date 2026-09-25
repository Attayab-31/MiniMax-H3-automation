import os
import time
import threading
from pathlib import Path

from app import db
from app.kaggle_client import fetch_output, poll_status, trigger_generation
from app.llm_client import generate_h3_segment_prompts, generate_platform_metadata
from app.models import GenerationJob, utcnow
from app.storage import download_video
from app.tiktok_client import publish_video
from app.youtube_client import upload_video


_account_locks = {}
_account_locks_guard = threading.Lock()


def _account_lock(job):
    account_key = str(job.kaggle_account_id or "environment")
    with _account_locks_guard:
        return _account_locks.setdefault(account_key, threading.Lock())


def run_pipeline_in_app_context(app, job_id: int):
    with app.app_context():
        job = db.session.get(GenerationJob, job_id)
        if job is None:
            return
        run_pipeline(job)


def resume_pipeline_in_app_context(app, job_id: int):
    """Resume a persisted job after the web process that owned it restarted.

    Kaggle keeps running independently of Render, while the in-process executor
    does not survive a deploy or instance restart. Resume from Kaggle status so
    a completed notebook can still be downloaded and attached to its job.
    """
    with app.app_context():
        job = db.session.get(GenerationJob, job_id)
        if job is None or job.status in {"completed", "failed"}:
            return
        with _account_lock(job):
            _resume_pipeline(job)


def retry_video_download_in_app_context(app, job_id: int):
    """Retry only artifact retrieval for a Kaggle run that already completed."""
    with app.app_context():
        job = db.session.get(GenerationJob, job_id)
        if job is None or job.status != "downloading":
            return
        with _account_lock(job):
            try:
                job.status = "downloading"
                db.session.commit()
                _fetch_output_with_retries(job)
                db.session.commit()
                job.status = "completed"
                job.error_message = None
            except Exception as exc:
                job.status = "failed"
                job.error_message = f"Video download retry failed: {exc}"
                app.logger.exception("Video download retry failed for job %s", job.job_id)
            finally:
                job.completed_at = utcnow()
                db.session.commit()


def _resume_pipeline(job: GenerationJob):
    try:
        wait_until_complete(job)
        if job.status == "failed":
            raise RuntimeError(job.error_message or "Kaggle execution failed.")

        job.status = "downloading"
        db.session.commit()
        _fetch_output_with_retries(job)
        db.session.commit()

        if job.target_platforms:
            job.status = "posting"
            db.session.commit()
            for platform in job.target_platforms:
                metadata = generate_platform_metadata(
                    job.niche or "general",
                    job.prompt_text or job.generation_params.get("prompt") or "",
                    platform,
                )
                job.post_results[platform] = _post_to_platform(platform, job, metadata)
                db.session.commit()

        job.status = "completed"
        job.error_message = None
    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
    finally:
        job.completed_at = utcnow()
        db.session.commit()


def _post_to_platform(platform: str, job: GenerationJob, metadata: dict):
    manifest = job.manifest_json or {}
    path = manifest.get("local_final_video")
    if not path or not os.path.isfile(path):
        path = None
    if not path and manifest.get("storage_path"):
        video_info = manifest.get("final_video") or {}
        original_name = video_info.get("path", "video.mp4") if isinstance(video_info, dict) else "video.mp4"
        extension = Path(original_name).suffix or ".mp4"
        path = download_video(
            manifest["storage_path"],
            str(Path("runtime") / "kaggle_outputs" / job.job_id / f"restored{extension}"),
        )
    if not path:
        raise RuntimeError(
            f"No generated video file is available for platform {platform}.")

    if platform == "youtube":
        result = upload_video(
            video_path=path,
            title=metadata.get("title", "AI generated short video"),
            description=metadata.get("description", ""),
            hashtags=metadata.get("hashtags", []),
            privacy="private",
        )
        return {"platform": platform, "status": "success", "result": result}

    if platform == "tiktok":
        result = publish_video(
            video_path=path,
            title=metadata.get("title", "AI generated short video"),
            description=metadata.get("description", ""),
            hashtags=metadata.get("hashtags", []),
        )
        return {"platform": platform, "status": "success", "result": result}

    raise RuntimeError(f"Unsupported platform: {platform}")


def wait_until_complete(job, poll_interval: float = 30.0, timeout_minutes: int = 660) -> None:
    deadline = time.monotonic() + (timeout_minutes * 60)
    consecutive_poll_errors = 0
    while True:
        try:
            status = poll_status(job)
            consecutive_poll_errors = 0
        except Exception as exc:
            consecutive_poll_errors += 1
            job.status = "running"
            job.log_tail = (
                f"Kaggle status check failed; retrying "
                f"({consecutive_poll_errors}/10): {exc}"
            )[-12000:]
            db.session.commit()
            if consecutive_poll_errors >= 10:
                raise RuntimeError(
                    f"Kaggle status checks failed 10 times in a row. Last error: {exc}"
                ) from exc

            retry_delay = min(60.0, max(5.0, 5.0 * (2 ** (consecutive_poll_errors - 1))))
            time.sleep(min(retry_delay, poll_interval))
            continue

        job.status = status
        db.session.commit()

        if status in {"completed", "failed"}:
            return

        if time.monotonic() >= deadline:
            job.status = "failed"
            job.error_message = "timed out waiting on Kaggle"
            db.session.commit()
            raise TimeoutError("timed out waiting on Kaggle")

        time.sleep(poll_interval)


def _fetch_output_with_retries(job: GenerationJob, attempts: int = 3) -> None:
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            fetch_output(job)
            return
        except Exception as exc:
            last_error = exc
            job.log_tail = (
                f"Kaggle output download failed; retrying "
                f"({attempt}/{attempts}): {exc}"
            )[-12000:]
            db.session.commit()
            if attempt < attempts:
                time.sleep(5 * attempt)
    raise RuntimeError(
        f"Kaggle output download failed after {attempts} attempts: {last_error}"
    ) from last_error


def retry_posting_only(job: GenerationJob):
    manifest = job.manifest_json or {}
    local_path = manifest.get("local_final_video")
    if not ((local_path and os.path.isfile(local_path)) or manifest.get("storage_path")):
        raise RuntimeError("No generated video exists to retry posting.")

    if not job.target_platforms:
        return

    job.status = "posting"
    job.error_message = None
    db.session.commit()

    for platform in job.target_platforms:
        metadata = generate_platform_metadata(
            job.niche or "general", job.prompt_text or "", platform)
        job.post_results[platform] = _post_to_platform(platform, job, metadata)
        db.session.commit()

    job.status = "completed"
    db.session.commit()


def run_pipeline(job: GenerationJob):
    with _account_lock(job):
        _run_pipeline(job)


def _run_pipeline(job: GenerationJob):
    try:
        if job.mode == "scheduled":
            params = dict(job.generation_params or {})
            duration = params.get("duration_seconds", 30)
            chunk_seconds = params.get("chunk_seconds", 10)
            creative_brief = params.get("creative_brief") or {}
            job.prompt_text = (
                f"Topic: {job.niche or 'cinematic short video'}. "
                f"Shared direction: {params.get('style_notes') or 'Maintain clear visual continuity across the sequence.'}"
            )
            params["segment_prompts"] = generate_h3_segment_prompts(
                job.niche,
                params.get("style_notes"),
                duration,
                chunk_seconds,
                creative_brief,
            )
            job.generation_params = params
            db.session.commit()

        job.status = "queued"
        job.started_at = utcnow()
        db.session.commit()

        job.status = "pushing"
        db.session.commit()
        trigger_generation(job)

        job.status = "running"
        db.session.commit()
        wait_until_complete(job)

        if job.status == "failed":
            raise RuntimeError(job.error_message or "Kaggle execution failed.")

        job.status = "downloading"
        db.session.commit()
        _fetch_output_with_retries(job)
        db.session.commit()

        if job.target_platforms:
            job.status = "posting"
            db.session.commit()
            for platform in job.target_platforms:
                metadata = generate_platform_metadata(
                    job.niche or "general", job.prompt_text or job.generation_params.get("prompt") or "", platform)
                job.post_results[platform] = _post_to_platform(
                    platform, job, metadata)
                db.session.commit()

        job.status = "completed"

    except Exception as exc:
        job.status = "failed"
        job.error_message = str(exc)
        db.session.commit()

    finally:
        job.completed_at = utcnow()
        db.session.commit()
