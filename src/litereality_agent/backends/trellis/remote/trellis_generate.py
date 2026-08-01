"""TRELLIS pipeline wrapper for the RunPod worker — adapted from the local
`backends/launcher/trellis_launcher.py` (`load_pipeline` + `generate`).

Keep the generation logic identical to the local launcher so server and local routes produce
the same GLBs. The pipeline is a process-wide singleton (loaded once, reused per job).

PORTING NOTE: copy the real body of `load_pipeline()` / `generate()` from
`backends/launcher/trellis_launcher.py` into here when baking the image — the structure below
mirrors it (`pipeline.run(image, seed)[0]` → postprocess → `glb.export(..., extension_webp=True)`).
"""

from __future__ import annotations

import os

_PIPELINE = None
_MODEL = os.environ.get("TRELLIS_MODEL", "microsoft/TRELLIS-image-large")


def warm_pipeline():
    """Load the TRELLIS pipeline once (cold start)."""
    global _PIPELINE
    if _PIPELINE is not None:
        return _PIPELINE
    # --- from trellis_launcher.load_pipeline(...) ---
    from trellis.pipelines import TrellisImageTo3DPipeline  # provided by the TRELLIS clone

    _PIPELINE = TrellisImageTo3DPipeline.from_pretrained(_MODEL)
    _PIPELINE.cuda()
    return _PIPELINE


def generate_glb(
    image_path: str,
    output_path: str,
    *,
    seed: int = 42,
    decimation: int = 50000,
    texture_size: int = 1024,
    pipeline_type: str | None = None,
) -> None:
    """image → GLB. Mirrors trellis_launcher.generate()."""
    import torch
    from PIL import Image
    from trellis.utils import postprocessing_utils

    pipeline = warm_pipeline()
    torch.manual_seed(seed)
    image = Image.open(image_path).convert("RGBA")
    outputs = (
        pipeline.run(image, seed=seed)
        if pipeline_type is None
        else pipeline.run(image, seed=seed, pipeline_type=pipeline_type)
    )
    rep = outputs["gaussian"][0] if isinstance(outputs, dict) else outputs[0]
    mesh = outputs["mesh"][0] if isinstance(outputs, dict) else outputs[0]

    glb = postprocessing_utils.to_glb(
        rep,
        mesh,
        simplify=decimation,
        texture_size=texture_size,
    )
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    glb.export(output_path, extension_webp=True)
