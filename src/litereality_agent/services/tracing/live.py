"""live_log.py — stream harness events to a JSONL file the live web page polls.

Enabled when $LR_LIVE_EVENTS is set (closed_stage sets it to
run/<scan>/scene_init/scene_stage/closed_harness/live_events.jsonl). Every event is one JSON line:
  {t: epoch seconds, type: run_start|iteration_start|stage_prompt|text|tool_call|tool_result|
   final_views|iteration_done, ...}
Image paths are rewritten repo-relative so a plain `python3 -m http.server` from the repo root can
serve them to the page (viewer/harness_live.html).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from litereality_agent import REPO_ROOT as _ROOT  # log paths are shown relative to the checkout


def _rel(p) -> str:
    try:
        return str(Path(p).resolve().relative_to(_ROOT))
    except Exception:  # noqa: BLE001
        return str(p)


def _relify(v):
    if isinstance(v, str) and ("/run/" in v or v.startswith(str(_ROOT))):
        return _rel(v)
    if isinstance(v, list):
        return [_relify(x) for x in v]
    if isinstance(v, dict):
        return {k: _relify(x) for k, x in v.items()}
    return v


def path() -> Path | None:
    p = os.environ.get("LR_LIVE_EVENTS", "").strip()
    return Path(p) if p else None


def emit(event: dict) -> None:
    """Append one event; never raises (live view is an aid, not a dependency)."""
    p = path()
    if not p:
        return
    try:
        event = {"t": round(time.time(), 2), **_relify(event)}
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception:  # noqa: BLE001
        pass


def reset(meta: dict) -> None:
    """Start a fresh stream (truncate) with a run_start event."""
    p = path()
    if not p:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
    except Exception:  # noqa: BLE001
        return
    emit({"type": "run_start", **meta})
