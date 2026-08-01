"""Paths, working-tree layout, and secrets for object_init — the single source of truth.

**Everything object_init (and the reconstruction it launches) produces lands under
one repo-level output tree**, grouped per scan, so nothing is scattered into random
folders:

    <repo>/run/<scan>/scene_init/obj_stage/
        object_init/                       # this stage's working tree (CWD-relative)
            input/usdz_files/<scan>.usdz
            input/scan_geometry/<scan>/scene_points.obj
            input/rgbd/<scan>/{image,depth,intrinsic,extrinsic,...}
            input/scene_data/<scan>/{walls,objects,wall_holes,floor}.pkl
            input/parsed_images/<scan>/<Object>/frame_*_ranking_*.jpg   # the crops
            object_refs/<scan>/<Object>/{input2imagegen.jpg,clean_obj_reference.png,reference_1024.png}
            chair_clusters/<scan>/{chair_clusters.json, nano_banana/, ...}
            opening_refs/<scan>/<Wall_Door/Window>/{crops/,reference_1024.png}
            object_init_summary.json
        reconstructed_objs/                # GLBs the launcher generates from the refs
            <Object>.glb, <ChairCluster>.glb
        traces/                            # process log for later visualization
            trace.jsonl, gemini/, agent/
        manifest.json                      # per-scan roll-up of everything above

(The room-build half lands in a sibling ``scene_stage/`` — see integration.config.)

Override the output root with ``--output-root`` / ``$LITEREALITY_OUTPUT``.

The ported preprocessing (``lr_preprocessing/``) uses **relative** ``input/...``
paths, so the stages that drive it ``chdir`` into the per-scan work root first
(:func:`enter_work_root`). The reference/cluster stages use the absolute helpers
below. Because the work root is per-scan, callers must select the scan with
:func:`set_scan` (``enter_work_root(scan)`` does this) before using the helpers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from litereality_agent import (
    REPO_ROOT,  # the CHECKOUT: scans_uploaded/, output/, .key ($LR_REPO_ROOT)
)

OBJECT_INIT_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = OBJECT_INIT_DIR.parent  # = scene_init/  (kept for back-compat refs)
AGENT_DIR = REPO_ROOT
LR_PREPROC_DIR = OBJECT_INIT_DIR / "extract" / "lr_preprocessing"

# Raw RoomPlan scans. Defaults to <repo>/scans_uploaded; point at the old repo (or anywhere)
# via $LR_SCANS_DIR so init can run on existing scan data without copying it.
SCANS_ROOT = Path(os.environ.get("LR_SCANS_DIR") or (REPO_ROOT / "scans_uploaded")).resolve()

# Optional extra secrets file (KEY=value lines). Point $LR_STUDIO_KEYS at one to use it.
_studio_keys = os.environ.get("LR_STUDIO_KEYS")
STUDIO_KEYS_FILE = Path(_studio_keys) if _studio_keys else None

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash-image"

# The scan whose per-scan output tree the helpers below resolve against. Set by
# :func:`set_scan` / :func:`enter_work_root`; falls back to ``_shared`` so the
# standalone CLIs keep working when no scan context has been established.
_CURRENT_SCAN: str | None = None


# ── reference artifacts ──────────────────────────────────────────────────────
# The names of the two images every reference stage writes, in ONE place. They used to be
# `gemini_input.jpg` / `nano_banana_raw.png` — provider names, from before image-gen moved to
# OpenAI, describing who made the file rather than what it is. Readers still accept the old
# spellings so a tree from an earlier run keeps working without a costly re-init.
INPUT_SHEET = "input2imagegen.jpg"        # the evidence sheet handed TO the image model
CLEAN_REFERENCE = "clean_obj_reference.png"  # the model's raw output, before crop/recentre
FINAL_REFERENCE = "reference_1024.png"    # the cropped, recentred reference the pipeline uses

_LEGACY = {INPUT_SHEET: "gemini_input.jpg", CLEAN_REFERENCE: "nano_banana_raw.png"}


def ref_artifact(ref_dir, name: str):
    """Locate one reference artifact under `ref_dir`, tolerating the pre-rename spelling.

    Returns the Path that exists, else None. Writers always use the new name; only readers go
    through here, so old trees stay readable and new ones never gain an old name.
    """
    ref_dir = Path(ref_dir)
    for candidate in (name, _LEGACY.get(name)):
        if candidate and (ref_dir / candidate).is_file():
            return ref_dir / candidate
    return None


# ── output tree ──────────────────────────────────────────────────────────────
def output_root() -> Path:
    """Repo-level output root holding every scan's artifacts (``<repo>/run``)."""
    env = os.environ.get("LITEREALITY_OUTPUT") or os.environ.get("OBJECT_INIT_OUTPUT")
    return Path(env).expanduser().resolve() if env else (REPO_ROOT / "run")


def set_scan(scan: str | None) -> None:
    """Select the scan whose per-scan output tree the path helpers resolve against."""
    global _CURRENT_SCAN
    _CURRENT_SCAN = scan


def current_scan() -> str:
    return _CURRENT_SCAN or "_shared"


def scan_output_dir(scan: str | None = None) -> Path:
    """``<repo>/run/<scan>`` — the one place everything for a scan lands."""
    return output_root() / (scan or current_scan())


def scene_init_dir(scan: str | None = None) -> Path:
    """Stage 1's output root for a scan — the parent of obj_stage/ and scene_stage/."""
    return final_root() / (scan or current_scan()) / "scene_init"


def obj_stage_dir(scan: str | None = None) -> Path:
    """The per-object half of stage 1 (object_init working tree, reference images, chair
    clustering, reconstructed GLBs). It lives under stage 1's own root in the deliverables tree,
    ``run/<scan>/scene_init/obj_stage`` (override the root via $LITEREALITY_FINAL). When the
    staging and deliverables roots differ, the staging spelling is kept as a symlink to here, so
    integration / run.sh / tooling resolve to the same physical tree either way."""
    return scene_init_dir(scan) / "obj_stage"


def reconstruct_dir(scan: str | None = None) -> Path:
    """Where the reconstruction launcher writes per-object / per-cluster GLBs."""
    return obj_stage_dir(scan) / "reconstructed_objs"


def traces_dir(scan: str | None = None) -> Path:
    """Process trace (Gemini calls, agent steps) for later visualization."""
    return obj_stage_dir(scan) / "traces"


def manifest_path(scan: str | None = None) -> Path:
    return obj_stage_dir(scan) / "manifest.json"


# ── work root (per scan; the object_init stage's working tree) ────────────────
def work_root() -> Path:
    return obj_stage_dir() / "object_init"


def enter_work_root(scan: str | None = None) -> Path:
    """Select ``scan``, mkdir + chdir into its work root (the ported preprocessing
    reads/writes CWD-relative ``input/...`` paths), and put lr_preprocessing on path."""
    if scan is not None:
        set_scan(scan)
    root = work_root()
    root.mkdir(parents=True, exist_ok=True)
    os.chdir(root)
    ensure_lr_on_path()
    return root


def input_root() -> Path:
    return work_root() / "input"


def scene_data_root() -> Path:
    return input_root() / "scene_data"


def parsed_images_root() -> Path:
    return input_root() / "parsed_images"


def object_refs_root() -> Path:
    return work_root() / "object_refs"


def final_root() -> Path:
    """Top-level deliverables tree (``<repo>/run``), shared with run.sh's FINAL_ROOT.
    Override with $LITEREALITY_FINAL. The whole object stage (obj_stage_dir) roots here."""
    env = os.environ.get("LITEREALITY_FINAL")
    return Path(env).expanduser().resolve() if env else (REPO_ROOT / "run")


def chair_clusters_root() -> Path:
    """Chair grouping + judge montages + cluster sheets. Nests inside the object_init work tree,
    which now lives under run/<scan>/obj_stage/ (see obj_stage_dir)."""
    return work_root() / "chair_clusters"


def opening_refs_root() -> Path:
    return work_root() / "opening_refs"


def scene_data_dir(scan: str) -> Path:
    return scene_data_root() / scan


def parsed_images_dir(scan: str) -> Path:
    return parsed_images_root() / scan


def scene_data_complete(scan: str) -> bool:
    d = scene_data_dir(scan)
    return all((d / f"{name}.pkl").exists() for name in ("walls", "objects", "wall_holes", "floor"))


# ── importing the ported preprocessing package ───────────────────────────────
def ensure_lr_on_path() -> None:
    """Put ``lr_preprocessing/`` on sys.path so ``import preprocessing`` and its
    internal ``from utils.X import ...`` resolve to the vendored copy."""
    p = str(LR_PREPROC_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


# ── secrets ──────────────────────────────────────────────────────────────────
def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip().strip('"').strip("'").strip()
    except OSError:
        pass
    return out


def _clean_key_value(value: str) -> str:
    """Take the value of a ``.key`` file, tolerating ``name=value`` / quotes.

    Accepts a bare key (``AIza...``), or a single ``NAME="AIza..."`` / ``NAME=AIza...``
    line — returns just the key in every case.
    """
    value = value.strip()
    if "=" in value:
        value = value.split("=", 1)[1].strip()
    return value.strip().strip('"').strip("'").strip()


def gemini_api_key() -> str:
    """Resolve the Google AI Studio key.

    Order: ``$GEMINI_API_KEY`` -> repo ``.key`` (bare key, or a single
    ``NAME="key"`` line) -> repo ``.keys`` -> the original LiteReality-Studio ``.keys``.
    """
    env = os.environ.get("GEMINI_API_KEY")
    if env:
        return env.strip()

    dot_key = REPO_ROOT / ".key"
    if dot_key.exists():
        value = _clean_key_value(dot_key.read_text(encoding="utf-8"))
        if value:
            return value

    for keys_file in (REPO_ROOT / ".keys", STUDIO_KEYS_FILE):
        if keys_file and keys_file.exists():
            parsed = _parse_env_file(keys_file)
            for name in ("GEMINI_API_KEY", "GEMINI_API_KEYS"):
                if parsed.get(name):
                    # GEMINI_API_KEYS may be a comma-separated list; take the first.
                    return parsed[name].split(",")[0].strip()

    raise RuntimeError(
        "No Gemini API key found. Set $GEMINI_API_KEY, or put one in "
        f"{REPO_ROOT / '.key'} (or a KEY=value file pointed to by $LR_STUDIO_KEYS)."
    )
