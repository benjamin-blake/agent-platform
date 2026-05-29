---
name: planning
description: Deep methodology and rules for software planning, complexity assessment, and verification tier design. Use this when running the /plan workflow or when architecting new features.
---

# Planning Methodology & Rules

You are using this skill to augment the `/plan` workflow. Apply these deep instructions when executing the workflow steps. You must NEVER initiate modifications to source code or global instructions (GEMINI.md, copilot-instructions.md, skills) during a planning session. The planning phase ends with the commitment of the PLAN artifact. Implementation only begins after an explicit /implement trigger with ANOTHER agent.

## Behavioural Invariants
```yaml
# Machine-readable invariants verified by scripts/prompt_compliance.py
preflight_run: true                # session_preflight.py must run at Step 1
branch_creation: true              # must create agent/{slug} branch before writing plan
critique_gate: true                # @plan-critique must be invoked before completion
never_on_main: true                # no file edits while on main branch
```

## Preflight Constraints (Workflow Step 1)
When reading `logs/.preflight-report.json`, apply these conditionals:
- **`venv_ok: false`** -- Auto-activate venv (`source .venv/Scripts/activate`) and rerun preflight. If still false, STOP.
- **`creds_status: "unavailable"`** -- **Static-key recovery (non-fatal, Decision 60):** the static-key assume-role chain has no interactive login. Verify it with `aws sts get-caller-identity --profile agent_platform`; if the `agent_static` key was rotated, refresh `~/.aws/credentials`. Do NOT block -- continue in degraded mode (credential-dependent verifiers are skipped, emitting SKIPPED). Autonomous executors never attempt recovery.
- **`log_sync_result.status == "committed"`** -- Print: "Session logs synced to main ([N] file(s) committed)." Continue.
- **`log_sync_result.status == "conflict"`** -- STOP. Print error and require human resolution.
- **`uncommitted_changes` non-empty** -- Ask human: "Resume, stash, or discard?". Wait.
- **`cron_review_fresh: false`** -- Note to human (non-blocking).
- **`outbox_synced: false`** -- Run `python -m scripts.sync_ops pull` to drain outbox and sync data (Decision 51). If fails, STOP.
- **`open_recommendations > 0`** -- Surface counts and ask whether to address. Wait.
- **`non_automatable_recommendations > 0`** -- MANDATORY discussion. Present each and require human decision (break down, keep open, or decline). Wait.
- **`friction_patterns` non-empty** -- Surface repeated patterns as planning context.
- **`metrics_anomalies` non-empty** -- Surface anomalies as planning context.
- **`token_anomalies` non-empty** -- Surface as planning context: "Context file token warning: [file list] exceed the 50K token threshold."
- **`data_quality.last_run.verdict == "FAIL"`** -- Surface as planning context: "Data quality checks failing ([N] failures across [tables]). Run `python -m scripts.data_quality_runner` for details." Non-blocking but relevant if the plan touches data pipelines or table schemas.
- **`data_quality.last_run` is null** -- Note: "Data quality checks have never been run. After fixing the pipeline, run `python -m scripts.data_quality_runner` to establish a baseline." Non-blocking.
- **`ci_rca_recs` non-empty** -- Surface as planning context: "[N] CI RCA rec(s) open -- these block the merge gate; recommend addressing before new feature work." Non-blocking but high priority.

### What Telemetry Health Represents

The preflight `telemetry_health` section reports operational health of the telemetry and ops data pipelines:

1. **Session metrics** (from Athena): session count over 7 days, success rate, and staleness of the latest session. These answer: "Is the system producing telemetry records and are they reaching Athena?"

2. **Data quality coverage** (from `config/agent/data_quality/*.yaml`): how many declarative checks (not_null, unique, accepted_values, relationships, row_count, recency) are defined across how many tables. This answers: "Do we have visibility into data correctness?"

3. **Last DQ run result** (from `logs/debug/dq-latest.json`): the verdict (PASS/FAIL), pass/fail/warn counts, and timestamp of the most recent `python -m scripts.data_quality_runner` execution. This answers: "When we last checked, was the data actually correct?"

Together these form a three-layer health picture:
- **Pipeline health**: Is data flowing? (session count > 0, staleness < 72h)
- **Quality coverage**: Do we have checks defined? (checks_defined > 0)
- **Quality state**: Are the checks passing? (last_run.verdict == PASS)

If pipeline health is critical (no sessions in 7 days), the plan should prioritise pipeline fixes before adding new features. If quality coverage is zero, any plan touching data write paths should include adding YAML checks. If the last DQ run failed, the plan should note which tables are affected.

## Clarification (Workflow Step 3)
Decompose the human's input into structured components:
| Component | Question to answer |
|-----------|-------------------|
| **Goal** | What outcome does the human actually want? (not just what they said) |
| **Constraints** | What explicit limits were stated? (time, scope, technology, cost) |
| **Acceptance criteria** | How will the human know when this is done? |
| **Affected areas** | Which files, modules, or infrastructure will be touched? |
| **Phase alignment** | Does this fall within the current roadmap phase? Does it depend on something not yet built? |

If the request is vague or missing key information, ask between 2 and 5 questions -- ranked by impact, no padding questions. Wait for answers before continuing.

## Suggest Aligned Recommendations
Search `logs/.recommendations-log.jsonl` for open recommendations that align with the current task (ensure cache is fresh via `python -m scripts.sync_ops pull` during preflight):
1. Extract keywords from the task description (file paths, module names, concepts)
2. Match against `title`, `file`, and `context` fields of open recommendations
3. Present top 3-5 matches (if any):
> "These open recommendations may align with your task:
> - **rec-XXX**: [title] (effort: [effort], priority: [priority])
>
> Want to bundle any into this session? Say 'include rec-XXX' or 'skip'."

## Documentation Artefact Design

This repository is agent-first. When a plan creates or modifies documentation artefacts,
apply these rules:

- Prefer extending an existing machine-readable source over creating a new document.
- A new file is warranted only when it has a distinct machine-parseable role (e.g., a
  decision manifest YAML, a registry YAML). Never create a human-readable companion
  alongside a machine-readable source -- that produces drift by design.
- Canonical field documentation pattern: ops.yaml extended contract. Add `description`
  and `semantics` metadata fields directly to the column entry in ops.yaml or
  telemetry.yaml. These fields are ignored by the DQ runner and consumed by agents.
  Do not create a separate briefing doc for the same information.
- When a plan step proposes a new document, ask: "Could this information be a metadata
  field in an existing YAML?" If yes, prefer that over a new file.

## Infrastructure & Lambda Assessment (Workflow Step 4)
**Infrastructure:** If `.tf` files are in scope, add an "Infrastructure Dependencies table" to the plan. Lambda handlers must accept a `force_{param}` event field. Pre-merge vs Post-deploy timing must be specified.
**Lambda Deployment:** If ANY scope file is Lambda-packaged (`config/config.yaml`, `config/lambda/<name>/`, `src/data/handlers/`, `scripts/llm_client.py`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`), the plan MUST include build, deploy, smoke-test, and model ID validation steps. Note: `config/agent/` is NOT Lambda-packaged and does NOT trigger this assessment. If `.tf` modifies IAM, terraform apply must precede Lambda deploy.

## Complexity Assessment (Workflow Step 4)
- **Scope files > 5** OR **estimated steps > 8** --> Plan Type must be **STRATEGIC**.
- If STRATEGIC, Work Areas must have precise lists, clear order, and concrete names.
- If IMPLEMENTATION (and complex), execution steps must have explicit pre/post-conditions.
- **Presentation Rule:** The classification MUST be presented to the human and confirmed, not assumed.


## Verification Tier Guidelines (Workflow Step 5)
Classify deterministically. Highest tier wins.
- **V1 (Static):** Docs, configs, markdown.
- **V2 (Unit):** Python source with no external integration. Must exercise real code paths.
- **V3 (Integration):** External systems, Terraform, Lambdas. Must tag steps as `[pre-deploy]` or `[post-deploy]`.

**VP Design Rationale:**
When writing Verification Plan steps, ask: "If this feature had a subtle bug (wrong column name, missing permission, off-by-one filter), would this step catch it?" If no, the step is too shallow.

**Anti-patterns to reject:**
- Structural-only: `grep -q "def my_function" src/module.py` -- proves existence, not function
- Test-only: "Run pytest" -- proves mocked paths work, not the real integration
- Existence-only: "Confirm the Athena view was created" -- does not confirm it returns correct data
- Import-only: "Confirm `import module` succeeds" -- loading without error is not verification
- Terraform-only: "Confirm `terraform apply` succeeded" -- infrastructure existing is not enough
- Prose-only VP step: VP step describes what to check but has no executable command -- the implement agent will substitute a weaker check

## Confirmation Gate (Workflow Step 6)
Wait for explicit 'write the plan' (or clear equivalent) before proceeding. Any other response is feedback -- incorporate it, re-present, and ask again.
IT IS **CRITICAL** THAT YOU DO NOT PROCEED UNTIL THE HUMAN CONFIRMS THE PLAN.

## Create Branch (Workflow Step 7)
The plan filename must match what find_plan.py will derive from the branch name (branch prefix agent/ is stripped, remainder is the slug).
e.g., if plan is `docs/plans/PLAN-fix-telemetry-drift.md`, branch must be `agent/fix-telemetry-drift`.

## PLAN-{slug}.md Template (Workflow Step 8)
Use exactly this structure:
```markdown
# Plan

## Intent
[1-2 sentences: how this work contributes toward the North Star.]

## Plan Type
IMPLEMENTATION / STRATEGIC / REPORT-ONLY

## Verification Tier
V1 / V2 / V3

## Branch
agent/{slug}

## Phase
[phase number and name from ROADMAP.md]

## Scope
| File | Action | Purpose |
|------|--------|---------|
| [path] | Create / Modify / Delete | [why] |

## Bundled Recommendations
[List any included open recs, or "None".]

## Infrastructure Dependencies (if applicable)
[Only if .tf files appear in Scope.]

## Acceptance Criteria
- [ ] [verifiable condition 1]

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | [exercise the feature] | `[executable shell command]` | [specific expected result] | [what failure looks like] |

## Constraints
- [limits from copilot-instructions.md and DECISIONS.md]
- No rescue agents or workaround loops (Decision 55)

## Context
- [Relevant decisions, phase dependencies, known gotchas]

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. [Specific file to create/modify -- what it must do]
N. **Execute Verification Plan** -- run each step. Loop until pass. If V3 fails unrecoverably, stop and analyze root cause (Decision 55).
N+1. Report: what was implemented, verification results.

## Work Areas (STRATEGIC plans only)
| Area | Scope | Rationale | Complexity |
|------|-------|-----------|------------|
| [area name] | [files affected] | [why] | XS/S/M/L/XL |
```

**Platform compatibility:** Verify shell commands are Windows-compatible. Use Python scripts for automation.

## Critique Gate (Workflow Step 9)
**DO NOT output the completion message until this step completes.**
Run the automated zero-context critique using the CLI:
```bash
python -m scripts.agent_development.run_skill --skill plan-critique --target docs/plans/PLAN-{slug}.md --context .github/copilot-instructions.md docs/ROADMAP-PRODUCT.md docs/ROADMAP-PLATFORM.yaml docs/DECISIONS.md
```
Read the critique output from the terminal.
If it suggests revisions, update the plan with these fixes.
Loop if REVISE. Proceed if PROCEED.

## Confirmation Messages (Workflow Step 11)
- **IMPLEMENTATION:** "Planning complete. `docs/plans/PLAN-{slug}.md` is ready and committed to branch `agent/{slug}`. Review and edit if needed. When satisfied, open a new chat and send **`/implement`**."
- **STRATEGIC:** "Planning complete. `docs/plans/PLAN-{slug}.md` is ready with Work Areas for scoping. Review and edit if needed. When satisfied, open a new chat and send **`/implement`**."
- **REPORT-ONLY:** "Planning complete. PLAN-{slug}.md contains a report/analysis for your review -- no implementation steps. Decide which items to act on, then start a new planning session for each. Do **not** send `/implement`."

**DO NOT PERFORM ANY FURTHER ACTIONS**
