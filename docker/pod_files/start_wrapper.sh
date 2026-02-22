#!/bin/bash

echo "==========================================="
echo "LTX-2 ComfyUI Serverless Worker v26"
echo "==========================================="

# Network Volume 路径检测
if [ -d "/runpod-volume/models" ]; then
    NETWORK_VOLUME="/runpod-volume"
elif [ -d "/workspace/models" ]; then
    NETWORK_VOLUME="/workspace"
else
    NETWORK_VOLUME=""
fi

COMFYUI_MODELS="/comfyui/models"
echo "Network Volume: ${NETWORK_VOLUME:-'Not found'}"

# 如果有 Network Volume，设置符号链接
if [ -n "$NETWORK_VOLUME" ] && [ -d "$NETWORK_VOLUME/models" ]; then
    echo "✅ Network Volume detected, setting up symlinks..."

    # 创建符号链接到 Network Volume
    for subdir in checkpoints text_encoders loras; do
        if [ -d "$NETWORK_VOLUME/models/$subdir" ]; then
            rm -rf "$COMFYUI_MODELS/$subdir" 2>/dev/null || true
            ln -sf "$NETWORK_VOLUME/models/$subdir" "$COMFYUI_MODELS/$subdir"
            echo "   Linked: $subdir"
        fi
    done

    MODEL_PATH="$NETWORK_VOLUME/models"
else
    echo "⚠️  No Network Volume, using local storage"
    MODEL_PATH="$COMFYUI_MODELS"
    mkdir -p "$MODEL_PATH/checkpoints" "$MODEL_PATH/text_encoders" "$MODEL_PATH/loras"
fi

# 兜底下载函数
download_if_missing() {
    local file="$1"
    local url="$2"
    local min_size="$3"

    if [ -f "$file" ]; then
        local size=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
        if [ "$size" -ge "$min_size" ]; then
            echo "✅ $(basename $file): $(numfmt --to=iec $size 2>/dev/null || echo ${size}B)"
            return 0
        fi
        echo "⚠️  $(basename $file) too small, re-downloading..."
        rm -f "$file"
    fi

    echo "📥 Downloading $(basename $file)..."
    wget -q --show-progress -O "$file" "$url" || {
        echo "❌ Download failed: $(basename $file)"
        return 1
    }
}

echo ""
echo "=== Checking Models ==="

# Checkpoint (~26GB)
download_if_missing \
    "$MODEL_PATH/checkpoints/ltx-2-19b-dev-fp8.safetensors" \
    "https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-19b-dev-fp8.safetensors" \
    18000000000 &

# Text Encoder (~13GB)
download_if_missing \
    "$MODEL_PATH/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors" \
    "https://huggingface.co/Kijai/LTXV2_comfy/resolve/main/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors" \
    12000000000 &

# LoRA distilled (~7.67GB)
download_if_missing \
    "$MODEL_PATH/loras/ltx-2-19b-distilled-lora-384.safetensors" \
    "https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-19b-distilled-lora-384.safetensors" \
    7000000000 &

# LoRA detailer (~2.5GB)
download_if_missing \
    "$MODEL_PATH/loras/ltx-2-19b-ic-lora-detailer.safetensors" \
    "https://huggingface.co/Lightricks/LTX-2-19b-IC-LoRA-Detailer/resolve/main/ltx-2-19b-ic-lora-detailer.safetensors" \
    2000000000 &

# LoRA camera (~313MB)
download_if_missing \
    "$MODEL_PATH/loras/ltx-2-19b-lora-camera-control-dolly-in.safetensors" \
    "https://huggingface.co/Lightricks/LTX-2-19b-LoRA-Camera-Control-Dolly-In/resolve/main/ltx-2-19b-lora-camera-control-dolly-in.safetensors" \
    200000000 &

# LoRA I2V Adapter (~4.93GB) - MachineDelusions Image2Video Adapter
download_if_missing \
    "$MODEL_PATH/loras/LTX-2-Image2Vid-Adapter.safetensors" \
    "https://huggingface.co/MachineDelusions/LTX-2_Image2Video_Adapter_LoRa/resolve/main/LTX-2-Image2Vid-Adapter.safetensors" \
    4000000000 &

# 等待所有下载完成
wait

echo ""
echo "=== Final Model Status ==="
ls -lh "$MODEL_PATH/checkpoints/" 2>/dev/null | grep -v "^total" | head -3
ls -lh "$MODEL_PATH/loras/" 2>/dev/null | grep -v "^total" | head -6

echo ""
echo "Starting RunPod Handler..."

# 调用原始启动脚本
exec /start.sh.original
