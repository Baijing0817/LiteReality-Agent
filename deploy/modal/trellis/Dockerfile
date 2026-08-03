FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda \
    PATH=/usr/local/cuda/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ffmpeg git git-lfs libgl1 libglib2.0-0 python3.10 python3-pip \
    python-is-python3 && \
    rm -rf /var/lib/apt/lists/*

RUN python3.10 -m pip install --no-cache-dir --upgrade pip && \
    python3.10 -m pip install --no-cache-dir \
      torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124

RUN git clone --branch main --recursive https://github.com/microsoft/TRELLIS.2.git /root/TRELLIS.2

# Use Microsoft's installation script for its compiled CUDA extensions. The Modal image builder
# receives an H100 because upstream's setup checks for a GPU and compiles device-specific pieces.
RUN cd /root/TRELLIS.2 && bash -lc \
    '. ./setup.sh --basic --cumesh --o-voxel --flexgemm --nvdiffrast --nvdiffrec' && \
    python3.10 -m pip install --no-cache-dir xformers huggingface-hub hf-xet

WORKDIR /root
