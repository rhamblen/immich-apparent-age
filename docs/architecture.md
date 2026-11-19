# Architecture

## Design principles

- **Immich is read-mostly.** Phases 1–4 only ever issue GETs and search POSTs. The single write path (tag write-back) is optional, namespaced and reversible, and arrives last. Immich's Postgres database is never touched directly: schema changes between releases, and a sidecar that reaches into it becomes an upgrade blocker.
- **The sidecar owns derived data.** Everything this project computes lives in its own SQLite file. Immich stays the source of truth for photographs, faces and people; the sidecar is the source of truth for apparent ages and residuals.
- **Ground truth and estimates never mix.** `true_age` comes from arithmetic on dates. `apparent_age` comes from a model. They live in separate tables, and no code path lets the model see the former. This is the whole experiment, so it is enforced structurally rather than by discipline.
- **Re-runnable and idempotent.** Every row is keyed so that a re-run updates in place, and a resumed run skips completed work. The expensive crawl is survivable; a model swap is cheap.
- **Versioned predictions.** Predictions carry the model name and version. A second model adds rows; it never overwrites the first. Cross-model agreement is the project's main internal check.
- **Method in the repo, identities in config.** This repo is public. The person-to-birth-date mapping, the host address and the API key live only in the gitignored `config.yaml`, and reports refer to people by configured labels.
- **Uncertainty travels with every number.** n and a confidence interval are part of a result, not an optional extra. Anything below the configured minimum sample is reported as insufficient rather than as a finding.

## Topology

```
┌─────────────────────────┐
│  Immich server          │   REST, API key, read-only
│  (+ immich-machine-     │   detection + clustering already done here
│   learning container)   │
└───────────┬─────────────┘
            │  GET /api/people                  → person ids
            │  POST /api/search/metadata        → assets for those people
            │  GET /api/faces?id={assetId}      → bounding boxes + owning person
            │  GET /api/assets/{id}/thumbnail   → pixels
            ▼
┌─────────────────────────┐
│  extract.py             │  crop · quality-gate · true_age from dates
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│  SQLite                 │  faces · predictions · people · runs
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│  estimate.py            │  apparent-age model, batched, local
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐
│  analyse.py             │  calibration · residuals · pairs · trajectories
└───────────┬─────────────┘
            ▼
┌─────────────────────────┐      ┌──────────────────────────────┐
│  reports/index.html     │      │  writeback.py  (phase 5,     │
│                         │      │  optional) → POST /api/tags  │
└─────────────────────────┘      └──────────────────────────────┘
```

## Data sources

| Endpoint | Used for | Notes |
|---|---|---|
| `GET /api/people` | Person ids, names, and whether `birthDate` is set | Envelope is `{people, total, hidden, hasNextPage?}`; `page`/`size`, size default 500, max 1000. Only people with a birth date can yield a residual. |
| `POST /api/search/metadata` | Assets containing a given person | Filter with `filter.personIds.any`; page with `cursor`/`nextCursor`. Returns `localDateTime`, which is the date used for true age. |
| `GET /api/faces?id={assetId}` | `AssetFaceResponseDto[]` — `boundingBoxX1..Y2`, `imageWidth`, `imageHeight`, `person`, `sourceType` | The face boxes, and the reason no detector is needed. See ADR 0004. |
| `GET /api/assets/{id}/thumbnail` | Pixels to crop | `size` is an AssetMediaSize: `thumbnail`, `preview`, `fullsize`. Must match the frame the boxes were computed against. |
| `GET /api/assets/{id}/original` | Pixels at full resolution | Only where a crop would otherwise fall below the size gate. |
| `POST /api/tags`, `PUT /api/tags/{id}/assets` | Phase 5 write-back | The only writes in the project. |

Auth is the `x-api-key` header. Field shapes above were verified against the Immich OpenAPI spec (info.version 3.4.0-rc.0) on 2026-11-19.

**Gotcha.** Face boxes are **not** on the asset. `GET /api/assets/{id}` returns `people[]` as `PersonResponseDto`, which has no `faces` field — the boxes come from the separate `GET /api/faces` endpoint above. The spec labels that endpoint's `id` parameter a "Face ID" while describing it as returning an asset's faces; an asset id is the reading the Immich web client uses, and `extract.py --probe` verifies it against the live server.

**Gotcha.** Both the obvious search parameters are deprecated. Top-level `personIds` is deprecated since v3.2.0 in favour of `filter.personIds`, and `page` in favour of `cursor`/`nextCursor`. The client prefers the modern shape and falls back automatically if a server rejects it.

**Gotcha.** Bounding boxes are expressed against a specific rendition and carry their own `imageWidth`/`imageHeight`. Scale by the ratio of actual image dimensions to those values before cropping — do not assume the original's dimensions.

**Gotcha.** Faces are bound to a person by the `person.id` on each face record. An unassigned face has `person: null`, so filtering by person id is both the identity check and the filter.

## Schema sketch

```sql
-- One row per configured person. Birth dates come from config, not from git.
people (
  person_id     TEXT PRIMARY KEY,   -- Immich person UUID
  label         TEXT NOT NULL,       -- report-safe label
  birth_date    DATE NOT NULL
);

-- One row per detected face of a configured person. Ground truth only.
faces (
  face_id       TEXT PRIMARY KEY,   -- Immich face UUID
  asset_id      TEXT NOT NULL,
  person_id     TEXT NOT NULL REFERENCES people,
  taken_at      DATETIME NOT NULL,  -- asset localDateTime
  true_age      REAL NOT NULL,      -- years, from taken_at - birth_date
  crop_px       INTEGER NOT NULL,   -- shorter edge of the crop
  blur_var      REAL,               -- Laplacian variance
  yaw_deg       REAL,               -- if available
  passes_gate   INTEGER NOT NULL,   -- 0/1, recomputable without re-extracting
  crop_path     TEXT,
  UNIQUE (asset_id, face_id)
);

-- One row per (face, model). Estimates only; the model never sees true_age.
predictions (
  face_id       TEXT NOT NULL REFERENCES faces,
  model_name    TEXT NOT NULL,
  model_version TEXT NOT NULL,
  apparent_age  REAL NOT NULL,
  inferred_at   DATETIME NOT NULL,
  PRIMARY KEY (face_id, model_name, model_version)
);

-- Provenance for every pass, so a result can be traced to the code that made it.
runs (
  run_id        TEXT PRIMARY KEY,
  phase         TEXT NOT NULL,
  started_at    DATETIME NOT NULL,
  finished_at   DATETIME,
  git_sha       TEXT,
  config_hash   TEXT,
  notes         TEXT
);
```

Residuals are a view, not a table: they are cheap to recompute and they change whenever the calibration does.

## Key trade-offs

| Decision | Alternative | Why this way |
|---|---|---|
| Reuse Immich's face boxes | Run our own detector | Immich has already detected and, crucially, *identified* every face. Re-detecting would mean re-solving identity too. ADR 0004. |
| Local model | Cloud vision API | No per-image cost on a six-figure library, no coarse age brackets, and no family photographs leaving the house. ADR 0002. |
| Apparent-age training data | Chronological-age training data | Perceived age is the question being asked. ADR 0003. |
| SQLite sidecar | Write into Immich | Immich has no per-face metadata field, and its schema is not a public interface. ADR 0007. |
| Crops cached to disk | Crop on the fly each pass | Extraction is the slow phase; caching makes model swaps cheap. Crops are gitignored and regenerable. |
| Quality gate as a stored flag | Filter during extraction | Thresholds will need tuning, and re-gating must not mean re-crawling. ADR 0008. |
| Same-photo comparisons as the headline | Cross-photo averages as the headline | Identical camera, lighting and moment removes the confounds that would otherwise dominate. ADR 0006. |

## Operational notes

- **Be kind to the ML container.** Concurrency is capped in config. A full crawl should be runnable overnight without disturbing normal Immich use.
- **Scale.** Roughly 150k assets and ~10k person clusters in the target library, but only configured people are crawled, so the working set is a small fraction of that.
- **Secrets.** The API key is read from the environment where possible. Nothing in `out/`, `crops/`, `reports/` or `models/` is committed.
