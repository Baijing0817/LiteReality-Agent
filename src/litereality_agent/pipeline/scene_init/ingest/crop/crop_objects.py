"""Stage 2 — scene data -> per-object cropped evidence images.

Ported from the v2 ``step2 cropping``. Drives the vendored preprocessing to crop
each RoomPlan object out of the capture frames (ranked, good-only), stitch them,
and prepare the camera metadata. Writes, relative to the work root:

    input/parsed_images/<scan>/<Object>/frame_*_ranking_*.jpg   # the crops
    input/parsed_images/<scan>/<Object>/camera/frame_*.json
    input/object_stage/<scan>/...
"""

from __future__ import annotations

import pickle
import time

from litereality_agent.pipeline.scene_init import paths as config

config.ensure_lr_on_path()
from preprocessing import (  # noqa: E402
    Colors,
    prepare_camera_data_for_retrieval,
    process_all_folders,
    process_object_images,
)


def _load_scene_data(scan: str):
    scene_dir = config.scene_data_dir(scan)
    required = {
        name: scene_dir / f"{name}.pkl" for name in ("walls", "objects", "wall_holes", "floor")
    }
    missing = [str(p) for p in required.values() if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing scene data (run extract_scene first): " + ", ".join(missing)
        )
    loaded = []
    for path in required.values():
        with path.open("rb") as f:
            loaded.append(pickle.load(f))
    return loaded  # walls, objects, wall_holes, floor


def crop(scan: str, include_walls: bool = False) -> None:
    """Crop every object's evidence images. Assumes CWD == work root."""
    started = time.time()
    walls, objects, wall_holes, _floor = _load_scene_data(scan)

    print(f"{Colors.BLUE}[crop]{Colors.RESET} processing object images...")
    process_object_images(scan, walls, objects, wall_holes, include_walls=include_walls)

    print(f"{Colors.BLUE}[crop]{Colors.RESET} stitching...")
    process_all_folders(f"input/parsed_images/{scan}")

    print(f"{Colors.BLUE}[crop]{Colors.RESET} preparing camera data...")
    prepare_camera_data_for_retrieval(scan)

    print(
        f"{Colors.GREEN}✓{Colors.RESET} crops in input/parsed_images/{scan} ({time.time() - started:.2f}s)"
    )
