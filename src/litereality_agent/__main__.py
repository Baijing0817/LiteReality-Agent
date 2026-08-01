"""`uv run -m litereality_agent <command>` — the package's command line.

There is no installed console script on purpose: the entry point is the package itself, so the
command you type names the thing you are running, and `uv run` resolves the environment. See
`cli.py` for the commands.
"""

from __future__ import annotations

from litereality_agent.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
