"""Run the primary agentic Room.py authoring pass."""

import shutil

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.result import StageResult, StageStatus
from litereality_agent.pipeline.stages._support import command_result, run_module


def complete(context: RunContext) -> bool:
    return (context.authored_room / "Room.py").is_file()


def run(context: RunContext, options: dict) -> StageResult:
    if not (context.seed_room / "Room.py").is_file():
        return StageResult("author", StageStatus.FAILED, error=f"missing seed room at {context.seed_room}")
    if context.authored_room.exists():
        shutil.rmtree(context.authored_room)
    context.authored_room.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(context.seed_room, context.authored_room)
    args: list[object] = [
        "--scene", context.scene_dir,
        "--room", context.authored_room,
        "--surface-ref", context.authoring_root / "surface_ref",
        "--scan", context.capture_dir,
        "--profile", options.get("profile", "base"),
        "--max-turns", options.get("max_turns", 140),
        "--step-budget", options.get("step_budget", 100),
    ]
    rc, log = run_module(context, "litereality_agent.pipeline.stages.author.impl", args, log_name="author")
    return command_result(
        "author", rc, artifacts={"room": context.authored_room}, log=log,
    )
