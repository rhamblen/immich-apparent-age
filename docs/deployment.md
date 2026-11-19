# Deployment

Runs as a published container image, pulled from the GitHub Container Registry. Nothing is built by hand on a server. The reasoning is in [ADR 0009](decisions/0009-containerised-deployment.md).

Host addresses, GPU ids and the API key live in `deploy/.env`, which is gitignored - this repo is public, so no real address or identifier appears in any committed file.

## Which host runs what

| Stage | Needs | Where it belongs |
|---|---|---|
| **1 · extract** | Network and disk. **No GPU.** | The host that runs Immich. It fetches one preview per asset across ~150,000 assets; keeping that on the local bridge rather than the LAN is the biggest saving available. |
| **3 · calibrate**, **4 · report** | A little CPU, seconds to minutes | Anywhere. Same CPU image. |
| **2 · estimate** | A GPU with roughly 4 GB free | Whichever card actually has room. Pinned by UUID in `deploy/.env`, so moving it is a one-line change and no rebuild. |

Phase 2 reads the crops phase 1 cached to disk and never contacts Immich, which is what allows the two to sit on different hosts. The `/data` mount is the handoff.

**Choosing the GPU.** Check before a run, because this changes:

```bash
nvidia-smi --query-gpu=index,uuid,name,memory.used,memory.total,utilization.gpu --format=csv
```

Prefer a card that is genuinely idle. Note that a Stable Diffusion or ComfyUI instance can hold most of a card's VRAM while reporting 0% utilisation - idle is not the same as free. Pin the UUID rather than `all`: these hosts have more than one GPU, and the others may be fully committed.

## Images

| Tag | Target | Contains | Size |
|---|---|---|---|
| `:latest`, `:sha-xxxxxxx` | `base` | Python, httpx, Pillow, numpy | ~150 MB |
| `:gpu` | `gpu` | the above plus CUDA 12.8 runtime and torch | several GB |

CI builds and publishes `base` on every push to `main`, after the test suite passes, and smoke-tests the published image by running the tests inside it. The `gpu` target is defined but not built in CI until `estimate.py` exists.

CUDA 12.8 covers Blackwell (sm_120), Ada (sm_89) and Ampere (sm_86), so the GPU choice stays open.

## First run

On the Immich host:

```bash
mkdir -p /mnt/user/appdata/immich-apparent-age
cd /mnt/user/appdata/immich-apparent-age
```

Put `config.yaml` there - start from [`config.example.yaml`](../config.example.yaml). The container reads `/data/config.yaml`, and `out/`, `crops/`, `reports/` and `models/` are created alongside it.

Then, from a checkout of this repo:

```bash
cp deploy/.env.example deploy/.env    # then edit: data dir, API key, TZ
cd deploy
```

Verify the server before trusting a crawl. This checks every assumption the client makes, including the one genuine ambiguity in the Immich API:

```bash
docker compose run --rm iaa extract.py --config /data/config.yaml --probe
```

Find everyone who can contribute a residual:

```bash
docker compose run --rm iaa extract.py --config /data/config.yaml --discover-people
```

Sample twenty assets per person without writing anything:

```bash
docker compose run --rm iaa extract.py --config /data/config.yaml --limit 20 --dry-run -v
```

Then the real extraction. This is the long one; it is resumable, so interrupting it is safe:

```bash
docker compose run --rm iaa extract.py --config /data/config.yaml
```

Contact sheets and the coverage report:

```bash
docker compose run --rm iaa verify.py --config /data/config.yaml
```

Look at the contact sheets in `reports/contact-sheets/` before going any further. Every face should be the right person, upright, and roughly the age printed beneath it. A mis-assigned face produces a confidently wrong residual, because the true age will be the wrong person's.

## Phase 2, when it exists

If the GPU host is not the Immich host, `/data` has to be reachable from both. On Unraid that means mounting the Immich host's share on the GPU host (Settings → Remote Shares, or Unassigned Devices), and pointing `IAA_DATA_DIR` at the mount. This shared mount is the main cost of splitting the stages, and the alternative is simply to run both on the Immich host's own card at a smaller batch size.

The GPU host also needs the **Unraid Nvidia Driver** plugin, which is what provides `--runtime=nvidia`.

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml \
    run --rm iaa estimate.py --config /data/config.yaml
```

## Operational notes

- **Pin the image for a long crawl.** `IAA_IMAGE=ghcr.io/rhamblen/immich-apparent-age:sha-xxxxxxx`, so an image update cannot change results midway through.
- **Stop it whenever you need the hardware.** Extraction is idempotent and keyed on face id, so a restart resumes and loses nothing but the asset in flight. That is what makes running on contended GPUs acceptable.
- **Be kind to the Immich ML container.** `immich.max_concurrency` in `config.yaml` caps request concurrency; the default is deliberately low so a crawl can run overnight without disturbing normal use.
- **Nothing is written to Immich** in phases 1 to 4. The only write in the project is the optional tag write-back in phase 5.
- **Crops contain faces.** `/data` holds them, and they are regenerable. Keep it on appdata, not in a shared or published location.
