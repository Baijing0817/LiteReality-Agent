"""The ``uv run litereality`` command line.

The public workflow is ``run`` plus independently resumable ``stage`` commands. ``scene_init``
and ``realism_authoring`` remain temporary aliases for existing automation.

UTILITIES (not stages — standalone tools that happen to share the environment):
  scene [dir]                    inspect / verify a scene package (what it holds, what is missing)
  view <scan>                    open the scene's viewer .html in a browser (--replay for the run page)
  trellis <image>                one image → one GLB via the gen3d provider (RunPod or local)
  sketchfab <cmd>                search / download real 3D models (needs $SKETCHFAB_API_TOKEN)

The seed stage seals its output folder with ``scene.json``, so every later stage launches from that
folder without being handed scan roots and per-stage path flags again.

A scan is named either way you like: `uv run litereality run Office_room` resolves it under
`$LR_SCANS_DIR`; `uv run litereality run example-scans/Office_room` takes the folder directly
(and points `$LR_SCANS_DIR` at its parent for the rest of the run).

The CLI is the composition edge: parsing and presentation only. Work lives in pipeline stages.
"""

from __future__ import annotations

import argparse
import os
import sys


def _print_pipeline_results(results) -> int:
    """Render one stable summary for full and single-stage runs."""
    failed = False
    for result in results:
        mark = {"completed": "✓", "reused": "↻", "skipped": "⊘", "failed": "✗"}[
            result.status.value
        ]
        detail = result.error or "; ".join(result.warnings)
        suffix = f" — {detail}" if detail else ""
        print(
            f"{mark} {result.stage:<12} {result.status.value:<9} "
            f"{result.duration_seconds:7.1f}s{suffix}"
        )
        failed |= result.status.value == "failed" and result.details.get("fatal", True)
    return 1 if failed else 0


def _run_pipeline(args) -> int:
    from litereality_agent.pipeline import PipelineRunner, RunContext

    try:
        context = RunContext.resolve(args.target, output_root=args.output_root)
        results = PipelineRunner().run(
            context,
            start=args.from_stage,
            through=args.through,
            force=set(args.force or ()),
            strict=args.strict,
        )
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    return _print_pipeline_results(results)


def _run_pipeline_stage(args) -> int:
    from litereality_agent.pipeline import PipelineRunner, RunContext

    try:
        context = RunContext.resolve(args.target, output_root=args.output_root)
        result = PipelineRunner().run_stage(
            context,
            args.stage,
            force=args.force_stage,
            strict=args.strict,
            options={"skip_image_generation": args.skip_image_generation},
        )
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    return _print_pipeline_results([result])


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--data-dir", default=None, help="data root (default: $LR_DATA_DIR or <repo>/data)"
    )


# --- scans: a NAME or a FOLDER ---------------------------------------------- #
# Every module downstream resolves a capture as `$LR_SCANS_DIR/<name>`, so a folder anywhere on
# disk is handled by pointing that variable at the folder's PARENT and keeping the basename as
# the scan name. One translation here, at the edge, instead of a second spelling for the capture
# threaded through init, scene_builder and the harness.
SCAN_MARKERS = ("room.usdz", "roomplan/room.usdz")


def looks_like_scan_dir(path) -> bool:
    """Is this a RoomPlan capture folder? A usdz, or the frame pairs the pipeline reads."""
    from pathlib import Path

    p = Path(path)
    if not p.is_dir():
        return False
    return any((p / m).is_file() for m in SCAN_MARKERS) or bool(next(p.glob("frame_*.jpg"), None))


def resolve_scan(value: str) -> str:
    """Take a scan NAME or a path to the scan FOLDER; return the name.

    When given a folder, `$LR_SCANS_DIR` is exported to its parent — so this must run BEFORE
    anything that reads that variable at import time (`scene_init.object_init.config`,
    `litereality_agent.services.rendering.config`). Callers do this first thing, before their lazy imports.
    """
    import os
    from pathlib import Path

    raw = str(value).rstrip("/")
    p = Path(raw).expanduser()
    # A bare name is a name — never a directory that happens to sit in the CWD.
    if os.sep not in raw and not raw.startswith("."):
        return raw
    if not p.is_dir():
        raise SystemExit(f"no such scan folder: {p}")
    if not looks_like_scan_dir(p):
        raise SystemExit(
            f"{p} does not look like a RoomPlan capture — expected room.usdz "
            f"(or roomplan/room.usdz) or frame_*.jpg inside it."
        )
    p = p.resolve()
    os.environ["LR_SCANS_DIR"] = str(p.parent)
    return p.name


def _add_model_opts(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--provider",
        default=None,
        choices=["claude_cli", "codex_cli"],
        help="reasoning CLI backend: claude_cli (`claude`, Claude Code) or codex_cli (`codex`, OpenAI Codex)",
    )
    p.add_argument("--model", default=None, help="reasoning model id (else provider default)")
    p.add_argument("--vlm", default=None, help="vision critic model id (e.g. gemini-*)")
    p.add_argument("--thinking-level", default=None, help="reasoning effort (low|medium|high)")
    p.add_argument("--max-turns", type=int, default=None)
    p.add_argument("--max-cost-usd", type=float, default=None, help="metered-spend cap")


def _run_init(args) -> int:
    print("note: 'scene_init' is deprecated; use 'litereality run --through seed'", file=sys.stderr)
    from litereality_agent.pipeline import PipelineRunner, RunContext

    context = RunContext.resolve(args.scan)
    through = "ingest" if getattr(args, "no_reconstruct", False) else "seed"
    options = {
        "ingest": {"skip_image_generation": getattr(args, "skip_gemini", False)},
        "seed": {
            "preview": not getattr(args, "no_preview", False),
            "capture_mode": getattr(args, "capture", "link"),
        },
    }
    return _print_pipeline_results(PipelineRunner().run(context, through=through, options=options))


def _run_scene(args) -> int:
    """Inspect the scene package — what init recorded, and whether it is all still on disk."""
    from litereality_agent.scene import manifest

    if args.adopt:
        # Every init that ran before packages existed left a perfectly good output tree with no
        # manifest. Writing one is exactly what init's final step does, so adoption is that step
        # run on its own — no reconstruction, no model calls, nothing overwritten but scene.json.
        from litereality_agent.pipeline.stages.seed.package import finalize

        pkg = finalize(resolve_scan(args.adopt), capture_mode=args.capture)
        print(pkg.summary())
        required, _ = pkg.check()
        for item in required:
            print(f"  ! MISSING (required): {item}")
        return 1 if required else 0

    if args.scene_cmd == "list":
        found = manifest.list_packages()
        for root in found:
            print(root)
        return 0 if found else 1

    pkg = manifest.require(args.path)
    if args.scene_cmd == "env":
        import shlex

        for key, value in {**pkg.env(), **pkg.stage_env()}.items():
            print(f"export {key}={shlex.quote(value)}")
        return 0

    print(pkg.summary())
    missing_required, missing_optional = pkg.check()
    for item in missing_optional:
        print(f"  ~ missing (optional): {item}")
    for item in missing_required:
        print(f"  ! MISSING (required): {item}")
    if missing_required:
        print("\nStage 2 cannot start from this package until those exist.")
    return 1 if missing_required else 0


def _run_view(args) -> int:
    """Open the scene's viewer .html (or its authoring-replay) in a browser.

    A convenience over hunting for ``run/<scan>/realism_authoring/<scan>.html``: find the viewer the
    export stage wrote and open it. Accepts a scan NAME or any path inside its output tree.
    ``--replay`` opens the run's authoring-replay page instead; ``--no-open`` (or ``NO_OPEN=1``) just
    prints the path (e.g. on a headless box).
    """
    import glob
    import webbrowser
    from pathlib import Path

    from litereality_agent.scene import config

    scan = args.scan
    name = config.scan_name(scan)
    tag = "_authoring_replay" if args.replay else ""
    p = Path(scan).expanduser()
    # A path into the output tree → search from there; a bare name → under the output root.
    root = (p if p.is_dir() else p.parent) if (os.sep in scan or p.exists()) else config.output_root() / name

    html = Path(root) / "realism_authoring" / f"{name}{tag}.html"
    if not html.is_file():
        found = [Path(x) for x in glob.glob(str(Path(root) / "**" / "*.html"), recursive=True)
                 if name in Path(x).name
                 and (("authoring_replay" in Path(x).name) == bool(args.replay))]
        html = max(found, key=lambda f: f.stat().st_mtime) if found else None

    if html is None:
        which = "authoring-replay" if args.replay else "viewer"
        print(f"✗ no {which} .html found for '{name}' under {root} — run: uv run litereality run {name}")
        return 2

    print(f"{'replay' if args.replay else 'viewer'} → {html}")
    if not (args.no_open or os.environ.get("NO_OPEN")):
        try:
            webbrowser.open(html.resolve().as_uri())
        except Exception:  # noqa: BLE001 — headless / no browser: the path is printed above
            pass
    return 0


def _run_authoring(args) -> int:
    """Deprecated alias for running the authoring-through-publish portion of the pipeline.

    Takes a scene PACKAGE directory, or nothing (run.sh discovers one from `$LR_SCENE`, the
    current directory, or the only package on disk). A scan that has never been through stage 1
    is refused with the command to run first, rather than quietly re-running init: the two halves
    cost very differently, and "authoring" silently doing a reconstruction is the wrong surprise.

    For the complete workflow, use `uv run litereality run <scan>`.
    """
    print("note: 'realism_authoring' is deprecated; use 'litereality run --from evidence'", file=sys.stderr)
    from litereality_agent.pipeline import PipelineRunner, RunContext
    from litereality_agent.scene import manifest

    target = getattr(args, "scene", None)
    pkg = manifest.discover(target) if target else manifest.discover()
    if pkg is None:
        where = f" for {target}" if target else ""
        raise SystemExit(
            f"no scene package found{where} — stage 2 needs stage 1's output.\n"
            "  run it first:  uv run litereality run --through seed <scan>\n"
            "  or run all:    uv run litereality run <scan>"
        )
    settings = None
    if args.blender:
        from litereality_agent.shared.settings import load_settings

        settings = load_settings(blender=args.blender)
    context = RunContext.resolve(pkg.root, settings=settings)
    return _print_pipeline_results(PipelineRunner().run(context, start="evidence"))


def _run_trellis(args) -> int:
    """Submit ONE image to the gen3d provider (RunPod if $RUNPOD_TRELLIS_ENDPOINT, else local)
    and write the GLB. The 'submit image → get GLB' tool."""
    import os

    from litereality_agent.pipeline.providers import gen3d_from_env

    svc = gen3d_from_env()
    out = args.out or (os.path.splitext(args.image)[0] + ".glb")
    out_dir = os.path.dirname(os.path.abspath(out)) or "."
    asset_id = os.path.splitext(os.path.basename(out))[0]
    print(f"[trellis] backend={svc.name}  {args.image} → {out}", flush=True)
    glb = svc.reconstruct(
        [args.image], out_dir=out_dir, asset_id=asset_id, seed=args.seed, simplify=args.simplify
    )
    rep = getattr(svc, "last_report", None)
    if rep is not None:
        print(f"  {rep.render()}")
    ok = bool(glb) and os.path.isfile(glb)
    print(f"  {'OK' if ok else 'FAILED'}: {glb or '(none)'}")
    return 0 if ok else 1


def _run_sketchfab(args) -> int:
    """Search / download real 3D models from Sketchfab (needs $SKETCHFAB_API_TOKEN)."""
    from litereality_agent.adapters.sketchfab.__main__ import main as sf_main

    argv = [args.sf_cmd]
    if args.sf_cmd == "search":
        argv += [args.query, "-n", str(args.n)]
        if args.max_faces:
            argv += ["--max-faces", str(args.max_faces)]
    elif args.sf_cmd == "get":
        argv += [args.model, "--out", args.out]
        if args.name:
            argv += ["--name", args.name]
    return sf_main(argv)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uv run litereality", description="LiteReality-Agent")
    sub = parser.add_subparsers(dest="command", required=True)

    stages = [
        "ingest", "reconstruct", "seed", "evidence",
        "author", "refine", "quality", "publish",
    ]
    p_run = sub.add_parser("run", help="run the complete reconstruction pipeline")
    p_run.add_argument("target", metavar="SCAN", help="scan name, capture folder, or scene package")
    p_run.add_argument("--from", dest="from_stage", choices=stages)
    p_run.add_argument("--through", choices=stages)
    p_run.add_argument(
        "--force", action="append", choices=stages,
        help="rerun this stage and invalidate every later stage",
    )
    p_run.add_argument("--strict", action="store_true", help="make optional failures fatal")
    p_run.add_argument("--output-root", default=None)
    p_run.set_defaults(func=_run_pipeline)

    p_stage = sub.add_parser("stage", help="run exactly one major pipeline stage")
    p_stage.add_argument("stage", choices=stages)
    p_stage.add_argument("target", metavar="SCAN_OR_SCENE")
    p_stage.add_argument("--force", dest="force_stage", action="store_true")
    p_stage.add_argument("--strict", action="store_true")
    p_stage.add_argument(
        "--skip-image-generation",
        action="store_true",
        help="ingest only: build capture evidence without paid reference-image generation",
    )
    p_stage.add_argument("--output-root", default=None)
    p_stage.set_defaults(func=_run_pipeline_stage)

    p_init = sub.add_parser("scene_init", help="STAGE 1 — deterministic: a scan → a scene package")
    p_init.add_argument("scan", metavar="SCAN",
                        help="scan NAME (resolved under $LR_SCANS_DIR) or the path to the scan"
                             " FOLDER itself, e.g. example_scans/Office_room")
    p_init.add_argument(
        "--crops-only",
        action="store_true",
        help="stop after crops + DINO refinement (no nano refs / generation)",
    )
    p_init.add_argument("--no-reconstruct", action="store_true",
                        help="skip GLB generation (TRELLIS / procedural) — refs only; faster but"
                             " scene_init will fail because Room.py needs the GLBs to assemble")
    p_init.add_argument("--no-procedural", action="store_true",
                        help="skip the articulated agent build (procedural objects + doors/windows);"
                             " still routes complexity and builds trellis-route assets via TRELLIS")
    p_init.add_argument("--no-preview", action="store_true",
                        help="skip compiling the seed Room.glb preview (Room.py still written)")
    p_init.add_argument(
        "--skip-gemini", action="store_true", help="no paid Gemini calls (placeholders)"
    )
    p_init.add_argument("--capture", default="link", choices=["link", "copy", "reference"],
                        help="how the scene package carries the capture: link (default, a symlink),"
                             " copy (real bytes — the folder becomes portable), reference (record"
                             " the source path only)")
    _add_common(p_init)
    _add_model_opts(p_init)
    p_init.set_defaults(func=_run_init)

    p_auth = sub.add_parser("realism_authoring",
                            help="STAGE 2 — agentic: author the scene until it looks real")
    p_auth.add_argument("scene", nargs="?", default=None, metavar="SCENE",
                        help="the scene package stage 1 wrote (the folder holding scene.json)."
                             " Omit to use $LR_SCENE, the current directory, or the only one on disk.")
    p_auth.add_argument("--blender", default=None,
                        help="Blender install dir or binary (else $LITEREALITY_BLENDER)")
    p_auth.set_defaults(func=_run_authoring)

    p_scene = sub.add_parser("scene", help="inspect / verify the scene package init wrote")
    p_scene.add_argument("path", nargs="?", default=None,
                         help="package dir, its scene.json, or anything inside it"
                              " (default: $LR_SCENE, else the current directory)")
    p_scene.add_argument("--env", dest="scene_cmd", action="store_const", const="env",
                         help="print eval-able exports that rebuild the stage-2 environment")
    p_scene.add_argument("--list", dest="scene_cmd", action="store_const", const="list",
                         help="every scene package under run/")
    p_scene.add_argument("--adopt", metavar="SCAN", default=None,
                         help="write scene.json for a scan that was init'd before packages"
                              " existed — nothing is rebuilt, only the manifest is added")
    p_scene.add_argument("--capture", default="link", choices=["link", "copy", "reference"],
                         help="with --adopt: how the package carries the capture (default link)")
    p_scene.set_defaults(func=_run_scene, scene_cmd="show")

    p_view = sub.add_parser("view", help="open the scene's viewer .html in a browser")
    p_view.add_argument("scan", help="scan name (or a path inside its output tree)")
    p_view.add_argument("--replay", action="store_true",
                        help="open the authoring-replay page instead of the room viewer")
    p_view.add_argument("--no-open", action="store_true",
                        help="just print the path; don't open a browser (also via NO_OPEN=1)")
    p_view.set_defaults(func=_run_view)

    p_tr = sub.add_parser("trellis", help="image → GLB via the gen3d provider (RunPod or local)")
    p_tr.add_argument("image", help="input reference image (png/jpg)")
    p_tr.add_argument("--out", default=None, help="output .glb (default: <image>.glb)")
    p_tr.add_argument("--seed", type=int, default=42)
    p_tr.add_argument("--simplify", type=float, default=0.95, help="mesh decimation ratio 0–1")
    _add_common(p_tr)
    p_tr.set_defaults(func=_run_trellis)

    p_model = sub.add_parser("model", help="standalone model adapter utilities")
    model_sub = p_model.add_subparsers(dest="model_command", required=True)
    p_gen3d = model_sub.add_parser("generate-3d", help="one image → one GLB")
    p_gen3d.add_argument("image", help="input reference image (png/jpg)")
    p_gen3d.add_argument("--out", default=None, help="output .glb (default: <image>.glb)")
    p_gen3d.add_argument("--seed", type=int, default=42)
    p_gen3d.add_argument("--simplify", type=float, default=0.95)
    _add_common(p_gen3d)
    p_gen3d.set_defaults(func=_run_trellis)

    p_sf = sub.add_parser("sketchfab", help="search/download real 3D models from Sketchfab")
    sf_sub = p_sf.add_subparsers(dest="sf_cmd", required=True)
    sf_s = sf_sub.add_parser("search", help="search downloadable models")
    sf_s.add_argument("query")
    sf_s.add_argument("-n", type=int, default=12)
    sf_s.add_argument("--max-faces", type=int, default=None)
    sf_g = sf_sub.add_parser("get", help="download a model (uid or URL) → .glb")
    sf_g.add_argument("model")
    sf_g.add_argument("--out", default="output/sketchfab")
    sf_g.add_argument("--name", default=None)
    p_sf.set_defaults(func=_run_sketchfab)

    return parser


def main(argv: list[str] | None = None) -> int:
    from litereality_agent.shared.settings import load_settings

    load_settings().apply_environment()
    values = list(argv if argv is not None else sys.argv[1:])
    if values[:2] == ["scene", "inspect"]:
        values.pop(1)
    args = _build_parser().parse_args(values)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
