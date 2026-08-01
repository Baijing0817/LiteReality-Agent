"""integration.export — scan → ``Room/<scan>/`` definition.

Turns a RoomPlan scan into the **compact, editable** room program:
    Room.py        — the assembler + this room's semantic SHELL
    manifest.json  — per-object placements / boxes

The seed an agent then refines. The compiler lives in ``integration.compile``.
"""
