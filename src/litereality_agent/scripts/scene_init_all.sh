#!/usr/bin/env bash
# scene_init_all.sh — STAGE-2 SEED ONLY (scene_init), for every scan.
#
# Assembles each scene's reconstructed objects into the seed room definition:
#   Room.py + manifest.json + SHELL   (export_initial_scene)
#   Room.glb preview                  (build_preview, needs Blender)
# saved under run/<scan>/scene_stage/room_init/room/ (via a scene_stage symlink, same
# pattern as obj_stage). This makes each scene READY for the second-stage optimization
# (authoring/refine) — but does NOT run that optimization.
#
# Run this ONLY after object reconstruction is complete (it references the reconstructed GLBs).
#
# The worklist defaults to every scan directory under $LR_SCANS_DIR; pass scan names to narrow it.
#
#   src/litereality_agent/scripts/scene_init_all.sh                 # every scan
#   src/litereality_agent/scripts/scene_init_all.sh <scan> [...]    # just these
#
# Watch:  tail -f run/<scan>/scene_init.log
set -uo pipefail
cd "$(dirname "$(realpath "$0")")/../../.."   # repo root (this lives in src/litereality_agent/scripts/)
[ -f .env ] && { set -a; . ./.env; set +a; }
[ -f models.env ] && . ./models.env

PY="${LR_PYTHON:-.venv/bin/python}"
export LITEREALITY_BLENDER="${LITEREALITY_BLENDER:-${BLENDER:-}}"
[ -n "$LITEREALITY_BLENDER" ] && export PATH="$LITEREALITY_BLENDER:$PATH"
export LR_SCANS_DIR="${LR_SCANS_DIR:-$PWD/scans_uploaded}"
export LITEREALITY_OUTPUT="${LITEREALITY_OUTPUT:-$PWD/run}"
export LITEREALITY_FINAL="${LITEREALITY_FINAL:-$PWD/run}"

# Worklist: explicit args, else every scan directory found under $LR_SCANS_DIR.
if [ $# -gt 0 ]; then
  SCENES=("$@")
else
  SCENES=()
  for d in "$LR_SCANS_DIR"/*/; do [ -d "$d" ] && SCENES+=("$(basename "$d")"); done
fi
[ ${#SCENES[@]} -gt 0 ] || {
  echo "no scans found in $LR_SCANS_DIR"
  echo "usage: src/litereality_agent/scripts/scene_init_all.sh [<scan> ...]"
  exit 2
}

# make $LITEREALITY_OUTPUT/<S>/<stage> resolve to the real tree under $LITEREALITY_FINAL/<S>/<stage>.
# With the default roots the two coincide (run/), so link_stage short-circuits on the -L/-d checks.
link_stage(){
  local S="$1" stage="$2"
  local real="$LITEREALITY_FINAL/$S/$stage" link="$LITEREALITY_OUTPUT/$S/$stage"
  # Roots coincide (the default: both are run/) -> the "link" IS the real dir, nothing to link.
  # Without this the migrate branch below sees a real dir at $link, finds $real already exists
  # (same path), and `rm -rf`s the stage data before symlinking it to itself.
  [ "$real" = "$link" ] && return 0
  mkdir -p "$LITEREALITY_FINAL/$S" "$LITEREALITY_OUTPUT/$S"
  if [ -L "$link" ]; then return; fi
  if [ -d "$link" ]; then                       # real dir already there -> migrate into the deliverables root
    if [ -e "$real" ]; then rm -rf "$link"; else mkdir -p "$(dirname "$real")"; mv "$link" "$real"; fi
    ln -sfn "$real" "$link"
  else
    mkdir -p "$real"; ln -sfn "$real" "$link"
  fi
}

n=0; ok=0; fail=0
for S in "${SCENES[@]}"; do
  n=$((n+1))
  link_stage "$S" obj_stage      # read reconstructed GLBs from the final root
  link_stage "$S" scene_stage    # write room_init into the final root
  log="$LITEREALITY_OUTPUT/$S/scene_init.log"; mkdir -p "$(dirname "$log")"
  echo "[$n/${#SCENES[@]}] ▶  scene_init $S"
  if $PY - "$S" >"$log" 2>&1 <<'PY'
import sys
from pathlib import Path
from init.scene_init.run_scene_init import export_initial_scene, build_preview
scan = sys.argv[1]
room_dir = export_initial_scene(scan)
if not room_dir:
    print("export_initial_scene returned None"); sys.exit(1)
print("Room.py ->", Path(room_dir) / "Room.py")
try:
    glb = build_preview(Path(room_dir))
    print("Room.glb ->", glb)
except Exception as e:
    print(f"build_preview failed (non-fatal, Room.py still valid): {type(e).__name__}: {e}")
PY
  then
    rp="$LITEREALITY_FINAL/$S/scene_init/scene_stage/room_init/room/Room.py"
    glb="$LITEREALITY_FINAL/$S/scene_init/scene_stage/room_init/room_preview/Room.glb"
    echo "[$n/${#SCENES[@]}] ✓  $S  (Room.py $([ -f "$rp" ] && echo ✓ || echo ✗)  Room.glb $([ -f "$glb" ] && echo ✓ || echo ✗))"
    ok=$((ok+1))
  else
    echo "[$n/${#SCENES[@]}] ✗  $S — scene_init failed; last lines:"; tail -n 12 "$log" | sed 's/^/      /'; fail=$((fail+1))
  fi
done
echo
echo "== scene_init_all done: $ok ok · $fail failed (of $n) =="
echo "   scenes are now SEEDED (Room.py + Room.glb) and READY for stage-2 optimization — NOT optimized."
[ "$fail" = 0 ]
