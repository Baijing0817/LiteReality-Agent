#!/usr/bin/env bash
# reexport.sh <scan> — re-run ONLY stage 6 (export) of run.sh against an already-authored room.
#
# run.sh has no skip flag for stage 3 (authoring is `hard` and unconditional), so re-running it to
# pick up a change downstream of authoring would re-author the room — another hour and ~$30. This
# replays just the export: rebuild the preview from Room.py (placing every object), bake the shell
# materials, regenerate the compare pairs, and write the viewer.
#
# Use after anything that changes the room's assets or Room.py without changing the authoring —
# e.g. src/litereality_agent/scripts/ops/adopt_stranded_glbs.py.
#
#   ./src/litereality_agent/scripts/ops/reexport.sh <scan>        COMPARE_FRAMES=0 to skip the compare pairs
set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../../../.."   # repo root (this lives in src/litereality_agent/scripts/ops/)

[ -f .env ] && { set -a; . ./.env; set +a; }
[ -f models.env ] && . ./models.env

SCAN="${1:?usage: ./src/litereality_agent/scripts/ops/reexport.sh <scan>}"
SUF="${RUN_TAG:+_$RUN_TAG}"
PY="${LR_PYTHON:-.venv/bin/python}"

export LITEREALITY_BLENDER="${LITEREALITY_BLENDER:-${BLENDER_PATH:-}}"
[ -n "$LITEREALITY_BLENDER" ] && export PATH="$LITEREALITY_BLENDER:$PATH"
export LITEREALITY_SCAN="$SCAN"
export LR_SCANS_DIR="${LR_SCANS_DIR:-$PWD/scans_uploaded}"
export LITEREALITY_OUTPUT="${LITEREALITY_OUTPUT:-$PWD/run}"
export LITEREALITY_FINAL="${LITEREALITY_FINAL:-$PWD/run}"

OUT="$LITEREALITY_OUTPUT/$SCAN"
WORKROOM="$OUT/scene_init/scene_stage/_oneshot${SUF}/room"
PREVIEW="$OUT/scene_init/scene_stage/_oneshot${SUF}/room_preview"
FINAL_OUT="$LITEREALITY_FINAL/$SCAN"
VIEWER_HTML="$FINAL_OUT/${SCAN}${SUF}.html"
SCAN_DIR="$LR_SCANS_DIR/$SCAN"

[ -f "$WORKROOM/Room.py" ] || { echo "✗ no authored room at $WORKROOM"; exit 3; }
echo "== re-export $SCAN =="
echo "   room    $WORKROOM"
echo "   viewer  $VIEWER_HTML"

# 1. rebuild the preview from Room.py — this is what runs each object.py and places the assets
$PY -m litereality_agent.integration.compile.build_from_room --room "$WORKROOM" --out "$PREVIEW" --regenerate \
    || echo "   (preview rebuild failed — falling back to the existing Room.glb)"

# 2. bake the shell node-graph materials into UV textures (glTF can't express BOX projection)
$PY -c "from litereality_agent.integration import bake_room; bake_room('$PREVIEW/Room.blend', '$PREVIEW/Room.glb')" \
    || echo "   (bake failed — viewer may show flat shell textures)"

glb="$PREVIEW/Room.glb"
[ -f "$glb" ] || { echo "   no Room.glb to export"; exit 1; }

# 3. real-vs-render compare pairs (stale once the object set changes, so regenerate)
cmp_dir="$FINAL_OUT/compare"
if [ "${COMPARE_FRAMES:-6}" != 0 ]; then
  $PY -m litereality_agent.realism_authoring.views.room_render.render_vs_capture --scan "$SCAN_DIR" --room "$WORKROOM" \
      --out "$cmp_dir" --frames "${COMPARE_FRAMES:-6}" --res-div "${COMPARE_RESDIV:-3}" \
      >/dev/null 2>&1 || echo "   (compare pairs failed — viewer ships without that panel)"
fi

# 4. viewer + machine-readable QC
$PY -m litereality_agent.realism_authoring.export_viewer "$glb" "$VIEWER_HTML" "$SCAN" \
    --room="$WORKROOM" --scan="$SCAN" --compare="$cmp_dir"
$PY -m litereality_agent.realism_authoring.qc_room --room "$WORKROOM" > "$FINAL_OUT/qc.txt" 2>&1 || true
sed -n "1,40p" "$FINAL_OUT/qc.txt" | sed "s/^/   /"

mkdir -p "$FINAL_OUT"
[ -f "$WORKROOM/Room.py" ] && cp -f "$WORKROOM/Room.py" "$FINAL_OUT/"
[ -f "$glb" ]             && cp -f "$glb" "$FINAL_OUT/Room.glb"
echo "   deliverables → $FINAL_OUT"
