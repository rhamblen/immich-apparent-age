# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Build phases map loosely to minor versions (Phase 1 → v0.1.0).

## [Unreleased]

Nothing yet. Phase 1 (Extract) is the next work.

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
