# TRELLIS on RunPod

This directory contains RunPod container packaging only. The application-facing service and
RunPod request adapter live under `litereality_agent.models.trellis`; execution transport lives
under `litereality_agent.runtimes`.

The existing deployed endpoint uses the original `TRELLIS-image-large` worker represented here.
Local inference uses TRELLIS.2. Keep that endpoint as the E2E baseline while its replacement is
built from the canonical TRELLIS.2 inference path; switch endpoint configuration only after a
one-object comparison succeeds.

Both deployments use this contract:

```text
input  = {"image_b64": str, "seed": 42, "simplify": 0.95, "texture_size": 1024}
output = {"glb_b64": str} | {"glb_url": str} | {"error": str}
```
