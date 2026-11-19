# v0.1.0 — Phase 1: extraction, containerised

First release. Measures how old the faces in an [Immich](https://immich.app) library *look*, and compares that against how old they actually were.

Immich already knows everyone's exact age on every photo, from their birth date and the asset date. The point of this project is the **residual** — the gap between that and what an age-estimation model guesses:

```
residual = apparent_age (model) − chronological_age (birth date + photo date)
```

Having ground truth for every single face is unusual, and it is what makes two otherwise impossible things possible: calibrating the model's systematic bias on these exact faces, and averaging a hopelessly noisy per-image signal (±5 years) down to a usable per-person one across hundreds of photographs.

## What this release contains

**The extractor (phase 1).** Pulls every face of every known-birth-date person out of Immich into a local SQLite database, with its exact age at the moment of the photograph and a measured crop-quality score. Read-only against Immich, resumable, idempotent, and keyed on face id.

- `extract.py` — `--probe`, `--discover-people`, `--dry-run`, `--limit`, `--person`, `--regate`
- `verify.py` — age-stratified contact sheets for human verification, plus a coverage report covering faces per person per decade, same-photo pair counts, and why faces were gated out
- 19 offline tests, no Immich required

**A published container.** `ghcr.io/rhamblen/immich-apparent-age`, built and pushed by CI after the tests pass, then smoke-tested by running the suite inside the published image. Two targets: a ~150 MB CPU image for phases 1, 3 and 4, and a CUDA 12.8 image for phase 2 only. Compose stacks for Unraid Compose Manager in `deploy/`.

**The reasoning, written down.** Nine ADRs in `docs/decisions/`, a phased plan, an architecture note and a cold-start orientation map. The repo is the source of truth for intent, not just code.

## The two decisions that carry the method

Both are failure modes that would otherwise look like success.

**Use a model trained on apparent age, not chronological age** (ADR 0003). Models trained on IMDB-WIKI or UTKFace regress toward metadata ages, so their error is mostly noise. ChaLearn LAP and APPA-REAL models predict *human-perceived* age, which is the actual question being asked.

**Score residuals against the model's own expectation at that age** (ADR 0005). Every age model compresses toward its training mean — too old for children, too young for the elderly. A raw `apparent − actual` residual therefore "proves" that everyone over fifty looks wonderful and every teenager looks rough, with a magnitude several years larger than the real between-person differences being looked for. Worse, it grows *more* statistically significant with more data, because it is systematic. It has to be designed out, not averaged away.

And the design that removes confounds rather than correcting for them: **same-photo comparison** (ADR 0006). Two known people in one frame share camera, lens, lighting, compression and moment. Camera era otherwise correlates with the subject's real age, which makes cross-decade comparisons measure cameras.

## Known limitations

- **Nothing here has run against a live Immich server yet.** The test suite is comprehensive but offline. `extract.py --probe` exists precisely to verify the client's assumptions before a crawl, and should be the first thing run.
- One genuine ambiguity survives in the Immich API: `GET /api/faces` documents its `id` parameter as a face id while describing the endpoint as returning an *asset's* faces. An asset id is what the Immich web client sends, so that is what this does — and `--probe` checks it.
- Phase 2 (estimate), 3 (calibrate) and 4 (report) are planned and specified, not written. The `:gpu` image is defined but not built by CI until `estimate.py` lands.
- Apparent age is a property of a photograph, not only of a face. Lighting, resolution and expression are part of the signal, which is why single-photo results are not reported as findings.

## Getting started

See [`docs/deployment.md`](docs/deployment.md). In short: put `config.yaml` in the data directory, set `IAA_DATA_DIR` and `IMMICH_API_KEY` in `.env`, then `docker compose run --rm probe` before anything else.

**MIT licensed.**
