#!/bin/bash
# ============================================================================
# Volume 同步脚本：从基线 Volume 同步到目标 Volume
#
# 同步内容:
#   - boot.sh                          (serverless 启动引导)
#   - handler/                          (serverless handler 代码)
#   - workflows/                        (workflow JSON)
#   - gcs-credentials.json              (GCS 凭证)
#   - custom_nodes/ComfyUI-ServerlessHandler/  (handler 启动钩子)
#   - .venv-cu128 site-packages 补丁包   (runpod, deepdiff 等)
#
# 不同步:
#   - models/       → 用 download_models.sh
#   - ComfyUI 本体  → 镜像 /start.sh 自动从镜像复制
#   - .venv-cu128   → 镜像 /start.sh 自动创建
#
# 用法:
#   ./sync_volume.sh --target-host <IP> --target-port <PORT>
#   ./sync_volume.sh --target-host <IP> --target-port <PORT> --dry-run
# ============================================================================

set -euo pipefail

SSH_KEY="$HOME/.ssh/id_ed25519"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=15"

# 基线 Pod SSH（每次开新 Pod 需更新）
SOURCE_HOST="213.173.103.164"
SOURCE_PORT="21595"

TARGET_HOST=""
TARGET_PORT=""

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
    cat << EOF
用法: $0 --target-host HOST --target-port PORT [--dry-run]

同步基线 Volume 的 serverless 代码到目标 Volume。
EOF
    exit 0
}

ssh_source() { ssh $SSH_OPTS -i "$SSH_KEY" "root@$SOURCE_HOST" -p "$SOURCE_PORT" "$@"; }
ssh_target() { ssh $SSH_OPTS -i "$SSH_KEY" "root@$TARGET_HOST" -p "$TARGET_PORT" "$@"; }

sync_dir() {
    local dir=$1
    local size
    size=$(ssh_source "du -sh '/workspace/$dir' 2>/dev/null | cut -f1" 2>/dev/null || echo "?")
    log_info "同步: $dir ($size)"
    if [ "$DRY_RUN" = true ]; then return; fi
    ssh_target "mkdir -p '/runpod-volume/$dir'"
    ssh_source "cd /workspace && tar cf - '$dir'" | ssh_target "cd /runpod-volume && tar xf -"
}

sync_file() {
    local file=$1
    log_info "同步: $file"
    if [ "$DRY_RUN" = true ]; then return; fi
    ssh_source "cat '/workspace/$file'" | ssh_target "cat > '/runpod-volume/$file'" 2>/dev/null || true
}

DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --target-host) TARGET_HOST="$2"; shift 2 ;;
        --target-port) TARGET_PORT="$2"; shift 2 ;;
        --dry-run)     DRY_RUN=true; shift ;;
        --help)        usage ;;
        *) log_error "未知参数: $1"; usage ;;
    esac
done

if [ -z "$TARGET_HOST" ] || [ -z "$TARGET_PORT" ]; then
    log_error "必须指定 --target-host 和 --target-port"
    usage
fi

echo "============================================"
echo " Volume 同步"
echo " 源: $SOURCE_HOST:$SOURCE_PORT (/workspace/)"
echo " 目标: $TARGET_HOST:$TARGET_PORT (/runpod-volume/)"
echo "============================================"

# 检查连接
ssh_source "echo ok" >/dev/null 2>&1 && log_info "源 Pod 连接成功" || { log_error "源 Pod 连接失败"; exit 1; }
ssh_target "echo ok" >/dev/null 2>&1 && log_info "目标 Pod 连接成功" || { log_error "目标 Pod 连接失败"; exit 1; }

START_TIME=$(date +%s)

# 代码文件
sync_dir "handler"
sync_dir "workflows"
sync_dir "runpod-slim/ComfyUI/custom_nodes/ComfyUI-ServerlessHandler"
sync_file "boot.sh"
sync_file "gcs-credentials.json"

# venv 补丁包（只同步我们额外装的包，不同步整个 venv）
log_info "同步 venv 补丁包..."
if [ "$DRY_RUN" = false ]; then
    VENV_SP="/workspace/runpod-slim/ComfyUI/.venv-cu128/lib/python3.12/site-packages"
    TARGET_VENV_SP="/runpod-volume/runpod-slim/ComfyUI/.venv-cu128/lib/python3.12/site-packages"
    PACKAGES="runpod google_cloud_storage google_auth google_api_core google_cloud_core google_resumable_media googleapis_common_protos google_crc32c proto librosa soundfile cpuinfo deepdiff rotary_embedding_torch imageio_ffmpeg piexif soxr lazy_loader pooch numba llvmlite joblib scikit_learn"
    for pkg in $PACKAGES; do
        if ssh_source "test -d '$VENV_SP/$pkg' || test -f '$VENV_SP/${pkg}.py'" 2>/dev/null; then
            ssh_source "cd '$VENV_SP' && tar cf - $pkg ${pkg}.py ${pkg}-*.dist-info 2>/dev/null" | \
                ssh_target "mkdir -p '$TARGET_VENV_SP' && cd '$TARGET_VENV_SP' && tar xf -" 2>/dev/null || true
        fi
    done
    log_info "venv 补丁包同步完成"
fi

ELAPSED=$(( $(date +%s) - START_TIME ))

echo ""
echo "============================================"
log_info "同步完成! 耗时: ${ELAPSED}s"
echo "============================================"
