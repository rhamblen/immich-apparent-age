# 0004 — Reuse Immich's face bounding boxes; run no detector

**Status:** Accepted
**Date:** 2026-11-19

## Context

An age-estimation pipeline normally begins with face detection and alignment. Immich has already done both, and more: its machine-learning container detects faces, computes recognition embeddings, and clusters them into people, which the user has then **named**. The target library has around 9,900 person clusters built this way.

`GET /api/faces?id={assetId}` exposes the result as an array of `AssetFaceResponseDto`, each carrying `boundingBoxX1`, `boundingBoxY1`, `boundingBoxX2`, `boundingBoxY2`, the `imageWidth` and `imageHeight` of the rendition those coordinates refer to, and the owning `person` — which is what binds a box to a birth date.

> **Correction, 2026-11-19.** This ADR originally said the boxes were nested as `people[].faces[]` on `GET /api/assets/{id}`. That was wrong, and so was the inference that the MCP server was trimming them: the asset endpoint returns `people[]` as `PersonResponseDto`, which has no `faces` field in the first place. Verified against the Immich OpenAPI spec (info.version 3.4.0-rc.0). The decision below is unaffected — only the endpoint changed.

Running a separate detector would mean re-detecting faces that are already detected, and then re-solving the much harder problem of *which* face belongs to whom — discarding the identity work that makes this project possible at all. It would also introduce a second, silent failure mode: a detector that disagrees with Immich about where a face is would produce crops that do not correspond to the person whose birth date is being used as ground truth.

## Decision

Take the bounding boxes from Immich and crop. No face detection, no identity resolution, no clustering in this project.

Implementation requirements:

- Crop from the **same rendition** the boxes were computed against. The box record's own `imageWidth`/`imageHeight` is the reference frame; scale by the ratio to the fetched image's actual dimensions. Do not assume the original asset's `width`/`height` — they will differ.
- Expand the box by a configurable margin before cropping, since age models expect some context around the face rather than a tight crop.
- Match faces to a person by the `person.id` on each face record, not by position or order.
- Talk to the **REST API**: the Immich MCP server exposes no face endpoint at all, so the boxes are unreachable through it.

One ambiguity survives the spec: the `id` query parameter of `GET /api/faces` is documented as a "Face ID" while the endpoint summary says it returns the faces of an *asset*. Passing an asset id is the reading the Immich web client uses, so that is what this project does — and `extract.py --probe` checks it against the live server before a full run, because everything downstream depends on it.

## Consequences

**Good.** Removes the entire detection and identification stage, which is most of the engineering. Each crop is bound to a named person, and therefore to a birth date, by Immich's own identity work. Crops stay consistent with what the user sees in the Immich UI, so a suspicious result can be inspected against the app.

**Bad.** Inherits Immich's detection choices, including misses on hard faces and any mis-assigned cluster. A wrongly assigned face produces a confidently wrong residual, since the true age will be the wrong person's. Phase 1 therefore samples crops into a contact sheet for human verification before any analysis.

**Also.** Immich's boxes are axis-aligned and unaligned by pose. If evaluation shows pose sensitivity, alignment can be added later using landmark detection on the crop — without reintroducing detection or identity resolution.
