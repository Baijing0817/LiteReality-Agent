#!/usr/bin/env bash
# preprocess_objects.sh — OBJECT-STAGE PREPROCESS ONLY, stopping BEFORE any generation.
#
# Runs object_init through: extract → crop → GroundingDINO bbox refine → object_references(crops)
# → CHAIR GROUPING (Claude Opus judge) → opening_references(crops). It STOPS there — NO reference
# image-gen (nano-banana / gpt-image) and NO TRELLIS / procedural GLB build. The chair-type judge
# still runs (Claude subscription, not metered); no OpenAI/Gemini key is used.
#
# This is the cheap, GPU-light front-load: get every scene grouped + cropped so image-gen and
# reconstruction can be decided/run later.  (Full seed init is still scripts/pipeline/init_batch.sh <scan>.)
#
# The worklist defaults to every scan directory under $LR_SCANS_DIR; pass scan names to narrow it.
#
#   scripts/pipeline/preprocess_objects.sh                 # preprocess every scan not done yet
#   scripts/pipeline/preprocess_objects.sh --force         # redo even scenes already grouped
#   scripts/pipeline/preprocess_objects.sh <scan> [<scan>] # just these
#
# Watch:  tail -f run/<scan>/preprocess.log
set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../.."   # repo root (this lives in scripts/pipeline/)
[ -f .env ] && { set -a; . ./.env; set +a; }
[ -f models.env ] && . ./models.env

PY="${LR_PYTHON:-.venv/bin/python}"
export LITEREALITY_BLENDER="${LITEREALITY_BLENDER:-${BLENDER:-}}"
[ -n "$LITEREALITY_BLENDER" ] && export PATH="$LITEREALITY_BLENDER:$PATH"
export LR_SCANS_DIR="${LR_SCANS_DIR:-$PWD/scans_uploaded}"
export LITEREALITY_OUTPUT="${LITEREALITY_OUTPUT:-$PWD/run}"
# object grouping is DINOv2 + a Claude Opus judge; keep the judge ON (default). No image provider is
# exercised here (--skip-gemini), so no OPENAI_API_KEY / GEMINI_API_KEY is required for this stage.
export LR_CHAIR_JUDGE="${LR_CHAIR_JUDGE:-1}"
# object clustering writes NATIVELY under run/object_clustering/<scan>/ now
# (litereality_agent.pipeline.paths::chair_clusters_root). Keep this root in sync with that config /
# run.sh's FINAL_ROOT so the grouped-marker check below looks in the right place.
FINAL_ROOT="${LITEREALITY_FINAL:-$PWD/run}"

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
  echo "usage: scripts/pipeline/preprocess_objects.sh [--force] [<scan> ...]"
  exit 2
}

# grouped-marker: chair_clusters.json lives under the (relocated) obj_stage tree
grouped(){ [ -f "$FINAL_ROOT/$1/scene_init/obj_stage/object_init/chair_clusters/$1/chair_clusters.json" ]; }

n=0; ok=0; skip=0; fail=0
for S in "${SCENES[@]}"; do
  n=$((n+1))
  if [ "$FORCE" != 1 ] && grouped "$S"; then
    echo "[$n/${#SCENES[@]}] ⏭  $S — already grouped, skipping (use --force to redo)"
    skip=$((skip+1)); continue
  fi
  if [ ! -d "$LR_SCANS_DIR/$S" ]; then
    echo "[$n/${#SCENES[@]}] ✗  $S — no scan dir at $LR_SCANS_DIR/$S"
    fail=$((fail+1)); continue
  fi
  log="$LITEREALITY_OUTPUT/$S/preprocess.log"
  mkdir -p "$(dirname "$log")"
  # PREFLIGHT: an interrupted earlier extraction can leave a PARTIAL input/rgbd tree (fewer depth/
  # image frames than poses). scene_data_complete() still calls it "complete", so object_init would
  # REUSE the broken tree and crop crashes on the missing depth frame (NoneType .shape). Detect the
  # count mismatch here and force a clean re-extract for just this scene so the run never wastes time
  # on a silently-truncated intermediate.
  R="$LITEREALITY_OUTPUT/$S/scene_init/obj_stage/object_init/input/rgbd/$S"
  FORCE_EXTRACT=""
  if [ -d "$R" ]; then
    nd=$(ls "$R/depth" 2>/dev/null | wc -l); ni=$(ls "$R/image" 2>/dev/null | wc -l)
    nk=$(ls "$R/intrinsic" 2>/dev/null | wc -l); ne=$(ls "$R/extrinsic" 2>/dev/null | wc -l)
    if [ "$nd" != "$ni" ] || [ "$nd" != "$nk" ] || [ "$nd" != "$ne" ]; then
      echo "   ⚠  partial rgbd tree (depth=$nd image=$ni intr=$nk extr=$ne) — deleting + forcing re-extract"
      rm -rf "$R"; FORCE_EXTRACT="--force"
    fi
  fi
  echo "[$n/${#SCENES[@]}] ▶  preprocess $S   (log: $log)"
  t0=$(date +%s)
  # --skip-gemini: no reference image-gen. no --reconstruct/--classify/--procedural: stop before
  # TRELLIS/procedural. Judge grouping runs regardless.
  if uv run litereality stage ingest "$S" --skip-image-generation $FORCE_EXTRACT >"$log" 2>&1; then
    dt=$(( $(date +%s) - t0 ))
    echo "[$n/${#SCENES[@]}] ✓  $S  (${dt}s)"; ok=$((ok+1))
  else
    echo "[$n/${#SCENES[@]}] ✗  $S — failed; last lines:"
    tail -n 15 "$log" | sed 's/^/      /'
    fail=$((fail+1))
  fi
done

echo
echo "== preprocess_objects done: $ok ok · $skip skipped · $fail failed (of $n) =="
[ "$fail" = 0 ]
