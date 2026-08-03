"""GroundingDINO and DINOv2 through one RunPod Serverless endpoint."""

from __future__ import annotations

import base64
import io
import os
import time
from pathlib import Path
from typing import Any

from litereality_agent.models.grounding_dino.service import Detection
from litereality_agent.runtimes.runpod import RunPodClient


class RunPodDinoService:
    """DetectionService + EmbeddingService implemented as queued API jobs."""

    name = "dino-runpod"
    _BAD = {"FAILED", "CANCELLED", "TIMED_OUT"}

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint_id: str | None = None,
        model_id: str | None = None,
        embed_model_id: str | None = None,
        poll_interval: float = 1.0,
        job_timeout: float = 300.0,
        client: Any = None,
    ) -> None:
        self.model_id = model_id
        self.embed_model_id = embed_model_id
        self.poll_interval = poll_interval
        self.job_timeout = job_timeout
        if client is not None:
            self.client = client
            return
        key = api_key or os.environ.get("RUNPOD_API_KEY", "").strip()
        endpoint = endpoint_id or os.environ.get("RUNPOD_DINO_ENDPOINT", "").strip()
        if not key or not endpoint:
            raise ValueError("RunPod DINO needs RUNPOD_API_KEY and RUNPOD_DINO_ENDPOINT")
        self.client = RunPodClient(key, endpoint)

    def _run(self, payload: dict) -> dict:
        job_id = self.client.run(payload)
        deadline = time.monotonic() + self.job_timeout
        while time.monotonic() < deadline:
            status = self.client.status(job_id)
            state = status.get("status")
            if state == "COMPLETED":
                output = status.get("output") or {}
                if output.get("error"):
                    raise RuntimeError(output["error"])
                return output
            if state in self._BAD:
                raise RuntimeError(status.get("error") or f"RunPod DINO job {state}")
            time.sleep(self.poll_interval)
        try:
            self.client.cancel(job_id)
        finally:
            raise TimeoutError(f"RunPod DINO job exceeded {self.job_timeout:.0f}s")

    def detect(
        self,
        image: Any,
        prompt: str,
        *,
        box_threshold: float = 0.30,
        text_threshold: float = 0.20,
        upright: bool = True,
    ) -> list[Detection]:
        output = self._run(
            {
                "op": "detect",
                "image_b64": _image_b64(image),
                "prompt": prompt,
                "box_threshold": box_threshold,
                "text_threshold": text_threshold,
                "upright": upright,
                "model_id": self.model_id,
            }
        )
        return [
            Detection(
                label=str(item["label"]),
                box_xyxy=tuple(float(value) for value in item["box"]),
                score=float(item["score"]),
            )
            for item in output.get("detections", [])
        ]

    def embed(self, images: list[Any], *, upright: bool = True) -> list[list[float]]:
        output = self._run(
            {
                "op": "embed",
                "images_b64": [_image_b64(image) for image in images],
                "upright": upright,
                "model_id": self.embed_model_id,
            }
        )
        return [[float(value) for value in row] for row in output.get("embeddings", [])]

    def close(self) -> None:
        """Match the local worker lifecycle API; queued HTTP jobs hold no client process."""


def _image_b64(image: Any) -> str:
    if isinstance(image, (str, os.PathLike)):
        raw = Path(image).read_bytes()
    elif isinstance(image, bytes):
        raw = image
    else:
        from PIL import Image

        pil = image if hasattr(image, "save") else Image.fromarray(image)
        buffer = io.BytesIO()
        pil.convert("RGB").save(buffer, format="PNG")
        raw = buffer.getvalue()
    return base64.b64encode(raw).decode()
