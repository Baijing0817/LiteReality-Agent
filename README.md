# LiteReality-Agent

LiteReality-Agent is a full-stack package that turns an indoor room scan into a realistic,
simulation-ready reconstruction — the scanner, the agentic authoring loop, and the integration
layer on top.

<p align="center">
  <img src="assets/comparison.gif"/>
</p>

## How to use

1. **Get the scanner app** — join the TestFlight beta at
   [testflight.apple.com/join/EbNYmVGV](https://testflight.apple.com/join/EbNYmVGV).
2. **Scan your room.** One walkthrough captures the RGB frames, depth, and the RoomPlan
   `room.usdz` the pipeline needs.
3. **Upload the scan** to the machine you'll run on.
4. **Run LiteReality-Agent** — `./run.sh <path/to/scan>` — for an articulated, realistic room reconstruction.

The result is an editable room program (Room.py) that can be compiled in Blender and integrated into other engines.

**Test scenes.** Don't have a scan yet? Clone the example room scans from
[LiteReality/example-scans](https://github.com/LiteReality/example-scans) and run any of them by
pointing at the folder:

```bash
git clone https://github.com/LiteReality/example-scans.git
./run.sh example-scans/<scan>
```


## Requirements

This repository has been tested on **macOS** (Apple Silicon) and **Linux** (with a 24 GB GPU).

1. [`uv`](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Blender 5.x
4. **OpenAI/google API key** for reference image generation (typically costs less than $1 per scene)
5. **logged-in agent CLI** on your `PATH` — drives all reasoning and vision. 
`claude` (Claude Code) is the default; `codex` (OpenAI Codex) is also supported
6. **RunPod API key** (typically costs less than $1 per scene): https://www.runpod.io/ 

(required on macOS for Trellis; can also be installed locally if you are on Linux, see more below)


## Install

**1. Install the env** (torch/DINO included — required):

```bash
uv sync --frozen --extra detect --group dev
```

**2. Configure** — Copy `.env.example` to `.env` and fill in the required values:

- `OPENAI_API_KEY` / `GOOGLE_API_KEY` — API key for reference image generation.
- `BLENDER_PATH` — Your **Blender installation directory** (the folder containing the `blender` binary).
- `RUNPOD_TRELLIS_ENDPOINT` + `RUNPOD_API_KEY` — your own RunPod Serverless TRELLIS endpoint ID
  and API key.
- `GROUNDING_DINO_PYTHON`

If you do not want to use RunPod and are on Linux, install TRELLIS locally and provide the TRELLIS Python environment path:

- `TRELLIS_PYTHON` — Path to the local GPU TRELLIS environment's Python interpreter.

**3. Check you're ready to go.** `sanity.py` verifies your dependencies, models, Blender installation, and API keys, and prints the exact fix for anything missing.

```bash
uv run python sanity.py
```

## Two stages

The pipeline is two halves that meet at a folder, and it is worth knowing which one you are in —
they fail differently, cost differently, and are re-run independently.

| | **1 · `scene_init`** | **2 · `realism_authoring`** |
|---|---|---|
| what | scan → per-object references → reconstructed GLBs → seed `Room.py` + `Room.glb` | edit `Room.py` until it looks like the real room: shell materials, fixtures, PBR, per-object refinement, QC, viewer |
| driven by | **deterministic** — models are called for specific decisions (grouping, classification, reference images), but the control flow is fixed and reproducible | **agentic** — self-paced model passes that look at renders and edit code |
| needs | the capture, GPU/RunPod for TRELLIS, Blender | the seed from stage 1, a logged-in agent CLI, Blender |
| re-run | when the capture or the reconstruction changes | freely — it never touches the seed |
| output | a **scene package**: `run/<scan>/` + `scene.json` | the authored `Room.py`, `Room.glb`, and the viewer |

The seam is the scene package. Stage 1 seals its output folder with a `scene.json` manifest
recording every path, root and capture location, so **stage 2 launches from that folder alone** —
no scan name, no `$LR_SCANS_DIR`, no per-stage path flags.

## Run

Both stages, end to end — give it a scan folder, or a name to resolve under `$LR_SCANS_DIR`:

```bash
./run.sh example-scans/Office_room     # the capture folder, from anywhere
```

Each stage prints as it completes, and per-stage logs land in `run/<scan>/`.
Or one stage at a time — the point of the seam:

```bash
uv run -m litereality_agent scene_init example-scans/Office_room          # stage 1 → a scene package
uv run -m litereality_agent realism_authoring run/Office_room   # stage 2, realism_authoring
```

Stage 2 takes the package and nothing else; omit the argument entirely when `$LR_SCENE` is set,
when you are standing inside a package, or when there is only one on disk. `./run.sh --scene <dir>`
is the same thing.



You get, in `run/<scan>/`:

| file | what |
|---|---|
| `Room.py` | the room as an editable program — walls, openings, objects, materials, fixtures |
| `Room.glb` | the built room, ready to drop into another engine |
| `<scan>.html` | a self-contained Three.js viewer — open it directly, no server needed |
| `scene.json` | the manifest: every path, root and capture location this scene needs |

The Three.js viewer is deliberately lightweight: it is there to check geometry and layout at a
glance, and does **not** reproduce the full PBR shading. For the accurate look, open the Blender
file — `Room.blend`, written next to the preview GLB at
`run/<scan>/scene_stage/_oneshot/room_preview/`.

**Where the code lives.** Everything importable is one package, `src/litereality_agent/`, laid out along
the same two stages:

```
src/litereality_agent/
├── scene_init/          STAGE 1 — the deterministic half (object_init + seed export + package)
├── realism_authoring/   STAGE 2 — the agentic half (author · materials · refine · qc · viewer)
├── integration/         the Room program: Room.py → Room.glb, and manifest.py (the scene package)
├── models/              one front door per model role: llm · vlm · detect · gen3d
├── backends/            heavy/external behind launchers: TRELLIS · GroundingDINO · procedural
├── scripts/             standalone entry points and batch runners
└── cli.py               the command line — `uv run -m litereality_agent <command>`
```

`run.sh`, `sanity.py`, `report.sh` and `tests/` stay at the repo root, alongside the data trees
they operate on (`run/`, `scans_uploaded/`). See
[ARCHITECTURE.md](ARCHITECTURE.md).

### Seeing what the agent did

The viewer's **trace** panel shows the run's event log — stage boundaries, image-generation calls,
reconstruction and QC events, with elapsed times. That is built in by default, no extra step.

```bash
./report.sh <scan>          # richer per-stage report — see the caveat below
```

> **Caveat:** `report.sh` renders `litereality_agent.realism_authoring.scene.report_html`, which reads the per-iteration
> `scene_stage/stage_<N>/iteration_<M>/verify.json` layout written by the older multi-stage harness.
> The current one-shot authoring path does not produce that layout, so on a default run the report
> comes out as an empty shell. It is useful only for runs made with the staged harness.
