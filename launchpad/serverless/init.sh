#!/bin/bash
echo "=== ComfyUI Serverless Worker ==="

# ── Venv bootstrap (runs once per volume, skips if already complete) ──
VENV="/workspace/venv-cu130"
MARKER="$VENV/.setup_done"

if [ ! -f "$MARKER" ]; then
    echo "First boot: setting up venv..."
    if [ ! -d "$VENV" ]; then
        python3 -m venv "$VENV" --system-site-packages
    fi
    source "$VENV/bin/activate"
    pip install --quiet runpod google-cloud-storage requests librosa soundfile
    # Custom nodes deps
    for req in /workspace/runpod-slim/ComfyUI/custom_nodes/*/requirements.txt; do
        [ -f "$req" ] && pip install --quiet -r "$req" 2>/dev/null || true
    done
    pip install --quiet sageattention --no-build-isolation 2>/dev/null || true
    pip install --quiet rotary_embedding_torch imageio-ffmpeg deepdiff piexif 2>/dev/null || true
    touch "$MARKER"
    echo "Venv setup complete ($(pip list 2>/dev/null | wc -l) packages)."
else
    echo "Venv already set up."
fi

# Activate venv
export PATH="$VENV/bin:$PATH"
export VIRTUAL_ENV="$VENV"

# Start ComfyUI in background
echo "Starting ComfyUI..."
cd /workspace/runpod-slim/ComfyUI
python main.py --listen 0.0.0.0 --port 8188 --enable-cors-header &
COMFYUI_PID=$!
echo "ComfyUI PID: $COMFYUI_PID"

# Wait for ComfyUI to accept connections
echo "Waiting for ComfyUI HTTP API..."
for i in $(seq 1 90); do
    if curl -s http://127.0.0.1:8188/system_stats > /dev/null 2>&1; then
        echo "ComfyUI ready."
        break
    fi
    sleep 2
done

# Start RunPod handler (foreground)
echo "Starting RunPod handler..."
exec python /workspace/handler/rp_handler.py
