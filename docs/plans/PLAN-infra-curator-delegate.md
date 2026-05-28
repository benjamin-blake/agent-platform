# Plan

## Intent
Extend the self-improving feedback loop with strategic oversight (curator agent) and scalable parallel execution (delegate-based implementation). The curator agent closes the loop between symptoms and root causes; delegate testing validates whether remote agents can preserve telemetry and quality gates while enabling parallel rec implementation.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-curator-delegate

## Phase
Infra (cross-cutting workflow improvement)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `.github/agents/rec-curator.agent.md` | Create | Scheduled agent that clusters recs, detects workarounds, suggests batches |
| `.github/agents/schedule.yaml` | Modify | Register rec-curator for weekly Monday 6am run |
| `.github/prompts/scheduled/rec-curator.prompt.md` | Create | Prompt template for curator analysis |
| `terraform/scheduled_agents.tf` | Modify | Add IAM permissions for claude-opus-4.6 model invocation |
| `scripts/delegate_runner.py` | Create | Wrapper to invoke `/delegate`, capture PR URL, poll for completion, verify telemetry |
| `docs/contracts/delegate-cli.md` | Create | Boundary contract for `/delegate` command |
| `tests/test_delegate_runner.py` | Create | Tests for delegate_runner.py (mock CLI calls) |
| `.gitignore` | Modify | Add `.github/copilot_instructions.md` to prevent recreation (rec-123) |
| `scripts/validate.py` | Modify | Add check that underscore instruction file does not exist (rec-123) |
| `tests/test_validate.py` | Modify | Append test for underscore instruction check to existing test file |

## Bundled Recommendations
- **rec-123**: copilot_instructions.md (underscore) persists as untracked file (XS, High)

## Acceptance Criteria
- [ ] `python -m pytest tests/test_delegate_runner.py -q` passes
- [ ] `grep -q "copilot_instructions.md" .gitignore` passes
- [ ] `ls .github/agents/rec-curator.agent.md` exists
- [ ] `grep -q "rec-curator" .github/agents/schedule.yaml` passes
- [ ] `python scripts/validate.py` exits 0 (including underscore check)
- [ ] Manual test: `copilot /delegate "echo test"` returns a PR URL or clear error

## Constraints
- Curator agent must use Claude Opus 4.6 (per user request)
- `/delegate` wrapper must preserve telemetry by capturing PR URL and polling for merge
- No real PRs created during automated testing (mock CLI calls)
- Windows Git Bash shell compatibility required

## Context
- **Decision 38** eliminated the underscore instruction file; rec-123 adds enforcement
- **Delegate telemetry risk**: `/delegate` runs remotely, so local transcript/telemetry capture is lost. Mitigation: capture PR URL, poll PR for status, extract commit history for audit trail.
- **Curator value**: Closes feedback loops by grouping related recs, detecting workarounds, suggesting batches for parallel execution.
- **Schedule.yaml**: Existing scheduled agent infrastructure in `.github/agents/schedule.yaml` and `src/data/handlers/scheduled_agent_handler.py`.

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add underscore file to .gitignore (rec-123 part 1)
Append `.github/copilot_instructions.md` to `.gitignore` to prevent accidental re-adds of the underscore variant. This enforces Decision 38.

### Step 2: Add underscore check to validate.py (rec-123 part 2)
Add a new validation function `validate_no_underscore_instructions(failed: list[str])` that fails if `.github/copilot_instructions.md` exists. Call it from the main validation flow.

### Step 3: Append test for underscore check to test_validate.py
Append a new test class to the existing `tests/test_validate.py` file that verifies the underscore check:
- `test_underscore_check_passes_when_file_absent` — Mock `Path.exists` to return False, verify validation passes
- `test_underscore_check_fails_when_file_present` — Mock `Path.exists` to return True for the underscore path, verify validation fails with appropriate message

### Step 4: Create boundary contract for /delegate
Create `docs/contracts/delegate-cli.md` documenting:
- **Tool**: Copilot CLI `/delegate` command
- **Input semantics**: Prompt describing the task; delegates to remote agent that creates a branch and PR
- **What we send**: Task description including rec ID, acceptance criteria, validation requirements
- **What we get back**: PR URL (or error)
- **Telemetry gap**: No local transcript — must poll PR for status and extract commit history
- **Doc page**: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#slash-commands-in-the-interactive-interface
- **Date last verified**: [implementation date]

### Step 5: Create delegate_runner.py
Create `scripts/delegate_runner.py` with:

**CRITICAL:** Per the Windows subprocess gotcha in `copilot-instructions.md`, do NOT use `subprocess.run(timeout=N)` for the Copilot CLI invocation. Instead, use the `subprocess.Popen` + `proc.communicate(timeout=N)` + `kill_process_tree(proc.pid)` pattern from `scripts/copilot_wrapper.py`. Import `kill_process_tree` from that module.

1. `delegate_task(prompt: str, rec_id: str) -> dict` — Invokes `/delegate` via `subprocess.Popen` with proper timeout handling and process tree cleanup. Parses PR URL from output, returns `{"pr_url": str, "status": "delegated"}` or `{"error": str, "status": "failed"}`.

2. `poll_delegate_pr(pr_url: str, timeout_secs: int = 600) -> dict` — Polls PR status via `gh pr view`, returns `{"status": "merged" | "open" | "closed" | "failed", "commits": int, "ci_status": str}`.

3. `capture_delegate_telemetry(pr_url: str, rec_id: str) -> None` — Extracts commit messages and diff stats from merged PR, writes summary to `logs/.delegate-telemetry.jsonl` for audit trail.

4. `main()` — CLI with `--rec-id`, `--prompt`, `--poll` flags for manual testing.

### Step 6: Create tests for delegate_runner.py
Create `tests/test_delegate_runner.py` with tests:
- `test_delegate_task_parses_pr_url` — Mock subprocess, verify PR URL extraction
- `test_delegate_task_handles_error` — Mock subprocess failure, verify error dict
- `test_poll_delegate_pr_returns_status` — Mock `gh pr view` output
- `test_capture_delegate_telemetry_writes_jsonl` — Mock PR data, verify JSONL write

### Step 7: Create rec-curator agent
Create `.github/agents/rec-curator.agent.md` with frontmatter:
```yaml
---
name: rec-curator
description: "Weekly scheduled agent that clusters recommendations, detects workarounds, and suggests batches for parallel execution"
model: Claude Opus 4.6 (copilot)
tools: ['read', 'search']
user-invocable: false
---
```

Agent workflow:
1. Read all open recs from `logs/.recommendations-log.jsonl`
2. Read recent closed recs (last 30 days)
3. Read gotchas from `copilot-instructions.md`
4. Cluster recs by semantic similarity (title, context, file)
5. Detect workaround patterns (same file 3+, rec chains, "add check" pattern)
6. Suggest batches for parallel execution
7. Output to `logs/.curator-report.jsonl`
8. Auto-file batch recs and root-cause recs back to recommendations log

### Step 8: Create rec-curator prompt template
Create `.github/prompts/scheduled/rec-curator.prompt.md` with the detailed prompt including:
- Input schema (recs, closed recs, gotchas, friction patterns)
- Clustering heuristics
- Workaround detection rules
- Output schema (clusters, batches, escalations, auto-filed recs)

### Step 9: Register curator in schedule.yaml
Modify `.github/agents/schedule.yaml` to add:
```yaml
- name: rec-curator
  cron: "0 6 * * 1"  # Monday 6am UTC
  model: claude-opus-4.6
  timeout: 300
```

### Step 10: Add Terraform IAM permissions for Opus 4.6
Modify `terraform/scheduled_agents.tf` to add IAM permissions allowing the Lambda dispatcher to invoke the `claude-opus-4.6` model via the GitHub Models API. This is required because existing permissions may only cover the models currently in use (e.g., `gpt-4.1`). Add the model to the allowed list in the IAM policy or verify the policy is model-agnostic.

### Step 11: Run full validation
```bash
python -m pytest tests/ -q
python scripts/validate.py
```
All tests must pass. validate.py must exit 0.

### Step 12: Manual delegate test
Run a manual test of the delegate command to verify it works:
```bash
copilot -i "/delegate Create a test branch and add a comment to README.md"
```
Document the output (PR URL or error) in the implementation report.

### Step 13: Report implementation summary
Report what was implemented, which recommendations were closed, manual test results, and any design decisions made during implementation.
