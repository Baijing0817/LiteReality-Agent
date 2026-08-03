# image_selection — the three-layer reference image selection (locked in)

Pick, once per scan, the reference images the harness should look at — **before** any
harness stage runs. Same locked-in principle across all layers: rank a view by how well
the target **fills the frame (size) × is centred × is visible**, then take the best few.

## The three layers

| Layer | Tool here | Locked-in scorer | What it selects |
|-------|-----------|------------------|-----------------|
| **ROOM** | (via `select_references`) | `authoring/views/room_render/select_views.py` → `quality()` | minimal set of views covering the whole room |
| **WALLS** | `surface_views.py` | this file + `stitch_wall` | per wall/floor/ceiling: **rectified mosaic** (room_pipeline) + **sharp boxed real frames** + **coverage% / blurry** notices; skips tiny walls; reports surfaces never captured |
| **OBJECTS** | `object_views.py` | `object_init/.../extract_image.py` → `object_view_quality()` (furniture); `object_init/opening_references.py` (openings) | per furniture: bbox-overlaid top-4; per opening (door/window): projected-3D-box top-4 |

The scorers (`object_view_quality`, `opening_references`, `select_views.quality`) are the
**locked-in methods and stay where they are** — this package only orchestrates them and
renders the references. If you tune one, keep the three consistent (same size×centred×vis idea).

## Run

```bash
# one scan, all three layers -> references.json + per-layer sheets
python -m litereality_agent.authoring.views.image_selection.select_references <scan> \
    --stitch <room_pipeline stitch_output dir>      # adds the rectified wall mosaics
    --room-manifest <render_manifest.json>          # enables the ROOM layer (needs a built scene)

# individual layers
python -m litereality_agent.authoring.views.image_selection.surface_views <scan> --stitch <dir>
python -m litereality_agent.authoring.views.image_selection.object_views   <scan>
```

The wall mosaics come from `room_pipeline.py` (RoomPlan scan → rectified per-surface stitch):
```bash
python room_pipeline.py scans_uploaded/<scan> --out <dir> --ppm 180 --max-frames 80
```

## Output (`references.json`)

```
room:    { views: [frame_…], note }
walls:   [ { name, kind, rectified_stitch, coverage_pct, blurry, low_coverage, images:[{frame,sharp,blurry}] } ]
objects: [ { name, kind: furniture|opening, method, frames:[{frame_id, rank, box}] } ]
```

The harness reads this fixed selection instead of re-selecting each stage → consistent
references across stages **and a measurable score** (fixed verification views).

## surface_compare/ — render vs real-stitch (verification)

A separate, deterministic tool that renders each wall/floor/ceiling of a BUILT room head-on and
pairs it with its room_pipeline stitch (`RENDER | REAL`), for stage-2 verification:
```bash
python -m litereality_agent.authoring.views.image_selection.surface_compare.run <scan>
```
See `surface_compare/README.md` for the geometry (Z-up planes, wall=group+PCA normal,
floor/ceiling oriented from room_pipeline's `dominant_room_axis`, flip flags).
