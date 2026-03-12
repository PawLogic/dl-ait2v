# LTX-2.3 架构说明

**原则**：ltx23 目录完全自包含，不修改 `pod_files/` 及主 Dockerfile 等已有文件。

---

## 目录结构

```
ltx23/
├── doc/                   # 文档
│   ├── ARCHITECTURE.md    # 本文件
│   ├── API.md
│   ├── DEPENDENCIES.md
│   └── DEPLOY_ISOLATION.md
├── Dockerfile
├── start_wrapper.sh
├── rp_handler.py
├── url_downloader.py
├── gcs_uploader.py
├── gcs-credentials.json
└── build_and_push.sh
```

**依赖关系**：仅从 `../workflow_ltx2-3_audio_gen.json` 读取 workflow，不依赖 `pod_files/`。

---

## 调用链路

```
RunPod 收到 POST 请求
    ↓
runpod.serverless.start({"handler": handler})
    ↓
handler(event) 被调用，event["input"] = 请求体中的 input
    ↓
1. 下载 image_url、audio_url
2. 上传到 ComfyUI input 目录
3. 加载 workflow_ltx2-3_audio_gen.json
4. 替换 Node 301/347/279/280 的 inputs（seed 由 workflow 自动随机）
5. POST 到 ComfyUI /prompt
6. 轮询 /history 等待完成
7. 上传视频到 GCS，返回 video_url
```

---

## Workflow 节点映射

| API 入参 | Workflow 节点 | 替换字段 |
|----------|---------------|----------|
| image_url → 下载后的文件名 | Node 301 (LoadImage) | inputs.image |
| audio_url → 下载后的文件名 | Node 347 (VHS_LoadAudioUpload) | inputs.audio |
| prompt_positive | Node 279 (CLIPTextEncode) | inputs.text |
| prompt_negative | Node 280 (CLIPTextEncode) | inputs.text |
| seed | - | workflow 已有自动随机，无需传入 |

---

## 与 LTX-2 的关系

| 组件 | LTX-2 (pod_files) | LTX-2.3 (ltx23) |
|------|-------------------|-----------------|
| rp_handler | 通用，支持 Mode 1/2/3 | 专用，仅图片+音频口型同步 |
| workflow | ltx2_enhanced, ltx2_audio_gen | workflow_ltx2-3_audio_gen |
| workflow_builder | 需要 | 不需要，直接 JSON 替换 |
