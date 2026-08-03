"""Typed application settings loaded once at the composition boundary."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from litereality_agent import REPO_ROOT


class LiteRealitySettings(BaseSettings):
    """Environment contract for the pipeline and its subprocess adapters.

    Pydantic's source ordering gives process environment priority over dotenv
    files. ``load`` supplies ``models.env`` first and ``.env`` second, so user
    machine/secrets configuration overrides repository model defaults.
    """

    model_config = SettingsConfigDict(
        case_sensitive=True,
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
    )

    repo_root: Path = Field(default=REPO_ROOT, validation_alias="LR_REPO_ROOT")
    scans_dir: Path | None = Field(default=None, validation_alias="LR_SCANS_DIR")
    output_root: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("LITEREALITY_OUTPUT", "OBJECT_INIT_OUTPUT"),
    )
    final_root: Path | None = Field(default=None, validation_alias="LITEREALITY_FINAL")
    scene: Path | None = Field(default=None, validation_alias="LR_SCENE")
    authoring_root: Path | None = Field(default=None, validation_alias="LR_AUTHORING")
    studio_keys: Path | None = Field(default=None, validation_alias="LR_STUDIO_KEYS")

    blender: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("LITEREALITY_BLENDER", "BLENDER_PATH", "BLENDER"),
    )
    dino_python: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("LR_DINO_PYTHON", "GROUNDING_DINO_PYTHON"),
    )
    trellis_python: Path | None = Field(
        default=None,
        validation_alias=AliasChoices("LITEREALITY_TRELLIS_PYTHON", "TRELLIS_PYTHON"),
    )
    procedural_python: Path | None = Field(
        default=None, validation_alias="LITEREALITY_PROCEDURAL_PYTHON"
    )

    harness_model: str = Field(default="claude-opus-5", validation_alias="HARNESS_MODEL")
    critic_model: str | None = Field(default=None, validation_alias="HARNESS_CRITIC_MODEL")
    chair_judge_model: str = Field(
        default="claude-opus-5", validation_alias="LR_CHAIR_JUDGE_MODEL"
    )
    procedural_model: str = Field(
        default="claude-opus-5", validation_alias="LR_PROCEDURAL_MODEL"
    )
    image_model: str = Field(default="gpt-image-2", validation_alias="LR_OPENAI_IMAGE_MODEL")
    dino_model: str = Field(
        default="IDEA-Research/grounding-dino-tiny", validation_alias="LR_DINO_MODEL"
    )
    dino_embed_model: str = Field(
        default="facebook/dinov2-small", validation_alias="LR_DINO_EMBED_MODEL"
    )

    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    runpod_api_key: SecretStr | None = Field(default=None, validation_alias="RUNPOD_API_KEY")
    runpod_trellis_endpoint: str | None = Field(
        default=None, validation_alias="RUNPOD_TRELLIS_ENDPOINT"
    )
    runpod_dino_endpoint: str | None = Field(
        default=None, validation_alias="RUNPOD_DINO_ENDPOINT"
    )

    @model_validator(mode="after")
    def resolve_dependent_defaults(self) -> "LiteRealitySettings":
        if not self.critic_model or self.critic_model == "$HARNESS_MODEL":
            self.critic_model = self.harness_model
        return self

    @classmethod
    def load(cls, root: Path | None = None, **overrides: Any) -> "LiteRealitySettings":
        root = (root or REPO_ROOT).resolve()
        return cls(
            _env_file=(root / "models.env", root / ".env"),
            _env_file_encoding="utf-8",
            **overrides,
        )

    def resolved_output_root(self) -> Path:
        return (self.output_root or self.final_root or (self.repo_root / "run")).resolve()

    def resolved_scans_dir(self) -> Path:
        return (self.scans_dir or (self.repo_root / "scans_uploaded")).resolve()

    def as_environment(self) -> dict[str, str]:
        """Serialize canonical names for subprocesses that have not yet been typed."""
        values: dict[str, object | None] = {
            "LR_REPO_ROOT": self.repo_root,
            "LR_SCANS_DIR": self.resolved_scans_dir(),
            "LITEREALITY_OUTPUT": self.resolved_output_root(),
            "LITEREALITY_FINAL": self.final_root or self.resolved_output_root(),
            "LR_SCENE": self.scene,
            "LR_AUTHORING": self.authoring_root,
            "LR_STUDIO_KEYS": self.studio_keys,
            "LITEREALITY_BLENDER": self.blender,
            "LR_DINO_PYTHON": self.dino_python,
            "LITEREALITY_TRELLIS_PYTHON": self.trellis_python,
            "LITEREALITY_PROCEDURAL_PYTHON": self.procedural_python,
            "HARNESS_MODEL": self.harness_model,
            "HARNESS_CRITIC_MODEL": self.critic_model,
            "LR_CHAIR_JUDGE_MODEL": self.chair_judge_model,
            "LR_PROCEDURAL_MODEL": self.procedural_model,
            "LR_OPENAI_IMAGE_MODEL": self.image_model,
            "LR_DINO_MODEL": self.dino_model,
            "LR_DINO_EMBED_MODEL": self.dino_embed_model,
            "RUNPOD_TRELLIS_ENDPOINT": self.runpod_trellis_endpoint,
            "RUNPOD_DINO_ENDPOINT": self.runpod_dino_endpoint,
        }
        secrets = {
            "OPENAI_API_KEY": self.openai_api_key,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "RUNPOD_API_KEY": self.runpod_api_key,
        }
        env = {key: str(value) for key, value in values.items() if value is not None}
        env.update(
            {key: value.get_secret_value() for key, value in secrets.items() if value is not None}
        )
        return env

    def apply_environment(self) -> None:
        """Populate canonical variables without overriding the invoking shell."""
        for key, value in self.as_environment().items():
            os.environ.setdefault(key, value)


def load_settings(root: Path | None = None, **overrides: Any) -> LiteRealitySettings:
    return LiteRealitySettings.load(root, **overrides)
