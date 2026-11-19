# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Build phases map loosely to minor versions (Phase 1 → v0.1.0).

## [Unreleased]

Phase 1 (Extract) — code complete and unit-tested offline, **not yet run against a live
Immich server**, so no extraction figures exist yet.

### Added

- `immich_apparent_age/` — `config` (loading, validation, `${ENV}` expansion, exact
  `age_at()` ground truth), `immich` (read-only REST client with retry/backoff, people and
  asset paging, face boxes, image fetch, and a `probe()` that checks the live server against
  every assumption), `db` (SQLite schema, idempotent upserts, resume support, re-gating,
  run provenance with git SHA), `quality` (rendition-aware box scaling, margin cropping,
  size-normalised sharpness measurement, gating).
- `extract.py` — Phase 1 entry point, with `--probe`, `--discover-people`, `--dry-run`,
  `--limit`, `--person`, `--regate` and resume-by-default.
- `verify.py` — age-stratified contact sheets for human verification of identity and
  orientation, plus a coverage report covering faces per person per decade, same-photo pair
  counts, and a breakdown of why faces were gated out.
- `tests/test_pipeline.py` — 19 offline tests (box scaling, gating, blur normalisation,
  config validation, database round-trip and re-gating). No Immich required.
- `requirements.txt` — Phase 1 only; the model runtime is deliberately deferred to Phase 2.

### Fixed

- **Face bounding boxes do not live on the asset.** The Phase 0 docs claimed
  `GET /api/assets/{id}` returns `people[].faces[]` and that the Immich MCP server was
  trimming it. Neither was true: `people[]` is `PersonResponseDto` and has no `faces` field
  at all. Boxes come from `GET /api/faces?id={assetId}`. Corrected in ADR 0004,
  `architecture.md`, `inventory.md` (gotcha 1) and `ai-context.md`. Verified against the
  Immich OpenAPI spec, info.version 3.4.0-rc.0.
- Recorded that the obvious search parameters are deprecated — top-level `personIds` since
  v3.2.0 in favour of `filter.personIds`, and `page` in favour of `cursor`/`nextCursor`. The
  client prefers the modern shape and falls back automatically.

### Notes

- Open decision 2 is settled: a 16 GB RTX 5070 Ti is available, so Phase 2 plans for MiVOLO
  across the whole library rather than a sample.

## [0.0.1] — 2026-11-19

Phase 0 — proposal and design. Documentation only; no runnable code.

### Added

- `README.md` — the case for the project, the residual metric, the Immich data flow, and the two
  methodological traps that would otherwise invalidate the results.
- `docs/project-plan.md` — six-phase roadmap with objectives, deliverables, rationale and exit
  criteria per phase, a live status table, and the open decisions still to be made.
- `docs/architecture.md` — design principles, the read-only integration contract with Immich,
  the data flow, the SQLite schema, and the key trade-offs.
- `docs/ai-context.md` — cold-start orientation map for a future AI session.
- `docs/inventory.md` — the starting-state facts the build assumes, measured against the live
  Immich instance on 2026-11-19.
- `docs/decisions/0001`–`0008` — ADRs covering the goal reframing, model sourcing, the rejection
  of cloud vision APIs, reuse of Immich's face boxes, regression-to-the-mean correction,
  same-photo comparison, the sidecar store, and quality gating.
- `config.example.yaml` — configuration template. Host, API key, and the person → birth date
  mapping live only in the gitignored `config.yaml`.
- MIT `LICENSE` and `.gitignore` covering config, derived data, crops and model weights.

### Notes

- Identities, birth dates and the Immich host address are deliberately absent from this repo,
  which is public. Reports refer to people by configured labels.
