# Roadmap

PIC restarted in September 2026 as an open-source, self-hosted project.
[v0.3.0](https://github.com/masa-57/PIC/releases/tag/v0.3.0) delivered the
reboot: it runs locally with `docker compose up` and has a web UI for
uploading, running, browsing and curating. Current work is tracked in the
[v0.4](https://github.com/masa-57/PIC/milestone/2) milestone on GitHub Issues.
This file is only the map; the issues hold the detail.

## Guiding principle

**Simplify.** Less code, fewer dependencies, fewer config knobs, less CI.
Simplification is mostly opportunistic: when touching a module, remove what a
small self-hosted deployment will never need. PIC stays open source, so keep
what outside users and contributors rely on. Items with a clear payoff are
tracked as their own issues under the `simplification` label.

## Order of work (v0.4)

1. **Reliability quick wins**
   - Single-worker lock and job start times ([#130](https://github.com/masa-57/PIC/issues/130)):
     stop two workers from competing for jobs, and base the stale-job sweep on
     when a job started, not when it was queued.
   - Thumbnails that respect EXIF orientation ([#138](https://github.com/masa-57/PIC/issues/138)).
   - Observability fixes ([#139](https://github.com/masa-57/PIC/issues/139)):
     worker log level, request IDs in logs, honest health checks.
2. **Clustering benchmark** ([#114](https://github.com/masa-57/PIC/issues/114))
   -- labeled dataset and precision/recall script. Needed before changing
   models or defaults; small catalogs already show L2 results flipping
   between CPU and GPU runs.
3. **Multi-model embeddings** ([#115](https://github.com/masa-57/PIC/issues/115))
   -- blocked on the benchmark.
4. **Toolchain**
   - Modal images built from `uv.lock` ([#124](https://github.com/masa-57/PIC/issues/124)).
   - Python 3.14 ([#123](https://github.com/masa-57/PIC/issues/123)), when
     the ML stack supports it.

Ongoing simplification: [#119](https://github.com/masa-57/PIC/issues/119)
(config surface).

## Later

Worth doing once the milestone above is done, or when a real need shows up.

- **Warm worker start.** Load the ML libraries and the DINOv2 model when
  `pic-worker` starts, so the first run after a restart skips a few seconds of
  setup.
- **Job queue.** Replace Postgres polling in the local worker with a proper
  queue (Redis, Celery or similar) if job volume or latency demands it.
- **Parallel job execution.** Let the local worker run more than one job at a
  time; today it runs one, and pipeline/cluster jobs share an advisory lock.
- **Local NVIDIA GPU support.** Ship CPU and CUDA torch variants in the
  lockfile so a Linux worker can use an NVIDIA GPU. Shares the fix with
  [#124](https://github.com/masa-57/PIC/issues/124).

## Done

- **v0.3.0** ([milestone](https://github.com/masa-57/PIC/milestone/1?closed=1)):
  unfreeze and dependency refresh (#111), simpler CI and dependencies (#116,
  #117), local worker backend (#112), web UI with folder upload and product
  curation (#113), pipeline fixes (#128, #129), and dropping unused features
  (#118, #120).

## Not planned

Webhooks, batch API, real-time clustering, Ray / Kubernetes workers.
These were on the previous roadmap and are out of scope until there is a user
who needs them.
