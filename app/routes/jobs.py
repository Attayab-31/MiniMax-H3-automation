from pathlib import Path
import mimetypes
import hmac
import os

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, send_file, url_for
from flask_login import login_required

from app import csrf, db
from app.models import GenerationJob, utcnow
from app.pipeline import retry_posting_only, run_pipeline_in_app_context
from app.storage import signed_video_url


jobs_bp = Blueprint("jobs", __name__)


def _progress_snapshot(job: GenerationJob) -> dict:
    progress = dict((job.generation_params or {}).get("_progress") or {})
    callback_configured = bool(
        current_app.config.get("KAGGLE_CALLBACK_URL")
        and current_app.config.get("KAGGLE_CALLBACK_TOKEN")
    )
    if job.status == "completed":
        return {
            **progress,
            "percent": 100,
            "stage": "Complete",
            "message": "The video is ready to preview and download.",
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
    job = GenerationJob.query.get_or_404(job_id)
    return render_template("job_detail.html", job=job)


@jobs_bp.route("/jobs/<int:job_id>/video")
@jobs_bp.route("/jobs/<int:job_id>/download", endpoint="download")
@login_required
def video(job_id: int):
    job = GenerationJob.query.get_or_404(job_id)
    manifest = job.manifest_json or {}
    filename = manifest.get("local_final_video")
    storage_path = manifest.get("storage_path")
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
    job = GenerationJob.query.get_or_404(job_id)
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
    job = GenerationJob.query.get_or_404(job_id)
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
        "video_url": url_for("jobs.video", job_id=job.id) if ((job.manifest_json or {}).get("local_final_video") or (job.manifest_json or {}).get("storage_path")) else None,
        "download_url": url_for("jobs.download", job_id=job.id) if ((job.manifest_json or {}).get("local_final_video") or (job.manifest_json or {}).get("storage_path")) else None,
        "post_results": job.post_results,
    })
