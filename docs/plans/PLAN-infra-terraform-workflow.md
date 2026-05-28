# Plan

## Intent
Close the infrastructure validation gap where Terraform changes flow through the same pipeline as Python code but lack deployment verification. By integrating terraform plan/apply gates into the `/plan` and `/implement` workflow, infrastructure changes will be tested against real AWS before merge — catching configuration errors during implementation rather than post-merge. This directly supports the North Star by ensuring the self-improving loop includes infrastructure, not just code.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-terraform-workflow

## Phase
Phase 1: Core Infrastructure (maintenance)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| .github/prompts/plan.prompt.md | Modify | Add Infrastructure Assessment section when scope includes .tf files; add Step 3b to suggest aligned recommendations |
| .github/prompts/implement.prompt.md | Modify | Add Infrastructure Deployment Phase between implementation and session close |
| scripts/session_preflight.py | Modify | Remove cron_review_fresh check (vestigial); add terraform_pending detection |
| scripts/validate.py | Modify | Add --scope terraform warning when changes pending (exit code 2 from plan -detailed-exitcode) |
| .github/copilot-instructions.md | Modify | Add Known Gotcha for terraform workflow (CLI version) |
| .github/copilot_instructions.md | Modify | Add Known Gotcha for terraform workflow (VS Code version) |
| docs/DECISIONS.md | Modify | Add Decision 35 documenting terraform workflow integration |
| tests/test_session_preflight.py | Modify | Remove cron_review_fresh tests; add terraform_pending tests |
| tests/test_validate.py | Modify | Add tests for terraform pending detection |

## Bundled Recommendations
- **rec-024** (YAML frontmatter for structured plan parsing) — Deferred to separate session. This plan focuses on prompt/workflow changes; YAML frontmatter is a parsing improvement that can be layered on afterward.

## Acceptance Criteria
- [ ] `plan.prompt.md` contains "Infrastructure Assessment" section guidance
- [ ] `plan.prompt.md` contains Step 3b for recommendation suggestion
- [ ] `implement.prompt.md` contains "Infrastructure Deployment Phase" section
- [ ] `session_preflight.py` no longer checks `cron_review_fresh`
- [ ] `session_preflight.py` outputs `terraform_pending: true/false` in JSON
- [ ] `validate.py --scope terraform` warns when `terraform plan -detailed-exitcode` returns 2
- [ ] `DECISIONS.md` contains Decision 35 for terraform workflow
- [ ] All tests pass: `python -m pytest tests/ -q`
- [ ] Validation passes: `python scripts/validate.py`

## Constraints
- Terraform apply remains human-triggered (never auto-apply from agent)
- Local fallback required when terraform binary not available
- Changes must not break existing non-terraform workflows
- Line length limit: 127 characters (ruff E501)
- Windows-compatible shell commands only (Python subprocess, not bash)

## Context
- **Decision 24**: Multi-environment deployment strategy — agents use company-aws-profile only; promotion is human-triggered
- **deploy.yml**: Already has `terraform plan` → `terraform apply` flow, but only via manual workflow_dispatch
- **validate.py**: Already runs `terraform validate` and `terraform fmt -check`; integration mode runs `terraform plan`
- **Known Gap**: Plans with .tf files pass validation without ever running `terraform plan` unless `--integration` flag is used
- **Observed Friction**: `agent/infra-s3-logs` branch had 28 steps including terraform changes but no plan/apply verification during implementation

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Remove cron_review_fresh from session_preflight.py
**File**: scripts/session_preflight.py
**Action**: modify
**Description**:
- Remove the `cron_review_fresh` check and related code (it checks for `.github/prompts/scheduled/` file age)
- Remove `cron_review_fresh` from the output JSON schema
- Add `terraform_pending` field to output JSON: runs `terraform -chdir=terraform plan -detailed-exitcode` if terraform is available, returns `true` if exit code is 2, `false` if exit code is 0, `null` if terraform not found or error
**Acceptance**: `python -c "import json; r=json.loads(open('logs/.preflight-report.json').read()); assert 'cron_review_fresh' not in r; print('ok')"`

### Step 2: Update tests for session_preflight.py
**File**: tests/test_session_preflight.py
**Action**: modify
**Description**:
- Remove tests for `cron_review_fresh`
- Add tests for `terraform_pending`: mock subprocess to return exit codes 0, 2, and error cases
- Test that terraform_pending is null when terraform binary not found
**Acceptance**: `python -m pytest tests/test_session_preflight.py -v -k terraform`

### Step 3: Add terraform pending detection to validate.py
**File**: scripts/validate.py
**Action**: modify
**Description**:
- In `run_terraform_checks()`, after `terraform validate` and `terraform fmt`, add a check that runs `terraform plan -detailed-exitcode`
- If exit code is 2 (changes pending), print warning: "WARNING: Terraform changes pending. Run `terraform apply` before merge or use `--integration` to verify."
- Do not fail the build — this is informational for non-integration mode
- In integration mode, the existing `invoke_step("Terraform plan", ...)` already runs plan but does not capture the distinction between "success with no changes" vs "success with changes"
**Acceptance**: `grep -q "detailed-exitcode\|changes pending" scripts/validate.py`

### Step 4: Update tests for validate.py terraform detection
**File**: tests/test_validate.py
**Action**: modify
**Description**:
- Add test that `run_terraform_checks()` warns when `terraform plan -detailed-exitcode` returns 2
- Mock subprocess to simulate different exit codes
**Acceptance**: `python -m pytest tests/test_validate.py -v -k terraform`

### Step 5: Add Infrastructure Assessment guidance to plan.prompt.md
**File**: .github/prompts/plan.prompt.md
**Action**: modify
**Description**:
Add new section after Step 5 (Identify Affected Files), before Step 6 (Create Branch):

```markdown
## Step 5b: Infrastructure Assessment (if .tf files in scope)

If the Scope table contains any `.tf` files, add the following to the plan:

### Infrastructure Dependencies table
| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing |
|----------|-----------------|------------------------------|---------------|
| [resource name] | create/modify/destroy | Yes/No | pre-merge/post-merge |

### Deploy Timing Guidance
- **Pre-merge** (recommended): When Python code depends on the infrastructure existing (e.g., S3 bucket the code writes to). Apply terraform before running integration tests.
- **Post-merge**: When infrastructure is additive and Python code has local fallback (e.g., optional S3 backend with local fallback).

### Rollback Notes
- For new resources: document `terraform destroy -target=<resource>` command
- For modified resources: note data migration or state considerations
```

Also add to the plan template in Step 7:
- Add `## Infrastructure Dependencies (if applicable)` section placeholder
- Add `## Deploy Timing` field (pre-merge/post-merge)
**Acceptance**: `grep -q "Infrastructure Assessment\|Deploy Timing" .github/prompts/plan.prompt.md`

### Step 6: Add recommendation suggestion to plan.prompt.md
**File**: .github/prompts/plan.prompt.md
**Action**: modify
**Description**:
Add Step 3b after Step 3 (Clarify the Request):

```markdown
## Step 3b: Suggest Aligned Recommendations

Search `logs/.recommendations-log.jsonl` for open recommendations that align with the current task:
1. Extract keywords from the task description (file paths, module names, concepts)
2. Match against `title`, `file`, and `context` fields of open recommendations
3. Present top 3-5 matches (if any) to the human:

> "These open recommendations may align with your task:
> - **rec-XXX**: [title] (effort: [effort], priority: [priority])
> - **rec-YYY**: [title] (effort: [effort], priority: [priority])
>
> Want to bundle any of these into this session? Say 'include rec-XXX' or 'skip' to proceed without."

If the human includes recommendations, add them to the plan's Scope and Ordered Execution Steps.
```
**Acceptance**: `grep -q "Aligned Recommendations\|recommendations-log.jsonl" .github/prompts/plan.prompt.md`

### Step 7: Add Infrastructure Deployment Phase to implement.prompt.md
**File**: .github/prompts/implement.prompt.md
**Action**: modify
**Description**:
Add new section after Step 6 (Execute Steps in Order), before Step 7 (Post-Implementation Checks):

```markdown
## Step 6b: Infrastructure Deployment Gate (if plan has .tf files)

If the plan's Scope table contains any `.tf` files:

1. **Run terraform plan**:
   ```bash
   terraform -chdir=terraform plan -out=tfplan
   ```

2. **Present the plan summary** to the human:
   > "Terraform plan shows:
   > - [N] resources to add
   > - [N] resources to change
   > - [N] resources to destroy
   >
   > Apply now? Say 'apply' to proceed, or 'defer' to skip (mark as post-merge task)."

3. **If 'apply'**:
   ```bash
   terraform -chdir=terraform apply tfplan
   ```
   Then run integration smoke tests if defined in the plan.

4. **If 'defer'**:
   Add to session notes: "Terraform apply deferred to post-merge. Run `terraform apply` after PR is merged."
   Continue to Step 7.

**Important**: Never auto-apply. Always wait for explicit human confirmation.
```
**Acceptance**: `grep -q "Infrastructure Deployment Gate\|terraform.*apply" .github/prompts/implement.prompt.md`

### Step 8: Add Decision 35 to DECISIONS.md
**File**: docs/DECISIONS.md
**Action**: modify
**Description**:
Add Decision 35:

```markdown
## Decision 35: Terraform Workflow Integration (Decided)

**Decision:** Integrate terraform plan/apply gates into the `/plan` and `/implement` workflow for infrastructure changes.

**Context:**
- Terraform files (.tf) were validated syntactically (terraform validate, fmt) but never planned/applied during implementation
- The `agent/infra-s3-logs` session created S3 bucket resources but had no verification they would actually deploy
- Infrastructure errors were discovered post-merge rather than during implementation

**Implementation:**
1. `plan.prompt.md` Step 5b adds Infrastructure Assessment section when scope includes .tf files
2. `implement.prompt.md` Step 6b adds Infrastructure Deployment Gate with human-confirmed apply
3. `session_preflight.py` reports `terraform_pending` status
4. `validate.py` warns when terraform changes are pending

**Rationale:**
- Catches infrastructure configuration errors during implementation, not post-merge
- Maintains human-in-the-loop for terraform apply (no auto-apply)
- Aligns with Decision 24 (agents use sandbox only; promotion is human-triggered)

**Trade-offs:**
- Adds friction to purely additive infrastructure changes
- Requires AWS SSO session for plan (not just validate)
- Mitigated by "defer to post-merge" option for low-risk additions
```
**Acceptance**: `grep -q "Decision 35" docs/DECISIONS.md`

### Step 9: Update both copilot instruction files
**Files**: .github/copilot-instructions.md (CLI), .github/copilot_instructions.md (VS Code)
**Action**: modify
**Description**:
Add to Known Gotchas section in BOTH files (they must stay in sync):

```markdown
- **Terraform workflow integration (Important):** When a plan includes `.tf` files, `implement.prompt.md` Step 6b requires running `terraform plan` and presenting the output to the human before proceeding. Terraform apply is NEVER automatic — always wait for explicit "apply" confirmation. If the human says "defer", mark as post-merge task and continue. Plans with `.tf` files should include an "Infrastructure Dependencies" section documenting deploy timing (pre-merge vs post-merge) and rollback commands.
```
**Acceptance**: `grep -q "Terraform workflow integration" .github/copilot-instructions.md && grep -q "Terraform workflow integration" .github/copilot_instructions.md`

### Step 10: Run pytest
**File**: N/A
**Action**: verify
**Description**: Run full test suite to verify all changes work together.
**Acceptance**: `python -m pytest tests/ -q`

### Step 11: Run validate.py
**File**: N/A
**Action**: verify
**Description**: Run full validation to ensure CI will pass.
**Acceptance**: `python scripts/validate.py`

### Step 12: Report implementation summary
**File**: N/A
**Action**: report
**Description**: Summarize what was implemented, confirm acceptance criteria met, note any deviations from plan.
**Acceptance**: N/A (human review)
