# integration — how we define a room

> **Quick API:** `import integration as sb`; call `sb.export_scene(scan)` → `Room/<scan>/`,
> then `sb.compile_room(room_dir)` → `Room.glb`. Everything below is the design behind those
> two calls and how to edit the room program by hand.

## Package map (after the 2026-06 reorg)
```
integration/
├── __init__.py           public API: export_scene · compile_room · bake_room
├── config.py             shared paths (output tree, scan dirs, Blender lookup)
├── export/               « scan → Room/<scan>/ definition »
│   ├── export_room.py        write Room.py + SHELL + manifest + per-object dirs
│   └── extract_shell.py      room.usdz → compact semantic SHELL (Blender)
├── compile/              « Room.py → Room.glb (the room compiler) »
│   ├── build_from_room.py    materialize objects + assemble SHELL in Blender
│   ├── bake_glb.py           flatten SHELL node materials so glb == render
│   ├── build_room.py         (internal) Blender room-build helpers
│   ├── pack_assets.py        gather a scan's GLBs into a flat asset dir
│   ├── fetch_textures.py     materialize textures from a textures.json recipe
│   ├── texture_recipe.py     reverse-engineer textures/ → textures.json recipe
│   └── recolor.py            LAB-shift a texture's mean to a target RGB
├── render.py             render a Room from the capture cameras (vs photo)
├── run.py                one-command: GLBs + scan → blank Room.glb
└── _harness.py           (internal) scene-builder dev harness
```
All `python -m` invocations use the subpackage path now:
`python -m litereality_agent.integration.compile.build_from_room --room <r>`,
`python -m litereality_agent.integration.export.export_room --scan <s>`, etc.

---

A **room** here is a single, self-contained, **plain-text definition** that fully
rebuilds the 3D scene. Nothing in the definition is a baked binary you have to trust
blindly — the geometry, the materials, and the assembly are all readable and editable
source. Run one command and the definition rebuilds itself into a previewable scene.

```
Room/<scan>/            the DEFINITION   (source of truth — commit this, edit this)
        │  build_from_room.py
        ▼
Room_preview/<scan>/    the BUILD        (derived — regenerable, gitignorable)
```

---

## The big idea — three principles

A room definition is built on three rules that keep it text, small, and editable:

1. **Geometry as text.** The room shell (walls, door/window openings, every object's
   box) is a compact `SHELL` dict embedded in `Room.py` — *not* a binary `room.usdz`.
   Walls are start/end points, openings are "which wall + offset + size + sill",
   objects are center/size/yaw. An agent edits numbers to edit the scene. (~9 KB total.)

2. **Materials as code.** Procedural objects store **no texture images** — just a
   `textures.json` *recipe*: a Poly Haven asset id to download, optionally with an LAB
   color shift (real texture + recolor, never a flat solid). Textures are rebuilt at
   build time. (Definition shrinks from tens of MB to a few KB.)

3. **One uniform `object.py` interface.** Every object — whether procedurally modeled
   or a neural mesh — exposes the same `object.py` (`blender … object.py -- <texdir>
   <out.glb>` produces its glb). The build treats them all alike: "run object.py → get
   a glb". (Procedural ones model from scratch; static ones load + finish a mesh.)

The only unavoidable binary is a **static object's `.glb`** (a neural/scanned mesh with
no code to regenerate it from).

---

## The two folders

### `Room/<scan>/` — the definition (source)
```
Room.py            the assembler + this room's SHELL (walls / openings / object boxes)
                   — embedded at the bottom as an editable dict. No room.usdz.
Room.md            English; explains the SHELL fields and how to edit the scene
manifest.json      which object fills which RoomPlan box
Objects/
  Procedural/<name>/   object.py   object.md   textures.json   (code + material recipe; NO glb, NO images)
  Static/<name>/       <name>.glb  object.py   object.md        (mesh source + uniform object.py)
```

### `Room_preview/<scan>/` — the build (derived)
```
Room.glb           the assembled blank scene (neutral shell + placed objects)
Room.blend         the same scene as a Blender project (open it to inspect/edit)
room_layout.json   machine-readable objects + cameras
Object/
  <name>.glb              each object materialized by running its object.py
  <name>_textures/        its textures, downloaded + recolored from the recipe
```

---

## Quick start

Two interpreters are involved (see **Running it** below): `$PY` = the venv with
`cv2`/`requests`, and Blender is invoked internally.

```bash
PY=.venv/bin/python   # the repo's uv env (has cv2, requests, trimesh)

# 1) write the definition for a scan  ->  Room/<scan>/
$PY integration/export_room.py --scan office-elliott

# 2) rebuild it  ->  Room_preview/<scan>/Room.glb + Room.blend
$PY integration/build_from_room.py --room Room/office-elliott
#    --regenerate   re-run every object.py / re-fetch every texture (else cached)
```

That's the whole loop: **export → edit → build_from_room**.

---

## How to edit a room

Everything is plain text, so editing the scene = editing files.

**Layout — move walls, doors, windows, furniture** → edit `SHELL` in `Room.py`:
```python
SHELL = {
  "floor_z": -1.59, "ceiling_z": 1.11,
  "walls":    {"Wall0": {"start": [-3.98, 0.69], "end": [-0.04, 2.27], "thickness": 0.0}, ...},
  "openings": {"Door0":   {"wall": "Wall1", "type": "door",   "offset": 0.50, "width": 0.79, "height": 2.06, "sill": 0.0},
               "Window0": {"wall": "Wall5", "type": "window", "offset": 0.99, "width": 1.77, "height": 1.51, "sill": 1.12}},
  "objects":  {"Table0": {"category": "table", "center": [-0.7, 0.6, -1.2], "size": [1.74, 1.72, 0.78], "yaw": 0.0}, ...},
}
```
- move a wall → change its `start`/`end`
- slide a door along its wall → change `offset`; raise a window → change `sill`
- move / rotate / resize a piece of furniture → change `center` / `yaw` / `size`

**Appearance — what an object is made of**:
- shape → edit the object's `object.py` (procedural build code)
- material → edit `textures.json`: a Poly Haven `base` id + an optional `rgb` color
  shift (`{"from":"recolor","base":"beige_wall_001","rgb":[208,207,207]}`)

Then run `build_from_room.py` to see the change.

---

## Scripts

| script | what it does | run with |
|--------|--------------|----------|
| **`export_room.py`** | scan → `Room/<scan>/`: extract `SHELL`, reverse textures into recipes, wrap static meshes in a uniform `object.py` | `$PY` (cv2/requests) |
| **`build_from_room.py`** | `Room/<scan>/` → `Room_preview/`: rebuild shell from `SHELL`, fetch+recolor textures, run each `object.py`, assemble `Room.glb` + `Room.blend` | `$PY` |
| `build_room.py` | the assembler itself (this is what's copied into each `Room.py`): shell → thicken walls → cut openings → fit objects into boxes → cameras → neutral shell → export | (Blender) |
| `extract_shell.py` | `room.usdz` → compact semantic `SHELL` (walls/openings/objects/floor) | (Blender) |
| `texture_recipe.py` | a `textures/` dir → `textures.json` (queries Poly Haven to classify each map) | `$PY` |
| `fetch_textures.py` | a `textures.json` → real images (download Poly Haven + LAB recolor), cached in `~/.litereality_texcache` | `$PY` |
| `recolor.py` | LAB color shift of one texture (keeps the pattern); ported from studio `apply_color_to_texture` | `$PY` |
| `pack_assets.py` / `run.py` | the *direct* build path (gather existing glbs + assemble, skipping the definition) — handy for quick iteration | `$PY` |

---

## Running it

- **`$PY`** = the repo's uv env, `.venv/bin/python` (has `cv2`, `requests`, `trimesh`).
  `export_room.py` and `build_from_room.py` must be run with it, because they recolor
  textures and query Poly Haven.
- **Blender** is found via `$BLENDER` (binary) or `$LITEREALITY_BLENDER` (install dir), else
  `blender` on PATH. The scripts call it internally (you don't invoke Blender yourself).
- **Cameras**: `build_from_room` adds the capture cameras when the original scan frames
  (`scans_uploaded/<scan>/frame_*.json`) are present; the shell itself needs only `SHELL`.

### Two workflows
- **A. define → rebuild** (canonical, reproducible): `export_room.py` then
  `build_from_room.py`. Use when you want the room *as a committed, portable definition*.
- **B. direct build** (fast iteration): `run.py --scan <name>` packs the live generator
  outputs and assembles straight to a `Room.glb`, skipping the definition.

---

## What the build deliberately leaves out

The assembled `Room.glb` is a **blank baseline**: neutral-grey walls + floor, no
ceiling, no wall fixtures, no collision. Wall/floor/ceiling materials and fixtures
(skirting, sockets, lights, …) are the **harness's** job (a later optimization stage),
not part of the room definition.

## Known limitations / TODO
- **Static `object.py` is currently a pass-through** (it just re-exports the mesh). It
  should additionally **drop floating fragments** (keep the largest connected component)
  and **fix orientation** (canonical facing) — this would fix bad TRELLIS chairs like
  `ChairCluster1` that land sunk into the floor or face the wrong way.
- A static object's neural-mesh `.glb` stays in the definition (no code to rebuild it).
- Camera poses still come from the original scan frames, not yet text in the definition.
