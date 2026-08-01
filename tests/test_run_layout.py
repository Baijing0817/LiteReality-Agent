"""`run.sh` must not bury stage 1's output inside stage 2's folder.

The object stage physically writes to `scene_init.object_init.config.scene_init_dir()` —
`$LITEREALITY_FINAL/<scan>/scene_init/{obj_stage,scene_stage}`. `run.sh` creates those two names
under `$LITEREALITY_OUTPUT/<scan>/` as well, symlinking across when the two roots differ, so every
stage resolves the same tree from either spelling.

Point those links at `$AUTHORING` (`run/<scan>/realism_authoring`) instead and the expensive half —
the TRELLIS reconstructions, the generated reference images, the seed `Room.py` — physically lives
inside the half the README calls disposable:

    README §Two stages, realism_authoring: | re-run | freely — it never touches the seed |
    run.sh:                                # Either half can be deleted and re-run without
                                           # disturbing the other.

So `rm -rf run/<scan>/realism_authoring` silently destroys stage 1 and leaves dangling links, and
the next `./run.sh --scene run/<scan>` has no seed to start from. These tests execute run.sh's own
path prologue and assert the two halves stay side by side.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUN_SH = REPO / "run.sh"
SCAN = "test-scan-Room"

# run.sh's path prologue ends here — the first line that consumes the layout rather than building
# it. Everything above is pure path arithmetic and mkdir/ln, which is exactly what we want to run.
END_MARKER = "VIEWER_HTML="

PROBE = """
python3 - "$OUT" "$AUTHORING" "$FINAL_ROOT" <<'PYEOF'
import json, sys
print(json.dumps({"out": sys.argv[1], "authoring": sys.argv[2], "final_root": sys.argv[3]}))
PYEOF
"""


def _prologue() -> str:
    lines = RUN_SH.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith(END_MARKER):
            return "".join(lines[:i])
    raise AssertionError(f"{END_MARKER!r} not found in run.sh — update END_MARKER")


@pytest.fixture
def layout(tmp_path: Path):
    """Run run.sh's path prologue in an isolated tree and hand back the paths it built.

    The probe script is copied into `tmp_path`, and run.sh cds to its own directory, so `$PWD/run`
    — the default for both roots — lands under tmp_path and nothing touches the real `run/`.
    """

    def _build(**env_extra: str) -> dict:
        probe = tmp_path / "run_probe.sh"
        probe.write_text(_prologue() + PROBE, encoding="utf-8")
        capture = tmp_path / "captures" / SCAN
        capture.mkdir(parents=True, exist_ok=True)

        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(tmp_path), **env_extra}
        proc = subprocess.run(
            ["bash", str(probe), str(capture)],
            capture_output=True, text=True, env=env, cwd=str(tmp_path), timeout=60,
        )
        assert proc.returncode == 0, f"prologue failed:\n{proc.stdout}\n{proc.stderr}"
        paths = json.loads(proc.stdout.strip().splitlines()[-1])
        return {k: Path(v) for k, v in paths.items()}

    return _build


def _stage_dirs(out: Path) -> list[Path]:
    return [out / "scene_init" / "obj_stage", out / "scene_init" / "scene_stage"]


def test_stage_dirs_are_not_inside_the_authoring_dir(layout):
    """The core invariant: whatever `run/<scan>/scene_init/*` names, it is not under stage 2."""
    p = layout()
    for d in _stage_dirs(p["out"]):
        assert d.exists(), f"{d} not created by run.sh"
        resolved = d.resolve()
        assert p["authoring"].resolve() not in resolved.parents, (
            f"{d} resolves to {resolved}, which is INSIDE the authoring dir "
            f"{p['authoring']} — deleting stage 2 would destroy stage 1"
        )


def test_object_stages_own_path_is_the_real_tree(layout):
    """`object_init.config.scene_init_dir()` returns `$LITEREALITY_FINAL/<scan>/scene_init`, and
    that is where the object stage opens its files. It has to BE the tree, not a link pointing
    somewhere else — comparing `d.resolve()` to it would pass vacuously, since with the default
    roots the two spellings are the same string."""
    p = layout()
    for d in _stage_dirs(p["out"]):
        physical = p["final_root"] / SCAN / "scene_init" / d.name
        assert physical.is_dir(), f"{physical} missing — the object stage writes there"
        assert not physical.is_symlink(), (
            f"{physical} is a symlink to {physical.resolve()}; the object stage's own path should "
            f"be the real directory"
        )


def test_default_roots_produce_one_real_directory(layout):
    """With both roots defaulting to `$PWD/run`, run.sh's own comment says `run/<scan>/` is one
    real directory and no symlink is made. It should not be quietly untrue."""
    p = layout()
    for d in _stage_dirs(p["out"]):
        assert not d.is_symlink(), f"{d} is a symlink even though both roots default to $PWD/run"


def test_split_roots_link_across_without_touching_stage_two(tmp_path, layout):
    """When the roots genuinely differ, the symlink path IS taken — that is what it is for — but
    it still points at stage 1's own tree, not into `realism_authoring/`."""
    final = tmp_path / "deliverables"
    p = layout(LITEREALITY_FINAL=str(final))
    for d in _stage_dirs(p["out"]):
        assert d.is_symlink(), f"{d} should be a symlink when the roots differ"
        resolved = d.resolve()
        assert resolved == (final / SCAN / "scene_init" / d.name).resolve()
        assert "realism_authoring" not in str(resolved)


def test_run_tag_shares_one_stage_one_tree(tmp_path, layout):
    """`RUN_TAG` isolates a *stage 2* re-run (its own `_oneshot_<tag>` dir and `<scan>_<tag>.html`).
    It must not fork stage 1 as well — that would re-run TRELLIS and the paid image-gen for a
    re-authoring pass that reuses the same seed."""
    plain = layout()
    tagged = layout(RUN_TAG="v2")
    assert tagged["authoring"] != plain["authoring"], "RUN_TAG should still isolate stage 2"
    for d, e in zip(_stage_dirs(tagged["out"]), _stage_dirs(plain["out"])):
        assert d.resolve() == e.resolve(), (
            f"RUN_TAG forked stage 1: {d.resolve()} != {e.resolve()}"
        )
