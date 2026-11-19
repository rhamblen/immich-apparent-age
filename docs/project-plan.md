# Project plan

## Status

| Phase | Name | State |
|---|---|---|
| 0 | Proposal and design | ☑ done |
| 1 | Extract — faces and ground truth | ◐ in progress — code written and unit-tested, not yet run against the server |
| 2 | Estimate — apparent age | ☐ not started |
| 3 | Calibrate and analyse | ☐ not started |
| 4 | Report | ☐ not started |
| 5 | Write-back to Immich *(optional)* | ☐ not started |

☐ not started · ◐ in progress · ☑ done

---

## Phase 0 — Proposal and design

**Objective.** Write down why this is worth building, how it will work, and how it integrates — before any code exists, so the reasoning survives.

**What we build.** This repository: README, phased plan, architecture, ADRs, inventory, config template, licence.

**Prerequisites.** A reachable Immich instance with facial recognition enabled.

**Deliverables.** Public repo at `rhamblen/immich-apparent-age`, eight ADRs, `config.example.yaml`.

**Why.** The method has two failure modes that look like success — a chronological-age model mistaken for an apparent-age model, and uncorrected regression to the mean — and both are far cheaper to design out now than to discover in the results. Writing the rationale down first is also what makes the eventual numbers defensible rather than merely interesting.

**Exit criteria.** Repo pushed; every design decision made so far has an ADR; a cold reader can tell what is being measured and why.

---

## Phase 1 — Extract: faces and ground truth

**Objective.** Get every usable face of every known-birth-date person out of Immich and into a local database, with its true age at the moment of the photograph.

**What we build.** `extract.py` — walks `POST /api/search/metadata` for the configured people, reads `people[].faces[]` from each asset, computes `true_age = asset_local_date − birth_date`, crops from the rendition the boxes were computed against, scores crop quality, and writes one row per face.

**Prerequisites.** Immich API key with read access; `config.yaml` with person ids and birth dates; birth dates set in Immich for the people who matter, since Immich's own age display is the cross-check. Runs from the published CPU image on the host running Immich — no GPU is involved in this phase at all. See [`deployment.md`](deployment.md).

**Deliverables.** Populated `faces` table; a contact sheet of sampled crops for eyeballing; a coverage report of faces per person per decade.

**Why.** Ground truth and image data are the expensive, slow part, and they do not change when the model does. Separating extraction from estimation means a model swap costs minutes rather than another full library crawl. The coverage report also decides whether the project is viable at all: a person with twenty usable faces cannot support a conclusion.

**Exit criteria.** Faces extracted for all configured people; sampled crops verified to contain the right person, right way up; coverage report shows at least one matched pair of people with 50 or more usable faces each.

---

## Phase 2 — Estimate: apparent age

**Objective.** Attach an apparent age to every gated face, from a model that has never seen the true answer.

**What we build.** `estimate.py` — batched inference over the stored crops, writing `apparent_age` plus the model name and version alongside each face. Idempotent and resumable; re-running with a new model adds rows rather than overwriting them.

**Prerequisites.** Phase 1 complete; model weights fetched into `models/`; the `:gpu` image built, and a GPU with roughly 4 GB free pinned by UUID in `deploy/.env`. This phase reads cached crops and never contacts Immich, so it can run on a different host from extraction — see [ADR 0009](decisions/0009-containerised-deployment.md) and open decision 7.

**Deliverables.** `predictions` table keyed on (face, model version); a runtime and throughput note for the phase log.

**Why.** Keeping predictions in their own table, versioned by model, is what allows a second model to be run as a cross-check. Agreement between two independently trained models is the cheapest available evidence that a residual is real rather than an artefact of one model's quirks.

**Exit criteria.** Every gated face has an apparent age from at least one model; a held-back sample shows error in the expected ±4–6 year band. If it does not, the model or the crop pipeline is wrong and no analysis should proceed.

---

## Phase 3 — Calibrate and analyse

**Objective.** Turn raw apparent ages into residuals that mean something.

**What we build.** `analyse.py` — fits predicted-against-true across all faces, derives the bias correction, computes per-face residual z-scores, aggregates per person with confidence intervals, extracts same-photo matched pairs, and fits each person's apparent-age-against-year trajectory.

**Prerequisites.** Phase 2 complete.

**Deliverables.** `residuals` view; a calibration plot; per-person summary table (n, mean residual, CI, z-score); matched-pair table; trajectory slopes.

**Why.** This is where the project either earns its conclusions or loses them. Raw `apparent − actual` is dominated by the model compressing toward its training mean, so it must be scored against the model's own expectation at that age (ADR 0005). Confidence intervals are not decoration: with n in the hundreds the standard error on a mean residual drops below a year, and that is what makes a two-to-three-year difference between two people reportable at all.

**Exit criteria.** Calibration curve fitted and plotted; every reported figure carries n and a confidence interval; at least one same-photo matched-pair comparison produced; conclusions suppressed automatically for anyone below `min_faces_per_person`.

---

## Phase 4 — Report

**Objective.** Make the results readable by people who have not read this repo.

**What we build.** A static HTML report: leaderboard of calibrated mean residuals with error bars; per-person trajectory chart (apparent age against photo year, with the slope called out); the same-photo head-to-head table; each person's youngest- and oldest-reading photographs.

**Prerequisites.** Phase 3 complete.

**Deliverables.** `reports/index.html` plus assets, self-contained and shareable.

**Why.** The trajectory slope is the most interesting output and the least obvious. A slope below 1.0 means a face is accumulating apparent years more slowly than real ones, which is a fundamentally different claim from a flat offset — and it is robust to someone simply having a youthful face, because each person acts as their own baseline.

**Exit criteria.** Report opens offline in a browser; every chart states n; no claim appears without its uncertainty; captions make clear what camera era can and cannot explain.

---

## Phase 5 — Write-back to Immich *(optional)*

**Objective.** Surface the results inside Immich itself.

**What we build.** `writeback.py` — creates a namespaced tag tree (`apparent-age/…`) via `POST /api/tags` and assigns tags per asset, with a dry-run mode and a clean removal path.

**Prerequisites.** Phase 4 complete; a deliberate decision that the tags are wanted.

**Deliverables.** Tags visible in the Immich UI; a documented undo.

**Why.** Tags make the results browsable where the photos already are. They are also the only write this project ever performs, which is why they come last, namespaced, optional and reversible. Immich tags are per-asset rather than per-face, so this is necessarily a coarsening of the data — the database stays the system of record (ADR 0007).

**Exit criteria.** Tags applied under a single removable namespace; dry run shown before any write; removal verified to leave the library as it was.

---

## Open decisions

| # | Question | Notes |
|---|---|---|
| 1 | MiVOLO or DEX apparent-age weights, or both as a cross-check? | MiVOLO is stronger and can use body context. Running both is the honest option; decide after the Phase 2 sanity check. |
| 7 | Which GPU host for Phase 2, and does `/data` get shared across hosts? | Deliberately left open: capacity changes hour to hour, so the card is pinned at runtime in `deploy/.env` ([ADR 0009](decisions/0009-containerised-deployment.md)). Current reading favours the idle 20 GB Ada card on the second host, which needs a remote mount for `/data`; the fallback is the Immich host's own 12 GB card at a smaller batch, which needs no mount but contends with a Stable Diffusion instance holding most of its VRAM. |
| ~~2~~ | ~~Is a GPU available for the estimation pass?~~ | **Settled 2026-11-19:** yes — an RTX 5070 Ti with 16 GB. MiVOLO is practical across the whole library rather than a sample, so Phase 2 plans for it as the primary model. |
| 3 | Scanned and pre-digital photographs: include or segregate? | They carry the most interesting age range and the worst confounds. Leaning towards extracting them but reporting them as a separate stratum. |
| 4 | Unnamed people clusters — any role? | No birth date means no residual, so they cannot contribute. Possible later use: apparent age as a sorting aid when naming clusters. |
| 5 | Multiple faces of one person in one asset (bursts, near-duplicates, mirrors) | Risks pseudo-replication inflating n. Likely fix: collapse to one face per person per asset, keeping the highest-quality crop. |
| 6 | Video frames | Excluded in Phase 1. Cheap to add later, but frame selection is its own problem. |
