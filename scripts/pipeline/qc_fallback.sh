#!/usr/bin/env bash
# Compatibility wrapper: retry the public quality stage for selected scenes.
set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../.."

CONCURRENCY="${CONCURRENCY:-6}"
[ "$#" -gt 0 ] || {
  echo "usage: [CONCURRENCY=n] scripts/pipeline/qc_fallback.sh <scan> [<scan> ...]"
  exit 2
}

run_one() {
  local scan="$1"
  local log="run/$scan/qc_logs/qc_retry_$(date +%Y%m%d_%H%M%S).log"
  mkdir -p "$(dirname "$log")"
  echo "[quality retry] $scan -> $log"
  uv run litereality stage quality "$scan" --force >"$log" 2>&1
}

for scan in "$@"; do
  while [ "$(jobs -rp | wc -l)" -ge "$CONCURRENCY" ]; do wait -n; done
  run_one "$scan" &
done
wait
