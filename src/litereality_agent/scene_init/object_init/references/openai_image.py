"""OpenAI image backend — a drop-in twin of :func:`gemini_image.nano_banana`.

Same signature and same on-disk contract (writes a raw PNG of the object on a solid
black background, which the shared :func:`gemini_image.normalize_generation_image`
then crops + recentres). Uses ``gpt-image-1`` via ``images.edit`` (evidence sheet in,
clean object render out). Selected by ``LR_IMAGE_PROVIDER=openai`` through
:mod:`image_backend`; the Gemini path stays the default.

Model / key:
  ``$LR_OPENAI_IMAGE_MODEL`` (default ``gpt-image-1``) · ``$OPENAI_API_KEY``.
The Gemini ``model=`` the callers pass is ignored here (it names a Gemini model).
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
from pathlib import Path

from PIL import Image

from .. import tracing

DEFAULT_IMAGE_MODEL = "gpt-image-1"
# gpt-image-1 token pricing ($/1M tokens); output image tokens dominate. Used only for the
# rough cost line we log — override via env if OpenAI changes rates.
_PRICE_IN_TEXT = float(os.environ.get("LR_OPENAI_PRICE_IN_TEXT", "5.0"))
_PRICE_IN_IMAGE = float(os.environ.get("LR_OPENAI_PRICE_IN_IMAGE", "10.0"))
_PRICE_OUT_IMAGE = float(os.environ.get("LR_OPENAI_PRICE_OUT_IMAGE", "40.0"))


def _cost_usd(usage: dict) -> float:
    """Rough USD from a gpt-image-1 usage block."""
    it = usage.get("input_tokens_details", {}) or {}
    text_in = it.get("text_tokens", 0)
    image_in = it.get("image_tokens", 0)
    out = usage.get("output_tokens", 0)
    return round(
        (text_in * _PRICE_IN_TEXT + image_in * _PRICE_IN_IMAGE + out * _PRICE_OUT_IMAGE) / 1e6, 5
    )


def _flatten_on_black(png_bytes: bytes) -> bytes:
    """Composite a possibly-transparent render onto solid black so normalize's black-key crop works."""
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    canvas = Image.new("RGBA", im.size, (0, 0, 0, 255))
    canvas.alpha_composite(im)
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG")
    return out.getvalue()


def nano_banana(
    sheet_path: Path,
    prompt: str,
    out_path: Path,
    *,
    model: str | None = None,  # gemini model name from callers — ignored here
    api_key: str | None = None,
    timeout: int = 180,
    retries: int = 3,
    force: bool = False,
    response_dir: Path | None = None,
) -> dict | None:
    """OpenAI twin of gemini_image.nano_banana. Writes the render to ``out_path`` (object on
    black). Returns a metadata dict (incl. token usage + cost_usd) on success, None on skip,
    raises on hard failure."""
    from openai import OpenAI

    sheet_path = Path(sheet_path)
    out_path = Path(out_path)
    call_t0 = time.time()
    if out_path.exists() and not force:
        tracing.on_gemini(prompt, sheet_path, out_path, "skipped_exists", model="openai")
        return None

    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OpenAI image backend needs $OPENAI_API_KEY (LR_IMAGE_PROVIDER=openai).")
    img_model = os.environ.get("LR_OPENAI_IMAGE_MODEL", DEFAULT_IMAGE_MODEL)
    quality = os.environ.get("LR_OPENAI_IMAGE_QUALITY", "medium")
    client = OpenAI(api_key=key, timeout=timeout)
    # gpt-image-2 rejects transparent backgrounds; only the gpt-image-1 family supports them. With
    # transparent we composite the exact object onto black; otherwise we ask the model for a solid
    # black background (normalize keys on black either way). A generic clause kills the hallucinated
    # hooks/posters/props gpt-image-1 tends to bolt on.
    use_transparent = "gpt-image-2" not in img_model
    clean = (
        "\n\nRender ONLY this single object as a clean photoreal PBR asset — remove loose clutter and "
        "scene (coats, bags, papers, people, room background, floor, added text or borders), but KEEP "
        "every fixture that is physically part of the object (e.g. hooks, handles, hinges, rails). Even "
        "studio lighting, no cast shadow, centered and fully visible. Reproduce the object's real "
        "structure and the EXACT COUNT of every repeated part (panels, glazed panes, drawers, doors, "
        "shelves, legs, hooks); do NOT simplify, drop, merge, or invent any real feature (e.g. never "
        "flatten a glazed/panelled surface into a plain one, and never add glazing that is not there)."
    )
    bg = (
        " Fully transparent background." if use_transparent
        else " Place it on a SOLID PURE BLACK (#000000) background."
    )
    full_prompt = prompt + clean + bg

    last_err = None
    for attempt in range(retries):
        try:
            edit_kwargs = dict(model=img_model, prompt=full_prompt, size="1024x1024", quality=quality)
            if use_transparent:
                edit_kwargs["background"] = "transparent"
            with open(sheet_path, "rb") as fh:
                result = client.images.edit(image=fh, **edit_kwargs)
            datum = result.data[0]
            png = base64.b64decode(datum.b64_json)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(_flatten_on_black(png) if use_transparent else png)
            usage = (
                result.usage.model_dump() if getattr(result, "usage", None) is not None else {}
            )
            cost = _cost_usd(usage)
            if response_dir is not None:
                response_dir.mkdir(parents=True, exist_ok=True)
                (response_dir / f"openai_response_{attempt}.json").write_text(
                    json.dumps({"model": img_model, "quality": quality, "usage": usage,
                                "cost_usd": cost}, indent=2),
                    encoding="utf-8",
                )
            tracing.on_gemini(
                prompt, sheet_path, out_path, "ok", model=f"openai:{img_model}",
                elapsed_sec=round(time.time() - call_t0, 3), attempt=attempt, usage=usage,
            )
            print(f"    [openai-image] {out_path.name}  ${cost}  ({usage.get('output_tokens','?')} out tok)", flush=True)
            return {
                "status": "ok",
                "model": f"openai:{img_model}",
                "attempt": attempt,
                "output": str(out_path),
                "elapsed_sec": round(time.time() - call_t0, 3),
                "usage": usage,
                "cost_usd": cost,
            }
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc}"
            time.sleep(1.5 * (attempt + 1))

    tracing.on_gemini(
        prompt, sheet_path, out_path, "error", model=f"openai:{img_model}",
        elapsed_sec=round(time.time() - call_t0, 3), error=str(last_err)[:400],
    )
    raise RuntimeError(f"OpenAI image returned nothing after {retries} tries: {last_err}")
