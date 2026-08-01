#!/usr/bin/env bash
# run_grounding_dino.sh — open-vocab detection via the GroundingDINO clone.
#
# Same interpreter resolution as run_trellis.sh; forwards all args to
# grounding_dino_launcher.py. The Swin-T checkpoint auto-downloads into
# backends/weights/ on first run; the clone is never modified.
#
#   ./run_grounding_dino.sh -i frame.jpg -p "a chair . a table" -o boxes.json
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
echo "[run_grounding_dino] interpreter: $PYTHON" >&2
exec "$PYTHON" "$HERE/grounding_dino_launcher.py" "$@"
