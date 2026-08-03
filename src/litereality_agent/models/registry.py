"""Bind model capabilities to local-process or hosted execution runtimes."""

from __future__ import annotations

from litereality_agent.settings import LiteRealitySettings, load_settings


def gen3d_from_settings(settings: LiteRealitySettings | None = None):
    settings = settings or load_settings()
    if settings.modal_trellis_app:
        if not settings.modal_profile:
            raise RuntimeError("MODAL_PROFILE must be set when using hosted TRELLIS.")
        from litereality_agent.models.trellis.modal import ModalTrellisService

        return ModalTrellisService(
            app_name=settings.modal_trellis_app,
            function_name=settings.modal_trellis_function,
            environment_name=settings.modal_environment,
            profile=settings.modal_profile,
        )
    if settings.trellis_python:
        from litereality_agent.models.trellis.service import LocalTrellisService

        return LocalTrellisService(python=str(settings.trellis_python))
    raise RuntimeError(
        "TRELLIS is not configured: set MODAL_TRELLIS_APP for hosted execution or "
        "TRELLIS_PYTHON for an explicit local GPU runtime."
    )


def detection_from_settings(settings: LiteRealitySettings | None = None):
    settings = settings or load_settings()
    if settings.modal_dino_app:
        if not settings.modal_profile:
            raise RuntimeError("MODAL_PROFILE must be set when using hosted DINO.")
        from litereality_agent.models.grounding_dino.modal import ModalDinoService

        return ModalDinoService(
            app_name=settings.modal_dino_app,
            function_name=settings.modal_dino_function,
            environment_name=settings.modal_environment,
            profile=settings.modal_profile,
            model_id=settings.dino_model,
            embed_model_id=settings.dino_embed_model,
        )
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
