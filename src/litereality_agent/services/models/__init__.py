"""Provider-neutral model protocols and value objects."""

from litereality_agent.services.models.base import (
    Critique,
    Detection,
    DetectionService,
    Generation3DService,
    ImageGenService,
    LLMProvider,
    ModelRegistry,
    VisionCritiqueService,
)
from litereality_agent.services.models.names import ProviderName, normalize_provider_name

__all__ = [
    "Critique",
    "Detection",
    "DetectionService",
    "Generation3DService",
    "ImageGenService",
    "LLMProvider",
    "ModelRegistry",
    "ProviderName",
    "VisionCritiqueService",
    "normalize_provider_name",
]
