"""Shared VLM call for the vision tools (read_image / critic).

One Gemini generateContent call with inline images. `json_mode=True` asks for (and parses) a JSON
reply — used by critic, which returns structure, not prose. Key via
litereality_agent.services.rendering.config.gemini_api_key(); lazy imports keep tool modules import-clean.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re

# Lazily-built per-process cap on concurrent Claude-vision sessions (see _vision_sem). Declared at
# module level so the `global` inside _vision_sem has something to read on the first call — without
# it the first `if _CLAUDE_VISION_SEM is None` raised NameError, and every critic/read_image call on
# the default (claude) VLM backend failed with "critic failed: name '_CLAUDE_VISION_SEM' is not defined".
_CLAUDE_VISION_SEM = None


def _img_b64(path, max_side: int = 1536, quality: int = 85) -> str:
    """JPEG-recompress + base64 an image for inline upload (bounded size)."""
    from PIL import Image

    im = Image.open(path).convert("RGB")
    if max(im.size) > max_side:
        s = max_side / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()


def _urlopen_retry(req, timeout: float, tries: int = 5):
    """urlopen with exponential backoff on rate-limit / transient errors (429/500/503)."""
    import time
    import urllib.error
    import urllib.request

    for k in range(tries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and k < tries - 1:
                time.sleep(min(5 * (2 ** k), 60))
                continue
            raise


def gemini_vision(images: list[str], prompt: str, *, json_mode: bool = False, labels: list[str] | None = None):
    """`labels` names each image FOR THE MODEL — a text part "IMAGE k — <label>:" precedes every
    inline image, so with several images the VLM always knows which wall/view it is looking at.
    Defaults to the filename stem (already descriptive: Wall2_frame_00030, Wall2_compare, ...)."""
    import urllib.request
    from pathlib import Path

    from litereality_agent.services.rendering import config

    key = config.gemini_api_key()
    if not key:
        raise RuntimeError("no Gemini key (set GEMINI_API_KEY or .key)")
    model = getattr(config, "GEMINI_MODEL", "gemini-2.5-flash")
    if labels is None or len(labels) != len(images):
        labels = [Path(p).stem for p in images]
    parts = [{"text": prompt}]
    for i, (img, lab) in enumerate(zip(images, labels), 1):
        parts.append({"text": f"IMAGE {i} — {lab}:"})
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": _img_b64(img)}})
    body: dict = {"contents": [{"role": "user", "parts": parts}]}
    if json_mode:
        body["generationConfig"] = {"response_mime_type": "application/json"}
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with _urlopen_retry(req, 120) as r:
        out = json.loads(r.read())
    text = out["candidates"][0]["content"]["parts"][0]["text"].strip()
    if not json_mode:
        return text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)  # salvage a fenced/wrapped JSON object
        if m:
            return json.loads(m.group(0))
        raise






def _vision_sem():
    """Cap concurrent Claude-vision sessions per process (survey fires ~10 reads at once;
    across a 7-scan fleet that would be ~70 simultaneous SDK sessions).

    Default 6: `survey` reads every surface concurrently, and each claude_vision read spawns
    its own claude CLI session (~12s), so a low cap serialises them into waves. Measured on
    Office-Elliott stage-1 survey (8 surfaces): cap 3 = 52s (3 waves), cap 8 = 34s (1 wave);
    6 balances that speedup against process count on a shared box. Raise via
    $HARNESS_VLM_CONCURRENCY for a single-tenant machine, lower it if the box is loaded."""
    global _CLAUDE_VISION_SEM
    if _CLAUDE_VISION_SEM is None:
        import asyncio

        _CLAUDE_VISION_SEM = asyncio.Semaphore(int(os.environ.get("HARNESS_VLM_CONCURRENCY", "6")))
    return _CLAUDE_VISION_SEM


async def claude_vision(images: list[str], prompt: str, *, json_mode: bool = False,
                        labels: list[str] | None = None, max_turns: int = 4):
    """Opus 4.8 as the VLM: Claude READS the images (SDK, Read-only) and answers — the drop-in
    counterpart of gemini_vision. json_mode parses (fence-tolerant) JSON from the reply."""
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    from litereality_agent.services.rendering import config

    opts = ClaudeAgentOptions(
        cwd=str(config.ROOT),
        add_dirs=[str(config.ROOT)],
        system_prompt={"type": "preset", "preset": "claude_code"},
        setting_sources=[],  # one-shot vision grade: skip loading project/user config (~17% faster/read, steadier, more reproducible; the worker's closed mode does the same)
        allowed_tools=["Read"],
        permission_mode="bypassPermissions",
        max_turns=max(max_turns, len(images) + 2),  # it must get to Read EVERY image
        model=getattr(config, "MODEL", "claude-opus-5"),
    )
    lines = []
    for k, ip in enumerate(images):
        lab = f" — {labels[k]}" if labels and k < len(labels) and labels[k] else ""
        lines.append(f"- IMAGE {k + 1}{lab}: {ip}")
    full = (
        "First Read (view) EVERY image listed below, then answer the question.\n"
        + "\n".join(lines) + "\n\n" + prompt
    )
    if json_mode:
        full += "\n\nReply with ONLY the JSON object — no prose, no code fences."
    out = ""
    async with _vision_sem():
        async for m in query(prompt=full, options=opts):
            if isinstance(m, ResultMessage):
                out = m.result or ""
    if not json_mode:
        return out
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        mt = re.search(r"\{.*\}", out, re.S)
        if mt:
            return json.loads(mt.group(0))
        mt = re.search(r"\[.*\]", out, re.S)
        return json.loads(mt.group(0)) if mt else {}


async def vision(images: list[str], prompt: str, *, json_mode: bool = False,
                 labels: list[str] | None = None):
    """THE image-understanding entry point (critic / read_image / fix-revision). Backend via
    $HARNESS_VLM: 'claude' (default — Opus 4.8) or 'gemini' (gemini_vision, run off-loop)."""
    if os.environ.get("HARNESS_VLM", "claude").lower().startswith("gem"):
        import asyncio

        return await asyncio.to_thread(
            gemini_vision, images, prompt, json_mode=json_mode, labels=labels
        )
    return await claude_vision(images, prompt, json_mode=json_mode, labels=labels)
