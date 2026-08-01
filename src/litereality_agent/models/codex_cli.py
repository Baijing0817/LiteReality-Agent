"""OpenAI Codex CLI provider (LLMProvider) — drives the local `codex` binary, no API key.

Same subprocess pattern as `claude_cli.py` — only the binary + render differ.
"""

from __future__ import annotations

import os

from litereality_agent.models._shared import env_float, run_cli, stub_response
from litereality_agent.models.base import ConversationMessage, ProviderResponse, ToolSchema

DEFAULT_CODEX_CLI_MODEL = "codex-cli-default"
CODEX_CLI_BIN_ENV = "LR_CODEX_CLI_BIN"
CODEX_CLI_TIMEOUT_ENV = "LR_CODEX_CLI_TIMEOUT_SECONDS"


class CodexCliLLM:
    def __init__(
        self,
        model_id: str = DEFAULT_CODEX_CLI_MODEL,
        *,
        thinking_level: str = "high",
        dry_run: bool = False,
    ) -> None:
        self.model_id = model_id or DEFAULT_CODEX_CLI_MODEL
        self.thinking_level = thinking_level
        self.dry_run = dry_run
        self.binary = os.environ.get(CODEX_CLI_BIN_ENV, "codex").strip() or "codex"
        self.timeout_seconds = env_float(CODEX_CLI_TIMEOUT_ENV, 900.0)

    async def generate_with_tools(
        self,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[ToolSchema],
    ) -> ProviderResponse:
        if self.dry_run:
            return stub_response(self.model_id, f"dry-run (codex CLI: {self.binary})")
        # TODO(port): render conversation+tools → prompt; run `codex exec ... --json`; parse the
        # last assistant message + tool calls → {text, tool_calls, thinking, usage}.
        raise NotImplementedError("CodexCliLLM.generate_with_tools not wired yet")
        _ = run_cli

    async def prepare_next_request(self, **_) -> None:
        return None

    async def close(self) -> None:
        return None
