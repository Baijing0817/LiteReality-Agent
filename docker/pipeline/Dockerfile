# syntax=docker/dockerfile:1.7

ARG UV_VERSION=0.9.17
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# The orchestration image intentionally excludes TRELLIS. TRELLIS stays behind the existing
# RunPod Serverless endpoint; this image runs ingestion, DINO, Blender, and the authoring agents.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ARG BLENDER_VERSION=4.3.2
ARG BLENDER_SERIES=4.3
ARG NODE_VERSION=22.14.0

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        git \
        git-lfs \
        libdbus-1-3 \
        libegl1 \
        libgl1 \
        libglib2.0-0 \
        libice6 \
        libsm6 \
        libx11-6 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxkbcommon0 \
        libxrender1 \
        libxxf86vm1 \
        python3 \
        python3-dev \
        python3-pip \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Pin Blender rather than relying on Ubuntu's older package. The archive is unpacked directly,
# so Blender is present in the container and never needs to be installed on the caller's machine.
RUN curl --fail --location --retry 5 \
        "https://download.blender.org/release/Blender${BLENDER_SERIES}/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        --output /tmp/blender.tar.xz \
    && mkdir -p /opt/blender \
    && tar --extract --xz --file /tmp/blender.tar.xz --strip-components=1 --directory /opt/blender \
    && rm /tmp/blender.tar.xz \
    && /opt/blender/blender --version

# Claude Code is needed both for subscription login and by claude-agent-sdk. Node is installed
# from a pinned upstream archive because Ubuntu 22.04's nodejs package is too old.
RUN curl --fail --location --retry 5 \
        "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
        --output /tmp/node.tar.xz \
    && tar --extract --xz --file /tmp/node.tar.xz --strip-components=1 --directory /usr/local \
    && rm /tmp/node.tar.xz \
    && npm install --global @anthropic-ai/claude-code \
    && claude --version

COPY --from=uv /uv /uvx /usr/local/bin/

WORKDIR /opt/litereality

# Keep the expensive dependency layer reusable when only application code changes. The detect
# extra installs torch/torchvision/transformers for GroundingDINO and DINOv2 on the Pod GPU.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --extra detect --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --extra detect \
    && .venv/bin/python -c "import torch, torchvision, transformers; print(torch.__version__)" \
    && .venv/bin/litereality --help >/dev/null

COPY docker/pipeline/entrypoint.sh /usr/local/bin/litereality-entrypoint
RUN chmod 0755 /usr/local/bin/litereality-entrypoint

# /workspace is the persistent RunPod mount. Keep scans, results, model caches, and remote Claude
# credentials there; none of them are embedded in or pushed with the image.
ENV PATH="/opt/litereality/.venv/bin:/opt/blender:${PATH}" \
    LR_REPO_ROOT=/opt/litereality \
    LR_SCANS_DIR=/workspace/scans \
    LITEREALITY_OUTPUT=/workspace/run \
    LITEREALITY_BLENDER=/opt/blender/blender \
    LR_DINO_PYTHON=/opt/litereality/.venv/bin/python \
    LITEREALITY_PROCEDURAL_PYTHON=/opt/litereality/.venv/bin/python \
    HF_HOME=/workspace/.cache/huggingface \
    TORCH_HOME=/workspace/.cache/torch \
    ANTHROPIC_CONFIG_DIR=/workspace/.config/anthropic \
    CLAUDE_CONFIG_DIR=/workspace/.claude \
    DISABLE_AUTOUPDATER=1

WORKDIR /workspace
ENTRYPOINT ["litereality-entrypoint"]
CMD ["sleep", "infinity"]
