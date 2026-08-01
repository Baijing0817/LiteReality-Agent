#!/usr/bin/env bash
# CONTINUE the QC on top with Opus 4.8 for scenes whose Fable QC hit the session limit.
# Runs qc_pass.py on the EXISTING _qc/room (does NOT re-copy from _oneshot), so Fable's partial edits
# are preserved and Opus picks up where it left off ("edit on the top").
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

CONCURRENCY="${CONCURRENCY:-6}"
MODEL="${QC_MODEL:-claude-opus-5}"
PY="${LR_PYTHON:-.venv/bin/python}"
[ $# -gt 0 ] || { echo "usage: [CONCURRENCY=n] src/litereality_agent/scripts/qc_fallback.sh <scan> [<scan> ...]"; exit 2; }

run_one(){
  local s="$1"
  local OUT="$PWD/run/$s"
  local QC="$OUT/scene_init/scene_stage/_qc/room"
  if [ ! -f "$QC/Room.py" ]; then echo "[skip] $s — no _qc/room (run qc_batch first)"; return 1; fi
  mkdir -p "run/$s/qc_logs"
  local LOG="run/$s/qc_logs/qc_opus_$(date +%Y%m%d_%H%M%S).log"
  echo "[opus-qc] $s  -> $LOG  (continuing ON TOP of Fable's partial _qc edits)"
  ( export LITEREALITY_SCAN="$s"
    HARNESS_MODEL="$MODEL" $PY -m litereality_agent.realism_authoring.qc_pass \
      --room "$QC" --surface-ref "$OUT/scene_init/scene_stage/_harness/surface_ref" \
      --scan "$LR_SCANS_DIR/$s" --refroot "$OUT/scene_init/obj_stage/object_init" --model "$MODEL" ) > "$LOG" 2>&1
  echo "[done] $s exit=$?  $(grep -oE 'QC done [0-9]+m[0-9]+s' "$LOG" | head -1)"
}

echo "== Opus-4.8 QC fallback: $# scene(s), concurrency=$CONCURRENCY, model=$MODEL =="
for s in "$@"; do
  while [ "$(jobs -rp | wc -l)" -ge "$CONCURRENCY" ]; do wait -n; done
  run_one "$s" &
done
wait
echo "== Opus fallback DONE =="
