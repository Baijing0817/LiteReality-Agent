"""Select local or hosted implementations for pipeline model capabilities."""

from __future__ import annotations

from litereality_agent.settings import LiteRealitySettings, load_settings


def gen3d_from_settings(settings: LiteRealitySettings | None = None):
    settings = settings or load_settings()
    if settings.runpod_trellis_endpoint:
        from litereality_agent.models.trellis.hosted.service import RunPodTrellisService

        return RunPodTrellisService(
            api_key=settings.runpod_api_key.get_secret_value() if settings.runpod_api_key else None,
            endpoint_id=settings.runpod_trellis_endpoint,
        )
    from litereality_agent.models.trellis.local.service import LocalTrellisService

    return LocalTrellisService(python=str(settings.trellis_python) if settings.trellis_python else None)


def gen3d_for_route(route: str, settings: LiteRealitySettings | None = None):
    if route.strip().lower() == "procedural":
        from litereality_agent.models.procedural.local.service import ProceduralService

        return ProceduralService()
    return gen3d_from_settings(settings)


def detection_from_settings(settings: LiteRealitySettings | None = None):
    settings = settings or load_settings()
    if settings.runpod_dino_endpoint:
        from litereality_agent.models.grounding_dino.hosted.service import RunPodDinoService

        return RunPodDinoService(
            api_key=settings.runpod_api_key.get_secret_value() if settings.runpod_api_key else None,
            endpoint_id=settings.runpod_dino_endpoint,
            model_id=settings.dino_model,
            embed_model_id=settings.dino_embed_model,
        )
    if settings.dino_python:
        from litereality_agent.models.grounding_dino.local.service import DinoSubprocessService

        return DinoSubprocessService(python=str(settings.dino_python))
    return None
