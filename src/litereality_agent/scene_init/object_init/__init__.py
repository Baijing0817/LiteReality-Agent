"""object_init — per-object initialization for a LiteReality room scan.

Given a raw scan folder (room.usdz + RGBD frames), produce, for every object:
  * cropped evidence images,
  * a clean Gemini / Nano Banana object-only reference,
and, for chairs, the grouping (clustering) of repeated chairs into shared types.

This is a self-contained port of the v2 preprocessing pipeline's objects/chairs
path. It needs no torch / GroundingDINO / pxr — only numpy, opencv, pillow, tqdm,
open3d, trimesh, and requests.

Stages (see ``run.py``):
    extract_scene -> crop_objects -> object_references -> chair_clusters
"""
