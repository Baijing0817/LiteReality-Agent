"""The run trace — the record of what an authoring pass actually did.

Two failures already happened here and both were invisible from inside a run: the passes shared one
trace file so the later pass wiped the earlier one, and the tool accounting reads fields off a block
type that does not carry them. Neither breaks a run; both destroy the evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from litereality_agent.realism_authoring.run_trace import RunTrace


def _events(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_each_pass_writes_its_own_file(tmp_path):
    """THE REGRESSION (fixed in 30a1778): every pass truncates its file on start, so a shared path
    meant the materials pass destroyed the authoring pass's trace mid-run."""
    author = RunTrace("author", room=tmp_path)
    author.start(model="m")
    author.tool("Read", {"file_path": "/x/Wall0_stitched.jpg"})

    materials = RunTrace("materials", room=tmp_path)
    materials.start(model="m")

    assert author.path != materials.path
    assert len(_events(author.path)) == 2, "the second pass truncated the first pass's trace"


def test_edit_events_name_the_file_and_the_size_of_the_change(tmp_path):
    tr = RunTrace("author", room=tmp_path)
    tr.tool("Edit", {"file_path": "/room/Room.py", "old_string": "a\nb", "new_string": "a\nb\nc\nd"})

    (event,) = [e for e in _events(tr.path) if e["kind"] == "tool"]
    assert event["tool"] == "Edit" and event["file"] == "Room.py"
    assert event["delta_lines"] == 2


def test_mcp_prefixes_are_stripped_so_tools_count_under_one_name(tmp_path):
    """The model calls `mcp__cap__render`; the report is about `render`. Without stripping, the same
    tool is counted twice under two names."""
    tr = RunTrace("author", room=tmp_path)
    tr.tool("mcp__cap__render", {"target": "Wall0"})
    tr.tool("render", {"target": "Wall1"})

    events = [e for e in _events(tr.path) if e["kind"] == "tool"]
    assert [e["tool"] for e in events] == ["render", "render"]
    assert [e["n"] for e in events] == [1, 2]


def test_end_records_the_totals(tmp_path):
    tr = RunTrace("author", room=tmp_path)
    tr.tool("Read", {"file_path": "/x.jpg"})
    tr.end(calls=1, cost_usd=1.5, summary="done")

    (end,) = [e for e in _events(tr.path) if e["kind"] == "session_end"]
    assert end["calls"] == 1 and end["cost_usd"] == 1.5 and end["counts"] == {"Read": 1}


def test_a_broken_trace_never_breaks_the_run(tmp_path):
    """A trace is telemetry. If its directory is unwritable the pass must continue regardless."""
    tr = RunTrace("author", room=tmp_path)
    tr.path.parent.chmod(0o500)
    try:
        tr.tool("Read", {"file_path": "/x.jpg"})  # must not raise
        tr.end(calls=1)
    finally:
        tr.path.parent.chmod(0o700)


def test_tool_result_block_carries_no_name_or_input():
    """Pins the SDK fact behind the accounting bug below: a `ToolResultBlock` has only
    `tool_use_id`, `content` and `is_error`. Anything that needs the tool NAME or its ARGUMENTS must
    read the `ToolUseBlock`. If a future SDK adds these fields, this test fails and the workaround
    can be revisited.
    """
    from claude_agent_sdk import ToolResultBlock

    fields = set(ToolResultBlock.__dataclass_fields__)
    assert fields == {"tool_use_id", "content", "is_error"}
    assert "name" not in fields and "input" not in fields


@pytest.mark.xfail(
    strict=True,
    reason="live bug: 113eff7 moved the per-tool counts and stitch-coverage tracking into the "
    "ToolResultBlock branch (author.py:289-298), which carries neither name nor input — so a real "
    "run prints calls=88 {'?': 88} and marks every stitch NEVER OPENED. Delete this marker when "
    "the four statements move back under `elif b == \"ToolUseBlock\"`.",
)
def test_stitch_coverage_is_tracked_where_the_tool_name_exists():
    """Source-level check: `read_surfaces` is the guardrail that reports whether the model actually
    opened each head-on stitch. It must be populated in the branch that has `input`.

    Checked statically because the accounting is inline in `author.run()` around a live `query()`
    call; extracting it is the fix, not the test.
    """
    src = (Path(__file__).resolve().parents[1] / "src" / "litereality_agent" / "realism_authoring" / "author.py").read_text()
    after_result_branch = src.split('elif b == "ToolResultBlock":', 1)[1]
    assert "read_surfaces.add" not in after_result_branch, (
        "coverage tracking sits in the ToolResultBlock branch, where input is always empty"
    )
