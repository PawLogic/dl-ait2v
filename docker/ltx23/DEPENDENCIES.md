# LTX-2.3 Audio Gen 依赖清单

用于 `workflow_ltx2-3_audio_gen.json` 部署到**新** RunPod Endpoint。  
**不影响当前线上 LTX-2 环境。**

---

## A. Custom Nodes 清单

| 包名 | GitHub | 提供的 class_type |
|------|--------|------------------|
| ComfyUI-LTXVideo | https://github.com/Lightricks/ComfyUI-LTXVideo | LTXVConditioning, LTXVImgToVideoInplace, LTXVPreprocess, LTXVAddGuideMulti, LTXVConcatAVLatent, LTXVSeparateAVLatent, LTXVAudioVAEEncode, LTXVAudioVAELoader |
| ComfyUI-KJNodes | https://github.com/kijai/ComfyUI-KJNodes | DiffusionModelLoaderKJ, VAELoaderKJ, ImageResizeKJv2, VisualizeSigmasKJ |
| ComfyUI-VideoHelperSuite | https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite | VHS_LoadAudioUpload, CreateVideo, SaveVideo, Video Slice |
| ComfyUI-MelBandRoFormer | https://github.com/chflame163/ComfyUI-MelBandRoFormer | MelBandRoFormerModelLoader, MelBandRoFormerSampler |
| ComfyUI-Custom-Scripts | https://github.com/pythongosssss/ComfyUI-Custom-Scripts | MathExpression\|pysssss |

**注意**：workflow 中 Node 254 使用 `Switch any [Crystools]`。若未安装 ComfyUI-Crystools，需在 workflow 中移除该 Switch 或改为固定走 BasicScheduler 路径。

---

## B. Model 清单

| 文件名 | 大小 | HuggingFace 下载链接 | ComfyUI 子目录 |
|--------|------|---------------------|---------------|
| ltx-2.3-22b-dev_transformer_only_fp8_scaled.safetensors | ~23.5 GB | https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/diffusion_models/ltx-2.3-22b-dev_transformer_only_fp8_scaled.safetensors | diffusion_models/ |
| gemma_3_12B_it_fp8_scaled.safetensors | ~13 GB | https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors | text_encoders/ |
| ltx-2.3_text_projection_bf16.safetensors | ~2.31 GB | https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/text_encoders/ltx-2.3_text_projection_bf16.safetensors | text_encoders/ |
| LTX23_video_vae_bf16.safetensors | ~1.45 GB | https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/vae/LTX23_video_vae_bf16.safetensors | vae/ |
| LTX23_audio_vae_bf16.safetensors | ~365 MB | https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/vae/LTX23_audio_vae_bf16.safetensors | vae/ |
| ltx-2.3-22b-distilled-lora-384.safetensors | ~7.61 GB | https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-distilled-lora-384.safetensors | loras/ |
| MelBandRoformer_fp16.safetensors | ~456 MB | https://huggingface.co/Kijai/MelBandRoFormer_comfy/resolve/main/MelBandRoformer_fp16.safetensors | mel_band_roformer/ |

**模型总大小**：约 48.7 GB

**说明**：
- `latent_upscale_model.safetensors`（Node 244）为孤立节点，无其他节点引用，可不下载。
- `gemma_3_12B_it_fp8_scaled.safetensors` 若现有 Network Volume 已有，可复用。

---

## 目录结构

```
zzh/dl-ait2v/docker/
├── Dockerfile              # 线上 LTX-2，不修改
├── pod_files/
│   └── start_wrapper.sh     # 线上 LTX-2，不修改
├── workflow_ltx2-3_audio_gen.json
└── ltx23/
    ├── DEPENDENCIES.md      # 本文件（LTX-2.3 依赖清单）
    ├── DEPLOY_ISOLATION.md  # 隔离说明
    ├── build_and_push.sh   # Step 6 构建脚本
    ├── Dockerfile           # LTX-2.3 专用，全新 Endpoint
    ├── gcs-credentials.json # GCS 凭证（本地复制，.gitignore 排除）
    └── start_wrapper.sh     # LTX-2.3 模型下载逻辑
```

## Step 6: 构建与部署

**前置条件**：需准备 `ltx23/gcs-credentials.json`（GCS 服务账号凭证）。可复制：`cp zzh/dramaland-agentic-service/app/core/service-account.json zzh/dl-ait2v/docker/ltx23/gcs-credentials.json`。该文件被 .gitignore 排除。

```bash
cd zzh/dl-ait2v/docker/ltx23
./build_and_push.sh
```

或手动执行：

```bash
cd zzh/dl-ait2v/docker
docker build --platform linux/amd64 -f ltx23/Dockerfile -t nooka210/ltx23-worker:v1 .
docker push nooka210/ltx23-worker:v1
```

在 RunPod 创建**新** Endpoint 时使用 `nooka210/ltx23-worker:v1`，与线上 LTX-2 Endpoint 完全隔离。详见 `DEPLOY_ISOLATION.md`。
