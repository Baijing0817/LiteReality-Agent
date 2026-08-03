"""GroundingDINO and DINOv2 through one RunPod Serverless endpoint."""

from __future__ import annotations

import base64
import io
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Detection:
    label: str
    box_xyxy: tuple[float, float, float, float]
    score: float


class _RunPodClient:
    def __init__(
        self,
        api_key: str,
        endpoint_id: str,
        *,
        base_url: str = "https://api.runpod.ai/v2",
        http_timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key
        self.base = f"{base_url.rstrip('/')}/{endpoint_id}"
        self.http_timeout = http_timeout

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        request = urllib.request.Request(
            f"{self.base}/{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=self.http_timeout) as response:
            return json.loads(response.read().decode())

    def run(self, job_input: dict) -> str:
        response = self._request("POST", "run", {"input": job_input})
        job_id = response.get("id")
        if not job_id:
            raise RuntimeError(f"RunPod DINO /run returned no id: {response}")
        return str(job_id)

    def status(self, job_id: str) -> dict:
        return self._request("GET", f"status/{job_id}")

    def cancel(self, job_id: str) -> dict:
        return self._request("POST", f"cancel/{job_id}")


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
        self.client = _RunPodClient(key, endpoint)

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

