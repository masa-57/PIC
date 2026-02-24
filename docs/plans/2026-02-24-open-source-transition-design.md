# Design: Open-Source Transition (NIC -> PIC)

**Date**: 2026-02-24
**Status**: Proposed

## Problem

The NIC project is ready to be shared publicly. Before open-sourcing, we need to:
- Create a clean public repository with no git history
- Rename the project from NIC to PIC (Product Image Clustering)
- Add proper open-source files (LICENSE, CONTRIBUTING, etc.)
- Document the architecture for platform-agnostic deployment
- Remove internal-only tooling and docs

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Repo strategy | New repo, fresh start | Cleanest for public; no risk of leaked history |
| License | MIT | Maximum adoption, permissive |
| Rename scope | Full (package + env vars + configs) | Consistent naming, no NIC/PIC confusion |
| Modal coupling | Document-only for now; decoupling on roadmap | Keep Modal default, document architecture, plan abstraction layer as roadmap item |
| Ingestion | Current methods + roadmap | URL-ingest and configurable S3 as future items |
| .claude/ directory | Remove entirely | Tool-specific, not useful for contributors |
| Debt tracking | Sanitized version | Transparency about known limitations |

## Architecture (unchanged)

```
[API Server (FastAPI)] --> [GPU Workers (Modal)] --> [PostgreSQL + pgvector]
        |                        |
        v                        v
[S3-Compatible Storage] <-- [Image Pipeline]
```

All components remain the same. The rename is cosmetic (NIC->PIC) with no architectural changes.

## Implementation Summary

1. Copy project to new directory, init fresh git
2. Remove ~30 internal files/dirs (infra/, .claude/, internal docs)
3. Rename package dir: src/nic/ -> src/pic/
4. Bulk find-and-replace across ~100+ files (imports, env vars, configs)
5. Create ~9 new files (LICENSE, CONTRIBUTING, CHANGELOG, SECURITY, CODE_OF_CONDUCT, ROADMAP, deployment docs)
6. Rewrite README and AGENTS.md for PIC
7. Run full verification suite
8. Publish and configure GitHub repo

## Risks

- **Missed rename**: grep verification catches this
- **Broken imports**: unit tests catch this
- **Secrets leak**: fresh repo with no history eliminates this
- **Modal deployment**: needs new `pic-env` secret and redeploy
