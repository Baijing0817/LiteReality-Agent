"""merge_objects.py — CLI over the box merge, for repairing a scan AFTER init already ran.

The merge itself is no longer manual: `scene_init/object_init/run.py` calls
`scene_init.object_init.merge_boxes.merge_for_scan` between extract and crop on every run, so a fresh
scan gets its counter runs fused automatically ($LR_BOX_MERGE=0 opts out). This script exists for
the cases that automation can't cover:

  · a scan whose init predates the automatic merge and you don't want to re-run from scratch
  · overriding the auto-detection with explicit groups the overlap heuristic gets wrong

Both algorithm and file writes live in `scene_init/object_init/merge_boxes.py` — this file is argument
parsing only, so the manual path and the pipeline path can never drift apart.

    .venv/bin/python scripts/ops/merge_objects.py <scan> --auto            # propose (dry run)
    .venv/bin/python scripts/ops/merge_objects.py <scan> --auto --apply    # write
    .venv/bin/python scripts/ops/merge_objects.py <scan> --apply \
        --group "Sink_Storage0=Storage1,Sink0,Sink1" --group "Hob_Storage0=Storage3,Oven1,Stove0"

After applying to an already-cropped scan, the crop/reference/reconstruct steps must be re-run for
the merged ids with the printed LR_ENLARGED_CROP_OBJECTS exported — the existing crops are of the
old separate boxes.
"""

from __future__ import annotations

import argparse
import pickle
import sys

from litereality_agent import REPO_ROOT as REPO
sys.path.insert(0, str(REPO))

from litereality_agent.pipeline import paths as config  # noqa: E402
from litereality_agent.pipeline.stages.ingest import merge_boxes  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scan")
    ap.add_argument("--group", action="append", default=[], help='"MergedName=Member1,Member2,..."')
    ap.add_argument("--auto", action="store_true", help="auto-detect overlapping same-yaw counter runs")
    ap.add_argument("--thresh", type=float, default=merge_boxes.DEFAULT_THRESH,
                    help=f"min footprint-overlap ratio to auto-merge (default {merge_boxes.DEFAULT_THRESH})")
    ap.add_argument("--apply", action="store_true", help="write objects.pkl (otherwise dry-run)")
    a = ap.parse_args()

    config.set_scan(a.scan)
    pkl = config.scene_data_dir(a.scan) / "objects.pkl"
    if not pkl.is_file():
        print(f"✗ no objects.pkl at {pkl}")
        return 2
    objs = pickle.load(open(pkl, "rb"))
    present = {o["object_type"] for o in objs}

    groups: dict[str, list[str]] = {}
    for g in a.group:
        name, members = g.split("=", 1)
        groups[name.strip()] = [m.strip() for m in members.split(",") if m.strip()]
    if a.auto:
        for mem in merge_boxes.auto_groups(objs, a.thresh):
            groups.setdefault(merge_boxes.name_for(mem, present | set(groups)), mem)
    if not groups:
        print("no groups (use --group or --auto)")
        return 2

    print(f"== merge groups for {a.scan} ==")
    for name, mem in groups.items():
        miss = [m for m in mem if m not in present]
        print(f"  {name} <- {mem}" + (f"   ⚠ MISSING {miss}" if miss else ""))
    if not a.apply:
        print("\n(dry run — re-run with --apply to write)")
        return 0

    res = merge_boxes.apply_merges(pkl, config.object_refs_root() / a.scan, groups)
    for name, mem in res["merged"].items():
        print(f"  ✓ {name} <- {', '.join(mem)}")
    for name, why in res["skipped"].items():
        print(f"  ! {name}: {why}")
    if not res["merged"]:
        print("\nnothing merged — objects.pkl untouched")
        return 1
    print(f"\nobjects.pkl rewritten (backup: {pkl.with_suffix('.pkl.bak')})")
    print(f"\nexport before the crop/reference re-run:\n"
          f"  LR_ENLARGED_CROP_OBJECTS={','.join(sorted(res['merged']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
