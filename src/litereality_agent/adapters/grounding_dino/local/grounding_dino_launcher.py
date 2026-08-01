#!/usr/bin/env python3
"""grounding_dino_launcher.py — open-vocabulary detection via the GroundingDINO clone.

Drives the pristine ``backends/GroundingDINO`` clone (never editing it) to detect
objects from a text prompt. The Swin-T checkpoint **auto-downloads** into
``backends/weights/`` on first run; the matching config comes from the clone.

    python grounding_dino_launcher.py -i frame.jpg -p "a chair . a table . a lamp" -o boxes.json
    python grounding_dino_launcher.py -i frame.jpg -p "door" --annotate annotated.jpg

``object_init`` itself does not need this (it recovers openings by projecting the
RoomPlan 3D boxes), but the detector is provided here for the v2 / agent paths that
want a 2D detector. Needs torch + the built groundingdino C++ op in the active env.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # integrations/ root (shared _env)
import _env  # noqa: E402  (sys.path + HF cache wiring)

_env.configure_grounding_dino()

# Default open-vocab Swin-T config (lives in the clone) + its checkpoint on HF.
CONFIG_REL = "groundingdino/config/GroundingDINO_SwinT_OGC.py"
HF_REPO = "ShilongLiu/GroundingDINO"
HF_CKPT = "groundingdino_swint_ogc.pth"


def ensure_checkpoint(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    from huggingface_hub import hf_hub_download

    print(f"[GDINO] resolving {HF_REPO}/{HF_CKPT} (downloads to {_env.WEIGHTS_DIR} on first run)")
    return Path(hf_hub_download(repo_id=HF_REPO, filename=HF_CKPT))


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("-i", "--image", type=Path, required=True, help="Input image.")
    p.add_argument("-p", "--prompt", required=True, help="Text query, '.'-separated phrases.")
    p.add_argument("-o", "--output", type=Path, help="Write detections JSON here.")
    p.add_argument("--annotate", type=Path, help="Also write an annotated image here.")
    p.add_argument(
        "--config", default=None, help="Override config path (default: clone Swin-T OGC)."
    )
    p.add_argument(
        "--checkpoint", default=None, help="Override checkpoint path (default: auto-download)."
    )
    p.add_argument("--box-threshold", type=float, default=0.35)
    p.add_argument("--text-threshold", type=float, default=0.25)
    args = p.parse_args()

    from groundingdino.util.inference import annotate, load_image, load_model, predict

    config_path = args.config or str(_env.GROUNDING_DINO_DIR / CONFIG_REL)
    checkpoint = ensure_checkpoint(args.checkpoint)
    model = load_model(config_path, str(checkpoint))

    image_source, image = load_image(str(args.image))
    boxes, logits, phrases = predict(
        model=model,
        image=image,
        caption=args.prompt,
        box_threshold=args.box_threshold,
        text_threshold=args.text_threshold,
    )

    detections = [
        {"phrase": ph, "score": float(sc), "box_cxcywh_norm": [float(v) for v in bx]}
        for bx, sc, ph in zip(boxes, logits, phrases)
    ]
    print(f"[GDINO] {len(detections)} detection(s): {[d['phrase'] for d in detections]}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {"image": str(args.image), "prompt": args.prompt, "detections": detections},
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"[GDINO] wrote {args.output}")
    if args.annotate:
        import cv2

        frame = annotate(image_source=image_source, boxes=boxes, logits=logits, phrases=phrases)
        args.annotate.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.annotate), frame)
        print(f"[GDINO] wrote {args.annotate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
