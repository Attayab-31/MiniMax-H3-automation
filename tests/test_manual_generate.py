import json
import os
import re
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import create_app, db
from app.kaggle_client import poll_status, trigger_generation
from app.models import GenerationJob, KaggleAccount, Schedule
from app.scheduler import _fire_schedule


class ManualGenerateRouteTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("ADMIN_USERNAME", "admin")
        os.environ.setdefault("ADMIN_PASSWORD", "BrightHorizon")
        os.environ.setdefault("FLASK_SECRET_KEY", "test-secret")

        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///:memory:"}):
            self.app = create_app()
        self.app.config.update(TESTING=True)

        with self.app.app_context():
            db.create_all()

        self.client = self.app.test_client()

    def _csrf_token(self, path: str) -> str:
        response = self.client.get(path)
        match = re.search(
            r'name="csrf_token" value="([^"]+)"',
            response.get_data(as_text=True),
        )
        self.assertIsNotNone(match, f"No CSRF field found in {path}.")
        return match.group(1)

    def _login(self):
        token = self._csrf_token("/login")
        return self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "username": "admin",
                "password": "BrightHorizon",
            },
            follow_redirects=True,
        )

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_manual_generation_creates_job_and_queues_pipeline(self):
        self._login()
        self.app.config["EXECUTOR"].submit = Mock()

        token = self._csrf_token("/generate")
        response = self.client.post(
            "/generate",
            data={
                "csrf_token": token,
                "niche": "productivity desk setups",
                "prompt": "A clean desk with warm lights and a laptop.",
                "resolution_profile": "portrait",
                "duration_seconds": "30",
                "clip_duration_seconds": "10",
                "customize_segments": "on",
                "segment_prompts": ["Show the desk", "Reveal the room", "Fade to morning"],
                "seed": "42",
                "use_turbo_lora": "on",
                "turbo_steps": "4",
                "auto_fallback": "on",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            job = GenerationJob.query.order_by(GenerationJob.id.desc()).first()
            self.assertIsNotNone(job)
            self.assertIn(job.status, {
                "queued", "pushing", "running", "downloading", "posting", "completed", "failed"})
            self.assertEqual(job.mode, "manual")
            self.assertEqual(job.target_platforms, [])
            self.assertEqual(job.generation_params["custom_width"], 352)
            self.assertEqual(job.generation_params["custom_height"], 608)
            self.assertEqual(job.generation_params["chunk_seconds"], 10)
            self.assertEqual(len(job.generation_params["segment_prompts"]), 3)
            self.assertTrue(job.generation_params["segment_prompts"][0].endswith("Show the desk"))

    def test_pipeline_worker_runs_with_app_context(self):
        from app.pipeline import run_pipeline_in_app_context

        with patch("app.pipeline.trigger_generation") as trigger, \
                patch("app.pipeline.poll_status", return_value="completed"), \
                patch("app.pipeline.fetch_output"):
            with self.app.app_context():
                job = GenerationJob(
                    mode="manual",
                    status="queued",
                    target_platforms=[],
                    generation_params={},
                )
                db.session.add(job)
                db.session.commit()
                run_pipeline_in_app_context(self.app, job.id)

        with self.app.app_context():
            refreshed_job = db.session.get(GenerationJob, job.id)
            self.assertEqual(refreshed_job.status, "completed")
        trigger.assert_called_once()

    def test_failed_job_can_retry_kaggle_video_download(self):
        self._login()
        self.app.config["EXECUTOR"].submit = Mock()
        with self.app.app_context():
            job = GenerationJob(
                mode="manual",
                status="failed",
                error_message="Kaggle output download failed",
                generation_params={},
                target_platforms=[],
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        token = self._csrf_token(f"/jobs/{job_id}")
        response = self.client.post(
            f"/jobs/{job_id}/retry-video-download",
            data={"csrf_token": token},
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            job = db.session.get(GenerationJob, job_id)
            self.assertEqual(job.status, "downloading")
            self.assertIsNone(job.error_message)
        self.app.config["EXECUTOR"].submit.assert_called_once()

    def test_custom_schedule_sizes_are_preserved_for_generations(self):
        with self.app.app_context():
            schedule = Schedule(
                name="Custom size run",
                niche="cinematic lifestyle",
                time_of_day="09:00",
                timezone="UTC",
                enabled=True,
                target_platforms=["youtube"],
                resolution_preset="Custom",
                custom_width=720,
                custom_height=405,
                duration_seconds=15,
                video_crf=18,
                video_preset="slow",
            )
            db.session.add(schedule)
            db.session.commit()

            self.app.config["EXECUTOR"].submit = Mock()
            _fire_schedule(self.app, schedule.id)

            job = GenerationJob.query.filter_by(
                schedule_id=schedule.id).order_by(GenerationJob.id.desc()).first()
            self.assertIsNotNone(job)
            self.assertEqual(
                job.generation_params["resolution_preset"], "Custom")
            self.assertEqual(job.generation_params["custom_width"], 720)
            self.assertEqual(job.generation_params["custom_height"], 405)

    def test_trigger_generation_builds_gpu_enabled_kaggle_metadata(self):
        fake_api = Mock()
        fake_api.kernels_push = Mock()

        with patch("app.kaggle_client._api", return_value=fake_api), \
                patch.dict(os.environ, {
                    "KAGGLE_USERNAME": "demo-user",
                    "KAGGLE_KEY": "demo-key",
                    "KAGGLE_KERNEL_ID": "demo-user/minimax-h3-automation",
                }, clear=False):
            job = GenerationJob(
                mode="manual",
                status="queued",
                target_platforms=["youtube"],
                generation_params={
                    "prompt": "A lantern floats over a quiet lake.",
                    "resolution_preset": "Custom",
                    "custom_width": 352,
                    "custom_height": 608,
                    "duration_seconds": 47.0,
                    "chunk_seconds": 10.0,
                    "segment_prompts": [],
                    "use_turbo_lora": True,
                    "turbo_steps": 4,
                    "steps": 4},
            )

            trigger_generation(job)

        push_dir = fake_api.kernels_push.call_args[0][0]
        metadata_path = Path(push_dir) / "kernel-metadata.json"
        self.assertTrue(metadata_path.exists())
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["enable_gpu"], "true")
        self.assertEqual(metadata["enable_internet"], "true")
        self.assertEqual(metadata["is_private"], "true")
        self.assertEqual(metadata["dataset_sources"], [])

        notebook_path = Path(push_dir) / "h3_automation.ipynb"
        pushed_notebook = json.loads(notebook_path.read_text(encoding="utf-8"))
        parameter_cell = "".join(pushed_notebook["cells"][3]["source"])
        self.assertIn("'duration_seconds': 47.0", parameter_cell)
        self.assertIn("'resolution_preset': 'Custom'", parameter_cell)
        self.assertIn("A lantern floats over a quiet lake.", parameter_cell)
        self.assertIn("'job_id':", parameter_cell)
        compile(parameter_cell, str(notebook_path), "exec")

    def test_kaggle_progress_callback_requires_token_and_updates_job(self):
        with self.app.app_context():
            job = GenerationJob(
                mode="manual",
                status="running",
                generation_params={"_progress": {"total_segments": 3}},
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.job_id

        payload = {
            "stage": "Sampling H3 video + stereo audio",
            "message": "Elapsed: 2.4 min",
            "segment_index": 1,
            "completed_segments": 1,
            "total_segments": 3,
            "segment_progress": 0.5,
        }
        with patch.dict(os.environ, {"KAGGLE_CALLBACK_TOKEN": "test-progress-token"}):
            rejected = self.client.post(f"/api/kaggle/progress/{job_id}", json=payload)
            self.assertEqual(rejected.status_code, 401)
            accepted = self.client.post(
                f"/api/kaggle/progress/{job_id}",
                json=payload,
                headers={"X-Kaggle-Progress-Token": "test-progress-token"},
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json["percent"], 50)
        with self.app.app_context():
            job = GenerationJob.query.filter_by(job_id=job_id).one()
            self.assertEqual(job.generation_params["_progress"]["current_segment"], 2)

    def test_generate_rejects_missing_csrf_token(self):
        self._login()
        response = self.client.post(
            "/generate",
            data={"prompt": "A test prompt", "kaggle_account_id": "environment"},
        )
        self.assertEqual(response.status_code, 400)

    def test_my_videos_lists_bucket_backed_jobs(self):
        self._login()
        with self.app.app_context():
            job = GenerationJob(
                mode="manual",
                status="completed",
                niche="rainy city at night",
                manifest_json={
                    "storage_path": "jobs/test-job/rainy-city.mp4",
                    "final_video": {"duration_seconds": 12},
                },
                video_storage_path="jobs/test-job/rainy-city.mp4",
                generation_params={},
                target_platforms=[],
            )
            db.session.add(job)
            db.session.commit()

        response = self.client.get("/videos")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"My Videos", response.data)
        self.assertIn(b"rainy city at night", response.data)
        self.assertIn(b"Saved</span>", response.data)
        self.assertIn(b"Delete video</button>", response.data)

    def test_delete_video_removes_storage_reference_and_keeps_job(self):
        self._login()
        with self.app.app_context():
            job = GenerationJob(
                mode="manual",
                status="completed",
                niche="quiet forest",
                manifest_json={"storage_path": "jobs/test-job/forest.mp4"},
                video_storage_path="jobs/test-job/forest.mp4",
                generation_params={},
                target_platforms=[],
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id
            job_uuid = job.job_id

        token = self._csrf_token("/videos")
        with patch("app.routes.jobs.delete_stored_video") as delete_storage:
            response = self.client.post(
                f"/jobs/{job_id}/delete-video",
                data={"csrf_token": token},
            )

        self.assertEqual(response.status_code, 302)
        delete_storage.assert_called_once_with("jobs/test-job/forest.mp4")
        with self.app.app_context():
            job = db.session.get(GenerationJob, job_id)
            self.assertIsNotNone(job)
            self.assertIsNone(job.video_storage_path)
            self.assertNotIn("storage_path", job.manifest_json)
            self.assertIn("video_deleted_at", job.manifest_json)

    def test_delete_prompts_keeps_video_and_job(self):
        self._login()
        with self.app.app_context():
            job = GenerationJob(
                mode="manual",
                status="completed",
                niche="city lights",
                prompt_text="A red car drives through a neon street.",
                generation_params={
                    "niche": "city lights",
                    "prompt": "A red car drives through a neon street.",
                    "segment_prompts": ["Show the car"],
                    "creative_brief": {"tone": "dramatic"},
                    "steps": 20,
                },
                manifest_json={"storage_path": "jobs/test-job/city.mp4"},
                video_storage_path="jobs/test-job/city.mp4",
                target_platforms=[],
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        token = self._csrf_token(f"/jobs/{job_id}")
        with patch("app.routes.jobs._remove_local_prompt_artifacts"):
            response = self.client.post(
                f"/jobs/{job_id}/delete-prompts", data={"csrf_token": token}
            )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            job = db.session.get(GenerationJob, job_id)
            self.assertIsNotNone(job)
            self.assertIsNone(job.prompt_text)
            self.assertIsNone(job.niche)
            self.assertEqual(job.video_storage_path, "jobs/test-job/city.mp4")
            self.assertNotIn("segment_prompts", job.generation_params)
            self.assertEqual(job.generation_params["steps"], 20)

    def test_delete_everything_removes_job_and_calls_storage(self):
        self._login()
        with self.app.app_context():
            job = GenerationJob(
                mode="manual",
                status="completed",
                prompt_text="A quiet ocean at sunrise.",
                generation_params={"prompt": "A quiet ocean at sunrise."},
                manifest_json={"storage_path": "jobs/test-job/ocean.mp4"},
                video_storage_path="jobs/test-job/ocean.mp4",
                target_platforms=[],
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id
            job_uuid = job.job_id

        token = self._csrf_token(f"/jobs/{job_id}")
        with patch("app.routes.jobs.delete_stored_video") as delete_storage, \
                patch("app.routes.jobs._remove_local_prompt_artifacts") as delete_local:
            response = self.client.post(
                f"/jobs/{job_id}/delete-everything", data={"csrf_token": token}
            )
        self.assertEqual(response.status_code, 302)
        delete_storage.assert_called_once_with("jobs/test-job/ocean.mp4")
        delete_local.assert_called_once()
        self.assertEqual(delete_local.call_args.args[0], job_uuid)
        self.assertTrue(delete_local.call_args.kwargs["remove_video"])
        with self.app.app_context():
            self.assertIsNone(db.session.get(GenerationJob, job_id))

    def test_delete_everything_keeps_job_when_storage_delete_fails(self):
        self._login()
        with self.app.app_context():
            job = GenerationJob(
                mode="manual", status="completed", prompt_text="Keep me if storage fails",
                generation_params={}, manifest_json={"storage_path": "jobs/failed/video.mp4"},
                video_storage_path="jobs/failed/video.mp4", target_platforms=[],
            )
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        token = self._csrf_token(f"/jobs/{job_id}")
        with patch("app.routes.jobs.delete_stored_video", side_effect=RuntimeError("storage unavailable")):
            response = self.client.post(
                f"/jobs/{job_id}/delete-everything", data={"csrf_token": token}
            )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            job = db.session.get(GenerationJob, job_id)
            self.assertIsNotNone(job)
            self.assertEqual(job.prompt_text, "Keep me if storage fails")

    def test_delete_kaggle_credentials_pauses_schedules_and_keeps_jobs(self):
        self._login()
        with self.app.app_context():
            account = KaggleAccount(
                label="Secondary", username="secondary-user",
                api_key_encrypted="encrypted-placeholder",
                kernel_id="secondary-user/h3-automation-secondary", enabled=True,
            )
            db.session.add(account)
            db.session.flush()
            schedule = Schedule(
                name="Secondary schedule", niche="nature", time_of_day="09:00",
                timezone="UTC", enabled=True, kaggle_account_id=account.id,
                target_platforms=[],
            )
            job = GenerationJob(
                mode="manual", status="completed", kaggle_account_id=account.id,
                kaggle_account_name=account.label, generation_params={}, target_platforms=[],
            )
            db.session.add_all([schedule, job])
            db.session.commit()
            account_id, schedule_id, job_id = account.id, schedule.id, job.id

        token = self._csrf_token("/settings")
        response = self.client.post(
            f"/settings/kaggle-accounts/{account_id}/delete", data={"csrf_token": token}
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(db.session.get(KaggleAccount, account_id))
            schedule = db.session.get(Schedule, schedule_id)
            job = db.session.get(GenerationJob, job_id)
            self.assertFalse(schedule.enabled)
            self.assertIsNone(schedule.kaggle_account_id)
            self.assertIsNone(job.kaggle_account_id)
            self.assertEqual(job.kaggle_account_name, "Secondary")

    def test_delete_schedule_removes_template_and_keeps_job_history(self):
        self._login()
        with self.app.app_context():
            schedule = Schedule(
                name="Daily prompt", niche="wildlife", style_notes="A red fox",
                time_of_day="09:00", timezone="UTC", enabled=True,
                target_platforms=[],
            )
            db.session.add(schedule)
            db.session.flush()
            job = GenerationJob(
                mode="scheduled", status="completed", schedule_id=schedule.id,
                niche="wildlife", prompt_text="A red fox walks through snow.",
                generation_params={}, target_platforms=[],
            )
            db.session.add(job)
            db.session.commit()
            schedule_id, job_id = schedule.id, job.id

        token = self._csrf_token(f"/schedules/{schedule_id}")
        response = self.client.post(
            f"/schedules/{schedule_id}/delete", data={"csrf_token": token}
        )
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Schedule, schedule_id))
            job = db.session.get(GenerationJob, job_id)
            self.assertIsNotNone(job)
            self.assertIsNone(job.schedule_id)
            self.assertEqual(job.prompt_text, "A red fox walks through snow.")


if __name__ == "__main__":
    unittest.main()
