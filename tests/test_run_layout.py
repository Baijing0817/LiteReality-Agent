"""The Python composition root owns run layout; the shell file only delegates."""

from pathlib import Path

from litereality_agent.pipeline.context import RunContext
from litereality_agent.shared.settings import LiteRealitySettings


def context(tmp_path: Path) -> RunContext:
    capture = tmp_path / "captures" / "Office"
    capture.mkdir(parents=True)
    (capture / "room.usdz").touch()
    settings = LiteRealitySettings(
        repo_root=tmp_path,
        scans_dir=capture.parent,
        output_root=tmp_path / "run",
    )
    return RunContext.resolve(capture, settings=settings)


def test_stage_one_and_authoring_are_siblings(tmp_path):
    ctx = context(tmp_path)
    assert ctx.init_root.parent == ctx.authoring_root.parent == ctx.scene_dir
    assert ctx.authoring_root not in ctx.init_root.parents
    assert ctx.init_root not in ctx.authoring_root.parents


def test_context_has_one_canonical_output_tree(tmp_path):
    ctx = context(tmp_path)
    assert ctx.scene_dir == tmp_path / "run" / "Office"
    assert ctx.object_root == ctx.scene_dir / "scene_init" / "obj_stage"
    assert ctx.seed_room == ctx.scene_dir / "scene_init" / "scene_stage" / "room_init" / "room"


def test_shell_launcher_contains_no_pipeline_logic():
    run_sh = (Path(__file__).resolve().parents[1] / "run.sh").read_text(encoding="utf-8")
    assert 'exec uv run litereality run "$@"' in run_sh
    assert "stage(){" not in run_sh
