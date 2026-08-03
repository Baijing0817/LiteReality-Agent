# DINO on Modal

This scale-to-zero app serves both GroundingDINO detection and DINOv2 embeddings through the
canonical model code. Its image is CPU-built from precompiled wheels; an L4 is attached only while
requests run. Public Hugging Face weights are cached in the `litereality-dino-models` Volume.

Deploy only through the shared `huangzhening` profile:

```bash
MODAL_PROFILE=huangzhening modal deploy --env main deploy/modal/dino/app.py
```

Configure the pipeline with:

```dotenv
MODAL_DINO_APP=litereality-dino
MODAL_DINO_FUNCTION=infer
MODAL_ENVIRONMENT=main
MODAL_PROFILE=huangzhening
```
