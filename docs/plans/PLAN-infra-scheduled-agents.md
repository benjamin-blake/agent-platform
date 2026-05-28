# Plan

## Intent
Enable autonomous scheduled agents that continuously review the codebase for quality issues, writing recommendations to S3 without requiring git write access. This creates a self-improving feedback loop where free-tier LLMs surface issues for human review.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-scheduled-agents

## Phase
Phase 1: Core Infrastructure (maintenance)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| .github/agents/schedule.yaml | Create | Manifest declaring agents, schedules, models, prompt paths |
| scripts/run_scheduled_agent.py | Create | Dispatcher: reads manifest, invokes copilot_call(), writes results to S3 |
| .github/workflows/scheduled-agents.yml | Create | GitHub Actions workflow: runs dispatcher sequentially on schedule |
| .github/prompts/scheduled/doc-freshness.prompt.md | Create | Agent: finds stale docs vs code |
| .github/prompts/scheduled/orphan-code.prompt.md | Create | Agent: finds unreferenced functions/files |
| .github/prompts/scheduled/transcript-review.prompt.md | Create | Agent: reviews recent transcripts for friction patterns |
| .github/prompts/scheduled/code-smell.prompt.md | Create | Agent: lightweight static analysis patterns |
| .github/prompts/cron_review.prompt.md | Delete | Replaced by scheduled agents |
| scripts/run_cron_review.py | Delete | Replaced by run_scheduled_agent.py |
| tests/test_run_cron_review.py | Delete | Tests for deleted script |
| tests/test_run_scheduled_agent.py | Create | Tests for new dispatcher |
| .github/copilot-instructions.md | Modify | Document scheduled agents, remove cron_review references |
| docs/GETTING_STARTED.md | Modify | Add GitHub Actions auth setup instructions |
| config/README.md | Modify | Document SCHEDULED_AGENT_MODEL env var |

## Acceptance Criteria
- [ ] python -m scripts.run_scheduled_agent --list prints all agents from manifest
- [ ] python -m scripts.run_scheduled_agent --agent doc-freshness --dry-run shows what would be invoked
- [ ] All 4 agent prompts exist in .github/prompts/scheduled/
- [ ] .github/workflows/scheduled-agents.yml has valid YAML syntax
- [ ] cron_review.prompt.md and run_cron_review.py are deleted
- [ ] python -m pytest tests/test_run_scheduled_agent.py -v passes
- [ ] python -m pytest tests/ passes (no broken imports from deleted files)
- [ ] python scripts/validate.py exits 0

## Constraints
- Agents run on free models only (gpt-4.1-mini, gemini-3.0-flash)
- All output goes to S3 (bblake-platform-agent-logs) - no git write access
- Sequential execution in workflow (no parallelism)
- GitHub Actions OIDC for AWS credentials (existing pattern)
- Copilot CLI requires GITHUB_TOKEN with copilot scope (manual setup by human)

## Context
- **Decision 33**: S3 append race condition accepted for sequential agents
- **Decision 34**: Unified session telemetry enables cross-workflow friction analysis
- **S3 bucket**: bblake-platform-agent-logs (created in Plan 1)
- **Existing pattern**: refresh-copilot-multipliers.yml uses monthly cron

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on main
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Create agent schedule manifest
**File**: .github/agents/schedule.yaml
**Action**: create
**Description**: Create YAML manifest with 4 agents. Each agent has: name, cron expression, model, prompt path, description. Include comments explaining the cron syntax. All agents run at 06:00 UTC on different days to avoid overlap. Use gpt-4.1-mini for most agents and gemini-3.0-flash for transcript-review.
**Acceptance**: `python -c "import yaml; yaml.safe_load(open('.github/agents/schedule.yaml')); print('ok')"`

### Step 2: Create scheduled agent dispatcher script
**File**: scripts/run_scheduled_agent.py
**Action**: create
**Description**: Create dispatcher script with:
- load_manifest() - reads .github/agents/schedule.yaml, returns list of agent dicts
- is_agent_due(agent, now) - checks if agent cron matches current time
- run_agent(agent, dry_run) - invokes copilot_call() with agent prompt and model, writes recommendations to S3
- main() with argparse: --list, --agent NAME, --due, --dry-run
- Write session envelope to logs/.session-telemetry.jsonl via session_telemetry.write_session_envelope()
- Write any recommendations to logs/.recommendations-log.jsonl via append_jsonl()
- Use simple cron matching: parse cron fields, check each against current time
**Acceptance**: `python -m scripts.run_scheduled_agent --list`

### Step 3: Create doc-freshness agent prompt
**File**: .github/prompts/scheduled/doc-freshness.prompt.md
**Action**: create
**Description**: Create read-only agent prompt that:
- Lists all .md files in docs/ and their git last-modified dates
- Lists corresponding source files and their last-modified dates
- Identifies docs where source file was modified more recently than doc
- Outputs JSON array of findings
- Uses read_file and run_in_terminal (git log) tools only
- No file writes - output is captured by dispatcher
**Acceptance**: `grep -q "doc-freshness" .github/prompts/scheduled/doc-freshness.prompt.md`

### Step 4: Create orphan-code agent prompt
**File**: .github/prompts/scheduled/orphan-code.prompt.md
**Action**: create
**Description**: Create read-only agent prompt that:
- Lists all Python functions and classes in scripts/ and src/
- For each, searches for references using grep
- Identifies symbols with zero external references
- Outputs JSON array of findings
- Excludes test files from reference counting
- Excludes __init__, main, if __name__ patterns
**Acceptance**: `grep -q "orphan-code" .github/prompts/scheduled/orphan-code.prompt.md`

### Step 5: Create transcript-review agent prompt
**File**: .github/prompts/scheduled/transcript-review.prompt.md
**Action**: create
**Description**: Create read-only agent prompt that:
- Lists transcripts in logs/transcripts/ from the last 24 hours
- For each transcript, identifies friction patterns: repeated tool failures, scope creep, context confusion
- Cross-references with existing recommendations to avoid duplicates
- Outputs JSON array of findings
**Acceptance**: `grep -q "transcript-review" .github/prompts/scheduled/transcript-review.prompt.md`

### Step 6: Create code-smell agent prompt
**File**: .github/prompts/scheduled/code-smell.prompt.md
**Action**: create
**Description**: Create read-only agent prompt that:
- Scans Python files for common smells: functions > 50 lines, files > 500 lines, deep nesting, bare except, mutable default args
- Uses grep and wc for line counts, ast parsing for structure
- Outputs JSON array of findings
**Acceptance**: `grep -q "code-smell" .github/prompts/scheduled/code-smell.prompt.md`

### Step 7: Create GitHub Actions workflow
**File**: .github/workflows/scheduled-agents.yml
**Action**: create
**Description**: Create workflow that:
- Triggers on schedule (hourly: 0 * * * *) and workflow_dispatch (manual)
- Has contents: read permission only
- Configures AWS credentials via OIDC (copy pattern from existing workflows)
- Sets S3_LOG_BUCKET and GITHUB_TOKEN env vars
- Runs python -m scripts.run_scheduled_agent --due
- Includes manual input for --agent NAME override
- Adds placeholder comment for GITHUB_TOKEN setup instructions
**Note**: GITHUB_TOKEN must have copilot scope - this requires a PAT, not the default GITHUB_TOKEN
**Acceptance**: `grep -q "scheduled-agents" .github/workflows/scheduled-agents.yml`

### Step 8: Create tests for dispatcher
**File**: tests/test_run_scheduled_agent.py
**Action**: create
**Description**: Create tests:
- TestLoadManifest: loads valid YAML, handles missing file
- TestIsAgentDue: matches cron expressions correctly
- TestRunAgent: mocks copilot_call, verifies prompt and model passed correctly
- TestMain: integration test for --list, --agent, --dry-run flags
**Acceptance**: `python -m pytest tests/test_run_scheduled_agent.py -v`

### Step 9: Delete cron_review.prompt.md
**File**: .github/prompts/cron_review.prompt.md
**Action**: delete
**Description**: Remove old interactive cron review prompt, replaced by scheduled agents.
**Acceptance**: `test ! -f .github/prompts/cron_review.prompt.md`

### Step 10: Delete run_cron_review.py
**File**: scripts/run_cron_review.py
**Action**: delete
**Description**: Remove old cron review script, replaced by run_scheduled_agent.py.
**Acceptance**: `test ! -f scripts/run_cron_review.py`

### Step 11: Delete test_run_cron_review.py
**File**: tests/test_run_cron_review.py
**Action**: delete
**Description**: Remove tests for deleted script.
**Acceptance**: `test ! -f tests/test_run_cron_review.py`

### Step 12: Update copilot-instructions.md
**File**: .github/copilot-instructions.md
**Action**: modify
**Description**:
- Remove cron_review.prompt.md from File Router
- Remove run_cron_review.py from File Router
- Add scheduled agents section with: schedule.yaml location, run_scheduled_agent.py, prompt folder
- Add note about free model usage for scheduled agents
**Acceptance**: `grep -q "scheduled" .github/copilot-instructions.md && ! grep -q "cron_review" .github/copilot-instructions.md`

### Step 13: Update GETTING_STARTED.md with GitHub Actions auth
**File**: docs/GETTING_STARTED.md
**Action**: modify
**Description**: Add section "Scheduled Agents Setup" with:
1. Create a GitHub PAT with copilot scope
2. Add PAT as repository secret named COPILOT_PAT
3. The workflow uses this for GITHUB_TOKEN to authenticate Copilot CLI
4. AWS OIDC is already configured (existing pattern)
5. First run will be manual via workflow_dispatch to verify setup
**Acceptance**: `grep -q "COPILOT_PAT" docs/GETTING_STARTED.md`

### Step 14: Update config README
**File**: config/README.md
**Action**: modify
**Description**: Add environment variables section for scheduled agents:
- S3_LOG_BUCKET - bucket for agent output (already documented, verify)
- SCHEDULED_AGENT_MODEL - optional override for all agent models
- GITHUB_TOKEN - PAT with copilot scope for CLI auth
**Acceptance**: `grep -q "SCHEDULED_AGENT" config/README.md`

### Step 15: Run pytest
**File**: N/A
**Action**: verify
**Description**: Run full test suite to verify no broken imports from deleted files.
**Acceptance**: `python -m pytest tests/ -v`

### Step 16: Run validate.py
**File**: N/A
**Action**: verify
**Description**: Run full validation to ensure CI will pass.
**Acceptance**: `python scripts/validate.py`

### Step 17: Report implementation summary
**File**: N/A
**Action**: report
**Description**: Summarize what was implemented, note that GitHub PAT setup is manual, and provide next steps for enabling the workflow.
**Acceptance**: N/A (human review)
