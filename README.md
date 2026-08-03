# LiteReality-Agent

LiteReality-Agent turns a RoomPlan capture into an editable `Room.py`, a compiled `Room.glb`, and a
self-contained viewer.

```text
capture → ingest → reconstruct → seed → author → publish
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

For a full remote run that does not install Blender or load models on a contributor laptop, use the
[RunPod pipeline image](docker/pipeline/README.md). GitHub Actions builds the image remotely; a
temporary RunPod Pod runs Blender, DINO, and authoring while calling TRELLIS Serverless.

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

Every runtime is grouped by model and execution location:

```text
models/grounding_dino/local/
models/dinov2/local/
models/trellis/local/
models/trellis/hosted/
models/openai/hosted/
models/claude/hosted/
```

`local/` implementations run only when explicitly configured; hosted TRELLIS uses the RunPod
credentials in `.env`. The normal offline test suite never loads models or starts Blender.

## Development

Safe local verification is limited to static checks, offline unit tests, CLI parsing, and package
builds:

```bash
uv run ruff check src tests sanity.py scripts
uv run pytest -q
uv build
```

Tests marked `blender`, `scan`, or `live` are excluded by default.
