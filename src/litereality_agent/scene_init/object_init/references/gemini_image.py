"""Self-contained Gemini / Nano Banana image generator.

Replaces the old external ``gemini_trellis_reconstruct.py`` helper (which the v2
scripts shelled out to and which no longer exists) with a direct REST call to
``gemini-2.5-flash-image`` — image-in, clean-image-out. The request/response shape
mirrors the working step4 client in the studio repo.

    nano_banana(sheet_path, prompt, out_path) -> dict | None   # writes the PNG

Plus :func:`normalize_generation_image`, the shared post-process that crops the
generated object off its black background and recentres it on a 1024² canvas.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import numpy as np
import requests
from PIL import Image

from .. import config, tracing


def mime_for(path: Path) -> str:
    return "image/png" if path.suffix.lower() == ".png" else "image/jpeg"


def _extract_image_bytes(response_json: dict) -> bytes | None:
    for candidate in response_json.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    return None


def nano_banana(
    sheet_path: Path,
    prompt: str,
    out_path: Path,
    *,
    model: str = config.DEFAULT_GEMINI_MODEL,
    api_key: str | None = None,
    timeout: int = 120,
    retries: int = 3,
    force: bool = False,
    response_dir: Path | None = None,
) -> dict | None:
    """Send one evidence sheet + prompt to Gemini and write the returned PNG.

    Returns a small metadata dict on success, or raises on hard failure. If
    ``out_path`` already exists and ``force`` is False, returns ``None`` (skip).
    """
    sheet_path = Path(sheet_path)
    out_path = Path(out_path)
    call_t0 = time.time()
    if out_path.exists() and not force:
        tracing.on_gemini(prompt, sheet_path, out_path, "skipped_exists", model=model)
        return None

    key = api_key or config.gemini_api_key()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_for(sheet_path),
                            "data": base64.b64encode(sheet_path.read_bytes()).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }

    last_status = None
    last_body: dict | None = None
    for attempt in range(retries):
        started = time.time()
        response = requests.post(
            url,
            params={"key": key},
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
        try:
            body = response.json()
        except Exception:
            body = {"raw_text": response.text}
        last_status, last_body = response.status_code, body
        if response_dir is not None:
            response_dir.mkdir(parents=True, exist_ok=True)
            (response_dir / f"gemini_response_{attempt}.json").write_text(
                json.dumps(body, indent=2), encoding="utf-8"
            )
        if response.status_code == 200:
            image_bytes = _extract_image_bytes(body)
            if image_bytes:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(image_bytes)
                usage = body.get("usageMetadata", {})
                tracing.on_gemini(
                    prompt,
                    sheet_path,
                    out_path,
                    "ok",
                    model=model,
                    elapsed_sec=round(time.time() - call_t0, 3),
                    attempt=attempt,
                    usage=usage,
                )
                return {
                    "status": "ok",
                    "model": model,
                    "attempt": attempt,
                    "output": str(out_path),
                    "elapsed_sec": round(time.time() - started, 3),
                    "usageMetadata": usage,
                }
        # transient: brief backoff before retrying
        time.sleep(1.5 * (attempt + 1))

    detail = ""
    if isinstance(last_body, dict):
        detail = json.dumps(last_body.get("error", last_body))[:400]
    tracing.on_gemini(
        prompt,
        sheet_path,
        out_path,
        "error",
        model=model,
        elapsed_sec=round(time.time() - call_t0, 3),
        error=f"status={last_status}: {detail}",
    )
    raise RuntimeError(
        f"Gemini returned no image after {retries} tries (status={last_status}): {detail}"
    )


def normalize_generation_image(
    source: Path,
    destination: Path,
    canvas_size: int = 1024,
    target_fill: float = 0.78,
    pad_ratio: float = 0.08,
) -> None:
    """Crop the object off the black background and recentre on a square canvas."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as im:
        image = im.convert("RGB")
    arr = np.asarray(image)
    mask = (arr[:, :, 0] > 14) | (arr[:, :, 1] > 14) | (arr[:, :, 2] > 14)
    ys, xs = np.where(mask)
    if len(xs) == 0:
        image.resize((canvas_size, canvas_size), Image.Resampling.LANCZOS).save(destination)
        return

    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1)
    width, height = x1 - x0, y1 - y0
    pad = int(max(width, height) * pad_ratio)
    x0 = max(0, x0 - pad)
    y0 = max(0, y0 - pad)
    x1 = min(image.width, x1 + pad)
    y1 = min(image.height, y1 + pad)

    crop = image.crop((x0, y0, x1, y1))
    scale = target_fill * canvas_size / max(crop.width, crop.height)
    resized = crop.resize(
        (max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = Image.new("RGB", (canvas_size, canvas_size), (0, 0, 0))
    canvas.paste(resized, ((canvas_size - resized.width) // 2, (canvas_size - resized.height) // 2))
    canvas.save(destination)
