#!/usr/bin/env python3
"""
Generic ComfyUI Workflow Runner for RunPod Serverless.

Auto-discovers workflows from /workspace/workflows/.
Auto-detects input nodes (LoadImage, LoadAudio, etc.) and output nodes.
No hardcoded workflow logic — works with any ComfyUI workflow.

Request format:
{
    "input": {
        "workflow": "workflow_name",          // filename without .json
        "image_url": "https://...",           // auto-mapped to LoadImage nodes
        "audio_url": "https://...",           // auto-mapped to audio input nodes
        "images": ["url1", "url2"],           // multi-image (mapped in node ID order)
        "overrides": {                        // override node inputs by node ID
            "315": {"noise_seed": 42},
            "299": {"width": 1280}
        }
    }
}

Response format:
{
    "status": "success",
    "output": {
        "files": [
            {"url": "https://...", "type": "video", "size_bytes": 12345}
        ],
        "workflow": "workflow_name",
        "generation_time": 45.3
    }
}
"""
import runpod
import requests
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from media_downloader import download_media
from gcs_uploader import upload_file, delete_local_file

# ─── Configuration ───────────────────────────────────────────────

COMFYUI_URL = os.environ.get("COMFYUI_URL", "http://127.0.0.1:8188")
WORKFLOW_DIR = os.environ.get("WORKFLOW_DIR", "/workspace/workflows")
COMFYUI_OUTPUT_DIR = os.environ.get(
    "COMFYUI_OUTPUT_DIR", "/workspace/runpod-slim/ComfyUI/output"
)

# Input node class_type → (input_field_name, media_type)
INPUT_NODE_MAP = {
    "LoadImage": ("image", "image"),
    "VHS_LoadAudioUpload": ("audio", "audio"),
    "LoadAudio": ("audio", "audio"),
    "VHS_LoadVideo": ("video", "video"),
}

# Request key → media_type
REQUEST_FILE_KEYS = {
    "image_url": "image",
    "audio_url": "audio",
    "video_url": "video",
}


# ─── Workflow Discovery & Analysis ───────────────────────────────

def list_workflows():
    """List available workflow names."""
    if not os.path.isdir(WORKFLOW_DIR):
        return []
    return [
        os.path.splitext(f)[0]
        for f in sorted(os.listdir(WORKFLOW_DIR))
        if f.endswith(".json")
    ]


def load_workflow(name):
    """Load workflow JSON by name. Auto-converts UI format to API format."""
    path = os.path.join(WORKFLOW_DIR, name if name.endswith(".json") else f"{name}.json")
    if not os.path.exists(path):
        available = list_workflows()
        raise FileNotFoundError(
            f"Workflow '{name}' not found. Available: {available}"
        )
    with open(path) as f:
        data = json.load(f)

    # Auto-detect UI format and convert
    from workflow_converter import is_ui_format, convert_ui_to_api
    if is_ui_format(data):
        print(f"Detected UI-format workflow, converting to API format...")
        data = convert_ui_to_api(data, COMFYUI_URL)

    return data


def find_input_nodes(workflow):
    """
    Find all media input nodes in workflow, grouped by media type.
    Returns: {"image": [(node_id, field), ...], "audio": [...]}
    Sorted by node ID for deterministic ordering.
    """
    result = {}
    for node_id in sorted(workflow.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        node = workflow[node_id]
        class_type = node.get("class_type", "")
        if class_type in INPUT_NODE_MAP:
            field, media_type = INPUT_NODE_MAP[class_type]
            result.setdefault(media_type, []).append((node_id, field))
    return result


# ─── ComfyUI Interaction ────────────────────────────────────────

def wait_for_comfyui(timeout=300):
    """Wait for ComfyUI HTTP API to be ready."""
    print("Waiting for ComfyUI...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{COMFYUI_URL}/system_stats", timeout=5)
            if r.status_code == 200:
                print("ComfyUI ready.")
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"ComfyUI not ready after {timeout}s")


def upload_to_comfyui(file_bytes, filename):
    """Upload a file to ComfyUI's input directory. Returns uploaded filename."""
    r = requests.post(
        f"{COMFYUI_URL}/upload/image",
        files={"image": (filename, file_bytes)},
        timeout=60,
    )
    r.raise_for_status()
    uploaded = r.json().get("name", filename)
    print(f"  Uploaded to ComfyUI: {filename} -> {uploaded}")
    return uploaded


def submit_workflow(workflow):
    """Submit workflow to ComfyUI. Returns prompt_id."""
    payload = {"prompt": workflow, "client_id": f"rp_{int(time.time())}"}
    r = requests.post(f"{COMFYUI_URL}/prompt", json=payload, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"ComfyUI rejected workflow: {r.text}")
    result = r.json()
    if "error" in result:
        raise RuntimeError(f"ComfyUI error: {result['error']}")
    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise RuntimeError("No prompt_id returned")
    print(f"Submitted: prompt_id={prompt_id}")
    return prompt_id


def wait_for_completion(prompt_id, timeout=1080):
    """
    Poll ComfyUI /history until workflow completes.
    Returns outputs dict: {node_id: {"gifs": [...], "images": [...], ...}}
    """
    print(f"Waiting for completion...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10)
            history = r.json()
            if prompt_id in history:
                status = history[prompt_id].get("status", {})
                if status.get("status_str") == "error":
                    msgs = status.get("messages", [])
                    raise RuntimeError(f"Workflow failed: {msgs}")
                outputs = history[prompt_id].get("outputs", {})
                if _has_output_files(outputs):
                    elapsed = time.time() - start
                    print(f"Completed in {elapsed:.1f}s")
                    return outputs
        except requests.RequestException as e:
            print(f"  Poll error: {e}")
        time.sleep(3)
    raise TimeoutError(f"Workflow timed out after {timeout}s")


def _has_output_files(outputs):
    """Check if any output node produced files."""
    for out in outputs.values():
        if out.get("gifs") or out.get("audio"):
            return True
        for img in out.get("images", []):
            if img.get("type") == "output":
                return True
    return False


# ─── Output Collection ──────────────────────────────────────────

def collect_output_files(outputs):
    """
    Collect all output files from ComfyUI history outputs.
    Returns: [{"path": str, "filename": str, "type": str}, ...]
    """
    files = []
    for node_id, out in outputs.items():
        # Video outputs (VHS_VideoCombine, SaveVideo, CreateVideo, etc.)
        for item in out.get("gifs", []):
            path = _resolve_output_path(item)
            if path:
                files.append({
                    "path": path,
                    "filename": item["filename"],
                    "type": "video",
                })

        # Image/video outputs (only "output" type, skip "temp" previews)
        for item in out.get("images", []):
            if item.get("type") == "output":
                path = _resolve_output_path(item)
                if path:
                    # Detect actual media type from extension
                    ext = os.path.splitext(item["filename"])[1].lower()
                    media_type = "video" if ext in (".mp4", ".webm", ".avi", ".mov") else "image"
                    files.append({
                        "path": path,
                        "filename": item["filename"],
                        "type": media_type,
                    })

        # Audio outputs
        for item in out.get("audio", []):
            path = _resolve_output_path(item)
            if path:
                files.append({
                    "path": path,
                    "filename": item["filename"],
                    "type": "audio",
                })

    return files


def _resolve_output_path(item):
    """Resolve full filesystem path for a ComfyUI output item."""
    filename = item.get("filename", "")
    subfolder = item.get("subfolder", "")

    candidates = [COMFYUI_OUTPUT_DIR, "/comfyui/output", "/workspace/ComfyUI/output"]
    for base in candidates:
        path = os.path.join(base, subfolder, filename) if subfolder else os.path.join(base, filename)
        if os.path.exists(path):
            return path

    print(f"  Warning: output not found: {filename}")
    return None


# ─── File Input Mapping ─────────────────────────────────────────

def collect_file_inputs(input_data):
    """
    Collect all file URLs from request in deterministic order.
    Returns: [(url, media_type), ...]
    """
    inputs = []

    # 1. Simple keys: image_url, audio_url, video_url
    for key, mtype in REQUEST_FILE_KEYS.items():
        url = input_data.get(key)
        if url:
            inputs.append((url, mtype))

    # 2. Array keys: images, audios
    for array_key, mtype in [("images", "image"), ("audios", "audio")]:
        for url in input_data.get(array_key, []):
            inputs.append((url, mtype))

    # 3. Numbered keys: image_url_2, image_url_3, ...
    for i in range(2, 10):
        for key, mtype in REQUEST_FILE_KEYS.items():
            url = input_data.get(f"{key}_{i}")
            if url:
                inputs.append((url, mtype))

    return inputs


# ─── Main Handler ────────────────────────────────────────────────

def handler(event):
    """
    Generic RunPod serverless handler.
    Loads any workflow, auto-maps file inputs, collects and uploads all outputs.
    """
    start_time = time.time()
    job_id = event.get("id")

    try:
        wait_for_comfyui(timeout=120)

        input_data = event.get("input", {})

        # ── 1. Load workflow ──
        workflow_name = input_data.get("workflow")
        if not workflow_name:
            return {
                "status": "error",
                "error": "Missing 'workflow' field",
                "available_workflows": list_workflows(),
            }

        workflow = load_workflow(workflow_name)
        print(f"Loaded: {workflow_name} ({len(workflow)} nodes)")

        # ── 2. Find input nodes ──
        input_nodes = find_input_nodes(workflow)
        print(f"Input nodes: { {k: [nid for nid, _ in v] for k, v in input_nodes.items()} }")

        # ── 3. Download, upload, and inject file inputs ──
        file_inputs = collect_file_inputs(input_data)
        for url, mtype in file_inputs:
            targets = input_nodes.get(mtype, [])
            if not targets:
                print(f"  Warning: no {mtype} input node for {url[:60]}")
                continue

            file_bytes, filename = download_media(url, mtype)
            uploaded_name = upload_to_comfyui(file_bytes, filename)

            node_id, field = targets.pop(0)
            workflow[node_id]["inputs"][field] = uploaded_name
            print(f"  {mtype} -> node {node_id}.{field}")

        # ── 4. Apply overrides ──
        overrides = input_data.get("overrides", {})
        for node_id, params in overrides.items():
            if node_id in workflow:
                workflow[node_id]["inputs"].update(params)
                print(f"  Override node {node_id}: {list(params.keys())}")
            else:
                print(f"  Warning: override target node {node_id} not in workflow")

        # ── 5. Submit ──
        prompt_id = submit_workflow(workflow)

        # ── 6. Wait ──
        outputs = wait_for_completion(prompt_id)

        # ── 7. Collect and upload outputs ──
        output_files = collect_output_files(outputs)
        if not output_files:
            return {"status": "error", "error": "No output files produced"}

        results = []
        for f in output_files:
            gcs_result = upload_file(f["path"], job_id=job_id)
            if gcs_result["success"]:
                delete_local_file(f["path"])
                results.append({
                    "url": gcs_result["public_url"],
                    "gcs_url": gcs_result["gcs_url"],
                    "filename": gcs_result["filename"],
                    "type": f["type"],
                    "size_bytes": gcs_result["size_bytes"],
                })
            else:
                results.append({
                    "url": None,
                    "type": f["type"],
                    "filename": f["filename"],
                    "error": gcs_result["error"],
                })

        generation_time = time.time() - start_time
        return {
            "status": "success",
            "output": {
                "files": results,
                "workflow": workflow_name,
                "prompt_id": prompt_id,
                "generation_time": round(generation_time, 1),
            },
        }

    except Exception as e:
        import traceback
        return {
            "status": "error",
            "error": str(e),
            "traceback": traceback.format_exc(),
        }


if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
