"""`litereality_agent` command line.

THE TWO STAGES:
  scene_init <scan|dir>          STAGE 1 · deterministic — a scan becomes a scene package:
                                 per-object references, reconstructed GLBs, seed Room.py + Room.glb
  realism_authoring [scene]      STAGE 2 · agentic — edit Room.py until it looks like the real
                                 room: shell materials, fixtures, PBR, per-object refine, QC, viewer

  Both in one go:  ./run.sh <scan|path/to/scan>

UTILITIES (not stages — standalone tools that happen to share the environment):
  scene [dir]                    inspect / verify a scene package (what it holds, what is missing)
  view <scan>                    open the scene's viewer .html in a browser (--replay for the run page)
  trellis <image>                one image → one GLB via the gen3d provider (RunPod or local)
  sketchfab <cmd>                search / download real 3D models (needs $SKETCHFAB_API_TOKEN)

`uv run -m litereality_agent scene_init` seals its output folder with a `scene.json` manifest, so every later stage can be
launched from that folder alone — `uv run -m litereality_agent realism_authoring <dir>` / `./run.sh --scene <dir>` need no scan name,
no `$LR_SCANS_DIR` and no per-stage path flags.

A scan is named either way you like: `uv run -m litereality_agent scene_init Office_room` resolves it under
`$LR_SCANS_DIR`; `uv run -m litereality_agent scene_init example_scans/Office_room` takes the folder directly
(and points `$LR_SCANS_DIR` at its parent for the rest of the run).

LAYER 5 — the top. Depends on everything; nothing depends on it. A single module rather than a
package: it is argument parsing and dispatch, and every command's real work lives in the layer
below (`scene_init.run_init`, `integration.manifest`, `models.factory`, `run.sh`).
"""

from __future__ import annotations

import argparse
import os
import sys


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
    `litereality_agent.realism_authoring.scene.config`). Callers do this first thing, before their lazy imports.
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
    # Resolve BEFORE the import below: object_init.config reads $LR_SCANS_DIR at import time.
    scan = resolve_scan(args.scan)

    # Stage 1 is the expensive half and the one with the long dependency list, so it checks the
    # environment BEFORE doing anything — a missing Blender should cost a second, not the twenty
    # minutes of reconstruction that precede the export needing it. SKIP_SANITY=1 to override.
    if os.environ.get("SKIP_SANITY", "").strip() not in ("1", "true", "yes"):
        import subprocess

        from litereality_agent import REPO_ROOT

        rc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "sanity.py"), scan, "--stage", "scene_init"]
        ).returncode
        if rc != 0:
            print("\n  sanity failed — fix the above, or SKIP_SANITY=1 to run anyway.")
            return rc

    from litereality_agent.scene_init.run_init import init_scene

    # reconstruct = True by default (we need the GLBs for scene_init to assemble a Room).
    # `classify` splits each asset procedural-vs-trellis so we build the right route for each;
    # `procedural`/`build_openings` build the box/articulated assets + doors/windows via the agent.
    # Opt out with --no-reconstruct (refs only) or --no-procedural (trellis only, no agent build).
    do_reconstruct = not getattr(args, "no_reconstruct", False)
    do_procedural = do_reconstruct and not getattr(args, "no_procedural", False)
    res = init_scene(
        scan,
        crops_only=getattr(args, "crops_only", False),
        reconstruct=do_reconstruct,
        classify=do_reconstruct,
        procedural=do_procedural,
        build_openings=do_procedural,
        skip_gemini=getattr(args, "skip_gemini", False),
        build_preview=not getattr(args, "no_preview", False),
        capture_mode=getattr(args, "capture", "link"),
    )
    return _report_init(res)


# --- output ------------------------------------------------------------------ #
def _report_init(res) -> int:
    """The stage-1 summary. Returns the process exit code.

    Rendered with `litereality_agent.console`, the same helpers the pipeline's own per-stage rows use,
    so the whole run reads as one thing rather than three tools each with its own idea of a log.
    """
    from litereality_agent.console import colour, row, rule, short

    gen = res.summary.get("generation") or {}
    n_glb = gen.get("n_glb", 0)
    missing, errors = gen.get("missing") or [], gen.get("errors") or []

    lines = [rule(f"stage 1 · scene_init · {res.scan}")]
    lines.append(row("done" if n_glb else "error", "objects", f"{n_glb} GLB(s) reconstructed"))
    for err in errors:
        lines.append(row("error", "stage error", err))
    if missing:
        lines.append(row("error", "missing GLB", ", ".join(missing)))
    if res.scene_py:
        lines.append(row("done", "Room.py", short(res.scene_py)))
    else:
        lines.append(row("error", "Room.py", res.summary.get("scene_init_error", "(unknown)")))
    if res.preview_glb:
        lines.append(row("done", "Room.glb", short(res.preview_glb)))
    elif "scene_preview_error" in res.summary:
        lines.append(row("reused", "Room.glb", f"skipped — {res.summary['scene_preview_error']}"))
    if res.scene_dir:
        lines.append(row("done", "scene package", short(res.scene_dir)))
    elif "scene_package_error" in res.summary:
        lines.append(row("error", "scene package", res.summary["scene_package_error"]))
    print("\n".join(lines))

    bold, off, dim, red = colour("bold"), colour("off"), colour("dim"), colour("red")
    if not res.scene_py:
        print(f"\n  {red}stage 1 did not produce a seed room{off} — stage 2 has nothing to "
              f"start from.")
        print(f"  {dim}the stage rows above show where it stopped; re-run the same command "
              f"once that is fixed.{off}")
        return 1

    print(f"\n  {bold}next{off}  uv run -m litereality_agent realism_authoring {short(res.scene_dir)}")
    if missing:
        print(f"  {dim}({len(missing)} object(s) failed to build — authoring will place the rest; "
              f"re-run stage 1 to retry them){off}")
    return res.object_init_rc


def _run_scene(args) -> int:
    """Inspect the scene package — what init recorded, and whether it is all still on disk."""
    from litereality_agent.integration import manifest

    if args.adopt:
        # Every init that ran before packages existed left a perfectly good output tree with no
        # manifest. Writing one is exactly what init's final step does, so adoption is that step
        # run on its own — no reconstruction, no model calls, nothing overwritten but scene.json.
        from litereality_agent.scene_init.package import finalize

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

    from litereality_agent.integration import config

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
        print(f"✗ no {which} .html found for '{name}' under {root} — run the pipeline first: ./run.sh {name}")
        return 2

    print(f"{'replay' if args.replay else 'viewer'} → {html}")
    if not (args.no_open or os.environ.get("NO_OPEN")):
        try:
            webbrowser.open(html.resolve().as_uri())
        except Exception:  # noqa: BLE001 — headless / no browser: the path is printed above
            pass
    return 0


def _run_authoring(args) -> int:
    """STAGE 2 — run the authoring half over an already-init'd scene. Delegates to ``./run.sh``.

    Takes a scene PACKAGE directory, or nothing (run.sh discovers one from `$LR_SCENE`, the
    current directory, or the only package on disk). A scan that has never been through stage 1
    is refused with the command to run first, rather than quietly re-running init: the two halves
    cost very differently, and "authoring" silently doing a reconstruction is the wrong surprise.

    For both stages in one go, use `./run.sh <scan>`.
    """
    import os
    import subprocess

    from litereality_agent import REPO_ROOT as root  # run.sh lives at the checkout root
    env = {**os.environ, "LITEREALITY_BLENDER": args.blender} if args.blender else None

    from litereality_agent.integration import manifest

    argv = ["bash", str(root / "run.sh")]
    target = getattr(args, "scene", None)
    pkg = manifest.discover(target) if target else manifest.discover()
    if pkg is None:
        where = f" for {target}" if target else ""
        raise SystemExit(
            f"no scene package found{where} — stage 2 needs stage 1's output.\n"
            f"  run it first:  uv run -m litereality_agent scene_init <scan|path/to/scan>\n"
            f"  or both:       ./run.sh <scan|path/to/scan>"
        )
    argv += ["--scene", str(pkg.root)]  # absolute: run.sh cds to the repo root before parsing
    return subprocess.run(argv, env=env).returncode


def _run_trellis(args) -> int:
    """Submit ONE image to the gen3d provider (RunPod if $RUNPOD_TRELLIS_ENDPOINT, else local)
    and write the GLB. The 'submit image → get GLB' tool."""
    import os

    from litereality_agent.models.factory import gen3d_from_env

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
    from litereality_agent.backends.sketchfab.__main__ import main as sf_main

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
    parser = argparse.ArgumentParser(prog="uv run -m litereality_agent", description="LiteReality-Agent")
    sub = parser.add_subparsers(dest="command", required=True)

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
    from litereality_agent.models.config import load_env

    load_env()  # repo .env (non-overriding); shell env wins
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
