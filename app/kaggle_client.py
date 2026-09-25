import json
import inspect
import os
import re
import uuid
from pathlib import Path
from pprint import pformat

try:
    from kaggle import KaggleApi
    from kaggle.api_client import ApiClient
    from kaggle.configuration import Configuration
except Exception:  # pragma: no cover - Kaggle config is optional during local scaffolding
    KaggleApi = None
    ApiClient = None
    Configuration = None

from app.kaggle_accounts import credentials_for_job
from app.storage import upload_video


def _api(credentials=None):
    if KaggleApi is None:
        return None
    try:
        if credentials is None:
            username = os.getenv("KAGGLE_USERNAME")
            key = os.getenv("KAGGLE_KEY")
        else:
            username, key = credentials["username"], credentials["key"]
        if not username or not key:
            return None
        configuration = Configuration()
        configuration.username = username
        configuration.password = key
        api = KaggleApi(ApiClient(configuration))
        api.config_values = {"username": username, "key": key}
        return api
    except Exception:
        return None


def _runtime_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    runtime_dir = root / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir


def _download_kernel_output(api, kernel_id: str, output_dir: Path, pattern: str):
    """Download output and return its paths across Kaggle client versions.

    Kaggle client releases differ in whether ``kernels_output`` accepts a file
    filter. The v1.6 client returns a list of every downloaded path (not a
    ``(files, metadata)`` pair), so normalize its result here.
    """
    output_method = api.kernels_output
    if "file_pattern" in inspect.signature(output_method).parameters:
        result = output_method(
            kernel_id, path=str(output_dir), file_pattern=pattern
        )
    else:
        result = output_method(kernel_id, path=str(output_dir))

    # Some wrappers return (files, metadata), while KaggleApi itself returns
    # files directly. Never unpack the path list as a fixed-size tuple.
    if isinstance(result, tuple):
        result = result[0] if result else []
    if result is None:
        return []
    return list(result)


def _set_kaggle_status(job, status: str) -> None:
    # SQLAlchemy does not detect in-place edits to a plain JSON dictionary.
    job.generation_params = {
        **(job.generation_params or {}),
        "_kaggle_status": status,
    }


def _resolved_job_params(job) -> dict:
    """Build the self-contained parameters consumed by the checked-in H3 notebook."""
    params = dict(job.generation_params or {})
    params["job_id"] = job.job_id
    params["prompt"] = (job.prompt_text or params.get("prompt") or "").strip()
    params.setdefault("segment_prompts", [])
    callback_url = os.getenv("KAGGLE_CALLBACK_URL", "").strip().rstrip("/")
    callback_token = os.getenv("KAGGLE_CALLBACK_TOKEN", "").strip()
    if callback_url and callback_token:
        params["automation_progress_url"] = f"{callback_url}/{job.job_id}"
        params["automation_progress_token"] = callback_token
    return params


def _write_params(job) -> Path:
    runtime_dir = _runtime_dir()
    params_path = runtime_dir / f"params_{job.job_id}.json"
    with params_path.open("w", encoding="utf-8") as fh:
        json.dump(_resolved_job_params(job), fh, indent=2, sort_keys=True)
    return params_path


def _embed_job_params(notebook_json: dict, params: dict) -> None:
    """Embed exactly one Flask job into a clean copy of the checked-in notebook."""
    marker = "PARAMS.update(known_overrides)"
    override = (
        "\n# Injected by the automation service for this specific queued job.\n"
        "PARAMS.update(" + pformat(params, sort_dicts=True) + ")\n"
    )
    for cell in notebook_json.get("cells", []):
        source = cell.get("source", [])
        source_text = source if isinstance(source, str) else "".join(source)
        if marker in source_text:
            cell["source"] = source_text.replace(marker, marker + override, 1).splitlines(keepends=True)
            return
    raise RuntimeError("Kaggle notebook has no automation parameter loader.")


def _build_kaggle_push_folder(params_path: Path, kernel_id: str, job_id: str) -> Path:
    runtime_dir = _runtime_dir()
    push_dir = runtime_dir / "kaggle_push" / job_id
    # Render starts with a clean, ephemeral filesystem, so the kaggle_push
    # parent will not exist on a fresh deploy (or after a restart).
    push_dir.mkdir(parents=True, exist_ok=True)

    notebook_dir = Path(__file__).resolve().parent.parent / "notebook"
    notebooks = sorted(notebook_dir.glob("*.ipynb"))
    if len(notebooks) != 1:
        raise RuntimeError(
            f"Expected one source notebook in {notebook_dir}; found {len(notebooks)}."
        )
    notebook_path = notebooks[0]
    pushed_notebook_name = "h3_automation.ipynb"
    notebook_json = json.loads(notebook_path.read_text(encoding="utf-8"))
    params = json.loads(params_path.read_text(encoding="utf-8"))
    _embed_job_params(notebook_json, params)
    # Remove saved notebook outputs so prior runs and embedded previews are
    # not republished with this job, and keep the push payload compact.
    for cell in notebook_json.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    (push_dir / pushed_notebook_name).write_text(
        json.dumps(notebook_json, ensure_ascii=True, indent=1),
        encoding="ascii",
    )

    kernel_title = kernel_id.rsplit("/", 1)[-1]
    gpu_enabled = str(os.getenv("KAGGLE_ENABLE_GPU", "true")).lower() == "true"
    gpu_type = os.getenv("KAGGLE_GPU_TYPE", "T4")

    metadata = {
        "id": kernel_id,
        "title": kernel_title,
        "code_file": pushed_notebook_name,
        "language": "python",
        "kernel_type": "notebook",
        "is_private": "true",
        "enable_gpu": "true" if gpu_enabled else "false",
        "enable_tpu": "false",
        "enable_internet": "true",
        "dataset_sources": [],
        "competition_sources": [],
        "kernel_sources": [],
        "model_sources": [],
    }
    if gpu_enabled and gpu_type:
        metadata["gpu_type"] = gpu_type

    metadata_path = push_dir / "kernel-metadata.json"
    with metadata_path.open("w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)

    return push_dir


def trigger_generation(job) -> None:
    if not job.job_id:
        job.job_id = str(uuid.uuid4())
    credentials = credentials_for_job(job)
    api = _api(credentials)
    _set_kaggle_status(job, "queued")
    params_path = _write_params(job)

    if api is None:
        raise RuntimeError(
            "Kaggle API authentication failed or credentials are missing. Set KAGGLE_USERNAME and KAGGLE_KEY."
        )

    push_dir = _build_kaggle_push_folder(params_path, credentials["kernel_id"], job.job_id)
    try:
        api.kernels_push(str(push_dir))
    except Exception as exc:
        job.error_message = f"Kaggle push failed: {exc}"
        _set_kaggle_status(job, "failed")
        raise RuntimeError(job.error_message) from exc

    _set_kaggle_status(job, "running")


def poll_status(job) -> str:
    status = str(job.generation_params.get("_kaggle_status", "queued")).lower()
    try:
        credentials = credentials_for_job(job)
        api = _api(credentials)
        if api is None:
            raise RuntimeError("Kaggle API authentication failed.")
        raw = api.kernels_status(credentials["kernel_id"])
        failure_message = None
        if isinstance(raw, dict):
            live_status = str(raw.get("status", status)).lower()
            failure_message = raw.get("failureMessage")
            if failure_message:
                live_status = "failed"
        else:
            live_status = str(raw).lower()

        mapping = {
            "queued": "queued",
            "pending": "queued",
            "starting": "running",
            "running": "running",
            "processing": "running",
            "complete": "completed",
            "completed": "completed",
            "finished": "completed",
            "failed": "failed",
            "error": "failed",
            "timeout": "failed",
            "gpu quota exhausted": "failed",
            "quota exhausted": "failed",
        }
        normalized = mapping.get(live_status, status)
        _set_kaggle_status(job, normalized)
        if normalized == "failed":
            job.error_message = str(failure_message or "Kaggle kernel reported a failure.")
            job.log_tail = job.error_message
        return normalized
    except Exception as exc:
        _set_kaggle_status(job, "failed")
        job.error_message = f"Kaggle status check failed: {exc}"
        return "failed"


def fetch_output(job) -> None:
    credentials = credentials_for_job(job)
    kernel_id = credentials["kernel_id"]
    api = _api(credentials)
    if api is None:
        raise RuntimeError("Kaggle API credentials are missing.")

    output_dir = _runtime_dir() / "kaggle_outputs" / job.job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        files = _download_kernel_output(
            api, kernel_id, output_dir, r"(^|/)automation_manifest\.json$"
        )
    except Exception as exc:
        raise RuntimeError(f"Kaggle manifest download failed: {exc}") from exc

    manifest_path = next((Path(f) for f in files if Path(f).name == "automation_manifest.json"), None)
    if manifest_path is None or not manifest_path.is_file():
        raise RuntimeError("Kaggle output did not include automation_manifest.json.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "success":
        raise RuntimeError("Kaggle automation manifest does not report success.")
    if manifest.get("job_id") != job.job_id:
        raise RuntimeError("Kaggle output belongs to a different job; refusing stale artifacts.")
    kernel_log = next(
        (Path(f) for f in files if Path(f).suffix.lower() == ".log"), None
    )
    if kernel_log and kernel_log.is_file():
        job.log_tail = kernel_log.read_text(encoding="utf-8", errors="replace")[-12000:]

    video_info = manifest.get("final_video")
    if not isinstance(video_info, dict) or not video_info.get("path"):
        raise RuntimeError("Kaggle manifest does not name a final video.")
    remote_video_path = str(video_info["path"])
    video_name = Path(remote_video_path).name
    if Path(video_name).suffix.lower() not in {".mp4", ".webm", ".mov", ".mkv"}:
        raise RuntimeError("Kaggle manifest final video has an unsupported format.")

    try:
        video_files = _download_kernel_output(
            api, kernel_id, output_dir, rf"(^|/){re.escape(video_name)}$"
        )
    except Exception as exc:
        raise RuntimeError(f"Kaggle video download failed: {exc}") from exc
    video_path = next((Path(f) for f in video_files if Path(f).name == video_name), None)
    if video_path is None or not video_path.is_file() or video_path.stat().st_size == 0:
        raise RuntimeError("Kaggle output did not include the notebook's final video.")
    expected_size = video_info.get("size_bytes")
    if expected_size and video_path.stat().st_size != int(expected_size):
        raise RuntimeError("Downloaded MP4 size does not match the Kaggle manifest.")

    storage_path = upload_video(str(video_path), f"jobs/{job.job_id}/{video_name}")
    if storage_path:
        manifest["storage_path"] = storage_path
        job.video_storage_path = storage_path
    manifest["local_final_video"] = str(video_path.resolve())
    job.manifest_json = manifest
