"""Compile and publish the final room, viewer, and review artifacts."""

import shutil

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.result import StageResult, StageStatus
from litereality_agent.pipeline.stages._support import run_module


def complete(context: RunContext) -> bool:
    return (context.authoring_root / "Room.glb").is_file() and (
        context.authoring_root / f"{context.scan}.html"
    ).is_file()


def run(context: RunContext, options: dict) -> StageResult:
    rc, log = run_module(
        context, "litereality_agent.scene.compile.build_from_room",
        ["--room", context.authored_room, "--out", context.preview_dir, "--regenerate"],
        log_name="publish_compile",
    )
    glb = context.preview_dir / "Room.glb"
    if rc or not glb.is_file():
        return StageResult("publish", StageStatus.FAILED, error=f"final compile failed; see {log}")
    viewer = context.authoring_root / f"{context.scan}.html"
    args: list[object] = [
        glb, viewer, context.scan, f"--room={context.authored_room}", f"--scan={context.scan}"
    ]
    compare = context.authoring_root / "compare"
    if compare.is_dir():
        args.append(f"--compare={compare}")
    viewer_rc, viewer_log = run_module(
        context, "litereality_agent.pipeline.stages.publish.viewer", args, log_name="publish_viewer"
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
    )
