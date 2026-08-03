"""Modal deployment wrapper for the canonical TRELLIS.2 implementation.

Deploy only from the shared ``huangzhening`` Modal workspace profile. See README.md.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

import modal

APP_NAME = "litereality-trellis"
FUNCTION_NAME = "generate"
MODEL_VOLUME = "litereality-trellis-models"
REMOTE_REPO_ROOT = Path("/root")
WEIGHTS_ROOT = Path("/models")

deployment_root = Path(__file__).resolve().parent
image = (
    modal.Image.from_dockerfile(
        deployment_root / "Dockerfile",
        context_dir=deployment_root,
        gpu="H100",
    )
    .add_local_python_source("litereality_agent")
    .env(
        {
            "LR_REPO_ROOT": str(REMOTE_REPO_ROOT),
            "LITEREALITY_WEIGHTS": str(WEIGHTS_ROOT),
            "HF_XET_HIGH_PERFORMANCE": "1",
        }
    )
)
weights = modal.Volume.from_name(MODEL_VOLUME, create_if_missing=True)
app = modal.App(APP_NAME)
_pipeline = None


def _load_pipeline():
    global _pipeline
    if _pipeline is None:
        from litereality_agent.models.trellis.inference import (
            DEFAULT_MODEL,
            load_pipeline,
            prepare_local_model,
        )

        _pipeline = load_pipeline(prepare_local_model(DEFAULT_MODEL))
        weights.commit()
    return _pipeline


@app.function(
    name=FUNCTION_NAME,
    image=image,
    gpu="H100",
    volumes={str(WEIGHTS_ROOT): weights},
    timeout=20 * 60,
    scaledown_window=60,
    max_containers=8,
)
def generate(request: dict) -> dict:
    """Convert the transport payload into one GLB using model-owned inference code."""
    from litereality_agent.models.trellis.inference import generate as generate_glb

    with tempfile.TemporaryDirectory() as temporary_dir:
        temp = Path(temporary_dir)
        image_path = temp / "input.png"
        output_path = temp / "output.glb"
        image_path.write_bytes(base64.b64decode(request["image_b64"], validate=True))
        generate_glb(
            _load_pipeline(),
            image_path,
            output_path,
            seed=int(request.get("seed", 42)),
            decimation_target=_decimation_target(request.get("simplify", 0.95)),
            texture_size=int(request.get("texture_size", 1024)),
            pipeline_type=None,
        )
        return {"glb_b64": base64.b64encode(output_path.read_bytes()).decode("ascii")}


def _decimation_target(simplify: float) -> int:
    """Translate the legacy ratio into the canonical launcher's face target."""
    ratio = min(max(float(simplify), 0.0), 1.0)
    return max(10_000, round(1_000_000 * (1.0 - ratio)))
