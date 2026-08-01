# TRELLIS RunPod serverless worker (on-demand, no GPU rental)

On-demand TRELLIS: a RunPod **serverless** endpoint (scales to **zero** when idle — you pay
per-second only while a job runs, never rent a GPU). The pipeline calls it over HTTP and runs
many assets in parallel. Client: `models/runpod_trellis.py`.


> **Cold start dominates a typical run.** Scale-to-zero means every scan that starts after the
> endpoint has been idle pays for the worker to boot: ~233 s of image pull + volume mount +
> weight load, against ~23 s of actual generation per asset. It is not a first-run-only cost.
> Set **active workers ≥ 1** (or a longer idle timeout) while working; see issue #1.

**Packaging = thin image + network volume.** The finicky TRELLIS env is NOT baked into the image
— it lives on a RunPod **network volume** (your exact `trellis2` env + the TRELLIS repo +
weights). The image is tiny and just launches the volume's python, so the worker behaves
identically to local with no Docker-dep pain.

```
/runpod-volume/                       (network volume, provisioned once)
  trellis2-env/   conda-packed trellis2 env (python+torch+o_voxel+natten+flash-attn+runpod)
  TRELLIS/        the TRELLIS repo (code)
  hf-cache/       model weights (HF_HOME)
image: nvidia/cuda + handler.py  →  CMD runs /runpod-volume/trellis2-env/bin/python handler.py
```

## I/O contract (keep in sync with the client)
```
input  = {"image_b64": str, "seed": 42, "decimation": 50000, "texture_size": 1024}
output = {"glb_b64": str}        # or {"glb_url": ...} for large assets
         {"error": str}          # on failure
```

## Deploy (one-time)

**1. Provision the volume from your working env.** On the machine with the `trellis2` conda env:
```bash
bash worker/trellis/provision_volume.sh pack trellis2 /path/to/TRELLIS
# → /tmp/trellis2-env.tar.gz + /tmp/TRELLIS.tar.gz
```
Create a **Network Volume** in the RunPod console, attach it to any cheap temp pod, copy the two
tarballs there (`scp` or `runpodctl send`), then on that pod:
```bash
bash worker/trellis/provision_volume.sh unpack    # unpacks into /runpod-volume + caches weights
```
Tear the temp pod down. The volume now holds everything.

**2. Build + push the THIN image** (fast, nothing finicky compiled):
```bash
docker build -t <user>/trellis-runpod:latest worker/trellis
docker push  <user>/trellis-runpod:latest
```

**3. Create the serverless endpoint** (console → Serverless → New Endpoint):
- Container image: `<user>/trellis-runpod:latest`
- **Attach the network volume** (mounts at `/runpod-volume`)
- GPU: 24 GB+ (Ampere)
- **Min Workers = 0** (true on-demand), **Max Workers = N** (your desired parallelism)
- Copy the **endpoint id**.

**4. Point the client at it** (gitignored `.env`):
```
RUNPOD_API_KEY=rpa_...                 # already moved here from the template
RUNPOD_TRELLIS_ENDPOINT=<endpoint id>
```

## On-demand vs latency
Min Workers = 0 means each cold job pays model-load (~tens of s) + first-mount. For batch
reconstruction that's fine. Set Min Workers = 1 only if you need low latency (costs more, less
"pure on-demand"). Max Workers caps parallelism; the client's `max_parallel` should be ≤ that.

## Parallelism
`RunPodTrellisService(max_parallel=N).reconstruct_many({asset_id: image, ...}, out_dir=...)`
submits up to N jobs concurrently; RunPod scales workers to match, then back to zero.
