"""Claude Code CLI provider (LLMProvider) — drives the local `claude` binary, no API key.

The harness loop is provider-agnostic, so a CLI agent plugs in the same as an API client: each
`generate_with_tools` turn renders (system_prompt, messages, tools) into a single Claude Code
prompt, runs `claude -p ... --output-format json`, and parses the assistant text + tool calls
back out. Symmetric with `codex_cli.py` (same subprocess + timeout pattern).
"""

from __future__ import annotations

import os

from litereality_agent.models._shared import env_float, run_cli, stub_response
from litereality_agent.models.base import ConversationMessage, ProviderResponse, ToolSchema

DEFAULT_CLAUDE_CLI_MODEL = "claude-cli-default"  # Claude Code uses its configured model
CLAUDE_CLI_BIN_ENV = "LR_CLAUDE_CLI_BIN"
CLAUDE_CLI_TIMEOUT_ENV = "LR_CLAUDE_CLI_TIMEOUT_SECONDS"


class ClaudeCliLLM:
    def __init__(
        self,
        model_id: str = DEFAULT_CLAUDE_CLI_MODEL,
        *,
        thinking_level: str = "high",
        dry_run: bool = False,
    ) -> None:
        self.model_id = model_id or DEFAULT_CLAUDE_CLI_MODEL
        self.thinking_level = thinking_level
        self.dry_run = dry_run
        self.binary = os.environ.get(CLAUDE_CLI_BIN_ENV, "claude").strip() or "claude"
        self.timeout_seconds = env_float(CLAUDE_CLI_TIMEOUT_ENV, 900.0)

    async def generate_with_tools(
        self,
        system_prompt: str,
        messages: list[ConversationMessage],
        tools: list[ToolSchema],
    ) -> ProviderResponse:
        if self.dry_run:
            return stub_response(self.model_id, f"dry-run (claude CLI: {self.binary})")
        # TODO(port): render the conversation+tools into a prompt, then:
        #   cmd = [self.binary, "-p", prompt, "--output-format", "json"]
        #   (+ "--model", self.model_id when not the sentinel)
        #   rc, out, err = await run_cli(cmd, timeout=self.timeout_seconds)
        # parse the JSON stream → {text, tool_calls, thinking, usage}.
        raise NotImplementedError("ClaudeCliLLM.generate_with_tools not wired yet")
        _ = run_cli  # keep import live until wired

    async def prepare_next_request(self, **_) -> None:
        return None

    async def close(self) -> None:
        return None
