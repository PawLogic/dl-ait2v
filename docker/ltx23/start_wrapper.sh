#!/bin/bash

echo "==========================================="
echo "LTX-2.3 ComfyUI Serverless Worker"
echo "全新 Endpoint，不影响线上 LTX-2"
echo "==========================================="

# Network Volume 路径检测（RunPod 挂载到 /runpod-volume，新建时可能为空）
if [ -d "/runpod-volume" ]; then
    NETWORK_VOLUME="/runpod-volume"
elif [ -d "/workspace" ]; then
    NETWORK_VOLUME="/workspace"
else
    NETWORK_VOLUME=""
fi

COMFYUI_MODELS="/comfyui/models"
echo "Network Volume: ${NETWORK_VOLUME:-'Not found'}"

# 如果有 Network Volume，创建 models 并设置符号链接
if [ -n "$NETWORK_VOLUME" ]; then
    echo "✅ Network Volume detected, setting up symlinks..."

    MODEL_PATH="$NETWORK_VOLUME/models"
    mkdir -p "$MODEL_PATH"
    # 确保目录存在并创建符号链接（首次冷启动时目录可能不存在）
    for subdir in checkpoints diffusion_models text_encoders vae loras mel_band_roformer; do
        mkdir -p "$MODEL_PATH/$subdir"
        rm -rf "$COMFYUI_MODELS/$subdir" 2>/dev/null || true
        ln -sf "$MODEL_PATH/$subdir" "$COMFYUI_MODELS/$subdir"
        echo "   Linked: $subdir"
    done
else
    echo "⚠️  No Network Volume, using local storage"
    MODEL_PATH="$COMFYUI_MODELS"
    mkdir -p "$MODEL_PATH/checkpoints" "$MODEL_PATH/diffusion_models" "$MODEL_PATH/text_encoders" \
             "$MODEL_PATH/vae" "$MODEL_PATH/loras" "$MODEL_PATH/mel_band_roformer"
fi

# SKIP_AUTO_DOWNLOAD=1：跳过自动下载，使用手动下载的模型
if [ -n "$SKIP_AUTO_DOWNLOAD" ]; then
    echo "SKIP_AUTO_DOWNLOAD=1: 跳过自动下载，使用 Volume 中已有模型"
else
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

    mkdir -p "$(dirname "$file")"
    echo "📥 Downloading $(basename $file)..."
    wget -q --show-progress -O "$file" "$url" || {
        echo "❌ Download failed: $(basename $file)"
        return 1
    }
}

echo ""
echo "=== Checking LTX-2.3 Models ==="

# Diffusion model (~23.5GB)
download_if_missing \
    "$MODEL_PATH/diffusion_models/ltx-2.3-22b-dev_transformer_only_fp8_scaled.safetensors" \
    "https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/diffusion_models/ltx-2.3-22b-dev_transformer_only_fp8_scaled.safetensors" \
    20000000000 &

# Text Encoder gemma (~13GB)
download_if_missing \
    "$MODEL_PATH/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors" \
    "https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors" \
    12000000000 &

# Text projection (~2.31GB)
download_if_missing \
    "$MODEL_PATH/text_encoders/ltx-2.3_text_projection_bf16.safetensors" \
    "https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/text_encoders/ltx-2.3_text_projection_bf16.safetensors" \
    2000000000 &

# Video VAE (~1.45GB)
download_if_missing \
    "$MODEL_PATH/vae/LTX23_video_vae_bf16.safetensors" \
    "https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/vae/LTX23_video_vae_bf16.safetensors" \
    1300000000 &

# Audio VAE (~365MB) - LTXVAudioVAELoader 从 checkpoints 加载
download_if_missing \
    "$MODEL_PATH/checkpoints/LTX23_audio_vae_bf16.safetensors" \
    "https://huggingface.co/Kijai/LTX2.3_comfy/resolve/main/vae/LTX23_audio_vae_bf16.safetensors" \
    300000000 &

# LoRA distilled (~7.61GB)
download_if_missing \
    "$MODEL_PATH/loras/ltx-2.3-22b-distilled-lora-384.safetensors" \
    "https://huggingface.co/Lightricks/LTX-2.3/resolve/main/ltx-2.3-22b-distilled-lora-384.safetensors" \
    7000000000 &

# MelBandRoFormer (~456MB) - ComfyUI-MelBandRoFormer 从 diffusion_models 加载
download_if_missing \
    "$MODEL_PATH/diffusion_models/MelBandRoformer_fp16.safetensors" \
    "https://huggingface.co/Kijai/MelBandRoFormer_comfy/resolve/main/MelBandRoformer_fp16.safetensors" \
    400000000 &

wait
fi

echo ""
echo "=== Final Model Status ==="
ls -lh "$MODEL_PATH/diffusion_models/" 2>/dev/null | grep -v "^total" | head -3
ls -lh "$MODEL_PATH/loras/" 2>/dev/null | grep -v "^total" | head -3

# 确保 test_input.json 存在，避免 RunPod Handler "not found, exiting"（不依赖镜像 COPY）
for d in / /workspace; do
    if [ -d "$d" ]; then
        echo '{"input":{"image_url":"https://placehold.co/512x512.png","audio_url":"https://example.com/silence.mp3","prompt_positive":"","prompt_negative":"","seed":42}}' > "$d/test_input.json"
        echo "   test_input.json -> $d"
    fi
done

echo ""
echo "Starting RunPod Handler..."
exec /start.sh.original
