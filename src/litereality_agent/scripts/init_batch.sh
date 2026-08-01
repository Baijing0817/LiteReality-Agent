#!/usr/bin/env bash
# init_batch.sh — run ONLY the deterministic init stage (crops → DINO → refs → reconstruct →
# seed Room.py/Room.glb) for a set of scenes, sequentially. This is the heavy stage
# (GPU/TRELLIS + paid image-gen), so it runs one scene at a time and SKIPS any scene whose
# room_init already exists (idempotent — safe to re-run). Full pipeline (author/refine/export)
# is still ./run.sh <scan>; this just front-loads init so every scan is seeded.
#
# The worklist defaults to every scan directory under $LR_SCANS_DIR; pass scan names to narrow it.
#
#   src/litereality_agent/scripts/init_batch.sh                 # init every scan that isn't done yet
#   src/litereality_agent/scripts/init_batch.sh --force         # re-init even scenes that already have room_init
#   src/litereality_agent/scripts/init_batch.sh <scan> [<scan>] # init just these
#
# Watch progress:  tail -f run/<scan>/init.log
set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../../.."   # repo root (this lives in src/litereality_agent/scripts/)
[ -f .env ] && { set -a; . ./.env; set +a; }
[ -f models.env ] && . ./models.env

PY="${LR_PYTHON:-.venv/bin/python}"
export LITEREALITY_BLENDER="${LITEREALITY_BLENDER:-${BLENDER:-}}"
[ -n "$LITEREALITY_BLENDER" ] && export PATH="$LITEREALITY_BLENDER:$PATH"
export LR_SCANS_DIR="${LR_SCANS_DIR:-$PWD/scans_uploaded}"
export LITEREALITY_OUTPUT="${LITEREALITY_OUTPUT:-$PWD/run}"
export LR_IMAGE_PROVIDER="${LR_IMAGE_PROVIDER:-openai}"
export LR_CLASSIFY_PROVIDER="${LR_CLASSIFY_PROVIDER:-claude}"
export HARNESS_VLM="${HARNESS_VLM:-claude}"

FORCE=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --force) FORCE=1 ;;
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
  echo "usage: src/litereality_agent/scripts/init_batch.sh [--force] [<scan> ...]"
  exit 2
}

done_marker(){ [ -f "$LITEREALITY_OUTPUT/$1/scene_init/scene_stage/room_init/room/Room.py" ]; }

n=0; ok=0; skip=0; fail=0
for S in "${SCENES[@]}"; do
  n=$((n+1))
  if [ "$FORCE" != 1 ] && done_marker "$S"; then
    echo "[$n/${#SCENES[@]}] ⏭  $S — room_init exists, skipping (use --force to redo)"
    skip=$((skip+1)); continue
  fi
  if [ ! -d "$LR_SCANS_DIR/$S" ]; then
    echo "[$n/${#SCENES[@]}] ✗  $S — no scan dir at $LR_SCANS_DIR/$S"
    fail=$((fail+1)); continue
  fi
  log="$LITEREALITY_OUTPUT/$S/init.log"
  mkdir -p "$(dirname "$log")"
  echo "[$n/${#SCENES[@]}] ▶  init $S   (log: $log)"
  t0=$(date +%s)
  if $PY -m litereality_agent scene_init "$S" >"$log" 2>&1; then
    dt=$(( $(date +%s) - t0 ))
    echo "[$n/${#SCENES[@]}] ✓  $S  (${dt}s)"; ok=$((ok+1))
  else
    echo "[$n/${#SCENES[@]}] ✗  $S — init failed; last lines:"
    tail -n 15 "$log" | sed 's/^/      /'
    fail=$((fail+1))
  fi
done

echo
echo "== init_batch done: $ok ok · $skip skipped · $fail failed (of $n) =="
[ "$fail" = 0 ]
