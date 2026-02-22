#!/usr/bin/env python3
"""
Enhanced RunPod Serverless Handler for LTX-2 Audio-to-Video

Supports:
- URL-based image and audio input
- Template-based workflow generation (workflow_ltx2_enhanced.json)
- Audio-video duration synchronization
- Quality presets (fast, high, ultra)

Based on test_720p.py production configuration.
"""
import runpod
import requests
import json
import base64
import time
import os
import sys

# Add handler directory to path for imports
sys.path.insert(0, '/workspace/handler')
sys.path.insert(0, '/')  # For root-level imports

from url_downloader import URLDownloader
from workflow_builder import WorkflowBuilder
from gcs_uploader import upload_video_to_gcs, delete_local_video

COMFYUI_URL = "http://127.0.0.1:8188"

# Quality presets based on test_720p.py
QUALITY_PRESETS = {
    "fast": {
        "steps": 8,
        "lora_distilled": 0.6,
        "lora_detailer": 0.5,
        "lora_camera": 0.3,
        "lora_i2v": 0.8,
        "description": "Fast preview quality"
    },
    "high": {
        "steps": 8,
        "lora_distilled": 0.6,
        "lora_detailer": 1.0,
        "lora_camera": 0.3,
        "lora_i2v": 0.8,
        "description": "Production quality (test_720p.py standard)"
    },
    "ultra": {
        "steps": 12,
        "lora_distilled": 0.8,
        "lora_detailer": 1.0,
        "lora_camera": 0.3,
        "lora_i2v": 1.0,
        "description": "Maximum quality"
    }
}

# Default prompts
DEFAULT_POSITIVE_PROMPT = "A person speaks naturally with perfect lip synchronization, high quality, detailed facial expressions"
DEFAULT_NEGATIVE_PROMPT = "static, bad teeth, blurry, low quality, pixelated, compressed artifacts, flickering"

# Default prompts for audio generation mode (no input audio)
DEFAULT_AUDIO_GEN_POSITIVE_PROMPT = "A person speaking naturally, high quality, detailed facial expressions, natural movements"
DEFAULT_AUDIO_GEN_NEGATIVE_PROMPT = "static, blurry, low quality, pixelated, compressed artifacts, flickering"

# Initialize workflow builder (will be done after ComfyUI is ready)
workflow_builder = None


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
    """
    Upload file to ComfyUI.

    Args:
        file_bytes: File content as bytes
        filename: Target filename
        subfolder: Optional subfolder

    Returns:
        Uploaded filename as returned by ComfyUI
    """
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


def wait_for_completion(prompt_id: str, timeout: int = 1080) -> dict:
    """
    Wait for ComfyUI workflow to complete.

    Args:
        prompt_id: ComfyUI prompt ID
        timeout: Maximum wait time in seconds

    Returns:
        Video output info dict with filename

    Raises:
        TimeoutError: If generation times out
        RuntimeError: If generation fails
    """
    print(f"Waiting for generation (prompt_id: {prompt_id})...")
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            response = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            history = response.json()

            if prompt_id in history:
                # Check for errors
                if history[prompt_id].get("status", {}).get("status_str") == "error":
                    error_msg = history[prompt_id].get("status", {}).get("messages", [])
                    raise RuntimeError(f"Generation failed: {error_msg}")

                outputs = history[prompt_id].get("outputs", {})

                # Check node 190 for video output (VHS_VideoCombine)
                if "190" in outputs:
                    videos = outputs["190"].get("gifs", [])
                    if videos:
                        video_info = videos[0]
                        elapsed = time.time() - start_time
                        print(f"Generation complete in {elapsed:.1f}s: {video_info.get('filename')}")
                        return video_info

                # Also check other nodes for video output
                for node_id, output_data in outputs.items():
                    if "gifs" in output_data and output_data["gifs"]:
                        video_info = output_data["gifs"][0]
                        elapsed = time.time() - start_time
                        print(f"Generation complete in {elapsed:.1f}s: {video_info.get('filename')}")
                        return video_info

        except requests.RequestException as e:
            print(f"  Request error (retrying): {e}")

        time.sleep(5)

    raise TimeoutError(f"Generation timeout after {timeout}s (18 min limit)")


def handler(event):
    """
    Enhanced RunPod Handler with URL support and template-based workflow.

    Input format:
    {
        "input": {
            "image_url": "https://example.com/image.jpg",
            "audio_url": "https://example.com/audio.mp3",
            "prompt_positive": "A person speaks naturally...",  // optional
            "prompt_negative": "blurry, low quality...",        // optional
            "seed": 12345,           // optional, random if not provided
            "width": 1280,           // optional, default 1280
            "height": 736,           // optional, default 736
            "quality_preset": "high" // optional: fast, high, ultra
        }
    }

    Output format:
    {
        "status": "success",
        "output": {
            "video_base64": "...",
            "video_filename": "ltx2_output_*.mp4",
            "resolution": "1280x736",
            "duration": "10.0s",
            "frames": 297,
            "fps": 30,
            "quality_preset": "high",
            "generation_time": 45.3
        }
    }
    """
    global workflow_builder

    start_time = time.time()

    try:
        # Wait for ComfyUI
        if not wait_for_comfyui(timeout=120):
            return {"status": "error", "error": "ComfyUI failed to start"}

        # Initialize workflow builder if needed
        if workflow_builder is None:
            template_path = "/comfyui/workflows/ltx2_enhanced.json"
            audio_gen_template_path = "/comfyui/workflows/ltx2_audio_gen.json"
            multiframe_template_path = "/comfyui/workflows/ltx2_multiframe.json"
            if not os.path.exists(template_path):
                return {"status": "error", "error": f"Workflow template not found: {template_path}"}
            workflow_builder = WorkflowBuilder(template_path, audio_gen_template_path, multiframe_template_path)
            print(f"Workflow builder initialized from {template_path}")

        input_data = event.get("input", {})

        # Validate required inputs
        image_url = input_data.get("image_url")
        audio_url = input_data.get("audio_url")

        if not image_url:
            return {"status": "error", "error": "Missing required field: image_url"}
        if not audio_url:
            return {"status": "error", "error": "Missing required field: audio_url"}

        # Validate URLs
        if not URLDownloader.validate_url(image_url):
            return {"status": "error", "error": f"Invalid image_url: {image_url}"}
        if not URLDownloader.validate_url(audio_url):
            return {"status": "error", "error": f"Invalid audio_url: {audio_url}"}

        # Download files
        print("Step 1/4: Downloading files...")
        try:
            image_bytes, image_filename = URLDownloader.download_image(image_url)
        except Exception as e:
            return {"status": "error", "error": f"Failed to download image: {e}"}

        try:
            audio_bytes, audio_filename, audio_duration = URLDownloader.download_audio(audio_url)
        except Exception as e:
            return {"status": "error", "error": f"Failed to download audio: {e}"}

        print(f"  Audio duration: {audio_duration:.2f}s")

        # Upload files to ComfyUI
        print("Step 2/4: Uploading to ComfyUI...")
        try:
            image_name = upload_file_to_comfyui(image_bytes, image_filename)
            audio_name = upload_file_to_comfyui(audio_bytes, audio_filename)
        except Exception as e:
            return {"status": "error", "error": f"Failed to upload files: {e}"}

        # Get configuration
        width = input_data.get("width", 1280)
        height = input_data.get("height", 736)
        seed = input_data.get("seed", int(time.time() * 1000) % (2**48))
        prompt_positive = input_data.get("prompt_positive", DEFAULT_POSITIVE_PROMPT)
        prompt_negative = input_data.get("prompt_negative", DEFAULT_NEGATIVE_PROMPT)

        # Get quality preset
        quality_preset = input_data.get("quality_preset", "high")
        if quality_preset not in QUALITY_PRESETS:
            quality_preset = "high"
        preset = QUALITY_PRESETS[quality_preset]

        # Allow direct LoRA strength override (0 = disabled)
        lora_camera = input_data.get("lora_camera", preset["lora_camera"])
        lora_distilled = input_data.get("lora_distilled", preset["lora_distilled"])
        lora_detailer = input_data.get("lora_detailer", preset["lora_detailer"])
        lora_i2v = input_data.get("lora_i2v", preset["lora_i2v"])

        # Image preprocessing parameters
        img_compression = input_data.get("img_compression", 23)  # Lower = better quality
        img_strength = input_data.get("img_strength", 1.0)  # First frame injection strength

        # Buffer seconds: extra video duration beyond audio (default 1.0s)
        buffer_seconds = input_data.get("buffer_seconds", 1.0)

        # Video frame rate (default 30fps, range 1-60)
        fps = input_data.get("fps", 30)
        if not isinstance(fps, (int, float)) or fps < 1 or fps > 60:
            fps = 30
        fps = int(fps)

        # Build workflow using template
        print("Step 3/4: Building workflow...")
        workflow = workflow_builder.build_workflow(
            image_name=image_name,
            audio_name=audio_name,
            audio_duration=audio_duration,
            prompt_positive=prompt_positive,
            prompt_negative=prompt_negative,
            seed=seed,
            width=width,
            height=height,
            fps=fps,
            steps=preset["steps"],
            cfg_scale=1.0,
            lora_distilled=lora_distilled,
            lora_detailer=lora_detailer,
            lora_camera=lora_camera,
            lora_i2v=lora_i2v,
            img_compression=img_compression,
            img_strength=img_strength,
            buffer_seconds=buffer_seconds,
        )

        # Get video parameters for response
        video_params = workflow_builder.get_video_params(audio_duration, fps=fps, buffer_seconds=buffer_seconds)

        print(f"  Resolution: {width}x{height}")
        print(f"  Frames: {video_params['num_frames']} @ {fps}fps = {video_params['actual_duration']:.1f}s")
        print(f"  Quality: {quality_preset} ({preset['description']})")
        print(f"  Seed: {seed}")

        # Submit to ComfyUI
        print("Step 4/4: Generating video...")
        payload = {
            "prompt": workflow,
            "client_id": f"runpod_{int(time.time())}"
        }

        response = requests.post(f"{COMFYUI_URL}/prompt", json=payload, timeout=30)
        if response.status_code != 200:
            return {"status": "error", "error": f"ComfyUI rejected workflow: {response.text}"}

        result = response.json()
        if "error" in result:
            return {"status": "error", "error": f"ComfyUI error: {result['error']}"}

        prompt_id = result.get("prompt_id")
        if not prompt_id:
            return {"status": "error", "error": "No prompt_id returned from ComfyUI"}

        # Wait for completion
        try:
            video_info = wait_for_completion(prompt_id, timeout=1080)
        except TimeoutError as e:
            return {"status": "error", "error": str(e)}
        except RuntimeError as e:
            return {"status": "error", "error": str(e)}

        # Read and encode video
        video_filename = video_info.get("filename", "output.mp4")
        video_subfolder = video_info.get("subfolder", "")

        if video_subfolder:
            video_path = f"/workspace/ComfyUI/output/{video_subfolder}/{video_filename}"
        else:
            video_path = f"/workspace/ComfyUI/output/{video_filename}"

        # Also check comfyui output directory
        if not os.path.exists(video_path):
            video_path = f"/comfyui/output/{video_filename}"

        if not os.path.exists(video_path):
            return {"status": "error", "error": f"Video file not found: {video_filename}"}

        generation_time = time.time() - start_time

        # Get job_id from RunPod event for GCS path organization
        job_id = event.get("id", None)

        # Upload to GCS
        print("Step 5/5: Uploading to GCS...")
        gcs_result = upload_video_to_gcs(
            video_path=video_path,
            job_id=job_id,
            subfolder="ltx2_videos"
        )

        if not gcs_result["success"]:
            # Fallback to base64 if GCS upload fails
            print(f"Warning: GCS upload failed: {gcs_result['error']}")
            print("Falling back to base64 encoding...")
            with open(video_path, "rb") as f:
                video_base64 = base64.b64encode(f.read()).decode()

            return {
                "status": "success",
                "output": {
                    "video_base64": video_base64,
                    "video_url": None,
                    "gcs_url": None,
                    "video_filename": video_filename,
                    "prompt_id": prompt_id,
                    "resolution": f"{width}x{height}",
                    "duration": f"{audio_duration:.1f}s",
                    "frames": video_params["num_frames"],
                    "fps": fps,
                    "seed": seed,
                    "quality_preset": quality_preset,
                    "generation_time": round(generation_time, 1),
                    "gcs_error": gcs_result["error"]
                }
            }

        # Clean up local file after successful upload
        delete_local_video(video_path)

        return {
            "status": "success",
            "output": {
                "video_url": gcs_result["public_url"],
                "gcs_url": gcs_result["gcs_url"],
                "video_filename": gcs_result["filename"],
                "video_size_bytes": gcs_result["size_bytes"],
                "prompt_id": prompt_id,
                "resolution": f"{width}x{height}",
                "duration": f"{audio_duration:.1f}s",
                "frames": video_params["num_frames"],
                "fps": fps,
                "seed": seed,
                "quality_preset": quality_preset,
                "generation_time": round(generation_time, 1)
            }
        }

    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def audio_gen_handler(event):
    """
    Handler for Image-to-Video+Audio generation (no input audio).

    Generates both video and audio from just an image and duration parameter.

    Input format:
    {
        "input": {
            "image_url": "https://example.com/image.jpg",
            "duration": 5.0,  // Video/audio duration in seconds (1-30)
            "prompt_positive": "A person speaking...",  // optional
            "prompt_negative": "blurry, low quality...",  // optional
            "seed": 12345,           // optional, random if not provided
            "width": 1280,           // optional, default 1280
            "height": 736,           // optional, default 736
            "quality_preset": "high" // optional: fast, high, ultra
        }
    }

    Output format:
    {
        "status": "success",
        "output": {
            "video_url": "...",
            "gcs_url": "...",
            "video_filename": "...",
            "resolution": "1280x736",
            "duration": "5.0s",
            "frames": 151,
            "audio_frames": 125,
            "fps": 30,
            "mode": "audio_gen",
            "generation_time": 45.3
        }
    }
    """
    global workflow_builder

    start_time = time.time()

    try:
        # Wait for ComfyUI
        if not wait_for_comfyui(timeout=120):
            return {"status": "error", "error": "ComfyUI failed to start"}

        # Initialize workflow builder if needed
        if workflow_builder is None:
            template_path = "/comfyui/workflows/ltx2_enhanced.json"
            audio_gen_template_path = "/comfyui/workflows/ltx2_audio_gen.json"
            multiframe_template_path = "/comfyui/workflows/ltx2_multiframe.json"
            if not os.path.exists(template_path):
                return {"status": "error", "error": f"Workflow template not found: {template_path}"}
            workflow_builder = WorkflowBuilder(template_path, audio_gen_template_path, multiframe_template_path)
            print(f"Workflow builder initialized with audio_gen template")

        # Check if audio_gen template is available
        if workflow_builder.audio_gen_template is None:
            return {"status": "error", "error": "Audio generation template not loaded"}

        input_data = event.get("input", {})

        # Validate required inputs
        image_url = input_data.get("image_url")
        duration = input_data.get("duration")

        if not image_url:
            return {"status": "error", "error": "Missing required field: image_url"}
        if duration is None:
            return {"status": "error", "error": "Missing required field: duration"}

        # Validate duration range
        try:
            duration = float(duration)
        except (TypeError, ValueError):
            return {"status": "error", "error": f"Invalid duration value: {duration}"}

        if duration < 1.0:
            return {"status": "error", "error": "Duration must be at least 1 second"}
        if duration > 30.0:
            return {"status": "error", "error": "Duration cannot exceed 30 seconds"}

        # Validate URL
        if not URLDownloader.validate_url(image_url):
            return {"status": "error", "error": f"Invalid image_url: {image_url}"}

        # Download image
        print("Step 1/4: Downloading image...")
        try:
            image_bytes, image_filename = URLDownloader.download_image(image_url)
        except Exception as e:
            return {"status": "error", "error": f"Failed to download image: {e}"}

        # Upload image to ComfyUI
        print("Step 2/4: Uploading to ComfyUI...")
        try:
            image_name = upload_file_to_comfyui(image_bytes, image_filename)
        except Exception as e:
            return {"status": "error", "error": f"Failed to upload image: {e}"}

        # Get configuration
        width = input_data.get("width", 1280)
        height = input_data.get("height", 736)
        seed = input_data.get("seed", int(time.time() * 1000) % (2**48))
        prompt_positive = input_data.get("prompt_positive", DEFAULT_AUDIO_GEN_POSITIVE_PROMPT)
        prompt_negative = input_data.get("prompt_negative", DEFAULT_AUDIO_GEN_NEGATIVE_PROMPT)

        # Get quality preset
        quality_preset = input_data.get("quality_preset", "high")
        if quality_preset not in QUALITY_PRESETS:
            quality_preset = "high"
        preset = QUALITY_PRESETS[quality_preset]

        # Allow direct LoRA strength override (0 = disabled)
        lora_camera = input_data.get("lora_camera", preset["lora_camera"])
        lora_distilled = input_data.get("lora_distilled", preset["lora_distilled"])
        lora_detailer = input_data.get("lora_detailer", preset["lora_detailer"])
        lora_i2v = input_data.get("lora_i2v", preset["lora_i2v"])

        # Image preprocessing parameters
        img_compression = input_data.get("img_compression", 23)
        img_strength = input_data.get("img_strength", 1.0)

        # Buffer seconds: extra video duration beyond target (default 1.0s)
        buffer_seconds = input_data.get("buffer_seconds", 1.0)

        # Video frame rate (default 30fps, range 1-60)
        fps = input_data.get("fps", 30)
        if not isinstance(fps, (int, float)) or fps < 1 or fps > 60:
            fps = 30
        fps = int(fps)

        # Build workflow using audio generation template
        print("Step 3/4: Building audio generation workflow...")
        workflow = workflow_builder.build_audio_gen_workflow(
            image_name=image_name,
            duration=duration,
            prompt_positive=prompt_positive,
            prompt_negative=prompt_negative,
            seed=seed,
            width=width,
            height=height,
            fps=fps,
            steps=preset["steps"],
            cfg_scale=1.0,
            lora_distilled=lora_distilled,
            lora_detailer=lora_detailer,
            lora_camera=lora_camera,
            lora_i2v=lora_i2v,
            img_compression=img_compression,
            img_strength=img_strength,
            buffer_seconds=buffer_seconds,
        )

        # Get video/audio parameters for response
        gen_params = workflow_builder.get_audio_gen_params(duration, fps=fps, buffer_seconds=buffer_seconds)

        print(f"  Resolution: {width}x{height}")
        print(f"  Duration: {duration}s")
        print(f"  Video frames: {gen_params['num_frames']} @ {fps}fps")
        print(f"  Audio frames: {gen_params['audio_frames']} @ 25Hz")
        print(f"  Quality: {quality_preset} ({preset['description']})")
        print(f"  Seed: {seed}")

        # Submit to ComfyUI
        print("Step 4/4: Generating video + audio...")
        payload = {
            "prompt": workflow,
            "client_id": f"runpod_audiogen_{int(time.time())}"
        }

        response = requests.post(f"{COMFYUI_URL}/prompt", json=payload, timeout=30)
        if response.status_code != 200:
            return {"status": "error", "error": f"ComfyUI rejected workflow: {response.text}"}

        result = response.json()
        if "error" in result:
            return {"status": "error", "error": f"ComfyUI error: {result['error']}"}

        prompt_id = result.get("prompt_id")
        if not prompt_id:
            return {"status": "error", "error": "No prompt_id returned from ComfyUI"}

        # Wait for completion
        try:
            video_info = wait_for_completion(prompt_id, timeout=1080)
        except TimeoutError as e:
            return {"status": "error", "error": str(e)}
        except RuntimeError as e:
            return {"status": "error", "error": str(e)}

        # Read and encode video
        video_filename = video_info.get("filename", "output.mp4")
        video_subfolder = video_info.get("subfolder", "")

        if video_subfolder:
            video_path = f"/workspace/ComfyUI/output/{video_subfolder}/{video_filename}"
        else:
            video_path = f"/workspace/ComfyUI/output/{video_filename}"

        # Also check comfyui output directory
        if not os.path.exists(video_path):
            video_path = f"/comfyui/output/{video_filename}"

        if not os.path.exists(video_path):
            return {"status": "error", "error": f"Video file not found: {video_filename}"}

        generation_time = time.time() - start_time

        # Get job_id from RunPod event for GCS path organization
        job_id = event.get("id", None)

        # Upload to GCS
        print("Step 5/5: Uploading to GCS...")
        gcs_result = upload_video_to_gcs(
            video_path=video_path,
            job_id=job_id,
            subfolder="ltx2_videos"
        )

        if not gcs_result["success"]:
            # Fallback to base64 if GCS upload fails
            print(f"Warning: GCS upload failed: {gcs_result['error']}")
            print("Falling back to base64 encoding...")
            with open(video_path, "rb") as f:
                video_base64 = base64.b64encode(f.read()).decode()

            return {
                "status": "success",
                "output": {
                    "video_base64": video_base64,
                    "video_url": None,
                    "gcs_url": None,
                    "video_filename": video_filename,
                    "prompt_id": prompt_id,
                    "resolution": f"{width}x{height}",
                    "duration": f"{duration:.1f}s",
                    "frames": gen_params["num_frames"],
                    "audio_frames": gen_params["audio_frames"],
                    "fps": fps,
                    "seed": seed,
                    "quality_preset": quality_preset,
                    "mode": "audio_gen",
                    "generation_time": round(generation_time, 1),
                    "gcs_error": gcs_result["error"]
                }
            }

        # Clean up local file after successful upload
        delete_local_video(video_path)

        return {
            "status": "success",
            "output": {
                "video_url": gcs_result["public_url"],
                "gcs_url": gcs_result["gcs_url"],
                "video_filename": gcs_result["filename"],
                "video_size_bytes": gcs_result["size_bytes"],
                "prompt_id": prompt_id,
                "resolution": f"{width}x{height}",
                "duration": f"{duration:.1f}s",
                "frames": gen_params["num_frames"],
                "audio_frames": gen_params["audio_frames"],
                "fps": fps,
                "seed": seed,
                "quality_preset": quality_preset,
                "mode": "audio_gen",
                "generation_time": round(generation_time, 1)
            }
        }

    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def multi_keyframe_handler(event):
    """
    Handler for multi-keyframe video generation (Mode 3a and 3b).

    Uses chained LTXVAddGuide nodes for reliable keyframe positioning (v55+).

    Mode 3a: Multi-keyframe + Lip-sync
    - Input: keyframes[] + audio_url
    - Output: Video with keyframe guides + lip-sync to provided audio

    Mode 3b: Multi-keyframe + Audio generation
    - Input: keyframes[] + duration (no audio_url)
    - Output: Video with keyframe guides + generated audio

    Input format:
    {
        "input": {
            "keyframes": [
                {"image_url": "https://...", "frame_position": "first", "strength": 1.0},
                {"image_url": "https://...", "frame_position": "last", "strength": 0.8}
            ],
            "audio_url": "https://...",  // Mode 3a: lip-sync
            // OR
            "duration": 5.0,             // Mode 3b: audio generation
            "prompt_positive": "...",    // optional
            "prompt_negative": "...",    // optional
            "seed": 12345,               // optional
            "width": 1280,               // optional
            "height": 736,               // optional
            "quality_preset": "high"     // optional: fast, high, ultra
        }
    }
    """
    global workflow_builder

    start_time = time.time()

    try:
        # Wait for ComfyUI
        if not wait_for_comfyui(timeout=120):
            return {"status": "error", "error": "ComfyUI failed to start"}

        # Initialize workflow builder if needed
        if workflow_builder is None:
            template_path = "/comfyui/workflows/ltx2_enhanced.json"
            audio_gen_template_path = "/comfyui/workflows/ltx2_audio_gen.json"
            multiframe_template_path = "/comfyui/workflows/ltx2_multiframe.json"
            if not os.path.exists(template_path):
                return {"status": "error", "error": f"Workflow template not found: {template_path}"}
            workflow_builder = WorkflowBuilder(template_path, audio_gen_template_path, multiframe_template_path)
            print(f"Workflow builder initialized with multiframe template")

        # Check if multiframe template is available
        if workflow_builder.multiframe_template is None:
            return {"status": "error", "error": "Multiframe template not loaded"}

        input_data = event.get("input", {})

        # Validate required inputs
        keyframes = input_data.get("keyframes", [])
        audio_url = input_data.get("audio_url")
        duration = input_data.get("duration")

        if not keyframes:
            return {"status": "error", "error": "Missing required field: keyframes"}

        # Validate keyframes (1-9)
        if len(keyframes) < 1:
            return {"status": "error", "error": "At least one keyframe is required"}
        if len(keyframes) > 9:
            return {"status": "error", "error": "Maximum 9 keyframes supported"}

        # Validate each keyframe
        for i, kf in enumerate(keyframes):
            if not kf.get("image_url"):
                return {"status": "error", "error": f"Keyframe {i+1} missing image_url"}
            if not URLDownloader.validate_url(kf["image_url"]):
                return {"status": "error", "error": f"Invalid image_url in keyframe {i+1}"}

            # Validate frame_position
            pos = kf.get("frame_position", "first" if i == 0 else "last")
            if pos not in ["first", "last"]:
                try:
                    pos_float = float(pos)
                    if pos_float < 0.0 or pos_float > 1.0:
                        return {"status": "error", "error": f"Keyframe {i+1} frame_position must be 'first', 'last', or 0.0-1.0"}
                except (TypeError, ValueError):
                    return {"status": "error", "error": f"Invalid frame_position in keyframe {i+1}"}

            # Validate strength
            strength = kf.get("strength", 1.0 if i == 0 else 0.8)
            if not isinstance(strength, (int, float)) or strength < 0.0 or strength > 1.0:
                return {"status": "error", "error": f"Keyframe {i+1} strength must be 0.0-1.0"}

        # Determine mode: 3a (audio_url) or 3b (duration)
        is_mode_3a = audio_url is not None
        is_mode_3b = duration is not None and not audio_url

        if not is_mode_3a and not is_mode_3b:
            return {"status": "error", "error": "Must provide either audio_url (Mode 3a) or duration (Mode 3b)"}

        # Download keyframe images
        print(f"Step 1/5: Downloading {len(keyframes)} keyframe images...")
        keyframe_data = []
        for i, kf in enumerate(keyframes):
            try:
                image_bytes, image_filename = URLDownloader.download_image(kf["image_url"])
            except Exception as e:
                return {"status": "error", "error": f"Failed to download keyframe {i+1} image: {e}"}

            # Upload to ComfyUI
            try:
                image_name = upload_file_to_comfyui(image_bytes, f"keyframe_{i}_{image_filename}")
            except Exception as e:
                return {"status": "error", "error": f"Failed to upload keyframe {i+1} image: {e}"}

            keyframe_data.append({
                "image_name": image_name,
                "frame_position": kf.get("frame_position", "first" if i == 0 else "last"),
                "strength": kf.get("strength", 1.0 if i == 0 else 0.8)
            })

        # Handle audio (Mode 3a) or duration (Mode 3b)
        audio_name = None
        audio_duration = None

        if is_mode_3a:
            # Mode 3a: Download and process audio
            print("Step 2/5: Downloading audio for lip-sync...")
            if not URLDownloader.validate_url(audio_url):
                return {"status": "error", "error": f"Invalid audio_url: {audio_url}"}

            try:
                audio_bytes, audio_filename, audio_duration = URLDownloader.download_audio(audio_url)
            except Exception as e:
                return {"status": "error", "error": f"Failed to download audio: {e}"}

            try:
                audio_name = upload_file_to_comfyui(audio_bytes, audio_filename)
            except Exception as e:
                return {"status": "error", "error": f"Failed to upload audio: {e}"}

            print(f"  Audio duration: {audio_duration:.2f}s")
        else:
            # Mode 3b: Validate duration
            print("Step 2/5: Setting up audio generation...")
            try:
                duration = float(duration)
            except (TypeError, ValueError):
                return {"status": "error", "error": f"Invalid duration value: {duration}"}

            if duration < 1.0:
                return {"status": "error", "error": "Duration must be at least 1 second"}
            if duration > 30.0:
                return {"status": "error", "error": "Duration cannot exceed 30 seconds"}

            print(f"  Target duration: {duration:.1f}s")

        # Get configuration
        width = input_data.get("width", 1280)
        height = input_data.get("height", 736)
        seed = input_data.get("seed", int(time.time() * 1000) % (2**48))
        prompt_positive = input_data.get("prompt_positive", DEFAULT_POSITIVE_PROMPT if is_mode_3a else DEFAULT_AUDIO_GEN_POSITIVE_PROMPT)
        prompt_negative = input_data.get("prompt_negative", DEFAULT_NEGATIVE_PROMPT if is_mode_3a else DEFAULT_AUDIO_GEN_NEGATIVE_PROMPT)

        # Get quality preset
        quality_preset = input_data.get("quality_preset", "high")
        if quality_preset not in QUALITY_PRESETS:
            quality_preset = "high"
        preset = QUALITY_PRESETS[quality_preset]

        # Allow direct LoRA strength override
        lora_camera = input_data.get("lora_camera", preset["lora_camera"])
        lora_distilled = input_data.get("lora_distilled", preset["lora_distilled"])
        lora_detailer = input_data.get("lora_detailer", preset["lora_detailer"])
        lora_i2v = input_data.get("lora_i2v", preset["lora_i2v"])

        # Image preprocessing parameters
        img_compression = input_data.get("img_compression", 23)

        # Mode 3 specific parameters
        trim_to_audio = input_data.get("trim_to_audio", False)  # Default off to prevent flickering
        frame_alignment = input_data.get("frame_alignment", 8)  # Set to 1 to disable alignment
        buffer_seconds = input_data.get("buffer_seconds", 1.0)  # Extra video duration beyond input
        # v59: Buffer guide strategy - True/"add_node", "extend_last", or False/"none"
        auto_buffer_guide = input_data.get("auto_buffer_guide", True)

        # Video frame rate (default 30fps, range 1-60)
        fps = input_data.get("fps", 30)
        if not isinstance(fps, (int, float)) or fps < 1 or fps > 60:
            fps = 30
        fps = int(fps)

        # Allow direct steps override
        steps = input_data.get("steps", preset["steps"])

        # Warn if distilled LoRA is disabled but steps is low
        if lora_distilled == 0 and steps < 20:
            print(f"  Warning: lora_distilled=0 with steps={steps}. Recommend steps >= 20 for quality.")

        # v55+: Always use chained LTXVAddGuide nodes (fixes flickering issue)
        # v59: auto_buffer_guide supports dual strategies to prevent buffer flickering
        print("Step 3/5: Building multi-keyframe workflow (chained LTXVAddGuide)...")
        workflow = workflow_builder.build_multiframe_chained_workflow(
            keyframes=keyframe_data,
            audio_name=audio_name,
            audio_duration=audio_duration,
            duration=duration if is_mode_3b else None,
            prompt_positive=prompt_positive,
            prompt_negative=prompt_negative,
            seed=seed,
            width=width,
            height=height,
            fps=fps,
            steps=steps,
            cfg_scale=1.0,
            lora_distilled=lora_distilled,
            lora_detailer=lora_detailer,
            lora_camera=lora_camera,
            lora_i2v=lora_i2v,
            img_compression=img_compression,
            trim_to_audio=trim_to_audio,
            frame_alignment=frame_alignment,
            buffer_seconds=buffer_seconds,
            auto_buffer_guide=auto_buffer_guide,
        )

        # Get video parameters for response
        gen_params = workflow_builder.get_multiframe_params(
            keyframes=keyframe_data,
            audio_duration=audio_duration,
            duration=duration if is_mode_3b else None,
            fps=fps,
            frame_alignment=frame_alignment,
            buffer_seconds=buffer_seconds,
            auto_buffer_guide=auto_buffer_guide
        )

        mode_str = "3a (lip-sync)" if is_mode_3a else "3b (audio-gen)"
        print(f"  Mode: {mode_str}")
        print(f"  Resolution: {width}x{height}")
        print(f"  Keyframes: {len(keyframe_data)}")
        print(f"  Duration: {gen_params['target_duration']:.1f}s")
        print(f"  Quality: {quality_preset} ({preset['description']})")
        print(f"  Steps: {steps}")
        print(f"  Seed: {seed}")
        print(f"  trim_to_audio: {trim_to_audio}")
        print(f"  frame_alignment: {frame_alignment}")
        print(f"  buffer_seconds: {buffer_seconds}")
        print(f"  auto_buffer_guide: {auto_buffer_guide} (strategy: {gen_params.get('buffer_strategy', 'unknown')})")

        # Submit to ComfyUI
        print("Step 4/5: Generating video...")
        payload = {
            "prompt": workflow,
            "client_id": f"runpod_multiframe_{int(time.time())}"
        }

        response = requests.post(f"{COMFYUI_URL}/prompt", json=payload, timeout=30)
        if response.status_code != 200:
            return {"status": "error", "error": f"ComfyUI rejected workflow: {response.text}"}

        result = response.json()
        if "error" in result:
            return {"status": "error", "error": f"ComfyUI error: {result['error']}"}

        prompt_id = result.get("prompt_id")
        if not prompt_id:
            return {"status": "error", "error": "No prompt_id returned from ComfyUI"}

        # Wait for completion
        try:
            video_info = wait_for_completion(prompt_id, timeout=1080)
        except TimeoutError as e:
            return {"status": "error", "error": str(e)}
        except RuntimeError as e:
            return {"status": "error", "error": str(e)}

        # Read and process video
        video_filename = video_info.get("filename", "output.mp4")
        video_subfolder = video_info.get("subfolder", "")

        if video_subfolder:
            video_path = f"/workspace/ComfyUI/output/{video_subfolder}/{video_filename}"
        else:
            video_path = f"/workspace/ComfyUI/output/{video_filename}"

        if not os.path.exists(video_path):
            video_path = f"/comfyui/output/{video_filename}"

        if not os.path.exists(video_path):
            return {"status": "error", "error": f"Video file not found: {video_filename}"}

        generation_time = time.time() - start_time

        # Get job_id from RunPod event for GCS path organization
        job_id = event.get("id", None)

        # Upload to GCS
        print("Step 5/5: Uploading to GCS...")
        gcs_result = upload_video_to_gcs(
            video_path=video_path,
            job_id=job_id,
            subfolder="ltx2_videos"
        )

        if not gcs_result["success"]:
            # Fallback to base64 if GCS upload fails
            print(f"Warning: GCS upload failed: {gcs_result['error']}")
            print("Falling back to base64 encoding...")
            with open(video_path, "rb") as f:
                video_base64 = base64.b64encode(f.read()).decode()

            return {
                "status": "success",
                "output": {
                    "video_base64": video_base64,
                    "video_url": None,
                    "gcs_url": None,
                    "video_filename": video_filename,
                    "prompt_id": prompt_id,
                    "resolution": f"{width}x{height}",
                    "duration": f"{gen_params['target_duration']:.1f}s",
                    "frames": gen_params["num_frames"],
                    "keyframes": len(keyframe_data),
                    "fps": fps,
                    "seed": seed,
                    "quality_preset": quality_preset,
                    "mode": "3a" if is_mode_3a else "3b",
                    "generation_time": round(generation_time, 1),
                    "gcs_error": gcs_result["error"]
                }
            }

        # Clean up local file after successful upload
        delete_local_video(video_path)

        return {
            "status": "success",
            "output": {
                "video_url": gcs_result["public_url"],
                "gcs_url": gcs_result["gcs_url"],
                "video_filename": gcs_result["filename"],
                "video_size_bytes": gcs_result["size_bytes"],
                "prompt_id": prompt_id,
                "resolution": f"{width}x{height}",
                "duration": f"{gen_params['target_duration']:.1f}s",
                "frames": gen_params["num_frames"],
                "keyframes": len(keyframe_data),
                "fps": fps,
                "seed": seed,
                "quality_preset": quality_preset,
                "mode": "3a" if is_mode_3a else "3b",
                "generation_time": round(generation_time, 1)
            }
        }

    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc()
        }


# Legacy handler for backward compatibility (accepts pre-built workflow)
def legacy_handler(event):
    """
    Legacy handler that accepts pre-built workflow.
    Maintained for backward compatibility.
    """
    try:
        if not wait_for_comfyui(timeout=60):
            return {"error": "ComfyUI failed to start"}

        input_data = event.get("input", {})
        workflow = input_data.get("workflow")
        if not workflow:
            return {"error": "Missing workflow in input"}

        images = input_data.get("images", [])

        if images:
            for img_data in images:
                name = img_data.get("name", "input.png")
                image_b64 = img_data.get("image", "")

                if image_b64.startswith("data:"):
                    header, b64_data = image_b64.split(",", 1)
                    file_bytes = base64.b64decode(b64_data)
                    upload_file_to_comfyui(file_bytes, name)

        payload = {"prompt": workflow, "client_id": "runpod-handler"}
        response = requests.post(f"{COMFYUI_URL}/prompt", json=payload, timeout=30)

        if response.status_code != 200:
            return {"error": f"ComfyUI error: {response.text}"}

        result = response.json()
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            return {"error": "No prompt_id returned"}

        video_info = wait_for_completion(prompt_id, timeout=1080)
        video_filename = video_info.get("filename", "output.mp4")
        video_path = f"/workspace/ComfyUI/output/{video_filename}"

        if not os.path.exists(video_path):
            video_path = f"/comfyui/output/{video_filename}"

        if os.path.exists(video_path):
            with open(video_path, "rb") as f:
                video_b64 = base64.b64encode(f.read()).decode()
            return {
                "status": "COMPLETED",
                "output": {"images": [{"data": video_b64, "filename": video_filename}]}
            }

        return {"status": "COMPLETED", "output": {"filename": video_filename}}

    except Exception as e:
        import traceback
        return {"error": str(e), "traceback": traceback.format_exc()}


def unified_handler(event):
    """
    Unified handler that routes to appropriate handler based on input.

    Mode 1: Audio-to-Video (lip-sync)
    - Input: image_url + audio_url
    - Output: Video with lip-sync to provided audio

    Mode 2: Image-to-Video+Audio (generation)
    - Input: image_url + duration (no audio_url)
    - Output: Video + generated audio

    Mode 3a: Multi-keyframe + Lip-sync
    - Input: keyframes[] + audio_url
    - Output: Video with keyframe guides + lip-sync

    Mode 3b: Multi-keyframe + Audio generation
    - Input: keyframes[] + duration
    - Output: Video with keyframe guides + generated audio

    Legacy: Pre-built workflow
    - Input: workflow object
    - Output: Workflow execution result
    """
    input_data = event.get("input", {})

    # Mode 3: Multi-keyframe (3a with audio_url, 3b with duration)
    if input_data.get("keyframes"):
        return multi_keyframe_handler(event)

    # Mode 1: Audio-to-Video (lip-sync) - image + audio
    if input_data.get("image_url") and input_data.get("audio_url"):
        return handler(event)

    # Mode 2: Image-to-Video+Audio (generation) - image + duration, no audio
    if input_data.get("image_url") and input_data.get("duration") and not input_data.get("audio_url"):
        return audio_gen_handler(event)

    # Legacy mode: pre-built workflow
    if input_data.get("workflow"):
        return legacy_handler(event)

    return {
        "status": "error",
        "error": "Invalid input. Provide: (keyframes[] + audio_url/duration) for Mode 3, (image_url + audio_url) for Mode 1, (image_url + duration) for Mode 2, or (workflow) for legacy mode."
    }


if __name__ == "__main__":
    print("Starting Enhanced LTX-2 RunPod Handler (v62)")
    print("Supported input modes:")
    print("  - Mode 1 (Lip-sync): image_url + audio_url")
    print("  - Mode 2 (Audio Gen): image_url + duration")
    print("  - Mode 3a (Multi-keyframe + Lip-sync): keyframes[] + audio_url")
    print("  - Mode 3b (Multi-keyframe + Audio Gen): keyframes[] + duration")
    print("  - Legacy mode: workflow + images")
    print("Note: Mode 3 uses chained LTXVAddGuide nodes (v59: dual buffer guide strategies)")

    # Check if running in Pod mode (not serverless)
    pod_mode = os.environ.get("POD_MODE", "").lower() in ("1", "true", "yes")
    if pod_mode:
        print("Running in POD_MODE - keeping container alive for testing")
        print("ComfyUI should be available at http://127.0.0.1:8188")
        # Keep the process alive
        import signal
        signal.pause()
    else:
        runpod.serverless.start({"handler": unified_handler})
