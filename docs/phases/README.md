# Phase build logs

One file per **completed** phase, named `phase-N-slug.md`, recording what was actually built
rather than what was planned. The plan lives in [`../project-plan.md`](../project-plan.md);
this directory is the build log.

Each phase log covers:

- **What was built** — concrete artefacts, with file names, table names and real identifiers.
- **How to reproduce** — the exact commands, in order, from a clean checkout.
- **Decisions and surprises** — what the plan got wrong, and anything that warranted a new ADR
  (link it).
- **Verification** — what was checked, how, and the numbers it produced.

Nothing here yet: Phase 0 produced this repo, and its content *is* the documentation.
