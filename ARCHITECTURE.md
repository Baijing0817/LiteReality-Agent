# LiteReality-Agent — Architecture

Scene reconstruction in two halves: a **deterministic `scene_init`** that seeds an editable scene from a
RoomPlan scan, and a **single agentic authoring pass + targeted refinement loops** that make it look
like the real room. Every model (LLM, VLM, detector, 3D-generator, image-gen) sits behind one **model
registry**, so backends are swappable from env vars. `Room.py` is a reproducible program — the same
inputs rebuild the same room.

```
scan ──init──▶ object_init (TRELLIS · Procedural Gen)
               + scene_init (export Room.py + SHELL) ──▶ Room.py seed
     ──author──▶ one self-paced model pass edits Room.py (materials + fixtures)
     ──refine──▶ per-object (vs reference frames)
     ──QC──▶ geometry lint · true-mesh collision · one model pass
     ──export──▶ .blend, .glb, self-contained Three.js .html viewer
```

## Layers

One installable package, `src/litereality_agent/`, holding six layers in dependency order. Each depends
only on the ones below it; nothing depends upward. Every layer states this contract in its own
`__init__.py`.

| # | package | job | may depend on |
|---|---|---|---|
| 5 | `cli.py` + `__main__.py` | the command line (`uv run -m litereality_agent`) — parsing and dispatch, nothing else | everything |
| 4 | `realism_authoring/` | the **agentic half**: author · refine · qc, the harness they run in, the closed tool set, and the imaging used to see the room | models · integration · scene_init · backends |
| 3 | `scene_init/` | the **deterministic half**: scan → reconstructed objects → seed `Room.py` + `Room.glb`. No LLM drives control flow | models · integration · backends |
| 2 | `integration/` | the **Room program**: export `Room.py` from a scan, compile it to `Room.glb`, and `manifest.py` — the scene package that ties a run's folder together | (nothing) |
| 1 | `models/` | **one front door per model role**: LLM, VLM, detect, gen3d — plus the repo `.env` loader | backends |
| 0 | `backends/` | heavy/external services behind launchers: TRELLIS, GroundingDINO, procedural agent, Sketchfab | (nothing) |

`integration/manifest.py` is deliberately **stdlib-only** even though the rest of `integration/`
pulls Blender and OpenCV: it is the seam between the two halves, so either side must be able to
depend on it cheaply — including a future split into two uv environments, where it is the shared
piece.

## Directory map

```
src/litereality_agent/            THE PACKAGE (one wheel, one import root)
│
├── __main__.py        `uv run -m litereality_agent` — the entry point (no installed console script)
├── cli.py             scene_init · realism_authoring (→ run.sh) · scene · trellis · sketchfab
├── console.py         compact colour-coded one-line-per-stage terminal progress ($LR_COLOR/$LR_QUIET)
├── fonts.py           one cross-platform font resolver for every image the pipeline labels
│
├── realism_authoring/ THE AGENTIC HALF (stage 2)
│   ├── author.py           one self-paced model pass edits Room.py (file tools + capability tools)
│   ├── materials_pass.py   post-author pass: real Poly Haven PBR (LAB-recoloured), material wiring only
│   ├── refine_objects.py   per-object shape refinement — turntable-vs-reference loop (skips TRELLIS meshes)
│   ├── qc_room.py          deterministic geometry linter (AABB: below-floor / floating / clash / …)
│   ├── qc_fix.py           deterministic box-based clash resolver (SAT min-translation)
│   ├── qc_collision.py     deterministic TRUE-MESH resolver (FCL, via scene_collision)
│   ├── qc_pass.py          model-driven QC pass: fewest edits to satisfy a fixed checklist
│   ├── scene_collision.py  true-mesh collision model of a room from Room.glb (FCL, allowed-collision matrix)
│   ├── export_viewer.py    compact self-contained Three.js viewer (OBJECTS · QC · COMPARE · TRACE panels)
│   ├── surfaces.py         dependency-free Room.py parser: the real surface ids (Wall*/Floor/Ceiling)
│   ├── stage_args.py       bind a scene package to a stage's --room/--scan/… path args (`--scene`)
│   ├── narrate.py          one readable line per tool call for the live status row + logs
│   ├── objview.py          Blender headless turntable render of one GLB (picks an articulation pose)
│   ├── run_trace.py        record each pass as structured JSONL + a raw SDK-message sidecar
│   ├── trace_report.py     self-contained HTML run report (timeline + seed→final Room.py diff)
│   ├── authoring_replay.py rebuild an HTML replay from Claude Code session transcripts
│   ├── scene/              the harness: config (paths/knobs) · surface_reference · surface_compare ·
│   │                       wall_refs · report_html · live_log
│   ├── tools/              the CLOSED capability tools those sessions may call: fetch_material ·
│   │                       render · critic · select_views · grid · check_collisions (+ base/registry;
│   │                       compile/ is the harness-intercepted primitive; render/engine/ = Blender render)
│   ├── prompts/           system + stage prompt templates
│   └── views/             IMAGING — how the room is seen
│       ├── room_render/       render_room_cameras · render_vs_capture · rank_views · select_views · annotate_views
│       ├── image_selection/   locked-in reference selection (room/walls/objects) + surface_compare/render_ortho
│       ├── stitch_wall_image/ head-on rectified per-wall ortho stitch + known/unknown masks
│       └── walls_floor_overlay/ overlay RoomPlan wall/floor geometry onto RGB frames (diagnostic)
│
├── scene_init/        THE DETERMINISTIC HALF (stage 1: scan → seed)
│   ├── object_init/       extract → box_merge → crop → detect/bbox_polish (GroundingDINO) → object
│   │                      references (OpenAI image / Claude classify) → chair clusters (DINOv2 + judge)
│   │                      → opening references → reconstruct (gen3d: TRELLIS / procedural via classify_complexity)
│   ├── run_scene_init.py  export the seed Room.py + SHELL (wraps integration.export.export_room)
│   ├── package.py         seal the output folder with its scene.json manifest
│   └── run_init.py        orchestrate object_init → scene export → package
│
├── integration/       THE ROOM PROGRAM + THE RUN'S MANIFEST
│   ├── manifest.py        scene.json: write · read · discover · apply its $LITEREALITY_* env ·
│   │                      embed the capture. `python -m litereality_agent.integration.manifest env <dir>`
│   │                      is what run.sh evals. Stdlib only.
│   ├── config.py          single source of truth for the run/<scan>/ output-tree paths
│   ├── procedural_materials.py  parametric Blender-node materials (carpet/fabric/plaster/tile/…)
│   ├── run.py             one-command driver: pack_assets → build_room → blank room.glb
│   ├── compile/           Room.py → Room.glb: build_room · build_from_room · bake_glb · pack_assets ·
│   │                      fetch_textures · texture_recipe · recolor
│   └── export/            scan → Room/<scan>/: export_room · extract_shell (usdz → semantic SHELL)
│
├── models/            ONE FRONT DOOR PER ROLE: base.py (role Protocols + ModelRegistry) · factory.py ·
│                      names.py · config.py (the repo .env loader) · _shared.py ·
│                      claude_cli/codex_cli · dino · procedural ·
│                      local_trellis · runpod_trellis
│
├── backends/          HEAVY/EXTERNAL, isolated behind launchers (_env.py puts pristine clones on sys.path):
│   ├── trellis/{remote,local}   RunPod serverless worker / local GPU
│   ├── grounding_dino/          detection worker
│   ├── procedural/              LLM-agent articulated-GLB generation (category specs + completeness gates)
│   └── sketchfab/               download real 3D models (fetch_object backend)
│
└── scripts/           standalone entry points, never imported (see scripts/README.md):
    ├── *.sh                     per-stage batch runners (init · preprocess · generate ·
    │                            reconstruct · scene_init · qc)
    ├── build_meshes.py · build_pointclouds.py · colorize_pcd.py   capture-side geometry
    ├── shrink_scan.py           shrink a RoomPlan capture (drop metadata, recompress frames)
    └── ops/                     adopt_stranded_glbs · merge_objects · reexport.sh

run.sh · sanity.py · tests/                  at the repo root — the entry points and their checks
run/ · scans_uploaded/ · example_scans/      data, addressed via REPO_ROOT (run/ and scans_uploaded/ gitignored)
```

## The registry — one front door per model

`models/base.py` defines `ModelRegistry` + a Protocol per role, used by **both** init and
the authoring/refine sessions:

| role | backend(s) | selected by |
|---|---|---|
| `llm` | claude_cli (default) / codex_cli | `ProviderConfig.provider` |
| `gen3d` | **neural** RunPod/Local TRELLIS · **procedural** (articulated, QC-gated) | `gen3d_for_env()` / `gen3d_for_route()` — `classify_complexity` routes box/articulated → procedural, organic → TRELLIS |
| `detect` | GroundingDINO | in-process (default) or isolated via `$LR_DINO_PYTHON` |
| `vlm` | Claude (default) | `HARNESS_VLM` |
| image-gen | OpenAI `gpt-image-2` (`gpt-image-1` legacy) | `LR_IMAGE_PROVIDER` (default `openai`) · model via `LR_OPENAI_IMAGE_MODEL` |

`llm`, `gen3d` and `detect` are wired into `ModelRegistry` today via `factory.build_model_registry`;
`vlm` and image-gen are still selected directly by their env vars (their registry wrappers are
pending). The default `llm` is `claude_cli` — the free, no-key path.

## Provider policy

**Claude for all reasoning/VLM · OpenAI for image-gen only · ** Defaults honour this:
`LR_IMAGE_PROVIDER=openai`, `LR_CLASSIFY_PROVIDER=claude`, `HARNESS_VLM=claude` (also baked into
`run.sh`). 

## How to run

```bash
./run.sh <scan|path/to/scan>    # whole pipeline — a name under $LR_SCANS_DIR, or the capture folder

uv run -m litereality_agent scene_init <scan|dir>           # stage 1 only → Room.py seed + Room.glb + scene.json
uv run -m litereality_agent realism_authoring <scan|dir>    # authoring + refinement on an existing init (delegates to run.sh)
```


