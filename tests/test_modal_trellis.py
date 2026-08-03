from __future__ import annotations

import base64
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


class FakeClient:
    def __init__(self, outputs):
        self.outputs = outputs
        self.inputs = None

    def map(self, inputs):
        self.inputs = list(inputs)
        return self.outputs


def test_pipeline_installs_background_bypass_before_model_construction(monkeypatch):
    from litereality_agent.models.trellis import inference

    calls = []

    class Pipeline:
        @classmethod
        def from_pretrained(cls, model_name):
            calls.append(("load", model_name))
            return cls()

        def cuda(self):
            calls.append(("cuda", None))

    torch = ModuleType("torch")
    torch.backends = SimpleNamespace(cudnn=SimpleNamespace(enabled=True))
    trellis = ModuleType("trellis2")
    pipelines = ModuleType("trellis2.pipelines")
    pipelines.Trellis2ImageTo3DPipeline = Pipeline
    trellis.pipelines = pipelines
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "trellis2", trellis)
    monkeypatch.setitem(sys.modules, "trellis2.pipelines", pipelines)
    monkeypatch.setattr(inference, "install_noop_rembg", lambda: calls.append(("bypass", None)))

    inference.load_pipeline("model")

    assert calls == [("bypass", None), ("load", "model"), ("cuda", None)]


def test_modal_trellis_maps_model_payloads_and_writes_outputs(tmp_path):
    from litereality_agent.models.trellis.modal import ModalTrellisService

    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"first-image")
    second.write_bytes(b"second-image")
    client = FakeClient(
        [
            {"glb_b64": base64.b64encode(b"first-glb").decode()},
            {"glb_b64": base64.b64encode(b"second-glb").decode()},
        ]
    )
    service = ModalTrellisService(app_name="unused", client=client)

    results = service.reconstruct_many(
        {"Chair0": first, "Chair1": second},
        out_dir=str(tmp_path / "out"),
        seed=7,
        simplify=0.9,
        texture_size=512,
    )

    assert base64.b64decode(client.inputs[0]["image_b64"]) == b"first-image"
    assert client.inputs[0] == {
        "image_b64": client.inputs[0]["image_b64"],
        "seed": 7,
        "simplify": 0.9,
        "texture_size": 512,
    }
    assert Path(results["Chair0"]).read_bytes() == b"first-glb"
    assert Path(results["Chair1"]).read_bytes() == b"second-glb"
    assert service.last_report.ok_count == 2


def test_modal_trellis_isolates_model_reported_errors(tmp_path):
    from litereality_agent.models.trellis.modal import ModalTrellisService

    client = FakeClient([{"error": "generation failed"}])
    service = ModalTrellisService(app_name="unused", client=client)
    results = service.reconstruct_many({"Chair0": b"image"}, out_dir=str(tmp_path))

    assert results == {"Chair0": ""}
    assert service.last_report.ok_count == 0
    assert service.last_report.assets[0].error == "generation failed"


def test_registry_selects_modal_trellis(monkeypatch):
    from litereality_agent.models import registry

    captured = {}

    class Service:
        def __init__(self, **options):
            captured.update(options)

    monkeypatch.setattr("litereality_agent.models.trellis.modal.ModalTrellisService", Service)
    settings = SimpleNamespace(
        modal_trellis_app="litereality-trellis",
        modal_trellis_function="generate",
        modal_environment="main",
    )

    assert isinstance(registry.gen3d_from_settings(settings), Service)
    assert captured == {
        "app_name": "litereality-trellis",
        "function_name": "generate",
        "environment_name": "main",
    }


def test_modal_client_uses_named_function_map():
    from litereality_agent.runtimes.modal import ModalClient

    class Function:
        def map(self, inputs, *, return_exceptions):
            assert return_exceptions is True
            return ({"value": item["value"] * 2} for item in inputs)

    client = ModalClient("unused", "unused", function=Function())
    assert client.map([{"value": 2}, {"value": 3}]) == [{"value": 4}, {"value": 6}]
