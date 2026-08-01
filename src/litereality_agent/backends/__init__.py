"""backends — heavy or external services, each isolated behind a launcher.

TRELLIS (image -> GLB, RunPod or local GPU), GroundingDINO (detection), the procedural
articulated-GLB agent, and Sketchfab (real model download). These run as subprocesses or
HTTP calls so their fat dependencies never enter the main env.

LAYER 0 — the bottom. Nothing here should import another package in this repo; callers
reach backends through `models`, never the other way round.

Known violation: backends/procedural/generate_procedural.py imports scene_init.object_init
{config, tracing}. That should be injected by the caller instead.
"""
