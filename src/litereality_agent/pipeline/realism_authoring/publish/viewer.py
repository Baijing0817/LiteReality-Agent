"""Gather the viewer's panel data from the RUN TREE, then hand it to the room-ops exporter.

The export itself is a room-ops capability and lives in `room_ops/viewer.py` — a GLB plus
panel data in, one HTML file out, with no idea where a run keeps its artifacts. Knowing where
they are is a PIPELINE concern, so the three collectors stay here: QC calls `pipeline.room_qc`
(which room_ops must not import), and the trace and comparison pairs are found by run layout.

    python -m litereality_agent.pipeline.realism_authoring.publish.viewer <Room.glb> <out.html> \
           ["Room label"] [--room=DIR] [--scan=NAME] [--compare=DIR]
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

from litereality_agent.room_ops.viewer import export_html


def collect_qc(room_dir: Path | None) -> dict:
    """Deterministic geometry QC for the room (no model). Returns {} when it can't run, so a
    missing layout degrades the panel rather than failing the export."""
    if not room_dir:
        return {}
    out: dict = {}
    try:
        from litereality_agent.pipeline.room_qc.checks import qc

        r = qc(str(room_dir))
        out = {
            "n_furniture": r.get("n_furniture", 0),
            "violations": [
                {"object": o, "check": c, "detail": d} for o, c, d in r.get("violations", [])
            ],
        }
    except Exception as e:  # noqa: BLE001
        out = {"error": f"{type(e).__name__}: {e}"}

    # Fold in the MESH collision map when one sits beside the room. Without this the panel reports
    # only the box-based positional checks and shows a clean tick on a room with known
    # interpenetration — a viewer that certifies a scene it never actually checked.
    try:
        maps = sorted(Path(room_dir).glob("collision_map*after*.json")) \
            or sorted(Path(room_dir).glob("collision_map*.json"))
        if maps:
            m = json.loads(maps[-1].read_text())
            out.setdefault("violations", [])
            out["n_mesh_checked"] = len(m.get("objects", []))
            for c in m.get("clashes", []):
                f = c.get("fix") or {}
                d = (f"{f['dist'] * 1000:.0f} mm — needs "
                     f"({f['dir'][0]:+.2f},{f['dir'][1]:+.2f})") if f else "no escape found"
                out["violations"].append({"object": f"{c['a']} × {c['b']}",
                                          "check": "mesh_clash", "detail": d})
            out.pop("error", None)
    except Exception:  # noqa: BLE001
        pass
    return out


def collect_trace(scan: str | None) -> list[dict]:
    """The run's event log as a list of dicts, oldest first. Looks in the same places the
    tracer writes to. Returns [] if the scan never traced."""
    if not scan:
        return []
    roots = []
    fin = os.environ.get("LITEREALITY_FINAL")
    out = os.environ.get("LITEREALITY_OUTPUT")
    from litereality_agent import REPO_ROOT as repo  # run/ lives here
    for base in (fin, out, repo / "run"):
        if not base:
            continue
        b = Path(base)
        for tdir in (b / scan / "scene_init" / "obj_stage" / "traces", b / scan / "traces"):
            roots.append(tdir / "trace.jsonl")
            # one file per authoring pass (author / materials / qc) — glob so a new pass is
            # picked up without touching this list, and so no pass can hide another.
            try:
                roots += sorted(tdir.glob("authoring_trace*.jsonl"))
            except Exception:  # noqa: BLE001, PERF203
                pass
    seen: set = set()
    out: list[dict] = []
    for p in roots:
        try:
            if not p.is_file() or p.resolve() in seen:
                continue
            seen.add(p.resolve())
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:  # noqa: BLE001, PERF203
                        pass
        except Exception:  # noqa: BLE001, PERF203
            continue
    # init events and the authoring loop are separate files; interleave by wall-clock so the
    # timeline reads as one run.
    out.sort(key=lambda e: e.get("t") or 0)
    return out


def collect_pairs(compare_dir: Path | None, max_pairs: int = 12) -> list[tuple[str, str]]:
    """Real-vs-render comparison pairs as (frame_label, jpeg data URI).

    The PNGs render_vs_capture writes are ~1.4 MB each; re-encoded to JPEG the whole set is well
    under a megabyte, which keeps the page self-contained without bloating it.
    """
    if not compare_dir:
        return []
    d = Path(compare_dir)
    src = d / "pairs" if (d / "pairs").is_dir() else d
    files = sorted(src.glob("pair_*.png")) + sorted(src.glob("pair_*.jpg"))
    if not files:
        return []
    out = []
    try:
        import io

        from PIL import Image
    except Exception:  # noqa: BLE001  (Pillow missing -> just skip the panel)
        return []
    for f in files[:max_pairs]:
        try:
            im = Image.open(f).convert("RGB")
            im.thumbnail((1400, 1400))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=78)
            uri = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
            out.append((f.stem.replace("pair_", "frame "), uri))
        except Exception:  # noqa: BLE001, PERF203
            continue
    return out


def main(argv) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in argv[1:] if a.startswith("--") and "=" in a}
    if len(args) < 2:
        print(__doc__)
        return 2
    qc = collect_qc(Path(opts["--room"]) if opts.get("--room") else None)
    trace = collect_trace(opts.get("--scan"))
    pairs = collect_pairs(Path(opts["--compare"]) if opts.get("--compare") else None)
    out = export_html(args[0], args[1], args[2] if len(args) > 2 else None,
                      qc=qc, trace=trace, pairs=pairs)
    mb = out.stat().st_size / 1024 / 1024
    nv = len(qc.get("violations", []))
    print(f"viewer → {out}  ({mb:.1f} MB, self-contained)")
    print(f"   panels: objects · QC ({nv} violation(s))"
          + (f" · compare ({len(pairs)} pairs)" if pairs else "")
          + (f" · trace ({len(trace)} events)" if trace else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
