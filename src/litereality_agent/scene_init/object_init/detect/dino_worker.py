"""GroundingDINO worker — runs in the ISOLATED detect env (torch + transformers).

A persistent JSON-lines server over stdin/stdout: the model loads once and serves many
detect requests warm (bbox_polish calls DINO on many crops per scan). Spawned by
`models/dino.py:DinoSubprocessService`. Run as:

    $LR_DINO_PYTHON -u -m litereality_agent.scene_init.object_init.detect.dino_worker

Protocol — one JSON object per line in, one per line out:
    {"op":"ping"}                              -> {"ok":true,"model":...,"cuda":bool}
    {"op":"detect","image_path":..,"prompt":..,"box_threshold":..,"text_threshold":..,
     "upright":true,"model_id":null,"id":N}    -> {"ok":true,"detections":[{box,score,label}],"id":N}
    {"op":"embed","image_paths":[..],"upright":true,"model_id":null,"id":N}
                                               -> {"ok":true,"embeddings":[[..],..],"id":N}
On error: {"ok":false,"error":"..."}.
"""

from __future__ import annotations

import json
import sys


def _handle(req: dict) -> dict:
    op = req.get("op", "detect")
    if op == "ping":
        from . import dino_detect

        try:
            import torch

            cuda = bool(torch.cuda.is_available())
        except Exception:
            cuda = False
        return {"ok": True, "model": dino_detect.default_model_id(), "cuda": cuda}
    if op == "detect":
        from PIL import Image

        from . import dino_detect

        img = Image.open(req["image_path"]).convert("RGB")
        dets = dino_detect.detect(
            img,
            req["prompt"],
            box_threshold=req.get("box_threshold", 0.30),
            text_threshold=req.get("text_threshold", 0.20),
            model_id=req.get("model_id"),
            upright=req.get("upright", True),
        )
        return {
            "ok": True,
            "detections": [
                {"box": list(d.box), "score": float(d.score), "label": d.label} for d in dets
            ],
        }
    if op == "embed":
        from . import dino_embed

        embs = dino_embed.embed_paths(
            list(req["image_paths"]),
            model_id=req.get("model_id"),
            upright=req.get("upright", True),
        )
        return {"ok": True, "embeddings": embs}
    return {"ok": False, "error": f"unknown op {op!r}"}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req: dict | None = None
        try:
            req = json.loads(line)
            resp = _handle(req)
        except Exception as e:  # noqa: BLE001 — report, keep serving
            resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        if isinstance(req, dict) and "id" in req:
            resp["id"] = req["id"]
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
