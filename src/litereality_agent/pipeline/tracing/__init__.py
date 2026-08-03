"""Pipeline-facing aliases for the package-level event logger."""

from litereality_agent.telemetry import (
    active_dir,
    agent_step,
    event,
    on_image_generation,
    stage,
    start,
)

__all__ = ["active_dir", "agent_step", "event", "on_image_generation", "stage", "start"]
