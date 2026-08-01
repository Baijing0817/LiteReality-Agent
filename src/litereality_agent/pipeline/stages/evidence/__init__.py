"""Build wall, floor, and ceiling evidence used by authoring."""

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.result import StageResult
from litereality_agent.pipeline.stages._support import command_result, run_module


def complete(context: RunContext) -> bool:
    return (context.authoring_root / "surface_ref" / "surface_ref_manifest.json").is_file()


def run(context: RunContext, options: dict) -> StageResult:
    args = ["--scene", context.scene_dir]
    if options.get("force"):
        args.append("--force")
    rc, log = run_module(
        context, "litereality_agent.pipeline.stages.evidence.surfaces", args,
        log_name="evidence",
    )
    return command_result(
        "evidence", rc,
        artifacts={"surface_references": context.authoring_root / "surface_ref"}, log=log,
    )
