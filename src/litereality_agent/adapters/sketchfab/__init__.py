"""sketchfab — pull real 3D objects from Sketchfab via the Download API.

A small client that authenticates with a Sketchfab API token ($SKETCHFAB_API_TOKEN), searches
for downloadable models, and downloads one to a local `.glb` (extracting the archive and, when
needed, packing glTF → GLB with trimesh). Attribution (author + license) is captured alongside
every download so CC-licensed assets can be credited.

Runnable:  python -m litereality_agent.adapters.sketchfab search "office chair"
           python -m litereality_agent.adapters.sketchfab get <uid|url> --out out/dir
Also exposed through `uv run litereality sketchfab` and the `fetch_object` capability tool.
"""

from __future__ import annotations

from .client import SketchfabClient, SketchfabError, parse_uid

__all__ = ["SketchfabClient", "SketchfabError", "parse_uid"]
