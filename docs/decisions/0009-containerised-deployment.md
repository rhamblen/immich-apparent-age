# 0009 - Ship as a published container; split CPU and GPU stages across hosts

**Status:** Accepted
**Date:** 2026-11-19

## Context

This runs on a home Unraid estate rather than a workstation: several servers, four GPUs between them, and Immich already containerised on the storage host. Three facts shaped the decision.

**The two expensive stages are expensive in different ways.** Extraction (phase 1) fetches one preview image per asset across a six-figure library and writes crops to disk. It is network- and disk-bound, and uses no GPU whatsoever. Estimation (phase 2) is GPU-bound and touches no network at all, because it reads the cached crops that phase 1 already wrote. A single image forced to carry a CUDA runtime and torch for a job that needs neither would be several gigabytes of dead weight on the stage that runs longest.

**GPU capacity is contended and changes hour to hour.** A survey on 2026-11-19 found one 24 GB card with 22.3 GB already committed, a 12 GB card with 1.1 GB free because a Stable Diffusion instance was holding models, a 24 GB workstation card sitting idle, and a 20 GB card whose ComfyUI had stopped serving. Any decision of the form "it runs on *that* GPU" would have been stale within a day.

**Nothing should be built by hand on a server.** An image built once on one box, with no record of what went into it, is not a release.

The crucial enabling detail is that phase 1 caches crops to disk. That is what makes the crop cache a handoff point between hosts, rather than merely a performance optimisation (and it was chosen in [0008](0008-quality-gating-as-stored-flag.md) for an unrelated reason — so thresholds could be retuned without re-crawling).

## Decision

**Publish, do not hand-build.** CI runs the test suite and pushes an image to the GitHub Container Registry on every push to the default branch, tagged `latest`, by short SHA, and by semver on a tag. Hosts pull. A long crawl pins a tag or digest so an image update cannot change results midway.

**Two targets in one Dockerfile.** `base` is CPU-only and small, and runs phases 1, 3 and 4. `gpu` adds the CUDA runtime and torch for phase 2 only. CI builds just `base` until `estimate.py` exists; building a multi-gigabyte CUDA image for a script that has not been written would be pure cost.

**Phase 1 runs on the host that runs Immich.** It fetches ~150,000 previews; keeping that on the local bridge instead of the LAN is the largest single saving available, and it costs nothing to arrange.

**Phase 2 runs wherever a GPU actually has room, pinned by UUID.** `NVIDIA_VISIBLE_DEVICES` takes a specific card, never `all`: these hosts have more than one GPU and the others may be fully committed. The GPU host is a runtime choice in `deploy/.env`, not a property of the build.

**A single `/data` mount carries all state** - `config.yaml`, the database, crops, models and reports. One bind mount moves the entire working set between stages and hosts.

**CUDA 12.8 in the GPU target**, so one image covers Blackwell (sm_120), Ada (sm_89) and Ampere (sm_86) and the GPU choice stays free.

**Run as an unprivileged user.** Everything written goes to `/data`, so `user: "99:100"` matches Unraid appdata ownership and the container never needs root.

## Consequences

**Good.** The image is reproducible, versioned, and tested before it is published. Phase 2 can be moved to whichever card is free that week by editing one line, with no rebuild. Extraction stops paying for a CUDA runtime it never uses. Because extraction is already resumable and idempotent, a container can be stopped the moment a GPU or a host is needed for something else, and restarted later with nothing lost but the asset in flight - which is what makes running on contended hardware acceptable at all.

**Bad.** Splitting the stages across hosts means `/data` has to be reachable from both, which on Unraid means a remote SMB or NFS mount rather than a local path. That is real added complexity, and it is the main cost of this decision. The alternative - running both stages on the Immich host, using its own 12 GB card - avoids the shared mount entirely but accepts contention with whatever else is using that GPU. Either is workable; the shared mount is preferred because the contended card is the weakest of the four.

**Also.** Two images mean two things to keep in step. The dependency split is enforced by `requirements.txt` versus `requirements-gpu.txt`, and torch is installed only in the GPU target, so drift shows up as an import error in phase 2 rather than silently.

**Open.** Which card phase 2 ends up on is not settled here and should not be: see the open decisions in [`../project-plan.md`](../project-plan.md). The current reading favours the idle 20 GB Ada card on the second host, with the Immich host's 12 GB card as the fallback at a smaller batch size.
