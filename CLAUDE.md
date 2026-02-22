# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.

## Project Overview

LTX-2 Video Generation RunPod Serverless API with four modes:
- **Mode 1 (Lip-sync)**: Image + Audio → Video with lip synchronization
- **Mode 2 (Audio Gen)**: Image + Duration → Video + Generated audio
- **Mode 3a (Multi-keyframe Lip-sync)**: Keyframes[] + Audio → Video (Chained LTXVAddGuide)
- **Mode 3b (Multi-keyframe Audio Gen)**: Keyframes[] + Duration → Video (Chained LTXVAddGuide)

Uses LTX-2 19B model with LoRA optimizations.

**Current Version**: v62 (zero-strength LoRA optimization)

## Architecture

```
Mode 1: User Request (image_url, audio_url, prompt)
Mode 2: User Request (image_url, duration, prompt)
Mode 3a: User Request (keyframes[], audio_url, prompt)
Mode 3b: User Request (keyframes[], duration, prompt)
    ↓
RunPod Serverless API (endpoint: 42qdgmzjc9ldy5)
    ↓
GPU Workers (RTX 4090/5090, 24GB+ VRAM)
    ├─ ComfyUI Framework
    ├─ LTX-2 19B Model (FP8)
    ├─ LoRA Models (distilled, detailer, camera, i2v-adapter)
    └─ KJNodes (Chained LTXVAddGuide for Mode 3)
    ↓
GCS Upload (dramaland-public bucket)
    ↓
Return video_url
```

## File Structure

```
LTX/
├── CLAUDE.md
├── docker/
│   ├── Dockerfile                    # Worker container (v51)
│   ├── workflow_ltx2_enhanced.json   # Mode 1: Lip-sync workflow
│   ├── workflow_ltx2_audio_gen.json  # Mode 2: Audio generation workflow
│   ├── workflow_ltx2_multiframe.json # Mode 3: Multi-keyframe workflow
│   ├── API.md                        # API documentation
│   └── pod_files/
│       ├── rp_handler.py             # RunPod handler (unified routing)
│       ├── url_downloader.py         # URL downloader
│       ├── workflow_builder.py       # Workflow builder (both modes)
│       ├── gcs_uploader.py           # GCS upload
│       ├── start_wrapper.sh          # Startup script
│       └── gcs-credentials.json      # GCS credentials
├── scripts/                          # Utility scripts
└── test/                             # Test files
```

## Key Commands

```bash
# Build & Push
cd docker
docker build --platform linux/amd64 -t nooka210/ltx2-comfyui-worker:v62 .
docker push nooka210/ltx2-comfyui-worker:v62

# Test Mode 1: Lip-sync
curl -X POST "https://api.runpod.ai/v2/42qdgmzjc9ldy5/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"image_url":"...","audio_url":"...","quality_preset":"fast"}}'

# Test Mode 2: Audio Generation
curl -X POST "https://api.runpod.ai/v2/42qdgmzjc9ldy5/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"image_url":"...","duration":5.0,"quality_preset":"fast"}}'

# Test Mode 3a: Multi-keyframe + Lip-sync
curl -X POST "https://api.runpod.ai/v2/42qdgmzjc9ldy5/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":{"keyframes":[{"image_url":"..."},{"image_url":"...","frame_position":"last"}],"audio_url":"..."}}'
```

## API

**Endpoint**: `https://api.runpod.ai/v2/42qdgmzjc9ldy5`

| Method | Path | Description |
|--------|------|-------------|
| POST | /run | Async job submission |
| POST | /runsync | Sync job (wait for result) |
| GET | /status/{id} | Check job status |

See `docker/API.md` for full documentation.

## Models (Network Volume)

| Model | Size | File |
|-------|------|------|
| Checkpoint | ~26GB | `checkpoints/ltx-2-19b-dev-fp8.safetensors` |
| Text Encoder | ~12GB | `text_encoders/gemma_3_12B_it_fp8_scaled.safetensors` |
| LoRA Distilled | ~7.6GB | `loras/ltx-video-2b-v0.9.7-distilled-lora-384.safetensors` |
| LoRA Detailer | ~2.5GB | `loras/ltx-video-2b-v0.9.7-detailer-lora-768.safetensors` |
| LoRA Camera | ~313MB | `loras/ltx-video-2b-v0.9.5-camera-control-dolly-in-lora.safetensors` |
| LoRA I2V Adapter | ~4.93GB | `loras/LTX-2-Image2Vid-Adapter.safetensors` |

## LoRA 配置

| LoRA | 作用 | 默认强度 |
|------|------|---------|
| Distilled | 加速推理 | 0.6 |
| Detailer | 增强细节 | 1.0 |
| Camera (dolly-in) | 推镜头效果 | 0.3 |
| I2V Adapter | 图像保真度与运动连贯性 | 0.8 |

## 图像参数

| 参数 | 作用 | 默认值 | 说明 |
|------|------|--------|------|
| img_compression | 首帧压缩 | 23 | 0-50，越低质量越好 |
| img_strength | 首帧注入 | 1.0 | 0-1，越低动画越自由 |

## 帧率配置

| 模态 | 帧率 | 计算公式 |
|------|------|---------|
| 视频 | 30 fps (默认，可通过 `fps` 参数配置 1-60) | `ceil(duration * fps) + 1` |
| 音频 | 25 Hz (固定，LTX-2 模型要求) | `ceil(duration * 25)` |

## API 模式

| 模式 | 输入 | 输出 |
|------|------|------|
| Mode 1 (Lip-sync) | image_url + audio_url | 视频 (lip-sync to audio) |
| Mode 2 (Audio Gen) | image_url + duration | 视频 + 生成音频 |
| Mode 3a (Multi-keyframe Lip-sync) | keyframes[] + audio_url | 多关键帧引导视频 + lip-sync |
| Mode 3b (Multi-keyframe Audio Gen) | keyframes[] + duration | 多关键帧引导视频 + 生成音频 |

## Mode 3 关键帧参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| keyframes | array | 必填 | 1-9 个关键帧对象 |
| keyframes[].image_url | string | 必填 | 关键帧图片 URL |
| keyframes[].frame_position | string/float | auto | "first", "last", 或 0.0-1.0 |
| keyframes[].strength | float | 1.0/0.8 | 引导强度 0.0-1.0 |
| buffer_seconds | float | 1.0 | 视频比输入时长多出的 buffer (v57+) |
| auto_buffer_guide | bool/string | true | Buffer 策略: `true`/`"add_node"`, `"extend_last"`, `false` (v59) |

## v59 Buffer 闪烁修复 (双策略)

v59 的 `auto_buffer_guide` 参数支持多种策略解决 buffer 区域闪烁问题：

| 值 | 策略 | 说明 |
|---|---|---|
| `true` 或 `"add_node"` | 方案 A | 添加隐式节点（默认，推荐）|
| `"extend_last"` | 方案 C | 将最后关键帧移动到 buffer 末尾 |
| `false` 或 `"none"` | 禁用 | 保持 v57 行为 |

**策略对比**:
- **add_node**: 复用最后关键帧图像，在 buffer 末尾添加隐式引导帧。不改变用户关键帧语义。
- **extend_last**: 直接将最后关键帧位置移动到 buffer 末尾。无额外节点，但改变了最后关键帧的原始位置。

**注意**: Mode 3 使用链式 LTXVAddGuide 节点（v56+ 已合并 Mode 4）

## Notes

- Video output: `gs://dramaland-public/ugc_media/{job_id}/ltx2_videos/`
- Network Volumes: `ltx2-models` (EU-RO-1), `ltx2-models-ustx3` (US-TX-3)
- Performance: ~60-120s for 10s video (quality: fast)
