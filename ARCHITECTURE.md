# Architecture

LiteReality is one resumable pipeline with five public stages:

```text
cli.py → PipelineRunner → ingest → reconstruct → seed → author → publish
```

Each stage exposes `run(context, options) -> StageResult`. `PipelineRunner` owns ordering,
prerequisites, reuse, failure handling, and state in `run/<scene>/.litereality/pipeline.json`.

## Package layout

```text
src/litereality_agent/
├── cli.py               the supported command surface
├── settings.py          Pydantic environment settings
├── telemetry.py         dependency-neutral event logging
├── pipeline/            workflow ordering and stage implementations
│   ├── ingest/          capture → crops and reference images
│   ├── reconstruct/     object routing and 3D generation
│   ├── author/          evidence and Room.py authoring tools
│   └── publish/         final compilation and viewer
├── scene/               scene data, geometry, rendering, export, and QC
└── models/
    ├── <model>/local/    implementations executed on a configured local machine
    └── <model>/hosted/   implementations executed through a hosted API

scripts/                  standalone capture and publishing utilities
```

There are no `services`, `adapters`, `shared`, or nested `pipeline/stages` layers. The directory
name answers the ownership question: workflow decisions belong in `pipeline`, reusable scene
behavior belongs in `scene`, and inference runtimes belong under their named model.

`pipeline/author` also owns the optional post-authoring passes (`refine_objects`, `materials`, and
model-driven `quality`). They remain part of the authoring feature rather than separate public
pipeline stages.

Imports follow one direction, enforced by `tests/test_architecture.py`:

```text
models    scene
    \      /
     pipeline → cli.py
```

Models and scene code never import pipeline code. Hosted/local model selection happens in
`models/registry.py`; the pipeline consumes that small composition boundary.

## Configuration and runtimes

`LiteRealitySettings` uses `pydantic-settings` and loads values in this order:

```text
process environment > .env > models.env > typed defaults
```

Heavy inference is isolated from the main environment. `models/<name>/local` means the code can be
run on a separately configured compute machine; it does not mean the main pipeline silently loads
that model in-process. TRELLIS can instead use `models/trellis/hosted` with RunPod. The CLI and unit
tests do not start DINO, TRELLIS, Blender, or paid model calls.

## Output compatibility

Generated paths remain stable so previous work can be resumed:

```text
run/<scene>/
├── scene.json
├── scene_init/          crops, references, reconstructed objects, seed room
├── realism_authoring/  authored room and final deliverables
└── .litereality/        resume state
```

Some legacy artifact filenames such as `nano_banana_raw.png` are still read for compatibility;
they are data-format details, not supported providers or package boundaries.
