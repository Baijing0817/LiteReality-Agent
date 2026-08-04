"""Deterministic QC over the authored Room.py — the pipeline's final gate.

structure.md: \"Last comes deterministic QC over the resulting Room.py. QC is part of the
pipeline: if it fails, an agent fixes Room.py, and we repeat until every check passes.\"

    checks.py   report the violations (no writes)
    fix.py      resolve them from the SHELL boxes (fast, coarse)
    correct.py  resolve them from the TRUE meshes in the compiled Room.glb (needs python-fcl)
"""
