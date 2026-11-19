# 0006 — Same-photo comparison is the primary design

**Status:** Accepted
**Date:** 2026-11-19

## Context

Apparent age is not a property of a face alone. It is a property of a photograph of a face, and the photograph contributes a great deal:

- **Resolution and compression.** Grain and JPEG artefacts read as skin texture, which reads as age. Scans and early digital-camera files therefore age their subjects.
- **Lighting.** Flat frontal flash fills in wrinkles and reads younger; raking side light reads older.
- **Expression.** A broad smile creates crow's feet and nasolabial folds, worth years.
- **Pose and crop size.** Profile and small crops degrade every model.
- **Grooming, facial hair, glasses, hair colour, makeup.**
- **Camera era**, which correlates with the subject's real age — the confound that matters most.

That last point is fatal to the obvious analysis. Comparing one person's 1998 scans against their 2024 phone photographs measures the cameras at least as much as the face. Since camera era advances in lockstep with the subject's age, the confound is perfectly aligned with the signal, and no statistical correction separates them.

The library offers a way out that costs nothing: **group photographs**. Two people in one frame share the camera, the lens, the lighting, the exposure, the compression, the processing pipeline and the moment in time. Every confound above except expression and grooming is held constant by construction. This is a matched-pair design, and it is available in bulk — a family library of 151,463 images contains a great many frames with two or more known people in them.

The target library also contains a natural pair: two adults born seven weeks apart in 1965, who appear together frequently. Same real age, same photographs, same era. Any difference in their apparent ages within one frame is close to a clean measurement.

## Decision

Same-photo comparisons are the headline result. Specifically:

- Where two or more configured people have usable crops in one asset, record the pairwise difference in apparent age within that asset, alongside the difference in their true ages.
- Aggregate those within-photo differences per pair of people. This is the figure reported most prominently.
- Cross-photo per-person means are still computed and reported, but captioned as the weaker evidence, with camera era named as the known confound.
- Trajectories (apparent age against photo year) are reported as slopes, where each person acts as their own baseline, which absorbs a constant personal offset but not a drift in camera era.

## Consequences

**Good.** Eliminates almost every confound by design rather than by correction, which is always preferable. Produces the most defensible claim the data can support, and the one most likely to be argued about productively. Needs no extra data collection — the group photographs already exist.

**Bad.** Restricts the sample to frames containing two or more configured people, which is a fraction of the library and depends on who photographs together. People who rarely appear with others get no matched-pair result. Expression and grooming are *not* controlled, and someone who habitually smiles broadly in photographs will read older in this design.

**Implication for Phase 1.** Extraction must record the asset id against every face, so pairs can be assembled later. It must not deduplicate across people within an asset.
