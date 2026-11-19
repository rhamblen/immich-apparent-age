# AI context — cold-start orientation

Dense, factual orientation for a future AI session picking this project up cold. Not for end users. Read this first, then [`project-plan.md`](project-plan.md) for where the work stands and [`decisions/`](decisions/) for why anything is the way it is.

## What this repo is

A sidecar for an [Immich](https://immich.app) photo library that measures **apparent age minus chronological age** for faces of people whose birth dates are known. The output is the residual, not the age. Immich already knows everyone's real age on every photo; the point is the gap.

**The project is at Phase 0: documentation only. There is no code yet.** Do not describe any script in this repo as existing. `extract.py`, `estimate.py`, `analyse.py` and `writeback.py` are planned, not written.

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
- **The MCP server trims `faces[]`** out of asset detail. Talk to the REST API for bounding boxes. See `inventory.md` gotcha 1.
- **Bounding boxes are rendition-relative** — scale by `imageWidth`/`imageHeight` from the face record, not the original asset dimensions. See `inventory.md` gotcha 3.
- **Quality gating is a stored flag**, not an extraction-time filter, so thresholds can be retuned without re-crawling (ADR 0008).
- **Watch for pseudo-replication.** Bursts and near-duplicates can inflate n for one person and manufacture significance. Open decision 5.

## Build phases

| Phase | Name | State | Version |
|---|---|---|---|
| 0 | Proposal and design | ☑ done | v0.0.1 |
| 1 | Extract — faces and ground truth | ☐ | v0.1.0 |
| 2 | Estimate — apparent age | ☐ | v0.2.0 |
| 3 | Calibrate and analyse | ☐ | v0.3.0 |
| 4 | Report | ☐ | v0.4.0 |
| 5 | Write-back to Immich (optional) | ☐ | v0.5.0 |

## Where the arguments are

Open questions that are deliberately unresolved are listed at the foot of [`project-plan.md`](project-plan.md): model choice and whether to run two, GPU availability, how to treat scanned photographs, whether unnamed clusters have any role, pseudo-replication, and video frames. Resolve them with an ADR, not a code comment.

## Tone of the output

This is a family curiosity. The reports should carry n and uncertainty on every claim, state plainly that camera era and lighting are part of the signal, and never present a single photograph as evidence about a person.
