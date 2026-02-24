# NIC to PIC Open-Source Transition — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a new public repository called PIC (Product Image Clustering) from the private NIC codebase, with a clean git history, MIT license, full rename (NIC->PIC), and proper open-source documentation.

**Architecture:** Copy the NIC project to a new directory, remove internal files, rename all references from NIC to PIC (package, imports, env vars, configs, docs), create open-source files (LICENSE, CONTRIBUTING, etc.), and publish as a fresh git repo.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pgvector, DINOv2, HDBSCAN, Modal, S3-compatible storage

**Design doc:** `docs/plans/2026-02-24-open-source-transition-design.md`

---

## Task 1: Prepare Working Copy

**Files:**
- Create: `~/Vibe/PIC/` (new directory, copy of NIC)

**Step 1: Create target directory and copy project files**

```bash
mkdir -p ~/Vibe/PIC
rsync -av --progress ~/Vibe/NIC/ ~/Vibe/PIC/ \
  --exclude='.git/' \
  --exclude='.env' \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='.mypy_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.pytest_cache/' \
  --exclude='.coverage' \
  --exclude='coverage.xml' \
  --exclude='coverage-integration.xml' \
  --exclude='*.egg-info/' \
  --exclude='data/' \
  --exclude='.DS_Store' \
  --exclude='htmlcov/' \
  --exclude='build/' \
  --exclude='dist/'
```

**Step 2: Initialize fresh git repo**

```bash
cd ~/Vibe/PIC
git init
git checkout -b main
```

Expected: Initialized empty Git repository.

**Step 3: Verify copy is clean**

```bash
cd ~/Vibe/PIC
ls -la .git  # should exist
ls -la .env  # should NOT exist
ls -la .venv # should NOT exist
ls -la __pycache__ # should NOT exist
```

**Step 4: Commit — initial copy**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: initial copy from NIC (pre-rename)"
```

---

## Task 2: Remove Internal Files and Directories

**Files to remove:**
- `infra/` — deprecated AWS CDK code
- `.claude/` — Claude Code tooling
- `CLAUDE.md` — Claude-specific instructions
- `.claude.local.md` — personal Claude config (if exists)
- `.mcp.json` — MCP server config
- `docs/audit/reports/` — generated audit reports
- `docs/audit/debt_register_148.csv` — internal debt register
- `docs/audit/debt_milestone_label_mapping.md` — internal mapping
- `docs/audit/2026-02-11-project-audit.md` — internal audit
- `docs/plans/` — internal development plans (including this plan and design doc)
- `docs/automation/` — internal automation policy
- `docs/claude-code-quality-enforcement.md` — internal
- `docs/TODO.md` — internal todo
- `docs/composite-shard-*.json` — service account artifacts (if any)
- `docs/notes.docx` — internal notes (if exists)
- `docs/product-workflow-guide.docx` — internal (if exists)
- `scripts/debt_sync.py` — internal debt management
- `scripts/generate_*_guide.py` — generated guide scripts (if any)
- `cluster_visualization.html` — generated output (if exists)
- `clusters.html` — generated output (if exists)
- `.github/copilot-instructions.md` — Copilot-specific
- `.github/workflows/debt-register-audit.yml` — internal debt automation
- `.github/workflows/codeql.yml` — remove (can re-enable post-publish)

**Step 1: Remove all internal files**

```bash
cd ~/Vibe/PIC

# Directories
rm -rf infra/
rm -rf .claude/
rm -rf docs/audit/reports/
rm -rf docs/plans/
rm -rf docs/automation/

# Individual files
rm -f CLAUDE.md
rm -f .claude.local.md
rm -f .mcp.json
rm -f docs/audit/debt_register_148.csv
rm -f docs/audit/debt_milestone_label_mapping.md
rm -f docs/audit/2026-02-11-project-audit.md
rm -f docs/claude-code-quality-enforcement.md
rm -f docs/TODO.md
rm -f docs/notes.docx
rm -f docs/product-workflow-guide.docx
rm -f scripts/debt_sync.py
rm -f cluster_visualization.html
rm -f clusters.html
rm -f .github/copilot-instructions.md
rm -f .github/workflows/debt-register-audit.yml
rm -f .github/workflows/codeql.yml
```

Also remove any files matching gitignored patterns that might have been copied:
```bash
rm -f docs/composite-shard-*.json
rm -f docs/*-guide.docx
rm -f docs/*-guide.md  # Be careful — keep gdrive-setup-guide.md and n8n-setup-guide.md if they exist as .md
```

Wait — `docs/*-guide.md` would delete the setup guides. The gitignore pattern `docs/*-guide.md` was for *generated* guides. Check what exists:
```bash
ls docs/*guide*
```
Keep `docs/gdrive-setup-guide.md` and `docs/n8n-setup-guide.md` if they exist. Only remove files matching `scripts/generate_*_guide.py`.

**Step 2: Remove empty directories**

```bash
# Clean up empty dirs left behind
find ~/Vibe/PIC/docs/audit -type d -empty -delete 2>/dev/null
rmdir docs/audit 2>/dev/null || true
```

**Step 3: Verify removals**

```bash
cd ~/Vibe/PIC
test ! -d infra && echo "OK: infra removed"
test ! -d .claude && echo "OK: .claude removed"
test ! -f CLAUDE.md && echo "OK: CLAUDE.md removed"
test ! -f .mcp.json && echo "OK: .mcp.json removed"
test ! -f scripts/debt_sync.py && echo "OK: debt_sync.py removed"
test ! -f .github/workflows/debt-register-audit.yml && echo "OK: debt workflow removed"
```

**Step 4: Commit — remove internal files**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: remove internal files (infra, .claude, audit, plans, debt tooling)"
```

---

## Task 3: Rename Package Directory

**Files:**
- Rename: `src/nic/` -> `src/pic/`

**Step 1: Rename the directory**

```bash
cd ~/Vibe/PIC
mv src/nic src/pic
```

**Step 2: Verify**

```bash
test -d src/pic && echo "OK: src/pic exists"
test ! -d src/nic && echo "OK: src/nic removed"
ls src/pic/__init__.py && echo "OK: package init exists"
```

**Step 3: Commit — rename package directory**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: rename package directory src/nic -> src/pic"
```

---

## Task 4: Bulk Rename Python Imports

All `from nic.` -> `from pic.` and `import nic.` -> `import pic.` across all Python files.

**Files:**
- Modify: All `*.py` files under `src/pic/`, `tests/`, `scripts/`

**Step 1: Run bulk sed replacement**

```bash
cd ~/Vibe/PIC

# Replace "from nic." with "from pic." in all Python files
find . -name "*.py" -not -path "./.venv/*" -exec sed -i '' 's/from nic\./from pic./g' {} +

# Replace "import nic." with "import pic." in all Python files
find . -name "*.py" -not -path "./.venv/*" -exec sed -i '' 's/import nic\./import pic./g' {} +

# Replace "import nic" (standalone, for add_local_python_source) with "import pic"
# Be careful — only match exact standalone "import nic" not "import nic_something"
find . -name "*.py" -not -path "./.venv/*" -exec sed -i '' 's/^import nic$/import pic/g' {} +
```

**Step 2: Fix modal_app.py specific references**

In `src/pic/modal_app.py`, the `.add_local_python_source("nic")` calls need updating:
```bash
cd ~/Vibe/PIC
sed -i '' 's/add_local_python_source("nic")/add_local_python_source("pic")/g' src/pic/modal_app.py
```

**Step 3: Fix mock paths in test files**

Test files use string paths for mocking like `"nic.services.image_store.get_s3_client"`. These need updating:
```bash
cd ~/Vibe/PIC
find tests/ -name "*.py" -exec sed -i '' 's/"nic\./"pic./g' {} +
```

**Step 4: Verify no remaining `from nic.` imports**

```bash
cd ~/Vibe/PIC
grep -rn "from nic\." --include="*.py" .
grep -rn "import nic\." --include="*.py" .
grep -rn "import nic$" --include="*.py" .
```

Expected: zero matches.

**Step 5: Verify no remaining `"nic.` mock paths**

```bash
cd ~/Vibe/PIC
grep -rn '"nic\.' --include="*.py" .
```

Expected: zero matches (or only in comments/strings that don't matter).

**Step 6: Commit — bulk rename Python imports**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: rename all Python imports from nic -> pic"
```

---

## Task 5: Rename Config and Core Files

**Files:**
- Modify: `src/pic/config.py`
- Modify: `src/pic/modal_app.py`
- Modify: `src/pic/services/modal_dispatch.py`

**Step 1: Update config.py**

In `src/pic/config.py`, make these changes:
- Line 11: `database_url` default: `"postgresql+asyncpg://localhost:5432/nic"` -> `"postgresql+asyncpg://localhost:5432/pic"`
- Line 18: `s3_bucket` default: `"nic-images"` -> `"pic-images"`
- Line 70: `env_prefix`: `"NIC_"` -> `"PIC_"`
- All error messages referencing `NIC_*` env vars -> `PIC_*`

Specifically in the error messages:
- `"S3 credentials (NIC_S3_ACCESS_KEY_ID, NIC_S3_SECRET_ACCESS_KEY) are required when NIC_S3_ENDPOINT_URL is set"` -> use `PIC_*`
- `"CORS wildcard ['*'] is not allowed when NIC_API_KEY is set"` -> `PIC_API_KEY`
- `"NIC_GDRIVE_SERVICE_ACCOUNT_JSON is not valid JSON"` -> `PIC_GDRIVE_SERVICE_ACCOUNT_JSON`
- `"NIC_CORS_ORIGINS"` -> `"PIC_CORS_ORIGINS"`

**Step 2: Update modal_app.py**

In `src/pic/modal_app.py`:
- Line 1 docstring: `"""Modal app definition for NIC GPU workers"""` -> `"""Modal app definition for PIC GPU workers"""`
- Line 5: `app = modal.App("nic")` -> `app = modal.App("pic")`
- Line 8: `nic_image = (` -> `pic_image = (`
- Line 37: `nic_check_image = (` -> `pic_check_image = (`
- Line 95: `modal.Function.from_name("nic", "sync_gdrive_to_r2")` -> `modal.Function.from_name("pic", "sync_gdrive_to_r2")`
- All `image=nic_image` -> `image=pic_image` (4 occurrences)
- All `image=nic_check_image` -> `image=pic_check_image` (1 occurrence)
- All `secrets=[modal.Secret.from_name("nic-env")]` -> `secrets=[modal.Secret.from_name("pic-env")]` (5 occurrences)

**Step 3: Update modal_dispatch.py**

In `src/pic/services/modal_dispatch.py`:
- Line 1 docstring: keep or update
- Line 14: `MODAL_APP_NAME = "nic"` -> `MODAL_APP_NAME = "pic"`

**Step 4: Verify Modal references**

```bash
cd ~/Vibe/PIC
grep -rn '"nic"' --include="*.py" src/pic/modal_app.py src/pic/services/modal_dispatch.py
grep -rn 'nic_image\|nic_check_image\|nic-env' --include="*.py" src/pic/
```

Expected: zero matches.

**Step 5: Verify config env prefix**

```bash
cd ~/Vibe/PIC
grep -n 'NIC_' src/pic/config.py
```

Expected: zero matches.

**Step 6: Commit — rename config and core files**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: rename config env prefix NIC_ -> PIC_, Modal app nic -> pic"
```

---

## Task 6: Rename main.py and API Layer

**Files:**
- Modify: `src/pic/main.py`

**Step 1: Update main.py**

In `src/pic/main.py`, find and replace:
- FastAPI `title` parameter: likely `"NIC"` or `"NIC API"` -> `"PIC"` or `"PIC API"`
- Any log messages mentioning "NIC" -> "PIC"
- The imports should already be updated from Task 4

```bash
cd ~/Vibe/PIC
grep -n "NIC\|nic" src/pic/main.py
```

Fix any remaining references found.

**Step 2: Verify**

```bash
cd ~/Vibe/PIC
grep -in "nic" src/pic/main.py
```

Expected: zero matches (except possibly in comments about the original project, which should also be updated).

**Step 3: Commit — update main.py**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: rename NIC references in main.py"
```

---

## Task 7: Rename Build and Infrastructure Files

**Files:**
- Modify: `pyproject.toml`
- Modify: `alembic.ini`
- Modify: `.pre-commit-config.yaml`
- Modify: `Makefile`
- Modify: `Dockerfile`
- Modify: `Dockerfile.railway`
- Modify: `docker-compose.yml`
- Modify: `.env.example`

**Step 1: Update pyproject.toml**

Changes needed:
- Line 2: `name = "nic"` -> `name = "pic"`
- Line 4: `description = "Hierarchical image clustering API for cake images"` -> `description = "Hierarchical image clustering API for product catalog images"`
- Line 54: `nic = "nic.main:app"` -> `pic = "pic.main:app"`
- Line 79: `extend-exclude = ["src/nic/migrations"]` -> `extend-exclude = ["src/pic/migrations"]`
- Line 97: `known-first-party = ["nic"]` -> `known-first-party = ["pic"]`
- Line 109: `source = ["src/nic"]` -> `source = ["src/pic"]`

**Step 2: Update alembic.ini**

Change: `script_location = src/nic/migrations` -> `script_location = src/pic/migrations`

**Step 3: Update .pre-commit-config.yaml**

Change: `entry: uv run mypy src/nic/` -> `entry: uv run mypy src/pic/`
Also check for any other `nic` references.

**Step 4: Update Makefile**

Changes needed:
- `uv run fastapi dev src/nic/main.py` -> `uv run fastapi dev src/pic/main.py`
- `--cov=src/nic` -> `--cov=src/pic`
- `uv run ruff check src/ tests/ scripts/` (no change needed — generic paths)
- `uv run mypy src/nic/` -> `uv run mypy src/pic/`
- `--owner masa-57 --repo NIC` -> remove debt-related targets entirely
- `NIC_POSTGRES_URL` -> `PIC_POSTGRES_URL`
- Backup prefix `nic_` -> `pic_`
- Remove `debt-check`, `debt-report`, `debt-issues-dry-run` targets (debt_sync.py was removed)

**Step 5: Update Dockerfile**

- Line 1: `# API Dockerfile for NIC` -> `# API Dockerfile for PIC`
- Line 22: `CMD uv run fastapi run src/nic/main.py --host 0.0.0.0 --port $PORT` -> `CMD uv run fastapi run src/pic/main.py --host 0.0.0.0 --port $PORT`

**Step 6: Update Dockerfile.railway**

- Line 2: `# Railway API-only Dockerfile (slim, no ML deps)` (keep as-is, generic)
- Line 21: `CMD uv run --no-sync fastapi run src/nic/main.py --host 0.0.0.0 --port $PORT` -> `CMD uv run --no-sync fastapi run src/pic/main.py --host 0.0.0.0 --port $PORT`

**Step 7: Update docker-compose.yml**

Changes needed:
- `POSTGRES_DB: nic` -> `POSTGRES_DB: pic`
- `POSTGRES_USER: nic` -> `POSTGRES_USER: pic`
- `POSTGRES_PASSWORD: nic_local` -> `POSTGRES_PASSWORD: pic_local`
- `pg_isready -U nic` -> `pg_isready -U pic`
- `NIC_DATABASE_URL: postgresql+asyncpg://nic:nic_local@db:5432/nic` -> `PIC_DATABASE_URL: postgresql+asyncpg://pic:pic_local@db:5432/pic`
- `NIC_S3_BUCKET: nic-local` -> `PIC_S3_BUCKET: pic-local`
- `NIC_S3_ENDPOINT_URL` -> `PIC_S3_ENDPOINT_URL`
- `NIC_S3_ACCESS_KEY_ID` -> `PIC_S3_ACCESS_KEY_ID`
- `NIC_S3_SECRET_ACCESS_KEY` -> `PIC_S3_SECRET_ACCESS_KEY`

**Step 8: Update .env.example**

Replace all `NIC_` prefixes with `PIC_`:
```bash
cd ~/Vibe/PIC
sed -i '' 's/NIC_/PIC_/g' .env.example
```

Also update:
- `nic?sslmode=require` -> `pic?sslmode=require` (in DB URLs)
- `nic-images` -> `pic-images` (in S3 bucket)
- Top comment mentioning NIC -> PIC

**Step 9: Verify all build files**

```bash
cd ~/Vibe/PIC
grep -n "NIC\|nic" pyproject.toml alembic.ini .pre-commit-config.yaml Makefile Dockerfile Dockerfile.railway docker-compose.yml .env.example
```

Expected: zero matches (except generic words like "communication" that contain "nic" as a substring — review carefully).

**Step 10: Commit — rename build and infrastructure files**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: rename NIC -> PIC in build, Docker, compose, Makefile, env example"
```

---

## Task 8: Rename CI/CD Workflows

**Files:**
- Modify: `.github/workflows/ci-cd.yml`
- Modify: `.github/workflows/deploy-staging.yml`
- Modify: `.github/ISSUE_TEMPLATE/config.yml`

**Step 1: Update ci-cd.yml**

Changes needed:
- Line 29: `uv run mypy src/nic/` -> `uv run mypy src/pic/`
- Line 38: `python3 scripts/debt_sync.py validate --strict --owner masa-57 --repo NIC` -> REMOVE entire `debt-integrity` job
- Line 39: `python3 scripts/debt_sync.py report --out-dir debt-report` -> REMOVE
- Line 50: `docker build -f Dockerfile.railway -t nic-api:scan .` -> `-t pic-api:scan .`
- Line 54: `image-ref: nic-api:scan` -> `image-ref: pic-api:scan`
- Line 72: `--cov=src/nic` -> `--cov=src/pic`
- Line 85: `POSTGRES_DB: nic_test` -> `POSTGRES_DB: pic_test`
- Line 106: `dsn = "postgresql://postgres:test@localhost:5432/nic_test"` -> `pic_test`
- Line 125: `NIC_DATABASE_URL: postgresql+asyncpg://postgres:test@localhost:5432/nic_test` -> `PIC_DATABASE_URL: ...pic_test`
- Line 127: `--cov=src/nic` -> `--cov=src/pic`
- Line 129: `NIC_DATABASE_URL: postgresql+asyncpg://postgres:test@localhost:5432/nic_test` -> `PIC_DATABASE_URL: ...pic_test`
- Line 155: Remove `debt-integrity` from `needs:` list in `deploy-modal`
- Line 184: `uv run modal deploy src/nic/modal_app.py` -> `uv run modal deploy src/pic/modal_app.py`
- Line 222: `uv run modal deploy src/nic/modal_app.py` (rollback) -> `uv run modal deploy src/pic/modal_app.py`

Also remove the entire `debt-integrity` job block (lines ~32-43) and the `debt-report` artifact upload.

**Step 2: Update deploy-staging.yml**

Changes needed:
- Line 26: `uv run mypy src/nic/` -> `uv run mypy src/pic/`
- Line 55: `uv run modal deploy src/nic/modal_app.py` -> `uv run modal deploy src/pic/modal_app.py`

**Step 3: Update issue template config**

In `.github/ISSUE_TEMPLATE/config.yml`:
- `url: https://github.com/masa-57/NIC/blob/main/docs/n8n-setup-guide.md` -> `url: https://github.com/masa-57/pic/blob/main/docs/n8n-setup-guide.md`

**Step 4: Verify no NIC references in workflows**

```bash
cd ~/Vibe/PIC
grep -rn "NIC\|nic" --include="*.yml" .github/
grep -rn "debt_sync\|debt-register\|debt-integrity" .github/
```

Expected: zero matches.

**Step 5: Commit — rename CI/CD workflows**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: rename NIC -> PIC in CI/CD workflows, remove debt automation"
```

---

## Task 9: Rename Test File Contents

**Files:**
- Modify: All `tests/**/*.py` files

**Step 1: Bulk replace NIC_ env var references in tests**

```bash
cd ~/Vibe/PIC
find tests/ -name "*.py" -exec sed -i '' 's/NIC_/PIC_/g' {} +
```

**Step 2: Replace remaining "nic" string references in tests**

Some tests may have string literals like `"nic"` for the Modal app name, DB names, etc.:
```bash
cd ~/Vibe/PIC
# Modal app name in assertions
find tests/ -name "*.py" -exec sed -i '' 's/App("nic")/App("pic")/g' {} +
find tests/ -name "*.py" -exec sed -i '' "s/from_name(\"nic\"/from_name(\"pic\"/g" {} +

# DB connection strings
find tests/ -name "*.py" -exec sed -i '' 's|localhost:5432/nic|localhost:5432/pic|g' {} +
find tests/ -name "*.py" -exec sed -i '' 's|nic_test|pic_test|g' {} +
```

**Step 3: Verify no remaining NIC references in tests**

```bash
cd ~/Vibe/PIC
grep -rn "NIC_\|from_name(\"nic\"\|App(\"nic\"\|/nic\?" --include="*.py" tests/
```

Expected: zero matches.

**Step 4: Commit — rename test contents**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: rename NIC -> PIC in test files (env vars, mock paths, DB names)"
```

---

## Task 10: Rename Scripts

**Files:**
- Modify: All `scripts/*.py` files

**Step 1: Bulk replace in scripts**

```bash
cd ~/Vibe/PIC
find scripts/ -name "*.py" -exec sed -i '' 's/NIC_/PIC_/g' {} +
find scripts/ -name "*.py" -exec sed -i '' 's|src/nic|src/pic|g' {} +
```

**Step 2: Check for any remaining references**

```bash
cd ~/Vibe/PIC
grep -rn "NIC\|nic" --include="*.py" scripts/
```

Fix any remaining references manually (e.g., "NIC" in comments, log messages, etc.).

**Step 3: Commit — rename scripts**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: rename NIC -> PIC in scripts"
```

---

## Task 11: Rename Remaining Source Files

Catch any remaining `NIC`/`nic` references in source that weren't covered by the bulk import rename.

**Files:**
- Modify: Various `src/pic/**/*.py` files

**Step 1: Find all remaining references**

```bash
cd ~/Vibe/PIC
# Uppercase NIC (in comments, docstrings, log messages)
grep -rn "NIC" --include="*.py" src/pic/

# Lowercase nic (in strings, comments — but NOT in words like "communication", "technical")
grep -rn '"nic"\|nic-\|nic_\| nic ' --include="*.py" src/pic/
```

**Step 2: Fix remaining references**

Common patterns to fix:
- Docstrings: `"""...NIC...""""` -> `"""...PIC..."""`
- Log messages: `"NIC ..."` -> `"PIC ..."`
- Comments: `# NIC ...` -> `# PIC ...`
- String literals: `"nic-images"` -> `"pic-images"` (should be caught by config, but check)
- Advisory lock comment: `# NIC advisory lock` -> `# PIC advisory lock`

```bash
cd ~/Vibe/PIC
# Replace NIC in comments and docstrings
find src/pic/ -name "*.py" -exec sed -i '' 's/NIC GPU workers/PIC GPU workers/g' {} +
find src/pic/ -name "*.py" -exec sed -i '' 's/NIC API/PIC API/g' {} +
find src/pic/ -name "*.py" -exec sed -i '' 's/NIC project/PIC project/g' {} +
find src/pic/ -name "*.py" -exec sed -i '' 's/replaces AWS Batch/dispatches ML jobs to Modal/g' {} +
```

**Step 3: Verify**

```bash
cd ~/Vibe/PIC
grep -rn "NIC" --include="*.py" src/pic/ | grep -v "# Original project: NIC"
```

Expected: zero matches (or only intentional references to the original project).

**Step 4: Commit — clean up remaining source references**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: clean up remaining NIC references in source code"
```

---

## Task 12: Rename Documentation Files

**Files:**
- Modify: `docs/operations/*.md`
- Modify: `docs/gdrive-setup-guide.md` (if exists)
- Modify: `docs/n8n-setup-guide.md` (if exists)
- Modify: `docs/runbooks/*.md` (if exists)
- Modify: `.gitignore`

**Step 1: Bulk replace in markdown files**

```bash
cd ~/Vibe/PIC

# Replace env var prefix
find docs/ -name "*.md" -exec sed -i '' 's/NIC_/PIC_/g' {} +

# Replace project references
find docs/ -name "*.md" -exec sed -i '' 's/NIC API/PIC API/g' {} +
find docs/ -name "*.md" -exec sed -i '' 's/NIC project/PIC project/g' {} +
find docs/ -name "*.md" -exec sed -i '' 's/src\/nic/src\/pic/g' {} +
find docs/ -name "*.md" -exec sed -i '' 's/masa-57\/NIC/masa-57\/pic/g' {} +

# Replace bucket/DB names
find docs/ -name "*.md" -exec sed -i '' 's/nic-images/pic-images/g' {} +
find docs/ -name "*.md" -exec sed -i '' 's/nic-env/pic-env/g' {} +
find docs/ -name "*.md" -exec sed -i '' 's/nic_test/pic_test/g' {} +
```

**Step 2: Update .gitignore**

Check for NIC-specific references:
```bash
cd ~/Vibe/PIC
grep -n "nic\|NIC" .gitignore
```

The `.gitignore` doesn't contain NIC-specific references based on our earlier read, but verify and fix if needed.

Remove entries that no longer apply:
- `infra/cdk.out/`, `infra/cdk.context.json`, `infra/.venv/` — infra/ was deleted
- `infra/lambda/psycopg2/`, `infra/lambda/psycopg2_binary*/` — same
- `scripts/generate_*_guide.py` — may not be needed
- `.claude/plugins/` — .claude/ was deleted
- `docs/*service-account*.json`, `docs/composite-shard-*.json` — cleaned up
- `docs/*-guide.docx`, `docs/*-guide.md` — generated guides pattern

Keep all other entries as they're generic Python/.env patterns.

**Step 3: Verify docs**

```bash
cd ~/Vibe/PIC
grep -rn "NIC" --include="*.md" docs/ | head -20
```

Expected: zero or near-zero matches.

**Step 4: Commit — rename documentation**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: rename NIC -> PIC in documentation and .gitignore cleanup"
```

---

## Task 13: Sanitize TECHNICAL_DEBT.md

**Files:**
- Modify: `TECHNICAL_DEBT.md`

**Step 1: Remove GitHub issue links**

Remove all `https://github.com/masa-57/NIC/issues/` links and their markdown formatting, while keeping the issue descriptions.

```bash
cd ~/Vibe/PIC
# Remove "(#NNN)" and "[#NNN](url)" patterns
sed -i '' 's/ *\[#[0-9]*\](https:\/\/github.com\/masa-57\/NIC\/issues\/[0-9]*)//g' TECHNICAL_DEBT.md
sed -i '' 's/ *(#[0-9]*)//g' TECHNICAL_DEBT.md
```

**Step 2: Replace NIC references**

```bash
cd ~/Vibe/PIC
sed -i '' 's/NIC_/PIC_/g' TECHNICAL_DEBT.md
sed -i '' 's/src\/nic\//src\/pic\//g' TECHNICAL_DEBT.md
sed -i '' 's/masa-57\/NIC/masa-57\/pic/g' TECHNICAL_DEBT.md
```

**Step 3: Review manually**

Open `TECHNICAL_DEBT.md` and verify:
- No GitHub issue links remain
- No `NIC` references remain (except historical context if needed)
- File paths use `src/pic/`
- Env vars use `PIC_*`

**Step 4: Commit — sanitize technical debt**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: sanitize TECHNICAL_DEBT.md for public repo (remove issue links, rename NIC -> PIC)"
```

---

## Task 14: Create LICENSE

**Files:**
- Create: `LICENSE`

**Step 1: Create MIT license file**

Write `LICENSE` with this content:

```
MIT License

Copyright (c) 2026 Masoud Ahanchian

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

**Step 2: Verify**

```bash
test -f ~/Vibe/PIC/LICENSE && echo "OK: LICENSE exists"
head -3 ~/Vibe/PIC/LICENSE
```

**Step 3: Commit — add LICENSE**

```bash
cd ~/Vibe/PIC
git add LICENSE
git commit -m "chore: add MIT license"
```

---

## Task 15: Create CONTRIBUTING.md

**Files:**
- Create: `CONTRIBUTING.md`

**Step 1: Write CONTRIBUTING.md**

Content should cover:
- Prerequisites (Python 3.12, uv, Docker, PostgreSQL with pgvector)
- Development setup (clone, uv sync, docker compose, migrations)
- Code style (ruff check, ruff format, mypy)
- Testing (unit, integration, e2e markers and how to run each)
- PR process (branch, test, lint, submit)
- Reference to CODE_OF_CONDUCT.md

**Step 2: Commit — add CONTRIBUTING.md**

```bash
cd ~/Vibe/PIC
git add CONTRIBUTING.md
git commit -m "docs: add CONTRIBUTING.md"
```

---

## Task 16: Create CHANGELOG.md

**Files:**
- Create: `CHANGELOG.md`

**Step 1: Write CHANGELOG.md**

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-02-24

### Added
- Initial open-source release of PIC (Product Image Clustering)
- Two-level hierarchical clustering: pHash L1 (near-duplicates) + DINOv2/HDBSCAN L2 (semantic similarity)
- FastAPI REST API with search, clustering, pipeline, and product endpoints
- Modal serverless GPU workers for embedding and clustering workloads
- Google Drive sync integration for automated image ingestion
- PostgreSQL with pgvector backend for vector similarity search
- S3-compatible object storage (tested with Cloudflare R2 and MinIO)
- Pipeline API for end-to-end processing (discover, deduplicate, ingest, cluster)
- API key authentication with configurable rate limiting
- Docker and Docker Compose support for local development
- Comprehensive test suite (unit, integration, e2e markers)

> PIC was originally developed as an internal project (NIC). This is the first public release.
```

**Step 2: Commit — add CHANGELOG.md**

```bash
cd ~/Vibe/PIC
git add CHANGELOG.md
git commit -m "docs: add CHANGELOG.md"
```

---

## Task 17: Create SECURITY.md

**Files:**
- Create: `SECURITY.md`

**Step 1: Write SECURITY.md**

Content should cover:
- Supported versions (0.1.x)
- Reporting vulnerabilities (email, not public issues)
- Response timeline expectations
- Security best practices for deployment

**Step 2: Commit — add SECURITY.md**

```bash
cd ~/Vibe/PIC
git add SECURITY.md
git commit -m "docs: add SECURITY.md"
```

---

## Task 18: Create CODE_OF_CONDUCT.md

**Files:**
- Create: `CODE_OF_CONDUCT.md`

**Step 1: Write CODE_OF_CONDUCT.md**

Use the Contributor Covenant v2.1 standard text.

**Step 2: Commit — add CODE_OF_CONDUCT.md**

```bash
cd ~/Vibe/PIC
git add CODE_OF_CONDUCT.md
git commit -m "docs: add CODE_OF_CONDUCT.md (Contributor Covenant v2.1)"
```

---

## Task 19: Create ROADMAP.md

**Files:**
- Create: `ROADMAP.md`

**Step 1: Write ROADMAP.md**

Content:
- **Worker Abstraction Layer (Modal Decoupling)** — Highest priority. Create a `WorkerDispatcher` protocol so GPU workloads can run on platforms other than Modal (Celery+Redis, AWS Batch, Kubernetes Jobs, Ray). Research needed: evaluate Celery vs Dramatiq vs custom protocol. Currently Modal is tightly coupled in `modal_app.py` and `modal_dispatch.py`.
- **URL-based Image Ingestion** — Accept image URLs directly via API (download, validate, process).
- **Configurable Image Source Backends** — Support GCS, Azure Blob, local filesystem in addition to S3-compatible.
- **Multi-model Embedding Support** — CLIP, SigLIP as alternatives to DINOv2.
- **Webhook Notifications** — Notify external services on job completion.
- **Batch API** — Process large image sets with progress tracking.

**Step 2: Commit — add ROADMAP.md**

```bash
cd ~/Vibe/PIC
git add ROADMAP.md
git commit -m "docs: add ROADMAP.md"
```

---

## Task 20: Create Deployment Documentation

**Files:**
- Create: `docs/deployment/architecture.md`
- Create: `docs/deployment/modal-setup.md`
- Create: `docs/deployment/self-hosted.md`

**Step 1: Create docs/deployment/ directory**

```bash
mkdir -p ~/Vibe/PIC/docs/deployment
```

**Step 2: Write architecture.md**

Platform-neutral architecture document covering:
- Components: API server (FastAPI), GPU workers (Modal), object storage (S3-compatible), PostgreSQL+pgvector
- Data flow: upload -> store in S3 -> process (embed+hash) -> store vectors -> cluster
- How components connect (env vars, shared DB, S3)
- Reference deployments: Docker Compose (local), Railway+Modal (current), custom

**Step 3: Write modal-setup.md**

Modal-specific setup:
- Create Modal account and workspace
- Create `pic-env` secret with all `PIC_*` env vars
- Deploy: `modal deploy src/pic/modal_app.py`
- Verify cron (GDrive check every 15 min)
- GPU selection and memory configuration

**Step 4: Write self-hosted.md**

Running without Modal:
- Worker entrypoint directly (local GPU)
- Docker Compose with GPU support
- Background process alternative to Modal cron
- Required env vars for workers

**Step 5: Commit — add deployment docs**

```bash
cd ~/Vibe/PIC
git add docs/deployment/
git commit -m "docs: add deployment documentation (architecture, Modal setup, self-hosted)"
```

---

## Task 21: Rewrite README.md

**Files:**
- Modify: `README.md`

**Step 1: Full rewrite**

The README should cover:
- Project name and description: "PIC - Product Image Clustering"
- One-paragraph summary of what it does
- Features list (two-level clustering, REST API, GPU workers, etc.)
- Quick start (prerequisites, clone, uv sync, docker compose, run)
- Architecture diagram (text-based)
- API overview (key endpoints)
- Configuration (env vars table with `PIC_*`)
- Deployment options (link to docs/deployment/)
- Contributing (link to CONTRIBUTING.md)
- License (MIT)

Remove ALL references to:
- "cake images" -> "product images"
- NIC -> PIC
- Internal tooling, Claude Code, debt tracking

**Step 2: Verify**

```bash
cd ~/Vibe/PIC
grep -in "nic\|cake" README.md
```

Expected: zero matches.

**Step 3: Commit — rewrite README**

```bash
cd ~/Vibe/PIC
git add README.md
git commit -m "docs: rewrite README.md for PIC open-source release"
```

---

## Task 22: Rewrite AGENTS.md

**Files:**
- Modify: `AGENTS.md`

**Step 1: Rewrite for PIC**

Update the entire file:
- All NIC -> PIC
- All `src/nic/` -> `src/pic/`
- All `NIC_*` -> `PIC_*`
- Remove references to internal tooling (debt_sync, .claude/, Claude-specific notes)
- Remove references to debt tracking commands
- Update commands: `uv run mypy src/pic/`, `modal deploy src/pic/modal_app.py`, etc.
- Remove "cake images" -> "product images"
- Remove internal issue references

**Step 2: Verify**

```bash
cd ~/Vibe/PIC
grep -in "NIC\|cake\|debt_sync\|\.claude" AGENTS.md
```

Expected: zero matches.

**Step 3: Commit — rewrite AGENTS.md**

```bash
cd ~/Vibe/PIC
git add AGENTS.md
git commit -m "docs: rewrite AGENTS.md for PIC"
```

---

## Task 23: Update Alembic Migration Files

**Files:**
- Modify: `src/pic/migrations/env.py`
- Review: `src/pic/migrations/versions/*.py`

**Step 1: Check migration env.py for NIC references**

```bash
cd ~/Vibe/PIC
grep -n "nic\|NIC" src/pic/migrations/env.py
```

Update any `from nic.` imports (should have been caught by Task 4, but verify).

**Step 2: Check migration version files**

```bash
cd ~/Vibe/PIC
grep -rn "nic\|NIC" src/pic/migrations/versions/
```

Migration files should generally NOT be edited (they represent historical schema changes), but fix any Python imports that reference `nic.` (these would break at runtime).

**Step 3: Commit if changes needed**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: update Alembic migration imports for PIC" --allow-empty
```

---

## Task 24: Full Grep Verification

**Files:** All files in the repo

**Step 1: Check for uppercase NIC**

```bash
cd ~/Vibe/PIC
grep -rn "NIC" --include="*.py" --include="*.yml" --include="*.md" --include="*.toml" --include="*.ini" --include="*.json" --include="*.sh" --include="*.yaml" . | grep -v "CHANGELOG.md" | grep -v node_modules
```

Expected: zero matches (CHANGELOG.md is the only allowed mention of NIC for historical context).

**Step 2: Check for NIC_ env var prefix**

```bash
cd ~/Vibe/PIC
grep -rn "NIC_" --include="*.py" --include="*.yml" --include="*.env*" --include="*.md" --include="*.toml" .
```

Expected: zero matches.

**Step 3: Check for `from nic.` imports**

```bash
cd ~/Vibe/PIC
grep -rn "from nic\." --include="*.py" .
```

Expected: zero matches.

**Step 4: Check for `"nic"` string literals**

```bash
cd ~/Vibe/PIC
grep -rn '"nic"' --include="*.py" .
```

Expected: zero matches.

**Step 5: Check for src/nic path references**

```bash
cd ~/Vibe/PIC
grep -rn "src/nic" . --include="*.py" --include="*.yml" --include="*.md" --include="*.toml" --include="*.ini" --include="*.cfg"
```

Expected: zero matches.

**Step 6: Check for `nic-env` (Modal secret name)**

```bash
cd ~/Vibe/PIC
grep -rn "nic-env" .
```

Expected: zero matches.

**Step 7: Check for `nic-images` (S3 bucket)**

```bash
cd ~/Vibe/PIC
grep -rn "nic-images\|nic_images\|nic-local" .
```

Expected: zero matches.

**Step 8: Fix any findings and re-verify**

If any matches are found, fix them and re-run the check. Repeat until all clean.

**Step 9: Commit any fixes**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "chore: fix remaining NIC references found in verification" --allow-empty
```

---

## Task 25: Run Lint and Format Checks

**Files:** None (verification only)

**Step 1: Install dependencies**

```bash
cd ~/Vibe/PIC
uv sync --extra ml
```

**Step 2: Run ruff check**

```bash
cd ~/Vibe/PIC
uv run ruff check src/ tests/ scripts/
```

Expected: clean (zero errors). Fix any issues found.

**Step 3: Run ruff format check**

```bash
cd ~/Vibe/PIC
uv run ruff format --check src/ tests/ scripts/
```

Expected: clean. If not, run `uv run ruff format src/ tests/ scripts/` to fix.

**Step 4: Run mypy**

```bash
cd ~/Vibe/PIC
uv run mypy src/pic/ --ignore-missing-imports
```

Expected: clean (zero errors). Fix any import path issues.

**Step 5: Commit any fixes**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "fix: resolve lint and type check issues after rename" --allow-empty
```

---

## Task 26: Run Unit Tests

**Files:** None (verification only)

**Step 1: Run unit tests**

```bash
cd ~/Vibe/PIC
uv run pytest -m unit -v
```

Expected: all tests pass. If any fail due to import paths or renamed references, fix them.

**Step 2: Fix any failures**

Common issues:
- Mock paths still using `nic.` instead of `pic.`
- Env var names in test fixtures still using `NIC_*`
- Import errors from missed renames

**Step 3: Commit any fixes**

```bash
cd ~/Vibe/PIC
git add -A
git commit -m "fix: resolve test failures after rename" --allow-empty
```

---

## Task 27: Docker Build Verification

**Files:** None (verification only)

**Step 1: Build Railway Docker image**

```bash
cd ~/Vibe/PIC
docker build -f Dockerfile.railway -t pic-api:test .
```

Expected: builds successfully.

**Step 2: Build standard Docker image**

```bash
cd ~/Vibe/PIC
docker build -f Dockerfile -t pic-api:full .
```

Expected: builds successfully.

**Step 3: Verify the image runs**

```bash
cd ~/Vibe/PIC
docker run --rm -e PORT=8000 -p 8000:8000 pic-api:test &
sleep 5
curl -s http://localhost:8000/health | head -1
docker stop $(docker ps -q --filter ancestor=pic-api:test)
```

Expected: health endpoint responds.

**Step 4: Commit — no changes expected here**

This is verification only. If Docker build fails, fix the issue and commit the fix.

---

## Task 28: Verify All Required Files Exist

**Files:** None (verification only)

**Step 1: Check all required open-source files**

```bash
cd ~/Vibe/PIC
for f in LICENSE CONTRIBUTING.md CHANGELOG.md SECURITY.md CODE_OF_CONDUCT.md ROADMAP.md README.md AGENTS.md TECHNICAL_DEBT.md; do
  test -f "$f" && echo "OK: $f" || echo "MISSING: $f"
done
```

**Step 2: Check deployment docs**

```bash
cd ~/Vibe/PIC
for f in docs/deployment/architecture.md docs/deployment/modal-setup.md docs/deployment/self-hosted.md; do
  test -f "$f" && echo "OK: $f" || echo "MISSING: $f"
done
```

Expected: all OK.

---

## Task 29: Final Review and Squash (Optional)

**Step 1: Review git log**

```bash
cd ~/Vibe/PIC
git log --oneline
```

**Step 2: Optionally squash into a single initial commit**

If you want a cleaner single-commit history for the public repo:

```bash
cd ~/Vibe/PIC
git reset --soft $(git rev-list --max-parents=0 HEAD)
git commit -m "Initial release of PIC (Product Image Clustering) v0.1.0"
```

Or keep the detailed commit history — both are valid since it's a fresh repo.

**Step 3: Tag the release**

```bash
cd ~/Vibe/PIC
git tag -a v0.1.0 -m "Initial open-source release"
```

---

## Task 30: Publish to GitHub

> **Note:** This task requires manual GitHub interaction for repo creation.

**Step 1: Create GitHub repository**

Go to GitHub and create `masa-57/pic` (public, empty, no README/LICENSE/gitignore).

**Step 2: Push**

```bash
cd ~/Vibe/PIC
git remote add origin git@github.com:masa-57/pic.git
git push -u origin main
git push --tags
```

**Step 3: Configure repository**

- Enable branch protection on `main` (require PR, require CI)
- Enable Dependabot (security updates)
- Enable GitHub Discussions
- Add topics: `image-clustering`, `computer-vision`, `fastapi`, `dinov2`, `product-images`, `pgvector`

**Step 4: Create GitHub Release**

```bash
gh release create v0.1.0 --title "v0.1.0 — Initial Release" --notes-file CHANGELOG.md
```

---

## Task 31: Post-Publication (Production Migration)

> **Note:** These are operational tasks to be done after the repo is public.

**Step 1: Archive NIC repo**

- Add redirect notice to NIC README: "This project has moved to [pic](https://github.com/masa-57/pic)"
- Archive the NIC repo on GitHub (Settings -> Archive)

**Step 2: Create Modal secret**

Create `pic-env` secret in Modal with all `PIC_*` env vars (same values as current `NIC_*` vars, just renamed).

**Step 3: Deploy Modal app**

```bash
cd ~/Vibe/PIC
modal deploy src/pic/modal_app.py
```

Verify cron job is running:
```bash
modal app list
```

**Step 4: Update Railway**

- Point Railway service to new `pic` repo
- Update all env vars from `NIC_*` to `PIC_*`
- Verify auto-deploy triggers

**Step 5: Rotate production secrets**

After confirming everything works on the new repo:
- Rotate Neon PostgreSQL password
- Rotate R2 access keys
- Generate new API key
- Update all secrets in Modal and Railway

---

## Summary

| Task | Description | Commit Message |
|------|-------------|----------------|
| 1 | Prepare working copy | `chore: initial copy from NIC (pre-rename)` |
| 2 | Remove internal files | `chore: remove internal files (infra, .claude, audit, plans, debt tooling)` |
| 3 | Rename package directory | `chore: rename package directory src/nic -> src/pic` |
| 4 | Bulk rename Python imports | `chore: rename all Python imports from nic -> pic` |
| 5 | Rename config and core files | `chore: rename config env prefix NIC_ -> PIC_, Modal app nic -> pic` |
| 6 | Rename main.py | `chore: rename NIC references in main.py` |
| 7 | Rename build/infra files | `chore: rename NIC -> PIC in build, Docker, compose, Makefile, env example` |
| 8 | Rename CI/CD workflows | `chore: rename NIC -> PIC in CI/CD workflows, remove debt automation` |
| 9 | Rename test contents | `chore: rename NIC -> PIC in test files (env vars, mock paths, DB names)` |
| 10 | Rename scripts | `chore: rename NIC -> PIC in scripts` |
| 11 | Rename remaining source | `chore: clean up remaining NIC references in source code` |
| 12 | Rename documentation | `chore: rename NIC -> PIC in documentation and .gitignore cleanup` |
| 13 | Sanitize TECHNICAL_DEBT.md | `chore: sanitize TECHNICAL_DEBT.md for public repo` |
| 14 | Create LICENSE | `chore: add MIT license` |
| 15 | Create CONTRIBUTING.md | `docs: add CONTRIBUTING.md` |
| 16 | Create CHANGELOG.md | `docs: add CHANGELOG.md` |
| 17 | Create SECURITY.md | `docs: add SECURITY.md` |
| 18 | Create CODE_OF_CONDUCT.md | `docs: add CODE_OF_CONDUCT.md` |
| 19 | Create ROADMAP.md | `docs: add ROADMAP.md` |
| 20 | Create deployment docs | `docs: add deployment documentation` |
| 21 | Rewrite README.md | `docs: rewrite README.md for PIC open-source release` |
| 22 | Rewrite AGENTS.md | `docs: rewrite AGENTS.md for PIC` |
| 23 | Update Alembic migrations | `chore: update Alembic migration imports for PIC` |
| 24 | Full grep verification | `chore: fix remaining NIC references found in verification` |
| 25 | Lint and format checks | `fix: resolve lint and type check issues after rename` |
| 26 | Run unit tests | `fix: resolve test failures after rename` |
| 27 | Docker build verification | (verification only) |
| 28 | Verify required files | (verification only) |
| 29 | Final review and tag | `Initial release of PIC v0.1.0` |
| 30 | Publish to GitHub | (manual) |
| 31 | Post-publication migration | (operational) |
