#!/usr/bin/env python3
"""
Generic file uploader to Google Cloud Storage.
Auto-detects content type from file extension.
"""
import os
from datetime import datetime

CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".flac": "audio/flac",
    ".ogg": "audio/ogg",
}

GCS_BUCKET = os.environ.get("GCS_BUCKET", "dramaland-public")
GCS_BASE_PATH = os.environ.get("GCS_BASE_PATH", "ugc_media")

CREDENTIAL_PATHS = [
    "/workspace/gcs-credentials.json",
    "/workspace/handler/gcs-credentials.json",
    "/gcs-credentials.json",
]


def _get_client():
    from google.cloud import storage
    from google.oauth2 import service_account

    creds_path = None
    for p in CREDENTIAL_PATHS:
        if os.path.exists(p):
            creds_path = p
            break

    env_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path and env_creds and os.path.exists(env_creds):
        creds_path = env_creds

    if not creds_path:
        raise FileNotFoundError(
            f"GCS credentials not found. Tried: {CREDENTIAL_PATHS}"
        )

    credentials = service_account.Credentials.from_service_account_file(creds_path)
    return storage.Client(credentials=credentials, project=credentials.project_id)


def upload_file(local_path, job_id=None, subfolder="outputs"):
    """
    Upload any file to GCS. Auto-detects content type.

    Returns:
        dict with success, gcs_url, public_url, filename, size_bytes, error
    """
    try:
        if not os.path.exists(local_path):
            return _fail(f"File not found: {local_path}")

        file_size = os.path.getsize(local_path)
        original = os.path.basename(local_path)
        ext = os.path.splitext(original)[1] or ".bin"
        name = os.path.splitext(original)[0]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_name = f"{timestamp}_{name}{ext}"

        if job_id:
            gcs_path = f"{GCS_BASE_PATH}/{job_id}/{subfolder}/{unique_name}"
        else:
            date_path = datetime.now().strftime("%Y/%m/%d")
            gcs_path = f"{GCS_BASE_PATH}/{date_path}/{subfolder}/{unique_name}"

        client = _get_client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(gcs_path)
        blob.content_type = CONTENT_TYPES.get(ext.lower(), "application/octet-stream")

        print(f"Uploading to GCS: {gcs_path} ({file_size / 1024 / 1024:.1f} MB)")
        blob.upload_from_filename(local_path)

        gcs_url = f"gs://{GCS_BUCKET}/{gcs_path}"
        public_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_path}"
        print(f"Uploaded: {public_url}")

        return {
            "success": True,
            "gcs_url": gcs_url,
            "public_url": public_url,
            "filename": unique_name,
            "size_bytes": file_size,
            "error": None,
        }

    except Exception as e:
        return _fail(str(e))


def delete_local_file(path):
    """Delete local file after upload."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Warning: could not delete {path}: {e}")


def _fail(msg):
    return {
        "success": False,
        "gcs_url": None,
        "public_url": None,
        "filename": None,
        "size_bytes": None,
        "error": msg,
    }
