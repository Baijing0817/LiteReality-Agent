"""scene_init — the deterministic half: a raw scan becomes a seeded, editable room.

    object_init/        extract frames -> detect -> group (DINOv2 + judge) -> reference images
                        -> reconstruct each object (TRELLIS or procedural)
    run_scene_init.py   assemble the reconstructed objects into the seed Room.py + SHELL,
                        and compile the first Room.glb
    package.py          seal the output folder with its scene.json manifest — the self-describing
                        scene package every later stage launches from
    run_init.py         orchestrate the three

No LLM drives control flow here — models are called for specific decisions (grouping,
classification, reference generation), but the pipeline is fixed and reproducible.

LAYER 3 — may depend on models, integration and backends. Must not depend on
authoring or cli.
"""
