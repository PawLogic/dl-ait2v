# LTX-2 Video Generation API

RunPod Serverless API for generating video with four modes:
- **Mode 1 (Lip-sync)**: Image + Audio → Video with lip synchronization
- **Mode 2 (Audio Gen)**: Image + Duration → Video + Generated audio
- **Mode 3a (Multi-keyframe Lip-sync)**: Multiple keyframe images + Audio → Video with smooth keyframe transitions
- **Mode 3b (Multi-keyframe Audio Gen)**: Multiple keyframe images + Duration → Video + Generated audio with smooth keyframe transitions

**Version**: v61

## Endpoint

```
https://api.runpod.ai/v2/42qdgmzjc9ldy5
```

## Authentication

```
Authorization: Bearer {RUNPOD_API_KEY}
```

## API Calls

### Synchronous (Wait for result)

```
POST /runsync
```

Waits for video generation to complete (timeout: 10 minutes).

### Asynchronous (Immediate return)

```
POST /run          # Submit job
GET /status/{id}   # Check status
```

## Mode 1: Lip-sync (Image + Audio)

Generate video with lip synchronization to provided audio.

### Request Format

```json
{
  "input": {
    "image_url": "https://example.com/portrait.jpg",
    "audio_url": "https://example.com/speech.mp3",
    "prompt_positive": "A person speaks naturally with perfect lip synchronization",
    "quality_preset": "high",
    "lora_camera": 0.3
  }
}
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `image_url` | string | Yes | - | URL to portrait image (JPG/PNG) |
| `audio_url` | string | Yes | - | URL to audio file (MP3/WAV) |
| `prompt_positive` | string | No | "A person speaks naturally..." | Positive prompt |
| `quality_preset` | string | No | "high" | Quality: `fast`, `high`, `ultra` |
| `width` | int | No | 1280 | Output width |
| `height` | int | No | 736 | Output height |
| `seed` | int | No | random | Random seed for reproducibility |
| `lora_camera` | float | No | 0.3 | Camera LoRA (0 = disable dolly-in) |
| `lora_distilled` | float | No | 0.6 | Distilled LoRA strength |
| `lora_detailer` | float | No | 1.0 | Detailer LoRA strength |
| `lora_i2v` | float | No | 0.8 | I2V Adapter LoRA strength (0 = disable) |
| `img_compression` | int | No | 23 | Image compression (0-50, lower = better) |
| `img_strength` | float | No | 1.0 | First frame injection strength (0-1) |
| `buffer_seconds` | float | No | 1.0 | Extra video buffer beyond audio duration |
| `fps` | int | No | 30 | Video frame rate (1-60) |

---

## Mode 2: Audio Generation (Image + Duration)

Generate video AND audio from just an image and duration (no input audio required).

### Request Format

```json
{
  "input": {
    "image_url": "https://example.com/portrait.jpg",
    "duration": 5.0,
    "prompt_positive": "A person speaking about nature",
    "quality_preset": "high"
  }
}
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `image_url` | string | Yes | - | URL to portrait image (JPG/PNG) |
| `duration` | float | Yes | - | Video/audio duration in seconds (1-30) |
| `prompt_positive` | string | No | "A person speaking naturally..." | Positive prompt |
| `prompt_negative` | string | No | "blurry, low quality..." | Negative prompt |
| `quality_preset` | string | No | "high" | Quality: `fast`, `high`, `ultra` |
| `width` | int | No | 1280 | Output width |
| `height` | int | No | 736 | Output height |
| `seed` | int | No | random | Random seed for reproducibility |
| `lora_camera` | float | No | 0.3 | Camera LoRA (0 = disable dolly-in) |
| `lora_distilled` | float | No | 0.6 | Distilled LoRA strength |
| `lora_detailer` | float | No | 1.0 | Detailer LoRA strength |
| `lora_i2v` | float | No | 0.8 | I2V Adapter LoRA strength (0 = disable) |
| `img_compression` | int | No | 23 | Image compression (0-50, lower = better) |
| `img_strength` | float | No | 1.0 | First frame injection strength (0-1) |
| `buffer_seconds` | float | No | 1.0 | Extra video buffer beyond target duration |
| `fps` | int | No | 30 | Video frame rate (1-60) |

### Audio Generation Notes

- Audio is generated at 25 Hz frame rate (LTX-2 native audio rate)
- Video is generated at 30 fps by default (configurable via `fps` parameter)
- Both are combined into a single MP4 file
- Generated audio matches the visual content based on the prompt

---

## Mode 3: Multi-Keyframe Video Generation

Generate video with multiple keyframe reference images. Supports both lip-sync (3a) and audio generation (3b).

**v56 Update**: Mode 3 now uses chained `LTXVAddGuide` nodes internally for improved stability and eliminates end-of-video flickering issues.

### Request Format - Mode 3a (Multi-keyframe + Lip-sync)

```json
{
  "input": {
    "keyframes": [
      {"image_url": "https://example.com/start.jpg", "frame_position": "first", "strength": 1.0},
      {"image_url": "https://example.com/end.jpg", "frame_position": "last", "strength": 0.8}
    ],
    "audio_url": "https://example.com/speech.mp3",
    "prompt_positive": "Smooth transition between keyframes...",
    "quality_preset": "high"
  }
}
```

### Request Format - Mode 3b (Multi-keyframe + Audio Generation)

```json
{
  "input": {
    "keyframes": [
      {"image_url": "https://example.com/start.jpg", "frame_position": "first", "strength": 1.0},
      {"image_url": "https://example.com/middle.jpg", "frame_position": 0.5, "strength": 0.7},
      {"image_url": "https://example.com/end.jpg", "frame_position": "last", "strength": 0.8}
    ],
    "duration": 10.0,
    "prompt_positive": "Natural motion with smooth transitions...",
    "quality_preset": "high"
  }
}
```

### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `keyframes` | array | Yes | - | Array of 1-9 keyframe objects |
| `keyframes[].image_url` | string | Yes | - | URL to keyframe image (JPG/PNG) |
| `keyframes[].frame_position` | string/float | No | auto | "first", "last", or 0.0-1.0 normalized |
| `keyframes[].strength` | float | No | 1.0/0.8 | Guide strength 0.0-1.0 |
| `audio_url` | string | Mode 3a | - | URL to audio file for lip-sync |
| `duration` | float | Mode 3b | - | Video duration in seconds (1-30) |
| `prompt_positive` | string | No | "A person speaks naturally..." | Positive prompt |
| `prompt_negative` | string | No | "static, blurry..." | Negative prompt |
| `quality_preset` | string | No | "high" | Quality: `fast`, `high`, `ultra` |
| `width` | int | No | 1280 | Output width |
| `height` | int | No | 736 | Output height |
| `seed` | int | No | random | Random seed for reproducibility |
| `lora_camera` | float | No | 0.3 | Camera LoRA (0 = disable dolly-in) |
| `lora_distilled` | float | No | 0.6 | Distilled LoRA strength (0 = disable, needs more steps) |
| `lora_detailer` | float | No | 1.0 | Detailer LoRA strength |
| `lora_i2v` | float | No | 0.8 | I2V Adapter LoRA strength (0 = disable) |
| `img_compression` | int | No | 23 | Image compression (0-50, lower = better) |
| `frame_alignment` | int | No | 8 | Keyframe alignment interval (set 1 to disable) |
| `steps` | int | No | preset | Sampling steps (recommend 25+ if lora_distilled=0) |
| `buffer_seconds` | float | No | 1.0 | Extra video buffer beyond input duration |
| `trim_to_audio` | bool | No | false | Trim output video to match audio length |
| `auto_buffer_guide` | bool/string | No | true | Buffer guide strategy (v59): `true`/`"add_node"`, `"extend_last"`, or `false`/`"none"` |
| `fps` | int | No | 30 | Video frame rate (1-60) |

### Frame Position

| Value | Description |
|-------|-------------|
| `"first"` | First frame (index 0) |
| `"last"` | Last frame (explicit last index) |
| `0.0-1.0` | Normalized position (0.0=first, 0.5=middle, 1.0=last) |

**Note**: Intermediate positions are aligned to 8-frame boundaries by default. Set `frame_alignment=1` to disable.

### Keyframe Defaults

- First keyframe: `frame_position: "first"`, `strength: 1.0`
- Last keyframe: `frame_position: "last"`, `strength: 0.8`
- Intermediate: Evenly distributed, `strength: 0.8`

### Keyframe Transition Behavior

**关键帧之间的过渡是平滑的 (Smooth Transitions)**

Mode 3 生成的视频中，关键帧之间会有自然的平滑过渡效果。这是 LTX-2 模型的默认行为，通过 `LTXVAddGuide` 节点的引导实现。

| 特性 | 说明 |
|------|------|
| 过渡类型 | 平滑过渡 (smooth transition) |
| 硬切支持 | 暂不支持 (not supported) |
| strength 作用 | 控制关键帧对该帧的引导强度，不控制过渡锐度 |

**注意**: 如需硬切 (hard cut) 效果，建议在后期处理阶段使用视频编辑工具实现。

### Mode 3 Notes

- **v56 Improvement**: Uses chained `LTXVAddGuide` nodes (fixes flickering issue from v53/v54)
- **Guide-based**: End frames are approximate guides, not exact matches
- **Max keyframes**: 1-9 keyframes supported
- **Strength tuning**: Lower strength (0.6-0.8) recommended for non-first frames
- **Mode Detection**: API auto-detects mode based on `audio_url` presence:
  - `audio_url` 存在 → Mode 3a (lip-sync)，以音频时长为准，忽略 `duration`
  - `audio_url` 不存在 → Mode 3b (audio generation)，使用 `duration` 参数

---

## Common Parameters

### Quality Presets

| Preset | Steps | Distilled | Detailer | Camera | I2V | Use Case |
|--------|-------|-----------|----------|--------|-----|----------|
| `fast` | 8 | 0.6 | 0.5 | 0.3 | 0.8 | Testing, iteration |
| `high` | 8 | 0.6 | 1.0 | 0.3 | 0.8 | Production (default) |
| `ultra` | 12 | 0.8 | 1.0 | 0.3 | 1.0 | Maximum quality |

### LoRA Parameters

| LoRA | Description | Range | Notes |
|------|-------------|-------|-------|
| `lora_camera` | Dolly-in camera effect | 0-1.0 | Set 0 to disable |
| `lora_distilled` | Inference acceleration | 0.4-0.8 | Lower = faster |
| `lora_detailer` | Detail enhancement | 0.5-1.0 | Higher = more detail |
| `lora_i2v` | I2V Adapter (image fidelity & motion) | 0-1.0 | Set 0 to disable; not trained on audio layers |

### Image Parameters

| Parameter | Description | Range | Notes |
|-----------|-------------|-------|-------|
| `img_compression` | First frame compression | 0-50 | Lower = better quality, may cause initial freeze |
| `img_strength` | First frame injection | 0-1.0 | Lower = more animation freedom |

### Buffer and Trimming

| Parameter | Description | Default | Notes |
|-----------|-------------|---------|-------|
| `buffer_seconds` | Extra video duration beyond input | 1.0 | Helps prevent end-of-video artifacts |
| `trim_to_audio` | Trim output to audio length | false | Only for Mode 3/4 |
| `auto_buffer_guide` | Buffer guide strategy | true | v59: Prevents buffer flickering |

**Buffer Guide Strategies (v59):**

| Value | Strategy | Description |
|-------|----------|-------------|
| `true` or `"add_node"` | 方案 A | Add implicit guide node at buffer end (default) |
| `"extend_last"` | 方案 C | Move last keyframe position to buffer end (no extra node) |
| `false` or `"none"` | 禁用 | No buffer guide, original v57 behavior |

**Strategy Comparison:**
- **add_node**: 添加一个隐式节点，复用最后关键帧的图像。优点：不改变用户关键帧语义；缺点：多一个节点。
- **extend_last**: 直接将最后关键帧移动到 buffer 末尾。优点：无额外节点；缺点：改变最后关键帧的原始位置。

**How they work together:**
- `buffer_seconds=1.0` + `trim_to_audio=false` → Video is 1s longer than input duration
- `buffer_seconds=1.0` + `trim_to_audio=true` → Generate 1s extra, then trim to match audio
- `auto_buffer_guide=true` → Strategy A: Add implicit guide at buffer end
- `auto_buffer_guide="extend_last"` → Strategy C: Move last keyframe to buffer end

**Use cases:**
- Prevent flickering (recommended): `buffer_seconds=1.0`, `auto_buffer_guide=true` (default)
- Fewer nodes: `buffer_seconds=1.0`, `auto_buffer_guide="extend_last"`
- No buffer guide: `auto_buffer_guide=false`
- No buffer: `buffer_seconds=0.0`

### Notes

- **Negative prompt**: Not effective at CFG=1.0 (current config uses distilled model)
- **Camera LoRA**: Creates a slow dolly-in (push) camera movement effect

---

## Response Format

### Mode 1 Success (Lip-sync)

```json
{
  "id": "job-id",
  "status": "COMPLETED",
  "output": {
    "status": "success",
    "output": {
      "video_url": "https://storage.googleapis.com/dramaland-public/ugc_media/{job_id}/ltx2_videos/{filename}.mp4",
      "gcs_url": "gs://dramaland-public/ugc_media/{job_id}/ltx2_videos/{filename}.mp4",
      "video_filename": "20260126_183520_ltx2_output_00001-audio.mp4",
      "video_size_bytes": 3167568,
      "resolution": "1280x736",
      "duration": "8.2s",
      "frames": 248,
      "fps": 30,
      "seed": 1769452070347,
      "quality_preset": "fast",
      "generation_time": 120.5
    }
  }
}
```

### Mode 2 Success (Audio Generation)

```json
{
  "id": "job-id",
  "status": "COMPLETED",
  "output": {
    "status": "success",
    "output": {
      "video_url": "https://storage.googleapis.com/dramaland-public/ugc_media/{job_id}/ltx2_videos/{filename}.mp4",
      "gcs_url": "gs://dramaland-public/ugc_media/{job_id}/ltx2_videos/{filename}.mp4",
      "video_filename": "20260127_120000_ltx2_output_00001-audio.mp4",
      "video_size_bytes": 2500000,
      "resolution": "1280x736",
      "duration": "5.0s",
      "frames": 151,
      "audio_frames": 125,
      "fps": 30,
      "seed": 1769452070347,
      "quality_preset": "high",
      "mode": "audio_gen",
      "generation_time": 90.5
    }
  }
}
```

### Mode 3a Success (Multi-keyframe + Lip-sync)

```json
{
  "id": "6e6b41ab-7f99-4965-8cb3-7747cb487880-e1",
  "status": "COMPLETED",
  "delayTime": 6380,
  "executionTime": 255342,
  "output": {
    "status": "success",
    "output": {
      "video_url": "https://storage.googleapis.com/dramaland-public/ugc_media/{job_id}/ltx2_videos/20260131_175533_ltx2_multiframe_00001-audio.mp4",
      "gcs_url": "gs://dramaland-public/ugc_media/{job_id}/ltx2_videos/20260131_175533_ltx2_multiframe_00001-audio.mp4",
      "video_filename": "20260131_175533_ltx2_multiframe_00001-audio.mp4",
      "video_size_bytes": 8777296,
      "resolution": "1280x736",
      "duration": "15.4s",
      "frames": 463,
      "fps": 30,
      "seed": 1769881892974,
      "quality_preset": "fast",
      "mode": "3a",
      "keyframes": 3,
      "generation_time": 254.8
    }
  }
}
```

### Mode 3b Success (Multi-keyframe + Audio Generation)

```json
{
  "id": "335baaef-24ad-4784-9986-f1104c0dfdbf-e1",
  "status": "COMPLETED",
  "delayTime": 7154,
  "executionTime": 321656,
  "output": {
    "status": "success",
    "output": {
      "video_url": "https://storage.googleapis.com/dramaland-public/ugc_media/{job_id}/ltx2_videos/20260131_174925_ltx2_multiframe_00001-audio.mp4",
      "gcs_url": "gs://dramaland-public/ugc_media/{job_id}/ltx2_videos/20260131_174925_ltx2_multiframe_00001-audio.mp4",
      "video_filename": "20260131_174925_ltx2_multiframe_00001-audio.mp4",
      "video_size_bytes": 4991000,
      "resolution": "1280x736",
      "duration": "10.0s",
      "frames": 301,
      "fps": 30,
      "seed": 1769881454461,
      "quality_preset": "fast",
      "mode": "3b",
      "keyframes": 3,
      "generation_time": 321.2
    }
  }
}
```

### Error

```json
{
  "id": "job-id",
  "status": "FAILED",
  "error": "Failed to download image: 404 Not Found"
}
```

## Examples

### cURL - Mode 1: Lip-sync (Basic)

```bash
curl -X POST "https://api.runpod.ai/v2/42qdgmzjc9ldy5/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "image_url": "https://example.com/portrait.jpg",
      "audio_url": "https://example.com/speech.mp3"
    }
  }'
```

### cURL - Mode 1: Disable Camera LoRA

```bash
curl -X POST "https://api.runpod.ai/v2/42qdgmzjc9ldy5/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "image_url": "https://example.com/portrait.jpg",
      "audio_url": "https://example.com/speech.mp3",
      "lora_camera": 0
    }
  }'
```

### cURL - Mode 2: Audio Generation

```bash
curl -X POST "https://api.runpod.ai/v2/42qdgmzjc9ldy5/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "image_url": "https://example.com/portrait.jpg",
      "duration": 5.0,
      "prompt_positive": "A person speaking about nature",
      "quality_preset": "high"
    }
  }'
```

### cURL - Mode 2: Fast Preview

```bash
curl -X POST "https://api.runpod.ai/v2/42qdgmzjc9ldy5/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "image_url": "https://example.com/portrait.jpg",
      "duration": 3.0,
      "quality_preset": "fast"
    }
  }'
```

### cURL - Mode 3a: Multi-keyframe + Lip-sync

```bash
curl -X POST "https://api.runpod.ai/v2/42qdgmzjc9ldy5/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "keyframes": [
        {"image_url": "https://example.com/start.jpg", "frame_position": "first", "strength": 1.0},
        {"image_url": "https://example.com/middle.jpg", "frame_position": 0.5, "strength": 0.8},
        {"image_url": "https://example.com/end.jpg", "frame_position": "last", "strength": 0.8}
      ],
      "audio_url": "https://example.com/speech.mp3",
      "prompt_positive": "A person speaking with expressive movements, natural lip sync",
      "quality_preset": "fast"
    }
  }'
```

### cURL - Mode 3b: Multi-keyframe + Audio Generation

```bash
curl -X POST "https://api.runpod.ai/v2/42qdgmzjc9ldy5/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "keyframes": [
        {"image_url": "https://example.com/start.jpg", "frame_position": "first", "strength": 1.0},
        {"image_url": "https://example.com/middle.jpg", "frame_position": 0.5, "strength": 0.8},
        {"image_url": "https://example.com/end.jpg", "frame_position": "last", "strength": 0.8}
      ],
      "duration": 10.0,
      "prompt_positive": "A person with expressive movements, smooth transitions between scenes",
      "quality_preset": "fast"
    }
  }'
```

### Python - Mode 1 (Lip-sync)

```python
import requests
import time

API_KEY = "your_runpod_api_key"
ENDPOINT = "https://api.runpod.ai/v2/42qdgmzjc9ldy5"

def generate_lipsync_video(
    image_url: str,
    audio_url: str,
    quality: str = "high",
    lora_camera: float = 0.3
) -> dict:
    """Generate lip-synced video from image and audio."""

    response = requests.post(
        f"{ENDPOINT}/run",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "input": {
                "image_url": image_url,
                "audio_url": audio_url,
                "quality_preset": quality,
                "lora_camera": lora_camera
            }
        }
    )
    job_id = response.json()["id"]
    print(f"Job submitted: {job_id}")

    # Poll for completion
    while True:
        result = requests.get(
            f"{ENDPOINT}/status/{job_id}",
            headers={"Authorization": f"Bearer {API_KEY}"}
        ).json()

        if result["status"] == "COMPLETED":
            return result["output"]["output"]
        if result["status"] == "FAILED":
            raise Exception(result.get("error", "Unknown error"))

        print(f"Status: {result['status']}")
        time.sleep(10)

# Usage
result = generate_lipsync_video(
    image_url="https://example.com/portrait.jpg",
    audio_url="https://example.com/speech.mp3",
    lora_camera=0  # Disable dolly-in effect
)
print(f"Video URL: {result['video_url']}")
```

### Python - Mode 2 (Audio Generation)

```python
def generate_video_with_audio(
    image_url: str,
    duration: float,
    prompt: str = "A person speaking naturally",
    quality: str = "high"
) -> dict:
    """Generate video AND audio from image and duration."""

    response = requests.post(
        f"{ENDPOINT}/run",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "input": {
                "image_url": image_url,
                "duration": duration,
                "prompt_positive": prompt,
                "quality_preset": quality
            }
        }
    )
    job_id = response.json()["id"]
    print(f"Job submitted: {job_id}")

    while True:
        result = requests.get(
            f"{ENDPOINT}/status/{job_id}",
            headers={"Authorization": f"Bearer {API_KEY}"}
        ).json()

        if result["status"] == "COMPLETED":
            return result["output"]["output"]
        if result["status"] == "FAILED":
            raise Exception(result.get("error", "Unknown error"))

        print(f"Status: {result['status']}")
        time.sleep(10)

# Usage
result = generate_video_with_audio(
    image_url="https://example.com/portrait.jpg",
    duration=5.0,
    prompt="A person speaking about technology"
)
print(f"Video URL: {result['video_url']}")
print(f"Mode: {result['mode']}")  # "audio_gen"
```

### Python - Mode 3 (Multi-keyframe)

```python
def generate_multiframe_video(
    keyframes: list,
    audio_url: str = None,
    duration: float = None,
    quality: str = "high"
) -> dict:
    """Generate video with multiple keyframe references."""

    input_data = {
        "keyframes": keyframes,
        "quality_preset": quality
    }

    if audio_url:
        input_data["audio_url"] = audio_url  # Mode 3a
    else:
        input_data["duration"] = duration    # Mode 3b

    response = requests.post(
        f"{ENDPOINT}/run",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        },
        json={"input": input_data}
    )
    job_id = response.json()["id"]
    print(f"Job submitted: {job_id}")

    while True:
        result = requests.get(
            f"{ENDPOINT}/status/{job_id}",
            headers={"Authorization": f"Bearer {API_KEY}"}
        ).json()

        if result["status"] == "COMPLETED":
            return result["output"]["output"]
        if result["status"] == "FAILED":
            raise Exception(result.get("error", "Unknown error"))

        print(f"Status: {result['status']}")
        time.sleep(10)

# Usage - Mode 3a (lip-sync with multiple keyframes)
result = generate_multiframe_video(
    keyframes=[
        {"image_url": "https://example.com/start.jpg", "frame_position": "first"},
        {"image_url": "https://example.com/end.jpg", "frame_position": "last", "strength": 0.8}
    ],
    audio_url="https://example.com/speech.mp3"
)
print(f"Video URL: {result['video_url']}")
print(f"Mode: {result['mode']}")  # "3a"

# Usage - Mode 3b (audio generation with multiple keyframes)
result = generate_multiframe_video(
    keyframes=[
        {"image_url": "https://example.com/pose1.jpg", "frame_position": "first"},
        {"image_url": "https://example.com/pose2.jpg", "frame_position": 0.5, "strength": 0.7},
        {"image_url": "https://example.com/pose3.jpg", "frame_position": "last", "strength": 0.8}
    ],
    duration=10.0
)
print(f"Mode: {result['mode']}")  # "3b"
print(f"Keyframes: {result['keyframes']}")  # 3
```

### TypeScript

```typescript
interface VideoResult {
  video_url: string;
  gcs_url: string;
  video_filename: string;
  video_size_bytes: number;
  resolution: string;
  duration: string;
  frames: number;
  audio_frames?: number;  // Mode 2 only
  fps: number;
  seed: number;
  quality_preset: string;
  mode?: string;
  keyframes?: number;  // Mode 3 only
  generation_time: number;
}

const API_KEY = process.env.RUNPOD_API_KEY;
const ENDPOINT = 'https://api.runpod.ai/v2/42qdgmzjc9ldy5';

// Mode 1: Lip-sync
async function generateLipsyncVideo(
  imageUrl: string,
  audioUrl: string,
  options: { quality?: string; loraCamera?: number } = {}
): Promise<VideoResult> {
  const submitRes = await fetch(`${ENDPOINT}/run`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      input: {
        image_url: imageUrl,
        audio_url: audioUrl,
        quality_preset: options.quality || 'high',
        lora_camera: options.loraCamera ?? 0.3,
      },
    }),
  });
  const { id: jobId } = await submitRes.json();

  while (true) {
    const statusRes = await fetch(`${ENDPOINT}/status/${jobId}`, {
      headers: { 'Authorization': `Bearer ${API_KEY}` },
    });
    const result = await statusRes.json();

    if (result.status === 'COMPLETED') return result.output.output;
    if (result.status === 'FAILED') throw new Error(result.error);

    await new Promise((r) => setTimeout(r, 10000));
  }
}

// Mode 2: Audio Generation
async function generateVideoWithAudio(
  imageUrl: string,
  duration: number,
  options: { prompt?: string; quality?: string } = {}
): Promise<VideoResult> {
  const submitRes = await fetch(`${ENDPOINT}/run`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      input: {
        image_url: imageUrl,
        duration: duration,
        prompt_positive: options.prompt || 'A person speaking naturally',
        quality_preset: options.quality || 'high',
      },
    }),
  });
  const { id: jobId } = await submitRes.json();

  while (true) {
    const statusRes = await fetch(`${ENDPOINT}/status/${jobId}`, {
      headers: { 'Authorization': `Bearer ${API_KEY}` },
    });
    const result = await statusRes.json();

    if (result.status === 'COMPLETED') return result.output.output;
    if (result.status === 'FAILED') throw new Error(result.error);

    await new Promise((r) => setTimeout(r, 10000));
  }
}

// Mode 3: Multi-keyframe
interface Keyframe {
  image_url: string;
  frame_position?: string | number;
  strength?: number;
}

async function generateMultiframeVideo(
  keyframes: Keyframe[],
  options: { audioUrl?: string; duration?: number; quality?: string } = {}
): Promise<VideoResult> {
  const input: any = {
    keyframes,
    quality_preset: options.quality || 'high',
  };

  if (options.audioUrl) {
    input.audio_url = options.audioUrl;  // Mode 3a
  } else {
    input.duration = options.duration;    // Mode 3b
  }

  const submitRes = await fetch(`${ENDPOINT}/run`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ input }),
  });
  const { id: jobId } = await submitRes.json();

  while (true) {
    const statusRes = await fetch(`${ENDPOINT}/status/${jobId}`, {
      headers: { 'Authorization': `Bearer ${API_KEY}` },
    });
    const result = await statusRes.json();

    if (result.status === 'COMPLETED') return result.output.output;
    if (result.status === 'FAILED') throw new Error(result.error);

    await new Promise((r) => setTimeout(r, 10000));
  }
}

// Usage
const lipsyncResult = await generateLipsyncVideo(
  'https://example.com/portrait.jpg',
  'https://example.com/speech.mp3',
  { loraCamera: 0 }
);

const audioGenResult = await generateVideoWithAudio(
  'https://example.com/portrait.jpg',
  5.0,
  { prompt: 'A person speaking about technology' }
);

const multiframeResult = await generateMultiframeVideo(
  [
    { image_url: 'https://example.com/start.jpg', frame_position: 'first' },
    { image_url: 'https://example.com/end.jpg', frame_position: 'last', strength: 0.8 }
  ],
  { audioUrl: 'https://example.com/speech.mp3' }
);
```

## Video Storage

Generated videos are stored in Google Cloud Storage:

```
https://storage.googleapis.com/dramaland-public/ugc_media/{job_id}/ltx2_videos/{filename}.mp4
```

## Performance

### Mode 1: Lip-sync

| Quality | Typical Time | Video Size |
|---------|-------------|------------|
| fast | 60-120s | ~3 MB |
| high | 120-180s | ~5 MB |
| ultra | 180-300s | ~8 MB |

*Times based on RTX 4090/5090, 10-second audio*

### Mode 2: Audio Generation

| Duration | Quality | Typical Time |
|----------|---------|-------------|
| 5s | fast | ~85s |
| 10s | fast | ~126s |
| 15s | fast | ~450s |

*Times based on RTX 4090/5090*

### Mode 3: Multi-keyframe

| Mode | Keyframes | Duration | Quality | Typical Time |
|------|-----------|----------|---------|--------------|
| 3a (lip-sync) | 3 | 15.4s (audio) | fast | ~255s |
| 3b (audio gen) | 3 | 10.0s | fast | ~321s |
| 3a (lip-sync) | 4 | 8s (audio) | fast | ~180s |
| 3b (audio gen) | 4 | 8s | fast | ~200s |

*Times based on RTX 4090/5090*

## Error Codes

| Error | Cause | Solution |
|-------|-------|----------|
| `Failed to download image` | Invalid image URL | Check URL accessibility |
| `Failed to download audio` | Invalid audio URL (Mode 1/3a) | Check URL accessibility |
| `Failed to download keyframe` | Invalid keyframe URL (Mode 3) | Check all keyframe URLs |
| `Duration must be at least 1 second` | duration < 1 | Use duration >= 1.0 |
| `Duration cannot exceed 30 seconds` | duration > 30 | Use duration <= 30.0 |
| `At least 1 keyframe is required` | Empty keyframes array | Provide at least 1 keyframe |
| `Maximum 9 keyframes supported` | Too many keyframes | Use 1-9 keyframes |
| `ComfyUI failed to start` | GPU initialization error | Retry request |
| `Generation timeout` | Processing exceeded 10 min | Use shorter duration or retry |
| `GCS upload failed` | Storage error | Video returned as base64 fallback |

## Limits

| Limit | Mode 1 | Mode 2 | Mode 3 |
|-------|--------|--------|--------|
| Max duration | ~30s (audio) | 30s | ~30s |
| Min duration | 1s | 1s | 1s |
| Max keyframes | 1 | 1 | 9 |
| Max file size | 50 MB/input | 50 MB | 50 MB/keyframe |
| Concurrent jobs | Worker pool | Worker pool | Worker pool |

## Changelog

### v61 (2026-02-22)
- **I2V Adapter LoRA**: 新增 MachineDelusions I2V Adapter LoRA (rank 256, ~4.93GB)
  - 提升图像保真度和运动连贯性
  - 新增 `lora_i2v` 参数（默认 0.8，0 = 禁用）
  - LoRA chain: Distilled → Detailer → Camera → **I2V Adapter** → Sampler
  - 注意：I2V Adapter 未训练音频层，可能对音频有轻微副作用
  - Quality Presets: fast/high = 0.8, ultra = 1.0

### v60 (2026-02-04)
- **帧率参数化**: 新增 `fps` 参数（默认 30fps，范围 1-60）
  - 所有模式均支持自定义帧率
  - 可设置 `"fps": 24` 获得电影标准帧率，减少约 20% 帧数和文件大小

### v59 (2026-02-03)
- **双策略支持**: `auto_buffer_guide` 参数现在支持多种值
  - `true` 或 `"add_node"`: 方案 A，添加隐式控制帧（默认，推荐）
  - `"extend_last"`: 方案 C，将最后关键帧位置移动到 buffer 末尾（无额外节点）
  - `false` 或 `"none"`: 禁用，保持 v57 行为
- **策略对比**:
  - `add_node`: 不改变用户关键帧语义，多一个节点
  - `extend_last`: 无额外节点，但最后关键帧位置被改变

### v58 (2026-02-03)
- **修复 buffer 区域闪烁**: 新增 `auto_buffer_guide` 参数（默认 `true`）
  - 当 `buffer_seconds > 0` 时，自动在 buffer 末尾添加隐式控制帧
  - 确保 buffer 区域有关键帧引导，避免闪烁

### v57 (2026-02-03)
- **修复闪烁**: "last" 关键帧位置现在也参与 `frame_alignment` 对齐，避免末尾闪烁
- **新增 `buffer_seconds` 参数**: 可配置生成视频比输入时长额外多出的时间（默认 1.0 秒）
  - Mode 1: 视频比音频多 buffer_seconds
  - Mode 2: 视频比目标 duration 多 buffer_seconds
  - Mode 3/4: 视频比音频/duration 多 buffer_seconds
- **与 `trim_to_audio` 配合使用**:
  - `buffer_seconds=1.0` + `trim_to_audio=true` → 生成多 1s，但输出时裁剪到音频长度
  - `buffer_seconds=1.0` + `trim_to_audio=false` → 保留完整生成视频（含 buffer）

### v56 (2026-02-03)
- **Mode 3 改进**: 使用链式 `LTXVAddGuide` 节点替代 `LTXVAddGuideMulti`，修复视频末尾闪烁问题
- **移除 Mode 4**: Mode 4 的链式实现已合并到 Mode 3，无需单独的 `use_chained_guides` 参数
- **平滑过渡**: 关键帧之间保持平滑过渡效果（不支持硬切）
- **实际部署版本**: v55 代码首次部署

### v54 (2026-02-01)
- 添加 `trim_to_audio` 和 `frame_alignment` 参数
- 添加 `steps` 参数用于自定义采样步数

### v53 (2026-01-31)
- 添加 Mode 3a/3b 多关键帧支持
- 使用 KJNodes 的 `LTXVAddGuideMulti` 节点
