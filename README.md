# immich-apparent-age

**Measures how old the faces in an [Immich](https://immich.app) library *look*, and compares that against how old they actually were.** Immich already knows everyone's real age on every photo; the interesting question is the gap between that and what an age-estimation model guesses — in other words, does someone look good for their age?

> Status: **Phase 0 — proposal and design.** No code yet. The rationale lives in [`docs/project-plan.md`](docs/project-plan.md), the method decisions in [`docs/decisions/`](docs/decisions/), and the Immich integration in [`docs/architecture.md`](docs/architecture.md).

## Why build this

Immich already solves the easy half. It detects faces, clusters them into people, and if you set a person's birth date it will show their exact age on every photo, computed from the asset date. That is ground truth, and no model can beat it.

What it cannot tell you is how old someone *appears*. That requires a second opinion from a model that has never been told the answer — and then the difference between the two numbers, the **residual**, is the quantity of interest:

```
residual = apparent_age (model) − chronological_age (birth date + photo date)
```

A persistently negative residual means a face reads younger than its years. Most projects that estimate age from photos have no ground truth to check themselves against. This one does, for every single face, which makes two otherwise impossible things possible:

- **Calibration** — the model's systematic bias can be measured on these exact faces and subtracted, instead of being hand-waved away.
- **Averaging** — a single photo's apparent age is worth very little (±5 years, driven as much by lighting and lens as by the face). Across hundreds of photos of the same person the noise falls off as roughly 1/√n, and the mean residual becomes a number worth arguing about over dinner.

## What it does, by phase

| Phase | What you get |
|---|---|
| **0 · Proposal** | This repo: the case for building it, the method, and the integration design. |
| **1 · Extract** | Every face of every known-birth-date person pulled from Immich into a local database, with its true age and a quality score. |
| **2 · Estimate** | An apparent age for each face from a model trained on *perceived* age, not chronological age. |
| **3 · Calibrate** | Bias correction, residual z-scores, per-person aggregates with confidence intervals, and same-photo matched pairs. |
| **4 · Report** | A leaderboard, an ageing-trajectory chart per person, the same-photo head-to-head table, and each person's youngest-reading photo. |
| **5 · Write-back** *(optional)* | Age-band tags pushed back into Immich so the results are browsable in the app. |

## How it reads a face

Immich hands over the face boxes, so this project never runs its own detector:

```
Immich REST API                     this project
───────────────                     ────────────
GET /api/people            ──▶  person ids (birth dates come from local config)
GET /api/search/metadata   ──▶  assets containing those people, with dates
GET /api/assets/{id}       ──▶  people[].faces[] → boundingBoxX1..Y2 + imageWidth/Height
GET /api/assets/{id}/thumbnail ─▶ pixels to crop from
                                      │
                                      ▼
                            crop ▶ quality gate ▶ apparent-age model
                                      │
                                      ▼
                            SQLite (one row per face, per model version)
                                      │
                                      ▼
                            calibrate ▶ residuals ▶ report
```

Immich is **read-only** throughout phases 1–4, and its database is never touched directly. See [ADR 0007](docs/decisions/0007-sidecar-sqlite-as-system-of-record.md).

## The two things that make or break the result

1. **The model must be trained on apparent age, not chronological age.** Models trained on IMDB-WIKI or UTKFace regress toward real age scraped from metadata, so their error is mostly noise. Models trained on ChaLearn LAP / APPA-REAL are trained on *human votes about how old someone looks*, which is the actual question. See [ADR 0003](docs/decisions/0003-apparent-age-trained-model.md).
2. **Regression to the mean will fake a result if left uncorrected.** Every age model hedges toward its training mean — too old for children, too young for the elderly. Raw `apparent − actual` therefore "proves" that everyone over 50 looks wonderful and every teenager looks rough. The fix is to score each face against the model's *own expectation at that age*. See [ADR 0005](docs/decisions/0005-correct-for-regression-to-the-mean.md).

And the design that removes almost every remaining confound: compare people **within the same photograph**, where camera, lighting, compression and moment are identical by construction. See [ADR 0006](docs/decisions/0006-same-photo-comparison-as-primary-design.md).

## Stack

| Piece | Choice | Why |
|---|---|---|
| Photo library | Immich (REST API + API key) | Already does detection, clustering and exact ages |
| Age model | MiVOLO, or DEX apparent-age weights | Trained/evaluated on APPA-REAL perceived age |
| Runtime | Python, ONNX Runtime or PyTorch | Local, no per-image cost, no faces leave the house |
| Store | SQLite | One row per (asset, face, model version); re-runnable |
| Reports | Static HTML + charts | Shareable without a server |

Cloud vision APIs were considered and rejected — see [ADR 0002](docs/decisions/0002-local-models-not-cloud-apis.md).

## Repo layout

```
.
├── README.md                  this file
├── CHANGELOG.md               Keep a Changelog + SemVer; updated every phase
├── config.example.yaml        copy to config.yaml (gitignored) and fill in
├── LICENSE                    MIT
└── docs/
    ├── project-plan.md        phased roadmap, status table, open decisions
    ├── architecture.md        principles, trade-offs, data flow, schema
    ├── ai-context.md          cold-start orientation for the next AI session
    ├── inventory.md           starting-state facts the build assumes
    ├── decisions/             ADRs — the durable "why"
    └── phases/                one build log per completed phase
```

## A note on what this measures

A residual is a statement about how a model trained on internet faces reads a photograph. Camera era, resolution, lighting, expression and grooming are all part of that signal — which is exactly why the same-photo comparisons are the ones to trust, and why single-photo results are not reported as findings. It is a family curiosity, not an assessment of anybody.

## Licence

[MIT](LICENSE).
