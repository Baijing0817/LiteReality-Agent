"""TRELLIS on RunPod — the `gen3d` registry backend (image → textured GLB), called over HTTP.

Replaces the local-GPU launcher with a RunPod **serverless** endpoint: submit one job per asset,
run many in PARALLEL (RunPod scales workers), poll, download the GLBs. The loop/init env needs
no torch/GPU — only this HTTP client.

Env:
    RUNPOD_API_KEY (or RUNPOD)       — bearer key
    RUNPOD_TRELLIS_ENDPOINT          — the deployed endpoint id

Worker I/O contract (see deploy/runpod/trellis):
    input  = {"image_b64", "seed", "decimation", "texture_size"}
    output = {"glb_b64"}   OR   {"glb_url"}
"""

from __future__ import annotations

import base64
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from litereality_agent.runtimes.runpod import RunPodClient

_TERMINAL_OK = {"COMPLETED"}
_TERMINAL_BAD = {"FAILED", "CANCELLED", "TIMED_OUT"}


@dataclass(slots=True)
class AssetReport:
    asset_id: str
    ok: bool
    wall_s: float  # client-side submit → glb-on-disk
    exec_s: float | None  # RunPod billed execution time (from status.executionTime)
    cost_usd: float | None  # exec_s × gpu rate (None if no rate configured)
    glb_path: str = ""
    error: str = ""
    # Appended, never inserted: a defaulted field added mid-dataclass silently re-points every
    # positional argument after it, and both call sites here build the report positionally.
    delay_s: float | None = None  # queue + worker cold start (from status.delayTime)


@dataclass(slots=True)
class BatchReport:
    assets: list[AssetReport] = field(default_factory=list)
    wall_s: float = 0.0  # total batch wall-clock (parallel, so << sum of asset walls)

    @property
    def ok_count(self) -> int:
        return sum(1 for a in self.assets if a.ok)

    @property
    def total_exec_s(self) -> float:
        return sum(a.exec_s or 0.0 for a in self.assets)

    # TODO(runpod #1): this number is the stage's real cost — 233s of boot for 45s of work on a
    # cold endpoint. Fixing it is endpoint configuration (active workers / idle timeout /
    # FlashBoot), not code; the open question here is whether one batched job would amortise a
    # single cold start over N assets instead of paying N of them.
    @property
    def max_delay_s(self) -> float:
        """The worst queue+cold-start wait. Max, not sum: assets are submitted in parallel and
        wait concurrently, so summing would triple-count one shared cold start."""
        return max((a.delay_s or 0.0 for a in self.assets), default=0.0)

    # TODO(runpod #1): counts execution only. If RunPod bills any of delayTime, every cost we
    # print understates it — verify against a real invoice before trusting these figures.
    @property
    def total_cost_usd(self) -> float | None:
        costs = [a.cost_usd for a in self.assets if a.cost_usd is not None]
        return sum(costs) if costs else None

    def render(self) -> str:
        # The interesting ratio is compute vs waiting: a serverless endpoint that scaled to zero
        # spends most of a run booting, and that is a console setting to change, not code.
        queued = self.max_delay_s
        share = f" ({queued / self.wall_s * 100:.0f}% of wall)" if self.wall_s and queued else ""
        lines = [
            f"  TRELLIS/RunPod batch: {self.ok_count}/{len(self.assets)} ok  "
            f"wall={self.wall_s:.1f}s  exec(sum)={self.total_exec_s:.1f}s"
            + (f"  queue+coldstart={queued:.1f}s{share}" if queued else "")
            + (f"  cost=${self.total_cost_usd:.4f}" if self.total_cost_usd is not None else "")
        ]
        for a in self.assets:
            c = f" ${a.cost_usd:.4f}" if a.cost_usd is not None else ""
            e = f" exec={a.exec_s:.1f}s" if a.exec_s is not None else ""
            d = f" queued={a.delay_s:.1f}s" if a.delay_s else ""
            status = "ok " if a.ok else "ERR"
            lines.append(
                f"    [{status}] {a.asset_id:16s} wall={a.wall_s:5.1f}s{d}{e}{c}"
                + ("" if a.ok else f"  {a.error}")
            )
        return "\n".join(lines)


def _api_key_from_env() -> str | None:
    for n in ("RUNPOD_API_KEY", "RUNPOD"):
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return None


class RunPodTrellisService:
    name = "trellis-runpod"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint_id: str | None = None,
        base_url: str = "https://api.runpod.ai/v2",
        poll_interval: float = 3.0,
        job_timeout: float = 900.0,
        max_parallel: int = 8,
        gpu_usd_per_hour: float | None = None,  # for cost; else $env RUNPOD_GPU_USD_PER_HR
        client: Any = None,  # injectable for tests (mock)
    ) -> None:
        self.poll_interval = poll_interval
        self.job_timeout = float(os.environ.get("RUNPOD_JOB_TIMEOUT", "").strip() or job_timeout)
        # $RUNPOD_MAX_PARALLEL overrides — submit all objects at once (RunPod scales workers)
        self.max_parallel = int(os.environ.get("RUNPOD_MAX_PARALLEL", "").strip() or max_parallel)
        rate = gpu_usd_per_hour
        if rate is None:
            env_rate = os.environ.get("RUNPOD_GPU_USD_PER_HR", "").strip()
            rate = float(env_rate) if env_rate else None
        self.gpu_usd_per_hour = rate
        self.last_report: BatchReport | None = None
        if client is not None:
            self.client = client
        else:
            key = api_key or _api_key_from_env()
            ep = endpoint_id or os.environ.get("RUNPOD_TRELLIS_ENDPOINT", "").strip()
            if not key or not ep:
                raise ValueError(
                    "RunPod TRELLIS needs RUNPOD_API_KEY (or RUNPOD) and RUNPOD_TRELLIS_ENDPOINT."
                )
            self.client = RunPodClient(key, ep, base_url=base_url)

    # -- Generation3DService -----------------------------------------------------
    def reconstruct(
        self, images: list[Any], *, out_dir: str, asset_id: str = "asset", **opts: Any
    ) -> str:
        """One asset (first image) → one GLB path."""
        image = images[0] if isinstance(images, (list, tuple)) else images
        return self.reconstruct_many({asset_id: image}, out_dir=out_dir, **opts)[asset_id]

    def reconstruct_many(
        self,
        items: dict[str, Any],
        *,
        out_dir: str,
        seed: int = 42,
        simplify: float = 0.95,
        texture_size: int = 1024,
    ) -> dict[str, str]:
        """{asset_id: image(path|PIL|bytes)} → {asset_id: glb_path}, run in PARALLEL on RunPod.

        Failed assets map to "" (logged), so one bad asset doesn't sink the batch.
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        results: dict[str, str] = {}
        report = BatchReport()
        rate_s = (self.gpu_usd_per_hour / 3600.0) if self.gpu_usd_per_hour else None

        def one(asset_id: str, image: Any) -> AssetReport:
            t0 = time.monotonic()
            payload = {
                "image_b64": _image_b64(image),
                "seed": seed,
                "simplify": simplify,
                "texture_size": texture_size,
            }
            job_id = self.client.run(payload)
            output, exec_ms, delay_ms = self._await(job_id)
            glb_path = out / f"{asset_id}.glb"
            _write_glb(output, glb_path, http_timeout=self.client.http_timeout)
            exec_s = (exec_ms / 1000.0) if exec_ms is not None else None
            delay_s = (delay_ms / 1000.0) if delay_ms is not None else None
            cost = (exec_s * rate_s) if (exec_s is not None and rate_s is not None) else None
            return AssetReport(asset_id, True, time.monotonic() - t0, exec_s, cost,
                               str(glb_path), delay_s=delay_s)

        batch_t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=self.max_parallel) as pool:
            futs = {
                pool.submit(one, aid, img): (aid, time.monotonic()) for aid, img in items.items()
            }
            for fut in as_completed(futs):
                aid, started = futs[fut]
                try:
                    rep = fut.result()
                except Exception as e:  # noqa: BLE001 — isolate one bad asset
                    rep = AssetReport(
                        aid,
                        False,
                        time.monotonic() - started,
                        None,
                        None,
                        error=f"{type(e).__name__}: {e}",
                    )
                    print(f"  [trellis-runpod] {aid} FAILED: {rep.error}", flush=True)
                report.assets.append(rep)
                results[aid] = rep.glb_path
        report.wall_s = time.monotonic() - batch_t0
        report.assets.sort(key=lambda a: a.asset_id)
        self.last_report = report
        print(report.render(), flush=True)
        return results

    def _await(self, job_id: str) -> tuple[dict, float | None, float | None]:
        """Return (output, executionTime_ms, delayTime_ms), both reported on COMPLETED.

        `delayTime` is how long the job sat before its handler started — queue plus, on a cold
        endpoint, the worker boot: image pull, network-volume mount, and loading TRELLIS weights
        into VRAM. On an endpoint that has scaled to zero this dwarfs the actual generation, and
        separating the two is the difference between "the model is slow" and "nothing was warm".
        """
        deadline = time.monotonic() + self.job_timeout
        while True:
            st = self.client.status(job_id)
            status = st.get("status")
            if status in _TERMINAL_OK:
                exec_ms, delay_ms = st.get("executionTime"), st.get("delayTime")
                return (
                    (st.get("output") or {}),
                    (float(exec_ms) if exec_ms is not None else None),
                    (float(delay_ms) if delay_ms is not None else None),
                )
            if status in _TERMINAL_BAD:
                raise RuntimeError(f"job {job_id} {status}: {st.get('error') or st}")
            if time.monotonic() > deadline:
                self.client.cancel(job_id)
                raise TimeoutError(f"job {job_id} exceeded {self.job_timeout}s (last={status})")
            time.sleep(self.poll_interval)


# -- helpers ---------------------------------------------------------------------
def _image_b64(image: Any) -> str:
    if isinstance(image, (bytes, bytearray)):
        return base64.b64encode(image).decode()
    if isinstance(image, (str, os.PathLike)):
        return base64.b64encode(Path(image).read_bytes()).decode()
    # PIL image
    import io

    buf = io.BytesIO()
    image.convert("RGBA").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _write_glb(output: dict, path: Path, *, http_timeout: float) -> None:
    if "glb_b64" in output:
        path.write_bytes(base64.b64decode(output["glb_b64"]))
        return
    if "glb_url" in output:
        with urllib.request.urlopen(output["glb_url"], timeout=http_timeout) as r:
            path.write_bytes(r.read())
        return
    raise RuntimeError(f"worker output has no glb_b64/glb_url: keys={list(output)}")
