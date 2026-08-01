"""RunPod serverless handler for TRELLIS — image → textured GLB.

I/O contract (must match models/runpod_trellis.py):
    input  = {"image_b64": str, "seed": int=42, "decimation": int=50000, "texture_size": int=1024}
    output = {"glb_b64": str}                 # base64 GLB (small/medium assets)
             # or upload to storage and return {"glb_url": ...} for large assets

The TRELLIS pipeline is loaded ONCE at cold start (module import) and reused across jobs —
RunPod keeps the worker warm, so subsequent jobs skip model load.
"""

from __future__ import annotations

import base64
import os
import tempfile
import traceback

import runpod
from trellis_generate import generate_glb, warm_pipeline

# cold-start: load the pipeline once (so the first job pays it, the rest are warm)
warm_pipeline()


def handler(job: dict) -> dict:
    try:
        inp = job.get("input") or {}
        image_b64 = inp["image_b64"]
        seed = int(inp.get("seed", 42))
        decimation = int(inp.get("decimation", 50000))
        texture_size = int(inp.get("texture_size", 1024))

        with tempfile.TemporaryDirectory() as d:
            in_png = os.path.join(d, "in.png")
            out_glb = os.path.join(d, "out.glb")
            with open(in_png, "wb") as f:
                f.write(base64.b64decode(image_b64))

            generate_glb(
                in_png, out_glb, seed=seed, decimation=decimation, texture_size=texture_size
            )

            with open(out_glb, "rb") as f:
                glb_b64 = base64.b64encode(f.read()).decode()
        return {"glb_b64": glb_b64}
    except Exception as e:  # noqa: BLE001 — return error to the client, don't crash the worker
        return {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}


runpod.serverless.start({"handler": handler})
