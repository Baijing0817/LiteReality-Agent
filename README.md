# LiteReality-Agent

LiteReality-Agent turns a RoomPlan capture into an editable `Room.py`, a compiled `Room.glb`, and a
self-contained viewer.

```text
capture → scene_init (ingest → reconstruct → seed)
        → realism_authoring (author → publish)
```

## Setup

Install the lightweight application environment:

```bash
uv sync --frozen --group dev
cp .env.example .env
```

Configure `OPENAI_API_KEY`, the scan/output paths, Blender, and a TRELLIS runtime. RunPod is the
recommended TRELLIS runtime on macOS; local model environments are isolated and explicitly
selected. See [ARCHITECTURE.md](ARCHITECTURE.md) for the package and runtime boundaries.

## Run

The installed CLI is the only supported pipeline entry point:

```bash
uv run litereality run /path/to/capture
uv run litereality run /path/to/capture --through seed
uv run litereality stage author run/my-room
uv run litereality stage author run/my-room --force --polish
uv run litereality scene inspect run/my-room
```

The five stages are resumable. Their state is stored in
`run/<scene>/.litereality/pipeline.json`; `--force <stage>` invalidates that stage and its
dependents.

The author stage retains three optional quality passes: procedural-object refinement, PBR material
polish, and model-driven final QC. `--polish` runs all three; the individual flags are
`--refine-objects`, `--materials`, and `--quality-pass`.

Output lives under `run/<scene>/`:

- `Room.py`: editable scene program
- `Room.glb`: compiled scene
- `<scene>.html`: lightweight Three.js viewer
- `scene.json`: paths and artifact manifest

## Models

Model packages contain one inference implementation and its application-facing adapters:

```text
models/grounding_dino/{inference,service,runpod,worker}.py
models/dinov2/inference.py
models/trellis/{inference,service,runpod}.py
runtimes/runpod.py
deploy/runpod/<model>/
```

Inference does not move when execution moves. Local services use an isolated process; RunPod
adapters call an endpoint through the shared runtime transport; container-only files live outside
`src` under `deploy/`. The normal offline test suite never loads models or starts Blender.

A hosted API call is not a model package. Reference-image generation and quick classification are
single requests to someone else's endpoint, with no inference to host and no runtime to choose, so
they are filed with the stage that makes the call, not grouped by the vendor that answers it:
`scene_init/ingest/references/image_gen.py` and
`scene_init/reconstruct/classify/classify_{claude,openai}.py`.

The procedural route is not a model. It is an agent workflow that authors Blender code from an
object reference, so it lives under `agent/object_generation/`; `procedural` remains the routing
label describing the generated geometry.

## Development

Safe local verification is limited to static checks, offline unit tests, CLI parsing, and package
builds:

```bash
uv run ruff check src tests sanity.py scripts
uv run pytest -q
uv build
```

Tests marked `blender`, `scan`, or `live` are excluded by default.
