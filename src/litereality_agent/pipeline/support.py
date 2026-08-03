from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable

from litereality_agent.pipeline.context import RunContext
from litereality_agent.pipeline.result import StageResult, StageStatus


def run_module(
    context: RunContext,
    module: str,
    args: Iterable[object] = (),
    *,
    log_name: str | None = None,
) -> tuple[int, Path | None]:
    log = None
    stream = None
    if log_name:
        log = context.authoring_root / "logs" / f"{log_name}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = log.open("w", encoding="utf-8")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", module, *(str(arg) for arg in args)],
            cwd=context.repo_root,
            env=context.environment,
            stdout=stream,
            stderr=subprocess.STDOUT if stream else None,
        )
        return proc.returncode, log
    finally:
        if stream:
            stream.close()


def command_result(
    stage: str,
    rc: int,
    *,
    artifacts: dict[str, Path] | None = None,
    log: Path | None = None,
    allow_nonzero: bool = False,
) -> StageResult:
    paths = {name: str(path) for name, path in (artifacts or {}).items() if path.exists()}
    warnings = []
    if rc and allow_nonzero:
        warnings.append(f"command exited {rc}" + (f"; see {log}" if log else ""))
    return StageResult(
        stage,
        StageStatus.COMPLETED if rc == 0 or allow_nonzero else StageStatus.FAILED,
        artifacts=paths,
        warnings=warnings,
        error=None if rc == 0 or allow_nonzero else f"command exited {rc}" + (f"; see {log}" if log else ""),
    )
