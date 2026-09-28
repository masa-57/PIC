# Roadmap

PIC restarted in September 2026 as an open-source, self-hosted project. All work is tracked in the
[v0.3 Reboot](https://github.com/masa-57/PIC/milestone/1) milestone on GitHub
Issues. This file is only the map; the issues hold the detail.

## Guiding principle

**Simplify.** Less code, fewer dependencies, fewer config knobs, less CI.
Simplification is mostly opportunistic: when touching a module, remove what a
small self-hosted deployment will never need. PIC stays open source, so keep
what outside users and contributors rely on. Items with a clear payoff are
tracked as their own issues under the `simplification` label.

## Order of work

1. **Unfreeze** ([#111](https://github.com/masa-57/PIC/issues/111)) -- refresh
   the lockfile, fix mypy, get CI green. Nothing else can merge until this lands.
2. **Simplify CI and deps** ([#116](https://github.com/masa-57/PIC/issues/116),
   [#117](https://github.com/masa-57/PIC/issues/117)) -- fold into the unfreeze
   pass where it saves work.
3. **Run without cloud accounts** ([#112](https://github.com/masa-57/PIC/issues/112))
   -- local worker backend so `docker compose up` plus a folder of images
   produces clusters.
4. **Web UI** ([#113](https://github.com/masa-57/PIC/issues/113)) -- browse and
   curate clusters from the API itself.
5. **Clustering benchmark** ([#114](https://github.com/masa-57/PIC/issues/114))
   -- labeled dataset and precision/recall script.
6. **Multi-model embeddings** ([#115](https://github.com/masa-57/PIC/issues/115))
   -- blocked on the benchmark.

Ongoing simplification: [#118](https://github.com/masa-57/PIC/issues/118)
(Docker and root config), [#119](https://github.com/masa-57/PIC/issues/119)
(config surface), [#120](https://github.com/masa-57/PIC/issues/120) (features
to drop).

## Later

Worth doing once the milestone above is done, or when a real need shows up.

- **Job queue.** Replace Postgres polling in the local worker with a proper
  queue (Redis, Celery or similar) if job volume or latency demands it.
- **Parallel job execution.** Let the local worker run more than one job at a
  time; today it runs one, and pipeline/cluster jobs share an advisory lock.
- **Local NVIDIA GPU support.** Ship CPU and CUDA torch variants in the
  lockfile so a Linux worker can use an NVIDIA GPU. Shares the fix with
  [#124](https://github.com/masa-57/PIC/issues/124).
- **Image upload endpoint.** Pairs with the web UI
  ([#113](https://github.com/masa-57/PIC/issues/113)).

## Not planned

Webhooks, batch API, real-time clustering, Ray / Kubernetes workers.
These were on the previous roadmap and are out of scope until there is a user
who needs them.
