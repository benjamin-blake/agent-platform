---
name: plan
description: Interactive planning session. Run this before any implementation work. Clarifies intent, loads project context, checks phase alignment, and produces PLAN-{slug}.md — a self-contained implementation brief for the next agent chat. Use when starting a new feature, fix, or any code change.
agent: agent
model: Claude Opus 4.6 (copilot)
tools: ['read', 'search', 'execute/runInTerminal', 'execute/getTerminalOutput', 'edit/editFiles', 'agent']
---

## Intent

Clarify the human's intent, orient against the project, and produce a complete self-contained PLAN-{slug}.md that any agent can execute without further interaction. Does not implement anything.

---

## Behavioural Invariants

```yaml
# Machine-readable invariants verified by scripts/prompt_compliance.py
preflight_run: true                # session_preflight.py must run at Step 1
branch_creation: true              # must create agent/{slug} branch before writing plan
critique_gate: true                # @plan-critique must be invoked before completion
never_on_main: true                # no file edits while on main branch
```

---

## Step 1: Run Preflight

```bash
python scripts/session_preflight.py
```

Read `logs/.preflight-report.json` and apply these conditionals before continuing:

- **`venv_ok: false`** -- Auto-activate venv:
  ```bash
  source .venv/Scripts/activate
  python scripts/session_preflight.py
  ```
  If `venv_ok` is still `false` after one attempt, STOP and report the error. Do not retry.

- **`sso_status: "expired"` or `"unknown"`** -- Auto-login to AWS SSO:
  ```bash
  aws sso login --profile company-aws-profile
  ```
  If the login command fails, STOP and report the error. Do not retry. If login succeeds, continue.

- **`log_sync_result.status == "committed"`** -- Print: "Session logs synced to main ([N] file(s) committed)." Continue.

- **`log_sync_result.status == "conflict"`** -- STOP. Print: "Log sync failed: push conflict on `main`. Conflict details: [log_sync_result.error]". Do not proceed until the human resolves the conflict.

- **`uncommitted_changes` non-empty or `stash_entries > 0`** -- Surface the list. Ask: "There are uncommitted changes on `[branch]`. Resume, stash, or discard?" Wait for the human's decision.

- **`cron_review_fresh: false`** -- Note: "Scheduled agent review has not run in 7 days. Consider running a manual check before planning." (non-blocking)

- **`open_recommendations > 0` or `aging_recommendations > 0`** -- Surface the counts. Ask whether to address any in this session. Wait for the human's answer before continuing.

- **`non_automatable_recommendations > 0`** -- MANDATORY DISCUSSION. Present each non-automatable rec:
  > "These recommendations are marked non-automatable and need human discussion:
  > - **rec-XXX**: [title] -- [context excerpt]
  >
  > For each, decide: (1) break into smaller automatable recs, (2) keep open with blocker noted, (3) decline with resolution."
  Wait for the human's response. Do not proceed until all non-automatable recs are addressed.

- **`friction_patterns` non-empty** -- Surface repeated patterns as planning context.

- **`metrics_anomalies` non-empty** -- Surface anomalies as planning context.

- **`token_anomalies` non-empty** -- Surface as planning context: "Context file token warning: [file list] exceed the 50K token threshold."

- **`data_quality.last_run.verdict == "FAIL"`** -- Surface: "Data quality checks failing ([N] failures). Run `python -m scripts.data_quality_runner` for details." Non-blocking but relevant if the plan touches data pipelines or table schemas.

- **`data_quality.last_run` is null** -- Note: "Data quality checks have never been run. Run `python -m scripts.data_quality_runner` to establish baseline." Non-blocking.

### What Telemetry Health Represents

The preflight `telemetry_health` and `data_quality` sections together report the health of the data pipelines:

- **Pipeline health** (`telemetry_health`): Is data flowing? Session count over 7 days, success rate, staleness. If `overall: "critical"` (no sessions in a week), pipeline fixes take priority over feature work.
- **Quality coverage** (`data_quality.checks_defined`): Are declarative data quality checks defined? These are dbt-style assertions (not_null, unique, accepted_values, FK relationships, row_count, recency) declared in `config/data_quality/*.yaml` and compiled to Athena SQL by `scripts/data_quality_runner.py`.
- **Quality state** (`data_quality.last_run`): When checks were last executed and whether they passed. A FAIL verdict means the data in Athena has integrity issues (null PKs, broken FKs, invalid enum values, empty tables, or stale data).

If pipeline health is critical, prioritise pipeline fixes. If quality coverage is zero for a table the plan modifies, add YAML checks to the plan scope. If the last DQ run failed, note affected tables in the plan context.

The preflight JSON also contains a `context` section -- use it in Step 2 below.

After all preflight conditions are handled, open a telemetry session:
```bash
python -m scripts.session_preflight --open-session --workflow plan
```
Save the printed UUID. Pass `--session-id <UUID>` to any `run_skill` invocations (e.g., critique gate in Step 9).

---

## Step 2: Read Context from Preflight

The preflight JSON `context` field contains pre-read summaries:

- **`context.roadmap_phase`** -- Current roadmap phase and name. Reference this in phase alignment checks.
- **`context.open_decisions_count`** -- Number of open architectural decisions. If > 0, new work should not conflict.
- **`context.recent_sessions`** -- Last 5 session summaries (date + Done line). Use to understand project momentum.
- **`context.strategic_review_due`** -- If `true`, mention to the human that a strategic review is overdue (non-blocking).

Also read `.github/copilot-instructions.md` fully (rules, branching, file router, known gotchas) -- this is not in the preflight summary.

If the human's request references a specific recommendation ID (e.g., "implement rec-002") or mentions implementing from a parent plan:

1. **Read JSONL entry:** Search `logs/.recommendations-log.jsonl` for the recommendation ID. Extract `context`, `dependencies`, and `acceptance` fields.
2. **Check for briefing file:** If `docs/plans/briefings/BRIEFING-{id}.md` exists, read it.
3. **Load dependencies:** For each ID in the `dependencies` array, read its JSONL entry. Note `status: "closed"` vs `status: "open"`.
4. **Reference parent plan:** If the recommendation came from a REPORT-ONLY plan, read that plan for broader context.

---

## Step 3: Clarify the Request

Decompose the human's input into structured components:

| Component | Question to answer |
|-----------|-------------------|
| **Goal** | What outcome does the human actually want? (not just what they said) |
| **Constraints** | What explicit limits were stated? (time, scope, technology, cost) |
| **Acceptance criteria** | How will the human know when this is done? |
| **Affected areas** | Which files, modules, or infrastructure will be touched? |
| **Phase alignment** | Does this fall within the current roadmap phase? Does it depend on something not yet built? |

If the request is vague or missing key information, ask between 2 and 5 questions -- ranked by impact, no padding questions. Wait for answers before continuing. If clear, proceed directly to Step 4.

**Contradictions to watch for:**
- Conflicts with a prior decision in `DECISIONS.md`
- Dependencies on incomplete prerequisites from `ROADMAP.md`
- Task belongs to a future phase

Report any conflicts and ask for clarification before proceeding.

### Suggest Aligned Recommendations

Search `logs/.recommendations-log.jsonl` for open recommendations that align with the current task:
1. Extract keywords from the task description (file paths, module names, concepts)
2. Match against `title`, `file`, and `context` fields of open recommendations
3. Present top 3-5 matches (if any):

> "These open recommendations may align with your task:
> - **rec-XXX**: [title] (effort: [effort], priority: [priority])
>
> Want to bundle any into this session? Say 'include rec-XXX' or 'skip'."

If the human includes recommendations, add them to the plan's Scope and Ordered Execution Steps.

---

## Step 4: Identify Affected Files

1. Use the File Router in `copilot-instructions.md` to locate relevant source files.
2. Read those files to understand the current implementation.
3. Check `tests/` for existing tests covering those files:
   ```bash
   git grep -r "from src.<module>" tests/
   ```
4. Note which tests will need to be updated or created.

### Infrastructure Assessment (if .tf files in scope)

If the Scope table contains any `.tf` files, add the following to the plan:

**Infrastructure Dependencies table:**

| Resource | Terraform Action | Python Code Depends On This? | Deploy Timing | Post-deploy Verification |
|----------|-----------------|------------------------------|---------------|--------------------------|
| [resource name] | create/modify/destroy | Yes/No | pre-merge/post-merge | [how to verify] |

For Lambda resources in scope:
- Handler must accept a `force_{param}` event field for manual post-deploy invocation
- Acceptance Criteria must include an invocation test:
  `aws lambda invoke --function-name <name> --payload '{"force_run":true}' --profile company-aws-profile out.json`

Deploy timing: **Pre-merge** when Python code depends on the infrastructure existing. **Post-merge** when infrastructure is additive with local fallback. For new resources, document `terraform destroy -target=<resource>` command. For modified resources, note data migration or state considerations.

### Lambda Deployment Assessment

If ANY scope file is Lambda-packaged (files under `src/data/handlers/`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`, `config/`, or scripts in `_LAMBDA_SCRIPTS` in `build_lambda.py`), the plan MUST include:

1. `python -m scripts.build_lambda` to rebuild the zip
2. `python -m scripts.build_lambda --deploy` to upload to S3 and update Lambda function code
3. `python -m scripts.run_scheduled_agent --smoke-test <agent-name>` to verify deployment
4. Model ID validation if any model ID is added or changed (per `docs/contracts/inference-provider.md`)

If `.tf` files modify Lambda IAM permissions, terraform apply MUST precede Lambda deploy.

Reference: Decision 47 (docs/DECISIONS.md), docs/contracts/inference-provider.md

### Complexity Assessment

1. Count Scope files and estimated execution steps.
2. If **Scope files > 5** OR **estimated steps > 8** --> Plan Type must be **STRATEGIC**.
3. Otherwise, Plan Type can be IMPLEMENTATION or STRATEGIC.

If STRATEGIC, each Work Area must have: precise file lists, independence or clear dependency order, no cross-layer spanning, concrete names, and a rationale.

If IMPLEMENTATION for complex work, Ordered Execution Steps must have explicit pre-conditions and post-conditions per step.

---

## Step 5: Verification Tier and Verification Plan

Every plan must declare a Verification Tier and include a Verification Plan. The Verification Plan is NOT the same as Acceptance Criteria. Acceptance Criteria define WHAT must be true. The Verification Plan defines HOW the agent will prove it works by exercising the feature with real inputs and inspecting real outputs.

### Tier Classification

Classify deterministically based on scope files. **Highest tier wins.**

**V1 (Static):** Scope contains only docs, prompts, configs, markdown, or YAML with no runtime effect.

**V2 (Unit):** Scope contains Python source files (scripts/, src/) with no external integration.

**V3 (Integration):** Scope contains files that interact with external systems. Triggers: `src/data/handlers/`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`, `terraform/*.tf` with runtime resources, files in `_LAMBDA_SCRIPTS`, or changes to cross-service contracts.

### Verification Plan Design

When writing Verification Plan steps, ask: **"If this feature had a subtle bug (wrong column name, missing permission, off-by-one filter), would this step catch it?"** If no, the step is too shallow.

**Every VP step MUST include a `Command` column** containing a literal shell command (Bash) or Python one-liner that the implementing agent can execute verbatim. Prose-only VP steps are rejected by the critique agent. The command must produce observable output that proves the expected outcome.

For V3 steps that require human-gated actions (e.g., `terraform apply`), split into: (a) a human-gated step with the apply command, and (b) a separate agent-executable post-deploy verification command.

**V1:** Confirm configs parse without error, docs render correctly.
- Example: "Write a 2-line Python script to `tmp_vp.py` that calls `yaml.safe_load(open('config/new.yaml'))` and prints 'OK'. Run `python tmp_vp.py` and confirm no parse error."

**V2:** Exercise the changed code path with real (non-mocked) input beyond what unit tests cover. Run the actual script/module with representative input and confirm output.
- Example: "Run `python -m scripts.sync_recommendations --dry-run` and confirm expected recommendation count."
- Example: "Run the new validation with intentionally malformed input and confirm correct error message."

**V3:** Deploy the artifact, invoke it, confirm the response/side-effects. Inherits all V2 requirements.
- Example: "Create Athena view, run `SELECT COUNT(*) FROM view_name`, confirm count > 0 and columns match schema."
- Example: "Deploy Lambda, invoke with test payload, confirm S3 output file exists with correct schema."

**V3 plans must tag each VP step as `[pre-deploy]` or `[post-deploy]`.** Pre-deploy steps are agent-executable without infrastructure changes (local Python, `terraform validate`). Post-deploy steps require `terraform apply` or Lambda deploy to have completed. The implement agent uses these tags to sequence verification correctly -- all pre-deploy steps run first, then the human-gated deploy, then all post-deploy steps. No merging until post-deploy steps pass.

**Anti-patterns to reject:**
- Structural-only: `grep -q "def my_function" src/module.py` -- proves existence, not function
- Test-only: "Run pytest" -- proves mocked paths work, not the real integration
- Existence-only: "Confirm the Athena view was created" -- does not confirm it returns correct data
- Import-only: "Confirm `import module` succeeds" -- loading without error is not verification
- Terraform-only: "Confirm `terraform apply` succeeded" -- infrastructure existing is not enough
- Prose-only VP step: VP step describes what to check but has no executable command -- the implement agent will substitute a weaker check

Reference: Decision 48 (docs/DECISIONS.md)

---

## Step 6: Create Branch

```bash
git checkout main
git pull origin main
git checkout -b agent/{slug}
git branch --show-current
```

Derive slug from the task description: `{phase}-{brief-slug}` (e.g., `1.5-backfill-handler`, `infra-slim-ci`). If the output of `git branch --show-current` is `main`, STOP and report the error.

---

## Step 7: Present Findings and Confirm Approach

Present your analysis to the human:

1. **Summary** -- Key findings from context loading (roadmap state, relevant decisions, open recommendations)
2. **Proposed approach** -- How you interpret the request and what you plan to include in the plan
3. **Options** (if applicable) -- Alternative approaches with trade-offs
4. **Open questions** (if any) -- Remaining ambiguities that affect scope

Then ask:
> "Does this approach look right? Say **'write the plan'** when you are ready, or tell me what to adjust."

Wait for explicit "write the plan" (or clear equivalent) before proceeding. Any other response is feedback -- incorporate it, re-present, and ask again.

---

## Step 8: Write PLAN-{slug}.md

Write the file `docs/plans/PLAN-{slug}.md`. If it already exists, use `replace_string_in_file` to replace all contents.

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
[Only if .tf files appear in Scope. See Step 4 Infrastructure Assessment.]

## Acceptance Criteria
- [ ] [verifiable condition 1]
- [ ] [verifiable condition 2]

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | [exercise the feature with real input] | `[executable shell command]` | [specific expected result] | [what failure looks like] |
| 2 | [post-deploy] | [...] | `[...]` | [...] | [...] |

## Constraints
- [limits from copilot-instructions.md and DECISIONS.md]

## Context
- [Relevant decisions, phase dependencies, known gotchas]

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. [Specific file to create/modify -- what it must do]
2. [...]
N-2. Run `pytest tests/` -- all tests must pass
N-1. Run `python scripts/validate.py` -- must exit 0
N. **Execute Verification Plan** -- run each step from the table above. If a step fails, fix the code, re-run tests + validate, and re-attempt. Loop until all steps pass. Do NOT merge with failing verification.
N+1. Report: what was implemented, verification results (actual outcomes), bugs found and fixed

## Work Areas (STRATEGIC plans only)
| Area | Scope | Rationale | Complexity |
|------|-------|-----------|------------|
| [area name] | [files/modules affected] | [why this area exists] | XS/S/M/L/XL |
```

Ordered Execution Steps must be specific enough that any agent can execute them without reading any file other than `PLAN-{slug}.md` and the files listed in Scope. Do not use vague verbs like "implement" or "update" without qualifying what the change must achieve.

**Platform compatibility:** Verify shell commands are Windows-compatible. Use Python scripts for automation per `copilot-instructions.md`.

After writing, commit to the branch:

```bash
git add docs/plans/PLAN-{slug}.md
git commit -m "plan({slug}): initial plan"
```

---

## Step 9: Plan Critique Gate (MANDATORY)

**DO NOT output the completion message until this step completes.**

Invoke `@plan-critique` with the path to the plan file.

**If REVISE:** Present findings to the human. Ask: "Update the plan with these fixes, or proceed anyway?" If "update", apply fixes and re-invoke (loop until PROCEED or human override). If "proceed anyway", emit the override as a process event: `python -c "from scripts.executor.telemetry import emit_process_event; emit_process_event(tier='decision', category='critique_skip', severity='info', description='Human overrode critique gate', detected_by='manual')"`.

**If PROCEED:** Continue to Step 10.

---

## Step 10: Confirm

After the plan critique passes, output the appropriate message based on `## Plan Type`:

**IMPLEMENTATION:**
> **Planning complete.** `docs/plans/PLAN-{slug}.md` is ready and committed to branch `agent/{slug}`.
> Review and edit if needed. When satisfied, open a new Copilot Chat and send **`/implement`**.
> After implementation, start a new chat with the `code-review` agent.

**STRATEGIC:**
> **Planning complete.** `docs/plans/PLAN-{slug}.md` is ready with Work Areas for scoping.
> Review and edit if needed. When satisfied, open a new Copilot Chat and send **`/implement`**.
> The implement session will research each Work Area and produce atomic recommendations for the executor.

**REPORT-ONLY:**
> **Planning complete.** PLAN-{slug}.md contains a report/analysis for your review -- no implementation steps.
> Decide which items to act on, then start a new planning session for each. Do **not** send `/implement`.

Finally, close the telemetry session:
```bash
python -m scripts.session_postflight --close-session --outcome success
```
Use `--outcome cancelled` if the plan was abandoned or not written.
