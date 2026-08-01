"""init — the deterministic stage that prepares a scan for the agentic loop.

`uv run -m litereality_agent scene_init <scan>` runs this. It produces the **seed** the loop refines:

    1. object_init   (vendored, init/object_init): scan → per-object crops + DINO-refined boxes
                      + nano references + chair groups (+ optional Trellis reconstruction).
                      Output tree: run/<scan>/obj_stage/  (object_init's own layout).
    2. scene_init    (TODO, next port): export the initial scene.py from RoomPlan + first render.
    3. record        (TODO): register the seed as rev_000001 in the data root.

Everything here is deterministic — no LLM drives control flow. The loop (`authoring/`)
starts only once this has run.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class InitResult:
    scan: str
    object_init_rc: int
    obj_stage_dir: str
    scene_py: str | None = None  # filled by scene_init
    preview_glb: str | None = None  # filled by build_preview (seed Room.glb)
    scene_dir: str | None = None  # the scene PACKAGE root (holds scene.json) — what stage 2 takes
    record_id: str | None = None  # filled by the record write (next phase)
    summary: dict[str, Any] = field(default_factory=dict)


def _install_detector_tool():
    """If $LR_DINO_PYTHON points at an isolated torch env, install the DINO subprocess tool as
    the init detector; bbox_polish / opening matcher then call THAT instead of importing torch
    in-process. Returns the service (to close) or None (in-process fallback)."""
    dino_python = os.environ.get("LR_DINO_PYTHON")
    if not dino_python:
        return None
    from litereality_agent.models.dino import DinoSubprocessService
    from litereality_agent.scene_init.object_init.detect import detector

    svc = DinoSubprocessService(python=dino_python)
    detector.set_service(svc)
    return svc


def _install_gen3d_tool():
    """Install the TRELLIS gen3d tool as the init reconstructor: RunPod when its endpoint is
    grounded ($RUNPOD_TRELLIS_ENDPOINT), else the LOCAL launcher (on-box GPU). Set
    $LR_GEN3D=off to skip (fall back to reconstruct.py's own launcher path). Returns the role used."""
    mode = os.environ.get("LR_GEN3D", "auto").strip().lower()
    if mode == "off":
        return None
    from litereality_agent.models.factory import gen3d_from_env  # single source of truth
    from litereality_agent.scene_init.object_init import reconstructor

    svc = gen3d_from_env()
    reconstructor.set_service(svc)
    return svc.name


def run_object_init(
    scan: str,
    *,
    crops_only: bool = False,
    reconstruct: bool = False,
    classify: bool = False,
    procedural: bool = False,
    build_openings: bool = False,
    skip_gemini: bool = False,
    extra: list[str] | None = None,
) -> int:
    """Drive the vendored object_init orchestrator for one scan. Returns its exit code.

    Flags map to object_init's CLI; pass anything else through `extra` (e.g. ["--chair-qc"]).
    `classify` runs the complexity router (procedural vs trellis) so `reconstruct` only builds
    the trellis-route assets and `procedural`/`build_openings` build the rest via the articulated
    agent — without it, `reconstruct` sends *every* asset to TRELLIS.
    DINO runs through the isolated tool when $LR_DINO_PYTHON is set (else in-process).

    object_init `chdir`s into the per-scan work root (the vendored preprocessing reads CWD-relative
    `input/` paths); we restore the original CWD afterwards so later stages (scene_init) and
    concurrent callers see a clean working directory.
    """
    from litereality_agent.scene_init.object_init import run as object_init_run

    argv = ["--scan", scan]
    if crops_only:
        argv.append("--crops-only")
    if reconstruct:
        argv.append("--reconstruct")
    if classify:
        argv.append("--classify")
    if procedural:
        argv.append("--procedural")
    if build_openings:
        argv.append("--build-openings")
    if skip_gemini:
        argv.append("--skip-gemini")
    if extra:
        argv += list(extra)

    cwd = os.getcwd()
    svc = _install_detector_tool()
    _install_gen3d_tool()
    try:
        return object_init_run.main(argv)
    finally:
        os.chdir(cwd)
        if svc is not None:
            svc.close()
            from litereality_agent.scene_init.object_init.detect import detector

            detector.set_service(None)
        from litereality_agent.scene_init.object_init import reconstructor

        reconstructor.set_service(None)


def _verify_generation(scan: str) -> dict:
    """Best-effort health check on object_init's GLB generation for `scan`.

    object_init treats a TRELLIS / procedural failure as non-fatal (it records `{"error": ...}` and
    keeps going), but scene_init then assembles a `Room.py` that references GLBs which may be
    missing — silently producing a broken seed. This surfaces that: it reports any swallowed stage
    error and, per routed asset, whether its GLB actually landed on disk. Never raises.
    """
    from litereality_agent.scene_init.object_init import config

    health: dict[str, Any] = {"errors": [], "missing": [], "n_glb": 0}
    recon_dir = config.reconstruct_dir(scan)

    summary_path = config.work_root() / "object_init_summary.json"
    if summary_path.exists():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        for stage in ("reconstruct", "procedural", "build_openings"):
            st = data.get(stage)
            if isinstance(st, dict) and st.get("error"):
                health["errors"].append(f"{stage}: {st['error']}")

    manifest = config.work_root() / "routing" / "routing_manifest.json"
    if manifest.exists():
        try:
            recs = json.loads(manifest.read_text(encoding="utf-8")).get("scans", {}).get(scan, [])
        except (OSError, ValueError):
            recs = []
        for rec in recs:
            name, route = rec.get("name"), rec.get("route")
            if not name:
                continue
            if route == "trellis":  # launcher writes reconstruct/<name>.glb
                present = (recon_dir / f"{name}.glb").exists()
            else:  # procedural: agent writes reconstruct/<name>/<...>.glb
                sub = recon_dir / name
                present = (recon_dir / f"{name}.glb").exists() or (
                    sub.is_dir() and any(sub.glob("*.glb"))
                )
            if not present:
                health["missing"].append(f"{name} ({route})")

    if recon_dir.is_dir():
        health["n_glb"] = len(list(recon_dir.glob("*.glb"))) + len(list(recon_dir.glob("*/*.glb")))
    return health


def init_scene(
    scan: str,
    *,
    build_preview: bool = True,
    capture_mode: str = "link",
    **flags: Any,
) -> InitResult:
    """Full deterministic init for one scan → an InitResult the loop can consume.

    Runs object_init (crops → refs → routed reconstruction) then scene_init (export the seed
    `Room.py` + SHELL) and, unless `build_preview=False`, compiles the seed `Room.glb` preview.
    Generation health (swallowed errors + missing GLBs) lands in `result.summary["generation"]`.

    Finally it writes the SCENE PACKAGE (`run/<scan>/scene.json`) — the manifest that
    makes the output folder self-describing, so stage 2 launches from the folder alone instead of
    being re-handed the scan name, the scans root and four per-stage path flags. `capture_mode`
    controls how the capture is carried (`link` / `copy` / `reference`); see
    `init.scene_init.package.finalize`.
    """
    from litereality_agent.scene_init.object_init import config
    from litereality_agent.scene_init.package import ensure_stage_links

    # FIRST: make run/<scan>/<stage> and run/<scan>/<stage> name the same tree. The
    # object stage writes to one spelling and the room export reads the other, so a run without
    # run.sh (which creates these) reconstructs everything and then exports nothing.
    ensure_stage_links(scan)

    rc = run_object_init(scan, **flags)
    config.set_scan(scan)
    result = InitResult(
        scan=scan,
        object_init_rc=rc,
        obj_stage_dir=str(config.obj_stage_dir(scan)),
    )
    result.summary["generation"] = _verify_generation(scan)

    # scene_init: export the initial Room.py + SHELL (the seed the harness refines)
    # NOTE: errors are NOT swallowed here — a missing Room.py kills the whole pipeline silently
    # otherwise (harness fails with "no baseline room definition"). Let it raise so the cause is visible.
    from litereality_agent.scene_init.run_scene_init import build_preview as build_seed_preview
    from litereality_agent.scene_init.run_scene_init import export_initial_scene

    room_dir = export_initial_scene(scan)
    if room_dir is None:
        result.summary["scene_init_error"] = "export_initial_scene returned None"
        _write_package(result, capture_mode)
        return result
    result.scene_py = str(Path(room_dir) / "Room.py")

    # Build the seed Room.glb preview (what the docs promise `uv run -m litereality_agent scene_init` produces). Non-fatal:
    # it needs Blender ($LITEREALITY_BLENDER) — a missing preview must not sink a valid Room.py.
    if build_preview:
        try:
            glb = build_seed_preview(Path(room_dir))
        except Exception as exc:  # noqa: BLE001
            glb = None
            result.summary["scene_preview_error"] = str(exc)
        if glb:
            result.preview_glb = glb
        else:
            result.summary.setdefault(
                "scene_preview_error", "compile_room failed (is $LITEREALITY_BLENDER set?)"
            )
    _write_package(result, capture_mode)
    # TODO(record): result.record_id = write_seed_record(scan, result)
    return result


def _write_package(result: InitResult, capture_mode: str) -> None:
    """Seal the output folder with its `scene.json`. Non-fatal, and written even on a partial
    init: a package that records what IS there is what lets `uv run -m litereality_agent scene` explain a failure,
    and a manifest is worthless if it only appears when everything already worked."""
    from litereality_agent.scene_init.package import finalize

    try:
        pkg = finalize(
            result.scan,
            capture_mode=capture_mode,
            init={
                "object_init_rc": result.object_init_rc,
                "room_py": result.scene_py,
                "preview_glb": result.preview_glb,
                "n_glb": (result.summary.get("generation") or {}).get("n_glb", 0),
                "generation": result.summary.get("generation") or {},
            },
        )
        result.scene_dir = str(pkg.root)
    except Exception as exc:  # noqa: BLE001
        result.summary["scene_package_error"] = str(exc)
