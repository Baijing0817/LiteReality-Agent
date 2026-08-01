# LiteReality-Agent architecture

LiteReality is one resumable Python pipeline. Every major stage has one public boundary and returns
a structured `StageResult`; `PipelineRunner` owns ordering, prerequisites, reuse, invalidation,
failure policy, and state persistence.

```text
ingest → reconstruct → seed → evidence → author → refine → quality → publish
```

Run the full workflow or one stage through the installed uv entrypoint:

```bash
uv run litereality run <scan-or-capture>
uv run litereality run <scene> --from author --through quality
uv run litereality stage publish <scene>
```

## Package layout

```text
src/litereality_agent/
├── cli/                 argument parsing, compatibility aliases, presentation
├── pipeline/
│   ├── context.py       explicit paths and typed settings for one run
│   ├── result.py        StageStatus and StageResult
│   ├── runner.py        dependency-aware orchestration and resume state
│   ├── providers.py     composition of model protocols with adapters
│   └── stages/          ingest, reconstruct, seed, evidence, author, refine, quality, publish
├── scene/               scene manifest, path rules, Room.py compiler, materials, geometry QC
├── services/
│   ├── models/          provider-neutral model protocols and value types
│   ├── rendering/       Blender rendering, view selection, comparisons, overlays
│   ├── tracing/         structured event history, narration, reports
│   └── tools/           closed authoring capability-tool registry
├── adapters/            Claude/Codex, DINO, TRELLIS, procedural, Blender, Sketchfab integrations
└── shared/              typed Pydantic settings and dependency-light utilities

scripts/
├── pipeline/            batch and compatibility wrappers
├── capture/             capture geometry utilities
└── ops/                 repair and migration operations
```

Top-level `scripts/` is not part of the wheel and must never be imported. Reusable behavior belongs
under `src/litereality_agent/`; scripts only translate operational arguments into package calls.

## Dependency direction

Imports point inward and are checked by `tests/test_architecture.py`:

```text
shared ← scene ← services ← adapters ← pipeline ← cli
```

- `scene` owns portable scene data and geometry behavior, not orchestration.
- `services.models` defines protocols; concrete provider implementations live in `adapters`.
- `pipeline.providers` is the composition root that binds protocols to adapters.
- Services and adapters never import pipeline stages.
- Pipeline stages may use every lower layer but not the CLI.

## Stage contract

Every stage exposes `run(context, options) -> StageResult` and declares:

- prerequisites;
- whether failure is required or optional;
- how completion is recognized on disk;
- the artifacts it produced.

Statuses are `completed`, `reused`, `skipped`, and `failed`. Required failures stop the run.
Optional failures remain visible and later independent stages continue; `--strict` promotes them to
fatal failures. `--force <stage>` removes saved state for that stage and all dependents.

The runner writes orchestration state to `run/<scene>/.litereality/pipeline.json`. Existing
`scene.json` fields and generated artifact paths remain compatible, so completed reconstruction work
does not need to be regenerated after this source restructure.

## Configuration

`shared.settings.LiteRealitySettings` is the typed configuration boundary, implemented with
`pydantic-settings`. Precedence is:

```text
process environment > .env > models.env > typed defaults
```

Aliases such as `BLENDER_PATH` and `GROUNDING_DINO_PYTHON` are normalized into canonical fields.
Secrets use `SecretStr`. The CLI loads settings once and `RunContext` passes them explicitly;
canonical environment variables are exported only for isolated legacy subprocesses. Importing a
module never searches for Blender, requires credentials, creates output folders, or requires a scan.

## Generated scene layout

The generated layout remains stable during this cleanup:

```text
run/<scene>/
├── scene.json
├── scene_init/
│   ├── obj_stage/       crops, references, reconstructed objects, traces
│   └── scene_stage/     seed Room.py, assets, seed preview
├── realism_authoring/   authored room, renders, refinement, QC, final deliverables
└── .litereality/        pipeline resume state
```

`scene_init/` and `realism_authoring/` are siblings, so rerunning or removing authoring output cannot
destroy expensive reconstructed seed assets.
