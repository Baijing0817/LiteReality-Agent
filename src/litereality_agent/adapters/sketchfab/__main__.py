"""CLI:  python -m litereality_agent.adapters.sketchfab {search,get,whoami}

  python -m litereality_agent.adapters.sketchfab whoami
  python -m litereality_agent.adapters.sketchfab search "office chair" -n 8 --max-faces 200000
  python -m litereality_agent.adapters.sketchfab get <uid|url> --out out/objects --name my_chair

Token from $SKETCHFAB_API_TOKEN (repo .env is loaded automatically).
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import SketchfabClient, SketchfabError


def _client() -> SketchfabClient:
    return SketchfabClient()


def _cmd_whoami(_args) -> int:
    print(_client().whoami())
    return 0


def _cmd_search(args) -> int:
    hits = _client().search(
        args.query, count=args.n, min_face_count=args.min_faces, max_face_count=args.max_faces
    )
    if not hits:
        print(f"no downloadable models for {args.query!r}")
        return 1
    for m in hits:
        print(f"{m['uid']}  {(m['name'] or '')[:44]:44}  faces={m['faces']}  "
              f"lic={m['license']}  by {m['author']}")
    return 0


def _cmd_get(args) -> int:
    try:
        res = _client().download(
            args.model, out_dir=args.out, name=args.name, prefer=args.format,
            pack_glb=not args.no_pack,
        )
    except SketchfabError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"OK  {res['glb']}  ({res['format']}, src={res['src_format']})")
    print(f"credit: {res['attribution']['credit']}")
    if args.json:
        print(json.dumps(res, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m litereality_agent.adapters.sketchfab", description="Sketchfab fetch tool")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="print the authenticated username").set_defaults(func=_cmd_whoami)

    ps = sub.add_parser("search", help="search downloadable models")
    ps.add_argument("query")
    ps.add_argument("-n", type=int, default=12, help="result count (default 12)")
    ps.add_argument("--min-faces", type=int, default=None)
    ps.add_argument("--max-faces", type=int, default=None, help="cap tris (game-ready assets)")
    ps.set_defaults(func=_cmd_search)

    pg = sub.add_parser("get", help="download a model by uid or URL → .glb")
    pg.add_argument("model", help="32-hex uid OR a sketchfab.com model URL")
    pg.add_argument("--out", default="output/sketchfab", help="output dir (default output/sketchfab)")
    pg.add_argument("--name", default=None, help="basename for the .glb (default: model slug)")
    pg.add_argument("--format", default="glb", choices=["glb", "gltf"], help="preferred archive")
    pg.add_argument("--no-pack", action="store_true", help="keep extracted glTF (don't pack to .glb)")
    pg.add_argument("--json", action="store_true", help="also print the full result JSON")
    pg.set_defaults(func=_cmd_get)

    args = p.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        return args.func(args)
    except SketchfabError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
