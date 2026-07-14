# Plan

## Intent

Improve repository organisation and workflow efficiency by restructuring the root directory, enabling true parallel development via git worktrees, and streamlining the agent workflow — advancing the North Star of continuous, unblocked agent-assisted development.

## Plan Type

IMPLEMENTATION

## Branch

agent/infra-repo-restructure

## Phase

Infrastructure (workflow self-improvement)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `docs/` | Create | New documentation folder |
| `docs/plans/` | Create | Subfolder for plan files |
| `logs/` | Create | New folder for JSONL tracking files |
| `docs/AGENT_WORKFLOW.md` | Move | Relocate from root |
| `docs/ARCHITECTURE.md` | Move | Relocate from root |
| `docs/CHANGELOG.md` | Move | Relocate from root |
| `docs/DECISIONS.md` | Move | Relocate from root |
| `docs/GETTING_STARTED.md` | Move | Relocate from root |
| `docs/RECOMMENDATIONS.md` | Move | Relocate from root |
| `docs/ROADMAP.md` | Move | Relocate from root |
| `docs/SESSION_LOG.md` | Move | Relocate from root |
| `docs/CRON_REVIEW_SUMMARY.md` | Move | Relocate from root |
| `logs/.retro-lite-log.jsonl` | Move | Relocate from root |
| `logs/.session-metrics-log.jsonl` | Move | Relocate from root |
| `logs/.recommendations-log.jsonl` | Move | Relocate from root |
| `logs/.rejected-suggestions.jsonl` | Move | Relocate from root |
| `logs/.decisions-index.jsonl` | Move | Relocate from root |
| `logs/.customizations-manifest.json` | Move | Relocate from root |
| `PLAN.md` | Delete | Remove legacy plan file from root |
| `.github/copilot_instructions.md` | Modify | Update File Router paths, add worktree guidance |
| `.github/prompts/plan.prompt.md` | Modify | Update paths, change SSO to direct login, add worktree setup, fix confirmation loop |
| `.github/prompts/implement.prompt.md` | Modify | Update paths, add pre-commit validation step |
| `.github/prompts/session_close.prompt.md` | Modify | Update paths |
| `.github/prompts/cron_review.prompt.md` | Modify | Update paths |
| `.github/prompts/strategic_review.prompt.md` | Modify | Update paths |
| `.github/prompts/ci_triage.prompt.md` | Modify | Update paths |
| `.github/agents/code-review.agent.md` | Modify | Update paths |
| `.github/agents/plan-critique.agent.md` | Modify | Update paths |
| `.github/agents/scope-guard.agent.md` | Modify | Update paths |
| `.github/agents/pre-commit-sanity.agent.md` | Modify | Update paths |
| `.github/agents/step-validator.agent.md` | Modify | Update paths |
| `.github/agents/retro-lite.agent.md` | Modify | Update paths |
| `.github/agents/retrospective.agent.md` | Modify | Update paths |
| `.github/agents/prompt-reviewer.agent.md` | Modify | Update paths |
| `scripts/run_retro_lite.py` | Modify | Update LOG_FILE path to `logs/` |
| `scripts/run_cron_review.py` | Modify | Update all file paths to new locations |
| `scripts/list_customizations.py` | Modify | Update MANIFEST, DECISIONS_INDEX, DECISIONS_FILE paths |
| `scripts/plan_audit.py` | Modify | Update plan file search to `docs/plans/`, update find_plan_file() |
| `scripts/session_metrics.py` | Modify | Update LOG_FILE path to `logs/` |
| `scripts/north_star_tracker.py` | Modify | Update SESSION_LOG path to `docs/` |
| `scripts/friction_analysis.py` | Modify | Update LOG_FILE path to `logs/` |
| `scripts/metrics_analysis.py` | Modify | Update LOG_FILE path to `logs/` |
| `scripts/migrate_recommendations.py` | Modify | Update RECOMMENDATIONS_MD and RECOMMENDATIONS_LOG paths |
| `.gitignore` | Modify | Add `.ruff_cache/`, update cron review temp paths to `logs/` |
| `docs/DECISIONS.md` | Modify | Add Decision 25 for worktree workflow |
| `README.md` | Modify | Update links to docs/ |
| `tests/test_plan_audit.py` | Modify | Update expected paths to `docs/plans/` |
| `tests/test_list_customizations.py` | Modify | Update expected manifest path to `logs/` |
| `tests/test_migrate_recommendations.py` | Modify | Update expected paths |

## Acceptance Criteria

- [ ] `docs/` folder contains: AGENT_WORKFLOW.md, ARCHITECTURE.md, CHANGELOG.md, DECISIONS.md, GETTING_STARTED.md, RECOMMENDATIONS.md, ROADMAP.md, SESSION_LOG.md, CRON_REVIEW_SUMMARY.md
- [ ] `docs/plans/` folder exists and is documented as the home for `PLAN-{slug}.md` files
- [ ] `logs/` folder contains all JSONL tracking files
- [ ] Legacy `PLAN.md` removed from root
- [ ] All prompts read/write to new paths
- [ ] All agents reference new paths
- [ ] All scripts read/write to new paths
- [ ] `/plan` runs `aws sso login` directly instead of checking credentials first
- [ ] `/plan` Step 7b confirmation loop is explicit (only "write the plan" proceeds; feedback triggers re-presentation)
- [ ] `/implement` runs pre-commit checks as part of validation
- [ ] `.ruff_cache/` is in `.gitignore`
- [ ] Worktree workflow documented in DECISIONS.md (Decision 25)
- [ ] Worktree setup instructions added to `/plan` prompt
- [ ] All internal markdown links updated to new paths
- [ ] `python scripts/validate.py` exits 0
- [ ] All tests pass with new paths
- [ ] This plan file moved to `docs/plans/` after implementation

## Constraints

- No renaming files — only relocating them
- Maintain backward compatibility for any in-flight work (check for legacy paths)
- All path updates must use forward slashes (cross-platform)
- No new Python dependencies required

## Context

**Why repo restructuring:**
- Root directory has 13 markdown files + 6 JSONL files = clutter
- Makes it hard to distinguish operational docs from code
- Plan files at root are visible but disorganised

**Why worktrees were overlooked in previous plan:**
The previous PLAN.md (agent/infra-parallel-workflow) stated Intent: "allowing multiple features to be planned and implemented concurrently without interference." However:
- The Scope only included: branch creation in `/plan`, branch-specific plan files, auto-merge
- No worktree setup was included in Ordered Execution Steps
- The implementation enabled **parallel planning** (via branch switches) but not **parallel implementation**
- True concurrent implementation requires git worktrees so both features can be worked on simultaneously without checkout switching
- The oversight: focusing on plan-file isolation without addressing working-directory isolation

**Why `/plan` confirmation loop needs fixing:**
In the current implementation, Step 7b says "Does this approach look right? Say 'write the plan' when ready." However:
- Feedback from user (e.g., "no, I want X instead") was incorrectly interpreted as confirmation
- The agent proceeded to write the plan file without explicit "write the plan" confirmation
- Fix: Make the confirmation loop explicit — only the literal phrase "write the plan" proceeds; any other response triggers refinement and re-presentation

**DRY analysis of run_retro_lite.py vs run_cron_review.py:**
These scripts serve fundamentally different purposes and should NOT be consolidated:
- `run_retro_lite.py`: Single-entry append with validation/deduplication (~100 lines)
- `run_cron_review.py`: Two-phase pipeline with prepare → AI loop → merge (~300 lines)
- Shared patterns (argparse, JSONL handling, atomic writes) are minimal and don't justify abstraction
- Consolidation would create a confusing multi-purpose script

**Relevant decisions:**
- Decision 23: Parallel workflow with branch-specific plans — worktrees are the natural extension
- Python-only scripting — all path updates in Python scripts

**Files verified to have NO path dependencies on docs/logs (excluded from scope):**
- `setup.py` — only handles venv, dependencies, tool checks; no doc/log references
- `scripts/validate.py` — only references `.github/prompts/` for prompt validation; no doc/log refs
- `tests/test_config.py` — only tests config module; no doc/log path refs
- `docker/Dockerfile`, `docker/docker-compose.yml` — COPY paths reference code, not docs
- `personal_scripts/` — gitignored, personal tooling

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.

- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

> **Execute these in sequence. Do not substitute the Scope table as a work list.**

### Step 1: Create folder structure

Create the new directories:

```bash
mkdir -p docs/plans logs
```

Verify creation:

```bash
ls -la docs/ logs/
```

---

### Step 2: Move documentation files to `docs/`

Move all documentation markdown files from root to `docs/`:

```bash
git mv AGENT_WORKFLOW.md docs/
git mv ARCHITECTURE.md docs/
git mv CHANGELOG.md docs/
git mv DECISIONS.md docs/
git mv GETTING_STARTED.md docs/
git mv RECOMMENDATIONS.md docs/
git mv ROADMAP.md docs/
git mv SESSION_LOG.md docs/
git mv CRON_REVIEW_SUMMARY.md docs/
```

Verify moves:

```bash
ls docs/
```

Expected: AGENT_WORKFLOW.md, ARCHITECTURE.md, CHANGELOG.md, CRON_REVIEW_SUMMARY.md, DECISIONS.md, GETTING_STARTED.md, RECOMMENDATIONS.md, ROADMAP.md, SESSION_LOG.md

---

### Step 3: Move JSONL tracking files to `logs/`

Move all tracking files from root to `logs/`. Use `git mv` for all files — it will only succeed for files that exist and are tracked. Ignore errors for files that don't exist (some may not have been created yet if cron review hasn't run).

```bash
git mv .retro-lite-log.jsonl logs/ 2>/dev/null || true
git mv .session-metrics-log.jsonl logs/ 2>/dev/null || true
git mv .recommendations-log.jsonl logs/ 2>/dev/null || true
git mv .rejected-suggestions.jsonl logs/ 2>/dev/null || true
git mv .decisions-index.jsonl logs/ 2>/dev/null || true
git mv .customizations-manifest.json logs/ 2>/dev/null || true
```

Verify what was moved:

```bash
ls -la logs/
```

---

### Step 4: Remove legacy `PLAN.md` from root

The legacy `PLAN.md` at root should be removed — all new plans use `docs/plans/PLAN-{slug}.md`:

```bash
git rm PLAN.md 2>/dev/null || true
```

If `PLAN.md` doesn't exist, this command will silently succeed.

---

### Step 5: Update `.gitignore`

Add `.ruff_cache/` to the gitignore (it's currently missing) and update cron review temp file paths:

**Add to Testing section:**
```
.ruff_cache/
```

**Update cron review section:**
```
# Cron review temp files (generated by run_cron_review.py --prepare, removed by --merge)
logs/.cron-review-queue.json
logs/.cron-review-responses.json
```

---

### Step 6: Update `scripts/run_retro_lite.py`

Change `LOG_FILE` path from:
```python
LOG_FILE = REPO_ROOT / ".retro-lite-log.jsonl"
```
To:
```python
LOG_FILE = REPO_ROOT / "logs" / ".retro-lite-log.jsonl"
```

---

### Step 7: Update `scripts/run_cron_review.py`

Update all file path constants:
```python
QUEUE_FILE = REPO_ROOT / "logs" / ".cron-review-queue.json"
RESPONSES_FILE = REPO_ROOT / "logs" / ".cron-review-responses.json"
MANIFEST_FILE = REPO_ROOT / "logs" / ".customizations-manifest.json"
REJECTION_FILE = REPO_ROOT / "logs" / ".rejected-suggestions.jsonl"
RECOMMENDATIONS_FILE = REPO_ROOT / "logs" / ".recommendations-log.jsonl"
SUMMARY_FILE = REPO_ROOT / "docs" / "CRON_REVIEW_SUMMARY.md"
```

---

### Step 8: Update `scripts/list_customizations.py`

Update the manifest output path to `logs/`:
```python
MANIFEST_FILE = REPO_ROOT / "logs" / ".customizations-manifest.json"
```

Also update the decisions index path:
```python
DECISIONS_INDEX_FILE = REPO_ROOT / "logs" / ".decisions-index.jsonl"
```

And the DECISIONS.md source path:
```python
DECISIONS_FILE = REPO_ROOT / "docs" / "DECISIONS.md"
```

---

### Step 9: Update `scripts/plan_audit.py`

Update the `find_plan_file()` function to search in `docs/plans/` instead of root:
- Change plan file search from `REPO_ROOT / f"PLAN-{slug}.md"` to `REPO_ROOT / "docs" / "plans" / f"PLAN-{slug}.md"`
- Update legacy fallback from `REPO_ROOT / "PLAN.md"` to `REPO_ROOT / "docs" / "plans" / "PLAN.md"`

---

### Step 10: Update `scripts/session_metrics.py`

Update the log file path:
```python
LOG_FILE = REPO_ROOT / "logs" / ".session-metrics-log.jsonl"
```

---

### Step 11: Update `scripts/north_star_tracker.py`

Update the SESSION_LOG path:
```python
SESSION_LOG = REPO_ROOT / "docs" / "SESSION_LOG.md"
```

---

### Step 12: Update `scripts/friction_analysis.py`

Update the log file path:
```python
LOG_FILE = REPO_ROOT / "logs" / ".retro-lite-log.jsonl"
```

---

### Step 13: Update `scripts/metrics_analysis.py`

Update the log file path:
```python
LOG_FILE = REPO_ROOT / "logs" / ".session-metrics-log.jsonl"
```

---

### Step 14: Update `scripts/migrate_recommendations.py`

Update paths:
```python
RECOMMENDATIONS_MD = REPO_ROOT / "docs" / "RECOMMENDATIONS.md"
RECOMMENDATIONS_LOG = REPO_ROOT / "logs" / ".recommendations-log.jsonl"
```

---

### Step 15: Update `.github/copilot_instructions.md`

Update the File Router table — all documentation paths change from root to `docs/`:
- `ROADMAP.md` → `docs/ROADMAP.md`
- `DECISIONS.md` → `docs/DECISIONS.md`
- `ARCHITECTURE.md` → `docs/ARCHITECTURE.md`
- `GETTING_STARTED.md` → `docs/GETTING_STARTED.md`
- `SESSION_LOG.md` → `docs/SESSION_LOG.md`
- `AGENT_WORKFLOW.md` → `docs/AGENT_WORKFLOW.md`
- `CRON_REVIEW_SUMMARY.md` → `docs/CRON_REVIEW_SUMMARY.md`
- `RECOMMENDATIONS.md` → `docs/RECOMMENDATIONS.md`
- `CHANGELOG.md` → `docs/CHANGELOG.md`

Update plan file location:
- `PLAN-{slug}.md (repository root)` → `PLAN-{slug}.md (docs/plans/)`

Add worktree guidance to Known Gotchas section:
```markdown
- **Git worktrees for parallel development:** To work on multiple features simultaneously, use git worktrees instead of branch switching. Each worktree is a separate working directory with its own branch. Setup: `git worktree add ../agent-platform-{slug} agent/{slug}`. List: `git worktree list`. Remove after merge: `git worktree remove ../agent-platform-{slug}`. Worktrees share the `.git` folder, so commits/pushes work normally.
```

---

### Step 16: Update `.github/prompts/plan.prompt.md`

**16a: Update Step 2 (AWS SSO)** — Replace credential check with direct login:

Current:
```markdown
## Step 2: Verify SSO Session

```bash
aws sts get-caller-identity --profile company-aws-profile
```

If this fails, run `aws sso login --profile company-aws-profile` before proceeding.
```

New:
```markdown
## Step 2: Establish SSO Session

```bash
aws sso login --profile company-aws-profile
```

This opens a browser for SSO authentication. Wait for confirmation before proceeding.
```

**16b: Update Step 3 (Load Project Context)** — Update all file paths:
- `ROADMAP.md` → `docs/ROADMAP.md`
- `DECISIONS.md` → `docs/DECISIONS.md`
- `SESSION_LOG.md` → `docs/SESSION_LOG.md`
- `RECOMMENDATIONS.md` → `docs/RECOMMENDATIONS.md`

**16c: Update Step 3b (Cron Review Freshness)** — Update path:
- `CRON_REVIEW_SUMMARY.md` → `docs/CRON_REVIEW_SUMMARY.md`

**16d: Update Step 7b (Present Findings and Confirm Approach)** — Make the confirmation loop explicit:

Current Step 7b ends with:
```markdown
> "Does this approach look right? Say **'write the plan'** when you are ready, or tell me what to adjust."
```

Replace the entire Step 7b with:
```markdown
## Step 7b: Present Findings and Confirm Approach

Before writing the plan file, present your analysis to the human:

1. **Summary** -- Key findings from context loading (roadmap state, relevant decisions, open recommendations)
2. **Proposed approach** -- How you interpret the request and what you plan to include in the plan
3. **Options** (if applicable) -- Alternative approaches with trade-offs
4. **Open questions** (if any) -- Remaining ambiguities that affect scope

Then ask:
> "Does this approach look right? Say **'write the plan'** when you are ready, or tell me what to adjust."

**CONFIRMATION LOOP RULES:**
- **ONLY proceed to Step 8 if the human responds with exactly "write the plan"** (or clear equivalent like "yes, write it", "go ahead and write the plan")
- **Any other response is FEEDBACK, not confirmation.** If the human provides feedback, corrections, or additional requirements:
  1. Incorporate the feedback into your analysis
  2. Re-present the refined approach
  3. Ask again: "Does this updated approach look right? Say 'write the plan' when ready."
  4. Loop until explicit confirmation is given
- **Do NOT interpret feedback as implicit confirmation.** Phrases like "yes, but also X" or "no, I want Y instead" are requests for refinement, not approval to write.
```

**16e: Update Step 8 (Write Plan File)** — Change plan file location:
- Write to `docs/plans/PLAN-{slug}.md` instead of root
- Update commit command: `git add docs/plans/PLAN-{slug}.md`

**16f: Add Step 7c (Worktree Setup)** — After creating branch, offer worktree setup:

Insert after Step 7b (before Step 8):
```markdown
## Step 7c: Worktree Setup (Optional)

If you want to work on this feature in parallel with other features (without checkout switching), create a worktree:

```bash
git worktree add ../agent-platform-{slug} agent/{slug}
```

This creates a new working directory at `../agent-platform-{slug}` checked out to the feature branch. You can open this in a separate VS Code window.

**Skip this step if you prefer the traditional single-directory workflow.**
```

---

### Step 17: Update `.github/prompts/implement.prompt.md`

**17a: Update Step 1 (Read Plan File)** — Update plan file search path:
- Look in `docs/plans/PLAN-{slug}.md` instead of root

**17b: Add pre-commit validation to Step 4 (Validation)** — Add pre-commit as part of validation:

Add to the validation step:
```markdown
Before implementing, run pre-commit checks:

```bash
pre-commit run --all-files
```

If pre-commit fails, fix the issues before proceeding. Pre-commit hooks include:
- ruff (linting and formatting)
- trailing-whitespace
- end-of-file-fixer
- detect-secrets
```

**17c: Update all documentation references** — Any refs to DECISIONS.md, ROADMAP.md, etc.

---

### Step 18: Update `.github/prompts/session_close.prompt.md`

Update all paths:
- `RECOMMENDATIONS.md` → `docs/RECOMMENDATIONS.md`
- `SESSION_LOG.md` → `docs/SESSION_LOG.md`
- `CHANGELOG.md` → `docs/CHANGELOG.md`
- `.retro-lite-log.jsonl` → `logs/.retro-lite-log.jsonl`
- `.session-metrics-log.jsonl` → `logs/.session-metrics-log.jsonl`

---

### Step 19: Update `.github/prompts/cron_review.prompt.md`

Update paths:
- `CRON_REVIEW_SUMMARY.md` → `docs/CRON_REVIEW_SUMMARY.md`
- `.recommendations-log.jsonl` → `logs/.recommendations-log.jsonl`
- `.rejected-suggestions.jsonl` → `logs/.rejected-suggestions.jsonl`
- `.customizations-manifest.json` → `logs/.customizations-manifest.json`
- `.cron-review-queue.json` → `logs/.cron-review-queue.json`
- `.cron-review-responses.json` → `logs/.cron-review-responses.json`

---

### Step 20: Update `.github/prompts/strategic_review.prompt.md`

Update all documentation paths to `docs/` and log paths to `logs/`.

---

### Step 21: Update `.github/prompts/ci_triage.prompt.md`

Update any documentation references.

---

### Step 22: Update agent files

Update paths in each agent file. For each agent, update:
- PLAN.md references → `docs/plans/PLAN-{slug}.md`
- DECISIONS.md references → `docs/DECISIONS.md`
- RECOMMENDATIONS.md references → `docs/RECOMMENDATIONS.md`
- Log file references → `logs/` prefix

**22a: `.github/agents/code-review.agent.md`**
- Update plan file detection logic to look in `docs/plans/`
- Update any DECISIONS.md, RECOMMENDATIONS.md refs to `docs/`

**22b: `.github/agents/plan-critique.agent.md`**
- Update plan file path references to `docs/plans/`
- Update DECISIONS.md refs to `docs/`

**22c: `.github/agents/scope-guard.agent.md`**
- Update plan file detection to `docs/plans/`
- Update any doc refs

**22d: `.github/agents/pre-commit-sanity.agent.md`**
- Update plan file detection to `docs/plans/`
- Update any doc refs

**22e: `.github/agents/step-validator.agent.md`**
- Update plan file path to `docs/plans/`

**22f: `.github/agents/retro-lite.agent.md`**
- Update log file path to `logs/.retro-lite-log.jsonl`

**22g: `.github/agents/retrospective.agent.md`**
- Update log file paths to `logs/`
- Update doc paths to `docs/`

**22h: `.github/agents/prompt-reviewer.agent.md`**
- Update log/manifest references to `logs/`

---

### Step 23: Update `README.md`

Update links to documentation files:
- All `[GETTING_STARTED.md]` → `[docs/GETTING_STARTED.md]`
- All `[ARCHITECTURE.md]` → `[docs/ARCHITECTURE.md]`
- All `[ROADMAP.md]` → `[docs/ROADMAP.md]`
- All `[CHANGELOG.md]` → `[docs/CHANGELOG.md]`

---

### Step 24: Add Decision 25 to `docs/DECISIONS.md`

Add new decision entry:

```markdown
## Decision 25: Git Worktree Parallel Development Workflow (Decided)

**Context:** Decision 23 enabled parallel planning via branch-specific plan files (`PLAN-{slug}.md`). However, true concurrent implementation still required checkout switching between branches, blocking one feature while working on another.

**Decision:** Support git worktrees as the recommended approach for parallel feature development:

**Worktree workflow:**
1. `/plan` creates branch `agent/{slug}` and optionally sets up worktree at `../agent-platform-{slug}`
2. Developer opens worktree in separate VS Code window
3. Each window has its own working directory, branch, and plan file
4. Commits/pushes work normally (worktrees share `.git`)
5. After merge, worktree is removed: `git worktree remove ../agent-platform-{slug}`

**Benefits:**
- True parallel implementation: work on feature B while feature A is in code review
- No context switching: each feature has its own window/terminal state
- Clean separation: no risk of committing to wrong branch

**Trade-offs:**
- Disk space: each worktree is a full working copy (~50MB excluding .git)
- Cognitive load: must remember which window is which feature
- Tooling: some VS Code extensions may not handle multiple workspaces well

**Guidance:**
- Use worktrees for features expected to overlap (e.g., parallel planning + implementation)
- Use traditional checkout for sequential work (most common case)
- Always remove worktrees after merge to avoid clutter

**Status:** Decided — March 2026
```

---

### Step 25: Update test files

**25a: `tests/test_plan_audit.py`**
Update expected plan file paths:
- Change `REPO_ROOT / f"PLAN-{slug}.md"` expectations to `REPO_ROOT / "docs" / "plans" / f"PLAN-{slug}.md"`
- Update legacy fallback path expectations to `docs/plans/PLAN.md`

**25b: `tests/test_list_customizations.py`**
Update expected manifest path:
- Change `REPO_ROOT / ".customizations-manifest.json"` to `REPO_ROOT / "logs" / ".customizations-manifest.json"`
- Update decisions index path expectations to `logs/`

**25c: `tests/test_migrate_recommendations.py`**
Update expected paths:
- Change RECOMMENDATIONS_MD expectations to `docs/RECOMMENDATIONS.md`
- Change RECOMMENDATIONS_LOG expectations to `logs/.recommendations-log.jsonl`

---

### Step 26: Run validation

```bash
python scripts/validate.py
```

Must exit 0.

---

### Step 27: Run all tests

```bash
pytest tests/
```

All tests must pass.

---

### Step 28: Move this plan file to `docs/plans/`

Archive the implementation plan to its permanent location:

```bash
git mv PLAN-infra-repo-restructure.md docs/plans/
```

Update the commit message for the final commit to note this archival.

---

### Step 29: Report implementation summary

Report:
- Files moved to `docs/`
- Files moved to `logs/`
- Number of prompts updated
- Number of agents updated
- Number of scripts updated
- Confirmation loop fix applied to `/plan` prompt
- Any design decisions made during implementation
