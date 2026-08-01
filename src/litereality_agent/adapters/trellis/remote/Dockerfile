# TRELLIS RunPod serverless worker — LEAN build.
# Same proven camenduru wheel set + weights, but we start FROM a CUDA image (CUDA 12.4 + nvcc +
# cudnn already present) instead of installing the 4 GB CUDA toolkit from scratch. Smaller image,
# much faster build, far less likely to hit RunPod's build disk/time limits.
FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

WORKDIR /content
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=True
ENV PATH="/home/camenduru/.local/bin:/usr/local/cuda/bin:${PATH}"

RUN apt update -y && apt install -y software-properties-common build-essential \
    libgl1 libglib2.0-0 && \
    add-apt-repository -y ppa:git-core/ppa && apt update -y && \
    apt install -y python-is-python3 python3-pip sudo aria2 curl wget git git-lfs ffmpeg && \
    adduser --disabled-password --gecos '' camenduru && \
    adduser camenduru sudo && \
    echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers && \
    chown -R camenduru:camenduru /content && chmod -R 777 /content && \
    chown -R camenduru:camenduru /home && chmod -R 777 /home && \
    rm -rf /var/lib/apt/lists/*

USER camenduru

# python deps — camenduru's exact proven wheels (no compilation; nvcc from the base if needed)
RUN pip install --no-cache-dir torch==2.5.1+cu124 torchvision==0.20.1+cu124 torchaudio==2.5.1+cu124 torchtext==0.18.0 torchdata==0.8.0 --extra-index-url https://download.pytorch.org/whl/cu124 && \
    pip install --no-cache-dir xformers==0.0.28.post3 && \
    pip install --no-cache-dir https://github.com/Dao-AILab/flash-attention/releases/download/v2.6.3/flash_attn-2.6.3+cu123torch2.3cxx11abiFALSE-cp310-cp310-linux_x86_64.whl && \
    pip install --no-cache-dir opencv-contrib-python imageio imageio-ffmpeg ffmpeg-python av runpod && \
    pip install --no-cache-dir easydict rembg onnxruntime onnxruntime-gpu numpy==2.0.0 plyfile huggingface-hub safetensors && \
    pip install --no-cache-dir trimesh xatlas pyvista pymeshfix igraph spconv-cu120 && \
    pip install --no-cache-dir https://github.com/camenduru/wheels/releases/download/3090/kaolin-0.17.0-cp310-cp310-linux_x86_64.whl && \
    pip install --no-cache-dir https://github.com/camenduru/wheels/releases/download/3090/diso-0.1.4-cp310-cp310-linux_x86_64.whl && \
    pip install --no-cache-dir https://github.com/camenduru/wheels/releases/download/3090/utils3d-0.0.2-py3-none-any.whl && \
    pip install --no-cache-dir https://huggingface.co/spaces/JeffreyXiang/TRELLIS/resolve/main/wheels/nvdiffrast-0.3.3-cp310-cp310-linux_x86_64.whl && \
    pip install --no-cache-dir https://huggingface.co/spaces/JeffreyXiang/TRELLIS/resolve/main/wheels/diff_gaussian_rasterization-0.0.0-cp310-cp310-linux_x86_64.whl

# TRELLIS code (own layer)
RUN git clone --recursive https://github.com/Microsoft/TRELLIS /content/TRELLIS

# model weights — baked in (own layer so a failure here doesn't redo pip)
RUN aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/raw/main/pipeline.json -d /content/model -o pipeline.json && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/resolve/main/ckpts/slat_dec_gs_swin8_B_64l8gs32_fp16.safetensors -d /content/model/ckpts -o slat_dec_gs_swin8_B_64l8gs32_fp16.safetensors && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/raw/main/ckpts/slat_dec_gs_swin8_B_64l8gs32_fp16.json -d /content/model/ckpts -o slat_dec_gs_swin8_B_64l8gs32_fp16.json && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/resolve/main/ckpts/slat_dec_mesh_swin8_B_64l8m256c_fp16.safetensors -d /content/model/ckpts -o slat_dec_mesh_swin8_B_64l8m256c_fp16.safetensors && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/raw/main/ckpts/slat_dec_mesh_swin8_B_64l8m256c_fp16.json -d /content/model/ckpts -o slat_dec_mesh_swin8_B_64l8m256c_fp16.json && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/resolve/main/ckpts/slat_enc_swin8_B_64l8_fp16.safetensors -d /content/model/ckpts -o slat_enc_swin8_B_64l8_fp16.safetensors && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/raw/main/ckpts/slat_enc_swin8_B_64l8_fp16.json -d /content/model/ckpts -o slat_enc_swin8_B_64l8_fp16.json && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/resolve/main/ckpts/slat_flow_img_dit_L_64l8p2_fp16.safetensors -d /content/model/ckpts -o slat_flow_img_dit_L_64l8p2_fp16.safetensors && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/raw/main/ckpts/slat_flow_img_dit_L_64l8p2_fp16.json -d /content/model/ckpts -o slat_flow_img_dit_L_64l8p2_fp16.json && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/resolve/main/ckpts/ss_dec_conv3d_16l8_fp16.safetensors -d /content/model/ckpts -o ss_dec_conv3d_16l8_fp16.safetensors && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/raw/main/ckpts/ss_dec_conv3d_16l8_fp16.json -d /content/model/ckpts -o ss_dec_conv3d_16l8_fp16.json && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/resolve/main/ckpts/ss_enc_conv3d_16l8_fp16.safetensors -d /content/model/ckpts -o ss_enc_conv3d_16l8_fp16.safetensors && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/raw/main/ckpts/ss_enc_conv3d_16l8_fp16.json -d /content/model/ckpts -o ss_enc_conv3d_16l8_fp16.json && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/resolve/main/ckpts/ss_flow_img_dit_L_16l8_fp16.safetensors -d /content/model/ckpts -o ss_flow_img_dit_L_16l8_fp16.safetensors && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/raw/main/ckpts/ss_flow_img_dit_L_16l8_fp16.json -d /content/model/ckpts -o ss_flow_img_dit_L_16l8_fp16.json && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://github.com/facebookresearch/dinov2/zipball/main -d /home/camenduru/.cache/torch/hub -o main.zip && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://dl.fbaipublicfiles.com/dinov2/dinov2_vitl14/dinov2_vitl14_reg4_pretrain.pth -d /home/camenduru/.cache/torch/hub/checkpoints -o dinov2_vitl14_reg4_pretrain.pth && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx -d /home/camenduru/.u2net -o u2net.onnx

# the lean-rewrite weights list dropped this radiance-field decoder ckpt that pipeline.json
# references; TRELLIS loads ALL models at startup, so it must be present.
RUN aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/resolve/main/ckpts/slat_dec_rf_swin8_B_64l8r16_fp16.safetensors -d /content/model/ckpts -o slat_dec_rf_swin8_B_64l8r16_fp16.safetensors && \
    aria2c --console-log-level=error -c -x 16 -s 16 -k 1M https://huggingface.co/JeffreyXiang/TRELLIS-image-large/raw/main/ckpts/slat_dec_rf_swin8_B_64l8r16_fp16.json -d /content/model/ckpts -o slat_dec_rf_swin8_B_64l8r16_fp16.json

# We only use IMAGE-to-3D, but upstream pipelines/__init__ eagerly imports the TEXT pipeline
# (drags in open3d + a numpy ABI clash with kaolin). Drop that import; keep transformers (cheap).
# kaolin's prebuilt wheel was compiled against numpy 1.x → force numpy<2 (overrides the base pin).
RUN pip install --no-cache-dir transformers "numpy==1.26.4" && \
    sed -i '/trellis_text_to_3d/d; /TrellisTextTo3DPipeline/d' /content/TRELLIS/trellis/pipelines/__init__.py

COPY ./worker_runpod.py /content/TRELLIS/worker_runpod.py
WORKDIR /content/TRELLIS
CMD python worker_runpod.py
