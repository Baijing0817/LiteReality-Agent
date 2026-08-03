FROM pytorch/pytorch:2.5.1-cuda12.4-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HF_HOME=/models/huggingface \
    HF_HUB_DISABLE_XET=1

WORKDIR /app

COPY src/litereality_agent/models/grounding_dino/hosted/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --no-deps torchvision==0.20.1 \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY src /app/src

# Bake public weights into the image so scale-to-zero workers do not download them per cold start.
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('IDEA-Research/grounding-dino-tiny'); snapshot_download('facebook/dinov2-small')"

CMD ["python", "-u", "-m", "litereality_agent.models.grounding_dino.hosted.worker_runpod"]

