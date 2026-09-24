import hashlib
import json
import os
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from cryptography.fernet import Fernet

from app import db
from app.models import PlatformCredential


def _fernet() -> Fernet:
    raw = (os.getenv("FERNET_KEY") or "").strip()
    if not raw:
        raise RuntimeError("FERNET_KEY is not configured.")
    if len(raw) >= 44:
        key = raw.encode()
    else:
        key = urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def _encrypt(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")


def _decrypt(value: str | None) -> str | None:
    if value is None:
        return None
    return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")


def get_tiktok_credential(account_label: str = "default") -> PlatformCredential | None:
    return PlatformCredential.query.filter_by(platform="tiktok", account_label=account_label).first()


def refresh_access_token(account_label: str = "default") -> PlatformCredential:
    credential = get_tiktok_credential(account_label)
    if credential is None:
        credential = PlatformCredential(
            platform="tiktok", account_label=account_label, scopes=["upload"])
        db.session.add(credential)

    refresh_token = _decrypt(
        credential.refresh_token_encrypted) if credential.refresh_token_encrypted else os.getenv("TIKTOK_REFRESH_TOKEN")
    if not refresh_token:
        raise RuntimeError("No TikTok refresh token is stored.")

    response = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token",
        data={
            "client_key": os.getenv("TIKTOK_CLIENT_KEY"),
            "client_secret": os.getenv("TIKTOK_CLIENT_SECRET"),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    access_token = payload.get("access_token")
    new_refresh_token = payload.get("refresh_token") or refresh_token
    credential.access_token_encrypted = _encrypt(access_token)
    credential.refresh_token_encrypted = _encrypt(new_refresh_token)
    credential.expires_at = datetime.now(timezone.utc) + timedelta(hours=23)
    credential.scopes = payload.get("scopes") or ["upload"]
    db.session.commit()
    return credential


def get_valid_access_token(account_label: str = "default") -> str:
    credential = get_tiktok_credential(account_label)
    if credential is None:
        raise RuntimeError("No TikTok credentials are configured.")
    now = datetime.now(timezone.utc)
    if credential.expires_at is None or credential.expires_at <= now + timedelta(hours=1):
        credential = refresh_access_token(account_label)
    token = _decrypt(credential.access_token_encrypted)
    if not token:
        raise RuntimeError("TikTok access token is missing.")
    return token


def publish_video(video_path: str, title: str, description: str, hashtags: list[str], account_label: str = "default") -> dict:
    token = get_valid_access_token(account_label)
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}

    creator_info_response = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/creator_info/query/",
        headers=headers,
        json={"fields": ["avatar_url", "username"]},
        timeout=30,
    )
    creator_info_response.raise_for_status()

    file_name = Path(video_path).name
    init_response = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers=headers,
        json={
            "post_info": {
                "title": title[:80],
                "privacy_level": "SELF_ONLY",
                "source": "FILE",
                "auto_caption": False,
                "disable_comment": False,
            },
            "video_info": {
                "video_size": str(Path(video_path).stat().st_size),
                "video_format": "mp4",
                "video_name": file_name,
            },
        },
        timeout=30,
    )
    init_response.raise_for_status()
    init_payload = init_response.json()
    upload_url = init_payload.get("data", {}).get("upload_url")
    if not upload_url:
        raise RuntimeError("TikTok video init did not return an upload URL.")

    with open(video_path, "rb") as fh:
        upload_response = requests.put(upload_url, data=fh, headers={
                                       "Content-Type": "video/mp4"}, timeout=120)
    upload_response.raise_for_status()

    status_payload = {"publish_id": init_payload.get(
        "data", {}).get("publish_id") or "pending"}
    for _ in range(12):
        status_response = requests.post(
            "https://open.tiktokapis.com/v2/post/publish/status/fetch/",
            headers=headers,
            json=status_payload,
            timeout=30,
        )
        status_response.raise_for_status()
        status_json = status_response.json()
        status = status_json.get("data", {}).get("status")
        if status in {"published", "failed", "error"}:
            return {
                "status": status,
                "publish_id": status_json.get("data", {}).get("publish_id"),
                "privacy": "SELF_ONLY",
                "caption": description,
            }
        import time
        time.sleep(5)

    return {"status": "pending", "publish_id": status_payload.get("publish_id"), "privacy": "SELF_ONLY", "caption": description}
