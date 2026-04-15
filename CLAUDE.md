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

## Architecture (Volume-Centric Serverless)

两套部署方式并存：

- **docker/** — 旧 Docker-embedded 方式（Dockerfile 打包所有逻辑）
- **launchpad/** — 新 Volume-Centric 方式（镜像只是运行环境，Volume 是交付物）

### Volume-Centric 架构（当前主力）

```
请求 → RunPod Serverless Endpoint (dramaland-ai)
       → Worker 启动: runpod/comfyui:cuda13.0 镜像
       → boot.sh: symlink Volume → /workspace/
       → /start.sh: 启动 ComfyUI (用 Volume 上的 .venv-cu128)
       → ComfyUI-ServerlessHandler: 启动 RunPod handler 线程
       → handler 收到请求 → 加载 workflow → 下载媒体
       → 提交 ComfyUI /prompt → 等待生成 → 上传 GCS → 返回 URL
```

关键特性：
- **Workflow 解耦** — handler 不绑定任何 workflow，自动扫描 /workflows/ 目录
- **UI 格式自动转换** — ComfyUI Save 的 UI 格式自动转成 API 格式
- **多 Volume 多 DC** — 同一个 Template 绑定不同 DC 的 Volume

### 当前部署状态

| 资源 | ID | 说明 |
|---|---|---|
| Endpoint | bm9lmit6l51900 | dramaland-ai，公司级 AI 中控 |
| Template | 0pmqlgeh7l | dramaland-serverless-boot |
| 基线 Volume | koihtblqmz | eu-ro-1 (EU-RO-1) |
| 基线 Pod | cx5lmple44ckep | 开发用，SSH: root@213.173.103.164:21595 |

## File Structure

```
dl-ait2v/
├── CLAUDE.md
├── docker/                              # 旧 Docker-embedded 方式
│   ├── Dockerfile
│   ├── pod_files/                       # 旧 handler（参考用）
│   └── ...
├── launchpad/                           # Volume-Centric Serverless
│   ├── LAUNCHPAD.md                     # 部署文档
│   ├── serverless/                      # 部署到 Volume 的文件
│   │   ├── boot.sh                      #   Serverless 启动引导
│   │   ├── ComfyUI-ServerlessHandler/   #   ComfyUI custom node (handler 启动钩子)
│   │   ├── rp_handler.py                #   通用 workflow runner
│   │   ├── workflow_converter.py        #   UI→API 格式转换
│   │   ├── media_downloader.py          #   媒体下载
│   │   ├── gcs_uploader.py              #   GCS 上传
│   │   └── init.sh                      #   Pod 开发模式启动脚本
│   ├── volume/                          # Volume 管理脚本
│   │   ├── sync_volume.sh               #   同步代码到其他 Volume
│   │   ├── download_models.sh           #   模型下载/校验
│   │   └── setup_venv.sh                #   venv 环境搭建
│   └── test/
│       └── test_serverless.sh           #   端到端测试
├── scripts/
└── test/
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
