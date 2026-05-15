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
import io
import json
import os
import sys
import time

import runpod
import requests
from PIL import Image

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

DEFAULT_CANVAS_RESOLUTION = "720p"
DEFAULT_CANVAS_ASPECT_RATIO = "16:9"

CANVAS_DIMENSIONS = {
    "480p": {
        "16:9": (864, 480),
        "9:16": (480, 864),
        "1:1": (640, 640),
    },
    "720p": {
        "16:9": (1280, 736),
        "9:16": (736, 1280),
        "1:1": (736, 736),
    },
    "1080p": {
        "16:9": (1920, 1088),
        "9:16": (1088, 1920),
        "1:1": (1088, 1088),
    },
}

CANVAS_NODE_IDS = (
    "292",  # SolidMask for audio latent mask
    "294",  # EmptyLTXVLatentVideo
    "299",  # Frame 1 resize
    "397",  # Frame 2 resize
    "402",  # Frame 3 resize
    "408",  # Frame 4 resize
    "409",  # Frame 5 resize
)


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


def load_workflow_raw(name):
    """Load workflow JSON without converting. Returns (data, is_ui_format)."""
    from workflow_converter import is_ui_format
    path = os.path.join(WORKFLOW_DIR, name if name.endswith(".json") else f"{name}.json")
    if not os.path.exists(path):
        available = list_workflows()
        raise FileNotFoundError(
            f"Workflow '{name}' not found. Available: {available}"
        )
    with open(path) as f:
        data = json.load(f)
    return data, is_ui_format(data)


def load_workflow_meta(name):
    """Load optional companion metadata file for a workflow."""
    base = name if not name.endswith(".json") else name[:-5]
    path = os.path.join(WORKFLOW_DIR, f"{base}_meta.json")
    if os.path.exists(path):
        with open(path) as f:
            meta = json.load(f)
        print(f"Loaded metadata: {path}")
        return meta
    return None


def activate_optional_chains(ui_workflow, meta, num_optional_images, has_audio):
    """
    Un-mute optional node chains in UI-format workflow based on provided inputs.
    Modifies ui_workflow in place.
    """
    nodes_by_id = {n["id"]: n for n in ui_workflow.get("nodes", [])}

    # Activate frame chains based on how many optional images are provided
    for chain in meta.get("frame_chains", []):
        # frame_index 2 = images[0], frame_index 3 = images[1], etc.
        arr_idx = chain["frame_index"] - 2
        if arr_idx < num_optional_images:
            for nid in chain["chain_nodes"]:
                if nid in nodes_by_id:
                    nodes_by_id[nid]["mode"] = 0
            print(f"  Activated frame {chain['frame_index']} chain (nodes {chain['chain_nodes']})")

    # Activate audio chain if audio is provided
    if has_audio:
        audio_chain = meta.get("audio_chain", {})
        for nid in audio_chain.get("chain_nodes", []):
            if nid in nodes_by_id:
                nodes_by_id[nid]["mode"] = 0
        print(f"  Activated audio chain (nodes {audio_chain.get('chain_nodes', [])})")


def fix_dangling_refs(workflow):
    """
    After UI→API conversion, fix inputs that reference absent (muted) nodes.
    For Switch nodes: redirect dangling on_true to on_false as safe fallback.
    For other nodes: remove the dangling key.
    """
    node_ids = set(workflow.keys())
    for node_id, node in workflow.items():
        inputs = node.get("inputs", {})
        for key, val in list(inputs.items()):
            if not (isinstance(val, list) and len(val) == 2 and isinstance(val[0], str)):
                continue
            if val[0] in node_ids:
                continue
            # Dangling reference found
            if "Switch" in node.get("class_type", "") and key == "on_true":
                on_false = inputs.get("on_false")
                if on_false is not None:
                    inputs["on_true"] = on_false
                    print(f"  Fixed dangling on_true in node {node_id} → on_false")
                    continue
            del inputs[key]
            print(f"  Removed dangling ref: node {node_id}.{key} → {val}")


def apply_switch_booleans(api_workflow, meta, num_optional_images, has_audio):
    """
    Set Switch node booleans in API-format workflow based on provided inputs.
    Modifies api_workflow in place.
    """
    # Enable frame switches
    for chain in meta.get("frame_chains", []):
        arr_idx = chain["frame_index"] - 2
        if arr_idx < num_optional_images:
            switch_id = str(chain["switch_node"])
            if switch_id in api_workflow:
                api_workflow[switch_id]["inputs"]["boolean"] = True
                print(f"  Enabled switch {switch_id} (frame {chain['frame_index']})")

    # Enable audio switches
    if has_audio:
        audio_chain = meta.get("audio_chain", {})
        for key in ("switch_node", "duration_node"):
            nid = str(audio_chain.get(key, ""))
            if nid and nid in api_workflow:
                ct = api_workflow[nid].get("class_type", "")
                # PrimitiveBoolean stores its value in "value"; Switch nodes use "boolean"
                field = "value" if ct == "PrimitiveBoolean" else "boolean"
                api_workflow[nid]["inputs"][field] = True
                print(f"  Enabled audio switch {nid} ({key})")


def count_optional_images(input_data):
    """Return how many optional image chains should be active."""
    keyframes = input_data.get("keyframes", [])
    if isinstance(keyframes, list) and keyframes:
        return max(0, len(keyframes) - 1)
    images = input_data.get("images", [])
    if isinstance(images, list):
        return len(images)
    return 0


def nearest_supported_aspect_ratio(width, height):
    """Map a source image size to the closest supported output ratio."""
    if width <= 0 or height <= 0:
        return DEFAULT_CANVAS_ASPECT_RATIO
    source_ratio = width / height
    candidates = {
        "16:9": 16 / 9,
        "9:16": 9 / 16,
        "1:1": 1.0,
    }
    return min(candidates, key=lambda ratio: abs(candidates[ratio] - source_ratio))


def normalize_canvas_resolution(value):
    if value is None:
        return DEFAULT_CANVAS_RESOLUTION
    resolution = str(value).strip().lower()
    if resolution in CANVAS_DIMENSIONS:
        return resolution
    return DEFAULT_CANVAS_RESOLUTION


def normalize_canvas_aspect_ratio(value):
    if value is None:
        return DEFAULT_CANVAS_ASPECT_RATIO
    aspect_ratio = str(value).strip()
    if aspect_ratio in CANVAS_DIMENSIONS[DEFAULT_CANVAS_RESOLUTION]:
        return aspect_ratio
    return DEFAULT_CANVAS_ASPECT_RATIO


def coerce_positive_int(value, field_name):
    try:
        result = int(value)
    except Exception:
        raise ValueError(f"{field_name} must be a positive integer: {value!r}")
    if result <= 0:
        raise ValueError(f"{field_name} must be a positive integer: {value!r}")
    return result


def probe_image_size(file_bytes):
    """Return (width, height) for an image, or None if probing fails."""
    try:
        with Image.open(io.BytesIO(file_bytes)) as image:
            return image.size
    except Exception as exc:
        print(f"  Warning: failed to inspect image size: {exc}")
        return None


def resolve_canvas_dimensions(input_data, first_image_size=None):
    """
    Resolve output canvas from explicit width/height, requested aspect ratio,
    or the first input image size. Returns (width, height, aspect, resolution)
    or None when the request/workflow does not imply canvas control.
    """
    has_width = input_data.get("width") is not None
    has_height = input_data.get("height") is not None
    if has_width or has_height:
        if not (has_width and has_height):
            raise ValueError("width and height must be provided together")
        width = coerce_positive_int(input_data["width"], "width")
        height = coerce_positive_int(input_data["height"], "height")
        return width, height, f"{width}:{height}", "custom"

    resolution = normalize_canvas_resolution(input_data.get("resolution"))
    requested_ratio = (
        input_data.get("aspect_ratio")
        or input_data.get("aspectRatio")
    )
    if requested_ratio:
        aspect_ratio = normalize_canvas_aspect_ratio(requested_ratio)
    elif first_image_size:
        aspect_ratio = nearest_supported_aspect_ratio(*first_image_size)
    else:
        return None

    width, height = CANVAS_DIMENSIONS[resolution][aspect_ratio]
    return width, height, aspect_ratio, resolution


def apply_canvas_dimensions(workflow, width, height):
    """Patch converted API workflow nodes that consume the output canvas size."""
    updated = []
    for node_id in CANVAS_NODE_IDS:
        node = workflow.get(node_id)
        if not node:
            continue
        inputs = node.setdefault("inputs", {})
        changed = False
        if "width" in inputs:
            inputs["width"] = width
            changed = True
        if "height" in inputs:
            inputs["height"] = height
            changed = True
        if changed:
            updated.append(node_id)
    return updated


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


def wait_for_completion(prompt_id, timeout=1800):
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
                # SaveVideo produces no history outputs — detect completion by status
                if status.get("completed") and status.get("status_str") == "success":
                    elapsed = time.time() - start
                    print(f"Completed in {elapsed:.1f}s (no history outputs, will scan disk)")
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

def collect_output_files(outputs, job_start_time=None):
    """
    Collect all output files from ComfyUI history outputs.
    Returns: [{"path": str, "filename": str, "type": str}, ...]

    Falls back to disk scan for SaveVideo (which writes files but reports no history outputs).
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

    # SaveVideo writes mp4 to disk but doesn't appear in history outputs.
    # Fall back to scanning for recently-created mp4 files.
    if not files and job_start_time is not None:
        cutoff = job_start_time - 5  # 5s buffer for clock skew
        output_dir = COMFYUI_OUTPUT_DIR
        if os.path.isdir(output_dir):
            for fname in os.listdir(output_dir):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in (".mp4", ".webm", ".avi", ".mov"):
                    continue
                fpath = os.path.join(output_dir, fname)
                if os.path.getmtime(fpath) >= cutoff:
                    print(f"  Disk scan found: {fname}")
                    files.append({"path": fpath, "filename": fname, "type": "video"})

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

    # 3a. keyframes array: extract image URLs in order (used by multiframe workflows)
    for kf in input_data.get("keyframes", []):
        url = kf.get("image_url") if isinstance(kf, dict) else None
        if url:
            inputs.append((url, "image"))

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

        num_optional_images = count_optional_images(input_data)
        has_audio = bool(input_data.get("audio_url"))

        # Load raw (UI or API) so we can activate optional chains before conversion
        workflow_raw, is_ui = load_workflow_raw(workflow_name)
        meta = load_workflow_meta(workflow_name)

        if meta and is_ui:
            activate_optional_chains(workflow_raw, meta, num_optional_images, has_audio)

        # Convert UI → API format (skips muted nodes)
        from workflow_converter import is_ui_format, convert_ui_to_api
        if is_ui:
            print(f"Converting UI-format workflow to API format...")
            workflow = convert_ui_to_api(workflow_raw, COMFYUI_URL)
            fix_dangling_refs(workflow)
        else:
            workflow = workflow_raw

        print(f"Loaded: {workflow_name} ({len(workflow)} nodes)")

        # ── 2. Find input nodes ──
        input_nodes = find_input_nodes(workflow)
        print(f"Input nodes: { {k: [nid for nid, _ in v] for k, v in input_nodes.items()} }")

        # ── 3. Download, upload, and inject file inputs ──
        file_inputs = collect_file_inputs(input_data)
        first_image_size = None
        for url, mtype in file_inputs:
            targets = input_nodes.get(mtype, [])
            if not targets:
                print(f"  Warning: no {mtype} input node for {url[:60]}")
                continue

            file_bytes, filename = download_media(url, mtype)
            if mtype == "image" and first_image_size is None:
                first_image_size = probe_image_size(file_bytes)
                if first_image_size:
                    width, height = first_image_size
                    print(f"  First image size: {width}x{height}")
            uploaded_name = upload_to_comfyui(file_bytes, filename)

            node_id, field = targets.pop(0)
            workflow[node_id]["inputs"][field] = uploaded_name
            print(f"  {mtype} -> node {node_id}.{field}")

        # ── 4. Apply output canvas ──
        canvas = resolve_canvas_dimensions(input_data, first_image_size)
        if canvas:
            width, height, aspect_ratio, resolution = canvas
            updated = apply_canvas_dimensions(workflow, width, height)
            if updated:
                print(
                    f"  Canvas: {width}x{height} "
                    f"({aspect_ratio}, {resolution}) -> nodes {updated}"
                )

        # ── 5. Apply overrides ──
        overrides = input_data.get("overrides", {})
        for node_id, params in overrides.items():
            if node_id in workflow:
                workflow[node_id]["inputs"].update(params)
                print(f"  Override node {node_id}: {list(params.keys())}")
            else:
                print(f"  Warning: override target node {node_id} not in workflow")

        # ── 5b. Auto-set switch booleans from metadata ──
        if meta:
            apply_switch_booleans(workflow, meta, num_optional_images, has_audio)

        # ── 6. Submit ──
        prompt_id = submit_workflow(workflow)

        # ── 7. Wait ──
        outputs = wait_for_completion(prompt_id)

        # ── 8. Collect and upload outputs ──
        output_files = collect_output_files(outputs, job_start_time=start_time)
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
