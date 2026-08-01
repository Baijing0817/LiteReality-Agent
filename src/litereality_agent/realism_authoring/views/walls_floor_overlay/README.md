# walls_floor_overlay

Project the Apple RoomPlan / LiteReality parametric room — **walls, floor, doors,
windows** from `room.usdz` — directly onto the captured `frame_*.jpg` photos,
using each frame's recorded camera pose + intrinsics. Writes annotated overlay
images plus a per-frame JSON manifest of what is visible.

It's the fast way to **read the layout on the photos** and to **sanity-check the
camera poses/intrinsics** (if walls land on walls, the data is good). Pure Python
— `numpy` + `Pillow` only. **No Blender, no GPU, no MCP.**

## Install

```bash
python3 -m pip install -r requirements.txt        # numpy, Pillow
# or isolated:
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```

## Generate the two sets (recommended)

Always produce **both** views of the same scan:

```bash
SCAN=/ABS/PATH/to/scan_folder        # contains room.usdz + frame_*.json + frame_*.jpg

# Set A — FILLED: translucent highlight boxes (each wall a solid-ish colour patch)
python3 overlay_roomplan.py "$SCAN" \
  --output "$SCAN/overlays/filled" \
  --style colored --labels

# Set B — TRANSPARENT MIDDLE: outline only, so you see the real wall through the box
python3 overlay_roomplan.py "$SCAN" \
  --output "$SCAN/overlays/outline" \
  --style colored --labels --outline-only
```

The only difference is **`--outline-only`** on Set B: it drops the translucent
fill and draws just the coloured boundary + label for each wall (and traces the
floor outline by ray-casting the floor plane). Set B is the one for inspecting
what the wall surfaces actually look like; Set A is the one for seeing each
wall's full extent at a glance.

Each run writes:
- `<output>/frame_NNNNN_overlay.jpg` — one annotated image per keyframe.
- `<output>/overlay_manifest.json` — per-frame list of visible
  walls/floor/doors/windows + run settings + totals, including per-wall coverage
  percentages (see below).

### Surface coverage percentage (manifest only)

For every image the **manifest** records, per visible **wall, floor and ceiling**,
the **percentage of the image area that surface covers**. This is data in the
JSON only — it is *not* drawn on the overlay images:

```jsonc
// one entry in overlay_manifest.json -> "images"
{
  "output_image": ".../frame_00004_overlay.jpg",
  "visible_walls": ["Wall0", "Wall5"],
  "wall_coverage_pct":    { "Wall0": 41.2, "Wall5": 12.0 },  // % of the image
  "visible_floors": ["Floor0"],
  "floor_coverage_pct":   { "Floor0": 3.1 },
  "visible_ceilings": ["Ceiling0"],
  "ceiling_coverage_pct": { "Ceiling0": 25.2 },
  ...
}
```

Each element in `visible_elements` also carries its own `image_coverage_pct`. The
percentage is the wall's projected footprint (convex hull, clipped to the image)
over the image area, so it's a good "is this a strong frame for this wall?"
signal — a wall at e.g. 60%+ fills the shot and is a good frame to read or
texture it from; ~0% means it's only edge-on or a sliver at the border. It is
style-independent (same in the filled and outline sets) and unaffected by the
auto-rotation (rotation preserves area).

## What gets drawn

`room.usdz` is parsed in-process (a usdz is a zip of `.usda` text):

| Element | Colour (`colored` style) | Notes |
|---|---|---|
| Walls `Wall0…` | stable per-wall palette | filled patch (Set A) or outline (Set B) |
| Floor `Floor0` | cyan | traced as a boundary line + labelled in **both** sets (ray-cast against the floor plane, so it's found even when the floor runs behind the camera) |
| Ceiling `Ceiling0` | purple | **derived** — RoomPlan exports no ceiling, so it's the floor outline raised to wall height; traced + labelled like the floor (boundary = where ceiling meets the walls) |
| Doors | green, dotted | labelled `Door0@Wall1` (keeps parent wall) |
| Windows | blue, dotted | labelled `Window0@Wall5` |

## Options (`--help` for the full list)

| Flag | Default | Effect |
|---|---|---|
| `--style {clean,colored,wireframe}` | `clean` | `colored` = stable per-wall colour + centred label (best for reading layout). |
| `--labels` | off | Draw element labels. |
| `--outline-only` | off | **Transparent middle** — outlines + labels, no fill (Set B). |
| `--no-rotate-clockwise` | off | Output is rotated 90° CW **by default** so portrait-held captures look upright; pass this to keep the raw landscape sensor frame instead. |
| `--no-opening-highlights` | on | Stop the dotted door/window outlines. |
| `--no-panel` | on | Hide the top-left "Visible RoomPlan Elements" box. |
| `--line-width N` | `5` | Outline width (px). |
| `--label-font-size N` | `48` | Label size (px). |
| `--limit N` | all | Only the first N frames (quick preview). |
| `--usdz PATH` | `<scan>/room.usdz` | Override USDZ path (e.g. `roomplan/room.usdz`). |
| `--output DIR` | `<scan>/overlays` | Output folder. |

## Verifying it worked

Open any **sharp** frame's overlay (early frames are often motion-blurred; pick
one with `motionQuality: 1` in its `frame_*.json`). Coloured wall outlines should
sit on the real walls and the labels on the right surfaces. If they don't, the
pose/intrinsics for that scan are off — fix the data, not the overlay.

## Orientation note

The phone is held in **portrait** but ARKit stores the **landscape** sensor
image, so the raw frames are "sideways." All the projection math runs in that
landscape frame (intrinsics, pose, and jpg are self-consistent there); the
output is then rotated 90° CW **by default** so the saved picture is upright for
a human. The rotation only affects the saved image and label placement, never
the projection. Pass `--no-rotate-clockwise` if you want the raw landscape frame
(e.g. to compare 1:1 against the original `frame_*.jpg`).

## Input folder expectations

`scan_folder` must contain `room.usdz` and matched `frame_NNNNN.json` +
`frame_NNNNN.jpg` pairs (jpgs are also found under `images/` if not beside the
JSONs). The per-frame JSON provides `intrinsics` (3×3) and `cameraPoseARFrame`
(4×4 camera→world, ARKit world frame).
