# Roadmap

PIC restarted as a hobby project in September 2026. All work is tracked in the
[v0.3 Reboot](https://github.com/masa-57/PIC/milestone/1) milestone on GitHub
Issues. This file is only the map; the issues hold the detail.

## Guiding principle

**Simplify.** Less code, fewer dependencies, fewer config knobs, less CI.
Simplification is mostly opportunistic: when touching a module, remove what a
single-user hobby deployment will never need. Items with a clear payoff are
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

## Not planned

Webhooks, batch API, real-time clustering, Celery / Ray / Kubernetes workers.
These were on the previous roadmap and are out of scope until there is a user
who needs them.
