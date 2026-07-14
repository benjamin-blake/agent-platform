# Plan

## Intent
Accelerate the self-improvement feedback loop by enabling compound execution of clustered recommendations — reducing CI overhead from N branches to 1 branch per cluster, and ensuring the executor critique performs content verification at the same standard as the planning critique.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-compound-execution

## Phase
Infrastructure (workflow tooling improvement — not phase-gated)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| scripts/execute_recommendation.py | Modify | Add `--compound` flag, `execute_compound()` function |
| scripts/executor/plan.py | Modify | Add `generate_compound_plan()` for multi-rec plan generation |
| scripts/run_scheduled_agent.py | Modify | Write findings to local JSONL when not in Lambda context |
| .github/instructions/executor-critique.instructions.md | Modify | Add mandatory scope file reading, factual verification checklist |
| config/prompts/executor/critique.prompt.md | Modify | Inject scope files list, require FILES READ section |
| tests/test_execute_recommendation.py | Modify | Add tests for `execute_compound()` |
| tests/test_run_scheduled_agent.py | Modify | Add test for local findings write |
| logs/.rec-curator-findings.jsonl | Create | Store curator output for compound batch consumption |

## Bundled Recommendations
- **rec-165** (new): Document SESSION_LOG.md ordering convention (date desc) to prevent agent ordering errors

## Acceptance Criteria
- [ ] `python -m scripts.run_scheduled_agent --agent rec-curator` produces valid JSON output and writes to `logs/.rec-curator-findings.jsonl`
- [ ] `python -m scripts.execute_recommendation --compound rec-042,rec-043` creates one branch, implements both recs, creates one PR
- [ ] `python -m scripts.execute_recommendation --compound cluster-001` reads cluster from curator findings and executes all recs in that cluster
- [ ] Executor critique reads ALL scope files before evaluating rules (verified by FILES READ section in critique output)
- [ ] `grep -q "FILES READ" config/prompts/executor/critique.prompt.md` returns 0
- [ ] All tests pass: `python -m pytest tests/test_execute_recommendation.py tests/test_run_scheduled_agent.py -q`

## Constraints
- Windows Git Bash environment — no PowerShell, no heredocs
- Python scripts only for automation (no shell scripts)
- Compound execution must be opt-in (default behaviour unchanged)
- Compound branch naming: `agent/compound-{first-rec-id}` or `agent/cluster-{cluster-id}`

## Context
- `execute_batch()` exists but runs recs sequentially with separate branches/PRs (line 887)
- `plan-critique.agent.md` already requires reading ALL scope files — executor critique should match
- rec-curator agent is defined but has never been run locally (no findings file exists)
- Current CI cycle per rec: ~10-15 minutes (branch + PR + CI wait + merge)
- Compound mode targets 3-5x throughput for non-conflicting XS/S recs

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Verify rec-curator can run and produce output
**File:** scripts/run_scheduled_agent.py (read-only verification)
**Action:** Run `python -m scripts.run_scheduled_agent --agent rec-curator --dry-run` to verify the agent is configured correctly. If dry-run passes, run without `--dry-run` and capture stdout.
**Acceptance:** `python -m scripts.run_scheduled_agent --list | grep -q rec-curator`

### Step 2: Add local findings write to run_scheduled_agent.py
**File:** scripts/run_scheduled_agent.py
**Action:** After `copilot_call()` returns, if running locally (not in Lambda context), parse the JSON output and append each finding to `logs/.rec-curator-findings.jsonl` using `append_jsonl()`. Detect Lambda context via `os.getenv("AWS_LAMBDA_FUNCTION_NAME")`.
**Acceptance:** `grep -q "rec-curator-findings" scripts/run_scheduled_agent.py`

### Step 3: Add execute_compound() function to execute_recommendation.py
**File:** scripts/execute_recommendation.py
**Action:** Add function `execute_compound(rec_ids: list[str], cluster_id: str | None = None) -> dict` that:
1. Creates branch `agent/compound-{rec_ids[0]}` or `agent/cluster-{cluster_id}`
2. For each rec_id: loads rec, generates plan, runs implementation steps, commits with rec-id in message
3. After ALL recs complete: runs `validate.py --ci`, creates ONE PR listing all recs, waits for CI, merges
4. Updates all rec statuses to `"closed"` with `"execution_result": "compound"`
5. Returns summary dict: `{"attempted": N, "succeeded": N, "failed": [], "pr_url": "..."}`
**Acceptance:** `grep -q "def execute_compound" scripts/execute_recommendation.py`

### Step 4: Add --compound CLI flag and cluster lookup
**File:** scripts/execute_recommendation.py
**Action:** Add `--compound` argument that accepts either:
- Comma-separated rec IDs: `--compound rec-042,rec-043`
- Cluster ID: `--compound cluster-001` (reads from `logs/.rec-curator-findings.jsonl`)

Add `load_cluster(cluster_id: str) -> list[str]` to read cluster rec_ids from curator findings.
**Acceptance:** `python -m scripts.execute_recommendation --help | grep -q compound`

### Step 5: Strengthen executor-critique.instructions.md
**File:** .github/instructions/executor-critique.instructions.md
**Action:** Update Phase 0 to require reading ALL files in the plan's scope table (not just target files). Add a checklist like plan-critique:
```
## Quality Gate (before outputting verdict)
- [ ] Read EVERY file in the plan's scope (not just .md files)
- [ ] Cite line numbers for functions being modified
- [ ] Cite line numbers for mocks that depend on modified code
- [ ] Your "FILES READ" list matches the scope file count
```
Add Rule 12: "Critique must include FILES READ section listing every file read with line count."
**Acceptance:** `grep -q "FILES READ" .github/instructions/executor-critique.instructions.md`

### Step 6: Update critique.prompt.md to inject scope and require FILES READ
**File:** config/prompts/executor/critique.prompt.md
**Action:** Add `{scope_files}` placeholder that gets populated with the list of files from the plan's scope table. Add instruction: "Before evaluating rules, read each file in this scope list. Your verdict MUST include a FILES READ section."
**Acceptance:** `grep -q "scope_files\|FILES READ" config/prompts/executor/critique.prompt.md`

### Step 7: Add tests for execute_compound()
**File:** tests/test_execute_recommendation.py
**Action:** Add `TestExecuteCompound` class with tests:
- `test_compound_creates_single_branch` — mocks git, verifies one branch created for 2 recs
- `test_compound_commits_per_rec` — verifies commit message contains rec-id for each
- `test_compound_single_pr` — verifies only one PR created
- `test_compound_updates_all_statuses` — verifies all recs marked closed
**Acceptance:** `python -m pytest tests/test_execute_recommendation.py::TestExecuteCompound -q`

### Step 8: Add test for local findings write
**File:** tests/test_run_scheduled_agent.py
**Action:** Add test that mocks `copilot_call()` returning JSON array, verifies `append_jsonl()` is called with findings path.
**Acceptance:** `python -m pytest tests/test_run_scheduled_agent.py -k "findings" -q`

### Step 9: File rec-165 for SESSION_LOG ordering convention
**File:** logs/.recommendations-log.jsonl
**Action:** Append new rec:
```json
{"id": "rec-165", "date": "2026-04-09", "title": "Document SESSION_LOG.md ordering convention (date desc)", "source": "planning", "effort": "XS", "priority": "Low", "status": "open", "automatable": true, "risk": "low", "file": "docs/SESSION_LOG.md", "context": "Supervisor agent appended session entry at end of file instead of start. File uses date-descending order but this is not documented. Add a comment block at the top of SESSION_LOG.md specifying the ordering convention.", "acceptance": "grep -qi 'date.*desc\\|newest.*first\\|reverse.*chron' docs/SESSION_LOG.md", "dependencies": [], "tags": ["documentation", "workflow"]}
```
**Acceptance:** `grep -q "rec-165" logs/.recommendations-log.jsonl`

### Step 10: Run pytest — all tests must pass
**Command:** `python -m pytest tests/test_execute_recommendation.py tests/test_run_scheduled_agent.py -q`
**Acceptance:** Exit code 0

### Step 11: Run validate.py — must exit 0
**Command:** `python scripts/validate.py --ci`
**Acceptance:** Exit code 0

### Step 12: Report implementation summary
**Action:** List what was implemented, any design decisions made, and confirm all acceptance criteria are met.
