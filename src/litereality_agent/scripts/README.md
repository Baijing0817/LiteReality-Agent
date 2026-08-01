# scripts/

Standalone tooling. Nothing here is imported by the package — these are entry points you run
directly. All of them resolve the repo root themselves, so they work from any working directory.

The supported pipeline entry points stay at the repo root: `./run.sh <scan>`, `sanity.py`, and the
`./report.sh <scan>`. Use these only when you want a single stage or a batch.

## Batch pipeline stages

Each defaults its worklist to every scan directory under `$LR_SCANS_DIR`; pass scan names to narrow
it. All are idempotent — finished work is skipped unless you pass `--force`.

| script | stage |
|---|---|
| `init_batch.sh` | full deterministic init (crops → DINO → refs → reconstruct → seed `Room.py`) |
| `preprocess_objects.sh` | object stage up to chair grouping, stopping before any generation |
| `generate_objects.sh` | reference image generation, stopping before reconstruction |
| `reconstruct_objects.sh` | object reconstruction for the named scans, sequentially |
| `reconstruct_all.sh` | `reconstruct_objects.sh` across every scan, GPU-throttled (`$LR_RECON_PARALLEL`, default 5) |
| `scene_init_all.sh` | scene_init seed only — assembles reconstructed objects into `Room.py` + `Room.glb` |
| `qc_batch.sh`, `qc_fallback.sh` | QC passes over authored rooms |

## Capture utilities

Fuse the raw RoomPlan capture into geometry for render-vs-real comparison.

- `build_meshes.py` — per-scene TSDF mesh from RGB + depth + poses
- `build_pointclouds.py` — per-scene fused colored point cloud
- `colorize_pcd.py` — colorize the scanner's own `pointcloud.pcd` by projecting RGB frames

## ops/

Publishing tooling for the results mini-site. Not part of the reconstruction pipeline — you only
need these to build and upload the public pages.

- `compact_rooms.py` — pack authored rooms into their compact, source-only form
- `compact_to_html.py` — one compact room → a self-contained interactive HTML page
- `make_recon_pages.py` / `make_recon_thumbs.py` / `make_recon_index.py` — build the per-scene
  pages, thumbnails, and the `/recon/` landing page
- `publish_qc.py` — publish QC'd rooms as separate `<scan>-QC` cards
- `upload_recon_r2.py` — upload the built site to R2
- `_r2_env.py` — shared R2 credential resolution (see below)

R2 credentials resolve in this order: ambient `R2_*` env vars → `--env-file` → `$LR_R2_ENV_FILE` →
`~/.litereality_r2.env`. The public base URL comes from `$LR_R2_PUBLIC_BASE`.
