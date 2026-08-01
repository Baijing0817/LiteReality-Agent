#!/usr/bin/env bash
# reconstruct_all.sh — run object reconstruction for EVERY scan with BOUNDED GPU parallelism.
#
# Each scene's opening-builder spawns a local GroundingDINO worker (~2.2 GiB VRAM) and the
# procedural agent renders in Blender (also GPU). Running many at once OOMs a 24 GiB GPU, so we
# cap concurrency to LR_RECON_PARALLEL scenes at a time (default 5) and let waves roll through.
# TRELLIS itself is remote (RunPod) so it doesn't add local GPU pressure. Idempotent: finished GLBs
# are skipped, so this safely resumes the scenes the un-throttled run left partial.
#
# The worklist defaults to every scan directory under $LR_SCANS_DIR; pass scan names to narrow it.
#
#   src/litereality_agent/scripts/reconstruct_all.sh                 # every scan, 5-wide
#   src/litereality_agent/scripts/reconstruct_all.sh <scan> [...]    # just these
#   LR_RECON_PARALLEL=3 src/litereality_agent/scripts/reconstruct_all.sh
#   src/litereality_agent/scripts/reconstruct_all.sh --force         # rebuild even existing GLBs
#
# Watch:  tail -f run/<scan>/reconstruct.log   ·   overall: tail -f run/_recon_all.log
set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../../.."   # repo root (this lives in src/litereality_agent/scripts/)
[ -f .env ] && { set -a; . ./.env; set +a; }
# reduce CUDA fragmentation across the wave hand-offs
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"
export LR_SCANS_DIR="${LR_SCANS_DIR:-$PWD/scans_uploaded}"
MAXP="${LR_RECON_PARALLEL:-5}"

FORCE=""
ARGS=()
for a in "$@"; do
  case "$a" in
    --force) FORCE="--force" ;;
    *) ARGS+=("$a") ;;
  esac
done

# Worklist: explicit args, else every scan directory found under $LR_SCANS_DIR.
if [ ${#ARGS[@]} -gt 0 ]; then
  SCENES=("${ARGS[@]}")
else
  SCENES=()
  for d in "$LR_SCANS_DIR"/*/; do [ -d "$d" ] && SCENES+=("$(basename "$d")"); done
fi
[ ${#SCENES[@]} -gt 0 ] || {
  echo "no scans found in $LR_SCANS_DIR"
  echo "usage: [LR_RECON_PARALLEL=n] src/litereality_agent/scripts/reconstruct_all.sh [--force] [<scan> ...]"
  exit 2
}

echo "== reconstruct_all: ${#SCENES[@]} scenes, up to $MAXP in parallel =="
for S in "${SCENES[@]}"; do
  # throttle: block until fewer than MAXP jobs are running
  while [ "$(jobs -rp | wc -l)" -ge "$MAXP" ]; do wait -n; done
  echo "▶ launching $S"
  src/litereality_agent/scripts/reconstruct_objects.sh $FORCE "$S" > "run/_recon_${S}.log" 2>&1 &
done
wait
echo
echo "== reconstruct_all DONE =="
for S in "${SCENES[@]}"; do
  n=$(find "run/$S/scene_init/obj_stage/reconstructed_objs" -name '*.glb' 2>/dev/null | wc -l)
  printf "  %-36s %s GLBs\n" "$S" "$n"
done
