# authoring/scene — the staged reconstruction loop

> **Which loop is current:** the supported entry is the **closed tool set** —
> `closed_stage.py`, run via `uv run -m litereality_agent realism_authoring <scan>`, where the agent works through a fixed set of
> tools (`authoring/tools/`) instead of raw Bash. The `run_scene.py` / `planner.py` / `vlm_critic.py`
> files below describe the earlier **legacy** open-tool loop, kept for reference but not wired
> into the CLI. See the repo [ARCHITECTURE.md](../../ARCHITECTURE.md) and
> [docs/HOW_IT_WORKS.md](../../docs/HOW_IT_WORKS.md) for the current flow.

The **legacy** notes below: it drives an LLM (Claude Code or OpenAI Codex CLI) to **edit
`Room.py`** in staged passes, rendering after each edit and gating on a Gemini VLM critic.

```
seed Room.py  ──►  observe (render + critic)  ──►  plan  ──►  agent edits Room.py  ──►  compile → render → verify  ──►  gate
                                                                                                                       │
                                                                                                  pass → next stage    │
                                                                                                  fail → critique back ┘
```

The agent is the intelligence; this module just **orchestrates, verifies, and records**.
Everything the agent touches is constrained to one iteration's `room/` (the `Room.py` it
edits) and `room_preview/` (the render).

## Two stages — each does ONE thing

| # | Stage | Edits | Target |
|---|---|---|---|
| 1 | `materials` | `Room.py` (SHELL materials) | walls / floor / **ceiling** PBR materials, visually matched (CC0 PBR via Poly Haven, per-wall when they differ) |
| 2 | `wall_objects` | `Room.py` + a new `object.py` per fixture | wall / ceiling / floor fixtures RoomPlan misses — sockets, switches, skirting, trunking, radiators, whiteboards, frames, vents, rugs |

> **Stage 3 (per-object refinement) is deferred** — the prompts
> (`authoring/prompts/stages/stage3_*.md`) and the `_stage3_setup()` helper are kept so it can be
> re-enabled by adding `3: {...}` back to `STAGES` in `run_scene.py`. The shipped scene
> runs **stages 1 → 2**.

Stage briefs live in [`authoring/prompts/stages/`](../prompts/stages/) — one **agent prompt** +
one **critic prompt** per stage. They render into the per-iteration prompt at runtime.

## What one iteration does (the observe → plan → edit → verify loop)

```
1. observe   render the CURRENT Room.py from the capture cameras; pair each view with its photo
2. plan      a separate VLM call (planner.py) emits a short structured plan from the render+photo
3. edit      the agent calls tools (edit_scene · place_object · set_material · add_wall_fixture …)
4. verify    compile_room → re-render → VLM critic (gemini) judges THIS stage's target
            → gate: pass → next stage; fail → feed critique back + loop (bounded by --max-refine)
```

Per iteration lands in `run/<scan>/scene_init/scene_stage/stage_<N>/iteration_<M>/`:
- `room/Room.py` — the file the agent edited this iteration.
- `room_preview/` — the render PNGs + the built `Room.glb`.
- `.scene_tracking/` — the exact `prompt.md` sent, the agent's `trajectory.jsonl`, and `verify.json`.

Iterations are self-contained: you can open any `room_preview/Room.glb` in a glTF viewer and
step through what the agent did.

## Run

```bash
# both stages in order, default provider (claude_cli)
uv run python -m litereality_agent.realism_authoring.scene.run_scene --scan <scan> --stage all

# one stage, up to 2 refine passes, judged on 10 views
uv run python -m litereality_agent.realism_authoring.scene.run_scene --scan <scan> --stage 1 --max-refine 2 --views 10

# use Codex CLI instead of Claude Code (loop is provider-agnostic)
LR_HARNESS_PROVIDER=codex uv run python -m litereality_agent.realism_authoring.scene.run_scene --scan <scan> --stage 1

# render the baseline + print the prompt without calling the LLM (free; CI-style)
uv run python -m litereality_agent.realism_authoring.scene.run_scene --scan <scan> --stage 2 --dry-run
```

`uv run -m litereality_agent realism_authoring <scan>` wraps the same orchestration via the top-level CLI.

## Files

```
authoring/scene/
├── run_scene.py     stage orchestration; per stage: render → plan → agent → verify → gate
├── config.py          all paths + knobs (single source of truth, env-driven)
├── agent.py           provider-agnostic agent wrapper (Claude or Codex, one bounded session)
├── planner.py         the planner VLM (a short structured "what to change next" pass)
├── verify.py          render + select + annotate views → report (no SSIM gate; trend only)
├── vlm_critic.py      structured VLM critique (Gemini; reads authoring/prompts/stages/stage{N}_critic.md)
├── evidence.py        per-stage evidence block (overlays, head-on stitches, references)
├── surface_reference.py    rectified head-on stitch per surface (stage-1 ground truth)
├── surface_compare.py      RENDER|REAL ortho sheets per surface (planner + verify input)
├── wall_refs.py            curated sharp wall references (both stages)
├── validate_layout.py      soft scope guard (which files the agent touched)
└── report_html.py     per-iteration HTML reports (browse all attempts)
```

The stage prompt **templates** (`stage{N}_materials.md`, `stage{N}_wall_objects.md`, and the
matching `stage{N}_critic.md`) all live in **`authoring/prompts/stages/`** — outside this module
so prompts are co-located in one place across the project.

## Requirements

- **Blender 4.x** — auto-found via `$LITEREALITY_BLENDER` / `$BLENDER` / `blender` on PATH.
- **`claude-agent-sdk`** in the env if you use `LR_HARNESS_PROVIDER=claude` (default); the
  Codex CLI binary `codex` if you use `LR_HARNESS_PROVIDER=codex`.
- **Gemini API key** (`GEMINI_API_KEY`) for the VLM critic and planner. Without it, the gate is
  skipped (verify reports SSIM only).
- Optional: `LR_DINO_PYTHON` (DINO env) and `RUNPOD_TRELLIS_ENDPOINT` (gen3d) — only used by
  `init/`, not by the loop. See the [README](../../README.md).

Tunables (env, see `config.py`): `HARNESS_ROUNDS`, `HARNESS_VIEWS`, `HARNESS_MODEL`,
`HARNESS_BUDGET`, `HARNESS_REFINE`.

## Scope guard

The agent is told to edit only `Room.py` / `object.py` under this iteration's `room/`. After
each pass the scene runs a soft scope check and **flags any out-of-scope edits** in the
report — it does not auto-revert (you can inspect and decide).
