# Improving Code Quality & Preventing Audit Issues in Claude Code

## Your Core Problem

Every time Claude Code makes changes, project audits flag many issues across domains. The root cause is that **Claude Code follows advisory instructions (CLAUDE.md) but has no deterministic enforcement**. Your CLAUDE.md tells Claude what to do, but nothing _forces_ compliance. The solution is a layered defense: tighten the CLAUDE.md, add deterministic hooks, connect relevant MCP servers, and create custom skills that bake quality checks into every workflow.

---

## Layer 1: Claude Code Hooks (Highest Impact)

Hooks are shell commands that run automatically at specific points in Claude Code's lifecycle. Unlike CLAUDE.md instructions which are advisory, **hooks are deterministic** — they guarantee the action happens every time.

### Recommended Hooks for Your Project

Add these to `.claude/settings.json` in your project root:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "FILE=$(echo $CLAUDE_TOOL_INPUT | jq -r '.file_path // empty'); if [[ \"$FILE\" == *.py ]]; then cd \"$CLAUDE_PROJECT_DIR\" && uv run ruff check --fix \"$FILE\" 2>&1 | head -20 && uv run ruff format \"$FILE\" 2>&1 | head -5; fi",
            "timeout": 30
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "COMMAND=$(echo $CLAUDE_TOOL_INPUT | jq -r '.command'); if echo \"$COMMAND\" | grep -qE 'git\\s+(commit|push.*\\smain|push.*origin\\s+main)'; then echo '{\"decision\":\"block\",\"reason\":\"Direct commits/pushes to main are blocked. Use a feature branch.\"}'; exit 0; fi; echo '{\"decision\":\"approve\"}'",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**What this does:**
- **PostToolUse (Edit|Write)**: Every time Claude edits or creates a `.py` file, ruff automatically lints and formats it. Issues are caught immediately, not at audit time.
- **PreToolUse (Bash)**: Blocks direct commits/pushes to `main`, enforcing feature branches.

### Additional Hooks to Consider

| Hook | Event | Purpose |
|------|-------|---------|
| Auto-typecheck | PostToolUse (Edit\|Write on *.py) | Run `uv run mypy` on changed files |
| Test runner | PostToolUse (Edit on src/**/*.py) | Run `uv run pytest -m unit -x` after source changes |
| Security scan | PreToolUse (Bash with `git commit`) | Run `pip-audit` or check for secrets before commits |
| Compaction reminder | SessionStart (compact) | Re-inject critical project rules after context compaction |

### SessionStart Hook for Context Preservation

This is critical for long sessions — when Claude's context compacts, it can forget your rules:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "compact",
        "hooks": [
          {
            "type": "command",
            "command": "echo 'REMINDER: Always run uv run ruff check && uv run mypy src/nic/ --ignore-missing-imports && uv run pytest -m unit before committing. Use async everywhere. DB has_embedding is integer 0/1 not boolean. Never push Docker images locally.'"
          }
        ]
      }
    ]
  }
}
```

---

## Layer 2: Improve Your CLAUDE.md

Your current CLAUDE.md is good but can be strengthened. Key principles from the research:

### Keep It Focused
The research shows Claude can follow ~150-200 instructions reliably. Your CLAUDE.md is reasonably sized, but every line should pass the test: "Would removing this cause Claude to make mistakes?"

### Add Explicit Quality Gates
Add a section like this to your CLAUDE.md:

```markdown
## Quality Gates (MUST follow before every commit)

**IMPORTANT: Run ALL checks before committing. Do NOT commit if any check fails.**

1. `uv run ruff check src/ tests/ scripts/` — zero errors
2. `uv run ruff format --check src/ tests/ scripts/` — zero formatting issues
3. `uv run mypy src/nic/ --ignore-missing-imports` — zero type errors
4. `uv run pytest -m unit` — all tests pass
5. `uv run pip-audit` — no known vulnerabilities

## Code Standards (MUST follow)

- Every new endpoint MUST have unit tests
- Every new service function MUST have type hints on all parameters and return values
- Every new API route MUST include proper error handling (try/except with appropriate HTTP status codes)
- Every database query MUST use parameterized queries (SQLAlchemy handles this, but never use raw f-strings for SQL)
- NEVER add TODO/FIXME without creating a corresponding GitHub issue
- NEVER import from internal modules using relative imports across package boundaries
- NEVER catch bare `except:` — always catch specific exceptions
```

### Use Emphasis for Critical Rules
The research confirms that adding "IMPORTANT", "MUST", or "NEVER" to critical rules improves adherence.

---

## Layer 3: Custom Skills

Skills are on-demand instruction sets that Claude loads when relevant. Unlike CLAUDE.md (always loaded), skills keep your main context lean.

### Recommended Skills to Create

#### 1. Quality Check Skill (`.claude/skills/quality-check/SKILL.md`)

```markdown
---
name: quality-check
description: Run full project quality checks. Use when finishing a feature, before committing, or when asked to verify code quality.
---

# Quality Check Procedure

Run these checks in order. Stop and fix issues before proceeding to the next step.

## Step 1: Lint
```bash
uv run ruff check src/ tests/ scripts/
```
Fix all errors before continuing.

## Step 2: Format
```bash
uv run ruff format src/ tests/ scripts/
```

## Step 3: Type Check
```bash
uv run mypy src/nic/ --ignore-missing-imports
```
Fix all type errors.

## Step 4: Unit Tests
```bash
uv run pytest -m unit --tb=short
```
All tests must pass.

## Step 5: Security Audit
```bash
uv run pip-audit
```

## Step 6: Coverage Check
```bash
uv run pytest -m unit --cov=src/nic --cov-report=term --cov-fail-under=70
```

Report results summary to the user.
```

#### 2. New Endpoint Skill (`.claude/skills/new-endpoint/SKILL.md`)

```markdown
---
name: new-endpoint
description: Create a new API endpoint following project conventions. Use when adding routes to the FastAPI application.
---

# New Endpoint Checklist

When creating a new endpoint:

1. Add the route in `src/nic/api/` following existing patterns
2. Use async def for all handlers
3. Add proper Pydantic request/response schemas in `src/nic/models/schemas.py`
4. Add the router to `src/nic/api/router.py`
5. Include error handling with appropriate HTTP status codes
6. Add unit tests in `tests/` with the `@pytest.mark.unit` marker
7. Add integration tests if the endpoint touches the database
8. Ensure the endpoint is behind API key auth (all /api/v1/* routes)
9. Run /quality-check before committing
```

#### 3. Pre-commit Skill (`.claude/skills/pre-commit/SKILL.md`)

```markdown
---
name: pre-commit
description: Run before committing code. Validates all quality gates pass.
---

# Pre-Commit Verification

Before committing, run ALL of the following. If any fail, fix before committing:

```bash
uv run ruff check src/ tests/ scripts/
uv run ruff format --check src/ tests/ scripts/
uv run mypy src/nic/ --ignore-missing-imports
uv run pytest -m unit -x
```

Commit message format: `type: description` where type is one of:
feat, fix, refactor, test, docs, chore, ci

Example: `feat: add bulk product creation endpoint`
```

---

## Layer 4: MCP Servers

### GitHub MCP Server (Recommended)

Connect Claude Code directly to your GitHub repo for issue management, PR creation, and CI/CD visibility:

```bash
claude mcp add -s user --transport http github \
  https://api.githubcopilot.com/mcp \
  -H "Authorization: Bearer YOUR_GITHUB_PAT"
```

**Why it matters for quality**: Claude can check CI status, create issues for problems it finds, create PRs with proper descriptions, and see if tests passed in CI before considering a task done.

### Context7 MCP Server (Recommended)

Gives Claude access to up-to-date documentation for your dependencies (FastAPI, SQLAlchemy, Pydantic, etc.):

```bash
claude mcp add context7 -- npx -y @upstash/context7-mcp@latest
```

**Why it matters for quality**: Reduces hallucinated API usage. Claude will use current, correct APIs instead of guessing from training data.

### Sequential Thinking MCP Server (Optional)

Helps Claude break down complex tasks before implementing:

```bash
claude mcp add sequential-thinking -- npx -y @modelcontextprotocol/server-sequential-thinking
```

---

## Layer 5: Strengthen CI/CD as the Final Gate

Your CI already runs lint, type check, and tests. Make it stricter:

### Add to `.github/workflows/ci-cd.yml`:

```yaml
# Add these as required status checks in GitHub branch protection
- name: Security audit
  run: uv run pip-audit

- name: Coverage threshold
  run: uv run pytest -m unit --cov=src/nic --cov-fail-under=70

- name: No TODO without issue
  run: |
    # Fail if there are TODOs without issue references
    if grep -rn 'TODO\|FIXME' src/nic/ --include='*.py' | grep -v '#.*[A-Z]\+-[0-9]'; then
      echo "Found TODOs without issue references"
      exit 1
    fi
```

### Enable GitHub Branch Protection
- Require PR reviews (even self-review forces a pause)
- Require status checks to pass before merging
- Require branches to be up to date before merging

---

## Layer 6: Plugins Worth Installing

### audit-project Plugin (Composio)

```bash
git clone https://github.com/ComposioHQ/awesome-claude-plugins.git
cd awesome-claude-plugins
claude --plugin-dir ./audit-project
```

This gives you `/audit-project` — a comprehensive audit command you can run proactively rather than reactively.

### claudekit (Carl Rannaberg)

Provides auto-save checkpointing, code quality hooks, and specialized subagents including a code-reviewer with 6-aspect deep analysis. Good for solo developers who need a "second pair of eyes."

### cc-tools (Josh Symonds)

High-performance Go implementation of Claude Code hooks and utilities. Provides smart linting, testing, and statusline generation with minimal overhead.

---

## Recommended Implementation Order

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| 1 | Add PostToolUse hooks for ruff lint/format | 10 min | **Very High** — catches issues instantly |
| 2 | Add quality gates section to CLAUDE.md | 10 min | **High** — sets expectations |
| 3 | Create `/quality-check` skill | 15 min | **High** — one-command full verification |
| 4 | Add SessionStart compact hook | 5 min | **High** — prevents rule forgetting in long sessions |
| 5 | Install GitHub MCP server | 10 min | **Medium** — better git workflow |
| 6 | Install Context7 MCP server | 5 min | **Medium** — reduces API hallucinations |
| 7 | Create `/new-endpoint` and `/pre-commit` skills | 20 min | **Medium** — standardizes workflows |
| 8 | Strengthen CI with coverage + audit | 15 min | **Medium** — catches what local checks miss |
| 9 | Enable branch protection on GitHub | 5 min | **Medium** — prevents direct main pushes |
| 10 | Install audit-project plugin | 10 min | **Low-Medium** — proactive auditing |

---

## Key Insight

The fundamental shift is from **reactive** (audit finds problems after the fact) to **proactive** (problems are prevented or caught at the moment they're introduced). The hooks are the most important piece because they're deterministic — Claude can't ignore them the way it sometimes ignores CLAUDE.md instructions. Combined with skills that standardize workflows and CI that acts as the final safety net, you'll dramatically reduce the number of issues found during audits.
