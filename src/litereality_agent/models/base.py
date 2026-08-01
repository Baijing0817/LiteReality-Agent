"""Model registry — one front door for every model the system calls.

The pipeline calls several model *families* — a reasoning LLM, a vision critic, an image
generator, a detector, a 3D reconstructor. They share nothing API-wise, so each gets a small
Protocol (`LLMProvider`, `VisionCritiqueService`, `ImageGenService`, `DetectionService`,
`Generation3DService`); a `ModelRegistry` resolves a logical role name → a concrete backend.

Two call sites pull from the registry:
  - the deterministic `init/` (DINO, Trellis, nano) — called directly;
  - the agentic loop (`authoring/`) — called *through tools* (`authoring/tools/`).

Design rule (per project memory `cost-claude-free-gemini-metered`): Claude/agent compute is
free, Gemini/DINO/Trellis is metered — so every metered call goes through a service here that
the `CostTracker` can see.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# ---- shared aliases ----
ToolSchema = dict[str, Any]
ConversationMessage = dict[str, Any]
ProviderResponse = dict[str, Any]  # {"text", "tool_calls", "thinking", "usage": {...}}


# ============================================================================
# 1. The reasoning LLM that drives the loop
# ============================================================================
@runtime_checkable
class LLMProvider(Protocol):
    """The model that reads the scene + render and decides the next tool call."""

    model_id: str

    async def generate_with_tools(
        self,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[ToolSchema],
    ) -> ProviderResponse:
        """One turn: return {text, tool_calls, thinking, usage}."""
        ...

    async def prepare_next_request(
        self,
        *,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[ToolSchema],
        completed_turns: int,
    ) -> Any:
        """Optional pre-request hook (context compaction / maintenance). May be a no-op."""
        ...

    async def close(self) -> Any: ...


# ============================================================================
# 2. Non-LLM model services  (the LiteReality widening)
# ============================================================================
@dataclass(slots=True)
class Detection:
    label: str
    box_xyxy: tuple[float, float, float, float]
    score: float


@runtime_checkable
class DetectionService(Protocol):
    """GroundingDINO. Used in init (bbox_polish, opening match); promotable to a loop tool."""

    name: str

    def detect(
        self,
        image: Any,
        prompt: str,
        *,
        box_threshold: float = 0.30,
        text_threshold: float = 0.20,
        upright: bool = True,
    ) -> list[Detection]: ...


@runtime_checkable
class Generation3DService(Protocol):
    """Trellis (or any image→mesh reconstructor). Used in init/object_init."""

    name: str

    def reconstruct(self, images: list[Any], *, out_dir: str, **opts: Any) -> str:
        """Return the path to the produced mesh/asset."""
        ...


@runtime_checkable
class ImageGenService(Protocol):
    """nano-banana / Gemini image. Used in init (object & opening references, chair grouping)."""

    name: str

    def generate(self, prompt: str, *, refs: list[Any] | None = None, **opts: Any) -> Any:
        """Return a PIL image (or path)."""
        ...


@dataclass(slots=True)
class Critique:
    score: float  # 0..1 overall quality / readiness
    passed: bool  # gate decision
    notes: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VisionCritiqueService(Protocol):
    """Gemini VLM critic. Used in the loop's gate (render(s) + rubric → Critique)."""

    name: str

    def critique(self, images: list[Any], rubric: str, **opts: Any) -> Critique: ...


# ============================================================================
# 3. The registry  (logical name → backend)
# ============================================================================
class ModelRegistry:
    """Holds one backend per role. The harness and init both resolve through this so the set
    of models is configured in ONE place and every metered call is observable.

    Roles are plain strings ("llm", "vlm", "detect", "gen3d", "imagegen") to stay open —
    add a role by registering it; no enum to edit.
    """

    def __init__(self) -> None:
        self._backends: dict[str, Any] = {}

    def register(self, role: str, backend: Any) -> None:
        self._backends[role] = backend

    def get(self, role: str) -> Any:
        if role not in self._backends:
            raise KeyError(
                f"no backend registered for role {role!r}; registered: {sorted(self._backends)}"
            )
        return self._backends[role]

    def has(self, role: str) -> bool:
        return role in self._backends

    # typed convenience accessors -------------------------------------------------
    def llm(self) -> LLMProvider:
        return self.get("llm")

    def vlm(self) -> VisionCritiqueService:
        return self.get("vlm")

    def detect(self) -> DetectionService:
        return self.get("detect")

    def gen3d(self) -> Generation3DService:
        return self.get("gen3d")

    def imagegen(self) -> ImageGenService:
        return self.get("imagegen")
