# 0002 — Run models locally; reject cloud vision APIs

**Status:** Accepted
**Date:** 2026-11-19

## Context

Amazon Rekognition was the starting suggestion, and it does offer age estimation: `DetectFaces` with `Attributes=ALL` returns an `AgeRange` of `{Low, High}`. Azure Face withdrew its age attribute in 2022 under its responsible-AI policy, and Google Cloud Vision has never offered one, so Rekognition is effectively the only mainstream cloud option.

Against that, the library holds 151,463 images, and the subjects are family members including children.

| | Rekognition | Local model |
|---|---|---|
| Output | `AgeRange{Low, High}` bucket | Point estimate |
| Cost | ~$1 per 1,000 images → **~$150 per pass**, repeated for every re-run | Nil after setup |
| Data | Faces uploaded to a third party | Nothing leaves the LAN |
| Iteration | Re-running costs money, which discourages exactly the experimentation this needs | Free |
| Model choice | Fixed, opaque, versioned by the vendor | Chosen deliberately, pinned, swappable |

The output format is the decisive problem rather than the cost. A residual needs a point estimate. Quantised brackets like 30–40 destroy the signal: taking bracket midpoints across many photographs yields a staircase, and the bias introduced by bracket boundaries is indistinguishable from the effect being measured. The brackets are also deliberately coarse, which makes the method's precision unachievable no matter how many photographs are averaged.

## Decision

All inference runs locally. Candidate models are MiVOLO, DEX apparent-age weights, and InsightFace `genderage.onnx` as a cheap baseline. Cloud vision APIs are rejected outright, not merely deferred.

## Consequences

**Good.** Free, unlimited re-runs, which is what allows calibration, model cross-checks and threshold tuning. No family photographs leave the house. The model is pinned and recorded with every prediction, so results are reproducible.

**Bad.** Local setup cost: Python environment, model weights, and ideally a GPU for MiVOLO across a large library. Accuracy is the operator's problem rather than a vendor's.

**Note.** If a cloud API were ever reconsidered, the blocker is the bracketed output, not the price. A cloud endpoint returning a point estimate would be worth re-evaluating on privacy and cost grounds alone.
