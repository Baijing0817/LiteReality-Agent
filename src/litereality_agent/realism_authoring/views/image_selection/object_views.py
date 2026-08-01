"""object_views.py — per-object reference frames (layer 3 of the image-selection package).

Gathers the locked-in object selections that object_init already computed and renders them
as bbox-overlaid full frames + a manifest:

  - FURNITURE: ranked top-k frames by `object_view_quality` (size x centredness x visibility),
    the 2D box from `bbox_info.json`.  → green box.
  - OPENINGS (doors/windows): ranked by `opening_references` (projected 3D opening box,
    visible-corners + sharpness), the box from each opening's `crops_meta.json`. → blue box.

The scorers are the locked-in methods and live elsewhere (not duplicated here):
  - object_view_quality:  litereality_agent/pipeline/object_init/lr_preprocessing/utils/extract_image.py
  - opening_references:    litereality_agent/pipeline/object_init/opening_references.py
This module only READS their outputs under run/<scan>/scene_init/obj_stage/object_init/ and presents them.

  python -m litereality_agent.realism_authoring.views.image_selection.object_views <scan>   # -> sheet + manifest
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from litereality_agent import REPO_ROOT as ROOT  # run/ and scans_uploaded/ live here
from litereality_agent.fonts import font as _shared_font

TOPK = 4
GREEN, BLUE = (90, 255, 120), (120, 180, 255)


def _font(s):
    try:
        return _shared_font(s)
    except Exception:
        return ImageFont.load_default()


FONT, HF = _font(26), _font(36)


def _paths(scan, output_root=None):
    out = Path(output_root) if output_root else ROOT / "run"
    base = out / scan / "scene_init" / "obj_stage" / "object_init"
    return (
        base / "input" / "object_stage" / scan,
        base / "input" / "parsed_images" / scan,
        base / "opening_refs" / scan,
        ROOT / "scans_uploaded" / scan,
    )


def gather(scan, output_root=None):
    """Return the per-object/opening selected frames + boxes (locked-in selections)."""
    obj_dir, parsed_dir, open_dir, _ = _paths(scan, output_root)
    items = []
    if obj_dir.is_dir():
        for d in sorted(obj_dir.iterdir()):
            if not (d / "bbox_info.json").is_file() or re.search(r"_(Door|Window)_", d.name):
                continue  # openings handled below
            pdir = parsed_dir / d.name
            crops = (
                sorted(
                    pdir.glob("frame_*_ranking_*.jpg"),
                    key=lambda p: int(re.search(r"ranking_(\d+)", p.name).group(1)),
                )
                if pdir.is_dir()
                else []
            )
            if not crops:
                continue
            bi = json.loads((d / "bbox_info.json").read_text())
            frames = []
            for cp in crops[:TOPK]:
                fid = int(re.search(r"frame_(\d+)_ranking", cp.name).group(1))
                rk = int(re.search(r"ranking_(\d+)", cp.name).group(1))
                box = bi.get(f"frame_{fid}")
                if box:
                    frames.append({"frame_id": fid, "rank": rk, "box": [float(b) for b in box]})
            if frames:
                items.append(
                    {
                        "name": d.name,
                        "kind": "furniture",
                        "method": "object_view_quality",
                        "frames": frames,
                    }
                )
    if open_dir.is_dir():
        for d in sorted(open_dir.iterdir()):
            cm = d / "crops_meta.json"
            if not cm.is_file():
                continue
            meta = json.loads(cm.read_text())[:TOPK]
            frames = [
                {"frame_id": int(m["frame_id"]), "rank": i, "box": [float(b) for b in m["box"]]}
                for i, m in enumerate(meta)
                if m.get("box") is not None
            ]
            if frames:
                items.append(
                    {
                        "name": d.name,
                        "kind": "opening",
                        "method": "opening_references",
                        "frames": frames,
                    }
                )
    return items


def _tile(scan_dir, fid, box, rank, col):
    fp = scan_dir / f"frame_{fid:05d}.jpg"
    if not fp.exists():
        return None
    im = Image.open(fp).convert("RGB")
    ImageDraw.Draw(im).rectangle(box, outline=col, width=8)
    out = im.transpose(Image.Transpose.ROTATE_270)
    out = out.resize((300, int(300 * out.height / out.width)))
    d = ImageDraw.Draw(out)
    d.rectangle((0, 0, 300, 30), fill=(0, 0, 0))
    d.text((4, 3), f"#{rank} frame_{fid:05d}", fill=col, font=FONT)
    return out


def build_sheet(scan, items, out_path, output_root=None):
    _, _, _, scan_dir = _paths(scan, output_root)
    rows = []
    for it in items:
        col = GREEN if it["kind"] == "furniture" else BLUE
        tiles = [
            t
            for t in (
                _tile(scan_dir, f["frame_id"], f["box"], f["rank"], col) for f in it["frames"]
            )
            if t
        ]
        if not tiles:
            continue
        h = max(t.height for t in tiles)
        row = Image.new("RGB", (300 * TOPK + 5 * (TOPK + 1), h + 8 + 46), (8, 10, 14))
        dh = ImageDraw.Draw(row)
        dh.rectangle((0, 0, row.width, 46), fill=(34, 40, 52))
        dh.text(
            (10, 5),
            f"{it['name']}  —  {it['kind']} · top {len(tiles)} ({it['method']})",
            fill=(255, 220, 150),
            font=HF,
        )
        for i, t in enumerate(tiles):
            row.paste(t, (5 + i * 305, 50))
        rows.append(row)
    if not rows:
        return None
    W = max(r.width for r in rows)
    sh = Image.new("RGB", (W, sum(r.height for r in rows) + 6 * (len(rows) + 1)), (8, 10, 14))
    y = 6
    for r in rows:
        sh.paste(r, (0, y))
        y += r.height + 6
    sh.save(out_path, quality=90)
    return out_path


def run(scan, out_dir, output_root=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    items = gather(scan, output_root)
    (out_dir / "object_views.json").write_text(
        json.dumps({"scan": scan, "objects": items}, indent=2)
    )
    sheet = build_sheet(scan, items, out_dir / "object_views_sheet.jpg", output_root)
    nf = sum(1 for i in items if i["kind"] == "furniture")
    no = sum(1 for i in items if i["kind"] == "opening")
    print(
        f"{scan}: {nf} furniture + {no} openings -> {out_dir / 'object_views.json'}"
        + (f"\nSHEET -> {sheet}" if sheet else "")
    )
    return items


if __name__ == "__main__":
    s = sys.argv[1]
    run(s, sys.argv[2] if len(sys.argv) > 2 else f"/tmp/claude-217658/scratchpad/objsel_{s}")
