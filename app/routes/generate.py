import math
import os
import secrets

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app import db
from app.models import GenerationJob, KaggleAccount
from app.pipeline import run_pipeline_in_app_context
from app.video_profiles import validate_video_profile


generate_bp = Blueprint("generate", __name__)


@generate_bp.route("/generate", methods=["GET", "POST"])
@login_required
def generate():
    kaggle_accounts = KaggleAccount.query.filter_by(enabled=True).order_by(KaggleAccount.label.asc()).all()
    environment_account_available = bool(os.getenv("KAGGLE_USERNAME") and os.getenv("KAGGLE_KEY"))
    form_context = {
        "kaggle_accounts": kaggle_accounts,
        "environment_account_available": environment_account_available,
    }
    if request.method == "POST":
        niche = (request.form.get("niche")
                 or "").strip() or "cinematic lifestyle"
        prompt_text = (request.form.get("prompt") or "").strip()
        if not prompt_text:
            flash("Enter the prompt for the video.", "error")
            return render_template("generate.html", **form_context), 400
        if len(prompt_text) > 10000:
            flash("The main prompt must be 10000 characters or fewer.", "error")
            return render_template("generate.html", **form_context), 400
        resolution_profile = request.form.get("resolution_profile", "portrait")
        profiles = {
            "portrait": (352, 608),
            "landscape": (608, 352),
            "fast": (512, 288),
            "detailed": (736, 416),
        }
        custom_width = request.form.get("custom_width")
        custom_height = request.form.get("custom_height")
        try:
            duration_seconds = float(request.form.get("duration_seconds") or 30)
            clip_duration_seconds = float(request.form.get("clip_duration_seconds") or 10)
            width, height = profiles.get(resolution_profile, (None, None))
            if resolution_profile == "custom":
                width = int(custom_width) if custom_width else None
                height = int(custom_height) if custom_height else None
            seed_value = (request.form.get("seed") or "").strip()
            seed = int(seed_value) if seed_value else secrets.randbelow(2**31)
            steps = int(request.form.get("steps") or 20)
            turbo_steps = int(request.form.get("turbo_steps") or 4)
            video_crf = int(request.form.get("video_crf") or 18)
        except ValueError:
            flash("Enter valid numbers for duration, clip length, seed, and dimensions.", "error")
            return render_template("generate.html", **form_context), 400

        if resolution_profile not in {*profiles, "custom"}:
            flash("Choose one of the available H3 output profiles.", "error")
            return render_template("generate.html", **form_context), 400
        profile_error = validate_video_profile(
            width, height, duration_seconds, clip_duration_seconds)
        if profile_error:
            flash(profile_error, "error")
            return render_template("generate.html", **form_context), 400
        video_preset = request.form.get("video_preset", "slow")
        use_turbo_lora = request.form.get("use_turbo_lora") == "on"
        if video_preset not in {"medium", "slow"} or not 0 <= video_crf <= 51:
            flash("Choose a supported encoding preset and a CRF value from 0 to 51.", "error")
            return render_template("generate.html", **form_context), 400

        account_value = (request.form.get("kaggle_account_id") or "").strip()
        if not account_value or (account_value == "environment" and environment_account_available):
            kaggle_account = None
            kaggle_account_name = "Environment account"
        else:
            try:
                kaggle_account = next(
                    account for account in kaggle_accounts if account.id == int(account_value)
                )
            except (ValueError, StopIteration):
                flash("Choose an enabled Kaggle account in Settings first.", "error")
                return render_template("generate.html", **form_context), 400
            kaggle_account_name = kaggle_account.label
        if not 1 <= turbo_steps <= 8 or not 4 <= steps <= 30:
            flash("Use 1-8 Turbo steps or 4-30 standard sampling steps.", "error")
            return render_template("generate.html", **form_context), 400
        if not 0 <= seed <= 2**32 - 1:
            flash("Seed must be between 0 and 4294967295.", "error")
            return render_template("generate.html", **form_context), 400

        segment_count = math.ceil(duration_seconds / clip_duration_seconds)
        submitted_segments = request.form.getlist("segment_prompts")
        segment_prompts = []
        if submitted_segments:
            if len(submitted_segments) != segment_count:
                flash("The clip timeline does not match the planned number of clips. Update the duration or clip length and try again.", "error")
                return render_template("generate.html", **form_context), 400
            if any(not clip_prompt.strip() for clip_prompt in submitted_segments):
                flash("Add a direction for every clip in the timeline.", "error")
                return render_template("generate.html", **form_context), 400
            if any(len(clip_prompt.strip()) > 5000 for clip_prompt in submitted_segments):
                flash("Each clip direction must be 5000 characters or fewer.", "error")
                return render_template("generate.html", **form_context), 400
            base_prompt = prompt_text[:10000]
            segment_prompts = [
                f"{base_prompt}\n\n{clip_prompt.strip()}"
                for clip_prompt in submitted_segments
            ]
            if any(len(clip_prompt) > 15000 for clip_prompt in segment_prompts):
                flash("Each combined clip prompt must be 15000 characters or fewer.", "error")
                return render_template("generate.html", **form_context), 400

        params = {
            "niche": niche,
            "prompt": prompt_text,
            "resolution_preset": "Custom",
            "resolution_profile": resolution_profile,
            "custom_width": width,
            "custom_height": height,
            "duration_seconds": duration_seconds,
            "chunk_seconds": clip_duration_seconds,
            "max_single_shot_seconds": clip_duration_seconds,
            "segment_prompts": segment_prompts,
            "seed": seed,
            "steps": steps,
            "turbo_steps": turbo_steps,
            "video_crf": video_crf,
            "video_preset": video_preset,
            "use_turbo_lora": use_turbo_lora,
            "auto_fallback": request.form.get("auto_fallback") == "on",
            "use_second_t4_for_text_encoder": False,
            "video_pixel_format": "yuv420p",
            "video_faststart": True,
        }

        job = GenerationJob(
            mode="manual",
            kaggle_account_id=kaggle_account.id if kaggle_account else None,
            kaggle_account_name=kaggle_account_name,
            niche=niche,
            prompt_text=prompt_text,
            generation_params=params,
            target_platforms=[],
            status="queued",
        )
        params["_progress"] = {
            "percent": 0,
            "stage": "Queued",
            "message": "Waiting for a Kaggle GPU worker.",
            "live": False,
            "callback_configured": bool(
                current_app.config.get("KAGGLE_CALLBACK_URL")
                and current_app.config.get("KAGGLE_CALLBACK_TOKEN")
            ),
            "completed_segments": 0,
            "total_segments": segment_count,
        }
        job.generation_params = params
        db.session.add(job)
        db.session.commit()

        app = current_app._get_current_object()
        app.config["EXECUTOR"].submit(
            run_pipeline_in_app_context, app, job.id)
        flash("Your video job has been queued successfully.", "success")
        return redirect(url_for("jobs.detail", job_id=job.id))

    return render_template("generate.html", **form_context)
