#!/bin/bash
# ============================================================================
# Serverless Boot Script
#
# Runs as container entrypoint BEFORE the image's /start.sh.
# Bridges the gap between Volume mount (/runpod-volume/) and
# the image's hardcoded paths (/workspace/).
#
# This file lives on the Volume and is called via template entrypoint:
#   /sbin/docker-init -- bash /runpod-volume/boot.sh
# ============================================================================

echo "=== Serverless Boot ==="

# Wait for Volume to be fully accessible
echo "Waiting for Volume..."
for i in $(seq 1 30); do
    if [ -d /runpod-volume/runpod-slim/ComfyUI ]; then
        echo "Volume ready."
        break
    fi
    sleep 1
done

# Symlink Volume content to /workspace/ where /start.sh expects it
rm -rf /workspace/runpod-slim
ln -sfn /runpod-volume/runpod-slim /workspace/runpod-slim
ln -sfn /runpod-volume/handler /workspace/handler
ln -sfn /runpod-volume/workflows /workspace/workflows
ln -sf /runpod-volume/gcs-credentials.json /workspace/gcs-credentials.json

# Verify
echo "ComfyUI: $(test -d /workspace/runpod-slim/ComfyUI && echo OK || echo FAIL)"
echo "Venv: $(test -d /workspace/runpod-slim/ComfyUI/.venv-cu128 && echo OK || echo FAIL)"
echo "Handler: $(test -d /workspace/handler && echo OK || echo FAIL)"

# Hand off to the image's original start script
exec /start.sh
