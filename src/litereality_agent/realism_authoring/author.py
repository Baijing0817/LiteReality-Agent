"""One-shot room authoring.

A single self-paced model pass reconstructs the room's shell materials and the wall/ceiling/floor
fixtures by editing `Room.py` in place — there is no staged survey/plan/fix orchestration. The
model is given generic Read/Edit/Write on the room directory plus a set of capability tools that
plain file-editing cannot replace: `fetch_material` (real Poly Haven PBR — diffuse + roughness +
normal, LAB-recoloured to the measured colour) and `render` / `critic` / `select_views` as an
optional self-check it may call to compare its render against the capture photos and correct
colour and placement.

    LITEREALITY_BLENDER=<blender dir> .venv/bin/python authoring/author.py --scene <scene dir>

`--scene` is the scene PACKAGE `uv run -m litereality_agent scene_init` wrote (the folder holding `scene.json`); it supplies the
room, the surface references and the capture. Omit it entirely when $LR_SCENE is set or the
current directory is inside a package. The explicit spelling still works and still wins:

    ... authoring/author.py --room <room dir> --surface-ref <dir> --scan <scan dir>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path


# Surfaces are DISCOVERED from the room, never assumed: a scan has as many walls as RoomPlan gave it
# (a one-bed flat came back with 30). A hardcoded Wall0..WallN silently drops every wall past the cap
# from the prompt AND from the stitch-coverage check below, so the run reports full coverage while
# most of the room was never referenced. `surface_ids` parses Room.py's SHELL and also excludes
# RoomPlan's sub-0.35m corner-artifact stub walls, whose stitches are useless smears.
def surfaces_for(room: Path) -> list[str]:
    from litereality_agent.realism_authoring.surfaces import surface_ids

    return surface_ids(room / "Room.py")


# capability tools exposed to the authoring model: real materials + optional self-check
CAPABILITY_TOOLS = ("fetch_material", "render", "critic", "select_views", "grid", "check_collisions")

PROMPT = """\
You are reconstructing a REAL room as an editable Python program, self-paced (no fixed steps).

The room is `Room.py` in your working directory: a builder + a `SHELL` dict (walls, openings,
object boxes). FIRST Read `Room.md` and `Room.py` IN FULL to learn the helper API (how shell
materials are assigned, how geometry is added). Then edit `Room.py` IN PLACE so the rebuilt room
matches the real room in the images.

Two jobs, IN THIS ORDER — do (1) fully first, then (2):
1) SHELL STRUCTURE + MATERIALS — the FOUNDATION. Get the room itself right and render-check the bare
   room BEFORE you add any fixture, so fixtures land on a room that already reads correctly.
   • STRUCTURE FIRST: check the room's SHAPE against the photos and fix clear scan errors in the
     `SHELL` dict — a missing or spurious wall, a wall with wrong endpoints/length, a door/window at
     the wrong offset/width/height/sill (or one the scan missed or hallucinated), a wrong floor/ceiling
     height. Edit the numbers in `SHELL` (see Room.md "Editing the scene"). Be CONSERVATIVE and
     evidence-based: correct obvious errors against the photos, keep it metric, and do NOT redesign a
     room that is already right. Do NOT move/resize the furniture object boxes
     (Table*/Chair*/reconstructed objects) — structure means walls / openings / floor+ceiling height only.
   • THEN MATERIALS for every surface ({surface_list}): base colour (hue+lightness),
     finish, pattern. READ PAST anything mounted on a wall — material is the exposed wall. Don't skip
     the CEILING. Don't touch fixtures until the structure is corrected and every surface has a material.
2) WALL FIXTURES the scan missed but the photos show (sockets, switches, trunking, boards, signs,
   radiators, shelves, skirting, ceiling vents, rugs) — simple procedural geometry flush to the
   wall, anchored to the SHELL's opening offsets / wall lengths. Never over a Door/Window opening.
   Only start this once (1) is done.

GROUP EVERY FIXTURE AS ONE UNIT. A fixture is usually several boxes (a whiteboard = frame bars +
face + tray; a radiator = panel + fins + valves). Those parts MUST be bundled into a single named,
hide-as-a-unit group — never left as a loose pile of boxes. Use the helper
`group_fixture(name, category, parts)` (defined near the collection helpers in `Room.py`; if your
`Room.py` doesn't have it, add it once: an empty named `name` with `room_id`/`category` props, each
part parented to it and moved into a collection named `name`). Collect the objects your box helpers
return into a list and pass them, e.g.
    parts = [_wall_box(...), _wall_box(...), ...]   # all boxes of THIS one fixture
    group_fixture("Whiteboard0", "whiteboard", parts)
Name each fixture like the furniture handles — `Whiteboard0`, `Radiator0`, `Shelf0`, `Socket0`,
`Trunking0`, `Vent0` (increment per instance). The whole fixture then selects/hides/toggles as one
object in the viewer, exactly like `Table0`/`Chair0`. This grouping is REQUIRED, not optional.

The DECISIVE references are the HEAD-ON STITCHES (each shows one surface square-on). Read every one:
{stitch_lines}
Raw oblique frames are in {scan} (optional context).

You have TOOLS beyond editing — use them:
- `fetch_material(query, name, color_hex, pattern_strength)` — for any PATTERNED surface (carpet,
  tile, wood, brick, strong plaster) pull a REAL Poly Haven PBR set (diffuse+roughness+normal),
  LAB-recoloured to your measured colour. It saves into the room's `materials/` + `textures.json`
  and returns a wiring snippet — wire it into `Room.py` (real UV scale in metres). Prefer this over
  a flat colour whenever the photo shows a pattern; keep flat colour+roughness only for PLAIN paint.
  For the categories Poly Haven covers poorly — CARPET / RUG / FABRIC / PLASTER and patterned
  TILE / BRICK / WOOD floors — you can instead use the code-native procedural materials:
  `from integration.procedural_materials import make` then `make("carpet"|"fabric"|"plaster"|
  "tile"|"brick"|"wood_planks", color=(r,g,b))` returns a Blender material to assign directly in
  `Room.py` (parametric, tileable, no download). Use whichever matches the photo better.
- `render(target)` — render `Room.py` for 'room' or a wall, paired with the real photo; it returns
  PNG path(s). READ the returned PNG with your own eyes to check colour/placement against the photo,
  then fix `Room.py`. Use this to CATCH COLOUR DRIFT especially — author, render, look, correct.
- `critic(images, goal)` — a strict pass/score verdict if you want a second opinion.
- `select_views(target)` — best frames (render auto-picks if you omit frames).
Call them when useful; you don't have to render every surface. A couple of render-checks on the
surfaces you're least sure about is worth far more than none.

Constraints:
- Edit ONLY `Room.py`; it MUST stay valid Python that compiles. You MAY correct SHELL STRUCTURE
  (walls, openings, floor/ceiling height) when the scan is clearly wrong vs the photos — conservatively
  and metric, per job (1). But do NOT move/resize the furniture object boxes (Table*/Chair*/reconstructed
  objects). Assign everything in CODE (materials via the fetched recipe so a fresh rebuild reproduces them).

When done, summarise per surface: the material (flat vs fetched PBR + which asset) and the fixtures.
"""

# "go harder" profile — same tools, but fixtures MUST be detailed multi-part geometry, render-verified.
DETAIL_PROMPT = """\
You are reconstructing a REAL room as an editable Python program, self-paced. The priority THIS run
is FIXTURE DETAIL: every mounted object must read as a real 3D thing, never a flat slab.

The room is `Room.py` in your working directory: a builder + a `SHELL` dict (walls, openings, object
boxes). FIRST Read `Room.md` and `Room.py` IN FULL to learn the helper API (how materials are
assigned, how geometry/boxes are added). Then edit `Room.py` IN PLACE to match the real room.

Two jobs, IN THIS ORDER — finish (1) FIRST, then spend the bulk of the run on (2):
1) SHELL STRUCTURE + MATERIALS — the foundation. Do this FIRST and render-check the bare room BEFORE
   any fixture, so fixtures land on a room that already reads correctly.
   • STRUCTURE: check the room's SHAPE against the photos and fix clear scan errors in the `SHELL`
     dict — a missing/spurious wall, wrong wall endpoints/length, a door/window at the wrong
     offset/width/height/sill (or one the scan missed or hallucinated), a wrong floor/ceiling height.
     Edit the numbers in `SHELL` (see Room.md "Editing the scene"). Be conservative, evidence-based and
     metric — correct obvious errors, don't redesign a room that's already right, and do NOT move/resize
     the furniture object boxes (Table*/Chair*/reconstructed objects).
   • MATERIALS for every surface ({surface_list}): match colour/finish/pattern. Read
     PAST anything mounted on a wall. Use `fetch_material` for genuinely patterned surfaces
     (carpet/tile/wood/brick); flat colour+roughness for plain paint. Keep it efficient (don't
     over-polish) but do NOT skip the CEILING. Don't start fixtures until structure is fixed and every
     surface has a material.
2) WALL FIXTURES the photos show — modelled as DETAILED MULTI-PART geometry. This is where most of
   your effort goes, but only AFTER (1) is done.

## THE RULE: no fixture is a single flat box. Build each from parts so its SILHOUETTE matches the stitch.
Model every non-trivial fixture as a small assembly (write a Python loop where it repeats):
- **shelving / bookshelf** → vertical uprights/standards + individual brackets per shelf + each board
  as its own slab + a few representative ITEMS sitting on the boards (books/boxes as small blocks).
- **radiator** → back panel + a LOOP of vertical fins (10–20 thin slats) + top grille + end caps +
  the two pipe valves at the bottom.
- **whiteboard / notice board** → frame border (4 thin bars) + recessed inset face (its own material)
  + a pen tray / bottom lip; cork boards get a visibly thicker frame.
- **AC / split unit** → main body box + a sloped/louvred front vent (a loop of thin louvre slats) +
  the pipe/conduit run leaving it.
- **cable trunking / conduit** → a channel base + a proud lid (two stacked thin boxes), not one strip.
- **sockets / switches** → a faceplate plate + the raised outlet/rocker on it (2 parts min), not a dot.
- **skirting / dado** → a board with a slightly proud top lip if the photo shows a moulding profile.
Match each part's real proportions off the stitch; give parts distinct materials (metal vs plastic vs
board). 10 lines of a `for`-loop beats one box.

## MANDATORY grouping: every fixture's parts bundle into ONE named, hide-as-a-unit group.
The whole point of multi-part fixtures is defeated if the parts are a loose pile you must hide one
box at a time. So EACH fixture (all its bars/fins/slats/boards/items) MUST be wrapped into a single
named group via the helper `group_fixture(name, category, parts)` (defined near the collection
helpers in `Room.py`; if it's not already there, add it once — an empty named `name` with
`room_id`/`category` props, each part parented to it and moved into a collection named `name`):
    parts = []
    parts.append(_wall_box(...))          # back panel
    for i in range(n_fins):               # the fin loop
        parts.append(_wall_box(...))
    parts += [_wall_box(...), _wall_box(...)]   # valves
    group_fixture("Radiator0", "radiator", parts)
Every box helper returns its object — collect them and pass the list. Name each instance like the
furniture handles: `Whiteboard0`, `Radiator0`, `Shelf0`, `Socket0`, `Trunking0`, `AC0`, `Vent0`.
The grouped fixture then selects, HIDES and toggles as ONE object in the viewer / outliner / glTF,
exactly like `Table0`/`Chair0`. This is REQUIRED for every fixture — a whiteboard's frame+face+tray
hide together, a radiator's fins hide together. Do NOT leave fixture parts ungrouped in the flat
`Fixtures` bucket.

## MANDATORY render-verify per wall (this is required, not optional)
After you add the fixtures on a wall, you MUST `render(target='Wall<N>')`, then READ the returned PNG
with your own eyes and check EACH fixture's SILHOUETTE against the real photo/stitch: does the
radiator show fins? the shelf show brackets + boards + items? the whiteboard show a frame + tray?
If any fixture reads as a flat rectangle/slab, ADD the missing parts and re-render that wall. Do NOT
mark a wall done until its fixtures read as 3D assemblies, not cut-outs. Anchor everything to the
SHELL's opening offsets / wall lengths; never place a fixture over a Door/Window opening; horizontal
runs (trunking, skirting) BREAK at openings.

The DECISIVE references are the HEAD-ON STITCHES (each surface square-on) — read every one:
{stitch_lines}
Raw oblique frames are in {scan}. Beware: a stitch can be mirrored/warped — cross-check fixture
positions against a raw frame before committing.

Tools: `fetch_material`, `render` (returns PNG paths — Read them), `critic(images, goal)`,
`select_views`. Use `render` liberally this run — it is how you confirm the silhouettes.

Constraints: edit ONLY `Room.py`; it MUST compile. You MAY correct SHELL STRUCTURE (walls, openings,
floor/ceiling height) when the scan is clearly wrong vs the photos — conservatively and metric, per
job (1) — but do NOT move/resize the furniture object boxes (Table*/Chair*/reconstructed objects).
Everything in CODE so a fresh rebuild reproduces it.

When done, summarise per wall: each fixture, its GROUP NAME (e.g. `Radiator0`), the PARTS you built
it from, and note which walls you render-verified.
"""

PROFILES = {"base": PROMPT, "detail": DETAIL_PROMPT}


def room_compiles(room: Path) -> str:
    """"" if `Room.py` is valid Python, else the error. A syntax check, not a build.

    Deliberately cheap — `compile()`, no Blender. It runs after every edit, and the failure it
    guards against is syntactic: an `Edit` applied to a file the model was mid-thought about.
    """
    src = room / "Room.py"
    try:
        compile(src.read_text(encoding="utf-8"), str(src), "exec")
    except SyntaxError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    except OSError as exc:
        return str(exc)
    return ""


def checkpoint(room: Path, where: Path) -> bool:
    """Save `Room.py` as last-known-good if it compiles. Returns True when saved.

    A long session that dies mid-edit used to leave whatever the last write happened to be —
    possibly unparseable, which fails every downstream stage. Keeping the newest COMPILING
    version means a break costs one edit, not the run.
    """
    if room_compiles(room):
        return False
    try:
        where.parent.mkdir(parents=True, exist_ok=True)
        where.write_bytes((room / "Room.py").read_bytes())
        return True
    except OSError:
        return False


def build_capability_server(scene_path: Path, tool_names):
    """In-process MCP server exposing a SUBSET of the closed registry, scene-bound. Mirrors
    agent/harness/agent.py:_build_closed_server but for a chosen tool list (capabilities only)."""
    from claude_agent_sdk import create_sdk_mcp_server
    from claude_agent_sdk import tool as sdk_tool

    from litereality_agent.realism_authoring.tools import build_default_registry

    registry = build_default_registry()

    def _make_handler(name: str):
        async def _handler(args):
            inv = await registry.build_invocation(name, args or {})
            if inv is None:
                return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "is_error": True}
            if hasattr(inv, "bind"):
                inv.bind(str(scene_path), None)
            try:
                res = await inv.execute()
            except Exception as exc:  # noqa: BLE001
                return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "is_error": True}
            return {"content": [{"type": "text", "text": json.dumps(res.to_dict(), default=str)}],
                    "is_error": not res.is_success()}
        return _handler

    sdk_tools = []
    for name in tool_names:
        decl = registry.get_tool(name)
        fn = decl.schema["function"]
        sdk_tools.append(sdk_tool(name, fn["description"], fn["parameters"])(_make_handler(name)))
    server = create_sdk_mcp_server(name="cap", version="1.0.0", tools=sdk_tools)
    allowed = [f"mcp__cap__{n}" for n in tool_names]
    return server, allowed


# The self-check / exploration tools are the capability MCP tools (mcp__cap__render|critic|
# select_views|grid|fetch_material). In wind-down they're switched off so the remaining budget goes
# to FINAL Room.py edits; Read/Edit/Write/Glob stay on so the model can still land its work.
_EXPLORE_PREFIX = "mcp__cap__"


def _make_step_budget_hook(state: dict, budget: int, reserve: int, log):
    """PreToolUse hook that turns a `budget` of tool-calls into a graceful landing.

    The only pre-existing control was `--max-turns`, a hard SDK cap that just throws and abandons
    the loop (whatever compiling Room.py was last checkpointed is kept). This instead COUNTS every
    tool call and steers the ending:
      • last `reserve` steps  → DENY the self-check tools so the model spends what's left making its
        final Room.py edits, with a message telling it to wind down;
      • at `budget`           → end the session cleanly (Room.py is already edited in place).
    `state` carries the live count back out for the run summary.
    """
    finalize_at = max(1, budget - max(0, reserve))

    async def hook(input_data, tool_use_id, context):
        state["calls"] += 1
        n = state["calls"]
        tool = input_data.get("tool_name", "") if isinstance(input_data, dict) \
            else getattr(input_data, "tool_name", "") or ""

        if n >= budget:
            if not state.get("hard_logged"):
                state["hard_logged"] = True
                state["stopped"] = f"step budget {budget} reached"
                log(f"\n  ⛔ step budget {budget} reached (call {n}) — ending the authoring session.")
            msg = (f"STEP BUDGET EXHAUSTED ({n}/{budget}). Stop now — do not call any more tools; "
                   f"Room.py is saved as-is.")
            return {"continue_": False, "stopReason": msg,
                    "systemMessage": f"authoring: step budget {budget} reached — ending run"}

        if n >= finalize_at:
            fin = (f"STEP BUDGET: step {n}/{budget}. WIND DOWN NOW — stop rendering / critiquing / "
                   f"fetching. Use your remaining {max(0, budget - n)} step(s) to make ONLY your final "
                   f"Room.py edits (the most important remaining fixes), then finish with your per-wall "
                   f"summary. The self-check tools are disabled for the rest of the run.")
            if tool.startswith(_EXPLORE_PREFIX):
                if not state.get("winddown_logged"):
                    state["winddown_logged"] = True
                    log(f"\n  ⏳ step {n}/{budget} — wind-down: self-check tools disabled, "
                        f"{max(0, budget - n)} step(s) left for final edits.")
                return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                               "permissionDecision": "deny",
                                               "permissionDecisionReason": fin}}
            # An allowed edit/read during wind-down: nudge once so the model knows it's landing.
            if not state.get("winddown_ctx_sent"):
                state["winddown_ctx_sent"] = True
                return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                               "permissionDecision": "allow",
                                               "additionalContext": fin}}
        return {}

    return hook


async def run(room: Path, surface_ref: Path, scan: Path, model: str, max_turns: int, profile: str = "base",
              step_budget: int = 100, step_reserve: int = 15):
    from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, ResultMessage, query

    surfaces = surfaces_for(room)
    stitches = [surface_ref / f"{s}_stitched.jpg" for s in surfaces]
    stitch_lines = "\n".join(f"  - {s} (head-on): {p}" for s, p in zip(surfaces, stitches) if p.is_file())
    prompt = PROFILES.get(profile, PROMPT).format(stitch_lines=stitch_lines, scan=scan,
                                                  surface_list=", ".join(surfaces))
    # Images the model MAKES to look at are evidence; give it somewhere durable to put them.
    from litereality_agent.realism_authoring import scratch
    scratch_at = scratch.bind(near=room)
    prompt += scratch.prompt_line()
    from litereality_agent.realism_authoring.narrate import describe_tools_line
    prompt += describe_tools_line()

    server, cap_allowed = build_capability_server(room, CAPABILITY_TOOLS)
    # readable roots: the room, the stitches, the scan, and the resolved output tree (render PNGs +
    # fetched textures land under the realpath of the output symlink) + the repo root.
    from litereality_agent import REPO_ROOT as repo_root
    dirs = {str(repo_root), str(os.path.realpath(room.parents[2])), str(surface_ref), str(scan),
            str(os.path.realpath(surface_ref))}
    if scratch_at is not None:
        dirs.add(str(scratch_at))
    # Step budget: a graceful landing at `step_budget` tool-calls (wind-down then stop), enforced by
    # a PreToolUse hook. `--max-turns` stays as the SDK-level backstop below it. budget<=0 disables.
    budget_state = {"calls": 0}
    hooks = None
    if step_budget and step_budget > 0:
        hooks = {"PreToolUse": [HookMatcher(
            hooks=[_make_step_budget_hook(budget_state, step_budget, step_reserve,
                                          lambda s: print(s, flush=True))])]}
    options = ClaudeAgentOptions(
        cwd=str(room),
        add_dirs=sorted(dirs),
        system_prompt={"type": "preset", "preset": "claude_code"},
        setting_sources=["project", "user"],
        allowed_tools=["Read", "Edit", "Write", "Glob"] + cap_allowed,
        mcp_servers={"cap": server},
        permission_mode="bypassPermissions",
        max_turns=max_turns,
        model=model,
        hooks=hooks,
    )

    # verify-reads guardrail: the stitches are the DECISIVE reference but are handed over by path,
    # so the model MUST choose to Read each one. Track which stitches it actually opened and report
    # per-surface coverage — a stitch that exists but was never read is a silent quality risk.
    present = {s: p for s, p in zip(surfaces, stitches) if p.is_file()}
    missing = [s for s in surfaces if s not in present]  # surface exists in Room.py, stage 2 gave no stitch
    stitch_names = {p.name: s for s, p in present.items()}  # basename → surface (symlink-proof match)
    read_surfaces: set[str] = set()

    budget_line = (f"step budget={step_budget} (wind-down at {max(1, step_budget - max(0, step_reserve))})"
                   if step_budget and step_budget > 0 else "step budget=off")
    print(f"== one-shot authoring + capability tools [profile={profile}] ==\n  model={model} room={room}\n"
          f"  tools=Read,Edit,Write,Glob + {list(CAPABILITY_TOOLS)}\n"
          f"  surfaces={len(surfaces)} stitches={len(present)}/{len(surfaces)}  |  {budget_line}, max-turns={max_turns}\n",
          flush=True)
    t0 = time.monotonic()
    result_text, cost = "", None
    # Names and inputs live on ToolUseBlock only; the narrator holds the id→call map so a
    # ToolResultBlock can be attributed back. See narrate.py for what reading them off the
    # result block cost us.
    from litereality_agent.realism_authoring.narrate import ToolNarrator
    nar = ToolNarrator()
    # Structured record of the loop, so a one-shot run is documented the way staged runs were.
    from litereality_agent.realism_authoring.run_trace import RunTrace
    tr = RunTrace("author", room=room, scan=os.environ.get("LITEREALITY_SCAN"))
    # The prompt is the other half of "what happened": a tool choice only makes sense
    # against what the session was actually asked to do, and profiles change that.
    tr.start(model=model, room=str(room), profile=profile, stitches=len(present),
             max_turns=max_turns, scratch=str(scratch_at) if scratch_at else None, prompt=prompt)
    # Kept OUTSIDE the room: the room dir is copied and scanned wholesale downstream, and a
    # stray second Room-ish file in it is a trap.
    last_good = room.parent / ".room_checkpoint.py"
    checkpoint(room, last_good)  # the seed is valid by construction — start from it
    ended_early = ""
    try:
      async for m in query(prompt=prompt, options=options):
        tr.raw(m)
        for block in getattr(m, "content", []) or []:
            b = type(block).__name__
            if b == "TextBlock" and getattr(block, "text", "").strip():
                print(f"  …{block.text.strip()[:150]}", flush=True)
                tr.think(block.text)
            elif b == "ToolUseBlock":
                print(nar.use(block), flush=True)
                tr.tool(getattr(block, "name", "?"), getattr(block, "input", {}) or {},
                        tool_id=getattr(block, "id", "") or "")
            elif b == "ToolResultBlock":
                tr.result(block)
                name, inp = nar.result(block)
                # Stitch coverage: the model was handed its head-on references by PATH, so
                # opening them is a choice. Credit the surface only once the Read comes back
                # — a use block that errored is not evidence the reference was seen.
                if name == "Read" and not getattr(block, "is_error", False):
                    surf = stitch_names.get(Path(str(inp.get("file_path") or "")).name)
                    if surf:
                        read_surfaces.add(surf)
                # Safety net: an image the model made outside the run (habitually /tmp) is copied
                # in now, while it still exists. Result time, not use time — a Bash that creates
                # the file has not run yet when its use block arrives.
                for kept in scratch.rescue(inp, getattr(block, "content", None)):
                    print(f"      ↳ kept {kept.name}", flush=True)
                failed = nar.error_line(name, block)
                if failed:
                    print(failed, flush=True)
                # Newest COMPILING Room.py wins. Cheap enough to run per edit, and it is what
                # makes an interrupted session cost one edit instead of the whole run.
                elif name in ("Edit", "Write", "Bash"):
                    checkpoint(room, last_good)
        if isinstance(m, ResultMessage):
            result_text = m.result or ""
            cost = getattr(m, "total_cost_usd", None)
    except BaseException as exc:  # noqa: BLE001 — including the SDK's turn-cap Exception
        # Running out of turns is not a failed run. `Room.py` is edited IN PLACE, so by this
        # point the session's work is already on disk; raising here threw it away, because
        # run.sh runs authoring as a HARD stage and aborts the pipeline on a non-zero exit.
        # Two hours of paid authoring were discarded for hitting a cap that means "time's up",
        # not "this is broken". What actually matters is whether the room still compiles —
        # checked below.
        ended_early = f"{type(exc).__name__}: {exc}"
        print(f"\n  ⚠ session ended early — {ended_early}", flush=True)
        tr.think(f"[session ended early] {ended_early}")
    # A budget stop is a deliberate, graceful end (continue=False from the hook), not a crash —
    # record it the same way as a turn-cap so the summary and exit logic treat it as "time's up".
    if budget_state.get("stopped") and not ended_early:
        ended_early = budget_state["stopped"]
        print(f"\n  ⏹ authoring stopped on {ended_early} "
              f"({budget_state['calls']} tool-calls) — Room.py kept as-is.", flush=True)
        tr.think(f"[step budget] {ended_early}")
    dt = round(time.monotonic() - t0, 1)
    calls, counts = nar.calls, nar.counts

    # The ONE thing that must hold when this returns: Room.py is valid Python. Every downstream
    # stage (materials, refine, qc, export) builds it, so a broken file fails all of them.
    broken = room_compiles(room)
    if broken and last_good.is_file():
        (room / "Room.py").write_bytes(last_good.read_bytes())
        print(f"  ⚠ Room.py did not compile ({broken}) — restored the last good version",
              flush=True)
        tr.think(f"[restored checkpoint] {broken}")
        broken = room_compiles(room)
    tr.end(calls=calls, cost_usd=cost, summary=result_text)
    print(f"\n== done {dt}s | calls={calls} {counts} | cost=${cost} ==\n", flush=True)
    if tr.ok:
        print(f"   trace → {tr.path}", flush=True)

    # per-surface stitch coverage — over EVERY surface in the room, not just the stitched ones, so a
    # surface stage 2 failed to stitch shows up as a gap instead of vanishing from the denominator.
    skipped = [s for s in present if s not in read_surfaces]
    print("STITCH COVERAGE (head-on references the model actually opened):", flush=True)
    for s in surfaces:
        mark = "✓" if s in read_surfaces else ("✗ NO STITCH" if s in missing else "✗ NEVER OPENED")
        print(f"  {mark} {s}", flush=True)
    if missing:
        print(f"  ⚠ {len(missing)}/{len(surfaces)} surface(s) have NO stitch: {', '.join(missing)} — "
              f"stage 2 (surface stitches) did not produce one.", flush=True)
    if skipped:
        print(f"  ⚠ {len(skipped)}/{len(present)} stitch(es) never read: {', '.join(skipped)} — "
              f"those surfaces were authored WITHOUT looking at their head-on reference.", flush=True)
    elif not missing:
        print(f"  all {len(present)} stitch(es) read ✓", flush=True)

    print("\nSUMMARY:\n" + result_text[:2500], flush=True)

    # Exit status = "is the room usable", not "did the session run to completion". Downstream
    # stages need valid Python and nothing else; a turn cap with a compiling room is a partial
    # success worth keeping, and only an unrecoverable room is worth aborting the pipeline for.
    if ended_early:
        print(f"  note: ended early ({ended_early}) — Room.py is valid, continuing.", flush=True)
    if broken:
        print(f"  ✗ Room.py does not compile and no checkpoint could be restored: {broken}",
              flush=True)
    return 1 if broken else 0


def main():
    from litereality_agent.realism_authoring import stage_args

    ap = argparse.ArgumentParser(description=__doc__)
    stage_args.add_scene_arg(ap)
    # Not required any more: a scene package supplies all three. Passing them still wins.
    ap.add_argument("--room", default=None, help="room dir to edit (default: the package's work room)")
    ap.add_argument("--surface-ref", default=None)
    ap.add_argument("--scan", default=None, help="the capture dir (default: the package's capture)")
    ap.add_argument("--model", default=os.environ.get("HARNESS_MODEL", "claude-opus-5"))
    ap.add_argument("--max-turns", type=int, default=140,
                    help="hard SDK backstop (assistant turns); the step budget lands the run before this")
    ap.add_argument("--step-budget", type=int, default=int(os.environ.get("AUTHOR_STEPS", "100")),
                    help="tool-call budget: graceful wind-down + stop at this many calls (0 disables)")
    ap.add_argument("--step-reserve", type=int, default=int(os.environ.get("AUTHOR_STEP_RESERVE", "15")),
                    help="steps before the budget at which self-check tools switch off for final edits")
    ap.add_argument("--profile", default="base", choices=list(PROFILES))
    a = stage_args.bind(ap.parse_args(), need=("room", "surface_ref", "scan"))
    from litereality_agent.realism_authoring import scratch
    try:
        rc = asyncio.run(run(Path(a.room), Path(a.surface_ref), Path(a.scan), a.model, a.max_turns,
                             a.profile, step_budget=a.step_budget, step_reserve=a.step_reserve))
        raise SystemExit(rc or 0)
    finally:
        # A turn cap, a budget stop and an SDK error all leave through here. Claim whatever the
        # session wrote to the scratch ROOT, and drop the run dir if it produced nothing.
        scratch.finish()


if __name__ == "__main__":
    main()
