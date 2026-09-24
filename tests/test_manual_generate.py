import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import create_app, db
from app.kaggle_client import poll_status, trigger_generation
from app.models import GenerationJob, Schedule
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

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_manual_generation_creates_job_and_queues_pipeline(self):
        self.client.post(
            "/login", data={"username": "admin", "password": "BrightHorizon"}, follow_redirects=True)
        self.app.config["EXECUTOR"].submit = Mock()

        response = self.client.post(
            "/generate",
            data={
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


if __name__ == "__main__":
    unittest.main()
