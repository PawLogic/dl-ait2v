#!/usr/bin/env python3
"""
Generic media downloader for ComfyUI workflow inputs.
Downloads images, audio, and video from URLs with validation.
"""
import os
import requests
from urllib.parse import urlparse

MAX_SIZES = {
    "image": 20 * 1024 * 1024,    # 20 MB
    "audio": 100 * 1024 * 1024,   # 100 MB
    "video": 500 * 1024 * 1024,   # 500 MB
}

VALID_EXTENSIONS = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".bmp"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"},
    "video": {".mp4", ".webm", ".avi", ".mov"},
}

DEFAULT_FILENAMES = {
    "image": "input.jpg",
    "audio": "input.mp3",
    "video": "input.mp4",
}


def download_media(url, media_type=None):
    """
    Download media from URL.

    Args:
        url: URL to download from.
        media_type: "image", "audio", or "video". Auto-detected if None.

    Returns:
        (file_bytes, filename)
    """
    if not _validate_url(url):
        raise ValueError(f"Invalid URL: {url}")

    print(f"  Downloading {media_type or 'file'}: {url[:100]}...")

    response = requests.get(url, timeout=120)
    response.raise_for_status()

    # Filename from URL path
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path) or DEFAULT_FILENAMES.get(media_type, "input.bin")
    _, ext = os.path.splitext(filename)

    # Auto-detect media type if not given
    if not media_type:
        for mtype, exts in VALID_EXTENSIONS.items():
            if ext.lower() in exts:
                media_type = mtype
                break
        media_type = media_type or "image"

    # Size guard
    max_size = MAX_SIZES.get(media_type, MAX_SIZES["video"])
    if len(response.content) > max_size:
        raise ValueError(
            f"File too large: {len(response.content)} bytes (max {max_size})"
        )

    # Fallback filename if no extension
    if not ext:
        filename = DEFAULT_FILENAMES.get(media_type, "input.bin")

    print(f"  Downloaded: {len(response.content)} bytes -> {filename}")
    return response.content, filename


def _validate_url(url):
    try:
        r = urlparse(url)
        return r.scheme in ("http", "https") and bool(r.netloc)
    except Exception:
        return False
