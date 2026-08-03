FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HF_HOME=/models/huggingface \
    HF_HUB_DISABLE_XET=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY deploy/runpod/grounding_dino/requirements.txt /tmp/requirements.txt
# Preserve the CUDA-enabled torch supplied by the base image.
RUN python -m pip install --no-cache-dir --no-deps torchvision==0.20.1 && \
    python -m pip install --no-cache-dir -r /tmp/requirements.txt

COPY src /app/src

CMD ["python", "-u", "-m", "litereality_agent.models.grounding_dino.worker", "--runpod"]
