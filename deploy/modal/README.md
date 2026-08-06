# Modal setup

Modal hosts the GPU-backed model functions while the pipeline stays on the calling machine. The
apps remain deployed between calls, but their containers scale to zero when idle.

Modal is rented compute, not a model API: a Modal token gives you GPUs, not models, so nothing is
callable until you deploy these apps into your own workspace.

## One-time setup

1. Join the intended Modal workspace, or use your own — nothing is pinned to a particular one.
2. Install the client with `uv sync --extra modal`.
3. Authenticate and select an explicit local profile:

   ```bash
   uv run modal setup
   uv run modal profile list
   uv run modal profile activate <profile>
   export MODAL_PROFILE=<profile>
   uv run modal profile current
   ```

   `MODAL_PROFILE` is required by the application. No workspace profile is hardcoded in source.

**No Hugging Face account or token is required for either app.** DINO's weights are public.
TRELLIS.2-4B is MIT and ungated, and TRELLIS.2's gated DINOv3 image encoder is baked into the image
from a digest-verified ungated mirror — see [`trellis/README.md`](trellis/README.md).

## Deploy

From the repository root, with `MODAL_PROFILE` still set:

```bash
uv run modal deploy --env main deploy/modal/dino/app.py
uv run modal deploy --env main deploy/modal/trellis/app.py
```

Then configure the pipeline. Modal is the default runtime, so `MODAL_PROFILE` alone is enough —
the app names, function names, and environment already default:

```dotenv
MODAL_PROFILE=<profile>
```

The first deployment builds the images, and the first invocation downloads model weights into
persistent Modal Volumes. DINO runs on an L4. TRELLIS runs on one H100 with zero application
retries and a ten-second idle scale-down window. A deployed app with zero active containers does
not consume GPU compute, though its stored image and Volume data remain.

## What deployment costs

Measured on a fresh workspace, 2026-08-06. The DINO image builds entirely on CPU. The TRELLIS image
took 11.3 minutes and about $0.45, split almost evenly in time between the CPU dependency layers
(318.0s) and the H100 extension compile (318.4s), with the GPU layer carrying roughly 78% of the
cost. A redeploy after a source-only change took 2.8 seconds. The first request returned a valid
512-texture GLB from `ChairCluster0` — 33,898 vertices, 47,793 faces — in 295.7s including the
one-time weights download.

Two known inefficiencies, both worth fixing before running this at volume:

1. **Every workspace rebuilds the image.** Modal caches built images per workspace with no
   cross-workspace sharing, so each deployer pays the same ~11 minutes and ~$0.45 to compile
   identical extensions. Publishing the built image to a public registry and switching to
   `modal.Image.from_registry(...)` would reduce a first deploy to a pull. The build needs an
   NVIDIA GPU only because upstream's `setup.sh` checks `nvidia-smi` — `nvcc` itself compiles
   without one, and `TORCH_CUDA_ARCH_LIST` is already pinned, so CI could build and publish it.
2. **Weights download on the H100.** `_load_pipeline()` runs inside the `gpu="H100"` function, so
   the first call transfers several GB at H100 prices (~$0.32 of that first request). A CPU-only
   function populating the same Volume would cost about a cent.

See [`dino/README.md`](dino/README.md) and [`trellis/README.md`](trellis/README.md) for model-specific
details.
