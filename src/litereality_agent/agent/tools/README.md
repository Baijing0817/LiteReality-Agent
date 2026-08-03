# authoring/tools — the agent's capability tools

The tools the authoring / materials / QC agent is handed each run, on top of `Read`/`Edit`/`Write`/
`Glob`. `default_registry.build_default_registry()` assembles them into a `ToolRegistry`, and
`author.build_capability_server` exposes them to the claude_agent_sdk as `mcp__cap__*`.

Shared plumbing: `base.py` (declarative tool + strict pydantic params), `registry.py` (name →
tool, OpenAI-format schemas), `code_region.py`, `_scene.py`, `_vlm.py` (self-contained VLM call).

**Where the heavy backing code lives.** The render/annotate ENGINE is at [`render/engine/`](render/engine/)
(CLI: `python -m litereality_agent.scene.rendering.engine <mode> ...`). Two backings stay
outside on purpose — shared library code the deterministic init also uses:
`authoring/views/room_render/select_for.py` (+`select_views.py`) which the `select_views` tool wraps,
and `integration.compile_room` which `render` recompiles through.

## Capability tools

| Tool | What it does |
|---|---|
| [`fetch_material`](fetch_material/) | real Poly Haven PBR set (diffuse+rough+normal), optionally recoloured |
| [`select_views`](select_views/) | best frames for `room` / a wall / an object — never guess frames |
| [`render`](render/) | render\|photo comparison for ONE target layer (auto-frames + recompiles) |
| [`grid`](grid/) | metric ruler on a surface stitch — READ a fixture's (u, z) in metres instead of estimating |
| [`critic`](critic/) | VLM **grade** vs a goal → `{pass, score, issues}` — the judge |
| [`check_collisions`](check_collisions/) | TRUE-MESH clash/containment (default) from Room.glb — object↔object, through-wall, outside-room, grounding + robotics-style articulated door/window checks (see [`../scene_collision.py`](../scene_collision.py)); each with a metric snap/resize fix. `method='box'` = fast SHELL-box fallback when no glb |

`compile/` stays a module (render recompiles through it) but is not a registered tool — the agent
compiles via `render`, not a standalone call.

## retired tools

The old **closed-loop driver** (`agent/harness/loop.py`, `run_agent(tools_mode="closed")`) drove an
"11 primitives + 3 composites" closed set with a raw-API loop. That driver is gone; the live stages
run on the claude_agent_sdk with the capability tools above. The retired primitives (`read_code`,
`edit_code`, `read_image`, `plan`, `fetch_object`) and composites (`inspect`, `fix`, `survey`) are
parked at the repo-root `legacy/litereality_agent/realism_authoring/tools/` for reference — nothing in the
live path imports them.
