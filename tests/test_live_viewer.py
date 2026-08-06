"""The live viewer's non-Blender halves: trace tailing, state, and the HTTP surface.

Compilation is deliberately not exercised — it spawns Blender, which the unit suite never does.
`LiveRoom.rebuild` is stubbed where a build is needed so the parts that run on every poll are
still covered.
"""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import urlopen

import pytest

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.realism_authoring import live


def _event(seq: int, t: float, **extra) -> str:
    return json.dumps({"seq": seq, "t": t, "dt": t - 100.0, **extra})


@pytest.fixture
def run_tree(tmp_path: Path) -> Path:
    scene = tmp_path / "run" / "Scan-1"
    (scene / "realism_authoring" / "room").mkdir(parents=True)
    (scene / "realism_authoring" / "room" / "Room.py").write_text("# room\n")
    (scene / "scene_init" / "obj_stage" / "traces").mkdir(parents=True)
    return scene


def _context(run_tree: Path) -> RunContext:
    return RunContext(
        scan="Scan-1",
        capture_dir=run_tree,
        scene_dir=run_tree,
        output_root=run_tree.parent,
    )


def test_trace_merges_files_in_wall_clock_order(run_tree: Path) -> None:
    traces = run_tree / "scene_init" / "obj_stage" / "traces"
    (traces / "trace.jsonl").write_text(_event(1, 100.0, kind="stage") + "\n")
    (traces / "authoring_trace.author.jsonl").write_text(
        _event(1, 101.0, kind="think", text="a") + "\n" + _event(2, 103.0, kind="tool") + "\n"
    )

    trace = live._Trace(live.trace_dirs(_context(run_tree)))
    trace.refresh()

    assert [e["t"] for e in trace.events] == [100.0, 101.0, 103.0]


def test_trace_tails_only_new_lines(run_tree: Path) -> None:
    path = run_tree / "scene_init" / "obj_stage" / "traces" / "trace.jsonl"
    path.write_text(_event(1, 100.0, kind="stage") + "\n")

    trace = live._Trace(live.trace_dirs(_context(run_tree)))
    trace.refresh()
    trace.refresh()  # nothing new — must not duplicate
    assert len(trace.events) == 1

    with path.open("a") as fh:
        fh.write(_event(2, 102.0, kind="tool") + "\n")
    trace.refresh()
    assert len(trace.events) == 2


def test_trace_ignores_a_partial_final_line(run_tree: Path) -> None:
    """A tracer mid-write leaves a line with no newline; it must be picked up on the next pass,
    not dropped and not parsed as truncated JSON."""
    path = run_tree / "scene_init" / "obj_stage" / "traces" / "trace.jsonl"
    path.write_text(_event(1, 100.0, kind="stage") + "\n" + '{"seq": 2, "t": 101.0, "kin')

    trace = live._Trace(live.trace_dirs(_context(run_tree)))
    trace.refresh()
    assert len(trace.events) == 1

    with path.open("a") as fh:
        fh.write('d": "tool"}\n')
    trace.refresh()
    assert [e["kind"] for e in trace.events] == ["stage", "tool"]


def test_trace_skips_raw_sibling(run_tree: Path) -> None:
    traces = run_tree / "scene_init" / "obj_stage" / "traces"
    (traces / "authoring_trace.author.jsonl").write_text(_event(1, 100.0, kind="tool") + "\n")
    (traces / "authoring_trace.author.raw.jsonl").write_text(_event(1, 100.0, kind="tool") + "\n")

    trace = live._Trace(live.trace_dirs(_context(run_tree)))
    trace.refresh()
    assert len(trace.events) == 1


def test_state_cursor_only_returns_new_events(run_tree: Path) -> None:
    path = run_tree / "scene_init" / "obj_stage" / "traces" / "trace.jsonl"
    path.write_text(_event(1, 100.0, kind="stage") + "\n")

    room = live.LiveRoom(_context(run_tree))
    room.trace.refresh()

    first = room.state(0)
    assert len(first["events"]) == 1 and first["cursor"] == 1
    assert room.state(first["cursor"])["events"] == []


def test_changed_fires_once_per_save(run_tree: Path) -> None:
    room = live.LiveRoom(_context(run_tree))
    assert room._changed() is True   # first look always builds
    assert room._changed() is False

    source = run_tree / "realism_authoring" / "room" / "Room.py"
    source.write_text("# edited\n")
    import os

    os.utime(source, (1_000_000, 1_000_000))
    assert room._changed() is True


def test_rebuild_records_failure_without_raising(run_tree: Path, monkeypatch) -> None:
    """A Room.py the agent has half-saved must leave the server up and say so on the page."""
    room = live.LiveRoom(_context(run_tree))

    def boom(*_a, **_k):
        raise RuntimeError("SyntaxError: unexpected EOF")

    monkeypatch.setattr("litereality_agent.room_ops.api.compile_room", boom)
    assert room.rebuild() is False
    assert room.state(0)["status"] == "failed"
    assert "unexpected EOF" in room.state(0)["error"]
    assert room.build == 0


def test_http_surface(run_tree: Path) -> None:
    room = live.LiveRoom(_context(run_tree))
    room.glb.write_bytes(b"glTF-not-really")
    room.build = 1

    server = ThreadingHTTPServer(("127.0.0.1", 0), live._handler(room, "Scan-1"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        home = urlopen(base + "/").read().decode()
        assert "Agent trace" in home and "Scan-1" in home

        state = json.loads(urlopen(base + "/state?since=0").read())
        assert state["build"] == 1

        assert urlopen(base + "/room.glb?b=1").read() == b"glTF-not-really"
    finally:
        server.shutdown()
        server.server_close()
