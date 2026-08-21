"""`make_selfcontained.py` bundles a build recipe + blender_lib.py into one self-contained
object.py by text transform. It found a real bug the hard way: a recipe that wrote
`sys.path.insert(...)` across several lines only had its opening line dropped, leaving the
trailing args and closing paren behind as a `SyntaxError: unmatched ')'` — Table1 silently
dropped out of a room for it. These tests are the regression coverage for that incident plus
the safety net that should have caught it immediately instead of hours into a live authoring
run.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/litereality_agent/models/object_generation/articulated-glb-agent"
    / ".claude/skills/image-to-articulated-glb/scripts/make_selfcontained.py"
)

LIB_SRC = '''"""blender_lib docstring."""
import bpy


def reset_scene():
    pass


def make_plain_material(name, color):
    pass
'''


@pytest.fixture(scope="module")
def make_selfcontained():
    spec = importlib.util.spec_from_file_location("make_selfcontained", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(tmp_path: Path, recipe_src: str) -> tuple[Path, Path]:
    recipe = tmp_path / "build_recipe.py"
    lib = tmp_path / "blender_lib.py"
    recipe.write_text(recipe_src, encoding="utf-8")
    lib.write_text(LIB_SRC, encoding="utf-8")
    return recipe, lib


def test_bundle_strips_a_multiline_sys_path_insert_cleanly(tmp_path, make_selfcontained):
    """The exact shape of the Table1 incident: sys.path.insert(...) wrapped across several
    lines. The bundled output must both parse AND contain no leftover sys.path reference."""
    recipe, lib = _write(
        tmp_path,
        '''"""A table recipe with a multi-line sys.path hack, like the one that broke Table1."""
import bpy
import sys
sys.path.insert(
    0,
    "/some/abs/path/to/scripts",
)
from blender_lib import reset_scene, make_plain_material


def build():
    reset_scene()
''',
    )

    out = make_selfcontained.bundle(str(recipe), str(lib), "Table1")

    ast.parse(out)  # must not raise
    assert "sys.path.insert" not in out


def test_bundle_still_strips_a_single_line_sys_path_insert(tmp_path, make_selfcontained):
    """The common case (Table0-style) must keep working exactly as before."""
    recipe, lib = _write(
        tmp_path,
        '''"""A table recipe with the ordinary single-line sys.path hack."""
import bpy
import sys
sys.path.insert(0, "/some/abs/path/to/scripts")
from blender_lib import reset_scene


def build():
    reset_scene()
''',
    )

    out = make_selfcontained.bundle(str(recipe), str(lib), "Table0")

    ast.parse(out)
    assert "sys.path.insert" not in out


def test_bundle_raises_a_clear_error_instead_of_writing_broken_python(tmp_path, make_selfcontained):
    """The safety net: whatever the recipe does that `drop_lines()` doesn't fully handle, bundle()
    must fail loudly — naming the recipe — rather than silently emit unparseable Python that only
    fails hours later when Blender tries to run it."""
    recipe, lib = _write(
        tmp_path,
        '''"""A recipe with a multi-line construct drop_lines() does not special-case."""
import bpy
TEXDIR = (
    "/some/abs/path",
)
from blender_lib import reset_scene


def build():
    reset_scene()
''',
    )

    with pytest.raises(SyntaxError, match=re.escape(str(recipe))):
        make_selfcontained.bundle(str(recipe), str(lib), "Broken0")


def test_main_never_writes_a_file_that_fails_to_parse(tmp_path, make_selfcontained, monkeypatch):
    """End-to-end through the CLI entrypoint: same multi-line sys.path.insert case, but driven the
    way the object-generation agent actually invokes this script."""
    recipe, lib = _write(
        tmp_path,
        '''"""CLI-driven bundle of a multi-line sys.path hack."""
import bpy
import sys
sys.path.insert(
    0,
    "/some/abs/path/to/scripts",
)
from blender_lib import reset_scene


def build():
    reset_scene()
''',
    )
    out = tmp_path / "object.py"

    monkeypatch.setattr(
        sys, "argv", ["make_selfcontained.py", str(recipe), str(out), "--lib", str(lib)]
    )
    make_selfcontained.main()

    ast.parse(out.read_text(encoding="utf-8"))
