#!/usr/bin/env bash
# run_trellis.sh — image -> GLB via the pristine TRELLIS.2 clone.
#
# Picks an interpreter that has the TRELLIS.2 runtime (torch 2.6+cu124, o_voxel,
# natten) and forwards all args to trellis_launcher.py. Weights auto-download into
# backends/weights/ on first run. The clone itself is never modified.
#
# Interpreter resolution (first that exists):
#   $LITEREALITY_TRELLIS_PYTHON  ->  <repo>/.venv/bin/python  ->  trellis2 conda env
#
#   ./run_trellis.sh -i ref.png -o out/ref.glb
#   ./run_trellis.sh -i refs/   -o out/            # batch
#   ./run_trellis.sh -i refs/   -o out/ --parallel 2 --seed 7 --decimation 50000
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../.." && pwd)"

pick_python() {
  for cand in "${LITEREALITY_TRELLIS_PYTHON:-}" \
              "$REPO_ROOT/.venv/bin/python"; do
    if [[ -n "$cand" && -x "$cand" ]]; then echo "$cand"; return 0; fi
  done
  command -v python3
}

PYTHON="$(pick_python)"
echo "[run_trellis] interpreter: $PYTHON" >&2
exec "$PYTHON" "$HERE/trellis_launcher.py" "$@"
