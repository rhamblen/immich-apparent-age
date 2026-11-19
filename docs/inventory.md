# Inventory — starting-state facts

Measured against the live Immich instance on **2026-11-19**, before any code was written. These are the facts the build assumes; re-measure before Phase 1 if significant time has passed.

The host address, API key and the person-to-birth-date mapping are deliberately not recorded here — this repo is public. They live in the gitignored `config.yaml`.

## Immich instance

| Fact | Value |
|---|---|
| Version | v3.4.1 |
| Host | LAN address, port 8080 (recorded in `config.yaml`) |
| Facial recognition | enabled |
| Smart search | enabled |
| OCR | enabled |
| Duplicate detection | enabled |
| Sidecar files | enabled |
| OAuth | disabled (password login) |

## Library scale

| Fact | Value |
|---|---|
| Images | 151,463 |
| Videos | 4,350 |
| Total assets | 155,813 |
| People — visible | 9,793 |
| People — hidden | 67 |
| People — total | 9,860 |

The overwhelming majority of those ~9,900 people are unnamed clusters. Only named people with a birth date set can contribute to this project, so the working set is a tiny fraction of the library.

## Ground-truth coverage

Of the first 25 people returned by `GET /api/people`, **8 had `birthDate` set** and 17 did not. Several of those with dates are useful by construction:

- Two adults born seven weeks apart in 1965 — a naturally matched pair, same age, same era of photographs, frequently in the same frame.
- Four individuals born in 2006, two of them sharing a birth date — a second matched set at the opposite end of the age range, which doubles as a check that the regression-to-the-mean correction is working (their corrected residuals should centre near zero too).

Implication for Phase 1: filling in the missing birth dates in Immich is the cheapest possible way to expand the sample, and it costs nothing but typing. Immich's own per-photo age display is also the free cross-check that the true-age arithmetic is right.

## API shape, as observed

- `GET /api/people` returns `id`, `name`, `birthDate`, `isHidden`, `thumbnailPath`, paginated with a `next` cursor, and reports visible/hidden totals.
- `GET /api/assets/{id}` returns `localDateTime`, `exifInfo.dateTimeOriginal`, `width`, `height` and a `people[]` array. For true age, `localDateTime` is the field to use.
- Asset listing and per-person asset queries are both served by `POST /api/search/metadata`.
- Tag endpoints exist for the optional Phase 5 write-back: `/api/tags`, `/api/tags/{id}/assets`.

Field-level shapes were subsequently verified against the Immich OpenAPI spec (info.version 3.4.0-rc.0) rather than inferred from responses; the result is in [`architecture.md`](architecture.md), and it corrected gotcha 1 below.

## Gotchas discovered during inventory

1. **Face boxes are on their own endpoint, not the asset.** *(Corrected 2026-11-19.)* This was first recorded as "the MCP server trims face data", on the assumption that `GET /api/assets/{id}` returns `people[].faces[]` and the MCP was stripping it. It does not: `people[]` is `PersonResponseDto`, which has no `faces` field in either the REST API or the MCP. Bounding boxes come from `GET /api/faces?id={assetId}`, which the MCP does not expose at all — so the conclusion stands (Phase 1 must use the REST API with an API key) even though the reason was wrong.
2. **Per-person asset counts need verifying.** A person-assets query through the MCP returned a total of 1 for someone who plainly appears in many photographs. Note also that the obvious search parameters are deprecated: top-level `personIds` since v3.2.0 in favour of `filter.personIds`, and `page` in favour of `cursor`/`nextCursor`. The MCP may be using the legacy form. Confirm counts against the REST API before trusting any coverage numbers.
3. **Bounding boxes are rendition-relative.** They carry their own `imageWidth`/`imageHeight`, which will not match the original asset's `width`/`height`. Scale before cropping.
4. **Dates are not uniformly trustworthy.** Scanned and imported photographs may carry an import date rather than a capture date. A true age computed from a wrong asset date is silently wrong, which is more dangerous than a missing one — Phase 1 should flag assets whose `localDateTime` looks like an import artefact (for example, a date that implies a negative age, or a cluster of assets sharing one timestamp).
