import hashlib
import os
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
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


def get_youtube_credential(account_label: str = "default") -> PlatformCredential | None:
    return PlatformCredential.query.filter_by(platform="youtube", account_label=account_label).first()


def start_oauth_flow() -> str:
    secrets_file = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE")
    if not secrets_file:
        raise RuntimeError("YOUTUBE_CLIENT_SECRETS_FILE is not configured.")
    flow = InstalledAppFlow.from_client_secrets_file(
        secrets_file, YOUTUBE_SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    auth_url, _ = flow.authorization_url(
        access_type="offline", include_granted_scopes="true")
    return auth_url


def complete_oauth_flow(code: str, account_label: str = "default") -> PlatformCredential:
    secrets_file = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE")
    if not secrets_file:
        raise RuntimeError("YOUTUBE_CLIENT_SECRETS_FILE is not configured.")
    flow = InstalledAppFlow.from_client_secrets_file(
        secrets_file, YOUTUBE_SCOPES)
    flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
    flow.fetch_token(code=code)
    credentials = flow.credentials

    record = PlatformCredential.query.filter_by(
        platform="youtube", account_label=account_label).first()
    if record is None:
        record = PlatformCredential(
            platform="youtube", account_label=account_label, scopes=list(YOUTUBE_SCOPES))
        db.session.add(record)

    record.access_token_encrypted = _encrypt(credentials.token)
    record.refresh_token_encrypted = _encrypt(credentials.refresh_token)
    record.expires_at = datetime.now(
        timezone.utc) + timedelta(seconds=credentials.expiry_seconds or 3600)
    record.scopes = list(YOUTUBE_SCOPES)
    db.session.commit()
    return record


def _get_valid_service(account_label: str = "default"):
    credential = get_youtube_credential(account_label)
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


def upload_video(video_path: str, title: str, description: str, hashtags: list[str], privacy: str = "private"):
    service = _get_valid_service()
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
