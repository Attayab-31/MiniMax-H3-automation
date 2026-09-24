import os

from cryptography.fernet import Fernet, InvalidToken

from app.models import KaggleAccount


def _fernet() -> Fernet:
    key = (os.getenv("FERNET_KEY") or "").strip()
    if not key:
        raise RuntimeError("Set FERNET_KEY before saving Kaggle accounts.")
    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("FERNET_KEY must be a valid Fernet key.") from exc


def encrypt_api_key(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeEncodeError) as exc:
        raise RuntimeError("Could not decrypt this Kaggle account. Check FERNET_KEY.") from exc


def credentials_for_job(job) -> dict:
    if job.kaggle_account_id is None:
        username = (os.getenv("KAGGLE_USERNAME") or "").strip()
        key = (os.getenv("KAGGLE_KEY") or "").strip()
        kernel_id = (os.getenv("KAGGLE_KERNEL_ID") or "").strip()
        if not kernel_id and username:
            kernel_id = f"{username}/minimax-h3-automation"
        if not username or not key or not kernel_id:
            raise RuntimeError("Select a configured Kaggle account before starting this job.")
        return {"username": username, "key": key, "kernel_id": kernel_id,
                "account_key": "environment", "label": "Environment account"}

    account = KaggleAccount.query.filter_by(id=job.kaggle_account_id).first()
    if account is None:
        raise RuntimeError("The Kaggle account assigned to this job is unavailable.")
    return {
        "username": account.username,
        "key": decrypt_api_key(account.api_key_encrypted),
        "kernel_id": account.kernel_id,
        "account_key": str(account.id),
        "label": account.label,
    }
