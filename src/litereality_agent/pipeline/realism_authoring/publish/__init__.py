"""Compile and publish the final room, viewer, and review artifacts."""

import shutil

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.result import StageResult, StageStatus
from litereality_agent.pipeline.support import run_module


def complete(context: RunContext) -> bool:
    return (context.authoring_root / "Room.glb").is_file() and (
        context.authoring_root / f"{context.scan}.html"
    ).is_file()


def run(context: RunContext, options: dict) -> StageResult:
    warnings: list[str] = []
    collision_rc, collision_log = run_module(
        context,
        "litereality_agent.pipeline.room_qc.correct",
        ["--room", context.authored_room, "--apply"],
        log_name="publish_collision",
    )
    if collision_rc:
        warnings.append(f"collision correction exited {collision_rc}; see {collision_log}")
    quality_rc, quality_log = run_module(
        context,
        "litereality_agent.pipeline.room_qc.checks",
        ["--room", context.authored_room],
        log_name="publish_quality",
    )
    if quality_rc:
        warnings.append(f"scene quality checks reported violations; see {quality_log}")
    rc, log = run_module(
        context, "litereality_agent.room_format.compile.build_from_room",
        ["--room", context.authored_room, "--out", context.preview_dir, "--regenerate"],
        log_name="publish_compile",
    )
    glb = context.preview_dir / "Room.glb"
    if rc or not glb.is_file():
        return StageResult("publish", StageStatus.FAILED, error=f"final compile failed; see {log}")
    # Flatten node-graph SHELL materials into the glb. `build_from_room` only EXPORTS; the bake is
    # the step `compile_room` adds on top, and the agent's own compile/render tool goes through
    # `compile_room` — so every render the author sees is baked. Publishing without it silently
    # shipped a different room: a procedural wall/floor/ceiling material (`two_tone_mat`,
    # `carpet_mat`, `ceiling_tile_mat`) has no glTF representation, so it exports with neither a
    # texture nor a baseColorFactor and renders WHITE. Flat-RGB and fetched-image materials
    # survive either way, which is why this stayed invisible until a room used procedural ones.
    from litereality_agent.room_format import api

    bake_rc = api.bake_room(context.preview_dir / "Room.blend", glb)
    if bake_rc:
        warnings.append(f"material bake exited {bake_rc}; see {glb.parent / 'bake.log'}")
    viewer = context.authoring_root / f"{context.scan}.html"
    args: list[object] = [
        glb, viewer, context.scan, f"--room={context.authored_room}", f"--scan={context.scan}"
    ]
    compare = context.authoring_root / "compare"
    if compare.is_dir():
        args.append(f"--compare={compare}")
    viewer_rc, viewer_log = run_module(
        context, "litereality_agent.pipeline.realism_authoring.publish.viewer", args, log_name="publish_viewer"
    )
    if viewer_rc:
        return StageResult("publish", StageStatus.FAILED, error=f"viewer export failed; see {viewer_log}")
    shutil.copy2(glb, context.authoring_root / "Room.glb")
    shutil.copy2(context.authored_room / "Room.py", context.authoring_root / "Room.py")
    return StageResult(
        "publish", StageStatus.COMPLETED,
        artifacts={
            "room_source": str(context.authoring_root / "Room.py"),
            "room_glb": str(context.authoring_root / "Room.glb"),
            "viewer": str(viewer),
        },
        warnings=warnings,
    )
