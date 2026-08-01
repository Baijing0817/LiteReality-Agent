# scripts/

Standalone tooling. Nothing here is imported by the package — these are entry points you run
directly. All of them resolve the repo root themselves, so they work from any working directory.

The supported entrypoint is `uv run litereality`. Files here are maintenance and batch wrappers,
not importable application code. Use `uv run litereality stage <name> <scene>` for one stage.

## Batch pipeline stages

Each defaults its worklist to every scan directory under `$LR_SCANS_DIR`; pass scan names to narrow
it. All are idempotent — finished work is skipped unless you pass `--force`.

| script | stage |
|---|---|
| `pipeline/init_batch.sh` | deterministic pipeline through seed `Room.py` |
| `pipeline/preprocess_objects.sh` | ingest up to chair grouping |
| `pipeline/generate_objects.sh` | reference generation before reconstruction |
| `pipeline/reconstruct_objects.sh` | reconstruction for named scans |
| `pipeline/reconstruct_all.sh` | reconstruction across scans with bounded parallelism |
| `pipeline/scene_init_all.sh` | seed assembly only |
| `pipeline/qc_batch.sh`, `pipeline/qc_fallback.sh` | batch quality operations |

## Capture utilities

Fuse the raw RoomPlan capture into geometry for render-vs-real comparison.

- `capture/build_meshes.py` — per-scene TSDF mesh from RGB + depth + poses
- `capture/build_pointclouds.py` — per-scene fused colored point cloud
- `capture/colorize_pcd.py` — colorize the scanner's point cloud from RGB frames
- `capture/shrink_scan.py` — reduce capture size without changing pipeline semantics

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
