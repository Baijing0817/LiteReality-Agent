"""The capability tools the authoring model is handed must actually be callable.

Stage 3 offers the model four tools it cannot substitute with file editing (`author.py`
CAPABILITY_TOOLS). If one of them is missing from the registry, mis-schema'd, or dies before it
reaches its real work, the run does not fail — the model simply stops using it and authors the room
blind. That is a silent quality loss, which is exactly the failure mode worth a test.

Offline by design: these check reachability and wiring, not pixels. A test that renders needs
Blender plus a real scan and is marked `blender`.
"""

from __future__ import annotations

import pytest

from litereality_agent.pipeline.author.agent import CAPABILITY_TOOLS, build_capability_server
from litereality_agent.pipeline.author.tools import build_default_registry


@pytest.fixture(scope="module")
def registry():
    return build_default_registry()


@pytest.mark.parametrize("name", CAPABILITY_TOOLS)
def test_capability_tool_is_registered(registry, name):
    """A renamed or dropped tool must break here, not degrade a $7 authoring run."""
    assert registry.get_tool(name) is not None, f"{name} is offered to the model but not registered"


@pytest.mark.parametrize("name", CAPABILITY_TOOLS)
def test_capability_tool_schema_is_well_formed(registry, name):
    """`build_capability_server` reads `schema["function"]["description"|"parameters"]` directly and
    would raise KeyError at harness start-up; assert the shape the SDK requires."""
    fn = registry.get_tool(name).schema["function"]
    assert fn["name"] == name
    assert fn["description"].strip(), f"{name} has no description — the model cannot know when to call it"
    params = fn["parameters"]
    assert params.get("type") == "object" and "properties" in params


def test_render_is_among_the_capabilities():
    """The image tool specifically: the prompt instructs the model to render and READ the PNG
    (`author.py` "render, look, correct"), so its absence would gut the self-check loop."""
    assert "render" in CAPABILITY_TOOLS
    assert "select_views" in CAPABILITY_TOOLS, "render auto-picks frames through select_views"


def test_capability_server_exposes_prefixed_names(tmp_path):
    """The allow-list must match the MCP names the SDK will emit, or every call is refused."""
    server, allowed = build_capability_server(tmp_path, CAPABILITY_TOOLS)
    assert server is not None
    assert allowed == [f"mcp__cap__{n}" for n in CAPABILITY_TOOLS]


@pytest.mark.parametrize("target", ["room", "Wall0"])
def test_render_params_accept_the_targets_the_prompt_asks_for(target):
    """The prompt tells the model to call `render(target='room')` and `render(target='Wall<N>')`;
    validation must not reject either, and `frames` must stay optional (auto-select)."""
    from litereality_agent.pipeline.author.tools.render.tool import RenderParams

    p = RenderParams(target=target)
    assert p.target == target and p.frames is None


def test_select_views_reaches_its_data_layer(stage_tree):
    """Integration guard for the LAYOUT contract, which is what actually broke.

    Bound to a room addressed through the `output` symlink, `select_views` must get past scan
    inference and config resolution and fail only for want of scan DATA (no `room.usdz` in this
    fixture). Any "could not infer scan" here means the image tools are dead again.

    Driven with `asyncio.run` rather than an async test so the suite needs no asyncio plugin.
    """
    import asyncio

    from litereality_agent.pipeline.author.tools.select_views.tool import (
        SelectViewsInvocation,
        SelectViewsParams,
    )

    inv = SelectViewsInvocation(SelectViewsParams(target="room", n=2))
    inv.bind(str(stage_tree.symlinked_room), None)
    res = asyncio.run(inv.execute())

    assert not res.is_success(), "fixture has no scan data; a success here means the assert is stale"
    assert "could not infer scan" not in (res.error or ""), (
        f"scan inference regressed — the image tools cannot run: {res.error}"
    )


@pytest.mark.scan
@pytest.mark.parametrize("target", ["room", "Wall0"])
def test_select_views_picks_frames_on_real_scan_data(target):
    """End-to-end on a REAL room, through the `output/…` spelling that used to fail.

    This is the stage that died in the recorded run ("view selection failed"), and it is what
    `render` calls whenever the model omits `frames` — which is how the prompt tells it to call it.
    No Blender needed: view selection only reads the capture poses.

    Opt-in (`-m scan`) because it needs capture data. Point `$LR_SCANS_DIR` at a directory holding
    `<scan>/{frame_*.jpg,frame_*.json,roomplan/room.usdz}`.
    """
    import asyncio
    import os
    from pathlib import Path

    scan = os.environ.get("LITEREALITY_SCAN", "Office-Elliott")
    repo = Path(__file__).resolve().parents[1]
    scans = Path(os.environ.get("LR_SCANS_DIR") or repo / "scans_uploaded")
    room = repo / "run" / scan / "scene_init" / "scene_stage" / "_oneshot" / "room"
    if not (scans / scan / "roomplan" / "room.usdz").is_file() or not room.is_dir():
        pytest.skip(f"no capture data for {scan} under {scans}")

    from litereality_agent.pipeline.author.tools.select_views.tool import (
        SelectViewsInvocation,
        SelectViewsParams,
    )

    inv = SelectViewsInvocation(SelectViewsParams(target=target, n=3))
    inv.bind(str(room), None)
    res = asyncio.run(inv.execute())

    assert res.is_success(), f"view selection failed for {target}: {res.error}"
    frames = res.output["frames"]
    assert frames, f"no frames picked for {target}"
    assert all(isinstance(f["frame"], int) for f in frames)
