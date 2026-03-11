#!/bin/bash
# =============================================================================
# LTX-2.3 Step 6: Docker build + push 到 DockerHub
# 与线上 LTX-2 环境完全隔离
# =============================================================================
#password
# 隔离策略：
#   1. 镜像名: nooka210/ltx23-worker:v1（与线上 ltx2-comfyui-worker:v62 不同）
#   2. RunPod: 创建新 Endpoint 时指定此镜像，得到新的 Endpoint ID
#   3. Network Volume: 创建新 Volume，不与线上共用
#
# 线上环境（不动）：
#   - Endpoint: 42qdgmzjc9ldy5
#   - Image: nooka210/ltx2-comfyui-worker:v62
#
# LTX-2.3 新部署：
#   - Endpoint: 新建
#   - Image: nooka210/ltx23-worker:v1
#
# =============================================================================

set -e

# 查找 docker 命令（macOS Docker Desktop 可能不在 PATH）
DOCKER_CMD=""
if command -v docker &>/dev/null; then
    DOCKER_CMD="docker"
elif [ -x "/usr/local/bin/docker" ]; then
    DOCKER_CMD="/usr/local/bin/docker"
elif [ -x "/Applications/Docker.app/Contents/Resources/bin/docker" ]; then
    DOCKER_CMD="/Applications/Docker.app/Contents/Resources/bin/docker"
elif [ -x "/opt/homebrew/bin/docker" ]; then
    DOCKER_CMD="/opt/homebrew/bin/docker"
fi

if [ -z "$DOCKER_CMD" ]; then
    echo "错误: 未找到 docker 命令"
    echo "请确保 Docker Desktop 已安装并启动"
    exit 1
fi

IMAGE_NAME="nooka210/ltx23-worker"
TAG="v1"

# 脚本在 ltx23/ 下，需在 docker/ 目录执行 build（build context）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$DOCKER_DIR"

# 检查 GCS 凭证文件（ltx23 专用，被 .gitignore 排除）
GCS_CREDS="$DOCKER_DIR/ltx23/gcs-credentials.json"
if [ ! -f "$GCS_CREDS" ]; then
    echo "错误: 未找到 $GCS_CREDS"
    echo ""
    echo "请复制服务账号 JSON 到 ltx23 目录："
    echo "  cp zzh/dramaland-agentic-service/app/core/service-account.json zzh/dl-ait2v/docker/ltx23/gcs-credentials.json"
    exit 1
fi

echo "=== LTX-2.3 构建（隔离模式）==="
echo "镜像: ${IMAGE_NAME}:${TAG}"
echo "Build context: $DOCKER_DIR"
echo "线上 ltx2-comfyui-worker:v62 不受影响"
echo ""

echo ">>> Building (linux/amd64)..."
$DOCKER_CMD build --platform linux/amd64 -f ltx23/Dockerfile -t "${IMAGE_NAME}:${TAG}" .

echo ""
echo ">>> Pushing to DockerHub..."
$DOCKER_CMD push "${IMAGE_NAME}:${TAG}"

echo ""
echo "=== 完成 ==="
echo "下一步：在 RunPod 创建新 Endpoint，Docker Image 填: ${IMAGE_NAME}:${TAG}"
echo "注意：选择新建的 Network Volume，不要选线上在用的"
