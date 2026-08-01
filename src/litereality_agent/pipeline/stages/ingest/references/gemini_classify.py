"""Structured Gemini vision classifier — image + prompt -> validated JSON.

A small REST client for `gemini-2.5-flash`/`pro` that forces structured output via
`responseMimeType=application/json` + `responseSchema`. Used by
:mod:`litereality_agent.pipeline.stages.reconstruct.classify.classify_complexity` to route each object to procedural vs
TRELLIS generation. Separate from :mod:`object_init.gemini_image` (which generates
images); this one returns a decision.
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import requests

from litereality_agent.pipeline import paths as config

DEFAULT_CLASSIFY_MODEL = "gemini-2.5-flash"


def _mime_for(path: Path) -> str:
    return "image/png" if path.suffix.lower() == ".png" else "image/jpeg"


def classify_image(
    image_path: Path,
    prompt: str,
    response_schema: dict,
    *,
    model: str = DEFAULT_CLASSIFY_MODEL,
    api_key: str | None = None,
    timeout: int = 60,
    retries: int = 3,
) -> dict:
    """Send one image + prompt and return the parsed JSON object (schema-validated)."""
    image_path = Path(image_path)
    key = api_key or config.gemini_api_key()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": _mime_for(image_path),
                            "data": base64.b64encode(image_path.read_bytes()).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
            "temperature": 0.1,
        },
    }

    last_err = None
    for attempt in range(retries):
        try:
            response = requests.post(
                url,
                params={"key": key},
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=timeout,
            )
            body = response.json()
            if response.status_code == 200:
                parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts)
                if text:
                    return json.loads(text)
                last_err = f"empty response: {json.dumps(body)[:300]}"
            else:
                last_err = (
                    f"status {response.status_code}: {json.dumps(body.get('error', body))[:300]}"
                )
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
        time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"Gemini classify failed after {retries} tries: {last_err}")
