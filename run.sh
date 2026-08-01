#!/usr/bin/env bash
# Deprecated compatibility launcher. Pipeline orchestration lives in Python.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT"
echo "note: ./run.sh is deprecated; use: uv run litereality run $*" >&2
exec uv run litereality run "$@"
