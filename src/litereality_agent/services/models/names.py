"""Provider names — the two supported reasoning CLIs, plus normalize.

The reasoning/agent is one of two local CLIs (no API key needed):
  - claude_cli : `claude` (Claude Code)
  - codex_cli  : `codex`  (OpenAI Codex)
"""

from __future__ import annotations

from enum import Enum


class ProviderName(str, Enum):
    CLAUDE_CLI = "claude_cli"  # CLI  (`claude` — Claude Code)
    CODEX_CLI = "codex_cli"  # CLI  (`codex` — OpenAI Codex)


_ALIASES: dict[str, ProviderName] = {
    "claude_cli": ProviderName.CLAUDE_CLI,
    "claude-cli": ProviderName.CLAUDE_CLI,
    "claude-code": ProviderName.CLAUDE_CLI,
    "claude": ProviderName.CLAUDE_CLI,
    "cc": ProviderName.CLAUDE_CLI,
    "codex_cli": ProviderName.CODEX_CLI,
    "codex-cli": ProviderName.CODEX_CLI,
    "codex": ProviderName.CODEX_CLI,
    "openai": ProviderName.CODEX_CLI,
    "openai-cli": ProviderName.CODEX_CLI,
}


def normalize_provider_name(provider: str | None) -> ProviderName:
    """Accept aliases / casing. Empty → claude_cli (the default, no-key path)."""
    if not provider:
        return ProviderName.CLAUDE_CLI
    key = provider.strip().lower().replace(" ", "")
    if key in _ALIASES:
        return _ALIASES[key]
    try:
        return ProviderName(key)
    except ValueError as exc:
        raise ValueError(
            f"unknown provider {provider!r}; supported: {sorted(p.value for p in ProviderName)} "
            f"(aliases: {sorted(_ALIASES)})"
        ) from exc
