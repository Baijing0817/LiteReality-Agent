# object_init — per-object initialization for a room scan

Given a raw LiteReality / RoomPlan scan folder, produce, **for every object**:

- its **cropped evidence images** (the object cut out of the capture frames, ranked good-first),
- a clean **Nano Banana** (Gemini `gemini-2.5-flash-image`) **object-only reference**,

and, for chairs, the **grouping** of repeated chairs into shared types (so four
identical chairs around a table become one type, generated once and placed four times),
and, for **doors/windows**, a clean reference recovered by projecting the RoomPlan
3D opening box into the frames (no detector needed).

This is the **object-evidence stage** of the LiteReality pipeline — it turns a scan
into clean per-object references that downstream 3D generation consumes.

```
raw scan ─► extract_scene ─► crop_objects ─► object_references ─► chair_clusters ─► opening_references
(usdz +      scene_data       per-object      clean nano-banana    chair grouping    door/window refs via
 RGBD)       (walls/objects/   crops           ref per object       + one ref/group   projected 3D opening box
              holes/floor)
```

Openings are thin and point-cloud-sparse, so the ordinary crop misses them. Instead
of a 2D detector (the v2 path used GroundingDINO), `opening_references` projects each
RoomPlan 3D opening box (the 8 world corners in `wall_holes.pkl`) into every frame via
that frame's intrinsic/extrinsic, scores visibility/size/centeredness/sharpness, crops
the best views, and feeds the evidence sheet to Gemini with a door/window prompt
(closed-door state, glass kept natural/content-free).

## Self-contained

A faithful port of the v2 preprocessing **objects/chairs path**. It deliberately
needs **no torch, GroundingDINO, or USD/pxr** — RoomPlan USDZ is parsed by
unzipping + reading the USDA text. Dependencies: `numpy, opencv, pillow, tqdm,
open3d, trimesh, requests` (declared in the repo `pyproject.toml`). The heavy
door/window detector path is intentionally out of scope.

The old external `gemini_trellis_reconstruct.py` helper is replaced by an owned,
self-contained REST client ([`gemini_image.py`](gemini_image.py)).

## Run

From the repo root, as a package module:

```bash
# one scan, end-to-end (real Gemini calls)
uv run -m litereality_agent.scene_init.object_init.run --scan office-elliott

# wire-check without any paid Gemini calls (writes placeholder references)
uv run -m litereality_agent.scene_init.object_init.run --scan office-elliott --skip-gemini

# THE WHOLE PIPELINE: references -> classify -> trellis (organic) + articulated agent (box) -> openings
uv run -m litereality_agent.scene_init.object_init.run --scan office-elliott --full

# just neural reconstruction of the trellis-route objects (needs the GPU env)
uv run -m litereality_agent.scene_init.object_init.run --scan office-elliott --classify --reconstruct

# several scans; --scan takes a scans_uploaded name OR an absolute raw path
uv run -m litereality_agent.scene_init.object_init.run --scan office-elliott tea_room

# a raw folder elsewhere, with an explicit scan name
uv run -m litereality_agent.scene_init.object_init.run --scan /abs/path/to/raw_scan --name my_room
```

Useful flags: `--skip-extract` / `--skip-crop` (reuse existing artifacts),
`--force-extract` / `--force-gemini` (redo), `--only Chair0 Table1`,
`--include-walls`, `--include-openings`, `--skip-openings`, `--max-images N`,
`--output-root DIR`. Reconstruction: `--reconstruct`, `--force-reconstruct`,
`--dry-run-reconstruct`, `--trellis-python PY`, `--seed N`, `--decimation N`.

### Requirements

- A Python with `numpy, opencv, pillow, tqdm, open3d, trimesh, requests`
  (`uv sync` installs them; or use any env that already has them).
- A **Google AI Studio key** for Nano Banana, resolved in order: `$GEMINI_API_KEY`
  → repo `.key` → repo `.keys` → the LiteReality-Studio `.keys`. Not needed with
  `--skip-gemini`.

## Outputs

**Everything for a scan lands under one place** — `<repo>/run/<scan>/` (override
with `--output-root` / `$LITEREALITY_OUTPUT`), grouped so nothing scatters:

```
run/<scan>/
  object_init/
    input/scene_data/<scan>/{walls,objects,wall_holes,floor}.pkl   # RoomPlan layout
    input/parsed_images/<scan>/<Object>/frame_*_ranking_*.jpg      # ★ per-object crops
    object_refs/<scan>/<Object>/
        input2imagegen.jpg      evidence sheet handed to the image model
        clean_obj_reference.png the raw generation (before crop/recentre)
        reference_1024.png      ★ clean object-only reference (normalized)
        gemini_prompt.txt, reference_meta.json
    chair_clusters/<scan>/
        chair_clusters.json     ★ the grouping: members + representative per cluster
        nano_banana_normalized_1024/<ChairCluster>.png   ★ clean per-group reference
    opening_refs/<scan>/<Wall_Door/Window>/
        crops/frame_*.jpg       evidence crops (projected 3D opening box)
        reference_1024.png      ★ clean door/window reference
    object_init_summary.json
  reconstruct/<asset>.glb       ★ textured GLBs (when --reconstruct)
  traces/trace.jsonl            ★ replayable process log (every Gemini call + stage)
  manifest.json                 ★ per-scan roll-up index of everything above
```

The chair `chair_clusters.json` is the grouping contract for downstream
reconstruction: generate one asset per cluster, place it at each member's
RoomPlan box.

## Module map — grouped by what they do

The pipeline runs top-to-bottom. `run.py` orchestrates; everything else is a stage or a
shared helper. **Each group below is its own folder, in flow order** —
`extract/ → crop/ → detect/ → references/ → classify/ → reconstruct.py + procedural/ → qc/`.
Within a folder siblings import each other `from . import X`; shared top-level modules
`from .. import config, tracing`. Modules invoked as subprocesses keep their `__main__` and
are called by their new dotted path (e.g. `-m scene_init.object_init.detect.dino_worker`).

**Orchestration & shared**
| file | role |
|---|---|
| `run.py` | the **orchestrator** — scan → all stages → `manifest.json`. Start here. |
| `config.py` | single source of truth: `run/<scan>/obj_stage/` layout, all paths, Gemini-key + Blender resolution |
| `tracing.py` | always-on event log → `traces/trace.jsonl` (every Gemini call + stage, replayable) |
| `extract/lr_preprocessing/` | vendored RoomPlan parse + point-cloud→frame projection + crop ranking (no torch/USD) |

**Stage 1 — scene extraction** `raw scan → RoomPlan layout`
| `extract_scene.py` | usdz + RGBD → `scene_data/{walls,objects,wall_holes,floor}.pkl` |

**Stage 2 — crops** `layout → per-object evidence images`
| `crop_objects.py` | project each object's 3D box into frames, rank best views, crop |

**Stage 2b — bbox refinement (GroundingDINO)** `tighten the projected crops`
| `detector.py` | **the entry point** — call this; routes to the DINO tool or in-process fallback |
| `dino_detect.py` | the HF GroundingDINO detector (in-process) |
| `dino_worker.py` | the DINO **isolated-subprocess** worker (torch env; loop env stays torch-free) |
| `bbox_polish.py` | drives detection per object → tightens each box to the real 2D detection |

**Stage 3 — clean references (Nano Banana / Gemini)** `crops → one clean ref per object`
| `object_references.py` | per-object crops → one clean object-only `reference_1024.png` |
| `opening_references.py` | doors/windows → ref by projecting the RoomPlan 3D opening box (no detector) |
| `gemini_image.py` | self-contained `gemini-2.5-flash-image` (Nano Banana) REST client |
| `gemini_classify.py` | structured Gemini vision classifier (image+prompt → validated JSON) |

**Stage 4 — chairs** `group repeats → one ref per group`
| `chair_clusters.py` | group identical chairs → `chair_clusters.json` + one ref/cluster |
| `chair_qc.py` | chair-only geometry QC + repair (after reconstruction) |

**Routing** `which generator per object`
| `classify_complexity.py` | VLM router — **procedural vs TRELLIS** per static object |

**Stage 5 — reconstruction** `references → textured GLBs`
| `reconstructor.py` | **the entry point** — call this; routes to the gen3d tool (RunPod/local) or launcher |
| `reconstruct.py` | gathers refs, runs TRELLIS (via `reconstructor`), launches the articulated agent |
| `procedural/generate_procedural.py` | the **agent-authored** route — image → articulated GLB via the `image-to-articulated-glb` skill (`--provider claude\|codex`) |
| `procedural/category_specs.py` | per-RoomPlan-category geometry + articulation domain knowledge |

**`qc/` — QA**
| `glb_qa.py` | geometry QA on generated GLBs (floor slabs, fused background, floaters) |
| `chair_qc.py` | chair-only geometry QC + repair (after reconstruction) |

The skill the procedural route drives lives at `backends/procedural/articulated-glb-agent/` (the
`image-to-articulated-glb` skill, shared by the claude + codex backends).
