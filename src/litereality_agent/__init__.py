"""litereality_agent — a room scan becomes an editable, realistic 3D program.

Two halves, joined by a folder: a deterministic **scene_init** seeds `Room.py` from a RoomPlan
scan, and an agentic **authoring** pass makes it look like the real room. The seam between them
is the scene package (`integration.manifest`) — a `scene.json` that describes what init produced,
so stage 2 launches from that folder alone.

Layers, in dependency order. Each depends only on the ones below it; nothing depends upward, and
every subpackage restates its own contract in its `__init__.py`.

    5  cli                the command line: `uv run -m litereality_agent <command>`  (everything)
    4  realism_authoring  STAGE 2, the AGENTIC half: author · refine · qc, the harness they run
                          in, the closed capability-tool set, and the imaging used to see the room
    3  scene_init         STAGE 1, the DETERMINISTIC half: scan → objects → seed Room.py + .glb
    2  integration    the Room PROGRAM: export Room.py, compile it to Room.glb, and the
                      scene-package manifest that ties a run's folder together
    1  models         one front door per model role: llm · vlm · detect · gen3d
    0  backends       heavy/external behind launchers: TRELLIS · GroundingDINO · procedural

`scripts/` sits outside the stack — standalone entry points, never imported.

## The two roots

Code and data live in different places, and conflating them is the classic src-layout bug:

    PACKAGE_ROOT   src/litereality_agent — where the CODE is. Use for anything shipped in the wheel:
                   a prompt template, a Blender helper script, a tool a subprocess must exec.
    REPO_ROOT      the checkout — where the DATA is: run/, scans_uploaded/,
                   .env, .key, run.sh. Override with $LR_REPO_ROOT when the package is installed
                   somewhere other than beside its data.

Reach for `REPO_ROOT` when you mean "where this user's scans and results live" and `PACKAGE_ROOT`
when you mean "where our own files are". They are the same directory in a source checkout, which
is exactly why the distinction has to be made deliberately rather than discovered later.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["PACKAGE_ROOT", "SRC_ROOT", "REPO_ROOT", "repo_root"]

PACKAGE_ROOT = Path(__file__).resolve().parent  # src/litereality_agent
SRC_ROOT = PACKAGE_ROOT.parent  # src


def repo_root() -> Path:
    """The checkout holding run/ · scans_uploaded/ · .env.

    Resolved fresh on each call so `$LR_REPO_ROOT` can be set after import (the launchers and
    Blender subprocesses set it on the way in). `REPO_ROOT` below is the import-time snapshot,
    which is what almost every call site wants.
    """
    env = os.environ.get("LR_REPO_ROOT")
    return Path(env).expanduser().resolve() if env else SRC_ROOT.parent


REPO_ROOT = repo_root()
