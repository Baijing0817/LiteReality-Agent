from __future__ import annotations

import base64
from types import SimpleNamespace

from litereality_agent.models.grounding_dino.runpod import RunPodDinoService


class Client:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.inputs = []

    def run(self, payload):
        self.inputs.append(payload)
        return f"job-{len(self.inputs)}"

    def status(self, job_id):
        return {"status": "COMPLETED", "output": self.outputs.pop(0)}

    def cancel(self, job_id):
        raise AssertionError("completed jobs must not be cancelled")


def test_detect_serializes_image_and_parses_boxes():
    client = Client([{"detections": [{"box": [1, 2, 3, 4], "score": 0.9, "label": "chair"}]}])
    service = RunPodDinoService(client=client, model_id="detector", poll_interval=0)

    detections = service.detect(b"png", "chair .", upright=False)

    assert base64.b64decode(client.inputs[0]["image_b64"]) == b"png"
    assert client.inputs[0]["model_id"] == "detector"
    assert detections[0].box_xyxy == (1.0, 2.0, 3.0, 4.0)
    assert detections[0].label == "chair"


def test_embed_uses_the_embedding_model():
    client = Client([{"embeddings": [[0.25, 0.75]]}])
    service = RunPodDinoService(client=client, embed_model_id="embedder", poll_interval=0)

    assert service.embed([b"one"]) == [[0.25, 0.75]]
    assert client.inputs[0]["op"] == "embed"
    assert client.inputs[0]["model_id"] == "embedder"


def test_registry_prefers_hosted_dino(monkeypatch):
    from litereality_agent.models import registry

    settings = SimpleNamespace(
        runpod_dino_endpoint="dino-endpoint",
        runpod_api_key=SimpleNamespace(get_secret_value=lambda: "secret"),
        dino_model="detector",
        dino_embed_model="embedder",
        dino_python=None,
    )
    service = registry.detection_from_settings(settings)

    assert isinstance(service, RunPodDinoService)
    assert service.model_id == "detector"
    assert service.embed_model_id == "embedder"
