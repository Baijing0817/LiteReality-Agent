# DINO RunPod worker

One scale-to-zero RunPod Serverless endpoint provides both capabilities used by ingest:

- GroundingDINO open-vocabulary boxes (`op: detect`)
- DINOv2 image embeddings (`op: embed`)

The local application sends images as base64 and receives JSON only. Torch and model inference stay
inside the remote worker. Attach a RunPod network volume and configure the endpoint with
`HF_HOME=/runpod-volume/huggingface`; the first worker downloads both public Hugging Face models,
and later scale-from-zero workers reuse the cached weights.

Both models use Hugging Face Transformers and Hugging Face-hosted weights, but neither is currently
served by a Hugging Face Inference Provider. This image has no custom CUDA compilation: its build
is CPU-only, while the RunPod endpoint supplies a GPU only during inference.

Configure the local application with:

```text
RUNPOD_API_KEY=...
RUNPOD_DINO_ENDPOINT=...
```

The worker image is built from the repository root using this directory's `Dockerfile`. Model
inference and the worker contract remain in `litereality_agent.models`; this directory contains
deployment packaging only.
