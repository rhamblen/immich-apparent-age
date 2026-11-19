# 0001 — Measure the apparent-age residual, not age

**Status:** Accepted
**Date:** 2026-11-19

## Context

The obvious reading of "use age-recognition AI on my photo library" is that the system should estimate how old people are. For this library that would be pointless: Immich already stores a birth date per person and every asset carries a capture date, so chronological age is exact arithmetic. A model could only approximate a number already known precisely.

The actual question is different — whether someone *looks* good for their age. That is a comparison between two quantities: how old a face appears, and how old the person demonstrably was when the shutter opened.

Having ground truth for every single face is unusual. Most apparent-age work has to treat model error as unmeasurable. Here it is directly observable, which makes two things possible that otherwise are not:

- **Calibration** — the model's systematic bias can be measured on these exact faces, at these ages, and removed.
- **Averaging** — one photograph's apparent age is nearly worthless, with error of roughly ±5 years driven as much by lighting, lens, expression and resolution as by the face. With hundreds of photographs per person, the noise falls off as about 1/√n and the mean becomes meaningful.

## Decision

The unit of analysis is the **residual**:

```
residual = apparent_age (model) − chronological_age (birth date + asset date)
```

Chronological age is computed arithmetically and is treated as exact. Apparent age comes from a model that is never given the true age. Neither is a deliverable on its own; the residual is.

Consequently:

- Only people with a known birth date can participate. Unnamed clusters and people without dates are out of scope for analysis.
- Ground truth and estimates are kept in separate tables with no code path between them (see [0007](0007-sidecar-sqlite-as-system-of-record.md)).
- Nothing is reported from a single photograph. Per-person aggregates carry n and a confidence interval.

## Consequences

**Good.** The project measures the thing actually being asked about. Ground truth turns an unverifiable estimate into a measurable, correctable error. Averaging over a large library converts a hopelessly noisy per-image signal into a usable per-person one.

**Bad.** Sample size becomes a hard constraint, so the project depends on birth dates being filled in. The raw residual is badly biased by the model compressing toward its training mean, which requires its own correction and is the single easiest way to produce a confident wrong answer — see [0005](0005-correct-for-regression-to-the-mean.md).

**Also.** The same machinery inverts usefully: given known birth dates and an apparent age, the *photograph's* date can be estimated for undated scans. Not in scope for now, but the data model should not preclude it.
