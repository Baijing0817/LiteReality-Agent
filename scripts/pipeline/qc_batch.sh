#!/usr/bin/env bash
# Run the public quality stage for one or more existing scenes.
set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../.."

CONCURRENCY="${CONCURRENCY:-2}"
[ "$#" -gt 0 ] || {
  echo "usage: [CONCURRENCY=n] scripts/pipeline/qc_batch.sh <scan> [<scan> ...]"
  exit 2
}

run_one() {
  local scan="$1"
  local log="run/$scan/qc_logs/qc_$(date +%Y%m%d_%H%M%S).log"
  mkdir -p "$(dirname "$log")"
  echo "[quality] $scan -> $log"
  if uv run litereality stage quality "$scan" --force >"$log" 2>&1; then
    echo "[done] $scan"
  else
    echo "[failed] $scan; see $log"
    return 1
  fi
}

echo "== quality batch: $# scene(s), concurrency=$CONCURRENCY =="
for scan in "$@"; do
  while [ "$(jobs -rp | wc -l)" -ge "$CONCURRENCY" ]; do wait -n; done
  run_one "$scan" &
done
wait
