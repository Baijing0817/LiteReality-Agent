"""Export the deterministic editable seed scene from RoomPlan data.

The scene export writes:
  Room.py        — the assembler + this room's SHELL (rebuilds the shell, no usdz needed)
  manifest.json  — placements / object boxes
and can compile it to a previewable GLB.
"""

from __future__ import annotations

from pathlib import Path


def export_initial_scene(scan: str, out_root: Path | None = None) -> Path | None:
    """Export Room.py + SHELL for `scan`; returns the Room dir (or None on failure)."""
    from litereality_agent.scene.export import export_room

    return export_room.export(scan, out_root)


def build_preview(room_dir: Path, out_dir: Path | None = None, regenerate: bool = False) -> str | None:
    """Build Room.py → Room.glb (assemble in Blender, then bake
    the SHELL materials so the seed glb is faithful — same compiler the harness loop uses).
    Returns the built `Room.glb` path, or None on failure (e.g. Blender missing)."""
    from litereality_agent.scene import (
        compile_room,
    )

    glb = compile_room(room_dir, out_dir, bake=True, regenerate=regenerate)
    return str(glb) if glb is not None else None
