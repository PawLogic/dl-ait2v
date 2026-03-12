# LTX-2.3 API

## 原理简述

1. **RunPod** 收到 POST 请求后，调用容器内的 `handler(event)`
2. **rp_handler** 从 `event["input"]` 读取 `image_url`、`audio_url`、`prompt_positive` 等
3. 下载图片和音频 → 上传到 ComfyUI input 目录
4. 加载 `workflow_ltx2-3_audio_gen.json`，按节点 ID 替换：
   - Node 301: 图片文件名
   - Node 347: 音频文件名
   - Node 279/280: prompt 文本
   - seed 由 workflow 自动随机，无需传入
5. 提交给 ComfyUI `/prompt`，轮询 `/history` 等待完成
6. 上传视频到 GCS，返回 `video_url`

---

## 正确的 POST Body

```json
{
  "input": {
    "image_url": "https://itchy-lime-q49kq0fex1.edgeone.app/20260310-140254.jpg",
    "audio_url": "https://quiet-scarlet-jq6kfzhzdk.edgeone.app/bazooka_19_37.mp3",
    "prompt_positive": "A mouse sing naturally with perfect lip synchronization, high quality, detailed facial expressions,he dance with rap music",
    "prompt_negative": "low quality, blurry, watermark"
  }
}
```

### 参数说明

| 参数 | 必填 | 说明 |
|------|:----:|------|
| image_url | ✓ | 人像图片 URL（JPG/PNG，建议 512x512 以上） |
| audio_url | ✓ | 音频 URL（MP3/WAV，口型将与此音频同步） |
| prompt_positive | | 正向 prompt，默认口型同步描述 |
| prompt_negative | | 负向 prompt |

---

## 请求示例

```bash
curl -X POST "https://api.runpod.ai/v2/YOUR_ENDPOINT_ID/run" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "image_url": "https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=512",
      "audio_url": "https://your-cdn.com/speech.mp3",
      "prompt_positive": "A person speaks naturally with perfect lip sync"
    }
  }'
```

---

## 返回示例

成功时 `output` 包含：
- `video_url`: GCS 公网 URL
- `duration`: 视频时长
- `generation_time`: 生成耗时（秒）
