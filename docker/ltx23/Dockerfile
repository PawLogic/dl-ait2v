# LTX-2.3 Audio Gen ComfyUI Worker for RunPod Serverless
# 全新 Endpoint，不影响当前线上 LTX-2 环境
# 构建: cd docker && docker build -f ltx23/Dockerfile -t your-registry/ltx23-worker:v1 .
FROM runpod/worker-comfyui:5.7.1-base-cuda12.8.1

WORKDIR /comfyui

# -----------------------------------------------------------------------------
# 0. Triton JIT 需要 C 编译器（FP8 dequantize 等运行时编译）
# -----------------------------------------------------------------------------
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

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
    git clone --depth 1 https://github.com/kijai/ComfyUI-MelBandRoFormer.git && \
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
# 3. 升级 PyTorch 到 cu130，启用 comfy_kitchen CUDA 后端
#    否则 cu128 下 cuda/triton 均 disabled，只用 eager → 30min vs 2min
# -----------------------------------------------------------------------------
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu130

# -----------------------------------------------------------------------------
# 4. 安装额外 pip 依赖
# -----------------------------------------------------------------------------
# sageattention: DiffusionModelLoaderKJ 的 sage_attention 需要
RUN pip install librosa soundfile demucs requests google-cloud-storage sageattention

# -----------------------------------------------------------------------------
# 5. COPY workflow JSON（LTX-2.3 专用）
# -----------------------------------------------------------------------------
COPY workflow_ltx2-3_audio_gen.json /comfyui/workflows/ltx2-3_audio_gen.json

# -----------------------------------------------------------------------------
# 6. COPY handler 文件（ltx23 完全自包含，不依赖 pod_files）
# -----------------------------------------------------------------------------
RUN mkdir -p /workspace/handler

COPY ltx23/rp_handler.py /workspace/handler/rp_handler.py
COPY ltx23/rp_handler.py /handler.py
COPY ltx23/url_downloader.py /workspace/handler/url_downloader.py
COPY ltx23/url_downloader.py /url_downloader.py
COPY ltx23/gcs_uploader.py /workspace/handler/gcs_uploader.py
COPY ltx23/gcs_uploader.py /gcs_uploader.py

COPY ltx23/gcs-credentials.json /workspace/gcs-credentials.json
COPY ltx23/gcs-credentials.json /gcs-credentials.json

# test_input.json: RunPod Handler 在 Pod 模式下需要，否则 "test_input.json not found, exiting"
COPY ltx23/test_input.json /test_input.json
COPY ltx23/test_input.json /workspace/test_input.json

# -----------------------------------------------------------------------------
# 7. COPY start_wrapper.sh（LTX-2.3 模型下载逻辑）
# -----------------------------------------------------------------------------
RUN mv /start.sh /start.sh.original
COPY ltx23/start_wrapper.sh /start.sh
RUN chmod +x /start.sh

RUN ls -la /workspace/handler/ /comfyui/workflows/ltx2-3_audio_gen.json /workspace/gcs-credentials.json
