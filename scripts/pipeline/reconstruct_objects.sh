#!/usr/bin/env bash
# reconstruct_objects.sh — OBJECT RECONSTRUCTION (the stage we deferred): reference images -> GLBs.
#
# Per scene, runs object_init with the reconstruction stages:
#   --classify        VLM (Claude) routes each object procedural vs trellis
#   --reconstruct     trellis-route objects -> GLBs via TRELLIS (RunPod when $RUNPOD_TRELLIS_ENDPOINT)
#   --procedural      procedural-route objects -> GLBs via the Claude articulated agent (Blender)
#   --build-openings  doors/windows -> articulated GLBs
# Output lands in run/<scan>/scene_init/obj_stage/reconstructed_objs/. Idempotent (skip_existing);
# use --force to rebuild. Non-fatal per object (failures are logged, the scene keeps going).
#
#   scripts/pipeline/reconstruct_objects.sh <scan> [<scan> ...]   # reconstruct these scenes (sequential)
#   scripts/pipeline/reconstruct_objects.sh --force <scan>        # rebuild even existing GLBs
# For MAX PARALLEL, launch one invocation per scene in the background (that's how we run all 11).
#
# Watch:  tail -f run/<scan>/reconstruct.log
set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../.."   # repo root (this lives in scripts/pipeline/)
[ -f .env ] && { set -a; . ./.env; set +a; }
[ -f models.env ] && . ./models.env

PY="${LR_PYTHON:-.venv/bin/python}"
export LITEREALITY_BLENDER="${LITEREALITY_BLENDER:-${BLENDER:-}}"
[ -n "$LITEREALITY_BLENDER" ] && export PATH="$LITEREALITY_BLENDER:$PATH"
export LR_SCANS_DIR="${LR_SCANS_DIR:-$PWD/scans_uploaded}"
export LITEREALITY_OUTPUT="${LITEREALITY_OUTPUT:-$PWD/run}"
export LITEREALITY_FINAL="${LITEREALITY_FINAL:-$PWD/run}"

CONCURRENCY="${LR_RECON_CONCURRENCY:-2}"   # articulated-agent concurrent jobs PER scene
FORCE=""
ARGS=()
for a in "$@"; do
  case "$a" in
    --force) FORCE="--force" ;;
    *) ARGS+=("$a") ;;
  esac
done
[ ${#ARGS[@]} -gt 0 ] || { echo "usage: scripts/pipeline/reconstruct_objects.sh [--force] <scan> [<scan> ...]"; exit 2; }

# keep the back-compat symlink run/<scan>/scene_init/obj_stage -> run/<scan>/scene_init/obj_stage
link_obj_stage(){
  local S="$1"; local real="$LITEREALITY_FINAL/$S/scene_init/obj_stage"; local link="$LITEREALITY_OUTPUT/$S/obj_stage"
  mkdir -p "$real" "$LITEREALITY_OUTPUT/$S"
  [ -e "$link" ] || ln -sfn "$real" "$link"
}

n=0; ok=0; fail=0
for S in "${ARGS[@]}"; do
  n=$((n+1))
  if [ ! -d "$LR_SCANS_DIR/$S" ]; then echo "✗ $S — no scan dir"; fail=$((fail+1)); continue; fi
  link_obj_stage "$S"
  log="$LITEREALITY_OUTPUT/$S/reconstruct.log"; mkdir -p "$(dirname "$log")"
  echo "[$n/${#ARGS[@]}] ▶  reconstruct $S   (log: $log)"
  t0=$(date +%s)
  if uv run litereality stage reconstruct "$S" $FORCE >"$log" 2>&1; then
    dt=$(( $(date +%s) - t0 ))
    nglb=$(command find "$LITEREALITY_FINAL/$S/scene_init/obj_stage/reconstructed_objs" -name '*.glb' 2>/dev/null | wc -l)
    echo "[$n/${#ARGS[@]}] ✓  $S  (${dt}s, ${nglb} GLBs)"; ok=$((ok+1))
  else
    echo "[$n/${#ARGS[@]}] ✗  $S — failed; last lines:"; tail -n 15 "$log" | sed 's/^/      /'; fail=$((fail+1))
  fi
done
echo
echo "== reconstruct done: $ok ok · $fail failed (of $n) =="
[ "$fail" = 0 ]
