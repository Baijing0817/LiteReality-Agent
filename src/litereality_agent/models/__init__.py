"""Model registry + providers.

The reasoning agent runs on one of two local CLIs — `claude_cli` (`claude`) or `codex_cli` (`codex`):

    from litereality_agent.models import ProviderConfig, create_provider_client
    llm = create_provider_client(ProviderConfig(provider="claude_cli"))   # or "codex_cli"
    registry = ModelRegistry(); registry.register("llm", llm)

Non-LLM model roles (vlm/detect/gen3d/imagegen) are registered the same way — see base.py.
`config.load_env` also lives here: the repo `.env` loader every entry point calls once.

LAYER 1 — sits above backends (it dispatches to them) and below everything else.
May depend on backends. Must not depend on init, authoring, integration or cli.
"""

from litereality_agent.models.base import (
    Critique,
    Detection,
    DetectionService,
    Generation3DService,
    ImageGenService,
    LLMProvider,
    ModelRegistry,
    VisionCritiqueService,
)
from litereality_agent.models.dino import DinoSubprocessService
from litereality_agent.models.factory import (
    ProviderConfig,
    ProviderConstructors,
    build_model_registry,
    create_provider_client,
    default_model_id,
    detect_from_env,
    gen3d_for_route,
    gen3d_from_env,
    normalize_provider_name,
    validate_provider_credentials,
)
from litereality_agent.models.local_trellis import LocalTrellisService
from litereality_agent.models.names import ProviderName
from litereality_agent.models.procedural import ProceduralService
from litereality_agent.models.runpod_trellis import RunPodTrellisService

__all__ = [
    "ModelRegistry",
    "LLMProvider",
    "DetectionService",
    "Generation3DService",
    "ImageGenService",
    "VisionCritiqueService",
    "Detection",
    "Critique",
    "DinoSubprocessService",
    "RunPodTrellisService",
    "LocalTrellisService",
    "ProceduralService",
    "ProviderConfig",
    "ProviderConstructors",
    "ProviderName",
    "create_provider_client",
    "validate_provider_credentials",
    "default_model_id",
    "normalize_provider_name",
    "gen3d_from_env",
    "gen3d_for_route",
    "detect_from_env",
    "build_model_registry",
]
