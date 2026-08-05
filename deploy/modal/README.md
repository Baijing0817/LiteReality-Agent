# Modal setup

Modal hosts the GPU-backed model functions while the pipeline stays on the calling machine. The
apps remain deployed between calls, but their containers scale to zero when idle.

## One-time setup

1. Join the intended shared Modal workspace.
2. Install the client with `uv sync --extra modal`.
3. Authenticate and select an explicit local profile:

   ```bash
   uv run modal setup
   uv run modal profile list
   uv run modal profile activate <shared-profile>
   export MODAL_PROFILE=<shared-profile>
   uv run modal profile current
   ```

   `MODAL_PROFILE` is required by the application. No workspace profile is hardcoded in source.

4. For TRELLIS only, obtain access to
   `facebook/dinov3-vitl16-pretrain-lvd1689m` on Hugging Face and create the workspace secret:

   ```bash
   uv run modal secret create --env main huggingface HF_TOKEN="$HF_TOKEN"
   ```

DINO uses public weights and does not need the Hugging Face secret.

## Deploy

From the repository root, with `MODAL_PROFILE` still set:

```bash
uv run modal deploy --env main deploy/modal/dino/app.py
uv run modal deploy --env main deploy/modal/trellis/app.py
```

Then configure the pipeline:

```dotenv
MODAL_PROFILE=<shared-profile>
MODAL_ENVIRONMENT=main
MODAL_DINO_APP=litereality-dino
MODAL_DINO_FUNCTION=infer
MODAL_TRELLIS_APP=litereality-trellis
MODAL_TRELLIS_FUNCTION=generate
```

The first deployment builds the images, and the first invocation downloads model weights into
persistent Modal Volumes. DINO runs on an L4. TRELLIS runs on one H100 with zero application
retries and a ten-second idle scale-down window. A deployed app with zero active containers does
not consume GPU compute, though its stored image and Volume data remain.

See [`dino/README.md`](dino/README.md) and [`trellis/README.md`](trellis/README.md) for model-specific
details.
