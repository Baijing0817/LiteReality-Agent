"""Every module named as a STRING must resolve.

A cross-package call that goes through a subprocess names its target in a string — `-m
litereality_agent.models.procedural.generate` — and a string is invisible to every import
check, every linter and every rename. This has already failed twice in exactly the same way: a
package moved, the imports were rewritten, and the `-m` strings quietly kept pointing at the old
name. The symptom is never an ImportError in the parent; it is a stage that "completes" with a
subprocess exit code nobody reads, and a missing GLB fifteen minutes later.

So: find every module path spelled as text in package and script sources and check it exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "src" / "litereality_agent"

# The top-level names that mean "a module in this repo". Anything else in a `-m` is a stdlib or
# third-party module (`json.tool`, `pytest`) and not ours to check.
OURS = ("litereality_agent",)
# Spellings that USED to be importable and must never come back — the exact regression above.
RETIRED = ("authoring", "scene_builder", "scene_package", "init", "object_init",
           "backends", "integration", "scene_init", "realism_authoring", "services", "adapters")

# `-m foo.bar` on a command line, and `NAME_MODULE = "foo.bar"` constants.
DASH_M = re.compile(r"""-m["'\s,\]]+\s*["']?([A-Za-z_][\w.]*\.[\w.]+)""")
MODULE_CONST = re.compile(r"""^\s*\w*MODULE\w*\s*=\s*["']([A-Za-z_][\w.]*\.[\w.]+)["']""", re.M)

SOURCES = sorted(
    [p for p in PKG.rglob("*.py")]
    + [p for p in PKG.rglob("*.sh")]
    + [p for p in (REPO / "scripts").rglob("*.py")]
    + [p for p in (REPO / "scripts").rglob("*.sh")]
    + [REPO / "sanity.py"]
)


def module_file(dotted: str) -> Path | None:
    """`litereality_agent.a.b` -> the .py (or package dir) it names, or None."""
    parts = dotted.split(".")
    if parts[0] != "litereality_agent":
        return None
    base = PKG.joinpath(*parts[1:])
    for candidate in (base.with_suffix(".py"), base / "__init__.py", base):
        if candidate.exists():
            return candidate
    return None


def collect() -> list[tuple[Path, int, str]]:
    found = []
    for src in SOURCES:
        if not src.is_file():
            continue
        for i, line in enumerate(src.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for m in DASH_M.finditer(line):
                found.append((src, i, m.group(1)))
        for m in MODULE_CONST.finditer(src.read_text(encoding="utf-8", errors="replace")):
            found.append((src, 0, m.group(1)))
    return found


def test_some_module_strings_exist():
    """Guard the guard: if the patterns stop matching, everything below passes vacuously."""
    ours = [d for _, _, d in collect() if d.startswith(OURS)]
    assert len(ours) >= 8, f"only found {len(ours)} module strings — the scan is not working"


def test_every_module_string_resolves():
    broken = [
        f"{src.relative_to(REPO)}:{line or '?'}: -m {dotted}"
        for src, line, dotted in collect()
        if dotted.startswith(OURS) and module_file(dotted) is None
    ]
    assert not broken, "module path(s) named in a string do not exist:\n  " + "\n  ".join(broken)


def test_no_retired_top_level_spelling():
    """`-m backends.procedural...` resolved before the src layout and silently stopped after.
    Nothing in the package is importable by a bare top-level name any more."""
    stale = [
        f"{src.relative_to(REPO)}:{line or '?'}: -m {dotted}"
        for src, line, dotted in collect()
        if dotted.split(".")[0] in RETIRED
    ]
    assert not stale, (
        "module path(s) missing the `litereality_agent.` prefix — importable before the src layout, "
        "silently dead after:\n  " + "\n  ".join(stale)
    )


@pytest.mark.parametrize("dotted", [
    "litereality_agent.models.procedural.generate",  # subprocess target used by the pipeline
    "litereality_agent.scene.compile.build_from_room",
    "litereality_agent.scene.manifest",
    "litereality_agent.pipeline.object_flow",
    "litereality_agent.models.grounding_dino.worker",
    "litereality_agent.pipeline.author.evidence",
    "litereality_agent.pipeline.author.refine_objects",
    "litereality_agent.pipeline.author.materials",
    "litereality_agent.pipeline.author.quality",
])
def test_known_subprocess_targets(dotted: str):
    """The specific modules some other process launches by name, pinned individually so a rename
    that misses one fails here rather than mid-run."""
    assert module_file(dotted) is not None, f"{dotted} is launched by name but does not exist"


def test_executable_helpers_survived_the_layout_move():
    from litereality_agent.pipeline.reconstruct import flow
    from litereality_agent.scene.rendering import config

    paths = (
        flow.LAUNCHER,
        config.RENDER_TOOL,
        config.SELECT_TOOL,
        config.STITCH_TOOL,
        config.FETCH_POLYHAVEN,
        PKG / "scene" / "rendering" / "object_turntable.py",
    )
    assert all(path.is_file() for path in paths), "missing helper(s): " + ", ".join(
        str(path) for path in paths if not path.is_file()
    )


def test_chair_repair_uses_hosted_trellis_when_configured(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from litereality_agent.pipeline.reconstruct.qc import chair_qc

    ref = tmp_path / "chair.png"
    ref.write_bytes(b"image")
    out = tmp_path / "Chair0.glb"
    settings = SimpleNamespace(runpod_trellis_endpoint="endpoint")
    monkeypatch.setattr("litereality_agent.settings.load_settings", lambda: settings)

    class Hosted:
        def reconstruct(self, images, *, out_dir, asset_id, **options):
            assert images == [ref]
            assert asset_id == "Chair0"
            path = Path(out_dir) / f"{asset_id}.glb"
            path.write_bytes(b"glb")
            return str(path)

    monkeypatch.setattr(
        "litereality_agent.models.registry.gen3d_from_settings", lambda configured: Hosted()
    )
    assert chair_qc._trellis_one("scan", ref, out, python=None, seed=42, decimation=50_000) == 0
