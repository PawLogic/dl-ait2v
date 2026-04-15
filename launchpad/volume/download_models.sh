#!/bin/bash
# ============================================================================
# 模型下载脚本：在 Pod 上运行，将模型下载到 Volume
#
# 用法:
#   ./download_models.sh            # 下载所有模型
#   ./download_models.sh --check    # 只检查模型完整性，不下载
# ============================================================================

set -euo pipefail

MODEL_PATH="/workspace/runpod-slim/ComfyUI/models"
CHECK_ONLY=false

[ "${1:-}" = "--check" ] && CHECK_ONLY=true

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

# model_file  url  min_size_bytes
MODELS=(
    "diffusion_models/ltx-2-19b-dev-fp8.safetensors|https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-19b-dev-fp8.safetensors|18000000000"
    "text_encoders/gemma_3_12B_it_fp8_scaled.safetensors|https://huggingface.co/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it_fp8_scaled.safetensors|12000000000"
    "loras/ltx-2-19b-distilled-lora-384.safetensors|https://huggingface.co/Lightricks/LTX-2/resolve/main/ltx-2-19b-distilled-lora-384.safetensors|7000000000"
    "loras/ltx-2-19b-ic-lora-detailer.safetensors|https://huggingface.co/Lightricks/LTX-2-19b-IC-LoRA-Detailer/resolve/main/ltx-2-19b-ic-lora-detailer.safetensors|2000000000"
    "loras/ltx-2-19b-lora-camera-control-dolly-in.safetensors|https://huggingface.co/Lightricks/LTX-2-19b-LoRA-Camera-Control-Dolly-In/resolve/main/ltx-2-19b-lora-camera-control-dolly-in.safetensors|200000000"
    "loras/LTX-2-Image2Vid-Adapter.safetensors|https://huggingface.co/MachineDelusions/LTX-2_Image2Video_Adapter_LoRa/resolve/main/LTX-2-Image2Vid-Adapter.safetensors|4000000000"
)

echo "=== Model Check ==="
MISSING=0

for entry in "${MODELS[@]}"; do
    IFS='|' read -r file url min_size <<< "$entry"
    filepath="$MODEL_PATH/$file"

    if [ -f "$filepath" ]; then
        size=$(stat -c%s "$filepath" 2>/dev/null || stat -f%z "$filepath" 2>/dev/null || echo 0)
        if [ "$size" -ge "$min_size" ]; then
            echo -e "${GREEN}OK${NC}  $(basename $file) ($(numfmt --to=iec $size 2>/dev/null || echo ${size}B))"
            continue
        fi
        echo -e "${RED}TOO SMALL${NC}  $(basename $file), re-downloading..."
        rm -f "$filepath"
    else
        echo -e "${RED}MISSING${NC}  $(basename $file)"
    fi

    MISSING=$((MISSING + 1))

    if [ "$CHECK_ONLY" = true ]; then
        continue
    fi

    echo "  Downloading $(basename $file)..."
    mkdir -p "$(dirname $filepath)"
    wget -q --show-progress -O "$filepath" "$url" || {
        echo "  Download failed: $(basename $file)"
    }
done

if [ "$MISSING" -eq 0 ]; then
    echo -e "${GREEN}All models present.${NC}"
else
    echo -e "${RED}${MISSING} model(s) need attention.${NC}"
fi
