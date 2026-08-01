"""Assemble reconstructed assets into the editable seed room."""

from pathlib import Path

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.result import StageResult, StageStatus


def complete(context: RunContext) -> bool:
    return (context.seed_room / "Room.py").is_file() and (context.scene_dir / "scene.json").is_file()


def run(context: RunContext, options: dict) -> StageResult:
    from litereality_agent.pipeline import paths as config
    from litereality_agent.pipeline.stages.seed.builder import build_preview, export_initial_scene
    from litereality_agent.pipeline.stages.seed.package import ensure_stage_links, finalize

    ensure_stage_links(context.scan)
    config.set_scan(context.scan)
    room = export_initial_scene(context.scan)
    if room is None or not (Path(room) / "Room.py").is_file():
        return StageResult("seed", StageStatus.FAILED, error="seed export did not produce Room.py")
    artifacts = {"room": str(room)}
    warnings: list[str] = []
    if options.get("preview", True):
        try:
            glb = build_preview(Path(room))
            if glb:
                artifacts["preview"] = str(glb)
        except Exception as exc:
            warnings.append(f"seed preview unavailable: {exc}")
    package = finalize(context.scan, capture_mode=options.get("capture_mode", "link"))
    artifacts["manifest"] = str(package.manifest)
    return StageResult("seed", StageStatus.COMPLETED, artifacts=artifacts, warnings=warnings)
