"""adopt_stranded_glbs.py — recover objects whose GLB was built but never packaged.

When the articulated agent dies mid-run — a network drop is the usual cause — it can leave a
valid, fully-textured `<name>.glb` in `reconstructed_objs/<name>/` while never writing the
`object.py` that the assembler actually runs. `build_from_room` then prints "missing object.py",
produces no `room_preview/Object/<name>.glb`, and `export_room` drops the object's box with
"dropped N empty object box(es) (no GLB generated)". The geometry is sitting on disk and the room
still ships empty.

This wraps each stranded GLB in the standard STATIC `object.py` interface (import the mesh, export
it) so the assembler treats it like any other asset — the same interface `Objects/Static/*` already
uses for neural/scanned meshes.

Two guards, because a half-written asset is worse than a missing one:
  · the GLB must parse and contain at least one mesh
  · every texture must be embedded — a GLB with external image URIs would lose them once the
    assembler runs it from a different directory

Tradeoff: the adopted object is frozen geometry, where a procedural object normally stays editable
as build code. Re-run the agent for any object you want editable again.

    .venv/bin/python scripts/ops/adopt_stranded_glbs.py <scan>            # report only
    .venv/bin/python scripts/ops/adopt_stranded_glbs.py <scan> --apply    # write
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import sys
from pathlib import Path

from litereality_agent import REPO_ROOT as REPO

FINAL = Path(os.environ.get("LITEREALITY_FINAL") or (REPO / "run"))

STATIC_OBJECT_PY = '''"""{name} — static object (mesh source, standard object.py interface).

ADOPTED: the articulated agent built this mesh but died before writing its object.py (see
scripts/ops/adopt_stranded_glbs.py). The geometry is the agent's own output, frozen — there is no
procedural build code for it. Re-run the agent for this object to get editable code back.

Run:
  blender -b --python object.py                       # ./{name}.glb -> ./{name}_built.glb
  blender -b --python object.py -- <texdir> <out.glb>
"""
import bpy, os, sys

HERE = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
_argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
SRC = os.path.join(HERE, "{name}.glb")                      # source mesh (textures embedded)
OUT = _argv[1] if len(_argv) > 1 else os.path.join(HERE, "{name}_built.glb")


def build(out_glb=OUT):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=SRC)
    bpy.ops.object.select_all(action="SELECT")
    os.makedirs(os.path.dirname(out_glb) or ".", exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=out_glb, export_format="GLB",
                              use_selection=True, export_apply=True)
    print(f"[static/adopted] {name} -> {{out_glb}}")
    return out_glb


if __name__ == "__main__":
    build()
'''

OBJECT_MD = """# {name} (adopted static asset)

The articulated agent produced this mesh but not its `object.py` — the run was interrupted after
the geometry was built. `scripts/ops/adopt_stranded_glbs.py` wrapped `{name}.glb` in the standard
static interface so the assembler can place it.

- source: `{src}`
- meshes: {meshes}, embedded textures: {images}
- geometry is FROZEN (no procedural build code); re-run the agent to make it editable again
"""


def glb_info(path: Path) -> dict:
    """Parse a GLB's JSON chunk: mesh count, and whether any image is an external URI."""
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"glTF":
        raise ValueError("not a GLB")
    total = struct.unpack("<III", data[:12])[2]
    off, js = 12, None
    while off < total:
        clen, ctype = struct.unpack("<II", data[off:off + 8])
        if ctype == 0x4E4F534A:  # 'JSON'
            js = json.loads(data[off + 8:off + 8 + clen].decode("utf-8"))
        off += 8 + clen
    if js is None:
        raise ValueError("no JSON chunk")
    images = js.get("images", [])
    return {
        "meshes": len(js.get("meshes", [])),
        "images": len(images),
        "external": [i["uri"] for i in images if i.get("uri")],
    }


def room_dirs(scan: str) -> list[Path]:
    """Every authored room for the scan (`_oneshot`, `_oneshot_<tag>`, …)."""
    return sorted((FINAL / scan / "scene_init" / "scene_stage").glob("_oneshot*/room"))


def find_stranded(scan: str, room: Path) -> list[tuple[str, Path, Path]]:
    """(name, built_glb, obj_dir) for objects with a GLB but no object.py in the room tree."""
    recon = FINAL / scan / "scene_init" / "obj_stage" / "reconstructed_objs"
    out = []
    for glb in sorted(recon.glob("*/*.glb")):
        name = glb.stem
        if glb.parent.name != name:
            continue
        for sub in ("Procedural", "Static"):
            d = room / "Objects" / sub / name
            if d.is_dir():
                if not (d / "object.py").exists():
                    out.append((name, glb, d))
                break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan")
    ap.add_argument("--apply", action="store_true", help="write object.py + the glb (else report only)")
    ap.add_argument("--room", help="specific room dir (default: every _oneshot*/room for the scan)")
    a = ap.parse_args()

    rooms = [Path(a.room)] if a.room else room_dirs(a.scan)
    if not rooms:
        print(f"✗ no authored room under {FINAL / a.scan / 'scene_init' / 'scene_stage'}")
        return 2

    total_adopted = 0
    for room in rooms:
        stranded = find_stranded(a.scan, room)
        print(f"== {room} ==")
        if not stranded:
            print("  nothing stranded — every built GLB already has its object.py")
            continue
        for name, glb, obj_dir in stranded:
            try:
                info = glb_info(glb)
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ {name}: unreadable GLB ({exc}) — leaving alone")
                continue
            if info["meshes"] < 1:
                print(f"  ✗ {name}: GLB has no meshes — leaving alone")
                continue
            if info["external"]:
                print(f"  ✗ {name}: GLB references external images {info['external'][:2]} — leaving alone")
                continue
            print(f"  ✓ {name}: {info['meshes']} mesh(es), {info['images']} embedded texture(s)"
                  f"  {glb.stat().st_size // 1024} KB")
            if not a.apply:
                continue
            shutil.copy2(glb, obj_dir / f"{name}.glb")
            (obj_dir / "object.py").write_text(STATIC_OBJECT_PY.format(name=name), encoding="utf-8")
            (obj_dir / "object.md").write_text(
                OBJECT_MD.format(name=name, src=glb, meshes=info["meshes"], images=info["images"]),
                encoding="utf-8",
            )
            total_adopted += 1

    if not a.apply:
        print("\n(report only — re-run with --apply to write)")
        return 0
    print(f"\nadopted {total_adopted} object(s). Re-export to place them:")
    print(f"  ./report.sh {a.scan}   # or re-run stage 6 (export)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
