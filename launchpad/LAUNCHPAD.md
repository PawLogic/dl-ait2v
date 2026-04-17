# Launchpad - Volume-Centric Serverless 部署

镜像不打包业务逻辑。Volume 是交付物，镜像只是运行环境。

## 架构

```
Serverless Worker 启动流程:

1. 容器启动，镜像 entrypoint 被 template 覆盖为:
   /sbin/docker-init -- bash /runpod-volume/boot.sh

2. boot.sh 执行:
   - 等待 Volume 挂载就绪
   - 创建 symlink: /workspace/runpod-slim → /runpod-volume/runpod-slim
   - 创建 symlink: /workspace/handler → /runpod-volume/handler
   - 创建 symlink: /workspace/workflows → /runpod-volume/workflows
   - exec /start.sh（镜像原始启动脚本）

3. /start.sh 执行:
   - 发现 /workspace/runpod-slim/ComfyUI 已存在（通过 symlink）→ 跳过复制
   - 激活 .venv-cu128（Volume 上的，含 runpod 等包）
   - 启动 ComfyUI

4. ComfyUI 加载 custom_nodes:
   - ComfyUI-ServerlessHandler/__init__.py 启动 RunPod handler 线程
   - Handler 连接 RunPod 任务队列，开始接收请求

5. 请求处理:
   - Handler 收到请求 → 加载 workflow → 下载媒体 → 提交 ComfyUI → 等待 → 上传 GCS → 返回
```

## 目录结构

```
launchpad/
├── LAUNCHPAD.md
├── serverless/                          # 部署到 Volume 的文件
│   ├── boot.sh                          #   → /runpod-volume/boot.sh (entrypoint)
│   ├── ComfyUI-ServerlessHandler/       #   → custom_nodes/ 下
│   │   └── __init__.py                  #     ComfyUI 启动时自动加载 handler
│   ├── rp_handler.py                    #   → /handler/ (通用 workflow runner)
│   ├── workflow_converter.py            #   → /handler/ (UI→API 格式转换)
│   ├── media_downloader.py              #   → /handler/ (媒体下载)
│   ├── gcs_uploader.py                  #   → /handler/ (GCS 上传)
│   ├── gcs-credentials.json             #   → Volume 根目录 (.gitignore)
│   └── init.sh                          #   (Pod 开发模式用，非 serverless)
├── volume/                              # Volume 管理脚本
│   ├── sync_volume.sh                   #   代码同步到其他 Volume
│   ├── download_models.sh               #   模型下载/校验
│   └── setup_venv.sh                    #   venv 环境搭建
└── test/
    └── test_serverless.sh               #   端到端测试
```

## Volume 结构

```
/runpod-volume/                          # Serverless worker 挂载点
├── boot.sh                              # Serverless 启动引导
├── gcs-credentials.json                 # GCS 凭证
├── handler/                             # Serverless handler 代码
│   ├── rp_handler.py
│   ├── workflow_converter.py
│   ├── media_downloader.py
│   └── gcs_uploader.py
├── workflows/                           # Workflow JSON（UI 或 API 格式）
├── runpod-slim/
│   ├── ComfyUI/
│   │   ├── custom_nodes/
│   │   │   ├── ComfyUI-ServerlessHandler/  # Handler 启动钩子
│   │   │   ├── ComfyUI-KJNodes/
│   │   │   ├── ComfyUI-LTXVideo/
│   │   │   └── ...
│   │   ├── models/                      # 模型文件 (~46GB)
│   │   └── .venv-cu128/                 # Python venv（含 runpod 等依赖）
│   └── filebrowser.db
├── init.sh                              # Pod 开发模式启动脚本
└── venv-cu130/                          # Pod 开发用 venv（serverless 不用）
```

## 关键点

- **Serverless 用 `.venv-cu128`**（镜像 /start.sh 硬编码），不是 `venv-cu130`
- **Volume 挂载在 `/runpod-volume/`**（非 `/workspace/`），boot.sh 通过 symlink 桥接
- **Handler 通过 custom node 启动**，不是 entrypoint/init.sh
- **Template**: `dramaland-serverless-boot`（ID: 0pmqlgeh7l），entrypoint 指向 `/runpod-volume/boot.sh`

## 同步到新 Volume

```bash
# 1. 开临时 Pod（runpod/base 模板，快速启动）
# 2. 从基线 Pod 同步代码
./sync_volume.sh --target-host <IP> --target-port <PORT>
# 3. 停掉临时 Pod
# 4. .venv-cu128 会在首次 serverless worker 启动时由镜像创建
#    但缺少 runpod 等包 → 需要手动装一次或在 boot.sh 里自动装
```

## 当前基线

- Volume: `eu-ro-1` (ID: koihtblqmz, DC: EU-RO-1)
- Endpoint: `dramaland-ai` (ID: bm9lmit6l51900)
- Template: `dramaland-serverless-boot` (ID: 0pmqlgeh7l)
- GPU: RTX 5090 / CUDA 13.0

---

## 运行时实测结构（2026-04-17，SSH 基线 Pod 验证）

### Volume 布局

```
/runpod-volume/
├── boot.sh                     # serverless 真入口
├── init.sh                     # 遗留，已不走主路径
├── gcs-credentials.json        # GCS 上传
├── runpod-slim/
│   ├── comfyui_args.txt
│   ├── filebrowser.db
│   └── ComfyUI/
│       ├── main.py
│       ├── .venv-cu128/        # 主 venv（py3.12, --system-site-packages）
│       ├── models/             # ~46 GB
│       │   ├── diffusion_models/   23G  (LTX-2)
│       │   ├── text_encoders/      15G
│       │   ├── loras/              7.1G
│       │   └── vae/                1.4G
│       └── custom_nodes/
│           ├── ComfyUI-ServerlessHandler/  ← 把 handler 寄生进 ComfyUI 进程
│           ├── ComfyUI-LTXVideo
│           ├── ComfyUI-KJNodes
│           ├── ComfyUI-VideoHelperSuite
│           ├── ComfyUI-MelBandRoFormer
│           ├── ComfyUI-RunpodDirect
│           ├── ComfyUI-Crystools
│           ├── ComfyUI-Custom-Scripts
│           ├── ComfyUI-Manager
│           └── Civicomfy
├── handler/
│   ├── rp_handler.py           # 563 行，主 handler
│   ├── workflow_converter.py   # 263 行，UI→API 自动转
│   ├── media_downloader.py
│   └── gcs_uploader.py
├── workflows/
│   ├── workflow_ltx23_multiframe_v1.json
│   ├── workflow_ltx23_audio_multiframe_v2.json
│   └── workflow_ltx23_audio_multiframe_v2_meta.json   # 可选子图开关元数据
└── venv-cu130/                 # 旧 init.sh 路径的独立 venv，serverless 不用
```

### 启动链（serverless 冷启动）

1. Template entrypoint → `bash /runpod-volume/boot.sh`
2. **boot.sh**（volume 上）：等 volume → 把 `/runpod-volume/{runpod-slim, handler, workflows, gcs-credentials.json}` symlink 进 `/workspace/` → `exec /start.sh`
3. **/start.sh**（镜像烘焙）：起 sshd、jupyter、filebrowser → 激活 `.venv-cu128` → `python main.py --listen 0.0.0.0 --port 8188`
4. ComfyUI 启动时扫 `custom_nodes/`
5. **ComfyUI-ServerlessHandler/\_\_init\_\_.py** 被 import：检测 `RUNPOD_POD_ID` → 开 **daemon thread** → `from rp_handler import handler` → **monkey-patch `signal.signal` 为 no-op**（解决 signal 不能在非主线程注册）→ `runpod.serverless.start({"handler": handler})`

主线程跑 ComfyUI（占 8188），从线程跑 RunPod handler；handler 内部走 localhost HTTP 调 ComfyUI。

### 脚本配合关系

| 脚本 | 住哪 | 职责 |
|---|---|---|
| `boot.sh` | Volume | 把 volume 三个目录 symlink 到 `/workspace/`，抹平镜像 hardcode |
| `/start.sh` | 镜像 | 起辅助服务 + venv + ComfyUI 主进程 |
| `ComfyUI-ServerlessHandler/__init__.py` | Volume（custom_node） | 在 ComfyUI 进程内起 daemon thread 跑 handler |
| `rp_handler.py` | Volume | 接 RunPod job → 转换/活化 workflow → 调 ComfyUI → 收 output → 上 GCS |
| `init.sh` | Volume | 老路径（独立 venv 启 ComfyUI+handler），现已不用 |

### Workflow 自动转化（UI → API）

`rp_handler.load_workflow()` 流程：

1. 读 `/workspace/workflows/<name>.json`
2. `workflow_converter.is_ui_format()` 判定：有 `nodes[]` + `links[]` 就是 UI 格式（ComfyUI web 端 "Save" 导出的）
3. UI 格式 → `convert_ui_to_api()`：
   - 拉 ComfyUI `/object_info` 解析 widget 名
   - 处理 KJNodes `SetNode`/`GetNode`（命名变量 pass-through）
   - 内联 `PrimitiveNode` 常量
   - 跳过 `Reroute`/`Note`、muted 节点（mode=2/4）
   - 支持 `COMFY_DYNAMICCOMBO_V3` 动态输入（LTXVAddGuideMulti）
   - `fix_dangling_refs`：Switch 的 `on_true` 断掉时退化到 `on_false`
4. 可选同名 `<name>_meta.json` 描述 `frame_chains` + `audio_chain`：
   - 按请求 `images[]` 长度 un-mute 对应 frame 子图
   - 按是否有 `audio_url` un-mute audio 链路
   - `apply_switch_booleans` 翻 Switch 的 boolean 字段（`boolean` 或 `value`）

请求形态：

```json
{
  "input": {
    "workflow": "workflow_ltx23_audio_multiframe_v2",
    "image_url": "...",
    "audio_url": "...",
    "images": ["url1", "url2"],
    "overrides": {"315": {"noise_seed": 42}, "299": {"width": 1280}}
  }
}
```

Handler 用 `INPUT_NODE_MAP`（`LoadImage` / `VHS_LoadAudioUpload` / `LoadAudio` / `VHS_LoadVideo`）按 node ID 升序自动对槽，`overrides` 可按 node_id 覆盖任意字段。

### 注意点

- `init.sh` 和 `venv-cu130/` 是老路径遗留，serverless 主路径完全不走，可考虑清理避免混淆
- `.venv-cu128` 命名是历史包袱，实际 PyTorch 是 cu130（吃镜像 system-site-packages）
- Volume 同时存 code + 46 GB models，跨 DC 复制是纯 rsync 工作
