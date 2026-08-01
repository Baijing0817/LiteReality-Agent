# Run notes — following README end-to-end on the two example scans

Date: 2026-08-01 · macOS (Apple Silicon) · Blender 5.1.2 · claude CLI 2.1.220 · uv 
Scans: `~/Desktop/example-scans/Office_room`, `~/Desktop/example-scans/Tea_room`

This file records every step taken, every issue hit, and what was done about it.

---

## Setup (README §Install)

| step | command | result |
|---|---|---|
| 1 | `uv sync --frozen --extra detect --group dev` | OK — 14 packages installed (torch 2.12.1, torchvision 0.27.1, transformers 5.12.1) |
| 2 | `.env` — already present with `OPENAI_API_KEY`, `RUNPOD_API_KEY`, `RUNPOD_TRELLIS_ENDPOINT`. `BLENDER_PATH`, `LR_SCANS_DIR`, `GROUNDING_DINO_PYTHON` left empty | OK (see ISSUE-1) |
| 3 | `uv run python sanity.py` | **SANITY OK**, 0 warnings |

`sanity.py` output: torch device `mps`, DINOv2 `facebook/dinov2-small`, GroundingDINO
`IDEA-Research/grounding-dino-tiny`, Blender 5.1.2, `claude` on PATH, OpenAI key HTTP 200,
RunPod endpoint set.

---

## Issues

### ISSUE-1 — a full two-stage run announces itself as `realism_authoring` (cosmetic, `run.sh:320`)

`run.sh` prints its banner unconditionally as

```
── realism_authoring · Office_room ─────────────────────────
```

even when the run is the **full** `./run.sh <scan>` path that starts with stage 1 (`init`). The very
next line printed is `▶ init…`, which contradicts the banner. README §"Two stages" makes the
`scene_init` / `realism_authoring` split load-bearing (they "fail differently, cost differently, and
are re-run independently"), so mislabelling which one you are in is exactly the confusion the docs
try to prevent.

`SKIP_INIT` is already resolved by the time the banner prints (set to 1 when a scene package was
discovered), so the label can be conditional.

Status: **fixed** — see Fixes below. (Deferred until both runs finished: bash reads a script
incrementally from disk, so editing `run.sh` while it is executing can corrupt the running shell.)

### ISSUE-2 — stage 1's output is physically stored *inside* stage 2's folder (`run.sh:137–149`)

Observed on a fresh `./run.sh <scan>`, seconds after the run started:

```
run/Office_room/scene_init/obj_stage   -> …/run/Office_room/realism_authoring/scene_init/obj_stage
run/Office_room/scene_init/scene_stage -> …/run/Office_room/realism_authoring/scene_init/scene_stage
```

So `run/<scan>/scene_init/` is two **symlinks**, and the real stage-1 tree (object crops, reference
images, chair clusters, the reconstructed TRELLIS GLBs, the seed `Room.py`) sits under
`run/<scan>/realism_authoring/`.

**Root cause.** `run.sh:137` sets `FINAL_OUT="$AUTHORING"` (`run/<scan>/realism_authoring`), but the
symlink block at 139–149 that consumes it is written for the *per-scan final dir*
(`$FINAL_ROOT/$SCAN` = `run/<scan>`). Its own comment says so:

> By DEFAULT the two roots coincide (`$PWD/run`) and, with no `RUN_TAG`, `$OUT == $FINAL_OUT` — the
> mkdir below then already created the dirs, the `[ -e ]` guards short-circuit, and no symlink is
> made: `run/<scan>/` is one real directory.

`$OUT` (`run/<scan>`) can never equal `$AUTHORING` (`run/<scan>/realism_authoring`), so that branch
is unreachable: the guards never short-circuit and the symlinks are created on **every** run.
Meanwhile the Python side is unambiguous about where it means to write —
`scene_init/object_init/config.py:118–124`:

> it lives under stage 1's own root in the deliverables tree, `run/<scan>/scene_init/obj_stage`

**Why it matters — this one costs money and time.** Both the code comment at `run.sh:123` and the
README say the halves are independent:

> `run.sh:123`: Either half can be deleted and re-run without disturbing the other.
> README §Two stages, `realism_authoring` row: re-run — freely — it never touches the seed.

Under the current layout that is false. `rm -rf run/<scan>/realism_authoring` — the obvious,
documented way to redo stage 2 — deletes the **entire stage-1 output** and leaves two dangling
symlinks behind. Stage 1 is the expensive half (OpenAI reference-image generation + RunPod TRELLIS
reconstruction, ~$1–2/scene per the README), so the failure mode is: user resets the cheap agentic
half, silently loses the expensive deterministic half, and pays for it again. A subsequent
`./run.sh --scene run/<scan>` also fails outright, because the seed it needs is gone.

**Confirmed with an isolated probe** of just that path block (current code vs. proposed), driving it
through the documented stage-2 reset:

```
── before (current run.sh) ──
   symlinks under run/<scan>/scene_init : scene_init/scene_stage  scene_init/obj_stage
   physical seed lands at               : run/Office_room/realism_authoring/scene_init/obj_stage/seed.txt
   after 'rm -rf run/<scan>/realism_authoring', seed survives? : NO  <-- stage-1 output destroyed
   dangling links left behind           : scene_init/scene_stage  scene_init/obj_stage

── after (proposed) ──
   symlinks under run/<scan>/scene_init : (none)
   physical seed lands at               : run/Office_room/scene_init/obj_stage/seed.txt
   after 'rm -rf run/<scan>/realism_authoring', seed survives? : YES
   dangling links left behind           : (none)
```

Same result with `RUN_TAG=v2` set. The "after" column is the layout `run.sh`'s own comment and the
README already describe.

**The manifest agrees, and is the strongest evidence.** The `scene.json` this very run sealed
records the two halves as *siblings* under the package root — every stage-1 path is relative to
`run/<scan>/` and none of them goes through `realism_authoring/`:

```json
"paths": {
  "obj_stage":  "scene_init/obj_stage",
  "room_py":    "scene_init/scene_stage/room_init/room/Room.py",
  "room_glb":   "scene_init/scene_stage/room_init/room_preview/Room.glb",
  "authoring":  "realism_authoring",
  ...
},
"roots": { "output": ".../LiteReality-Agent/run", "final": ".../LiteReality-Agent/run" }
```

`scene.json` is what the README calls the seam — "Stage 1 seals its output folder with a
`scene.json` manifest recording every path … so stage 2 launches from that folder alone". Its
contract says `scene_init/` and `realism_authoring/` are siblings; on disk the `scene_init/*`
entries are symlinks pointing *into* `realism_authoring/`. And note `roots.output == roots.final`
— exactly the case `run.sh`'s comment claims yields "one real directory … no symlink is made".

Stage 1 also reported the nesting straight to the terminal:

```
✓ Room.py    run/Office_room/realism_authoring/scene_init/scene_stage/room_init/room/Room.py
✓ Room.glb   run/Office_room/realism_authoring/scene_init/scene_stage/room_init/room_preview/Room.glb
✓ scene package  run/Office_room
```

A regression test was added first, `tests/test_run_layout.py`, which executes `run.sh`'s own path
prologue in a temp tree and asserts the invariant. Against the current `run.sh` it is red:

```
FAILED test_stage_dirs_are_not_inside_the_authoring_dir
FAILED test_object_stages_own_path_is_the_real_tree
FAILED test_default_roots_produce_one_real_directory
FAILED test_split_roots_link_across_without_touching_stage_two
4 failed, 1 passed
```

The one that passes (`test_run_tag_shares_one_stage_one_tree`) documents a property that already
holds by accident and must keep holding: a `RUN_TAG` re-run of stage 2 must not fork stage 1.

Status: **fixed** — see Fixes below (deferred for the same in-flight-`run.sh` reason as ISSUE-1).

### ISSUE-3 — docs name the wrong image model (`ARCHITECTURE.md:129`, `sanity.py:267`)

`models.env:42` sets the default to `gpt-image-2` and that is what the run actually used —
the stage log shows `[openai-image] clean_obj_reference.png $0.08389`, and `openai_image.py:86–90`
has live `gpt-image-2`-specific behaviour (it disables transparent backgrounds, which only the
`gpt-image-1` family supports). But two places still advertise the legacy model:

- `ARCHITECTURE.md:129` — the registry table lists image-gen as `OpenAI gpt-image-1`
- `sanity.py:267` — `"OPENAI_API_KEY unset — reference image-gen (gpt-image-1) will fail."`

Cosmetic, but `sanity.py` is the file the README points users at when something is wrong, so it is
the worst place to name a model the pipeline does not use.

Status: **fixed** — see Fixes below.

*(Checked and NOT an issue: I suspected `models.env` was honoured only by `run.sh`, leaving the
README's `uv run -m litereality_agent <stage>` entry point on the code default
`openai_image.py:27 DEFAULT_IMAGE_MODEL = "gpt-image-1"`. It isn't — `cli.py:436` calls
`models.config.load_env()`, which parses `models.env` itself for exactly this reason. Both entry
points agree.)*

### ISSUE-4 — `sanity.py` reports the *code* defaults, not the models actually configured

Chasing ISSUE-3 turned up the reason the stale model name mattered. `sanity.py:_load_dotenv()` reads
**only `.env`**. `run.sh:41` sources `.env` **and `models.env`**, and `models.config.load_env()`
(what `uv run -m litereality_agent` uses) reads both as well. So `sanity.py` — the one script whose
stated job is

> `sanity.py:75–78`: so a bare `python sanity.py` sees the SAME config as `./run.sh`

— is the only entry point that does not. Every model choice lives in `models.env`, so the checks
that *print a model name* print whatever the code hardcodes:

- `LR_DINO_MODEL` → `dino_detect.default_model_id()` (`dino_detect.py:33`)
- `LR_DINO_EMBED_MODEL` → `dino_embed.default_model_id()` (`dino_embed.py:24`)
- `LR_OPENAI_IMAGE_MODEL` → the image-gen failure message

Demonstrated with an isolated fake repo whose `models.env` picks non-default checkpoints
(`grounding-dino-base`, `dinov2-large`, `gpt-image-9`), running each `sanity.py` against it:

```
── BEFORE (sanity.py at HEAD) ──
  ✓ DINOv2 grouping available (facebook/dinov2-small)              <-- code default
  ✓ GroundingDINO detector available (IDEA-Research/grounding-dino-tiny)   <-- code default
  ✗ OPENAI_API_KEY unset — reference image-gen (gpt-image-1) will fail.    <-- code default

── AFTER ──
  ✓ DINOv2 grouping available (facebook/dinov2-large)              <-- what models.env selects
  ✓ GroundingDINO detector available (IDEA-Research/grounding-dino-base)
  ✗ OPENAI_API_KEY unset — reference image-gen (gpt-image-9) will fail.
```

This is the failure mode `sanity.py`'s own docstring is written against — it exists to catch
"silent degradation … components that 'work' by quietly falling back to a weaker path". A user who
switches to a heavier detector in `models.env` and runs `sanity.py` to confirm gets a green tick
naming the small model, and cannot tell which one the run will load.

Status: **fixed** — see Fixes below.

### ISSUE-5 — the README documents `./report.sh`, which is not in the repo

README §"Seeing what the agent did":

```bash
./report.sh <scan>          # richer per-stage report — see the caveat below
```

and README:141 — "`run.sh`, `sanity.py`, `report.sh` and `tests/` stay at the repo root".

There is no `report.sh`. Not on disk (`ls *.sh` → `run.sh` only) and not tracked
(`git ls-files | grep report` → only the Python modules). It is not one of the deliberately
local-only files either — `.gitignore` lists those explicitly (`/NOTICE`, `/SETUP.md`, `/web/`)
and `report.sh` is not among them.

The README's own caveat then explains that the thing this missing script would have run
(`realism_authoring.scene.report_html`) reads the per-iteration `stage_<N>/iteration_<M>/verify.json`
layout of the retired multi-stage harness, so "on a default run the report comes out as an empty
shell". So the section documents a script that does not exist, to produce a report that would be
empty if it did.

There *is* a working equivalent for the current one-shot path:
`realism_authoring.trace_report` — "a self-contained HTML report of an authoring run: the trace
timeline WITH the rendered images embedded inline and the actual Room.py code changes shown as a
diff", reading `authoring_trace.*.jsonl` from `run/<scan>/`.

**Both halves verified against this run's real output**, mid-authoring:

```
$ uv run -m litereality_agent.services.tracing.report run/Office_room <out.html>
wrote <out.html>  (1.9 MB, 12 images, 87 events)                       # works

$ uv run -m litereality_agent.pipeline.stages.publish.report --scan Office_room --out <out>
no iteration with a verify.json under .../run/Office_room/scene_init/scene_stage/stage_1
$ echo $?
1                                                                       # and writes nothing
```

So the caveat was also understated: `report_html` does not produce "an empty shell", it exits
non-zero and produces no file.

Status: **fixed** — README now documents the `trace_report` module that works on the current
one-shot path, and the caveat says what actually happens. The `report.sh` mention in the repo-root
file list is gone.

*Alternative considered and rejected:* adding a `report.sh` wrapper to preserve the documented
spelling. The README ties `report.sh` specifically to `report_html`, the broken one, so a wrapper
would either keep pointing at the failing module or quietly mean something new. Pointing the docs
at the module that works is the smaller and more honest change; nothing in the codebase references
`report.sh`.

### ISSUE-6 — `run.sh`'s usage header states the opposite defaults to its own code

The header block a user reads at the top of `run.sh` (lines 21–25) and the implementation
(lines 347–362) disagree, in both directions — the two defaults look like they were swapped and the
header never updated:

| stage | header says | code does |
|---|---|---|
| 4 · materials | "**ON by default**; MATERIALS=0 to skip" | `if [ "${MATERIALS:-0}" = 1 ]` → **OFF** |
| 5 · refine | "**OFF by default**; RUN_REFINE=1 to enable" | `if [ "${RUN_REFINE:-1}" = 1 ]` → **ON** |

The run confirms it: `⊘ [4/7] fixturing + PBR materials — skipped (MATERIALS=0)` with no `MATERIALS`
set anywhere, and `obj refine` ran unasked. The implementation-side comments give clear rationales
for both current defaults, so the code is the intent and the header is stale.

Status: **fixed** — header corrected to match the code. Behaviour deliberately left alone: the
inline comments explain why materials is off ("the authoring pass already textures the shell, and
this extra PBR pass on the fixture palette isn't worth its cost/time for most runs") and why refine
is on. Flipping a default that costs ~13 min and money per run is the maintainer's call, not a
documentation fix.

### ISSUE-7 — per-object refinement is broken on every run: `run.sh` passes a `--refroot` that does not exist

The `obj refine` stage failed **4 out of 4 objects**:

```
   refining objects: Table0,Table1,Wall1_Door_0,Wall5_Window_0  (concurrency=2, budget=$8/obj)
  Table0: ✗ ERROR — no selected capture frames
  Table1: ✗ ERROR — no selected capture frames
  Wall1_Door_0: ✗ ERROR — no selected capture frames
  Wall5_Window_0: ✗ ERROR — no selected capture frames
  ⚠ 4/4 object(s) failed to refine
```

**Root cause.** `run.sh` passed `--refroot "$OUT/obj_stage/object_init"` in three places (lines 249,
264, 272). The object stage lives at `$OUT/**scene_init**/obj_stage/object_init` — the literal is
missing the `scene_init/` level and points at a directory that has never existed. `refine_objects.py:257–263`
globs the selected frames under that root, finds nothing, and returns the error for every object.

Note `run.sh` had already got this right one line earlier for the room:
`ROOM_INIT="${LR_ROOM_INIT:-$OUT/scene_init/scene_stage/room_init/room}"`. The `refroot` literals
simply were not updated when the layout gained the `scene_init/` level. The manifest has exported
the correct value all along — `LR_REFROOT=…/run/Office_room/scene_init/obj_stage/object_init`.

Proven directly against this run's tree, resolving frames both ways:

```
── OLD (run.sh before fix)  exists=False
     Table0           selected_frames= 0  -> ERROR 'no selected capture frames'
     Table1           selected_frames= 0  -> ERROR 'no selected capture frames'
     Wall1_Door_0     selected_frames= 0  -> ERROR 'no selected capture frames'
     Wall5_Window_0   selected_frames= 0  -> ERROR 'no selected capture frames'
── NEW (run.sh after fix)   exists=True
     Table0           selected_frames= 4  -> OK ['frame_00035.jpg', 'frame_00037.jpg', ...]
     Table1           selected_frames= 4  -> OK ['frame_00016.jpg', 'frame_00018.jpg', ...]
     Wall1_Door_0     selected_frames= 4  -> OK ['frame_00026.jpg', 'frame_00027.jpg', ...]
     Wall5_Window_0   selected_frames= 4  -> OK ['frame_00007.jpg', 'frame_00009.jpg', ...]
```

Since refine is ON by default (ISSUE-6), this means **a stage that runs on every default run has
never done anything**. The same bad path was also passed to `materials_pass` (line 272) and
`qc_pass` (line 249) — both currently opt-in, so those were latent.

Status: **fixed** — a single `REFROOT="${LR_REFROOT:-$OUT/scene_init/obj_stage/object_init}"`
defined next to `ROOM_INIT`, used in all three places, package-first like every other stage path.

### ISSUE-8 — the documented install omits `python-fcl`, so QC's clash resolver aborts every run

The `qc` stage ended with a traceback:

```
File ".../realism_authoring/qc_collision.py", line 76, in plan
    findings = sc.check_all(bodies, SHELL)
  ...
ValueError: No FCL Available! Please install the python-fcl library
```

`pyproject.toml:46` puts it behind an optional extra — `collision = ["python-fcl", "networkx"]` —
but the README's install line is `uv sync --frozen --extra detect --group dev`, which does not
include it. `run.sh:246` runs `qc_collision … || true` on every default run, so the missing
dependency never fails the run; it just prints a traceback into the stage log.

**This was not cosmetic.** Installing `python-fcl` and re-running the exact same command on the
finished room found real work that the run had skipped:

```
COLLISION FIX (true-mesh) run/Office_room/realism_authoring/room/Room.py
  mesh clashes: 2   moves: 3   other: 0   grounding: 0
  ↔ Table1           0.243 m   (-2.687, -1.218) → (-2.709, -0.976)
  ↔ Table0           0.242 m   (-0.701, 0.645) → (-0.701, 0.887)
  ↔ Chair4           0.241 m   (-1.119, 0.123) → (-1.119, -0.118)
```

Three objects were interpenetrating by ~24 cm each and the gate that would have fixed them was
silently inert. `python-fcl` installs cleanly from a wheel on macOS/Apple Silicon — there was no
platform reason to leave it out.

Status: **fixed** — README install line is now
`uv sync --frozen --extra detect --extra collision --group dev`, with a note on what it is for, and
`sanity.py` gained a check so this is caught *before* a run instead of mid-stage. Verified in both
directions by uninstalling and reinstalling `python-fcl`:

```
✗ python-fcl NOT available — QC's true-mesh clash resolver will abort and the run will SILENTLY skip it.
      → fix: run uv sync --frozen --extra detect --extra collision --group dev
✓ python-fcl available (true-mesh clash resolver)
```

### ISSUE-9 — the README's output table points at the wrong directory

README §"You get, in `run/<scan>/`" lists four files. Checked against the finished run:

```
  ✗ run/Office_room/Room.py           MISSING
  ✗ run/Office_room/Room.glb          MISSING
  ✗ run/Office_room/Office_room.html  MISSING
  ✓ run/Office_room/scene.json
```

Three of the four are one level down, in `run/<scan>/realism_authoring/` — which is what `run.sh`
prints at the end and what `scene.json` says (`"authoring": "realism_authoring"`). The
`Room.blend` path in the viewer note was wrong too: README said
`run/<scan>/scene_stage/_oneshot/room_preview/`, actual is
`run/<scan>/realism_authoring/room_preview/`.

Status: **fixed** — README now describes the real layout (`scene.json` + the two stage folders at
the package root, deliverables inside `realism_authoring/`) and the corrected `Room.blend` path.

*Alternative considered and rejected:* moving the deliverables up to `run/<scan>/` to match the old
text, by setting `FINAL_OUT="$FINAL_ROOT/$SCAN"`. `scene.json`, `run.sh`'s final summary and the
viewer/replay path resolution all consistently place stage 2's output under `realism_authoring/`,
so the docs were the outlier. Moving them would have meant re-verifying viewer, replay and compare
path resolution across another full run for no functional gain.

### ISSUE-10 — the run summary reports failed stages as successful (not fixed — see below)

The final summary for a run in which refinement failed on every object and QC aborted:

```
   ✓ init                                             21m20s
   ✓ stitches                                            14s
   ✓ authoring                                        20m55s
   ✓ materials (skipped)                                       0s
   ✓ obj refine                                           0s     <-- 4/4 objects failed
   ✓ qc                                                   3s     <-- ValueError: No FCL Available!
   ✓ export                                              21s
   total                                            42m57s
```

`run.sh` exited 0. The mechanism: `stage()` decides pass/fail purely from the command's exit
status, and both stages swallow theirs — `do_qc` runs each sub-step with `|| true` (lines 245–246),
and `refine_objects` reports per-object errors but exits 0. So the ✓ is truthful about the exit
code and misleading about the outcome, and the only trace is a 34-column snippet of the stage log
in the middle column — which is how both of these were noticed at all.

This is the reason ISSUE-7 and ISSUE-8 could persist: both are loud in the stage log and invisible
in the summary.

Status: **NOT fixed — deliberately left for the maintainer.** A correct fix means deciding, per
stage, which partial failures should turn the run red, and `soft` stages exist precisely so a run
is not aborted by them. Making `obj refine` fail the run when any object fails, or `qc` fail when
FCL is missing, is a policy change to the pipeline's success contract that could start failing runs
that currently complete — not something to change underneath you while fixing path bugs. Flagging
it as the highest-value follow-up: with ISSUE-7 and ISSUE-8 fixed, both known offenders are gone,
so the summary is currently honest for these two scans, but the masking mechanism remains.

### ISSUE-11 — refinement's 25-turn cap is far too low (found *because* ISSUE-7 was fixed; NOT fixed)

**This one only became visible after the ISSUE-7 fix, and it means refinement is still not
usable — I want to be plain about that.** Fixing the `--refroot` path was necessary but not
sufficient.

With the path fixed, refinement does real work for the first time: each object reads its selected
capture frames, crops detail regions, renders the model and compares. But 7 of 8 objects then died
on a *different* limit:

```
== ALL DONE ==
  Dishwasher0:      ✗ ERROR — Reached maximum number of turns (25)
  Sink_Storage0:    ✗ ERROR — Reached maximum number of turns (25)
  Storage0:         ✗ ERROR — Reached maximum number of turns (25)
  Storage1:         ✗ ERROR — Reached maximum number of turns (25)
  Storage3:         rounds=0 calls=30 code Δ +100/-113 cost=$2.64      <-- the only one that landed
  Table0:           ✗ ERROR — Reached maximum number of turns (25)
  Wall10_Door_0:    ✗ ERROR — Reached maximum number of turns (25)
  Wall10_Window_0:  ✗ ERROR — Reached maximum number of turns (25)
  ⚠ 7/8 object(s) failed to refine        [stage time: 80m19s]
```

**Root cause.** `refine_objects.py:379` — `--max-turns` defaults to
`int(os.environ.get("LR_REFINE_MAX_TURNS", "25"))`, and `run.sh` never passes the flag, so it is
always 25. For contrast the authoring stage gets `AUTHOR_TURNS=200` with a step budget of 100 —
and the one object that succeeded used 30 calls. The cap is almost certainly untuned: until the
`--refroot` fix, every object failed at frame selection in ~0 seconds, so the cap could never be
reached and never showed up as wrong.

The cost is real: this run spent **80 minutes** on 8 agent sessions, of which 7 hit the wall and
produced nothing. The per-object `$8` budget guardrail was never the binding constraint — the turn
cap was.

**UPDATE — fixed, at your direction (cap 100, one simple change, and never force an edit).**
Three changes to `refine_objects.py`:

1. **`--max-turns` default 25 → 100.** At 25 an object spent nearly every turn *reading* — `object.md`,
   `object.py`, three capture frames, then crops of those — and died before landing an edit.
2. **The prompt now asks for ONE small, high-value change, not a rebuild.** No rewriting or
   refactoring `object.py`, no chasing small details; render once, then either make the single
   most valuable fix or conclude none is needed.
3. **It must not invent work.** The prompt opens by asking whether anything needs changing at all,
   states that "no change needed" is a good and common result, and warns that a speculative edit to
   an object that was already fine usually makes it worse. It is also told to leave alone any detail
   the frames are too small, blurry or occluded to judge — guessing from bad evidence is worse than
   the current build. A clean session with no edits now reports `✓ no change needed`, not a bare
   `rounds=… code Δ +0/-0` that reads like a silent no-op.

An earlier draft of (2) pushed too hard the other way — it told the agent that "running out of turns
before you have edited `object.py` is the worst outcome", which pressures it into unnecessary edits.
Removed.

Original status, kept for the record: **NOT fixed — needs a decision I should not make for you.** Raising the default directly
multiplies time and spend on every run (the one object that completed cost $2.64; eight objects
allowed to run to completion could plausibly be 3-4× this run's refine spend). I have one scan's
worth of evidence and no basis for picking the right number. Three options, in the order I would
consider them:

1. **Raise `LR_REFINE_MAX_TURNS`** to something in the 60-100 range and measure. The knob already
   works via the environment (`LR_REFINE_MAX_TURNS=80 ./run.sh <scan>`) — `run.sh` passes its
   environment to every stage, so nothing needs plumbing.
2. **Turn refinement off by default** (`RUN_REFINE=0`) until the cap is tuned, since at 25 turns it
   is ~87% wasted spend on every default run.
3. Leave as-is and accept that refinement is best-effort.

What I did do: documented the knob in `run.sh`'s usage header next to `LR_REFINE_ROUNDS`, which did
not mention it.

### ISSUE-12 — every before/after comparison image was silently missing (`$LITEREALITY_BLENDER` dir vs binary)

Found while verifying ISSUE-11: refinement completed 4/4 objects with real edits, but produced no
comparison images at all — only `.diff` files. The `*_views` directories existed and were **empty**.

**Root cause.** `_snapshot_views` runs `subprocess.run([blender, "-b", ...])` with `blender` taken
straight from `$LITEREALITY_BLENDER`. But that variable is the *install directory*, by this repo's
own documentation:

> `.env.example:8` — Your Blender INSTALL DIR — the folder containing the `blender` binary, not the binary itself.
> `README.md:61` — `BLENDER_PATH` — Your **Blender installation directory**.

Executing a directory raises `PermissionError: Permission denied:
'/Applications/Blender.app/Contents/MacOS'`. `_snapshot_views` catches everything, returns `False`,
and prints nothing — and the before/after sheet is only written when the snapshot succeeds. So the
sole symptom was a missing image with nothing in any log connecting it to Blender. A blank
`BLENDER_PATH` (the state of this machine's `.env`) fails the same way via an empty string.

Both Blender steps work fine when handed the real binary — verified by running them by hand:

```
build  -> EXPORTED: .../t0.glb                (rc 0)
render -> Saved: view_0.png … view_3.png      (rc 0)
```

The repo already has the resolver for exactly this: `integration/config.py:find_blender()`
"Accepts either the binary or the install directory", and its docstring records that six copies of
this logic once existed and disagreed. `refine_objects` was bypassing it.

Status: **fixed** — `_blender()` now always delegates to `find_blender()`, and `_snapshot_views`
prints `[snapshot] <name> FAILED — no before/after image will be written. <why>` instead of
returning False in silence. Verified: `Wall5_Window_0` re-run produced
`_beforeafter/Wall5_Window_0_beforeafter.png` (real capture | before | after | after-opened) and the
combined `refine_beforeafter.png`, with zero snapshot failures in the log.

### ISSUE-13 — `--scene` and `run.sh` wrote refine results to different directories

`stage_args.bind` defaulted `--results` to `<package>/obj_refine`, while `run.sh:281` passes
`--results "$FINAL_OUT/obj_refine"` = `<package>/realism_authoring/obj_refine`. So the same stage
put its before/after evidence in two different places depending on how it was launched, and
`run.sh`'s summary — which prints the `before/after` line only if
`$FINAL_OUT/obj_refine/refine_beforeafter.png` exists — would never find a `--scene` run's output.

`work_room()` in the same file already documents this hazard for the room itself ("a
package-launched stage and a run.sh-launched stage quietly fork into two rooms and the later stages
export whichever one they happen to find"); the results dir had the same problem.

Status: **fixed** — `results` is now derived from `work_room(pkg, create=False).parent`, so it sits
beside the work room and matches run.sh, picking up `$RUN_TAG` and the legacy pre-move layout for
free. Verified: `--scene run/Office_room` now resolves
`room = run/Office_room/realism_authoring/room`,
`refroot = run/Office_room/scene_init/obj_stage/object_init`,
`results = run/Office_room/realism_authoring/obj_refine`.

---

## Fixes applied

All changes are in `run.sh`, `sanity.py`, `README.md`, `ARCHITECTURE.md` and one new test file.
No behavioural default was changed — only paths that were wrong, docs that disagreed with the code,
and one missing dependency.

| # | file | change |
|---|---|---|
| 1 | `run.sh` | banner names the halves the run will actually do (`scene_init + realism_authoring`, or `realism_authoring` when `SKIP_INIT=1`) |
| 2 | `run.sh` | new `STAGE_ROOT="$FINAL_ROOT/$SCAN"` for the stage-dir mkdir/symlink block, so stage 1 lands beside stage 2 instead of inside it |
| 3 | `ARCHITECTURE.md`, `sanity.py` | image model named as `gpt-image-2`; sanity now reports whatever `LR_OPENAI_IMAGE_MODEL` actually is |
| 4 | `sanity.py` | `_load_dotenv()` now loads `models.env` too, via the package's own `models.config.load_env` (with the old `.env`-only parse kept as the half-installed-tree fallback) |
| 5 | `README.md` | `./report.sh` → the `trace_report` module that works; caveat corrected |
| 6 | `run.sh` | usage header's materials/refine defaults corrected to match the code |
| 7 | `run.sh` | new `REFROOT="${LR_REFROOT:-$OUT/scene_init/obj_stage/object_init}"`, used by refine · materials · qc_pass |
| 8 | `README.md`, `sanity.py` | install line gains `--extra collision`; new pre-run `python-fcl` check |
| 9 | `README.md` | output-path table and `Room.blend` path corrected |
| 11 | `run.sh`, `refine_objects.py` | turn cap 25→100; prompt asks for ONE small change and permits "no change needed"; partial results keep their sheet + diff; usage header documents the knob |
| 12 | `refine_objects.py` | `_blender()` always resolves via `find_blender()` (dir→binary); failed snapshots report why |
| 13 | `stage_args.py` | `--scene` results dir now matches run.sh's (`<authoring>/obj_refine`) |
| — | `tests/test_run_layout.py` | **new** — 5 tests executing `run.sh`'s path prologue, guarding #2 and the `RUN_TAG` invariant |

Test suite: **305 passed, 5 skipped, 1 xfailed** (was 300 passed before the new file).
`tests/test_run_layout.py` went 4-failed → 5-passed on the ISSUE-2 fix.

### Fixes validated on a live run, not just in tests

Tea_room was run **after** every fix was applied, so it is an end-to-end check. Both runs' own
terminal output, side by side:

```
BEFORE fix (Office_room) — stage 1's own report:
   ✓ Room.py    run/Office_room/realism_authoring/scene_init/scene_stage/room_init/room/Room.py
   ✓ Room.glb   run/Office_room/realism_authoring/scene_init/scene_stage/room_init/room_preview/Room.glb

AFTER fix (Tea_room):
   ✓ Room.py    run/Tea_room/scene_init/scene_stage/room_init/room/Room.py
   ✓ Room.glb   run/Tea_room/scene_init/scene_stage/room_init/room_preview/Room.glb
```

and where the stage directories physically resolve to:

```
  Office_room  obj_stage      549 files  ✗ NESTED in stage 2
  Office_room  scene_stage     66 files  ✗ NESTED in stage 2
  Tea_room     obj_stage      682 files  ✓ beside stage 2
  Tea_room     scene_stage    133 files  ✓ beside stage 2
```

615 files of Office_room's stage-1 output — every reference image, every reconstructed GLB, the
seed — sit inside the folder the README says you may delete and re-run freely. Tea_room's 815 sit
beside it. The only symlink left under `run/Tea_room/` is `capture/Tea_room`, which is deliberate
(`scene.json`: `"capture": {"mode": "link"}`).

Also confirmed live: the banner now reads `── scene_init + realism_authoring · Tea_room ──`
(ISSUE-1), and `sanity.py`'s new `✓ python-fcl available` line ran as part of the pipeline's own
pre-flight (ISSUE-8).

Three things were deliberately *not* changed, each called out above with reasoning: the
materials/refine defaults themselves (ISSUE-6), the summary's pass/fail contract (ISSUE-10), and
the refine turn cap (ISSUE-11). All three are cost/policy decisions rather than defects with one
obviously correct answer.

## Refinement, after ISSUE-7 / 11 / 12 / 13

Office_room's refine stage re-run with every fix in place — from 4/4 failing in 0 seconds to 4/4
landing edits, ~$5.43 total:

| object | calls | code Δ | cost |
|---|---|---|---|
| Table0 | 13 | +14/−5 | $1.28 |
| Table1 | 27 | +21/−14 | $1.89 |
| Wall1_Door_0 | 19 | +10/−6 | $1.25 |
| Wall5_Window_0 | 23 | +14/−11 | $1.70 |

`Wall5_Window_0`'s comparison sheet shows the upper pane band widened to match the real window's
proportions, with the articulation still working in the OPENED panel.

Caveat on those numbers: they ran before the "do not invent work" prompt revision, so some of those
edits may not have been necessary. Re-running under the current prompt is the fair measurement.

Per-stage command, either scan:

```bash
uv run -m litereality_agent.pipeline.stages.refine.objects --scene run/<scan>
```

## Still open, in the order I would tackle them

1. **ISSUE-10 — the summary ticks failed stages green.** Now the top item. This is what let
   ISSUE-7 and ISSUE-8 hide in plain sight across an entire run that exited 0, and it is the reason
   ISSUE-12 stayed invisible too.
2. **Re-measure refinement under the revised prompt.** The 100-turn cap and the "one small change /
   no change is fine" wording have not been measured together on a full scene. Tea_room is the
   natural test.
3. **`Storage0` floating 1.42 m** in Tea_room (needs a 1.78 m correction the resolver declined to
   apply). Now visible thanks to the ISSUE-8 fix; root cause not investigated.
4. **Office_room's stage-1 tree is still in the ISSUE-2 layout** (615 files nested inside
   `realism_authoring/`). New scenes are fine; that one scene would need a manual move.

---

## Run log

### Office_room — `./run.sh ~/Desktop/example-scans/Office_room`

Scans came from the README's own source, `git clone https://github.com/LiteReality/example-scans`
(the checkout on this machine is `~/Desktop/example-scans`). Both scans were run **sequentially,
not in parallel** — overlapping them would have put two heavy `claude` CLI sessions and two Blender
processes in flight at once, and any rate-limit or contention failure would then be indistinguishable
from a real code issue, which is the opposite of what this log is for.

**Stage 1 · `scene_init` — 21m20s, clean**

| stage | result | time |
|---|---|---|
| extract | 59 frames, 9 walls / 7 objects / 1 floor, 2 openings | 0.5s |
| box merge | no overlaps to merge | 0.0s |
| crops | 9 objects | 1.4s |
| dino polish | 29 boxes tightened, 0 wrong-projection + 3 blurry dropped | 28.9s |
| object refs | 2 objects (Table0, Table1) — `gpt-image-2`, $0.084 each | 76.7s |
| chair groups | 5 chairs → 2 clusters (DINOv2 + `claude-opus-5` judge) | 96.5s |
| opening refs | 2 openings (Wall1_Door_0, Wall5_Window_0) | 85.0s |
| routing | 2 procedural · 2 trellis | 37.1s |
| reconstruction | 6/6 built | 15m06s |
| build | 6 GLBs + Room.glb 16.0 MB | ~5s |

Reconstruction detail: TRELLIS/RunPod did both chair clusters in 119.7s wall, of which **100.3s
(84%) was queue + cold start** and only 37.0s was execution. The procedural agent branch dominated:
`Wall1_Door_0` alone took 839s. Openings finished 2/2.

Observations that are **not** issues, checked and dismissed:

- `⚠ No ranked crops for Wall5_Window_0, skipping` during `crops` looks alarming, but that is the
  *object*-crop path; `opening refs` then produced the window reference fine (4 views, 4
  DINO-refined) and it reconstructed.
- `[nano-banana] ChairCluster0` in the logs is legacy naming, not a provider-policy violation —
  `references/openai_image.py:1` is "a drop-in twin of `gemini_image.nano_banana`" and keeps the
  function name, and `object_init/config.py:68` documents the legacy filenames deliberately. The
  adjacent `[openai-image]` line is the real call.
- Repeated Blender `BindingsAtPrim … MaterialBindingAPI is not applied` warnings during USD export
  are from Blender's own USD library, not this codebase.

**Stage 2 · `realism_authoring` — 21m37s**

| stage | result | time |
|---|---|---|
| stitches | 8/8 surfaces stitched (+ known/unknown masks) | 14s |
| authoring | one-shot pass, `claude-opus-5`, 86 steps; two-tone wall paint, speckled carpet, 600 mm ceiling tiles, trunking + skirting on all 9 walls, shelf, whiteboard, 15 sockets | 20m55s |
| materials | skipped (`MATERIALS=0`) → ISSUE-6 | 0s |
| obj refine | **4/4 failed** — `no selected capture frames` → ISSUE-7 | 0s |
| qc | geometry lint clean (0 violations); collision resolver **crashed** on missing FCL → ISSUE-8 | 3s |
| export | viewer + Room.glb + replay | 21s |

**Total 42m57s, exit 0, all seven stages reported ✓** → ISSUE-10.

Run made before any fix was applied, so it is the "before" reference throughout this document.

---

### Tea_room — `./run.sh ~/Desktop/example-scans/Tea_room`

Run **after every fix**, as the end-to-end validation.

| stage | result | time |
|---|---|---|
| init | 62 frames · 13 objects cropped · 30 boxes tightened · 7 object refs · 4 chairs → 2 groups · 2 openings · routing 6 procedural + 3 trellis · **11/11 reconstructed** | 29m19s |
| stitches | 9 walls + floor + ceiling | 16s |
| authoring | one-shot pass, 86 steps; sockets, door/window trim, wall bands | 19m52s |
| materials | skipped (`MATERIALS=0`) — expected | 0s |
| obj refine | **now does real work** (ISSUE-7 fixed): 8 objects, ~30 tool calls each, `Storage3` landed code Δ +100/-113. But **7/8 hit the 25-turn cap** → ISSUE-11 | 80m19s |
| qc | **ran properly** (ISSUE-8 fixed): 2 geometry violations + 4 mesh clashes found and reported | 9s |
| export | viewer + Room.glb + replay | 1m32s |

**Total 131m31s, exit 0.**

QC output, which on Office_room was a traceback and here is a real report:

```
  furniture: 10  wall fixtures: 13  violations: 2
  ✗ Storage0         floating             1.42 m above the floor
  ✗ Switch0          fixture_over_opening sits over Window0 on Wall10 ~0.09 m
COLLISION FIX (true-mesh) run/Tea_room/realism_authoring/room/Room.py
  mesh clashes: 4   moves: 0   other: 0   grounding: 1
  ! Storage0         reverted: needs 1.78 m (cap 0.30)
  ! Storage1         reverted: needs 1.18 m (cap 0.30)
  ! Storage3         reverted: needs 1.96 m (cap 0.30)
  ! Sink_Storage0    reverted: needs 1.78 m (cap 0.30)
```

(The four reverts are the resolver working as designed — each needed a nudge well beyond the 0.30 m
cap, so it declined and reported rather than teleporting furniture. Worth a look: `Storage0`
floating 1.42 m and needing 1.78 m suggests its placement is wrong upstream, in stage 1 or
authoring. Not investigated — out of scope for this pass, but it is the kind of thing the QC gate
exists to surface, and it could not surface it at all before ISSUE-8 was fixed.)

**Deliverables verified present**, at the paths the README now documents:

```
  ✓ run/Tea_room/scene.json
  ✓ run/Tea_room/scene_init/          (real dir, not a symlink)
  ✓ run/Tea_room/realism_authoring/Room.py     84K
  ✓ run/Tea_room/realism_authoring/Room.glb    26M
  ✓ run/Tea_room/realism_authoring/Tea_room.html  35M
  ✓ run/Tea_room/realism_authoring/room_preview/Room.blend
  ✓ trace_report → Tea_room_trace_report.html  (16.8 MB, 97 images, 254 events)
```
