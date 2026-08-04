"""ROOM-level QC: is the assembled scene in a sane state?

The pipeline's final gate. structure.md: "Last comes deterministic QC over the resulting
Room.py. QC is part of the pipeline: if it fails, an agent fixes Room.py, and we repeat until
every check passes." Operates on the authored `Room.py` plus its compiled `Room.glb`; the
repair is a nudge to a PLACEMENT, never a change to an object.

Distinct from `scene_init/reconstruct/mesh_qc`, which gates each generated asset as it is made
and asks whether the MESH is usable. Same kind of gate, different subject and scale.

    checks.py   report the violations (no writes)
    fix.py      resolve them from the SHELL boxes (fast, coarse)
    correct.py  resolve them from the TRUE meshes in the compiled Room.glb (needs python-fcl)
"""
