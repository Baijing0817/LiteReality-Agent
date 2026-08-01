"""A long authoring session must not be able to lose its work.

`run.sh` runs authoring as a HARD stage — a non-zero exit aborts the whole pipeline. The SDK
raises when `--max-turns` is reached, so a 200-turn session that used its budget threw away
every edit it had made and killed the run, despite `Room.py` being edited IN PLACE and sitting
valid on disk the entire time. Running out of turns means "time's up", not "this is broken".

What actually matters downstream is narrow: every later stage (materials, refine, qc, export)
builds `Room.py`, so it must be valid Python. That is what these pin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from litereality_agent.realism_authoring.author import checkpoint, room_compiles

GOOD = "SHELL = {'walls': {}}\n\n\ndef build():\n    return SHELL\n"
BROKEN = "SHELL = {'walls': {\n\ndef build(:\n"


@pytest.fixture
def room(tmp_path: Path) -> Path:
    d = tmp_path / "realism_authoring" / "room"
    d.mkdir(parents=True)
    (d / "Room.py").write_text(GOOD, encoding="utf-8")
    return d


def test_a_valid_room_reports_no_error(room: Path):
    assert room_compiles(room) == ""


def test_a_broken_room_is_reported_with_the_line(room: Path):
    (room / "Room.py").write_text(BROKEN, encoding="utf-8")
    err = room_compiles(room)
    assert err and "line" in err


def test_a_missing_room_is_an_error_not_a_crash(tmp_path: Path):
    assert room_compiles(tmp_path) != ""


def test_only_a_compiling_room_is_checkpointed(room: Path, tmp_path: Path):
    """Saving a broken file as last-known-good would defeat the entire mechanism."""
    ckpt = tmp_path / ".room_checkpoint.py"
    assert checkpoint(room, ckpt) is True
    assert ckpt.read_text() == GOOD

    (room / "Room.py").write_text(BROKEN, encoding="utf-8")
    assert checkpoint(room, ckpt) is False
    assert ckpt.read_text() == GOOD, "the checkpoint must still hold the last GOOD version"


def test_the_checkpoint_advances_with_each_good_edit(room: Path, tmp_path: Path):
    """A break should cost one edit, not the run — so the newest compiling version wins."""
    ckpt = tmp_path / ".room_checkpoint.py"
    checkpoint(room, ckpt)
    later = GOOD + "\nWALL_COLOUR = (0.8, 0.8, 0.75)\n"
    (room / "Room.py").write_text(later, encoding="utf-8")
    assert checkpoint(room, ckpt) is True
    assert "WALL_COLOUR" in ckpt.read_text()


def test_restoring_a_checkpoint_yields_a_compiling_room(room: Path, tmp_path: Path):
    """The recovery path the run performs when a session dies mid-edit."""
    ckpt = tmp_path / ".room_checkpoint.py"
    checkpoint(room, ckpt)
    (room / "Room.py").write_text(BROKEN, encoding="utf-8")
    assert room_compiles(room) != ""

    (room / "Room.py").write_bytes(ckpt.read_bytes())  # what run() does
    assert room_compiles(room) == ""


def test_the_checkpoint_lives_outside_the_room(room: Path):
    """The room dir is copied and scanned wholesale downstream; a second Room-ish .py inside it
    would be picked up as scene code."""
    ckpt = room.parent / ".room_checkpoint.py"
    checkpoint(room, ckpt)
    assert ckpt.is_file()
    assert ckpt.parent != room
    assert not list(room.glob("*checkpoint*"))
