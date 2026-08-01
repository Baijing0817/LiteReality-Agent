"""Adopting stranded GLBs — recovering assets an interrupted agent built but never packaged.

The failure this recovers from: the articulated agent writes `<name>.glb` and then dies before
writing the `object.py` the assembler runs, so `build_from_room` reports "missing object.py", no
`room_preview/Object/<name>.glb` appears, and the object's box is dropped from the room. Valid
geometry on disk, empty room shipped.

The guards matter more than the happy path here. Adopting a truncated or externally-textured GLB
produces an object that loads but renders wrong, which is worse than a visibly missing one — a
missing object gets noticed, a silently untextured one ships.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "litereality_agent" / "scripts" / "ops"))
import adopt_stranded_glbs as adopt  # noqa: E402


def make_glb(path: Path, *, meshes: int = 1, images: int = 0, external: int = 0) -> Path:
    """Minimal but structurally real GLB: 12-byte header + a JSON chunk."""
    doc = {
        "asset": {"version": "2.0"},
        "meshes": [{"primitives": []} for _ in range(meshes)],
        "images": (
            [{"bufferView": 0} for _ in range(images)]
            + [{"uri": f"tex{i}.png"} for i in range(external)]
        ),
    }
    body = json.dumps(doc).encode("utf-8")
    body += b" " * ((4 - len(body) % 4) % 4)  # chunks are 4-byte aligned
    chunk = struct.pack("<II", len(body), 0x4E4F534A) + body
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(chunk)) + chunk)
    return path


def test_reads_mesh_and_texture_counts(tmp_path):
    info = adopt.glb_info(make_glb(tmp_path / "a.glb", meshes=4, images=5))
    assert info["meshes"] == 4 and info["images"] == 5 and info["external"] == []


def test_flags_external_textures(tmp_path):
    """A GLB with external image URIs loses them once the assembler runs it from another
    directory — the object imports fine and renders untextured."""
    info = adopt.glb_info(make_glb(tmp_path / "b.glb", meshes=2, images=1, external=2))
    assert info["external"] == ["tex0.png", "tex1.png"]


def test_rejects_a_non_glb(tmp_path):
    bad = tmp_path / "c.glb"
    bad.write_bytes(b"not a glb at all")
    with pytest.raises(ValueError):
        adopt.glb_info(bad)


def test_rejects_a_truncated_glb(tmp_path):
    """An agent killed mid-write leaves a partial file — it must not be adopted."""
    good = make_glb(tmp_path / "d.glb", meshes=3)
    trunc = tmp_path / "e.glb"
    trunc.write_bytes(good.read_bytes()[:20])
    with pytest.raises(Exception):
        adopt.glb_info(trunc)


def _scan_tree(tmp_path: Path, scan: str = "S") -> tuple[Path, Path]:
    """A scan tree with one packaged object and one stranded one."""
    final = tmp_path / "run"
    recon = final / scan / "scene_init" / "obj_stage" / "reconstructed_objs"
    room = final / scan / "scene_init" / "scene_stage" / "_oneshot" / "room"
    for name in ("Packaged0", "Stranded0"):
        (recon / name).mkdir(parents=True)
        make_glb(recon / name / f"{name}.glb", meshes=2, images=1)
        (room / "Objects" / "Procedural" / name).mkdir(parents=True)
    (room / "Objects" / "Procedural" / "Packaged0" / "object.py").write_text("# built by the agent")
    return final, room


def test_finds_only_the_object_missing_its_interface(tmp_path, monkeypatch):
    final, room = _scan_tree(tmp_path)
    monkeypatch.setattr(adopt, "FINAL", final)
    assert [n for n, _, _ in adopt.find_stranded("S", room)] == ["Stranded0"]


def test_locates_every_authored_room_variant(tmp_path, monkeypatch):
    """`RUN_TAG` gives a run its own `_oneshot_<tag>` room; a repair that only knew `_oneshot`
    would silently skip the room the user actually cares about."""
    final, _ = _scan_tree(tmp_path)
    (final / "S" / "scene_init" / "scene_stage" / "_oneshot_v2" / "room").mkdir(parents=True)
    monkeypatch.setattr(adopt, "FINAL", final)
    assert [p.parent.name for p in adopt.room_dirs("S")] == ["_oneshot", "_oneshot_v2"]


def test_generated_object_py_matches_the_assembler_contract():
    """`run_object_py` invokes `blender -b --python object.py -- <texdir> <out_glb>` and then
    requires out_glb to exist, so the script must read argv[1] as the output path."""
    src = adopt.STATIC_OBJECT_PY.format(name="Sink_Storage0")
    assert 'sys.argv.index("--")' in src
    assert "_argv[1] if len(_argv) > 1" in src, "must take the 2nd arg as the output glb"
    assert 'os.path.join(HERE, "Sink_Storage0.glb")' in src, "source must resolve next to object.py"
    compile(src, "object.py", "exec")  # must at least be valid Python


def test_generated_object_py_says_the_geometry_is_frozen():
    """Whoever opens this file next needs to know there is no build code behind it — otherwise
    the adopted asset reads as a normal procedural object that mysteriously can't be edited."""
    src = adopt.STATIC_OBJECT_PY.format(name="X0")
    assert "ADOPTED" in src and "frozen" in src.lower()
