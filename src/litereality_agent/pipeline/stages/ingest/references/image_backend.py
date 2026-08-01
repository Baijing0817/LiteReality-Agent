"""Image-generation backend dispatch — Gemini (default) or OpenAI.

``LR_IMAGE_PROVIDER=openai`` routes reference generation to ``gpt-image-1``; anything
else keeps the Gemini ``nano-banana`` path. The reference stages import this module
*as* ``gemini_image`` so their call sites (``nano_banana`` / ``normalize_generation_image``)
are unchanged. ``normalize_generation_image`` is provider-agnostic (pure PIL) and always
comes from :mod:`gemini_image`.
"""

from __future__ import annotations

import os

from . import gemini_image

# post-process is shared and provider-independent
normalize_generation_image = gemini_image.normalize_generation_image


def provider() -> str:
    # Default OpenAI (gpt-image-1) — the project's provider policy is "OpenAI for image-gen only,
    # no Gemini". The Gemini path stays reachable ONLY if a user explicitly sets LR_IMAGE_PROVIDER=gemini.
    return os.environ.get("LR_IMAGE_PROVIDER", "openai").strip().lower()


def nano_banana(*args, **kwargs):
    if provider() == "openai":
        from . import openai_image

        return openai_image.nano_banana(*args, **kwargs)
    return gemini_image.nano_banana(*args, **kwargs)
