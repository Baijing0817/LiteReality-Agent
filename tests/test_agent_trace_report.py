"""The report must render what the trace now records.

The trace was deepened (full tool inputs, tool results, per-call timing, a verbatim sidecar)
but the report rendered only the old fields, so the detail existed on disk and was invisible.
These build a real report from a synthetic trace and assert the new data reaches the page.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from litereality_agent.agent import trace_report

SEED = "SHELL = {'walls': {}}\n"
AUTHORED = "SHELL = {'walls': {'Wall0': 1}}\n"


def _write_trace(traces: Path, name: str, events: list[dict]) -> None:
    traces.mkdir(parents=True, exist_ok=True)
    (traces / name).write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


@pytest.fixture
def scene(tmp_path: Path) -> Path:
    """A scene package with one authoring trace containing a failed and a successful call."""
    scene = tmp_path / "run" / "Office_room"
    traces = scene / "scene_init" / "obj_stage" / "traces"
    _write_trace(traces, "authoring_trace.author.jsonl", [
        {"seq": 1, "dt": 0.0, "kind": "session_start", "pass": "author", "model": "claude-opus-5",
         "profile": "detail", "max_turns": 140, "prompt": "AUTHOR THE ROOM: unique-prompt-marker"},
        {"seq": 2, "dt": 1.2, "kind": "think", "text": "Checking the dado band first."},
        {"seq": 3, "dt": 1.3, "kind": "tool", "tool": "Bash", "n": 1, "id": "tu_1",
         "hint": "measure dado", "args": {"command": "python3 -c 'print(1)'  # unique-command-marker",
                                          "description": "Measure dado band on Wall2"}},
        {"seq": 4, "dt": 3.9, "kind": "result", "id": "tu_1", "tool": "Bash", "secs": 2.6,
         "chars": 24, "output": "dado top at 0.94 m  # unique-output-marker"},
        {"seq": 5, "dt": 4.0, "kind": "tool", "tool": "render", "n": 1, "id": "tu_2",
         "hint": "Wall2", "args": {"target": "Wall2"}},
        {"seq": 6, "dt": 9.0, "kind": "result", "id": "tu_2", "tool": "render", "secs": 5.0,
         "is_error": True, "chars": 12, "output": "Blender exited 1"},
        {"seq": 7, "dt": 9.1, "kind": "session_end", "calls": 2, "seconds": 9.1,
         "cost_usd": 0.42, "summary": "done"},
    ])
    room = scene / "realism_authoring" / "room"
    room.mkdir(parents=True)
    (room / "Room.py").write_text(AUTHORED, encoding="utf-8")
    seed = scene / "scene_init" / "scene_stage" / "room_init" / "room"
    seed.mkdir(parents=True)
    (seed / "Room.py").write_text(SEED, encoding="utf-8")
    return scene


def _build(scene: Path, tmp_path: Path) -> str:
    out = tmp_path / "report.html"
    trace_report.build(scene, out)
    return out.read_text(encoding="utf-8")


def test_the_prompt_reaches_the_report(scene: Path, tmp_path: Path):
    """Every decision in the run was a response to it; without it the timeline is unreadable."""
    assert "unique-prompt-marker" in _build(scene, tmp_path)


def test_full_command_and_output_reach_the_report(scene: Path, tmp_path: Path):
    """The two halves that used to be dropped: the method, and what it answered."""
    html = _build(scene, tmp_path)
    assert "unique-command-marker" in html
    assert "unique-output-marker" in html


def test_a_failed_call_is_marked(scene: Path, tmp_path: Path):
    html = _build(scene, tmp_path)
    assert 'class="err"' in html
    assert "Blender exited 1" in html


def test_per_call_timing_is_shown(scene: Path, tmp_path: Path):
    html = _build(scene, tmp_path)
    assert "2.6s" in html and "5.0s" in html


def test_results_are_not_also_rendered_as_their_own_rows(scene: Path, tmp_path: Path):
    """A result belongs inside the call it answers; as a sibling row it doubles the timeline."""
    html = _build(scene, tmp_path)
    assert html.count("unique-output-marker") == 1


def test_the_authored_room_is_found_in_realism_authoring(scene: Path, tmp_path: Path):
    """The work room moved out of scene_stage/_oneshot; the diff must follow it or read empty."""
    html = _build(scene, tmp_path)
    assert "Wall0" in html and "+1" in html


def test_the_legacy_oneshot_room_still_diffs(scene: Path, tmp_path: Path):
    """A run made before the move must not silently render an empty diff."""
    import shutil

    shutil.rmtree(scene / "realism_authoring")
    legacy = scene / "scene_init" / "scene_stage" / "_oneshot" / "room"
    legacy.mkdir(parents=True)
    (legacy / "Room.py").write_text(AUTHORED, encoding="utf-8")
    assert "Wall0" in _build(scene, tmp_path)


def test_every_pass_is_loaded_not_just_the_named_ones(scene: Path, tmp_path: Path):
    """The loader listed `author` and `materials` by name, so a qc run rendered an empty page."""
    traces = scene / "scene_init" / "obj_stage" / "traces"
    _write_trace(traces, "authoring_trace.qc.jsonl", [
        {"seq": 1, "dt": 0.0, "kind": "think", "text": "qc-pass-marker"}])
    assert "qc-pass-marker" in _build(scene, tmp_path)


def test_the_raw_sidecar_is_rendered_and_excluded_from_the_timeline(scene: Path, tmp_path: Path):
    traces = scene / "scene_init" / "obj_stage" / "traces"
    (traces / "authoring_trace.author.raw.jsonl").write_text(
        json.dumps({"t": 1.0, "dt": 0.5,
                    "msg": {"__type__": "AssistantMessage",
                            "content": [{"__type__": "TextBlock", "text": "raw-marker"}]}}) + "\n",
        encoding="utf-8")
    html = _build(scene, tmp_path)
    assert "raw-marker" in html
    assert 'id="raw"' in html
    # The sidecar must not be parsed as timeline events — it has no `kind`, and counting it
    # there would inflate every figure in the header.
    events = trace_report.load_trace(traces)
    assert all("msg" not in e for e in events)


def test_a_run_with_no_sidecar_says_so(scene: Path, tmp_path: Path):
    assert "LR_TRACE_RAW=0" in _build(scene, tmp_path)
