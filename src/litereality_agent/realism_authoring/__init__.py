"""authoring — the agentic half: turn the seeded Room.py into something that looks real.

    author.py        one self-paced model pass edits Room.py (materials + fixtures)
    refine_*.py      per-object and per-wall refinement against reference images
    qc_*.py          quality gates over the authored room
    scene/           the harness the sessions run in: evidence, critic, validation, report
    tools/           the CLOSED capability-tool set those sessions may call
    views/           imaging: select reference views, render the room, stitch walls, overlays

LAYER 4 — the top of the library stack, below `cli`. May depend on models,
integration, init and backends. Nothing should depend on authoring.
"""
