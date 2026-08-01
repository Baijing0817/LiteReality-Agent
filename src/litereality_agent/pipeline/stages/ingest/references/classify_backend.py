"""Complexity-classifier backend dispatch — Claude (default), OpenAI, or Gemini.

The procedural-vs-trellis router picks its backend from ``LR_CLASSIFY_PROVIDER``:

  claude  (default)  → :mod:`claude_classify`  (logged-in Claude, no key; the "no Gemini" policy)
  openai             → :mod:`openai_classify`   (needs $OPENAI_API_KEY)
  gemini             → :mod:`gemini_classify`   (needs $GEMINI_API_KEY)

Classify is **decoupled** from image generation on purpose: image-gen has no Claude option
(Claude can't render), so it stays on ``LR_IMAGE_PROVIDER`` (openai|gemini), while *reasoning*
about an image (classify) defaults to Claude. Imported *as* ``gemini_classify`` by
:mod:`classify_complexity` so its call sites are unchanged.
"""

from __future__ import annotations

import os

DEFAULT_CLASSIFY_MODEL = "claude"  # a non-None default; each backend resolves its own model


def provider() -> str:
    # Provider policy: classification (reasoning) is CLAUDE by default; OpenAI is image-gen only.
    # An explicit LR_CLASSIFY_PROVIDER override still wins for users who want it, but the default
    # never routes classify to OpenAI just because image-gen is OpenAI.
    p = os.environ.get("LR_CLASSIFY_PROVIDER")
    return p.strip().lower() if p else "claude"


def classify_image(*args, **kwargs):
    p = provider()
    if p == "openai":
        from . import openai_classify

        return openai_classify.classify_image(*args, **kwargs)
    if p in ("gemini", "google"):
        from . import gemini_classify

        return gemini_classify.classify_image(*args, **kwargs)
    from . import claude_classify

    return claude_classify.classify_image(*args, **kwargs)
