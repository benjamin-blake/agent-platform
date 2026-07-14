# Plan

## Intent

Reduce workflow token costs by 30-40% and close the recursive self-improvement loop by offloading deterministic work to Python scripts, merging the implement+close phases, persisting analysis outputs, and adding session timing metrics. This directly serves the North Star by making the self-improving system more efficient and measurable.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-workflow-cost-optimisation

## Phase
Infra (workflow infrastructure improvements)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `scripts/session_preflight.py` | Create | Deterministic pre-session checks, outputs JSON report |
| `scripts/session_postflight.py` | Create | Deterministic post-session tasks, CI happy-path, pre-commit-sanity logic |
| `.github/prompts/plan.prompt.md` | Modify | Remove Steps 0-3b, 10b-10e; add preflight JSON read |
| `.github/prompts/implement.prompt.md` | Modify | Absorb session_close logic; add postflight call; change retrospective to Haiku |
| `.github/prompts/session_close.prompt.md` | Delete | Merged into implement.prompt.md |
| `.github/agents/pre-commit-sanity.agent.md` | Delete | Logic moved to postflight script |
| `.github/agents/retrospective.agent.md` | Modify | Change model from Sonnet to Haiku |
| `scripts/friction_analysis.py` | Modify | Add JSONL output to `logs/.friction-analysis-log.jsonl` |
| `scripts/metrics_analysis.py` | Modify | Add JSONL output to `logs/.metrics-analysis-log.jsonl` |
| `scripts/plan_audit.py` | Modify | Add JSONL output to `logs/.plan-audit-log.jsonl` |
| `scripts/north_star_tracker.py` | Modify | Add JSONL output to `logs/.north-star-log.jsonl` |
| `scripts/session_metrics.py` | Modify | Fix test_functions_added; add session_start/session_end timing |
| `scripts/run_retro_lite.py` | Modify | Record clean sessions with `"friction": "clean"` |
| `docs/AGENT_WORKFLOW.md` | Modify | Update workflow diagram for merged implement+close |
| `.github/copilot_instructions.md` | Modify | Update File Router; document model assignments; remove deleted file references |
| `docs/DECISIONS.md` | Modify | Update Decision 23 to remove deleted file references; add Decision 26 |
| `.gitignore` | Modify | Add `logs/.preflight-report.json` (transient, not tracked) |
| `tests/test_session_preflight.py` | Create | Unit tests for preflight script |
| `tests/test_session_postflight.py` | Create | Unit tests for postflight script |
| `tests/test_run_retro_lite.py` | Create | Unit tests for clean session recording |
| `tests/test_session_metrics.py` | Create | Unit tests for timing and test_functions_added fix |

## Acceptance Criteria

- [ ] `python scripts/session_preflight.py` outputs valid JSON with keys: `venv_ok`, `branch`, `uncommitted_changes`, `stash_entries`, `sso_status`, `cron_review_fresh`, `last_session`, `open_recommendations`, `aging_recommendations`, `friction_patterns`, `metrics_anomalies`, `session_start`
- [ ] `python scripts/session_postflight.py --validate` runs validation and returns exit code
- [ ] `python scripts/session_postflight.py --commit "message"` handles git add/commit with pre-commit retry
- [ ] `python scripts/session_postflight.py --push` handles push, PR create, CI polling, and auto-merge on green
- [ ] `python scripts/session_postflight.py --push` returns structured JSON for LLM triage when CI fails or conflicts occur
- [ ] `plan.prompt.md` reduced from ~418 lines to ~200 lines
- [ ] `implement.prompt.md` contains full implement+close workflow, ~250 lines
- [ ] `session_close.prompt.md` deleted
- [ ] `pre-commit-sanity.agent.md` deleted
- [ ] `retrospective.agent.md` model changed to `Claude Haiku 4.5 (copilot)`
- [ ] All 4 analysis scripts append JSONL records (not just stdout)
- [ ] `session_metrics.py` records `session_start` and `session_end` timestamps
- [ ] `run_retro_lite.py` records clean sessions (not skipped)
- [ ] `test_functions_added` metric counts tests by comparing branch vs main (not diff lines)
- [ ] `docs/DECISIONS.md` Decision 23 no longer references `session_close.prompt.md` or `pre-commit-sanity.agent.md`
- [ ] `.github/copilot_instructions.md` File Router no longer references deleted files
- [ ] `.gitignore` contains `logs/.preflight-report.json`
- [ ] JSONL analysis logs (`logs/*-log.jsonl`) are committed (tracked for trending)
- [ ] All existing tests pass (`pytest tests/`)
- [ ] `python scripts/validate.py` exits 0

## Constraints

- Python scripts only for automation (no bash scripts)
- Windows-compatible (use `subprocess` with `encoding='utf-8'`)
- Must maintain backward compatibility during transition (prompts can fall back if scripts missing)
- `gh` CLI required for PR/CI operations (documented in GETTING_STARTED.md)
- Free agents (GPT-4.1) only for single-minded tasks; keep Gemini for plan-critique

## Context

- Decision 23: Parallel workflow with branch-specific plans
- Decision 25: Git worktrees for parallel development
- Token costs: Opus (highest), Sonnet (1x), Gemini (1x), Haiku (0.33x), GPT-4.1 (0x)
- Current `/implement` runs on Sonnet (1x); merged workflow keeps Sonnet for implementation, Haiku for retrospective
- Validation sync gotcha: all changes to validate.py must work in CI

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

> **Execute these in sequence. Do not substitute the Scope table as a work list.**

### Phase 1: Create Preflight Script (Steps 1-3)

**Step 1:** Create `scripts/session_preflight.py` with the following functionality:
- Check venv: `sys.executable` must contain repo folder name
- Check git status: uncommitted changes, stash list, current branch
- Check cron review freshness: mtime of `docs/CRON_REVIEW_SUMMARY.md`
- Check SSO status: `aws sts get-caller-identity --profile company-aws-profile` (non-blocking)
- Load context summaries: parse `docs/SESSION_LOG.md` (last entry), count open recommendations in `docs/RECOMMENDATIONS.md`, count aging (>30 days)
- Run `scripts/friction_analysis.py` and capture patterns
- Run `scripts/metrics_analysis.py` and capture anomalies
- Record `session_start` timestamp (ISO-8601)
- Output JSON to `logs/.preflight-report.json`
- Exit 0 on success, exit 1 on critical failure (wrong venv)

**Step 2:** Create `tests/test_session_preflight.py` with tests for:
- Correct venv detection (mock sys.executable)
- Wrong venv detection and exit code 1
- Git status parsing (clean, uncommitted, stash)
- Cron review freshness calculation
- JSON output schema validation
- Graceful handling when optional files missing

**Step 3:** Run `pytest tests/test_session_preflight.py -v` -- all tests must pass

### Phase 2: Create Postflight Script (Steps 4-7)

**Step 4:** Create `scripts/session_postflight.py` with the following modes:

`--validate`: Run `python scripts/validate.py` and return exit code

`--pre-commit-sanity`: Replaces pre-commit-sanity.agent.md logic:
- Check branch is not `main`
- Find plan file for current branch
- Parse Scope table from plan
- Compare against `git diff --name-only`
- Scan diff for orphaned TODO/FIXME
- Output JSON: `{"status": "PASS|WARN|FAIL", "branch": "...", "planned": N, "changed": N, "unplanned": [...], "orphaned_todos": [...]}`

`--commit "message"`:
- Run `git add .`
- Run `git commit -m "message"`
- If pre-commit hooks modify files, retry up to 3 times
- Return exit code

`--push`:
- Run `git push` (with `--set-upstream` if needed)
- Run `gh pr create` with auto-generated title/body from plan Intent
- Poll `gh run list` every 30s for up to 5 minutes
- If CI green: run `gh pr merge --squash --auto --delete-branch`, return `{"status": "merged", "pr_url": "..."}`
- If CI fails: return `{"status": "ci_failed", "run_id": "...", "error_summary": "..."}` for LLM triage
- If conflict: return `{"status": "conflict", "files": [...]}` for LLM triage

`--metrics`:
- Run `python scripts/session_metrics.py`
- Run `python scripts/plan_audit.py`
- Return combined JSON output

`--log-housekeeping`:
- Check for uncommitted log files (`logs/*.jsonl`)
- If any, commit with message `chore: session log updates`
- Push

**Step 5:** Create `tests/test_session_postflight.py` with tests for:
- Validate mode exit codes
- Pre-commit-sanity scope comparison (mock git diff, mock plan file)
- Commit retry logic (mock pre-commit hook failures)
- Push with upstream detection
- CI polling timeout handling
- JSON output schema for each mode

**Step 6:** Run `pytest tests/test_session_postflight.py -v` -- all tests must pass

**Step 7:** Delete `.github/agents/pre-commit-sanity.agent.md`

### Phase 3: Persist Analysis Outputs (Steps 8-12)

**Step 8:** Modify `scripts/friction_analysis.py`:
- After printing to stdout, append a JSONL record to `logs/.friction-analysis-log.jsonl`
- Record schema: `{"timestamp": "ISO-8601", "total_entries": N, "friction_count": N, "clean_count": N, "repeated_patterns": [{"pattern": "...", "count": N}]}`
- Create file with schema comment if it doesn't exist

**Step 9:** Modify `scripts/metrics_analysis.py`:
- After printing to stdout, append a JSONL record to `logs/.metrics-analysis-log.jsonl`
- Record schema: `{"timestamp": "ISO-8601", "sessions_analyzed": N, "rolling_avg_files": N, "rolling_avg_lines": N, "coverage_trend": "up|down|flat", "anomalies": [...]}`

**Step 10:** Modify `scripts/plan_audit.py`:
- After printing to stdout, append a JSONL record to `logs/.plan-audit-log.jsonl`
- Record schema: `{"timestamp": "ISO-8601", "branch": "...", "planned": N, "changed": N, "unplanned": N, "missing": N, "action_mismatches": N}`

**Step 11:** Modify `scripts/north_star_tracker.py`:
- After printing to stdout, append a JSONL record to `logs/.north-star-log.jsonl`
- Record schema: `{"timestamp": "ISO-8601", "period_days": 30, "sessions_total": N, "feature_count": N, "fix_count": N, "infra_count": N, "momentum_pct": N, "infra_ratio_pct": N}`

**Step 12:** Modify `scripts/session_metrics.py`:
- Add `session_start` field (read from `logs/.preflight-report.json` if exists)
- Add `session_end` field (current timestamp)
- Add `session_duration_minutes` field (computed)
- Fix `test_functions_added`: count test functions in `tests/` on branch vs main using `git show main:tests/ | grep "def test_"` comparison

**Step 12b:** Create `tests/test_session_metrics.py` with tests for:
- Session timing fields (`session_start`, `session_end`, `session_duration_minutes`)
- `test_functions_added` counts correctly (mock git show output)
- Graceful handling when preflight report missing
- JSONL output schema validation

### Phase 4: Fix Retro-Lite Clean Session Recording (Steps 13-14)

**Step 13:** Modify `scripts/run_retro_lite.py`:
- Remove the `SKIPPED: Clean session` early return
- Instead, write `{"timestamp": "...", "session": "...", "friction": "clean", "missing_context": "none", "deviation": "none", "suggested_fix": "none"}`
- Update `--stats` mode to report clean vs friction counts

**Step 14:** Create `tests/test_run_retro_lite.py` with tests for:
- Clean session recording (friction="clean" writes to file, not skipped)
- Friction session recording (existing behaviour)
- `--stats` mode reports clean vs friction counts correctly
- Schema validation for both clean and friction entries
- Deduplication still works for clean sessions

### Phase 5: Trim plan.prompt.md (Steps 15-16)

**Step 15:** Modify `.github/prompts/plan.prompt.md`:

Remove these sections entirely (handled by preflight):
- Step 0 (Recovery Check)
- Step 1 (Verify Python Environment)
- Step 2 (Establish SSO Session)
- Step 3b (Check Cron Review Freshness)

Remove these sections entirely (moved to implement):
- Step 10b (Surface Friction Patterns)
- Step 10c (Surface Last Session Anomalies)
- Step 10d (Invoke Retrospective)
- Step 10e (Capture Planning Session Friction)

Replace with new Step 0:
```markdown
## Step 0: Run Preflight

```bash
python scripts/session_preflight.py
```

Read `logs/.preflight-report.json`. If `venv_ok` is false, stop and report the venv error.

Surface to the human:
- If `uncommitted_changes` is true: "There are uncommitted changes on branch `[branch]`. Resume, stash, or discard?"
- If `stash_entries` is non-empty: "Stashed work exists: [list]"
- If `cron_review_fresh` is false: "Cron review has not run in 7 days. Consider running `/cron_review`."
- If `friction_patterns` has items with count >= 3: "Repeated friction patterns: [list]"
- If `metrics_anomalies` is non-empty: "Session anomalies: [list]"

Wait for human decision on uncommitted changes before proceeding.
```

Update Step 3 (Load Project Context):
- Remove the file-reading instructions (already summarised in preflight)
- Keep the recommendation surfacing and human interaction logic
- Read from `preflight.open_recommendations` and `preflight.aging_recommendations`

**Step 16:** Verify `plan.prompt.md` is approximately 200 lines (down from 418)

### Phase 6: Merge implement + session_close (Steps 17-21)

**Step 17:** Read the full content of `.github/prompts/session_close.prompt.md` to understand all steps that need merging

**Step 18:** Modify `.github/prompts/implement.prompt.md`:

Add after current Step 10 (Code Review):
```markdown
---

## Session Close Phase

The following steps complete the session. Do not start a new chat -- continue here.

## Step 11: Run Postflight Validation

```bash
python scripts/session_postflight.py --validate
```

If validation fails, fix all failures before proceeding.

## Step 12: Intent Verification

Compare the plan's `## Intent` against what was actually implemented (use `git diff --stat`).

- If achieved: proceed
- If partial: report what was and wasn't achieved
- If not achieved: report gap and ask whether to continue closing or address it

## Step 13: Quantitative Audit

```bash
python scripts/session_postflight.py --metrics
```

If plan_audit shows unplanned files, surface them for review.

## Step 14: Invoke Retrospective

Invoke `@retrospective`. Wait for it to complete.

Note: The retrospective now runs on Haiku with full session context (no reconstruction from diffs needed).

## Step 15: Write Session Log

Append to `docs/SESSION_LOG.md`:

```
## [YYYY-MM-DD] -- [branch name]

**Done:** [1-2 sentences]
**Next:** [1-2 sentences]
**Retrospective:** [completed / skipped]
**Recommendations:** [from retrospective summary, or "none"]
**Metrics:** [from postflight --metrics output]
```

## Step 16: Pre-Commit Sanity

```bash
python scripts/session_postflight.py --pre-commit-sanity
```

If WARN, surface warnings. If FAIL (on main), stop.

## Step 17: Commit

```bash
python scripts/session_postflight.py --commit "<conventional-prefix>: <summary>"
```

Commit message:
- Conventional prefix: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `ci:`
- One concise line, max 72 characters

## Step 18: Push and Merge

```bash
python scripts/session_postflight.py --push
```

Parse the JSON output:
- If `status: merged`: "PR merged to main. Session complete."
- If `status: ci_failed`: Enter CI Triage (see below)
- If `status: conflict`: Enter Conflict Resolution (see below)

## Step 19: CI Triage (if needed)

If postflight returned `status: ci_failed`:

Read the `error_summary` field. Classify as:
- `VALIDATE_GAP`: Fix in validate.py first, then fix the code
- `ENV_DIFFERENCE`: Document in Known Gotchas, fix workflow or skip check in CI
- `TEST_FLAKY`: Fix the test
- `WORKFLOW_CONFIG`: Fix the workflow YAML
- `DEPENDENCY`: Fix requirements.txt or workflow

Present triage report to human. Apply fix after confirmation. Re-run postflight --push.

Maximum 2 triage cycles before escalating to manual investigation.

## Step 20: Conflict Resolution (if needed)

If postflight returned `status: conflict`:

For Tier 1 files (SESSION_LOG.md, *.jsonl): Keep both additions
For Tier 2 files (RECOMMENDATIONS.md, DECISIONS.md): Merge rows, dedupe
For Tier 3 files (.py, .tf, .prompt.md): Escalate to human

After resolution: `git add -A && git commit -m "merge: resolve conflicts"`, then re-run postflight --push.

## Step 21: Log Housekeeping

```bash
python scripts/session_postflight.py --log-housekeeping
```

## Step 22: End-of-Session Friction Capture

Write friction entry directly to `logs/.retro-lite-log.jsonl`:

```bash
python scripts/run_retro_lite.py --append '{"timestamp": "...", "session": "implement / [branch]", "friction": "...", "missing_context": "...", "deviation": "...", "suggested_fix": "..."}'
```

If zero friction, write with `"friction": "clean"`.

## Step 23: Return to Main

```bash
git checkout main && git pull origin main && git branch -d [branch]
```

Report: "Session complete. Ready for next task."
```

**Step 19:** Delete `.github/prompts/session_close.prompt.md`

**Step 20:** Modify `.github/agents/retrospective.agent.md`:
- Change `model: Claude Sonnet 4.5 (copilot)` to `model: Claude Haiku 4.5 (copilot)`
- Add note: "Note: Runs on Haiku because the merged implement+close prompt provides full session context, eliminating the need for expensive reconstruction from diffs."

**Step 21:** Run tests for Phase 6 changes: `pytest tests/ -v -k "implement or retrospective"` (if applicable tests exist)

### Phase 7: Update Documentation (Steps 22-27)

**Step 22:** Modify `docs/AGENT_WORKFLOW.md`:
- Update workflow diagram to show 2-chat model: `/plan` -> `/implement` (includes close)
- Remove references to `/session_close` as separate invocation
- Remove `pre-commit-sanity` from agent list
- Add note about preflight/postflight scripts

**Step 23:** Modify `.github/copilot_instructions.md`:
- **Remove from File Router:** `session_close.prompt.md`, `pre-commit-sanity.agent.md`
- **Add to File Router:** `session_preflight.py`, `session_postflight.py`, new JSONL log files
- **Update Workflow entry point section:** Remove mention of `/session_close` as separate step
- **Update model assignments:** Show Haiku for retrospective
- **Update Free agents section:** Remove `pre-commit-sanity` from list

**Step 24:** Modify `.gitignore`:
- Add `logs/.preflight-report.json` (transient file, regenerated each session)
- Note: JSONL analysis logs (`logs/*-log.jsonl`) are NOT gitignored -- they are committed for trending

**Step 25:** Modify `docs/DECISIONS.md`:

Update Decision 23 (Parallel Workflow with Branch-Specific Plans):
- Remove references to `/session_close` as a separate chat/invocation
- Remove `pre-commit-sanity.agent.md` from any agent lists
- Update workflow description to reflect merged implement+close

Add Decision 26:
```markdown
## Decision 26: Workflow Cost Optimisation (Decided)

**Context:** The 3-chat workflow (/plan, /implement, /session_close) reloaded context files 3 times per cycle. Deterministic steps (venv check, git status, validation, CI polling) consumed expensive LLM tokens. Analysis scripts output to stdout only, preventing trend analysis.

**Decision:** Merge to 2-chat workflow with deterministic offloading:
- `scripts/session_preflight.py`: All pre-session checks, outputs JSON
- `scripts/session_postflight.py`: Validation, commit, push, CI polling, auto-merge
- `/implement` absorbs `/session_close` steps
- Retrospective model changed from Sonnet (1x) to Haiku (0.33x) -- full context available
- Analysis scripts persist JSONL records for trending
- Clean sessions recorded (not skipped) for friction rate calculation

**Estimated savings:** 30-40% reduction in Opus/Sonnet tokens per workflow cycle

**Rationale:**
- Context reload eliminated by merging chats (saves ~5-10K tokens)
- Deterministic work in Python is free; in LLM is expensive
- Haiku sufficient for retrospective when full context available (3x cheaper)
- Persisted analysis enables recursive self-improvement measurement

**Status:** Decided -- March 2026
```

### Phase 8: Final Validation (Steps 26-28)

**Step 26:** Run `pytest tests/ -v` -- all tests must pass

**Step 27:** Run `python scripts/validate.py` -- must exit 0

**Step 28:** Report:
- Files created
- Files modified
- Files deleted
- Line count changes for trimmed prompts
- Any design decisions made during implementation
