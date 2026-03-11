# LTX-2.3 Audio Gen ComfyUI Worker for RunPod Serverless
# 全新 Endpoint，不影响当前线上 LTX-2 环境
# 构建: cd docker && docker build -f ltx23/Dockerfile -t your-registry/ltx23-worker:v1 .
FROM runpod/worker-comfyui:5.7.1-base-cuda12.8.1

WORKDIR /comfyui

# -----------------------------------------------------------------------------
# 1. 更新 ComfyUI 到最新
# -----------------------------------------------------------------------------
RUN git fetch origin master && \
    git reset --hard origin/master && \
    pip install -r requirements.txt || true

# -----------------------------------------------------------------------------
# 2. 安装 Custom Nodes（按 ltx23/DEPENDENCIES.md 清单）
# -----------------------------------------------------------------------------
# ComfyUI-LTXVideo
RUN cd /comfyui/custom_nodes && \
    rm -rf ComfyUI-LTXVideo || true && \
    git clone --depth 1 https://github.com/Lightricks/ComfyUI-LTXVideo.git && \
    cd ComfyUI-LTXVideo && pip install -r requirements.txt

# ComfyUI-KJNodes: DiffusionModelLoaderKJ, VAELoaderKJ, ImageResizeKJv2
RUN cd /comfyui/custom_nodes && \
    rm -rf ComfyUI-KJNodes || true && \
    git clone --depth 1 https://github.com/kijai/ComfyUI-KJNodes.git && \
    cd ComfyUI-KJNodes && pip install -r requirements.txt || true

# ComfyUI-VideoHelperSuite: VHS_LoadAudioUpload, CreateVideo, SaveVideo
RUN cd /comfyui/custom_nodes && \
    rm -rf ComfyUI-VideoHelperSuite || true && \
    git clone --depth 1 https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    cd ComfyUI-VideoHelperSuite && pip install -r requirements.txt

# ComfyUI-MelBandRoFormer: MelBandRoFormerModelLoader, MelBandRoFormerSampler
RUN cd /comfyui/custom_nodes && \
    rm -rf ComfyUI-MelBandRoFormer || true && \
    git clone --depth 1 https://github.com/chflame163/ComfyUI-MelBandRoFormer.git && \
    cd ComfyUI-MelBandRoFormer && pip install -r requirements.txt || true

# ComfyUI-Custom-Scripts: MathExpression|pysssss
RUN cd /comfyui/custom_nodes && \
    rm -rf ComfyUI-Custom-Scripts || true && \
    git clone --depth 1 https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git && \
    cd ComfyUI-Custom-Scripts && pip install -r requirements.txt || true

# ComfyUI-Crystools: Switch any [Crystools]
RUN cd /comfyui/custom_nodes && \
    rm -rf ComfyUI-Crystools || true && \
    git clone --depth 1 https://github.com/crystian/ComfyUI-Crystools.git && \
    cd ComfyUI-Crystools && pip install -r requirements.txt || true

# -----------------------------------------------------------------------------
# 3. 安装额外 pip 依赖
# -----------------------------------------------------------------------------
RUN pip install librosa soundfile torchaudio demucs requests google-cloud-storage

# -----------------------------------------------------------------------------
# 4. COPY workflow JSON（LTX-2.3 专用）
# -----------------------------------------------------------------------------
COPY workflow_ltx2-3_audio_gen.json /comfyui/workflows/ltx2-3_audio_gen.json

# -----------------------------------------------------------------------------
# 5. COPY handler 文件（复用 docker/pod_files）
# -----------------------------------------------------------------------------
RUN mkdir -p /workspace/handler

COPY pod_files/rp_handler.py /workspace/handler/rp_handler.py
COPY pod_files/url_downloader.py /workspace/handler/url_downloader.py
COPY pod_files/workflow_builder.py /workspace/handler/workflow_builder.py
COPY pod_files/gcs_uploader.py /workspace/handler/gcs_uploader.py

COPY pod_files/rp_handler.py /handler.py
COPY pod_files/url_downloader.py /url_downloader.py
COPY pod_files/workflow_builder.py /workflow_builder.py
COPY pod_files/gcs_uploader.py /gcs_uploader.py

COPY ltx23/gcs-credentials.json /workspace/gcs-credentials.json
COPY ltx23/gcs-credentials.json /gcs-credentials.json

# -----------------------------------------------------------------------------
# 6. COPY start_wrapper.sh（LTX-2.3 模型下载逻辑）
# -----------------------------------------------------------------------------
RUN mv /start.sh /start.sh.original
COPY ltx23/start_wrapper.sh /start.sh
RUN chmod +x /start.sh

RUN ls -la /workspace/handler/ /comfyui/workflows/ltx2-3_audio_gen.json /workspace/gcs-credentials.json
