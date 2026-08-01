"""Procedural articulated generation as a `gen3d` backend — reference image → articulated GLB.

Sibling of the TRELLIS gen3d backends, but a different *method*: instead of a neural mesh, an LLM
coding agent (`$LR_PROCEDURAL_PROVIDER=claude|codex`) runs the `image-to-articulated-glb` skill to
author `object.py` → Blender → an **articulated** GLB (drawers pull out, doors swing). Use it for
box-like / articulated objects (cabinets, dishwashers, doors); TRELLIS for organic ones (chairs,
sofas). `classify_complexity` is the router that picks per object.

It's a *meta*-provider: it depends on the `llm` choice (claude/codex) one level down. Same
`Generation3DService` interface as TRELLIS, so the router/caller treats them identically — except
each item carries the extra context procedural needs (category + real-world dims) via `meta`.

    svc = ProceduralService()                      # provider from $LR_PROCEDURAL_PROVIDER
    svc.reconstruct(["cabinet.png"], out_dir="out", asset_id="Storage0",
                    category="storage", dims="0.6 x 0.6 x 2.0")   # → out/Storage0/Storage0.glb
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any


class ProceduralService:
    name = "procedural"

    def __init__(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        max_turns: int = 80,
        max_budget_usd: float = 5.0,
        retries: int = 1,
        concurrency: int = 2,
    ) -> None:
        self.provider = provider  # claude|codex; None → $LR_PROCEDURAL_PROVIDER (else claude)
        self.model = model
        self.max_turns = max_turns
        self.max_budget_usd = max_budget_usd
        self.retries = retries
        self.concurrency = concurrency
        self.last_report: dict | None = None

    # -- Generation3DService -----------------------------------------------------
    def reconstruct(
        self,
        images: list[Any],
        *,
        out_dir: str,
        asset_id: str = "asset",
        category: str = "object",
        dims: str = "",
        scan: str = "_",
        **opts: Any,
    ) -> str:
        image = images[0] if isinstance(images, (list, tuple)) else images
        meta = {asset_id: {"category": category, "dims": dims, "scan": scan}}
        return self.reconstruct_many({asset_id: image}, out_dir=out_dir, meta=meta, **opts)[
            asset_id
        ]

    def reconstruct_many(
        self, items: dict[str, Any], *, out_dir: str, meta: dict[str, dict] | None = None, **_: Any
    ) -> dict[str, str]:
        """{asset_id: image} (+ per-id `meta` = {category, dims, scan}) → {asset_id: glb_path}.

        Runs the articulated agent per object, concurrently. Failed assets → "" (logged)."""
        from litereality_agent.adapters.procedural import (
            generate_procedural as gp,  # lazy: pulls object_init
        )

        meta = meta or {}
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        args = SimpleNamespace(
            provider=self.provider,
            model=self.model,
            max_turns=self.max_turns,
            max_budget_usd=self.max_budget_usd,
            skip_existing=False,
            retries=self.retries,
        )
        jobs = []
        for aid, image in items.items():
            m = meta.get(aid, {})
            jobs.append(
                gp.Job(
                    scan=m.get("scan", "_"),
                    name=aid,
                    category=m.get("category", "object"),
                    image=Path(image),
                    glb=out / aid / f"{aid}.glb",
                    dims=m.get("dims", ""),
                )
            )

        async def _run() -> None:
            sem = asyncio.Semaphore(self.concurrency)
            await asyncio.gather(*(gp.process(j, sem, args) for j in jobs))

        asyncio.run(_run())
        self.last_report = {
            "n": len(jobs),
            "ok": sum(1 for j in jobs if j.status == "ok"),
            "cost_usd": round(sum(j.cost_usd for j in jobs), 4),
        }
        return {j.name: (str(j.glb) if j.glb.is_file() else "") for j in jobs}
