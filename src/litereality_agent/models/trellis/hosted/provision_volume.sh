#!/usr/bin/env bash
# Provision a RunPod NETWORK VOLUME with your exact trellis2 env so the serverless worker runs
# identically to local, with NO finicky image build. Two parts: (A) pack locally, (B) unpack on
# a temp pod that has the volume mounted. Read it; run the parts on the right machines.
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# PART A — on the machine that HAS the working trellis2 conda env
# ─────────────────────────────────────────────────────────────────────────────
# Bundle the env (conda-pack fixes up absolute paths so it relocates onto the volume) and the
# TRELLIS repo. Make sure `runpod` is installed INTO the env first (the handler imports it).
part_a_pack() {
  local TRELLIS_ENV="${1:-trellis2}"                       # conda env name
  local TRELLIS_REPO="${2:-/path/to/TRELLIS}"              # the TRELLIS clone
  conda run -n "$TRELLIS_ENV" pip install --no-input runpod conda-pack
  conda run -n "$TRELLIS_ENV" python -m conda_pack -n "$TRELLIS_ENV" -o /tmp/trellis2-env.tar.gz --force
  tar czf /tmp/TRELLIS.tar.gz -C "$(dirname "$TRELLIS_REPO")" "$(basename "$TRELLIS_REPO")"
  echo "packed: /tmp/trellis2-env.tar.gz  +  /tmp/TRELLIS.tar.gz"
  echo "→ upload both to the temp pod (scp / runpodctl send), then run PART B there."
}

# ─────────────────────────────────────────────────────────────────────────────
# PART B — on a CHEAP temp pod with the network volume mounted at /runpod-volume
# (create the volume in the RunPod console, attach it to any small GPU/CPU pod, scp the tarballs)
# ─────────────────────────────────────────────────────────────────────────────
part_b_unpack() {
  local VOL=/runpod-volume
  mkdir -p "$VOL/trellis2-env" "$VOL/hf-cache"
  tar xzf /tmp/trellis2-env.tar.gz -C "$VOL/trellis2-env"
  "$VOL/trellis2-env/bin/conda-unpack"                      # fix relocated paths
  tar xzf /tmp/TRELLIS.tar.gz -C "$VOL"                     # → /runpod-volume/TRELLIS
  # pre-cache the weights so the first real job doesn't pay the download:
  HF_HOME="$VOL/hf-cache" PYTHONPATH="$VOL/TRELLIS" \
    "$VOL/trellis2-env/bin/python" - <<'PY'
from trellis.pipelines import TrellisImageTo3DPipeline as P
P.from_pretrained("microsoft/TRELLIS-image-large")
print("weights cached to /runpod-volume/hf-cache")
PY
  echo "volume ready: trellis2-env + TRELLIS + hf-cache"
}

case "${1:-}" in
  pack)   shift; part_a_pack "$@";;
  unpack) part_b_unpack;;
  *) echo "usage: $0 pack [env_name] [trellis_repo]   # on the trellis2 machine";
     echo "       $0 unpack                            # on the temp pod (volume mounted)"; exit 1;;
esac
