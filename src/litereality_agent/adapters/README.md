# launcher — thin runners over the pristine third-party clones

`backends/TRELLIS.2/` and `backends/GroundingDINO/` are **direct `git clone`s,
kept unmodified** so the setup reproduces anywhere. This folder is the only thing
that knows how to *call* them: it puts each clone on `sys.path`, points the
HuggingFace cache at [`../weights/`](../weights/) so model weights **auto-download
there on first run**, and sets the GPU defaults TRELLIS.2 expects — without editing
a single file in either clone.

| file | what it does |
|------|--------------|
| `_env.py` | shared wiring: clone paths on `sys.path`, `HF_HOME -> ../weights`, sdpa attention, EXR I/O |
| `trellis_launcher.py` | image → textured **GLB** via `microsoft/TRELLIS.2-4B` (auto-downloaded) |
| `grounding_dino_launcher.py` | open-vocab **detection** from a text prompt (Swin-T, auto-downloaded) |
| `run_trellis.sh` | picks an interpreter, forwards to `trellis_launcher.py` |
| `run_grounding_dino.sh` | picks an interpreter, forwards to `grounding_dino_launcher.py` |

## Use

```bash
# image(s) -> GLB(s); model auto-downloads into ../weights on first run
./run_trellis.sh -i ../../run/<scan>/object_init/object_refs/<scan>/Table0/reference_1024.png \
                 -o ../../run/<scan>/reconstruct/Table0.glb

# batch a whole folder of references
./run_trellis.sh -i some_refs_dir/ -o out_dir/ --seed 7 --decimation 50000

# open-vocab detection
./run_grounding_dino.sh -i frame.jpg -p "a chair . a table . a lamp" -o boxes.json
```

`object_init` calls `trellis_launcher.py` for you — see
[`litereality_agent/pipeline/object_init/reconstruct.py`](../../litereality_agent/pipeline/object_init/reconstruct.py)
and `python -m litereality_agent.pipeline.object_init.run --scan <scan> --reconstruct`.

## Interpreter

The launchers need the heavy TRELLIS.2 runtime (torch 2.6+cu124, `o_voxel`, `natten`).
The wrappers resolve, in order:

```
$LITEREALITY_TRELLIS_PYTHON  ->  <repo>/.venv/bin/python  ->  python3 on PATH
```

Set `LITEREALITY_TRELLIS_PYTHON` to point at whichever env has the runtime. See
[`docs/installation.md`](../../docs/installation.md) for building it
(`TRELLIS.2/setup.sh` installs `o_voxel` / `flash-attn` / etc.; GroundingDINO needs
`pip install -e backends/GroundingDINO` to build its C++ op).

## Two upstream quirks handled here (no clone edits)

1. **RMBG-2.0 is gated.** `trellis_launcher.py` defaults to `--skip-rembg`, monkeypatching
   a no-op matter that treats the near-black background as transparent. `object_init`
   references are already object-only on black, so no matting is needed. Pass
   `--no-skip-rembg` to force the real model (needs HF access).
2. **flex-gemm autotune cache** defaults to `~/.flex_gemm`, often a broken symlink;
   `_env.py` redirects it under `../weights/.flex_gemm/`.
