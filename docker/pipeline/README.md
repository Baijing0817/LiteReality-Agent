# RunPod pipeline image

This image is the remote orchestrator for the full LiteReality pipeline. It contains Blender,
GroundingDINO/DINOv2, Claude Code, `claude-agent-sdk`, and the application. TRELLIS deliberately
stays in its existing RunPod Serverless endpoint.

## Build

Do not build this image on a contributor laptop. `.github/workflows/pipeline-image.yml` builds it
on GitHub-hosted infrastructure and publishes branch and commit tags to:

```text
ghcr.io/litereality/litereality-pipeline
```

The workflow runs when pipeline-container inputs change and can also be started manually after it
exists on the default branch. A private GHCR package requires a RunPod registry credential with a
GitHub token that has `read:packages`; no registry token belongs in this repository or image.

## RunPod template

Create an on-demand GPU Pod template with:

- Image: the workflow's immutable `sha-...` tag
- Container disk: at least 30 GB
- Volume or network volume: at least 50 GB, mounted at `/workspace`
- Start command: leave unset (the image stays alive for SSH access)
- GPU: start with a 24 GB card; TRELLIS itself runs on the separate Serverless endpoint

Supply these as RunPod environment variables/secrets at deployment time:

```text
OPENAI_API_KEY
RUNPOD_API_KEY
RUNPOD_TRELLIS_ENDPOINT
```

Do not set `ANTHROPIC_API_KEY` when the run should use the Claude Code subscription.

## First remote session

Connect to the Pod and authenticate Claude Code. The browser portion of login can be completed on
your normal computer; the resulting credential is stored under persistent `/workspace` rather than
inside the image.

```bash
claude
claude auth status
```

Upload a RoomPlan capture to `/workspace/scans/<name>/`, then run:

```bash
litereality run /workspace/scans/<name> --polish
```

Results are written to `/workspace/run/<name>/`. Download the result and terminate the Pod when the
run is finished. Stopping releases GPU compute but can continue to incur storage charges.

## Remote smoke checks

These commands verify the container without loading a model or running a render:

```bash
blender --version
python -c 'import torch; print(torch.__version__, torch.cuda.is_available())'
litereality --help
claude auth status
```

