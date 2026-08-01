"""Repo environment loading — `.env` and `models.env`.

Two files, loaded in the same order and with the same precedence `run.sh` uses:

  `.env`        your secrets and machine paths — plain `KEY=value`
  `models.env`  THE one place every model is picked — shell `export K="${K:-default}"`

Non-empty shell env always wins over both, and `.env` wins over `models.env` (which only ever
supplies defaults). Empty template values are ignored.

`models.env` is shell, and shell entry points simply source it. Everything reachable only through
the CLI could not, so `uv run -m litereality_agent scene_init` and `./run.sh` silently ran DIFFERENT
models — image-gen fell back to the code default while run.sh used the file. Parsing the handful
of `export`/`${K:-v}` forms that file actually contains is what keeps the two entry points honest.
No third-party dotenv dependency; both formats are trivial.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from litereality_agent import REPO_ROOT  # the checkout, where .env lives

# The names the README/.env.example ask users for -> the canonical names the code reads.
# Keeping both means the documented, friendlier spelling works without touching every read site.
ALIASES = {
    "BLENDER_PATH": "LITEREALITY_BLENDER",
    "BLENDER": "LITEREALITY_BLENDER",
    "GROUNDING_DINO_PYTHON": "LR_DINO_PYTHON",
    "TRELLIS_PYTHON": "LITEREALITY_TRELLIS_PYTHON",
    # The `alr` command is gone and its env vars moved to the repo's LR_ family. An existing
    # .env from before that keeps working — nobody has to edit a config file to pick up a rename.
    **{f"ALR_{n}": f"LR_{n}" for n in (
        "PROVIDER", "DATA_DIR",
        "CLAUDE_CLI_BIN", "CLAUDE_CLI_TIMEOUT_SECONDS", "CLAUDE_CLI_MODEL",
        "CODEX_CLI_BIN", "CODEX_CLI_TIMEOUT_SECONDS", "CODEX_MODEL",
        "KIMI_CLI_BIN", "KIMI_CLI_TIMEOUT_SECONDS", "KIMI_MODEL",
    )},
}


def apply_aliases(env: dict | None = None) -> None:
    """Copy any alias that is set onto its canonical name. The canonical name wins if both
    are set, so this can never override an explicit value."""
    e = os.environ if env is None else env
    for alias, canonical in ALIASES.items():
        val = e.get(alias, "").strip()
        if val and not e.get(canonical, "").strip():
            e[canonical] = val


# `export NAME="${NAME:-value}"` / `export NAME=value` / `NAME=value`, with an optional trailing
# comment. That is the whole of models.env's grammar — anything richer belongs in .env.
_ASSIGN = re.compile(
    r"""^\s*(?:export\s+)?(?P<key>[A-Za-z_]\w*)=(?P<val>.*?)\s*$"""
)
_REF = re.compile(r"\$\{?(?P<name>[A-Za-z_]\w*)\}?")
_SELF_DEFAULT = re.compile(r"""^\$\{(?P<key>[A-Za-z_]\w*):-(?P<val>.*)\}$""")


def _value(raw: str, key: str) -> str | None:
    """The literal a line assigns, or None when there is nothing usable.

    Unquote FIRST, then resolve `${K:-default}` — several models.env lines carry a trailing
    comment, and matching the substitution against the whole raw tail silently fails on those,
    leaving the literal `${...}` as the value.
    """
    raw = raw.strip()
    if raw.startswith(('"', "'")):
        quote = raw[0]
        end = raw.find(quote, 1)
        raw = raw[1:end] if end > 0 else raw[1:]
    else:
        raw = raw.split(" #", 1)[0].split("\t#", 1)[0].strip()

    m = _SELF_DEFAULT.match(raw)
    if m:
        # `${K:-default}` means "keep K if set, else default" — exactly this loader's own
        # precedence, so carrying the default is all that is needed.
        if m.group("key") != key:
            return None  # an indirection we do not model; leave it to the shell
        raw = m.group("val").strip()

    # A default may name another variable (`HARNESS_CRITIC_MODEL=${…:-$HARNESS_MODEL}`). Expand
    # from what is loaded so far; if the referent is unset, set nothing rather than a literal `$X`.
    if "$" in raw:
        def _sub(mm):
            return os.environ.get(mm.group("name"), "\0")
        raw = _REF.sub(_sub, raw)
        if "\0" in raw:
            return None
    return raw or None


def _load_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = _ASSIGN.match(line)
        if not m:
            continue
        key = m.group("key")
        val = _value(m.group("val"), key)
        if not val:
            continue
        if os.environ.get(key, "").strip():
            continue  # non-empty shell value wins
        os.environ[key] = val


def load_env(root: Path | None = None) -> None:
    """Load `.env` then `models.env`. Idempotent; safe to call more than once."""
    root = root or REPO_ROOT
    _load_file(root / ".env")        # secrets + machine paths win …
    _load_file(root / "models.env")  # … over the model defaults
    apply_aliases()
