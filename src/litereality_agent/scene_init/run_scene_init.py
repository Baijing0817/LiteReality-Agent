"""scene_init — export the initial scene (the `Room.py` assembler + semantic SHELL) from a
scan's RoomPlan, the deterministic seed the harness then refines.

Thin wrapper over `integration.export.export_room.export`, which writes `Room/<scan>/` with:
  Room.py        — the assembler + this room's SHELL (rebuilds the shell, no usdz needed)
  manifest.json  — placements / object boxes
build it to a previewable room.glb with `integration.compile.build_from_room`.
"""

from __future__ import annotations

from pathlib import Path


def export_initial_scene(scan: str, out_root: Path | None = None) -> Path | None:
    """Export Room.py + SHELL for `scan`; returns the Room dir (or None on failure)."""
    from litereality_agent.integration.export import export_room

    return export_room.export(scan, out_root)


def build_preview(room_dir: Path, out_dir: Path | None = None, regenerate: bool = False) -> str | None:
    """Build Room.py → Room.glb via `integration.compile_room` (assemble in Blender, then bake
    the SHELL materials so the seed glb is faithful — same compiler the harness loop uses).
    Returns the built `Room.glb` path, or None on failure (e.g. Blender missing)."""
    from litereality_agent.integration import (
        compile_room,  # public API exposed by integration/__init__.py
    )

    glb = compile_room(room_dir, out_dir, bake=True, regenerate=regenerate)
    return str(glb) if glb is not None else None
