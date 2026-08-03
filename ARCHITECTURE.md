# Architecture

LiteReality is one resumable pipeline with two explicit phases and five public stages:

```text
cli.py → PipelineRunner → scene_init                    → realism_authoring
                          ingest → reconstruct → seed      author → publish
```

Each stage exposes `run(context, options) -> StageResult`. `PipelineRunner` owns ordering,
prerequisites, reuse, failure handling, and state in `run/<scene>/.litereality/pipeline.json`.

## Package layout

```text
src/litereality_agent/
├── cli.py               the supported command surface
├── settings.py          Pydantic environment settings
├── pipeline/            workflow ordering, state, and phase implementations
│   ├── scene_init/      capture ingest, reconstruction, and deterministic seed room
│   └── realism_authoring/
│       ├── author/      evidence and optional realism passes
│       └── publish/     final compilation and viewer
├── agent/               extensible agent runners, prompts, tools, and scratch evidence
├── scene/               scene data, geometry, rendering, export, and QC
├── models/              canonical inference and model-specific service adapters
│   └── llm/             provider integrations (`openai/` and `claude/`)
└── runtimes/            execution transports such as RunPod

scripts/                  standalone capture and publishing utilities
deploy/runpod/            container packaging; never imported by application code
```

There are no `services`, `adapters`, `shared`, or nested `pipeline/stages` layers. The directory
name answers the ownership question: phase decisions belong in `pipeline`, reusable model-driven
capabilities belong in `agent`, reusable scene behavior belongs in `scene`, models own inference,
and runtimes own execution location.

`pipeline/realism_authoring/author` owns the optional post-authoring passes (`refine_objects`,
`materials`, and model-driven `quality`). They remain part of the authoring phase rather than
separate public pipeline stages. The Claude session and its capability-tool framework live in
`agent/`, so adding another agent workflow does not expand a pipeline-stage package.

Imports follow one direction, enforced by `tests/test_architecture.py`:

```text
runtimes → models    scene
             \      /  ↑
              pipeline │ agent
                   \    /
                    cli.py
```

Models and scene code never import pipeline code. Agent entry points may consume pipeline context
helpers, while pipeline stages launch agents through their public module entry points. Runtime
selection happens in `models/registry.py`; the pipeline consumes that small composition boundary.

## Configuration and runtimes

`LiteRealitySettings` uses `pydantic-settings` and loads values in this order:

```text
process environment > .env > models.env > typed defaults
```

Heavy inference is isolated from the main environment. A model package owns one inference path
regardless of where it executes. A local adapter can run it in a separately configured process;
a RunPod adapter sends its request contract through `runtimes/runpod.py`. Container-only files
live under `deploy/runpod`, outside application source. The CLI and unit tests do not start DINO,
TRELLIS, Blender, or paid model calls.

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
