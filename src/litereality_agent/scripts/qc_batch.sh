#!/usr/bin/env bash
# QC pass (Fable-5) over already-authored scenes, WITHOUT overwriting the _oneshot result.
# For each scene: copy _oneshot/room -> _qc/room, run litereality_agent.realism_authoring.qc_pass on the copy, log + time it.
# Concurrency-capped. Per-scene timing is printed by qc_pass.py ("QC done XmYYs").
set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../../.."   # repo root (this lives in src/litereality_agent/scripts/)
[ -f .env ] && { set -a; . ./.env; set +a; }
[ -f models.env ] && . ./models.env
export LITEREALITY_BLENDER="${LITEREALITY_BLENDER:-${BLENDER:-}}"
[ -n "$LITEREALITY_BLENDER" ] && export PATH="$LITEREALITY_BLENDER:$PATH"
export LR_SCANS_DIR="${LR_SCANS_DIR:-$PWD/scans_uploaded}"
export LR_CACHE="${LR_CACHE:-$PWD/.cache}"
export HF_HOME="${HF_HOME:-$LR_CACHE/huggingface}"; export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$LR_CACHE/xdg}"
export TMPDIR="${TMPDIR:-$LR_CACHE/tmp}"; mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$TMPDIR"

CONCURRENCY="${CONCURRENCY:-2}"
QC_MODEL="${QC_MODEL:-claude-opus-5}"
PY="${LR_PYTHON:-.venv/bin/python}"
SCENES=("$@")
[ ${#SCENES[@]} -gt 0 ] || { echo "usage: [CONCURRENCY=n] src/litereality_agent/scripts/qc_batch.sh <scan> [<scan> ...]"; exit 2; }

run_one(){
  local s="$1"
  local OUT="$PWD/run/$s"
  local SRC="$OUT/scene_init/scene_stage/_oneshot/room"
  local QCDIR="$OUT/scene_init/scene_stage/_qc"
  local QC="$QCDIR/room"
  local SURFREF="$OUT/scene_init/scene_stage/_harness/surface_ref"
  local SCAN_DIR="$LR_SCANS_DIR/$s"
  local REFROOT="$OUT/scene_init/obj_stage/object_init"
  if [ ! -f "$SRC/Room.py" ]; then echo "[skip] $s — no authored room at $SRC"; return 1; fi
  mkdir -p "run/$s/qc_logs"
  local LOG="run/$s/qc_logs/qc_$(date +%Y%m%d_%H%M%S).log"
  # fresh copy so the authored _oneshot is NEVER overwritten
  rm -rf "$QCDIR" && mkdir -p "$QCDIR" && cp -r "$SRC" "$QC"
  echo "[qc] $s  -> $LOG   (result in $QC, _oneshot preserved)"
  ( export LITEREALITY_SCAN="$s"
    HARNESS_MODEL="$QC_MODEL" $PY -m litereality_agent.realism_authoring.qc_pass \
      --room "$QC" --surface-ref "$SURFREF" --scan "$SCAN_DIR" --refroot "$REFROOT" \
      --model "$QC_MODEL" ) > "$LOG" 2>&1
  echo "[done] $s exit=$?  $(grep -oE 'QC done [0-9]+m[0-9]+s' "$LOG" | head -1)"
}

echo "== QC batch: ${#SCENES[@]} scene(s), concurrency=$CONCURRENCY, model=$QC_MODEL =="
for s in "${SCENES[@]}"; do
  while [ "$(jobs -rp | wc -l)" -ge "$CONCURRENCY" ]; do wait -n; done
  run_one "$s" &
done
wait
echo "== QC batch: ALL DONE =="
