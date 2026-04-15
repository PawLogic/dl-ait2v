#!/bin/bash
# ============================================================================
# Venv 环境搭建脚本：在目标 Pod 上运行
#
# 创建或更新 /workspace/venv-cu130 并安装所有依赖
# 用于新 Volume 初始化或 custom_nodes 依赖变更后重建
#
# 用法:
#   ./setup_venv.sh              # 创建/更新 venv
#   ./setup_venv.sh --rebuild    # 删除并重建 venv
# ============================================================================

set -euo pipefail

VENV_PATH="/workspace/venv-cu130"
COMFYUI_PATH="/workspace/runpod-slim/ComfyUI"
REBUILD=false

[ "${1:-}" = "--rebuild" ] && REBUILD=true

echo "=== Venv Setup ==="

if [ "$REBUILD" = true ] && [ -d "$VENV_PATH" ]; then
    echo "Removing existing venv..."
    rm -rf "$VENV_PATH"
fi

if [ ! -d "$VENV_PATH" ]; then
    echo "Creating venv at $VENV_PATH..."
    python3 -m venv "$VENV_PATH" --system-site-packages
fi

source "$VENV_PATH/bin/activate"
echo "Python: $(python3 --version)"
echo "Pip: $(pip --version)"

# ── Core packages ──
echo ""
echo "=== Installing core packages ==="
pip install --upgrade pip
pip install runpod google-cloud-storage requests

# ── ComfyUI requirements ──
if [ -f "$COMFYUI_PATH/requirements.txt" ]; then
    echo ""
    echo "=== ComfyUI requirements ==="
    pip install -r "$COMFYUI_PATH/requirements.txt" || true
fi

# ── Custom nodes dependencies ──
echo ""
echo "=== Custom nodes dependencies ==="
for req in "$COMFYUI_PATH"/custom_nodes/*/requirements.txt; do
    if [ -f "$req" ]; then
        node_name=$(basename "$(dirname "$req")")
        echo "  $node_name..."
        pip install -r "$req" 2>/dev/null || echo "  Warning: some deps failed for $node_name"
    fi
done

# ── Extra packages (not in any requirements.txt) ──
echo ""
echo "=== Extra packages ==="
pip install sageattention --no-build-isolation 2>/dev/null || echo "SageAttention skipped"
pip install rotary_embedding_torch imageio-ffmpeg deepdiff piexif librosa soundfile 2>/dev/null || true

echo ""
echo "=== Done ==="
echo "Total packages: $(pip list 2>/dev/null | wc -l)"
