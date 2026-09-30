import hashlib
import os
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app import db
from app.models import PlatformCredential


YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


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


def get_youtube_credential(user_id: int, account_label: str = "default") -> PlatformCredential | None:
    return PlatformCredential.query.filter_by(user_id=user_id, platform="youtube", account_label=account_label).first()


def _get_valid_service(user_id: int, account_label: str = "default"):
    credential = get_youtube_credential(user_id, account_label)
    if credential is None:
        raise RuntimeError("No YouTube OAuth credential is configured.")

    access_token = _decrypt(credential.access_token_encrypted)
    refresh_token = _decrypt(credential.refresh_token_encrypted)
    if not refresh_token:
        raise RuntimeError("YouTube refresh token is missing.")

    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("YOUTUBE_CLIENT_ID", ""),
        client_secret=os.getenv("YOUTUBE_CLIENT_SECRET", ""),
        scopes=credential.scopes or YOUTUBE_SCOPES,
    )
    if creds.expired or not creds.valid:
        creds.refresh(Request())
        credential.access_token_encrypted = _encrypt(creds.token)
        credential.expires_at = datetime.now(
            timezone.utc) + timedelta(seconds=max(3600, creds.expiry_seconds or 3600))
        db.session.commit()
    return build("youtube", "v3", credentials=creds)


def upload_video(video_path: str, title: str, description: str, hashtags: list[str], user_id: int, privacy: str = "private"):
    service = _get_valid_service(user_id)
    body = {
        "snippet": {
            "title": title[:100],
            "description": description,
            "tags": [tag.strip("#") for tag in hashtags[:15]],
        },
        "status": {"privacyStatus": privacy},
    }
    media = MediaFileUpload(video_path, resumable=True,
                            chunksize=1024 * 1024, mimetype="video/mp4")
    request = service.videos().insert(
        part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            continue
    return {"status": "uploaded", "video_id": response.get("id"), "privacy": privacy}
