"""Optional object and material refinement passes."""

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.result import StageResult, StageStatus
from litereality_agent.pipeline.stages._support import run_module


def complete(context: RunContext) -> bool:
    return (context.authoring_root / "obj_refine" / "summary.json").is_file()


def run(context: RunContext, options: dict) -> StageResult:
    args: list[object] = [
        "--scene", context.scene_dir, "--room", context.authored_room,
        "--refroot", context.object_root / "object_init", "--scan", context.capture_dir,
        "--results", context.authoring_root / "obj_refine",
        "--concurrency", options.get("concurrency", 2),
        "--budget", options.get("budget", 8),
    ]
    if options.get("objects"):
        args.extend(("--objects", options["objects"]))
    rc, log = run_module(context, "litereality_agent.pipeline.stages.refine.objects", args, log_name="refine")
    warnings = []
    if rc:
        warnings.append(f"object refinement exited {rc}; see {log}")
    if options.get("materials"):
        mrc, mlog = run_module(
            context,
            "litereality_agent.pipeline.stages.refine.materials",
            ["--scene", context.scene_dir, "--room", context.authored_room,
             "--surface-ref", context.authoring_root / "surface_ref", "--scan", context.capture_dir,
             "--refroot", context.object_root / "object_init"],
            log_name="materials",
        )
        if mrc:
            warnings.append(f"materials pass exited {mrc}; see {mlog}")
    return StageResult(
        "refine", StageStatus.COMPLETED if not rc else StageStatus.FAILED,
        artifacts={"results": str(context.authoring_root / "obj_refine")}, warnings=warnings,
        error=f"refinement exited {rc}" if rc else None,
    )
