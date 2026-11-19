# 0008 — Quality gating is a stored flag, not an extraction filter

**Status:** Accepted
**Date:** 2026-11-19

## Context

Crop quality dominates apparent-age error. A 40-pixel face from the corner of a group shot, or a motion-blurred frame, or a near-profile, will produce a number — models always produce a number — and that number carries little information while being indistinguishable in the database from a good measurement.

A single gate on crop size and sharpness is expected to improve accuracy more than any model upgrade. The question is where the gate lives.

Filtering during extraction, and simply not storing poor crops, is the obvious implementation and the wrong one. The thresholds are guesses until there is data to tune them against: the right minimum crop size for this library, with its mix of scans, compact-camera files and modern phone photographs, is not knowable in advance. Discarding at extraction time means every retune requires another crawl of a six-figure library, and the gate's effect can never be measured, because the excluded population no longer exists.

## Decision

Every face Immich reports is extracted and stored. Quality is recorded as measurements plus a derived flag:

- `crop_px` — shorter edge of the crop in pixels
- `blur_var` — variance of the Laplacian, the standard cheap sharpness proxy
- `yaw_deg` — where the model or landmarks expose pose
- `passes_gate` — 0 or 1, derived from the config thresholds

Analysis uses `passes_gate = 1`. Re-gating is an `UPDATE`, not a re-crawl.

Initial thresholds, to be tuned: `min_crop_px: 112` (the input size most face models expect, so smaller means upscaling invented detail), `min_laplacian_var: 60.0`, `max_yaw_deg: 30`.

Quality covariates are retained in the analysis stage, not merely used for filtering, so that residual against crop size and residual against sharpness can be plotted. If a residual correlates with crop quality, the finding is about image quality rather than the face, and must be reported as such.

## Consequences

**Good.** Thresholds can be tuned against real data, and the tuning is cheap. The gate's effect is measurable, because both populations are present. Correlation between residual and image quality becomes detectable — which matters, since it is exactly how a false result would arise. Storing everything also keeps open any later use of the poor crops, such as dating undated photographs, where a rough estimate still helps.

**Bad.** A larger database and a larger crop cache, holding faces that will mostly never be used. Inference cost rises if predictions are run over ungated faces, so Phase 2 should respect the gate by default and treat ungated inference as an explicit opt-in.

**Related.** Quality interacts directly with [0006](0006-same-photo-comparison-as-primary-design.md): within one photograph, two people can still have very different crop sizes if one is nearer the camera, so same-photo pairs should additionally require comparable crop quality before being treated as matched.
