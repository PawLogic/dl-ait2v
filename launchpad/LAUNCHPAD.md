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
