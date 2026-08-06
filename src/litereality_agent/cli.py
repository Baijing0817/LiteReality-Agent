"""Public ``litereality`` command line.

The command surface deliberately mirrors the core architecture: run a pipeline,
run one stage, inspect a scene package, or invoke one model directly.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from litereality_agent.pipeline import PipelineRunner, RunContext
from litereality_agent.pipeline.stages import STAGES
from litereality_agent.settings import load_settings

SCAN_MARKERS = ("room.usdz", "roomplan/room.usdz")


def looks_like_scan_dir(path: str | os.PathLike[str]) -> bool:
    candidate = Path(path)
    return candidate.is_dir() and (
        any((candidate / marker).is_file() for marker in SCAN_MARKERS)
        or bool(next(candidate.glob("frame_*.jpg"), None))
    )


def resolve_scan(value: str) -> str:
    """Resolve a scan folder for small standalone callers retained in the package."""
    raw = value.rstrip("/")
    candidate = Path(raw).expanduser()
    if os.sep not in raw and not raw.startswith("."):
        return raw
    if not candidate.is_dir():
        raise SystemExit(f"no such scan folder: {candidate}")
    if not looks_like_scan_dir(candidate):
        raise SystemExit(f"{candidate} does not look like a RoomPlan capture")
    candidate = candidate.resolve()
    os.environ["LR_SCANS_DIR"] = str(candidate.parent)
    return candidate.name


def _print_results(results) -> int:
    failed = False
    marks = {"completed": "✓", "reused": "↻", "skipped": "⊘", "failed": "✗"}
    for result in results:
        detail = result.error or "; ".join(result.warnings)
        suffix = f" — {detail}" if detail else ""
        print(
            f"{marks[result.status.value]} {result.stage:<12} "
            f"{result.status.value:<9} {result.duration_seconds:7.1f}s{suffix}"
        )
        failed |= result.status.value == "failed" and result.details.get("fatal", True)
    return int(failed)


def _context(args) -> RunContext:
    return RunContext.resolve(args.target, output_root=getattr(args, "output_root", None))


def _author_options(args) -> dict:
    polish = getattr(args, "polish", False)
    return {
        "refine_objects": polish or getattr(args, "refine_objects", False),
        "materials": polish or getattr(args, "materials", False),
        "quality_pass": polish or getattr(args, "quality_pass", False),
    }


def _add_author_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--polish",
        action="store_true",
        help="run object refinement, materials, and model-driven QC after authoring",
    )
    parser.add_argument("--refine-objects", action="store_true")
    parser.add_argument("--materials", action="store_true")
    parser.add_argument("--quality-pass", action="store_true")


def _run(args) -> int:
    results = PipelineRunner().run(
        _context(args),
        start=args.from_stage,
        through=args.through,
        force=set(args.force or ()),
        strict=args.strict,
        options={"author": _author_options(args)},
    )
    return _print_results(results)


def _stage(args) -> int:
    result = PipelineRunner().run_stage(
        _context(args),
        args.stage,
        force=args.force,
        strict=args.strict,
        options={
            "skip_image_generation": args.skip_image_generation,
            **_author_options(args),
        },
    )
    return _print_results([result])


def _inspect(args) -> int:
    from litereality_agent.room_ops import manifest

    package = manifest.require(args.target)
    print(package.summary())
    required, optional = package.check()
    for path in optional:
        print(f"  ~ missing optional: {path}")
    for path in required:
        print(f"  ! missing required: {path}")
    return int(bool(required))


def _generate_3d(args) -> int:
    from litereality_agent.models.registry import gen3d_from_settings

    service = gen3d_from_settings(load_settings())
    output = args.out or str(Path(args.image).with_suffix(".glb"))
    result = service.reconstruct(
        [args.image], out_dir=str(Path(output).resolve().parent),
        asset_id=Path(output).stem, seed=args.seed, simplify=args.simplify,
    )
    print(result)
    return int(not result or not Path(result).is_file())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="litereality", description="LiteReality-Agent")
    commands = parser.add_subparsers(dest="command", required=True)
    stages = [stage.name for stage in STAGES]

    run = commands.add_parser("run", help="run the reconstruction pipeline")
    run.add_argument("target", metavar="SCAN_OR_SCENE")
    run.add_argument("--from", dest="from_stage", choices=stages)
    run.add_argument("--through", choices=stages)
    run.add_argument("--force", action="append", choices=stages)
    run.add_argument("--strict", action="store_true")
    run.add_argument("--output-root")
    _add_author_options(run)
    run.set_defaults(handler=_run)

    stage = commands.add_parser("stage", help="run exactly one pipeline stage")
    stage.add_argument("stage", choices=stages)
    stage.add_argument("target", metavar="SCAN_OR_SCENE")
    stage.add_argument("--force", action="store_true")
    stage.add_argument("--strict", action="store_true")
    stage.add_argument("--skip-image-generation", action="store_true")
    stage.add_argument("--output-root")
    _add_author_options(stage)
    stage.set_defaults(handler=_stage)

    scene = commands.add_parser("scene", help="inspect a generated scene package")
    scene_subcommands = scene.add_subparsers(dest="scene_command", required=True)
    inspect = scene_subcommands.add_parser("inspect")
    inspect.add_argument("target", nargs="?", default=None)
    inspect.set_defaults(handler=_inspect)

    model = commands.add_parser("model", help="invoke one configured model")
    model_subcommands = model.add_subparsers(dest="model_command", required=True)
    generate = model_subcommands.add_parser("generate-3d")
    generate.add_argument("image")
    generate.add_argument("--out")
    generate.add_argument("--seed", type=int, default=42)
    generate.add_argument("--simplify", type=float, default=0.95)
    generate.set_defaults(handler=_generate_3d)
    return parser


def main(argv: list[str] | None = None) -> int:
    load_settings().apply_environment()
    args = _parser().parse_args(argv)
    try:
        return args.handler(args)
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    raise SystemExit(main())
