# 0005 — Score residuals against the model's own expectation at that age

**Status:** Accepted
**Date:** 2026-11-19

## Context

This is the decision that determines whether the project produces a result or an artefact.

Every age-estimation model compresses its output range. Minimising squared error over a training set makes hedging toward the training mean the optimal strategy under uncertainty, so predictions are systematically pulled inward: too old for children, too young for the elderly. The effect is well documented on APPA-REAL, where human annotators show it too — they guess young for older faces and old for younger ones.

The consequence for a naive implementation is severe. Computing `apparent − actual` and averaging per person will show a large negative residual for every older subject and a positive one for every younger subject. Read uncritically, the output "proves" that everyone over fifty looks marvellous and every teenager looks haggard. The magnitude of that artefact is several years — comfortably larger than the real between-person differences being looked for, which are on the order of two to three years.

Worse, it is a *confident* artefact. It grows more statistically significant with more data, because it is systematic rather than random. No amount of averaging will reveal the problem; it has to be designed out.

## Decision

A residual is never reported against chronological age directly. Instead:

1. Fit the model's prediction against true age across all extracted faces, producing `expected(apparent | true_age)` — an isotonic or linear fit, configurable, with isotonic the default since the relationship is monotonic but not linear.
2. Define the reported residual as `apparent_age − expected(apparent | true_age)`.
3. Standardise by the residual spread at that age, giving a z-score, so a result reads as *"this face reads 1.4 standard deviations younger than this model typically reads a 55-year-old"*.
4. Publish the calibration curve alongside the results, so the correction is auditable rather than hidden.

The fit is derived from the library's own faces. This makes the reference population the family itself, which is a limitation worth stating plainly: it answers "young-looking relative to this model's reading of people this age in this library", not an absolute claim.

## Consequences

**Good.** Removes the dominant systematic bias, and makes between-person comparisons across different age bands meaningful at all. The z-score form is honest about what is being claimed. Publishing the curve lets a sceptical reader check the correction rather than trust it.

**Bad.** More machinery, and a correction fitted on a modest sample is itself uncertain — at the extremes of the age range, where there is least data, the fit is weakest. Using the family as its own reference population means a family-wide tendency (shared genetics, shared lifestyle, shared photographer) is absorbed into the baseline and becomes invisible. A larger external reference set would fix that, and is not available.

**Cross-check.** The four individuals born in 2006 provide a built-in test: after correction, their residuals should centre near zero relative to each other, with no systematic pull from their position in the age range. If a corrected residual still trends with age, the correction is not working and no conclusions should be drawn.

**Related.** [0006](0006-same-photo-comparison-as-primary-design.md) removes a different and equally large class of confound, and does so by design rather than by correction, which is why it is preferred as the headline result.
