#!/usr/bin/env python3
"""
URL downloader - ltx23 自持副本，与 pod_files 独立
"""
import os
import requests
from typing import Tuple
from urllib.parse import urlparse


class URLDownloader:
    ALLOWED_IMAGE_TYPES = {
        'image/jpeg', 'image/png', 'image/webp', 'image/jpg',
        'application/octet-stream'
    }
    ALLOWED_AUDIO_TYPES = {
        'audio/mpeg', 'audio/wav', 'audio/mp3', 'audio/x-wav',
        'audio/x-m4a', 'audio/mp4', 'audio/aac',
        'application/octet-stream'
    }
    MAX_IMAGE_SIZE = 20 * 1024 * 1024
    MAX_AUDIO_SIZE = 100 * 1024 * 1024

    @staticmethod
    def download_image(url: str) -> Tuple[bytes, str]:
        print(f"  Downloading image from: {url[:80]}...")
        response = requests.get(url, timeout=60, stream=True)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path) or 'input.jpg'
        _, ext = os.path.splitext(filename)
        if content_type not in URLDownloader.ALLOWED_IMAGE_TYPES:
            if ext.lower() not in {'.jpg', '.jpeg', '.png', '.webp'}:
                raise ValueError(f"Invalid image type: {content_type}")
        image_bytes = response.content
        if len(image_bytes) > URLDownloader.MAX_IMAGE_SIZE:
            raise ValueError(f"Image too large")
        if not ext:
            filename = 'input.jpg'
        print(f"  Downloaded image: {len(image_bytes)} bytes -> {filename}")
        return image_bytes, filename

    @staticmethod
    def download_audio(url: str) -> Tuple[bytes, str, float]:
        print(f"  Downloading audio from: {url[:80]}...")
        response = requests.get(url, timeout=120, stream=True)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path) or 'input.mp3'
        _, ext = os.path.splitext(filename)
        if content_type not in URLDownloader.ALLOWED_AUDIO_TYPES:
            if ext.lower() not in {'.mp3', '.wav', '.m4a', '.aac', '.ogg'}:
                raise ValueError(f"Invalid audio type: {content_type}")
        audio_bytes = response.content
        if len(audio_bytes) > URLDownloader.MAX_AUDIO_SIZE:
            raise ValueError(f"Audio too large")
        import librosa
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=ext or '.mp3', delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            duration = librosa.get_duration(path=tmp_path)
        finally:
            os.path.exists(tmp_path) and os.remove(tmp_path)
        if not ext:
            filename = 'input.mp3'
        print(f"  Downloaded audio: {len(audio_bytes)} bytes, {duration:.2f}s -> {filename}")
        return audio_bytes, filename, duration
