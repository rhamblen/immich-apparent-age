# AI context — cold-start orientation

Dense, factual orientation for a future AI session picking this project up cold. Not for end users. Read this first, then [`project-plan.md`](project-plan.md) for where the work stands and [`decisions/`](decisions/) for why anything is the way it is.

## What this repo is

A sidecar for an [Immich](https://immich.app) photo library that measures **apparent age minus chronological age** for faces of people whose birth dates are known. The output is the residual, not the age. Immich already knows everyone's real age on every photo; the point is the gap.

**The project is in Phase 1.** What exists: `extract.py`, `verify.py`, the `immich_apparent_age` package (`config`, `immich`, `db`, `quality`), `tests/test_pipeline.py` (19 offline tests, all passing, no Immich needed), a two-target `Dockerfile`, the `deploy/` compose stacks, and CI that tests and publishes the CPU image to GHCR. What does not: `estimate.py`, `analyse.py` and `writeback.py` are planned, not written, so the `:gpu` image is defined but not built by CI.

**No extraction has been run against the live server yet.** The code has never made a real Immich request, so nothing in the database and no coverage figure exists. `extract.py --probe` is the first thing to run once an API key is available, and until it passes, treat the client's assumptions as unverified.

## How to work here

- **Follow the phased-repo doc conventions** in the user's global `CLAUDE.md`: README leads with what and why; `docs/project-plan.md` holds the phased roadmap with a live status table; `docs/decisions/NNNN-title.md` holds ADRs (Status, Date, Context, Decision, Consequences); `docs/phases/` gets one build log per completed phase; `CHANGELOG.md` is Keep a Changelog plus SemVer and is updated **every phase**; phases map loosely to minor versions (Phase 1 → v0.1.0).
- **Every significant choice gets an ADR.** The repo is the source of truth for intent and rationale. If a decision is made in conversation and not written down, it is lost.
- **Update the status table** in `project-plan.md` when a phase changes state, and move the question out of **Open decisions** when it is settled (into an ADR).
- **This repo is public.** Never commit a name, a birth date, the Immich host address, an API key, or a face crop. Identities live in the gitignored `config.yaml`; reports use configured labels. Examples use placeholder UUIDs and dates.
- **Releases only when explicitly asked**, per the global release procedure. `gh` 2.95.0 is installed and authenticated, so the REST-API fallback in the global instructions is not needed here.

## Environment

| Thing | Value |
|---|---|
| Local working folder | `C:\Users\richa\face age recognition` (note the spaces; quote paths) |
| Remote | `https://github.com/rhamblen/immich-apparent-age` — public, default branch `main` |
| Platform | Windows 11, PowerShell primary, Git Bash available |
| Immich | v3.4.1, LAN host, facial recognition enabled — see [`inventory.md`](inventory.md) |
| Immich auth | API key, read-only for phases 1–4; from env `IMMICH_API_KEY` |
| Config | `config.yaml`, gitignored; template at `config.example.yaml` |
| Deployment | Published image `ghcr.io/rhamblen/immich-apparent-age`; compose in `deploy/`; host specifics in gitignored `deploy/.env`. See [`deployment.md`](deployment.md) |
| Hosts | Three Unraid servers, four GPUs. Immich and a 12 GB card on the storage host; a 20 GB Ada card on a second host; two 24 GB cards on a third. Capacity is contended and changes hourly — see [`inventory.md`](inventory.md) |

## The method in six lines

1. Ground truth: `true_age = asset.localDateTime − person.birthDate`. Exact, free, no model.
2. Estimate: an apparent-age model reads the face crop and guesses, never seeing the true age.
3. Raw residual: `apparent − true`. **Not reportable on its own** — see point 4.
4. Age models compress toward their training mean, so raw residuals make every older person look young and every teenager look old. Score against the model's own expectation at that age instead, then z-score by the residual spread at that age (ADR 0005).
5. Average over many photos per person: single-photo apparent age is ±5 years, dominated by lighting, lens and expression. Noise falls as roughly 1/√n (ADR 0001).
6. Trust the **same-photo** comparisons most: two configured people in one frame share camera, lighting, compression and moment (ADR 0006).

## Non-obvious constraints

- **Use an apparent-age model, not a chronological one.** IMDB-WIKI / UTKFace-trained models (including DeepFace's age head) regress toward metadata ages; ChaLearn LAP / APPA-REAL-trained models predict human-perceived age, which is the actual question (ADR 0003).
- **Cloud vision APIs are rejected**, not merely unused: coarse `AgeRange` buckets are unusable for a residual, cost scales with a six-figure asset count, and family faces would leave the house (ADR 0002).
- **Never run a face detector here.** Immich has already detected *and identified* every face; re-detecting would mean re-solving identity. Take the bounding boxes (ADR 0004).
- **Never write to Immich's Postgres.** The only sanctioned write is optional, namespaced tag write-back in Phase 5 (ADR 0007).
- **Face boxes are not on the asset.** `GET /api/assets/{id}` has no `faces` field anywhere in it. They come from `GET /api/faces?id={assetId}`, which the MCP does not expose — so Phase 1 uses the REST API with an API key. See `inventory.md` gotcha 1 for the correction, and ADR 0004.
- **The obvious search parameters are deprecated.** Use `filter.personIds.any` rather than top-level `personIds`, and `cursor`/`nextCursor` rather than `page`. The client in `immich_apparent_age/immich.py` falls back automatically.
- **Run `python extract.py --probe` before trusting a crawl.** It checks the live server against every assumption the client makes, including the one real ambiguity in the spec (whether `/api/faces?id=` wants an asset id).
- **Bounding boxes are rendition-relative** — scale by `imageWidth`/`imageHeight` from the face record, not the original asset dimensions. See `inventory.md` gotcha 3.
- **Quality gating is a stored flag**, not an extraction-time filter, so thresholds can be retuned without re-crawling (ADR 0008).
- **Watch for pseudo-replication.** Bursts and near-duplicates can inflate n for one person and manufacture significance. Open decision 5.
- **Phase 1 needs no GPU.** Extraction is network- and disk-bound; only Phase 2 touches a GPU. Do not put a CUDA runtime in the path of extraction (ADR 0009).
- **Never pin `NVIDIA_VISIBLE_DEVICES=all`.** These hosts have several GPUs and the others may be fully committed. Pin a UUID.
- **Crop caching is load-bearing twice.** ADR 0008 cached crops so thresholds could be retuned without re-crawling; ADR 0009 then relies on that cache as the handoff that lets Phase 2 run on a different machine.

## Build phases

| Phase | Name | State | Version |
|---|---|---|---|
| 0 | Proposal and design | ☑ done | v0.0.1 |
| 1 | Extract — faces and ground truth | ◐ code written and unit-tested; not yet run live | v0.1.0 |
| 2 | Estimate — apparent age | ☐ | v0.2.0 |
| 3 | Calibrate and analyse | ☐ | v0.3.0 |
| 4 | Report | ☐ | v0.4.0 |
| 5 | Write-back to Immich (optional) | ☐ | v0.5.0 |

## Where the arguments are

Open questions that are deliberately unresolved are listed at the foot of [`project-plan.md`](project-plan.md): model choice and whether to run two, GPU availability, how to treat scanned photographs, whether unnamed clusters have any role, pseudo-replication, and video frames. Resolve them with an ADR, not a code comment.

## Tone of the output

This is a family curiosity. The reports should carry n and uncertainty on every claim, state plainly that camera era and lighting are part of the signal, and never present a single photograph as evidence about a person.
