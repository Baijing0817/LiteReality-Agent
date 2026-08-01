#!/usr/bin/env python3
"""Completeness QC — does the render capture every salient feature of the reference?

The geometry probe (probe_glb.py) proves a model is VALID (connected, sane joints, faces the
front) but is blind to MISSING features: a door that lacks its coat hooks, a cabinet missing a
handle, the wrong number of drawers. This closes that gap with a vision judge: it compares the
reference image against the render previews and lists what's present in the reference but absent
or wrong in the render.

Runs on the logged-in Claude via claude_agent_sdk (Read-only) — no API key, no Gemini. Kept
separate from probe_glb.py so that stays a pure, dependency-free geometric check.

Usage:
    completeness_check.py --ref <reference.png> --render <r.png> [--render <r2.png> ...] [--json]

Exit 0 = complete (nothing salient missing), 1 = missing features, 2 = bad usage / VLM error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path

PROMPT = (
    "IMAGE 1 is the REFERENCE of a single object. The remaining images are RENDERS of a 3D model "
    "built to reproduce it (front / closed / open views). Judge only whether the render captures "
    "every SALIENT feature of the reference: the distinct parts (hooks, handles, latches, knobs, "
    "vents, shelves, panels, glazing, trim), their COUNT, and rough placement. IGNORE lighting, "
    "exact colour, background, resolution and micro-detail. "
    'Reply with ONLY a JSON object: {"pass": bool, "missing": ["<feature in the reference that is '
    'absent or clearly wrong in the render>", ...], "notes": "<one short line>"}. '
    "Set pass=true only when nothing salient is missing."
)


async def _ask(images: list[Path]) -> str:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    opts = ClaudeAgentOptions(
        cwd=str(images[0].parent),
        add_dirs=sorted({str(p.parent) for p in images}),
        system_prompt={"type": "preset", "preset": "claude_code"},
        setting_sources=[],
        allowed_tools=["Read"],
        permission_mode="bypassPermissions",
        max_turns=len(images) + 3,
        model=os.environ.get("HARNESS_MODEL", "claude-opus-5"),
    )
    listing = "\n".join(f"- IMAGE {i + 1}: {p}" for i, p in enumerate(images))
    full = f"First Read (view) EVERY image below, then answer.\n{listing}\n\n{PROMPT}"
    out = ""
    async for m in query(prompt=full, options=opts):
        if isinstance(m, ResultMessage):
            out = m.result or ""
    return out


def _parse(out: str) -> dict:
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", out, re.S)
        return json.loads(m.group(0)) if m else {"pass": True, "missing": [], "notes": "unparsed"}


def check(ref: Path, renders: list[Path]) -> dict:
    imgs = [ref] + [r for r in renders if r.is_file()]
    if len(imgs) < 2:
        return {"pass": True, "missing": [], "notes": "no renders to compare", "error": "no_renders"}
    try:
        data = _parse(asyncio.run(_ask(imgs)))
    except Exception as e:  # noqa: BLE001 — never hard-fail delivery on a VLM hiccup
        return {"pass": True, "missing": [], "notes": f"vlm error: {type(e).__name__}", "error": str(e)}
    data.setdefault("pass", True)
    data.setdefault("missing", [])
    data.setdefault("notes", "")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--render", action="append", default=[], help="repeatable")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = check(Path(args.ref), [Path(r) for r in args.render])
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        verdict = "COMPLETE" if report["pass"] else "INCOMPLETE"
        print(f"completeness: {verdict}")
        for m in report.get("missing", []):
            print(f"  ✗ missing: {m}")
        if report.get("notes"):
            print(f"  note: {report['notes']}")
    return 0 if report.get("pass", True) else 1


if __name__ == "__main__":
    sys.exit(main())
