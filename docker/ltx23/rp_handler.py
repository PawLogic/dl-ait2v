#!/usr/bin/env python3
"""
LTX-2.3 RunPod Handler - 适配 workflow_ltx2-3_audio_gen.json

Input: image_url, audio_url, prompt_positive, prompt_negative
Workflow 节点映射:
  - Node 301 (LoadImage): image 文件名
  - Node 347 (VHS_LoadAudioUpload): audio 文件名
  - Node 279 (CLIPTextEncode): prompt_positive
  - Node 280 (CLIPTextEncode): prompt_negative
  - Node 315 (RandomNoise): workflow 已有自动随机，不传 seed
"""
import runpod
import requests
import json
import base64
import time
import os
import sys
import glob

sys.path.insert(0, '/workspace/handler')
sys.path.insert(0, '/')

from url_downloader import URLDownloader
from gcs_uploader import upload_video_to_gcs, delete_local_video

COMFYUI_URL = "http://127.0.0.1:8188"
WORKFLOW_PATH = "/comfyui/workflows/ltx2-3_audio_gen.json"

DEFAULT_POSITIVE_PROMPT = "A person speaks naturally with perfect lip synchronization, high quality, detailed facial expressions"
DEFAULT_NEGATIVE_PROMPT = "low quality, still frame, blurry, watermark, overlay, titles"


def wait_for_comfyui(timeout=300):
    """Wait for ComfyUI to be ready."""
    print("Waiting for ComfyUI...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
            if response.status_code == 200:
                print("ComfyUI is ready")
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def upload_file_to_comfyui(file_bytes: bytes, filename: str, subfolder: str = "") -> str:
    """Upload file to ComfyUI input folder. For audio, fallback to direct write."""
    # Try HTTP upload first (works for images)
    try:
        files = {"image": (filename, file_bytes)}
        data = {}
        if subfolder:
            data["subfolder"] = subfolder

        response = requests.post(
            f"{COMFYUI_URL}/upload/image",
            files=files,
            data=data,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        uploaded_name = result.get("name", filename)
        print(f"  Uploaded: {filename} -> {uploaded_name}")
        return uploaded_name
    except Exception as e:
        # Fallback: write directly to ComfyUI input (for audio etc.)
        for input_dir in ["/comfyui/input", "/workspace/ComfyUI/input"]:
            if os.path.exists(input_dir):
                target = os.path.join(input_dir, filename)
                with open(target, "wb") as f:
                    f.write(file_bytes)
                print(f"  Wrote to {target}")
                return filename
        raise e


def wait_for_completion(prompt_id: str, timeout: int = 1080) -> dict:
    """Wait for workflow completion, return video info."""
    print(f"Waiting for generation (prompt_id: {prompt_id})...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            history = response.json()

            if prompt_id in history:
                if history[prompt_id].get("status", {}).get("status_str") == "error":
                    error_msg = history[prompt_id].get("status", {}).get("messages", [])
                    raise RuntimeError(f"Generation failed: {error_msg}")

                outputs = history[prompt_id].get("outputs", {})

                # Check for video output - SaveVideo/gifs/videos
                for node_id, output_data in outputs.items():
                    if isinstance(output_data, dict):
                        for key in ("gifs", "videos", "mp4"):
                            if key in output_data and output_data[key]:
                                item = output_data[key][0]
                                video_info = item if isinstance(item, dict) else {"filename": item}
                                elapsed = time.time() - start_time
                                print(f"Generation complete in {elapsed:.1f}s")
                                return video_info

        except requests.RequestException as e:
            print(f"  Request error (retrying): {e}")

        time.sleep(5)

    raise TimeoutError(f"Generation timeout after {timeout}s")


def find_output_video(prompt_id: str):
    """Fallback: find most recent video in output folder. Returns (filename, full_path)."""
    output_dirs = [
        "/comfyui/output",
        "/workspace/ComfyUI/output",
    ]
    for base in output_dirs:
        if os.path.exists(base):
            for ext in ("*.mp4", "*.webm", "*.gif"):
                files = glob.glob(os.path.join(base, "**", ext), recursive=True)
                if files:
                    latest = max(files, key=os.path.getmtime)
                    return os.path.basename(latest), latest
    return None, None


def handler(event):
    """
    LTX-2.3 Handler - 图片 + 音频 → 口型同步视频

    Input:
    {
        "input": {
            "image_url": "https://example.com/portrait.jpg",
            "audio_url": "https://example.com/speech.mp3",
            "prompt_positive": "A person speaks naturally...",  // optional
            "prompt_negative": "blurry, low quality..."        // optional
        }
    }
    seed 由 workflow 自动随机，无需传入
    """
    start_time = time.time()

    try:
        if not wait_for_comfyui(timeout=120):
            return {"status": "error", "error": "ComfyUI failed to start"}

        input_data = event.get("input", {})
        image_url = input_data.get("image_url")
        audio_url = input_data.get("audio_url")

        if not image_url or not audio_url:
            return {
                "status": "error",
                "error": "Missing required: image_url and audio_url"
            }

        # Download files
        print("Step 1/5: Downloading files...")
        try:
            image_bytes, image_filename = URLDownloader.download_image(image_url)
            audio_bytes, audio_filename, audio_duration = URLDownloader.download_audio(audio_url)
        except Exception as e:
            return {"status": "error", "error": f"Download failed: {e}"}

        print(f"  Image: {image_filename}, Audio: {audio_filename} ({audio_duration:.2f}s)")

        # Upload to ComfyUI
        print("Step 2/5: Uploading to ComfyUI...")
        try:
            image_name = upload_file_to_comfyui(image_bytes, image_filename)
            audio_name = upload_file_to_comfyui(audio_bytes, audio_filename)
        except Exception as e:
            return {"status": "error", "error": f"Upload failed: {e}"}

        # Load workflow and inject parameters
        print("Step 3/5: Building workflow...")
        with open(WORKFLOW_PATH, 'r') as f:
            workflow = json.load(f)

        # Node 301: LoadImage
        if "301" in workflow:
            workflow["301"]["inputs"]["image"] = image_name

        # Node 347: VHS_LoadAudioUpload (duration=0 means full audio)
        if "347" in workflow:
            workflow["347"]["inputs"]["audio"] = audio_name
            workflow["347"]["inputs"]["start_time"] = 0
            workflow["347"]["inputs"]["duration"] = 0

        # Node 279: CLIPTextEncode (positive prompt)
        prompt_positive = input_data.get("prompt_positive", DEFAULT_POSITIVE_PROMPT)
        if "279" in workflow:
            workflow["279"]["inputs"]["text"] = prompt_positive

        # Node 280: CLIPTextEncode (negative prompt)
        prompt_negative = input_data.get("prompt_negative", DEFAULT_NEGATIVE_PROMPT)
        if "280" in workflow:
            workflow["280"]["inputs"]["text"] = prompt_negative

        # Node 315: RandomNoise - workflow 已有自动随机，不传 seed 则保持原样
        print(f"  Prompt: {prompt_positive[:50]}...")

        # Submit to ComfyUI
        print("Step 4/5: Generating video...")
        payload = {
            "prompt": workflow,
            "client_id": f"runpod_ltx23_{int(time.time())}"
        }

        response = requests.post(f"{COMFYUI_URL}/prompt", json=payload, timeout=30)
        if response.status_code != 200:
            return {"status": "error", "error": f"ComfyUI rejected: {response.text}"}

        result = response.json()
        if "error" in result:
            return {"status": "error", "error": result["error"]}

        prompt_id = result.get("prompt_id")
        if not prompt_id:
            return {"status": "error", "error": "No prompt_id from ComfyUI"}

        # Wait for completion
        try:
            video_info = wait_for_completion(prompt_id, timeout=1080)
        except TimeoutError as e:
            return {"status": "error", "error": str(e)}
        except RuntimeError as e:
            return {"status": "error", "error": str(e)}

        video_filename = video_info.get("filename", "output.mp4") if isinstance(video_info, dict) else "output.mp4"
        video_subfolder = video_info.get("subfolder", "") if isinstance(video_info, dict) else ""

        # Find video file
        if video_subfolder:
            video_path = f"/workspace/ComfyUI/output/{video_subfolder}/{video_filename}"
        else:
            video_path = f"/workspace/ComfyUI/output/{video_filename}"

        if not os.path.exists(video_path):
            video_path = f"/comfyui/output/{video_filename}"

        if not os.path.exists(video_path):
            # Fallback: find latest video in output
            _, video_path = find_output_video(prompt_id)
            if not video_path:
                return {"status": "error", "error": f"Video not found: {video_filename}"}
            video_filename = os.path.basename(video_path)

        generation_time = time.time() - start_time
        job_id = event.get("id")

        # Upload to GCS
        print("Step 5/5: Uploading to GCS...")
        gcs_result = upload_video_to_gcs(
            video_path=video_path,
            job_id=job_id,
            subfolder="ltx23_videos"
        )

        if not gcs_result["success"]:
            print(f"Warning: GCS failed: {gcs_result['error']}")
            with open(video_path, "rb") as f:
                video_base64 = base64.b64encode(f.read()).decode()
            return {
                "status": "success",
                "output": {
                    "video_base64": video_base64,
                    "video_url": None,
                    "video_filename": video_filename,
                    "duration": f"{audio_duration:.1f}s",
                    "generation_time": round(generation_time, 1),
                }
            }

        delete_local_video(video_path)

        return {
            "status": "success",
            "output": {
                "video_url": gcs_result["public_url"],
                "gcs_url": gcs_result["gcs_url"],
                "video_filename": gcs_result["filename"],
                "duration": f"{audio_duration:.1f}s",
                "generation_time": round(generation_time, 1),
            }
        }

    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


if __name__ == "__main__":
    print("Starting LTX-2.3 RunPod Handler")
    print("Input: image_url, audio_url, prompt_positive, prompt_negative, seed")
    runpod.serverless.start({"handler": handler})
