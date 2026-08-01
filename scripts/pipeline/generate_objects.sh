#!/usr/bin/env bash
# generate_objects.sh — OBJECT-STAGE IMAGE GENERATION, stopping BEFORE reconstruction.
#
# Runs object_init WITHOUT --skip-gemini so every reference image is generated via OpenAI
# (LR_IMAGE_PROVIDER=openai → gpt-image, model = $LR_OPENAI_IMAGE_MODEL, default gpt-image-2):
#   object_references (per non-chair object) + chair-cluster references + opening references.
# It does NOT pass --reconstruct/--classify/--procedural, so NO TRELLIS and NO procedural GLB
# build happens — image generation only. Chair grouping (Claude judge) re-runs harmlessly.
#
# Idempotent: nano_banana skips any reference image that already exists, so re-running only fills
# gaps (use --force-images to regenerate). All output lands in run/<scan>/scene_init/obj_stage/.
#
# The worklist defaults to every scan directory under $LR_SCANS_DIR; pass scan names to narrow it.
#
#   scripts/pipeline/generate_objects.sh                 # generate for every scan
#   scripts/pipeline/generate_objects.sh <scan> [<scan>] # just these
#   scripts/pipeline/generate_objects.sh --force-images  # regenerate even existing images
#
# Watch:  tail -f run/<scan>/generate.log
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
export LR_IMAGE_PROVIDER="${LR_IMAGE_PROVIDER:-openai}"   # OpenAI image-gen (policy: no Gemini)
export LR_CHAIR_JUDGE="${LR_CHAIR_JUDGE:-1}"

if [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "✗ OPENAI_API_KEY not set (needed for LR_IMAGE_PROVIDER=openai). Put it in .env." >&2
  exit 1
fi
echo "image provider=$LR_IMAGE_PROVIDER · model=${LR_OPENAI_IMAGE_MODEL:-gpt-image-2}"

FORCE_IMAGES=0
ARGS=()
for a in "$@"; do
  case "$a" in
    --force-images) FORCE_IMAGES=1 ;;
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
  echo "usage: scripts/pipeline/generate_objects.sh [--force-images] [<scan> ...]"
  exit 2
}
EXTRA=""; [ "$FORCE_IMAGES" = 1 ] && EXTRA="--force"

# keep the back-compat symlink run/<scan>/scene_init/obj_stage → run/<scan>/scene_init/obj_stage in place so
# integration / run.sh / tooling that reference the output path resolve to the real (final) tree.
link_obj_stage(){
  local S="$1"; local real="$LITEREALITY_FINAL/$S/scene_init/obj_stage"; local link="$LITEREALITY_OUTPUT/$S/obj_stage"
  mkdir -p "$real"; mkdir -p "$LITEREALITY_OUTPUT/$S"
  [ -L "$link" ] || { [ -e "$link" ] && return 0; ln -sfn "$real" "$link"; }
}

n=0; ok=0; fail=0
for S in "${SCENES[@]}"; do
  n=$((n+1))
  if [ ! -d "$LR_SCANS_DIR/$S" ]; then
    echo "[$n/${#SCENES[@]}] ✗  $S — no scan dir at $LR_SCANS_DIR/$S"; fail=$((fail+1)); continue
  fi
  link_obj_stage "$S"
  log="$LITEREALITY_OUTPUT/$S/generate.log"; mkdir -p "$(dirname "$log")"
  echo "[$n/${#SCENES[@]}] ▶  generate $S   (log: $log)"
  t0=$(date +%s)
  # no --skip-gemini  → generate images.   no --reconstruct/--classify/--procedural → stop before GLBs.
  if uv run litereality stage ingest "$S" $EXTRA >"$log" 2>&1; then
    dt=$(( $(date +%s) - t0 ))
    nimg=$(ls "$LITEREALITY_FINAL/$S/scene_init/obj_stage/object_init"/object_refs/"$S"/*/reference_1024.png 2>/dev/null | wc -l)
    echo "[$n/${#SCENES[@]}] ✓  $S  (${dt}s)"; ok=$((ok+1))
  else
    echo "[$n/${#SCENES[@]}] ✗  $S — failed; last lines:"; tail -n 15 "$log" | sed 's/^/      /'; fail=$((fail+1))
  fi
done

echo
echo "== generate_objects done: $ok ok · $fail failed (of $n) =="
[ "$fail" = 0 ]
