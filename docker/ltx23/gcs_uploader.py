#!/usr/bin/env python3
"""
GCS Uploader - ltx23 自持副本，与 pod_files 独立
"""
import os
from datetime import datetime
from google.cloud import storage
from google.oauth2 import service_account

GCS_BUCKET = "dramaland-public"
GCS_BASE_PATH = "ugc_media"
SERVICE_ACCOUNT_PATHS = [
    "/workspace/gcs-credentials.json",
    "/gcs-credentials.json",
]


def get_gcs_client():
    creds_path = None
    for path in SERVICE_ACCOUNT_PATHS:
        if os.path.exists(path):
            creds_path = path
            break
    if not creds_path:
        env_creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if env_creds and os.path.exists(env_creds):
            creds_path = env_creds
    if not creds_path:
        raise FileNotFoundError(f"GCS credentials not found")
    credentials = service_account.Credentials.from_service_account_file(creds_path)
    return storage.Client(credentials=credentials, project=credentials.project_id)


def upload_video_to_gcs(video_path: str, job_id: str = None, subfolder: str = "videos") -> dict:
    try:
        if not os.path.exists(video_path):
            return {"success": False, "error": f"File not found: {video_path}"}
        file_size = os.path.getsize(video_path)
        original_filename = os.path.basename(video_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_part = os.path.splitext(original_filename)[0]
        ext = os.path.splitext(original_filename)[1] or ".mp4"
        unique_filename = f"{timestamp}_{name_part}{ext}"
        if job_id:
            gcs_path = f"{GCS_BASE_PATH}/{job_id}/{subfolder}/{unique_filename}"
        else:
            date_path = datetime.now().strftime("%Y/%m/%d")
            gcs_path = f"{GCS_BASE_PATH}/{date_path}/{subfolder}/{unique_filename}"
        client = get_gcs_client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(gcs_path)
        blob.content_type = "video/mp4"
        blob.upload_from_filename(video_path)
        gcs_url = f"gs://{GCS_BUCKET}/{gcs_path}"
        public_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{gcs_path}"
        return {"success": True, "gcs_url": gcs_url, "public_url": public_url, "filename": unique_filename, "size_bytes": file_size, "error": None}
    except Exception as e:
        return {"success": False, "gcs_url": None, "public_url": None, "filename": None, "size_bytes": None, "error": str(e)}


def delete_local_video(video_path: str) -> bool:
    try:
        if os.path.exists(video_path):
            os.remove(video_path)
            return True
    except Exception:
        pass
    return False
