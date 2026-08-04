"""Bind model capabilities to local-process or RunPod execution runtimes."""

from __future__ import annotations

from litereality_agent.settings import LiteRealitySettings, load_settings


def gen3d_from_settings(settings: LiteRealitySettings | None = None):
    settings = settings or load_settings()
    if settings.runpod_trellis_endpoint:
        from litereality_agent.models.trellis.runpod import RunPodTrellisService

        return RunPodTrellisService(
            api_key=settings.runpod_api_key.get_secret_value() if settings.runpod_api_key else None,
            endpoint_id=settings.runpod_trellis_endpoint,
        )
    from litereality_agent.models.trellis.service import LocalTrellisService

    return LocalTrellisService(python=str(settings.trellis_python) if settings.trellis_python else None)


def detection_from_settings(settings: LiteRealitySettings | None = None):
    settings = settings or load_settings()
    if settings.runpod_dino_endpoint:
        from litereality_agent.models.grounding_dino.runpod import RunPodDinoService

        return RunPodDinoService(
            api_key=settings.runpod_api_key.get_secret_value() if settings.runpod_api_key else None,
            endpoint_id=settings.runpod_dino_endpoint,
            model_id=settings.dino_model,
            embed_model_id=settings.dino_embed_model,
        )
    if settings.dino_python:
        from litereality_agent.models.grounding_dino.service import DinoSubprocessService

        return DinoSubprocessService(python=str(settings.dino_python))
    return None
