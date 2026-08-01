#!/usr/bin/env bash
# LiteReality-Agent — ONE command: an input scan in, a finished room out. The agentic layer is
# a single one-shot authoring pass (no fixed multi-stage loop).
#
#   ./run.sh <scan>            from a raw capture under $LR_SCANS_DIR: init, then author it
#   ./run.sh <path/to/scan>    the same, given the capture folder directly
#   ./run.sh --scene <dir>     from an init'd SCENE PACKAGE: skip init, author it
#   ./run.sh                   same, discovering the package from $LR_SCENE / the current dir
#
# A scene package is the folder `uv run -m litereality_agent scene_init` seals with a `scene.json` manifest — it records the
# scan name, every stage path and the capture location, so the stages below need no arguments
# beyond the folder itself. `--scene` implies SKIP_INIT=1 (the package IS the init output);
# set SKIP_INIT=0 explicitly to re-run init over it.
#
# Stages:
#   1 init      extract → detect → ENHANCED chair grouping (DINOv2 + Claude Opus judge) →
#               references (OpenAI image, Claude classify) → reconstruct (TRELLIS + gated
#               procedural) → seed Room.py + Room.glb
#   2 stitches  head-on per-surface reference images (input for authoring)
#   3 author    one-shot authoring edits Room.py — shell materials + fixtures, one pass
#   4 materials  PBR materials for every fixture-palette key (geometry untouched) — OFF by
#               default (the authoring pass already textures the shell, so this extra pass on the
#               fixture palette isn't worth its cost for most runs); MATERIALS=1 to enable.
#               ~13 min on a 14-key room
#   5 refine    per-object refinement (tighten each procedural object vs its reference) — ON by
#               default; RUN_REFINE=0 or SKIP_REFINE=1 to skip (REFINE_OBJECTS still selects WHICH
#               objects). LR_REFINE_ROUNDS (default 2) caps the render->look->fix rounds per object,
#               and LR_REFINE_MAX_TURNS (default 25) caps the agent turns per object. 25 is LOW —
#               objects routinely need ~30 turns just to study the reference before editing, so most
#               of them end on "Reached maximum number of turns" and land no change. Raise it if you
#               want this stage to actually converge.
#   6 export     rebuild Room.glb + a self-contained viewer with OBJECTS (hide/isolate),
#               QC (deterministic geometry violations), REAL-VS-RENDER pairs and the TRACE
#               timeline. COMPARE_FRAMES=0 skips the pair renders.
#
# Provider policy (baked): OpenAI for image-gen only; Claude for everything else; no Gemini.
set -uo pipefail
# Resolve caller-relative paths BEFORE the cd below moves us to the repo root — otherwise
# `./run.sh ../captures/foo` or `--scene ./out/foo` silently resolves against the wrong directory.
CALLER_PWD="$PWD"
# `cd` + `pwd -P` rather than string concatenation: that is what makes `..` and symlinks come out
# right (on macOS /tmp IS a symlink, so "$PWD/../x" lands somewhere that does not exist). Prints
# nothing when the argument is not a directory, which the callers turn into a clean error.
absdir(){ ( cd "$CALLER_PWD" 2>/dev/null && cd "$1" 2>/dev/null && pwd -P ) || true; }
abspath(){ absdir "$1" || true; }
cd "$(dirname "$(realpath "$0")")"
[ -f .env ] && { set -a; . ./.env; set +a; }
# models.env — the ONE place to pick every model. Sourced after .env so .env/shell
# values win; exports here reach every stage (each stage is a subprocess).
[ -f models.env ] && . ./models.env

PROFILE="${PROFILE:-detail}"
AUTHOR_TURNS="${AUTHOR_TURNS:-200}"
# How many tool-calls ("steps") the authoring stage may take before it winds down (self-check tools
# off, final edits only) and stops. This is the primary way to bound how far authoring goes;
# AUTHOR_TURNS stays as the hard SDK backstop above it. 0 disables the budget.
AUTHOR_STEPS="${AUTHOR_STEPS:-100}"
# The interpreter every stage runs in. Overridable so the pipeline can be driven from a different
# environment than the repo's own .venv (and so the resolution below is testable).
PY="${LR_PYTHON:-.venv/bin/python}"

# ---- resolve the scan, from a name or from a scene package -------------------
SCENE=""
case "${1:-}" in
  --scene) SCENE=$(absdir "${2:?usage: ./run.sh --scene <dir>}"); shift 2 ;;
  --scene=*) SCENE=$(absdir "${1#--scene=}"); shift ;;
  "") SCENE="${LR_SCENE:-}" ;;   # no argument at all: discover one (empty hint = auto)
esac
SCAN="${1:-}"

# `litereality_agent.integration.manifest env` prints the exports that rebuild the whole $LITEREALITY_* environment from
# the folder — scan name, output/final roots, scans root, plus LR_* for each stage path. Failure
# is not fatal: without a package we fall back to deriving everything from <scan>, exactly as
# before packages existed.
if [ -z "$SCAN" ] || [ -n "$SCENE" ]; then
  if SCENE_ENV=$($PY -m litereality_agent.integration.manifest env "$SCENE" 2>/dev/null) && [ -n "$SCENE_ENV" ]; then
    eval "$SCENE_ENV"
    SCAN="$LITEREALITY_SCAN"
    SCENE="$LR_SCENE"
    : "${SKIP_INIT:=1}"          # the package IS the init output; SKIP_INIT=0 to redo it
    printf "${C_DIM:-}scene package: %s${C_0:-}\n" "$SCENE"
  fi
fi
[ -n "$SCAN" ] || { echo "usage: ./run.sh <scan|scan-dir> | ./run.sh --scene <dir> | ./run.sh (inside a scene package)"; exit 2; }

# A scan is given as a NAME (resolved under $LR_SCANS_DIR) or as the capture FOLDER itself.
# A folder is translated once, here: $LR_SCANS_DIR points at its parent and the basename becomes
# the name — so every stage below still resolves the capture the single way it knows how.
case "$SCAN" in
  */*)
    SCAN_ABS=$(absdir "$SCAN")
    [ -n "$SCAN_ABS" ] || { echo "no such scan folder: $SCAN (from $CALLER_PWD)"; exit 2; }
    export LR_SCANS_DIR=$(dirname "$SCAN_ABS")
    SCAN=$(basename "$SCAN_ABS")
    printf "scan folder: %s/%s\n" "$LR_SCANS_DIR" "$SCAN"
    ;;
esac

# Accept the friendlier names the README/.env.example document as aliases for the canonical
# vars the code reads. The canonical name always wins if both are set.
export LITEREALITY_BLENDER="${LITEREALITY_BLENDER:-${BLENDER_PATH:-${BLENDER:-}}}"
export LR_DINO_PYTHON="${LR_DINO_PYTHON:-${GROUNDING_DINO_PYTHON:-}}"
export LITEREALITY_TRELLIS_PYTHON="${LITEREALITY_TRELLIS_PYTHON:-${TRELLIS_PYTHON:-}}"
[ -n "$LITEREALITY_BLENDER" ] && export PATH="$LITEREALITY_BLENDER:$PATH"
export LITEREALITY_SCAN="$SCAN"
export LR_SCANS_DIR="${LR_SCANS_DIR:-$PWD/scans_uploaded}"
export LITEREALITY_OUTPUT="${LITEREALITY_OUTPUT:-$PWD/run}"
export LR_IMAGE_PROVIDER="${LR_IMAGE_PROVIDER:-openai}"
export LR_CLASSIFY_PROVIDER="${LR_CLASSIFY_PROVIDER:-claude}"
export HARNESS_VLM="${HARNESS_VLM:-claude}"

# Keep ALL agent / HuggingFace / temp caches on /scratch2 — $HOME is 25G-capped and hitting EDQUOT
# mid-run breaks the shell. Repo lives on /scratch2, so a repo-local .cache is safe.
export LR_CACHE="${LR_CACHE:-$PWD/.cache}"
export HF_HOME="${HF_HOME:-$LR_CACHE/huggingface}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-$HF_HOME}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$LR_CACHE/xdg}"
export TMPDIR="${TMPDIR:-$LR_CACHE/tmp}"
mkdir -p "$HF_HOME" "$XDG_CACHE_HOME" "$TMPDIR"

OUT="$LITEREALITY_OUTPUT/$SCAN"
# The scene package exports LR_* for every stage path (integration.manifest). Prefer those —
# they are what stage 1 actually wrote, so the halves cannot drift when the layout changes. The
# literal paths are the fallback for a run with no package.
ROOM_INIT="${LR_ROOM_INIT:-$OUT/scene_init/scene_stage/room_init/room}"
# The object stage's working tree — where refine/materials/qc_pass read each object's reference
# images and selected capture frames from. Same package-first, literal-fallback rule as ROOM_INIT.
# The literal MUST carry the scene_init/ level: without it every object fails with "no selected
# capture frames", which the refine stage reports as a per-object error and the run summary still
# ticks green.
REFROOT="${LR_REFROOT:-$OUT/scene_init/obj_stage/object_init}"
# RUN_TAG isolates a run into its own _oneshot_<tag> dir + <scan>_<tag>.html, so you can re-run
# (e.g. after code changes) WITHOUT overwriting a previous result — keep both to compare.
SUF="${RUN_TAG:+_$RUN_TAG}"
# Stage 2 owns realism_authoring/, alongside stage 1's scene_init/: the room it edits, its
# renders, its stitches, its logs and its deliverables. Either half can be deleted and re-run
# without disturbing the other.
AUTHORING="${LR_AUTHORING:-$OUT/realism_authoring}${SUF}"
WORKROOM="$AUTHORING/room"
PREVIEW="$AUTHORING/room_preview"
SURFREF="$AUTHORING/surface_ref"
mkdir -p "$AUTHORING"
SCAN_DIR="$LR_SCANS_DIR/$SCAN"
# EVERYTHING for a scene — stage data, deliverables, tracing — collects under ONE folder,
# run/<scan>/. Holds the viewer .html, the authored+refined Room.py, the obj/scene stages, and the
# refine tracing (before/after sheets, target crops, round montages). Override with LITEREALITY_FINAL.
# The output root defaults to the SAME tree, so run/<scan>/ is one real directory (see below).
FINAL_ROOT="${LITEREALITY_FINAL:-$PWD/run}"
FINAL_OUT="$AUTHORING"
mkdir -p "$FINAL_OUT"
# Physical stage-1 data lives under $STAGE_ROOT — the PER-SCAN deliverables dir the object stage
# writes into via litereality_agent.scene_init.object_init.config.final_root, i.e.
# $LITEREALITY_FINAL/<scan>/scene_init/{obj_stage,scene_stage}. $OUT/<scan>/ carries back-compat
# SYMLINKS so every stage that resolves run/<scan>/scene_init/{obj_stage,scene_stage} finds the same
# files. Without the link a FRESH scene's init reconstructs fine but the seed export can't find the
# objects.
# This MUST be the per-scan final dir, not $FINAL_OUT: stage 2's deliverables live one level deeper
# ($AUTHORING), so linking there buried stage 1's output INSIDE stage 2's folder — and then
# `rm -rf run/<scan>/realism_authoring`, which this file and the README both call safe ("Either half
# can be deleted and re-run without disturbing the other"), silently deleted the expensive seed:
# the TRELLIS reconstructions and the paid reference images. scene.json models the two as siblings.
# By DEFAULT the two roots coincide ($PWD/run) and $OUT == $STAGE_ROOT — the mkdir below then
# already created the dirs, the `[ -e ]` guards short-circuit, and no symlink is made:
# run/<scan>/ is one real directory. The links only appear when a custom root splits them.
# $OUT/scene_init must exist before a stage dir can be linked INTO it.
STAGE_ROOT="$FINAL_ROOT/$SCAN"
mkdir -p "$OUT/scene_init" "$STAGE_ROOT/scene_init/obj_stage" "$STAGE_ROOT/scene_init/scene_stage"
[ -e "$OUT/scene_init/obj_stage" ]   || ln -sfn "$STAGE_ROOT/scene_init/obj_stage"   "$OUT/scene_init/obj_stage"
[ -e "$OUT/scene_init/scene_stage" ] || ln -sfn "$STAGE_ROOT/scene_init/scene_stage" "$OUT/scene_init/scene_stage"
# Write the viewer straight into the run tree (no redundant copy).
VIEWER_HTML="$FINAL_OUT/${SCAN}${SUF}.html"

# ---- stage tracker ----------------------------------------------------------
# Same visual language as stage 1 (litereality_agent.console): one row per stage, a stable colour per
# stage, and the stage's own narration on a single line that refreshes in place while it runs.
# The narration goes to a log either way; $LR_VERBOSE=1 streams it to the terminal instead.
C_DIM='\033[2m'; C_CY='\033[1;36m'; C_GR='\033[1;32m'; C_RD='\033[1;31m'
C_YE='\033[1;33m'; C_MA='\033[1;35m'; C_BL='\033[1;34m'; C_B='\033[1m'; C_0='\033[0m'
[ -t 1 ] || { C_DIM=''; C_CY=''; C_GR=''; C_RD=''; C_YE=''; C_MA=''; C_BL=''; C_B=''; C_0=''; }
TOTAL=7; STAGE_NAMES=(); STAGE_SECS=(); STAGE_OK=(); RUN_T0=$(date +%s)
STAGE_LOGS="$AUTHORING/logs"; mkdir -p "$STAGE_LOGS"

fmt_t(){ local s=$1; if [ "$s" -ge 60 ]; then printf "%dm%02ds" $((s/60)) $((s%60)); else printf "%ds" "$s"; fi; }

# The newest line from a log that is worth showing: not blank, not a tqdm bar, not a warning.
live_line(){ tail -n 40 "$1" 2>/dev/null \
  | tr -d '\r' \
  | grep -avE '^[[:space:]]*$|^[[:space:]]*[0-9]+%\||^(Warning|warning|UserWarning|FutureWarning)|huggingface|HF_TOKEN|^\$ ' \
  | tail -n 1 | cut -c1-70; }

# Redraw one status line in place while a stage runs. Killed by stage() when the stage ends.
watch_log(){  # label colour logfile
  local label="$1" col="$2" log="$3" last=""
  while :; do
    local line; line=$(live_line "$log")
    if [ -n "$line" ] && [ "$line" != "$last" ]; then
      printf "\r\033[K   ${C_DIM}▶${C_0} ${col}%-14s${C_0} ${C_DIM}%s${C_0}" "$label" "$line"
      last="$line"
    fi
    sleep 0.5
  done
}

stage(){  # num label colour mode(hard|soft) -- command...
  local num="$1" label="$2" col="$3" mode="$4"; shift 4
  local log="$STAGE_LOGS/${label// /_}.log" t0 ok=1 dt watcher=""
  : > "$log"
  local t0; t0=$(date +%s)
  if [ "${LR_VERBOSE:-0}" = 1 ]; then
    printf "   ${C_DIM}▶ %s…${C_0}\n" "$label"
    "$@" 2>&1 | tee -a "$log"; ok=${PIPESTATUS[0]:-0}; [ "$ok" = 0 ] && ok=1 || ok=0
  else
    printf "   ${C_DIM}▶ %s…${C_0}" "$label"
    [ -t 1 ] && { watch_log "$label" "$col" "$log" & watcher=$!; }
    "$@" >>"$log" 2>&1 || ok=0
    [ -n "$watcher" ] && { kill "$watcher" 2>/dev/null; wait "$watcher" 2>/dev/null; }
  fi
  dt=$(( $(date +%s) - t0 ))
  STAGE_NAMES+=("$label"); STAGE_SECS+=("$dt"); STAGE_OK+=("$ok")
  printf "\r\033[K"
  if [ "$ok" = 1 ]; then
    printf "   ${C_GR}✓${C_0} ${col}%-14s${C_0} %-34s${C_DIM}%6s${C_0}\n" "$label" "$(live_line "$log")" "$(fmt_t "$dt")"
  else
    printf "   ${C_RD}✗${C_0} ${col}%-14s${C_0} %-34s${C_DIM}%6s${C_0}\n" "$label" "failed — see log" "$(fmt_t "$dt")"
    while IFS= read -r _l; do printf "     ${C_DIM}%s${C_0}\n" "$_l"; done < <(tail -n 12 "$log")
    printf "     ${C_DIM}… full log: %s${C_0}\n" "${log#"$PWD/"}"
    if [ "$mode" = hard ]; then
      printf "   ${C_RD}this stage is required — aborting.${C_0}\n"; summary; exit 1
    fi
  fi
}

summary(){
  local tot=$(( $(date +%s) - RUN_T0 )) i
  printf "\n${C_CY}── %s ─────────────────────────────────────────────${C_0}\n" "$SCAN"
  for i in "${!STAGE_NAMES[@]}"; do
    local mark; [ "${STAGE_OK[$i]}" = 1 ] && mark="${C_GR}✓${C_0}" || mark="${C_RD}✗${C_0}"
    printf "   %b %-14s %34s${C_DIM}%6s${C_0}\n" "$mark" "${STAGE_NAMES[$i]}" "" "$(fmt_t "${STAGE_SECS[$i]}")"
  done
  printf "   ${C_B}%-14s %34s%6s${C_0}\n" "total" "" "$(fmt_t "$tot")"
  [ -f "$VIEWER_HTML" ]        && printf "   ${C_CY}viewer${C_0}       %s\n" "${VIEWER_HTML#"$PWD/"}"
  [ -f "$WORKROOM/Room.py" ]   && printf "   ${C_CY}room${C_0}         %s\n" "${WORKROOM#"$PWD/"}/Room.py"
  local ba="$FINAL_OUT/obj_refine/refine_beforeafter.png"
  [ -f "$ba" ]                 && printf "   ${C_CY}before/after${C_0} %s\n" "${ba#"$PWD/"}"
  printf "   ${C_DIM}stage logs   %s${C_0}\n" "${STAGE_LOGS#"$PWD/"}"
}

# ---- stage bodies ----------------------------------------------------------
do_init(){   $PY -m litereality_agent scene_init "$SCAN"; }
do_stitch(){ $PY -m litereality_agent.realism_authoring.scene.surface_reference; }
do_author(){ mkdir -p "$(dirname "$WORKROOM")" && rm -rf "$WORKROOM" && cp -r "$ROOM_INIT" "$WORKROOM" \
             && $PY -m litereality_agent.realism_authoring.author --room "$WORKROOM" --surface-ref "$SURFREF" \
                    --scan "$SCAN_DIR" --profile "$PROFILE" --max-turns "$AUTHOR_TURNS" \
                    --step-budget "$AUTHOR_STEPS"; }
# DETERMINISTIC QC over the just-authored Room.py — no model, no images. Rebuild the room (layout +
# Room.glb) from the current Room.py, run the geometry linter (qc_room) to REPORT all violations, then
# resolve furniture interpenetrations from the TRUE MESHES (qc_collision -> scene_collision/FCL, the
# accurate check — a chair tucked under a desk reads clear where boxes false-clash) by nudging
# PLACEMENTS only: it edits `center` arrays in Room.py and NEVER touches object.py (objects are final).
# This deterministic gate is enough on its own; a model/image pass is only worth it for clashes the
# fixer can't clear (e.g. both pieces anchored), so it is opt-in (QC_MODEL_PASS=1), not the default.
do_qc(){
  $PY -m litereality_agent.integration.compile.build_from_room --room "$WORKROOM" --out "$PREVIEW" \
      >/dev/null 2>&1 || echo "   (layout/glb rebuild failed; using existing)"
  $PY -m litereality_agent.realism_authoring.qc_room       --room "$WORKROOM" || true          # report all geometry violations
  $PY -m litereality_agent.realism_authoring.qc_collision  --room "$WORKROOM" --apply || true  # TRUE-MESH clash resolve -> Room.py
  if [ "${QC_MODEL_PASS:-0}" = 1 ]; then
    $PY -m litereality_agent.realism_authoring.qc_pass --room "$WORKROOM" --surface-ref "$SURFREF" --scan "$SCAN_DIR" \
        --refroot "$REFROOT" --model "${QC_MODEL:-${HARNESS_MODEL:-claude-opus-5}}" \
        --max-turns "${QC_TURNS:-160}"
  fi
}
# SELECTIVE per-object refinement — not every object is worth optimising. Choose which with
# REFINE_OBJECTS="Sink_Storage0,Sofa0,..." (unset = every procedural object in the room).
# Concurrency/budget are capped (GPU + cost): REFINE_CONCURRENCY (2), REFINE_BUDGET ($/obj, 8).
do_refine(){
  local objs="${REFINE_OBJECTS:-}"
  if [ -z "$objs" ]; then
    objs=$(ls -1 "$WORKROOM/Objects/Procedural" 2>/dev/null | paste -sd, -)
  fi
  [ -n "$objs" ] || { echo "   no procedural objects to refine — skipping"; return 0; }
  echo "   refining objects: $objs  (concurrency=${REFINE_CONCURRENCY:-2}, budget=\$${REFINE_BUDGET:-8}/obj)"
  $PY -m litereality_agent.realism_authoring.refine_objects --room "$WORKROOM" \
        --refroot "$REFROOT" --scan "$SCAN_DIR" \
        --results "$FINAL_OUT/obj_refine" --objects "$objs" \
        --concurrency "${REFINE_CONCURRENCY:-2}" --budget "${REFINE_BUDGET:-8}"; }
# PBR materials pass — geometry is finished; this only changes what things are MADE OF. The
# authoring pass reliably textures the shell but leaves furniture/fixtures on flat _solid_mat
# colours; a simple box with a real captured PBR set reads far closer to the photo. MATERIALS=0 to
# skip; MATERIALS_TARGETS caps how many surfaces it aims for.
do_materials(){ $PY -m litereality_agent.realism_authoring.materials_pass --room "$WORKROOM" --surface-ref "$SURFREF" \
                    --scan "$SCAN_DIR" --refroot "$REFROOT" \
                    --targets "${MATERIALS_TARGETS:-8}" --max-turns "${MATERIALS_TURNS:-80}"; }
do_export(){
  # rebuild Room.glb from the (authored + refined) Room.py so the viewer reflects every edit —
  # otherwise the export would ship the pre-refine preview. --regenerate reruns each object.py.
  $PY -m litereality_agent.integration.compile.build_from_room --room "$WORKROOM" --out "$PREVIEW" --regenerate \
      || echo "   (preview rebuild failed — falling back to the existing Room.glb)"
  # bake shell node-graph materials (BOX-projected, glTF can't express them) into UV textures so
  # the viewer glb matches the Blender look instead of showing flat walls/floor.
  $PY -c "from litereality_agent.integration import bake_room; bake_room('$PREVIEW/Room.blend', '$PREVIEW/Room.glb')" \
      || echo "   (bake failed — viewer may show flat shell textures)"
  local glb="$PREVIEW/Room.glb"
  [ -f "$glb" ] || glb=$(/usr/bin/find "$OUT/scene_stage/_oneshot" -name 'Room.glb' 2>/dev/null | head -1)
  [ -n "$glb" ] && [ -f "$glb" ] || { echo "   no Room.glb to export"; return 1; }
  # Real-vs-render pairs at the capture's own ARKit poses, for the viewer's compare panel.
  # ~15s/frame at res-div 3; COMPARE_FRAMES=0 skips the stage entirely.
  local cmp_dir="$FINAL_OUT/compare"
  if [ "${COMPARE_FRAMES:-6}" != 0 ]; then
    $PY -m litereality_agent.realism_authoring.views.room_render.render_vs_capture --scan "$SCAN_DIR" --room "$WORKROOM" \
        --out "$cmp_dir" --frames "${COMPARE_FRAMES:-6}" --res-div "${COMPARE_RESDIV:-3}" \
        >/dev/null 2>&1 || echo "   (compare pairs failed — viewer ships without that panel)"
  fi
  # QC + trace + compare panels are built in by default: --room gives the deterministic geometry
  # check (authoring/qc_room.py, no model), --scan pulls that run's traces/trace.jsonl timeline,
  # --compare embeds the pairs above.
  $PY -m litereality_agent.realism_authoring.export_viewer "$glb" "$VIEWER_HTML" "$SCAN" \
      --room="$WORKROOM" --scan="$SCAN" --compare="$cmp_dir"
  # machine-readable QC alongside the page, so batch runs can grep it
  $PY -m litereality_agent.realism_authoring.qc_room --room "$WORKROOM" > "$FINAL_OUT/qc.txt" 2>&1 || true
  sed -n "1,40p" "$FINAL_OUT/qc.txt" | sed "s/^/   /"
  # Authoring replay: a self-contained page of the run — reasoning + every code edit as a real
  # diff + every image the agent saw — built straight from the enriched run-trace (run_trace.py
  # now stores edit old/new + copies each render into traces/img/). Default on; REPLAY=0 to skip.
  if [ "${REPLAY:-1}" = 1 ]; then
    LITEREALITY_FINAL="$FINAL_ROOT" $PY -m litereality_agent.realism_authoring.authoring_replay "$SCAN" \
        "$FINAL_OUT/${SCAN}${SUF}_authoring_replay.html" 2>&1 | sed "s/^/   /" \
        || echo "   (authoring replay skipped)"
  fi
  # collect the finished deliverable into final_results/<scan>/ alongside its refine tracing, so the
  # whole scene (viewer + source Room.py + built Room.glb) lives in one reviewable place.
  mkdir -p "$FINAL_OUT"
  # viewer already written straight to $FINAL_OUT (VIEWER_HTML) — no copy needed
  [ -f "$WORKROOM/Room.py" ] && cp -f "$WORKROOM/Room.py" "$FINAL_OUT/"
  [ -f "$glb" ]            && cp -f "$glb" "$FINAL_OUT/Room.glb"
  echo "   final_results → $FINAL_OUT"
}

# ---- run -------------------------------------------------------------------
# Name the halves this run will actually do. Announcing "realism_authoring" and then printing
# "▶ init…" one line later contradicts the two-stage split the README makes load-bearing.
RUN_LABEL="scene_init + realism_authoring"
[ "${SKIP_INIT:-0}" = 1 ] && RUN_LABEL="realism_authoring"
printf "\n${C_CY}── %s · %s %s${C_0}\n" "$RUN_LABEL" "$SCAN" \
       "$(printf '─%.0s' $(seq 1 $((50 - ${#SCAN}))))"
printf "   ${C_DIM}editor %s · vlm %s · image %s${C_0}\n" \
       "${HARNESS_MODEL:-?}" "${HARNESS_VLM:-?}" "${LR_OPENAI_IMAGE_MODEL:-?}"
# Check what THIS run will actually use. A --scene run starts at stage 2, which never touches
# torch, GroundingDINO or a TRELLIS endpoint — gating it on those aborts a pipeline that would
# have run fine. A full run checks everything, because it does everything.
if [ "${SKIP_SANITY:-0}" != 1 ]; then
  SANITY_STAGE="all"; [ "${SKIP_INIT:-0}" = 1 ] && SANITY_STAGE="realism_authoring"
  $PY sanity.py "$SCAN" --stage "$SANITY_STAGE" \
    || { echo "   ${C_RD}sanity failed — fix above, or SKIP_SANITY=1 to override.${C_0}"; exit 3; }
fi

if [ "${SKIP_INIT:-0}" = 1 ]; then
  printf "\n${C_DIM}⊘  [1/%d] init — skipped (reusing existing object stage)${C_0}\n" "$TOTAL"
  STAGE_NAMES+=("init (skipped)"); STAGE_SECS+=(0); STAGE_OK+=(1)
  [ -f "$ROOM_INIT/Room.py" ] || { echo "✗ SKIP_INIT but no seed at $ROOM_INIT — run init first."; exit 3; }
else
  stage 1 "init"           "$C_CY" hard do_init
fi
if [ "${SKIP_STITCH:-0}" = 1 ] && [ -f "$SURFREF/surface_ref_manifest.json" ]; then
  printf "\n${C_DIM}⊘  [2/%d] surface stitches — skipped (SKIP_STITCH=1, reusing existing)${C_0}\n" "$TOTAL"
  STAGE_NAMES+=("stitches (skipped)"); STAGE_SECS+=(0); STAGE_OK+=(1)
else
  stage 2 "stitches"       "$C_CY" soft do_stitch
fi
stage 3 "authoring"      "$C_MA" hard do_author
# Stage 4 — FIXTURING + PBR MATERIALS. OFF by default: the authoring pass already textures the
# shell, and this extra PBR pass on the fixture palette isn't worth its cost/time for most runs.
# MATERIALS=1 to re-enable.
if [ "${MATERIALS:-0}" = 1 ]; then
  stage 4 "materials"      "$C_MA" soft do_materials
else
  printf "\n${C_DIM}⊘  [4/%d] fixturing + PBR materials — skipped (MATERIALS=0)${C_0}\n" "$TOTAL"
  STAGE_NAMES+=("materials (skipped)"); STAGE_SECS+=(0); STAGE_OK+=(1)
fi
# Stage 5 — PER-OBJECT REFINEMENT. ON by default now (RUN_REFINE=0 or SKIP_REFINE=1 to skip):
# tightens each procedural object against its reference in a render->look->fix loop.
# LR_REFINE_ROUNDS (default 2) caps the rounds per object; REFINE_OBJECTS selects which objects.
if [ "${RUN_REFINE:-1}" = 1 ] && [ "${SKIP_REFINE:-0}" != 1 ]; then
  stage 5 "obj refine"     "$C_MA" soft do_refine
else
  printf "\n${C_DIM}⊘  [5/%d] per-object refinement — skipped (RUN_REFINE=0)${C_0}\n" "$TOTAL"
  STAGE_NAMES+=("obj refine (skipped)"); STAGE_SECS+=(0); STAGE_OK+=(1)
fi
# Stage 6 — QC PASS (final verify). ON by default now (RUN_QC=0 to skip): model-driven checklist —
# openings open + articulate, glass transparent, windows/curtains articulate, per-wall opening layout
# matches its stitch, no fixture over an opening, ceiling materialed, AND geometry fidelity (fixtures
# not over-simplified, nothing hallucinated the photos don't show, object positions/scale correct).
# This is the seam where an enforced verify->fix loop would slot in.
if [ "${RUN_QC:-1}" = 1 ]; then
  stage 6 "qc"             "$C_YE" soft do_qc
else
  printf "\n${C_DIM}⊘  [6/%d] QC pass — skipped (RUN_QC=0)${C_0}\n" "$TOTAL"
  STAGE_NAMES+=("qc (skipped)"); STAGE_SECS+=(0); STAGE_OK+=(1)
fi
stage 7 "export"         "$C_GR" soft do_export

summary
