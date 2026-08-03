"""select_references.py — the three-layer image-selection orchestrator.

Runs all three locked-in reference selectors for a scan and writes ONE references.json
(+ the per-layer contact sheets) that the harness can read instead of re-selecting each
stage. The three layers:

  ROOM    — select_views.py            minimal-cover views of the whole room
  WALLS   — surface_views.py           per wall/floor/ceiling: rectified mosaic + sharp
                                        boxed real frames + coverage% / blurry notices
  OBJECTS — object_views.py            per furniture: bbox top-4 (object_view_quality);
                                        per opening: projected-box top-4 (opening_references)

  python -m litereality_agent.room_format.rendering.image_selection.select_references <scan> \
         [--out DIR] [--stitch ROOM_PIPELINE_DIR] [--room-manifest render_manifest.json]

Notes
- WALLS uses the rectified mosaic when --stitch points at a room_pipeline stitch_output dir.
- ROOM runs select_views only when a render_manifest.json is available (it needs the built
  scene's per-view visibility); otherwise that layer is left empty and noted.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from litereality_agent import PACKAGE_ROOT
from litereality_agent import REPO_ROOT as ROOT

HERE = Path(__file__).resolve().parent
# the view picker is CODE (shipped with the package); scans_uploaded/ and .venv are the CHECKOUT
SELECT_VIEWS = PACKAGE_ROOT / "room_format" / "rendering" / "room_render" / "select_views.py"


def run(scan, out_dir, stitch_dir=None, room_manifest=None, output_root=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    refs = {"scan": scan, "room": {"views": [], "note": ""}, "walls": [], "objects": []}

    # --- WALLS (+ floor/ceiling) ---
    import importlib.util as u

    sv = u.module_from_spec(u.spec_from_file_location("surface_views", HERE / "surface_views.py"))
    u.spec_from_file_location("surface_views", HERE / "surface_views.py").loader.exec_module(sv)
    sv.run(scan, out_dir / "walls", Path(stitch_dir) if stitch_dir else None)
    wj = out_dir / "walls" / "surface_views.json"
    if wj.is_file():
        refs["walls"] = json.loads(wj.read_text()).get("surfaces", [])

    # --- OBJECTS + OPENINGS ---
    from . import object_views

    object_views.run(scan, out_dir / "objects", output_root)
    oj = out_dir / "objects" / "object_views.json"
    if oj.is_file():
        refs["objects"] = json.loads(oj.read_text()).get("objects", [])

    # --- ROOM (needs a built-scene render_manifest) ---
    if room_manifest and Path(room_manifest).is_file():
        import os

        env = dict(
            os.environ,
            SB_RENDER_DIR=str(Path(room_manifest).parent),
            SB_SCAN_DIR=str(ROOT / "scans_uploaded" / scan),
            SB_VIEW_OUT=str(out_dir),
        )
        r = subprocess.run(
            [str(ROOT / ".venv/bin/python"), str(SELECT_VIEWS), "8"],
            env=env,
            capture_output=True,
            text=True,
        )
        sel = [l for l in r.stdout.splitlines() if l.startswith("SELECTED")]
        if sel:
            refs["room"]["views"] = [f.strip() for f in sel[0].split(":", 1)[1].split(",")]
    else:
        refs["room"]["note"] = "no render_manifest supplied — run select_views on a built scene"

    (out_dir / "references.json").write_text(json.dumps(refs, indent=2))
    print(f"\n== references for {scan} ==")
    print(
        f"  room:    {len(refs['room']['views'])} views"
        + (f"  ({refs['room']['note']})" if refs["room"]["note"] else "")
    )
    print(f"  walls:   {len(refs['walls'])} surfaces")
    print(
        f"  objects: {sum(1 for o in refs['objects'] if o['kind'] == 'furniture')} furniture + "
        f"{sum(1 for o in refs['objects'] if o['kind'] == 'opening')} openings"
    )
    print(f"  -> {out_dir / 'references.json'}")
    return refs


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("scan")
    ap.add_argument("--out", default=None)
    ap.add_argument("--stitch", default=None, help="room_pipeline stitch_output dir (wall mosaics)")
    ap.add_argument("--room-manifest", default=None, help="render_manifest.json for select_views")
    a = ap.parse_args()
    run(a.scan, a.out or f"/tmp/claude-217658/scratchpad/refs_{a.scan}", a.stitch, a.room_manifest)
