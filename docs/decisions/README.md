# Decision records

One file per significant choice, in the form *Status · Date · Context · Decision · Consequences*. These are the durable record of **why** the project works the way it does. Supersede an ADR with a new one rather than rewriting history.

| # | Decision | Status |
|---|---|---|
| [0001](0001-measure-apparent-age-residual.md) | Measure the apparent-age residual, not age | Accepted |
| [0002](0002-local-models-not-cloud-apis.md) | Run models locally; reject cloud vision APIs | Accepted |
| [0003](0003-apparent-age-trained-model.md) | Use a model trained on apparent age, not chronological age | Accepted |
| [0004](0004-reuse-immich-face-boxes.md) | Reuse Immich's face bounding boxes; run no detector | Accepted |
| [0005](0005-correct-for-regression-to-the-mean.md) | Score residuals against the model's own expectation at that age | Accepted |
| [0006](0006-same-photo-comparison-as-primary-design.md) | Same-photo comparison is the primary design | Accepted |
| [0007](0007-sidecar-sqlite-as-system-of-record.md) | A sidecar SQLite database is the system of record | Accepted |
| [0008](0008-quality-gating-as-stored-flag.md) | Quality gating is a stored flag, not an extraction filter | Accepted |

The two that matter most if you read only two: **0005**, because without it the results are a confident artefact, and **0006**, because it is the only design here that removes confounds rather than correcting for them.

Questions still open are listed at the foot of [`../project-plan.md`](../project-plan.md). Settle them with a new ADR.
