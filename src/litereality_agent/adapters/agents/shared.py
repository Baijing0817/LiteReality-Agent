"""Shared provider helpers.

Key handling pattern: every provider reads a single `<P>_API_KEY` *and* a pool
`<P>_API_KEYS` (comma/newline-separated). Keys are collected, deduped, and one is chosen at
**random per call** so a pool of keys spreads rate limits. A var name ending in `KEYS` (or any
value containing a comma/newline) is treated as a pool; everything else as a single key.
"""

from __future__ import annotations

import asyncio
import os
import random
from typing import Any


def collect_env_keys(*names: str) -> list[str]:
    """Collect keys from `names` (single or pool), deduped, order-preserving."""
    keys: list[str] = []
    for n in names:
        raw = os.environ.get(n, "")
        if not raw.strip():
            continue
        if n.endswith("KEYS") or "," in raw or "\n" in raw:
            keys.extend(t.strip() for t in raw.replace("\n", ",").split(",") if t.strip())
        else:
            keys.append(raw.strip())
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k not in seen:
            out.append(k)
            seen.add(k)
    return out


def random_env_key(*names: str) -> str | None:
    """One key chosen at random from the pool across `names`, or None."""
    keys = collect_env_keys(*names)
    return random.choice(keys) if keys else None


# back-compat alias (first key, not random) — prefer random_env_key
def api_key_from_env(*names: str) -> str | None:
    keys = collect_env_keys(*names)
    return keys[0] if keys else None


def env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def stub_response(model_id: str, note: str) -> dict[str, Any]:
    """A dry-run / not-yet-wired turn: no tool calls, short text, zero usage. Lets the loop be
    smoke-tested without keys or binaries."""
    return {
        "text": f"[{model_id}] {note}",
        "tool_calls": [],
        "thinking": "",
        "usage": {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0},
    }


async def run_cli(
    cmd: list[str], *, cwd: str | None = None, timeout: float = 900.0, stdin: str | None = None
) -> tuple[int, str, str]:
    """Run a subprocess (for the CLI providers); return (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await asyncio.wait_for(
        proc.communicate(stdin.encode() if stdin is not None else None), timeout=timeout
    )
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")
