from __future__ import annotations

from pathlib import Path


def test_service_result_is_an_error_when_an_expected_glb_is_missing(tmp_path, monkeypatch):
    from litereality_agent.pipeline.scene_init.reconstruct import flow, service

    reference = tmp_path / "Chair0.png"
    reference.write_bytes(b"reference")
    output = tmp_path / "reconstructed"

    class EmptyService:
        name = "empty"

        def reconstruct_many(self, *_args, **_kwargs):
            return {"Chair0": str(output / "Chair0.glb")}

    monkeypatch.setattr(flow.config, "reconstruct_dir", lambda _scan: output)
    monkeypatch.setattr(flow, "collect_references", lambda _scan: [("Chair0", reference)])
    monkeypatch.setattr(service, "_SERVICE", EmptyService())

    result = flow.run_for_scan("scan")

    assert result["status"] == "failed"
    assert result["generated"] == 0
    assert result["failed_assets"] == ["Chair0"]


def test_flow_returns_nonzero_when_requested_assets_are_missing(monkeypatch):
    from litereality_agent.pipeline.scene_init import flow

    monkeypatch.setattr(flow, "resolve_scan", lambda *_args: (Path("capture"), "scan"))
    monkeypatch.setattr(flow, "process_scan", lambda *_args: {"scan": "scan"})
    monkeypatch.setattr(flow, "summarize", lambda _results: None)
    monkeypatch.setattr(flow, "_expected_assets", lambda _scan: ["Chair0"])
    monkeypatch.setattr(flow, "_missing_assets", lambda _scan, _expected: ["Chair0"])

    assert flow.main(["--scan", "capture", "--reconstruct"]) == 1


def test_flow_allows_a_room_with_no_expected_assets(monkeypatch):
    from litereality_agent.pipeline.scene_init import flow

    monkeypatch.setattr(flow, "resolve_scan", lambda *_args: (Path("capture"), "scan"))
    monkeypatch.setattr(flow, "process_scan", lambda *_args: {"scan": "scan"})
    monkeypatch.setattr(flow, "summarize", lambda _results: None)
    monkeypatch.setattr(flow, "_expected_assets", lambda _scan: [])
    monkeypatch.setattr(flow, "_missing_assets", lambda _scan, _expected: [])

    assert flow.main(["--scan", "capture", "--reconstruct"]) == 0


def _context(tmp_path: Path):
    from litereality_agent.pipeline.context import RunContext
    from litereality_agent.settings import LiteRealitySettings

    settings = LiteRealitySettings(repo_root=tmp_path, output_root=tmp_path / "run")
    return RunContext("scan", tmp_path / "capture", tmp_path / "run" / "scan", tmp_path / "run", settings=settings)


def _write_routing(context, names: list[str]) -> None:
    import json

    routing = context.object_root / "object_init" / "routing" / "routing_manifest.json"
    routing.parent.mkdir(parents=True, exist_ok=True)
    routing.write_text(
        json.dumps({"scans": {context.scan: [{"name": n} for n in names]}}), encoding="utf-8"
    )


def test_reconstruct_stage_is_not_complete_when_a_routed_object_has_no_glb(tmp_path):
    """The exact shape of the real incident: an OOM-killed batch leaves ChairCluster0 built and
    ChairCluster1/ChairCluster2 missing. The old check ("does any .glb exist") called this
    complete and a bare rerun would have silently reused the partial tree."""
    from litereality_agent.pipeline.scene_init.reconstruct import complete

    context = _context(tmp_path)
    _write_routing(context, ["ChairCluster0", "ChairCluster1", "ChairCluster2"])
    recon = context.object_root / "reconstructed_objs"
    recon.mkdir(parents=True)
    (recon / "ChairCluster0.glb").write_bytes(b"glb")

    assert complete(context) is False


def test_reconstruct_stage_is_complete_once_every_routed_object_and_opening_has_a_glb(tmp_path):
    from litereality_agent.pipeline.scene_init.reconstruct import complete

    context = _context(tmp_path)
    _write_routing(context, ["Table0"])
    opening = context.object_root / "object_init" / "opening_refs" / context.scan / "Wall0_Door_0"
    opening.mkdir(parents=True)

    recon = context.object_root / "reconstructed_objs"
    (recon / "Table0").mkdir(parents=True)
    (recon / "Table0" / "Table0.glb").write_bytes(b"glb")
    (recon / "Wall0_Door_0.glb").write_bytes(b"glb")

    assert complete(context) is True


def test_reconstruct_stage_falls_back_to_any_glb_when_there_is_no_routing_manifest(tmp_path):
    """No routing/opening manifest to check against (e.g. a hand-placed tree) — the stage falls
    back to the old, coarser signal instead of refusing to ever reuse it."""
    from litereality_agent.pipeline.scene_init.reconstruct import complete

    context = _context(tmp_path)
    recon = context.object_root / "reconstructed_objs"
    recon.mkdir(parents=True)
    (recon / "Whatever.glb").write_bytes(b"glb")

    assert complete(context) is True
