# 0003 — Use a model trained on apparent age, not chronological age

**Status:** Accepted
**Date:** 2026-11-19

## Context

Age estimators are not interchangeable, because their training labels answer different questions.

- **Chronological-age datasets** — IMDB-WIKI, UTKFace — label each face with the subject's real age, scraped from metadata. A model trained on these is trying to recover a fact. Its error on any given face is mostly noise: resolution, pose, lighting, and label error in the training set itself.
- **Apparent-age datasets** — ChaLearn LAP, and especially **APPA-REAL** — label each face with the *mean of many human guesses* about how old the person looks. A model trained on these is trying to predict human perception.

The project's question is explicitly about perception: does this person look good for their age. APPA-REAL matters particularly because it carries **both** the real age and the mean human apparent age for the same image, which means the real-versus-apparent gap is an established, measured quantity rather than something invented here — and a model evaluated on it can be reasoned about in exactly the terms this project uses.

DeepFace was the other starting suggestion. Its age head is IMDB-WIKI-derived, so it is a chronological estimator: convenient API, but answering the wrong question. It also drags in TensorFlow, which for a six-figure library is a real throughput cost.

## Decision

Use a model trained or evaluated on perceived age. Preference order:

1. **MiVOLO** — strongest current option, reports on APPA-REAL, and can use body context as well as the face, which helps on the profile and low-resolution crops that a family library is full of. Wants a GPU.
2. **DEX apparent-age weights** — the ChaLearn LAP winner's approach, lighter, a reasonable fallback.
3. **InsightFace `genderage.onnx`** — kept only as a fast baseline and smoke test. It is tiny, CPU-friendly, and from the same model family Immich already uses, but it is a chronological estimator and must not be the basis of a reported result.

Every prediction is stored with its model name and version, and running two models as a cross-check is explicitly supported.

## Consequences

**Good.** The measured quantity matches the question asked. Published APPA-REAL performance gives a prior for what error to expect, which makes the Phase 2 sanity check meaningful. Cross-model agreement becomes available as evidence.

**Bad.** Heavier dependencies than a small ONNX file, and probably a GPU. Perceived-age models inherit the biases of their human annotators, who were not a representative sample — so a residual is relative to a particular population's idea of how old a face looks, and should be read that way.

**Mitigation.** Because the baseline model is kept and versioned alongside the others, a disagreement between a chronological and an apparent-age model on the same face is itself informative, and cheap to inspect.
