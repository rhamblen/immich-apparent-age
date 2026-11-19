# 0007 — A sidecar SQLite database is the system of record

**Status:** Accepted
**Date:** 2026-11-19

## Context

The results have to live somewhere. Three options were considered.

**Write into Immich's Postgres directly.** Rejected. The schema is internal and changes between releases, so a sidecar that reaches into it becomes an upgrade blocker and a corruption risk. It is also unsupported, which means any resulting breakage is self-inflicted and undiagnosable.

**Store results in Immich through its API.** Partially viable but insufficient. Immich has no per-face custom metadata field, and the unit of analysis here is the face: a single photograph can contain several people with different residuals. The available write targets are per-asset — tags, and the free-text `description` field. Tags can express a band (`apparent-age/reads-younger`), not a number with a confidence interval, and cannot distinguish two people in one frame.

**A local SQLite sidecar.** Fits the data model exactly: one row per face, several predictions per face keyed by model version, and provenance per run.

## Decision

A local SQLite database is the system of record for everything this project computes. Immich remains the source of truth for photographs, faces and people.

- **Immich is read-only** for phases 1 through 4.
- **Immich's database is never accessed directly** — only its REST API.
- **Ground truth and estimates live in separate tables** (`faces` and `predictions`) with no code path from a model to `true_age`. The separation is structural because it is the integrity of the whole experiment.
- **Predictions are keyed by model name and version**, so a second model adds rows rather than overwriting the first.
- **A `runs` table records git SHA and config hash** per pass, so any figure can be traced to the code and settings that produced it.
- **Residuals are a view, not a table.** They change whenever the calibration does, and are cheap to recompute.
- **Write-back to Immich is optional, last and reversible** (Phase 5): a namespaced tag tree with a dry-run mode and a documented removal path. It is a deliberate coarsening for browsability, never the record.

The database and cached crops are gitignored. They contain face data and are fully regenerable.

## Consequences

**Good.** Immich survives upgrades untouched. Model swaps and recalibration cost nothing and lose no history. The schema matches the question. Everything is reproducible and attributable to a commit.

**Bad.** Results are not visible in Immich by default — they live in a database and a generated report, which is a worse experience than seeing a number next to a photograph. Phase 5 exists to soften that, at the cost of granularity. The sidecar can also drift out of date as the library grows, so re-extraction is a periodic chore rather than something that happens automatically.

**Operationally.** A crawl of a 151,463-asset library is not instant, so extraction must be resumable and idempotent, keyed on `(asset_id, face_id)`.
