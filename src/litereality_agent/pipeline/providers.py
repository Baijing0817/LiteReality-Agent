"""Provider factory.

`create_provider_client(ProviderConfig)` resolves a reasoning-provider name → a concrete
`LLMProvider`. Two providers are supported, both LOCAL CLIs (no API key): `claude_cli` (`claude`,
Claude Code) and `codex_cli` (`codex`, OpenAI Codex). `validate_provider_credentials` checks the
binary is on PATH. Constructors are injectable for testing (`ProviderConstructors`).

The gen3d (image→GLB) and detect (GroundingDINO) env resolvers also live here — one source of truth
for the whole pipeline.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass

from litereality_agent.adapters.agents.claude import (
    CLAUDE_CLI_BIN_ENV,
    DEFAULT_CLAUDE_CLI_MODEL,
    ClaudeCliLLM,
)
from litereality_agent.adapters.agents.codex import (
    CODEX_CLI_BIN_ENV,
    DEFAULT_CODEX_CLI_MODEL,
    CodexCliLLM,
)
from litereality_agent.services.models.base import LLMProvider, ModelRegistry
from litereality_agent.services.models.names import ProviderName, normalize_provider_name

__all__ = [
    "ProviderConfig",
    "ProviderConstructors",
    "create_provider_client",
    "validate_provider_credentials",
    "default_model_id",
    "normalize_provider_name",
    "gen3d_from_env",
    "gen3d_for_route",
    "detect_from_env",
    "build_model_registry",
]


def gen3d_from_env():
    """The configured `gen3d` (image→GLB) backend — one source of truth for the whole pipeline.

    RunPod TRELLIS when `$RUNPOD_TRELLIS_ENDPOINT` is set (on-demand cloud, parallel), else the
    on-box LocalTrellisService. Both implement Generation3DService, so callers are identical.
    """
    if os.environ.get("RUNPOD_TRELLIS_ENDPOINT", "").strip():
        from litereality_agent.adapters.trellis.remote.service import RunPodTrellisService

        return RunPodTrellisService()
    from litereality_agent.adapters.trellis.local.service import LocalTrellisService

    return LocalTrellisService()


def gen3d_for_route(route: str):
    """Pick the gen3d backend for a per-object routing decision (classify_complexity):
    'procedural' → the LLM-agent articulated backend (ProceduralService); anything else
    ('trellis') → neural TRELLIS via gen3d_from_env(). This is the registry view of the
    procedural-vs-TRELLIS router — both are Generation3DService, so the caller is identical."""
    if (route or "").strip().lower() == "procedural":
        from litereality_agent.adapters.procedural.service import ProceduralService

        return ProceduralService()
    return gen3d_from_env()


def detect_from_env():
    """The `detect` (GroundingDINO) backend when `$LR_DINO_PYTHON` is set, else None (in-process)."""
    if os.environ.get("LR_DINO_PYTHON", "").strip():
        from litereality_agent.adapters.grounding_dino.service import DinoSubprocessService

        return DinoSubprocessService()
    return None


def build_model_registry(
    config: ProviderConfig | None = None, *, dry_run: bool = False
) -> ModelRegistry:
    """Wire every configured model backend from env into one registry.

    llm  ← create_provider_client(config)   gen3d ← gen3d_from_env()   detect ← detect_from_env()
    (vlm/imagegen register the same way once their wrappers land).
    """
    reg = ModelRegistry()
    reg.register("llm", create_provider_client(config or ProviderConfig(), dry_run=dry_run))
    reg.register("gen3d", gen3d_from_env())
    det = detect_from_env()
    if det is not None:
        reg.register("detect", det)
    return reg


@dataclass(slots=True, frozen=True)
class ProviderConfig:
    provider: str = "claude_cli"  # default: the free, no-key path
    model_id: str | None = None
    thinking_level: str = "high"


@dataclass(slots=True, frozen=True)
class ProviderConstructors:
    claude_cli: Callable[..., LLMProvider] = ClaudeCliLLM
    codex_cli: Callable[..., LLMProvider] = CodexCliLLM


def default_model_id(config: ProviderConfig) -> str:
    if config.model_id:
        return config.model_id
    p = normalize_provider_name(config.provider)
    return {
        ProviderName.CLAUDE_CLI: os.environ.get("LR_CLAUDE_CLI_MODEL") or DEFAULT_CLAUDE_CLI_MODEL,
        ProviderName.CODEX_CLI: os.environ.get("LR_CODEX_MODEL") or DEFAULT_CODEX_CLI_MODEL,
    }[p]


def create_provider_client(
    config: ProviderConfig,
    *,
    dry_run: bool = False,
    constructors: ProviderConstructors | None = None,
) -> LLMProvider:
    p = normalize_provider_name(config.provider)
    model_id = default_model_id(config)
    c = constructors or ProviderConstructors()
    ctor = {
        ProviderName.CLAUDE_CLI: c.claude_cli,
        ProviderName.CODEX_CLI: c.codex_cli,
    }[p]
    return ctor(model_id=model_id, thinking_level=config.thinking_level, dry_run=dry_run)


def validate_provider_credentials(provider: str) -> None:
    """Raise a helpful error if the chosen provider can't run (its CLI binary is missing)."""
    p = normalize_provider_name(provider)
    if p is ProviderName.CLAUDE_CLI:
        binary = os.environ.get(CLAUDE_CLI_BIN_ENV, "claude").strip() or "claude"
        if shutil.which(binary) is None:
            raise ValueError(
                f"Claude Code CLI provider needs the `{binary}` executable on PATH "
                f"(install Claude Code / `npm i -g @anthropic-ai/claude-code`, or set {CLAUDE_CLI_BIN_ENV})."
            )
    if p is ProviderName.CODEX_CLI:
        binary = os.environ.get(CODEX_CLI_BIN_ENV, "codex").strip() or "codex"
        if shutil.which(binary) is None:
            raise ValueError(
                f"Codex CLI provider needs the `{binary}` executable on PATH "
                f"(install/login to Codex CLI, or set {CODEX_CLI_BIN_ENV})."
            )
