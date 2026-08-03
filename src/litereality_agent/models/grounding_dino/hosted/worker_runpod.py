"""RunPod handler for GroundingDINO detection and DINOv2 embeddings."""

from __future__ import annotations

import base64
import io
import tempfile
import traceback
from pathlib import Path

import runpod
from PIL import Image


def _image(encoded: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")


def handler(job: dict) -> dict:
    try:
        request = job.get("input") or {}
        operation = request.get("op", "detect")
        if operation == "detect":
            from litereality_agent.models.grounding_dino.local import detect

            detections = detect.detect(
                _image(request["image_b64"]),
                request["prompt"],
                box_threshold=float(request.get("box_threshold", 0.30)),
                text_threshold=float(request.get("text_threshold", 0.20)),
                model_id=request.get("model_id"),
                upright=bool(request.get("upright", True)),
            )
            return {
                "detections": [
                    {"box": item.box, "score": item.score, "label": item.label}
                    for item in detections
                ]
            }
        if operation == "embed":
            from litereality_agent.models.dinov2.local import embed

            with tempfile.TemporaryDirectory() as directory:
                paths: list[str] = []
                for index, encoded in enumerate(request.get("images_b64") or []):
                    path = Path(directory) / f"{index}.png"
                    _image(encoded).save(path)
                    paths.append(str(path))
                embeddings = embed.embed_paths(
                    paths,
                    model_id=request.get("model_id"),
                    upright=bool(request.get("upright", True)),
                )
            return {"embeddings": embeddings}
        return {"error": f"unknown op {operation!r}"}
    except Exception as exc:  # keep the worker alive and return a useful remote traceback
        return {
            "error": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc()[-2000:],
        }


runpod.serverless.start({"handler": handler})

