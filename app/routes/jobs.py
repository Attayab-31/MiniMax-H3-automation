from pathlib import Path
import mimetypes
import hmac
import os
import shutil

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import login_required
from sqlalchemy import or_

from app import csrf, db
from app.models import GenerationJob, utcnow
from app.pipeline import retry_posting_only, run_pipeline_in_app_context
from app.storage import delete_video as delete_stored_video, signed_video_url


jobs_bp = Blueprint("jobs", __name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ACTIVE_JOB_STATUSES = {"queued", "pushing", "running", "downloading", "posting"}


def _remove_local_prompt_artifacts(job_id: str, *, remove_video: bool) -> None:
    runtime = (_PROJECT_ROOT / "runtime").resolve()
    safe_id = str(job_id)
    if Path(safe_id).name != safe_id or safe_id in {"", ".", ".."}:
        return

    params_file = (runtime / f"params_{safe_id}.json").resolve()
    if params_file.parent == runtime and params_file.is_file():
        params_file.unlink(missing_ok=True)

    push_dir = (runtime / "kaggle_push" / safe_id).resolve()
    push_root = (runtime / "kaggle_push").resolve()
    if push_dir.parent == push_root and push_dir.is_dir():
        shutil.rmtree(push_dir)

    output_dir = (runtime / "kaggle_outputs" / safe_id).resolve()
    output_root = (runtime / "kaggle_outputs").resolve()
    if output_dir.parent != output_root or not output_dir.is_dir():
        return
    if remove_video:
        shutil.rmtree(output_dir)
        return
    for child in output_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        elif child.suffix.lower() not in {".mp4", ".webm", ".mov", ".mkv"}:
            child.unlink(missing_ok=True)


def _delete_storage_object(job: GenerationJob) -> None:
    manifest = job.manifest_json or {}
    object_path = job.video_storage_path or manifest.get("storage_path")
    if object_path:
        delete_stored_video(object_path)


@jobs_bp.route("/jobs/<int:job_id>/delete-prompts", methods=["POST"])
@login_required
def delete_prompts(job_id: int):
    job = db.get_or_404(GenerationJob, job_id)
    if job.status in _ACTIVE_JOB_STATUSES:
        flash("Wait for this job to finish before deleting its prompts.", "error")
        return redirect(url_for("jobs.detail", job_id=job.id))

    params = dict(job.generation_params or {})
    for key in ("prompt", "segment_prompts", "niche", "style_notes", "creative_brief"):
        params.pop(key, None)
    job.generation_params = params
    job.niche = None
    job.prompt_text = None
    job.log_tail = None
    job.error_message = None
    job.post_results = {}
    manifest = dict(job.manifest_json or {})
    for key in ("prompt", "prompts", "segment_prompts", "niche", "style_notes", "creative_brief"):
        manifest.pop(key, None)
    job.manifest_json = manifest
    _remove_local_prompt_artifacts(job.job_id, remove_video=False)
    db.session.commit()
    flash("This job's prompts, prompt logs, and generated prompt metadata were deleted.", "success")
    return redirect(url_for("jobs.detail", job_id=job.id))


@jobs_bp.route("/jobs/<int:job_id>/delete-everything", methods=["POST"])
@login_required
def delete_everything(job_id: int):
    job = db.get_or_404(GenerationJob, job_id)
    if job.status in _ACTIVE_JOB_STATUSES:
        flash("Wait for this job to finish before deleting its data.", "error")
        return redirect(url_for("jobs.detail", job_id=job.id))

    try:
        _delete_storage_object(job)
    except Exception:
        current_app.logger.exception("Could not delete the video before removing its job")
        flash("The stored video could not be deleted. The job and prompts were kept.", "error")
        return redirect(url_for("jobs.detail", job_id=job.id))

    _remove_local_prompt_artifacts(job.job_id, remove_video=True)
    db.session.delete(job)
    db.session.commit()
    flash("The job, prompts, logs, metadata, and stored video were deleted.", "success")
    return redirect(url_for("dashboard.index"))


@jobs_bp.route("/videos")
@login_required
def videos():
    page = request.args.get("page", 1, type=int)
    pagination = (
        GenerationJob.query.filter(or_(
            GenerationJob.video_storage_path.isnot(None),
            GenerationJob.manifest_json["storage_path"].as_string().isnot(None),
        ))
        .order_by(GenerationJob.created_at.desc())
        .paginate(page=max(page, 1), per_page=24, error_out=False)
    )
    storage_ready = bool(
        current_app.config.get("SUPABASE_URL")
        and current_app.config.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    return render_template(
        "videos.html", pagination=pagination, storage_ready=storage_ready
    )


@jobs_bp.route("/jobs/<int:job_id>/delete-video", methods=["POST"])
@login_required
def delete_video(job_id: int):
    job = db.get_or_404(GenerationJob, job_id)
    if job.status not in {"completed", "failed"}:
        flash("Wait for this job to finish before deleting its video.", "error")
        return redirect(url_for("jobs.videos"))
    manifest = dict(job.manifest_json or {})
    object_path = job.video_storage_path or manifest.get("storage_path")
    if not object_path:
        flash("This job does not have a video saved in Supabase Storage.", "error")
        return redirect(url_for("jobs.videos"))

    try:
        delete_stored_video(object_path)
    except Exception:
        current_app.logger.exception("Could not delete a video from Supabase Storage")
        flash("Supabase could not delete the video. It remains in your library.", "error")
        return redirect(url_for("jobs.videos"))

    local_path = manifest.get("local_final_video")
    if local_path:
        path = Path(local_path).resolve()
        output_root = (Path(__file__).resolve().parents[2] / "runtime" / "kaggle_outputs").resolve()
        if output_root in path.parents and path.is_file():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                current_app.logger.exception("Could not remove the local video cache")

    manifest.pop("storage_path", None)
    manifest.pop("local_final_video", None)
    manifest["video_deleted_at"] = utcnow().isoformat()
    job.manifest_json = manifest
    job.video_storage_path = None
    db.session.commit()
    flash("Video deleted from Supabase Storage. The generation history was kept.", "success")
    return redirect(url_for("jobs.videos"))


def _progress_snapshot(job: GenerationJob) -> dict:
    progress = dict((job.generation_params or {}).get("_progress") or {})
    callback_configured = bool(
        current_app.config.get("KAGGLE_CALLBACK_URL")
        and current_app.config.get("KAGGLE_CALLBACK_TOKEN")
    )
    if job.status == "completed":
        video_deleted = bool((job.manifest_json or {}).get("video_deleted_at"))
        return {
            **progress,
            "percent": 100,
            "stage": "Video deleted" if video_deleted else "Complete",
            "message": (
                "The video was deleted from storage; the generation history remains."
                if video_deleted else "The video is ready to preview and download."
            ),
            "live": True,
            "callback_configured": callback_configured,
        }
    if job.status == "failed":
        has_video = bool((job.manifest_json or {}).get("local_final_video") or (job.manifest_json or {}).get("storage_path"))
        return {
            **progress,
            "percent": 99 if has_video else 0,
            "stage": "Video ready; another step failed" if has_video else "Failed",
            "message": job.error_message or "The job failed.",
            "live": False,
            "callback_configured": callback_configured,
        }
    if progress.get("live"):
        progress["callback_configured"] = callback_configured
        return progress

    fallback = {
        "queued": (2, "Queued", "Waiting for the Kaggle worker."),
        "pushing": (5, "Preparing notebook", "Sending this job to Kaggle."),
        "running": (8, "Running on Kaggle", "GPU progress is not available yet."),
        "downloading": (96, "Downloading final video", "Kaggle finished; Flask is fetching the output."),
        "posting": (98, "Publishing", "The generated video is ready."),
        "completed": (100, "Complete", "The video is ready to preview and download."),
        "failed": (0, "Failed", job.error_message or "The job failed."),
    }
    percent, stage, message = fallback.get(job.status, (2, "Queued", "Waiting for the Kaggle worker."))
    return {
        "percent": percent,
        "stage": stage,
        "message": message,
        "live": False,
        "callback_configured": callback_configured,
        "completed_segments": progress.get("completed_segments", 0),
        "total_segments": progress.get("total_segments", 0),
    }


@jobs_bp.route("/api/kaggle/progress/<job_id>", methods=["POST"])
@csrf.exempt
def kaggle_progress(job_id: str):
    """Receive signed, per-segment/per-step progress from the Kaggle notebook."""
    expected_token = os.getenv("KAGGLE_CALLBACK_TOKEN", "")
    provided_token = request.headers.get("X-Kaggle-Progress-Token", "")
    if not expected_token or not hmac.compare_digest(provided_token, expected_token):
        return jsonify({"error": "unauthorized"}), 401

    job = GenerationJob.query.filter_by(job_id=job_id).first_or_404()
    if job.status in {"completed", "failed"}:
        return jsonify({"error": "job is no longer active"}), 409

    payload = request.get_json(silent=True) or {}
    try:
        total_segments = int(payload.get("total_segments", 0))
        completed_segments = int(payload.get("completed_segments", 0))
        segment_index = int(payload.get("segment_index", 0))
        segment_progress = float(payload.get("segment_progress", 0.0))
    except (TypeError, ValueError):
        return jsonify({"error": "invalid progress values"}), 400

    if not 1 <= total_segments <= 12:
        return jsonify({"error": "invalid total_segments"}), 400
    if not 0 <= completed_segments <= total_segments:
        return jsonify({"error": "invalid completed_segments"}), 400
    if not 0 <= segment_index < total_segments:
        return jsonify({"error": "invalid segment_index"}), 400
    if not 0 <= segment_progress <= 1:
        return jsonify({"error": "invalid segment_progress"}), 400

    percent = round(100 * (completed_segments + segment_progress) / total_segments)
    percent = min(99, max(1, percent))
    progress = {
        "percent": percent,
        "stage": str(payload.get("stage") or "Generating")[:80],
        "message": str(payload.get("message") or "Working on the current clip.")[:240],
        "live": True,
        "callback_configured": True,
        "completed_segments": completed_segments,
        "total_segments": total_segments,
        "current_segment": min(total_segments, max(1, segment_index + 1)),
        "segment_progress": (
            100 if completed_segments > segment_index else round(segment_progress * 100)
        ),
        "updated_at": utcnow().isoformat(),
    }
    job.generation_params = {
        **(job.generation_params or {}),
        "_progress": progress,
    }
    db.session.commit()
    return jsonify({"accepted": True, "percent": percent})


@jobs_bp.route("/jobs/<int:job_id>")
@login_required
def detail(job_id: int):
    job = db.get_or_404(GenerationJob, job_id)
    return render_template("job_detail.html", job=job)


@jobs_bp.route("/jobs/<int:job_id>/video")
@jobs_bp.route("/jobs/<int:job_id>/download", endpoint="download")
@login_required
def video(job_id: int):
    job = db.get_or_404(GenerationJob, job_id)
    manifest = job.manifest_json or {}
    filename = manifest.get("local_final_video")
    storage_path = job.video_storage_path or manifest.get("storage_path")
    if storage_path:
        try:
            return redirect(signed_video_url(storage_path, download=request.endpoint == "jobs.download"))
        except Exception as exc:
            current_app.logger.exception("Could not create a Supabase video URL")
            return f"Video storage is temporarily unavailable: {exc}", 503
    if not filename:
        return "Video is not ready yet.", 404

    path = Path(filename).resolve()
    output_root = (Path(__file__).resolve().parents[2] / "runtime" / "kaggle_outputs").resolve()
    if output_root not in path.parents or not path.is_file():
        return "Video output is unavailable.", 404
    return send_file(
        path,
        mimetype=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        as_attachment=request.endpoint == "jobs.download",
        download_name=f"h3-video-{job.job_id[:8]}{path.suffix.lower()}",
        conditional=True,
    )


@jobs_bp.route("/jobs/<int:job_id>/retry-posting", methods=["POST"])
@login_required
def retry_posting(job_id: int):
    job = db.get_or_404(GenerationJob, job_id)
    if (job.manifest_json or {}).get("local_final_video") or (job.manifest_json or {}).get("storage_path"):
        app = current_app._get_current_object()
        app.config["EXECUTOR"].submit(
            _run_retry_posting_in_app_context, app, job)
        flash("Retrying posting for this job only.", "success")
    else:
        flash("This job has no completed video to post yet.", "error")
    return redirect(url_for("jobs.detail", job_id=job.id))


def _run_retry_posting_in_app_context(app, job):
    with app.app_context():
        retry_posting_only(job)


@jobs_bp.route("/api/jobs/<int:job_id>")
@login_required
def job_api(job_id: int):
    job = db.get_or_404(GenerationJob, job_id)
    return jsonify({
        "id": job.id,
        "job_id": job.job_id,
        "mode": job.mode,
        "status": job.status,
        "niche": job.niche,
        "kaggle_account_name": job.kaggle_account_name or "Environment account",
        "target_platforms": job.target_platforms or [],
        "log_tail": job.log_tail,
        "error_message": job.error_message,
        "progress": _progress_snapshot(job),
        "video_url": url_for("jobs.video", job_id=job.id) if (job.video_storage_path or (job.manifest_json or {}).get("local_final_video") or (job.manifest_json or {}).get("storage_path")) else None,
        "download_url": url_for("jobs.download", job_id=job.id) if (job.video_storage_path or (job.manifest_json or {}).get("local_final_video") or (job.manifest_json or {}).get("storage_path")) else None,
        "post_results": job.post_results,
    })
