"""RunPod serverless TRELLIS worker — clean image → GLB, returned inline (no external storage).

Built on camenduru/trellis-tost's proven Dockerfile (CUDA 12.6 + torch 2.5.1 + flash-attn +
kaolin/nvdiffrast/diso/spconv + TRELLIS-image-large weights baked in at /content/model). We keep
their environment and just replace the Discord-upload handler with a clean contract that matches
our client (models/runpod_trellis.py):

    input  = {"image_b64": str, "seed": 42, "simplify": 0.95, "texture_size": 1024,
              "preprocess_image": true}
    output = {"glb_b64": str}   |   {"error": str}
"""

import base64
import os
import tempfile
import traceback

# TRELLIS backends — set BEFORE importing trellis. Override via endpoint env if needed.
os.environ.setdefault("SPCONV_ALGO", "native")
os.environ.setdefault("ATTN_BACKEND", os.environ.get("TRELLIS_ATTN", "xformers"))

import runpod
from PIL import Image
from trellis.pipelines import TrellisImageTo3DPipeline
from trellis.utils import postprocessing_utils

# cold start: load the pipeline + baked weights ONCE; RunPod keeps the worker warm.
pipeline = TrellisImageTo3DPipeline.from_pretrained("/content/model")
pipeline.cuda()


def handler(job):
    try:
        inp = job.get("input") or {}
        image_b64 = inp["image_b64"]
        seed = int(inp.get("seed", 42))
        simplify = float(inp.get("simplify", 0.95))  # GLB decimation ratio (0–1)
        texture_size = int(inp.get("texture_size", 1024))
        preprocess = bool(inp.get("preprocess_image", True))  # rembg background removal

        with tempfile.TemporaryDirectory() as d:
            in_png = os.path.join(d, "in.png")
            out_glb = os.path.join(d, "out.glb")
            with open(in_png, "wb") as f:
                f.write(base64.b64decode(image_b64))

            outputs = pipeline.run(
                Image.open(in_png).convert("RGBA"),
                seed=seed,
                formats=["gaussian", "mesh"],
                preprocess_image=preprocess,
            )
            glb = postprocessing_utils.to_glb(
                outputs["gaussian"][0],
                outputs["mesh"][0],
                simplify=simplify,
                texture_size=texture_size,
                verbose=False,
            )
            glb.export(out_glb)
            with open(out_glb, "rb") as f:
                glb_b64 = base64.b64encode(f.read()).decode()
        return {"glb_b64": glb_b64}
    except Exception as e:  # noqa: BLE001 — return the error, keep the worker alive
        return {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-2000:]}


runpod.serverless.start({"handler": handler})
