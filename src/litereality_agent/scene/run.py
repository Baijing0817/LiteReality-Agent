#!/usr/bin/env python3
"""run.py — one command: generated GLBs + RoomPlan scan -> blank room.glb.

Runs pack_assets.py (gather a scan's GLBs into <assets>/) then build_room.py
inside Blender (assemble the blank scene). This is the whole "assembly layer".

    python integration/run.py --scan office-elliott
    python integration/run.py --scan tea_room --out output/tea_room/room.glb
    python integration/run.py --glb-dir /path/to/glbs --scan-dir /path/to/scan

Blender is found via $BLENDER, else a couple of known locations. The scan dir
(room.usdz + frame_*) is resolved from --scan-dir, else scans_uploaded/<scan>,
else input/<scan>.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

try:
    from . import config, pack_assets
except ImportError:  # run as a plain script
    import config
    import pack_assets  # type: ignore

HERE = Path(__file__).resolve().parent


def find_blender() -> str:
    """Delegates to the one resolver in integration.config — see the note there about the six
    copies that disagreed about macOS."""
    from litereality_agent.scene.paths import find_blender as _canonical

    return _canonical()

def resolve_scan_dir(scan: str | None, scan_dir: str | None) -> Path:
    if scan_dir:
        return Path(scan_dir)
    cand = config.resolve_scan_dir(scan)
    if (cand / "room.usdz").exists() or (cand / "roomplan" / "room.usdz").exists():
        return cand
    sys.exit(f"no room.usdz for scan '{scan}'. Pass --scan-dir explicitly.")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--scan", help="scan name (e.g. office-elliott)")
    ap.add_argument(
        "--glb-dir", help="pack a flat folder of prim-named GLBs instead of the reconstruct tree"
    )
    ap.add_argument(
        "--scan-dir", help="explicit scan dir (room.usdz + frame_*); overrides --scan lookup"
    )
    ap.add_argument("--assets", help="assets dir (default run/<scan>/room/_assets)")
    ap.add_argument("--out", help="output Room.glb (default run/<scan>/room_preview/Room.glb)")
    ap.add_argument("--skip-pack", action="store_true", help="reuse existing <assets>/, only build")
    args = ap.parse_args()
    if not args.scan and not (args.glb_dir and args.scan_dir):
        ap.error("give --scan, or both --glb-dir and --scan-dir")

    scene = config.scan_name(args.scan) if args.scan else Path(args.scan_dir).name
    if args.scan:
        args.scan = scene
    blender = find_blender()
    scan_dir = resolve_scan_dir(args.scan, args.scan_dir)
    assets = Path(args.assets) if args.assets else config.assets_dir(scene)
    out = Path(args.out) if args.out else config.room_preview_dir(scene) / "Room.glb"
    out.parent.mkdir(parents=True, exist_ok=True)

    # 1. pack (in-process)
    if not args.skip_pack:
        print("=== pack_assets ===")
        pack_assets.pack(scan=args.scan, glb_dir=args.glb_dir, out=assets)

    # 2. build
    print("\n=== build_room (blender) ===")
    build = [
        blender,
        "-b",
        "--python",
        str(HERE / "compile" / "build_room.py"),
        "--",
        str(scan_dir),
        str(assets),
        str(out),
    ]
    subprocess.run(build, check=True)
    print(f"\nRoom.glb    -> {out}")
    print(f"room_layout -> {out.with_name('room_layout.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
