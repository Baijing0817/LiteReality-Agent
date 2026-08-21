"""Route and reconstruct every detected scene object."""

import json
from pathlib import Path

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.result import StageResult
from litereality_agent.pipeline.support import command_result, run_module


def _routed_objects(context: RunContext) -> set[str]:
    """Every object/opening this scan's routing pass committed to building.

    Read straight from `context`-relative paths rather than `scene_init.paths`' global scan
    state, so this agrees with the `RunContext` actually in hand (including a non-default
    `--output-root`) instead of whatever `$LITEREALITY_FINAL` happens to resolve to in this
    process. Missing/unreadable manifests just yield an empty set — callers fall back to the
    old "something got built" signal rather than treating that as "nothing is expected".
    """
    work = context.object_root / "object_init"
    names: set[str] = set()
    routing = work / "routing" / "routing_manifest.json"
    if routing.is_file():
        try:
            recs = json.loads(routing.read_text(encoding="utf-8")).get("scans", {}).get(context.scan, [])
            names.update(r["name"] for r in recs if r.get("name"))
        except (OSError, ValueError, AttributeError):
            pass
    refs = work / "opening_refs" / context.scan
    if refs.is_dir():
        names.update(d.name for d in refs.iterdir() if d.is_dir())
    return names


def _asset_built(reconstructed: Path, name: str) -> bool:
    if (reconstructed / f"{name}.glb").is_file():
        return True
    d = reconstructed / name
    return d.is_dir() and any(d.glob("*.glb"))


def complete(context: RunContext) -> bool:
    root = context.object_root / "reconstructed_objs"
    if not root.is_dir():
        return False
    expected = _routed_objects(context)
    if not expected:
        # No routing/opening manifest to check against — fall back to the old, coarser signal
        # rather than refusing to reuse a tree nothing here can explain.
        return bool(list(root.glob("*.glb")) + list(root.glob("*/*.glb")))
    # Every routed object needs its GLB on disk, not just "at least one exists somewhere" — a
    # reconstruct run an OOM killer or Ctrl-C cut short otherwise reads as "complete" on the next
    # invocation and silently ships a room missing whichever objects hadn't finished yet.
    return all(_asset_built(root, name) for name in expected)


def run(context: RunContext, options: dict) -> StageResult:
    args: list[object] = [
        "--scan", context.capture_dir, "--name", context.scan,
        "--output-root", context.output_root,
        "--skip-extract", "--skip-crop", "--skip-references",
        "--classify", "--reconstruct",
        "--procedural", "--build-openings",
        "--agent-model", context.settings.procedural_model,
    ]
    if options.get("chair_qc"):
        args.append("--chair-qc")
    if options.get("force"):
        args.append("--force-reconstruct")
    if options.get("concurrency"):
        args.extend(("--concurrency", options["concurrency"]))
    rc, log = run_module(
        context, "litereality_agent.pipeline.scene_init.flow", args, log_name="reconstruct"
    )
    return command_result(
        "reconstruct", rc,
        artifacts={"objects": context.object_root / "reconstructed_objs"}, log=log,
    )
