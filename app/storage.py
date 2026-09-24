from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

import requests
from flask import current_app


def _storage_config():
    base_url = current_app.config.get("SUPABASE_URL", "")
    service_key = current_app.config.get("SUPABASE_SERVICE_ROLE_KEY", "")
    bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "")
    if not (base_url or service_key):
        return None
    if not (base_url and service_key and bucket):
        raise RuntimeError("Set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and SUPABASE_STORAGE_BUCKET together.")
    return base_url, service_key, bucket


def upload_video(local_path: str, object_path: str) -> str | None:
    config = _storage_config()
    if config is None:
        return None
    base_url, service_key, bucket = config
    encoded_path = quote(object_path, safe="/")
    with open(local_path, "rb") as video:
        response = requests.post(
            f"{base_url}/storage/v1/object/{quote(bucket, safe='')}/{encoded_path}",
            headers={
                "Authorization": f"Bearer {service_key}",
                "apikey": service_key,
                "Content-Type": mimetypes.guess_type(local_path)[0] or "application/octet-stream",
                "x-upsert": "true",
            },
            data=video,
            timeout=(15, 900),
        )
    response.raise_for_status()
    return object_path


def delete_video(object_path: str) -> None:
    config = _storage_config()
    if config is None:
        raise RuntimeError("Supabase Storage is not configured for this deployment.")
    base_url, service_key, bucket = config
    response = requests.delete(
        f"{base_url}/storage/v1/object/{quote(bucket, safe='')}",
        headers={
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
            "Content-Type": "application/json",
        },
        json={"prefixes": [object_path]},
        timeout=30,
    )
    response.raise_for_status()


def signed_video_url(object_path: str, *, download: bool = False) -> str:
    config = _storage_config()
    if config is None:
        raise RuntimeError("Supabase Storage is not configured for this deployment.")
    base_url, service_key, bucket = config
    encoded_path = quote(object_path, safe="/")
    response = requests.post(
        f"{base_url}/storage/v1/object/sign/{quote(bucket, safe='')}/{encoded_path}",
        headers={
            "Authorization": f"Bearer {service_key}",
            "apikey": service_key,
            "Content-Type": "application/json",
        },
        json={"expiresIn": 600},
        timeout=20,
    )
    response.raise_for_status()
    signed_path = response.json().get("signedURL")
    if not signed_path:
        raise RuntimeError("Supabase Storage did not return a signed download URL.")
    url = signed_path if signed_path.startswith("http") else f"{base_url}/storage/v1{signed_path}"
    if download:
        parts = urlsplit(url)
        separator = "&" if parts.query else ""
        url = urlunsplit((parts.scheme, parts.netloc, parts.path,
                          parts.query + separator + urlencode({"download": "video.mp4"}), parts.fragment))
    return url


def download_video(object_path: str, destination: str) -> str:
    response = requests.get(signed_video_url(object_path), stream=True, timeout=(15, 300))
    response.raise_for_status()
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with temporary.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    output.write(chunk)
        temporary.replace(target)
    finally:
        response.close()
        if temporary.exists():
            temporary.unlink()
    return str(target)
