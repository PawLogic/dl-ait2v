# LTX-2 Audio-to-Video ComfyUI Worker for RunPod Serverless
# v40: Added POD_MODE support for Pod-based testing
FROM runpod/worker-comfyui:5.7.1-base-cuda12.8.1

WORKDIR /comfyui

# Full update to latest ComfyUI master for LTX-2 audio-video support
RUN git fetch origin master && \
    git reset --hard origin/master && \
    pip install -r requirements.txt || true && \
    echo "ComfyUI updated to latest master with LTX-2 audio-video support"

# Verify LTX-2 audio nodes exist
RUN echo "=== Verifying LTX-2 audio files ===" && \
    ls -la /comfyui/comfy_extras/nodes_lt*.py && \
    grep -l "LTXAVTextEncoderLoader\|LTXV" /comfyui/comfy_extras/*.py || echo "Checking nodes..."

# Install LTX-2 custom nodes
RUN cd /comfyui/custom_nodes && \
    rm -rf ComfyUI-LTXVideo || true && \
    git clone --depth 1 https://github.com/Lightricks/ComfyUI-LTXVideo.git && \
    cd ComfyUI-LTXVideo && \
    pip install -r requirements.txt

# Install Video Helper Suite for video output
RUN cd /comfyui/custom_nodes && \
    git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    cd ComfyUI-VideoHelperSuite && \
    pip install -r requirements.txt

# Install KJ Nodes (for ImageResizeKJv2, PatchSageAttentionKJ, etc.)
RUN cd /comfyui/custom_nodes && \
    (rm -rf ComfyUI-KJNodes || true) && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git && \
    cd ComfyUI-KJNodes && \
    pip install -r requirements.txt || true

# Install MelBandRoFormer (for vocal separation)
RUN cd /comfyui/custom_nodes && \
    (rm -rf ComfyUI-MelBandRoFormer || true) && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-MelBandRoFormer.git && \
    cd ComfyUI-MelBandRoFormer && \
    pip install -r requirements.txt || true

# Install ComfyUI-Manager (useful for node management)
RUN cd /comfyui/custom_nodes && \
    (rm -rf ComfyUI-Manager || true) && \
    git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Manager.git || true

# Install audio processing dependencies + GCS client (v28: added google-cloud-storage)
RUN pip install librosa soundfile torchaudio demucs requests google-cloud-storage

# Install SageAttention for KJNodes memory optimization (PatchSageAttentionKJ)
RUN pip install sageattention || echo "SageAttention installation skipped"

# Create handler directory
RUN mkdir -p /workspace/handler

# Copy enhanced workflow template (CRITICAL: includes Node 287 + audio routing)
# img_compression fixed to 30 for production quality (test_720p.py standard)
COPY workflow_ltx2_enhanced.json /comfyui/workflows/ltx2_enhanced.json

# Copy audio generation workflow template (Mode 2: image + duration -> video + generated audio)
COPY workflow_ltx2_audio_gen.json /comfyui/workflows/ltx2_audio_gen.json

# Copy multiframe workflow template (Mode 3: multi-keyframe + audio)
COPY workflow_ltx2_multiframe.json /comfyui/workflows/ltx2_multiframe.json

# Copy handler files (v28: added gcs_uploader.py for GCS upload)
COPY pod_files/rp_handler.py /workspace/handler/rp_handler.py
COPY pod_files/url_downloader.py /workspace/handler/url_downloader.py
COPY pod_files/workflow_builder.py /workspace/handler/workflow_builder.py
COPY pod_files/gcs_uploader.py /workspace/handler/gcs_uploader.py

# v27: Replace default handler with our custom handler that builds workflow from template
COPY pod_files/rp_handler.py /handler.py
COPY pod_files/url_downloader.py /url_downloader.py
COPY pod_files/workflow_builder.py /workflow_builder.py
COPY pod_files/gcs_uploader.py /gcs_uploader.py

# v28: Copy GCS service account credentials
COPY pod_files/gcs-credentials.json /workspace/gcs-credentials.json
COPY pod_files/gcs-credentials.json /gcs-credentials.json

# v26: Replace /start.sh with our wrapper that sets up Network Volume symlinks
RUN mv /start.sh /start.sh.original
COPY pod_files/start_wrapper.sh /start.sh
RUN chmod +x /start.sh

# Verify handler files
RUN echo "=== Verifying handler files ===" && \
    ls -la /workspace/handler/ && \
    ls -la /comfyui/workflows/ && \
    echo "=== Workflow templates ===" && \
    ls -la /comfyui/workflows/ltx2_*.json && \
    ls -la /workspace/gcs-credentials.json

# Default command uses the base image's entrypoint which calls /start.sh
# Our /start.sh wrapper sets up Network Volume symlinks then calls original
