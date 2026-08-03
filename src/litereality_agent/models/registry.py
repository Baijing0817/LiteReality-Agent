"""Bind model capabilities to local-process or hosted execution runtimes."""

from __future__ import annotations

from litereality_agent.settings import LiteRealitySettings, load_settings


def gen3d_from_settings(settings: LiteRealitySettings | None = None):
    settings = settings or load_settings()
    if settings.modal_trellis_app:
        from litereality_agent.models.trellis.modal import ModalTrellisService

        return ModalTrellisService(
            app_name=settings.modal_trellis_app,
            function_name=settings.modal_trellis_function,
            environment_name=settings.modal_environment,
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
