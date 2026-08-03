# TRELLIS on Modal

This is a deployment wrapper around
`litereality_agent.models.trellis.inference`; model inference remains in `src/` and the Modal
runtime only supplies a GPU, parallel execution, and a persistent weight cache.

No Modal resources were created while preparing this change. The Modal CLI was not installed in
the development environment, so the active workspace could not be verified safely. Before doing
anything that creates resources, install/authenticate a profile whose workspace is **huangzhening**
(the workspace at <https://modal.com/apps/huangzhening/main>) and verify it explicitly:

```bash
modal profile list
modal profile activate <the-profile-for-huangzhening>
modal profile current
```

Modal associates deployments with the workspace belonging to the active profile; the workspace
cannot be selected by app source code. Do not deploy from a personal-workspace profile.

Then create/deploy into its `main` environment:

```bash
modal deploy --env main deploy/modal/trellis/app.py
```

The first invocation downloads `microsoft/TRELLIS.2-4B` into the
`litereality-trellis-models` Volume; later containers reuse that cache. Configure the application:

```dotenv
MODAL_TRELLIS_APP=litereality-trellis
MODAL_TRELLIS_FUNCTION=generate
MODAL_ENVIRONMENT=main
```

Install client support with `uv sync --extra modal`. A deployment builds CUDA extensions on an
H100 and therefore incurs GPU build cost; inference also uses H100s. Neither operation is part of
the offline test suite.
