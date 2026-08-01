"""Compile and apply deterministic room quality checks."""

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.result import StageResult, StageStatus
from litereality_agent.pipeline.stages._support import run_module


def complete(context: RunContext) -> bool:
    return (context.authoring_root / "qc.txt").is_file()


def run(context: RunContext, options: dict) -> StageResult:
    warnings = []
    compile_rc, compile_log = run_module(
        context, "litereality_agent.scene.compile.build_from_room",
        ["--room", context.authored_room, "--out", context.preview_dir], log_name="quality_compile",
    )
    if compile_rc:
        warnings.append(f"preview compile exited {compile_rc}; see {compile_log}")
    collision_rc, collision_log = run_module(
        context, "litereality_agent.pipeline.stages.quality.collision",
        ["--room", context.authored_room, "--apply"], log_name="quality_collision",
    )
    if collision_rc:
        warnings.append(f"collision correction exited {collision_rc}; see {collision_log}")
    qc_rc, qc_log = run_module(
        context, "litereality_agent.scene.quality.room",
        ["--room", context.authored_room], log_name="quality",
    )
    qc_path = context.authoring_root / "qc.txt"
    if qc_log and qc_log.exists():
        qc_path.write_text(qc_log.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    if qc_rc:
        warnings.append("room still has reported quality violations")
    return StageResult(
        "quality", StageStatus.COMPLETED,
        artifacts={"report": str(qc_path)}, warnings=warnings,
    )
