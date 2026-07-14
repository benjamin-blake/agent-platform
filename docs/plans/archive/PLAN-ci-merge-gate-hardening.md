# Plan

## Intent
Restore the remote CI merge gate to green by closing three IAM gaps and one verifier bug, then codify and implement the architectural response to future CI failures: an auto-triggered ci-rca agent that files recs (source=ci_rca) consumed via the standard /plan -> /implement flow. Bundles two hygiene fixes (`.gitignore` for transient state, `git pull --rebase` in `/plan`) that prevent the conflict class hit during this session's preflight.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/ci-merge-gate-hardening

## Phase
Phase 2 / Operational Hardening (per preflight: Phase 1 Core Infrastructure complete)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `terraform/ec2_runner.tf` | Modify | Add three IAM statements to `aws_iam_policy.github_runner_ci`: (a) `s3:DeleteObject` on `${runner_agent_logs}/tmp/*`; (b) `s3:GetBucketLocation` on BOTH `${runner_data_lake}` AND `${runner_agent_logs}` bucket-level (belt-and-suspenders -- the immediate failure is on data-lake per CI logs, but preflight uses agent-logs as its Athena output bucket; granting on both eliminates a likely-next-failure round trip); (c) `glue:DeleteTable`/`glue:CreateTable`/`glue:UpdateTable` on `catalog`, `database/trading_formulas_db`, `table/trading_formulas_db/*` |
| `scripts/verifiers/schema_integrity.py` | Modify | (1) Replace `set(model_cls.__dataclass_fields__.keys())` with `{f.name for f in dataclasses.fields(model_cls)}` -- the raw `__dataclass_fields__` dict includes `ClassVar` entries (with internal type `_FIELD_CLASSVAR`); the public `dataclasses.fields()` API correctly filters them. (2) Remove the `injected_cols` block (lines 98-102) entirely -- empirically confirmed redundant: Pydantic `Recommendation.model_fields` already contains `created_timestamp` and `last_updated_timestamp`, and every telemetry dataclass already declares `ingested_at`/`trade_date` as real fields with default factories. The two stray names (`ingested_at`/`trade_date` for `ops_recommendations`; `created_timestamp`/`last_updated_timestamp` for telemetry tables) are *not* actual columns and were the source of the false-positive drift report. |
| `docs/DECISIONS.md` | Modify | Add `## Decision 72: RCA-as-Plan-Source for CI Merge Gate Failures`. Codifies: workflow_run-triggered headless Claude agent on CI failure; agent diagnoses and files rec with `source="ci_rca"`; does not propose autonomous fix; human consumes via `/plan` referencing the rec. References Decisions 55 (RCA-first), 60 (two-tier validation), 61 (source as discriminator), 68 (self-hosted runner), 71 (cc-scheduled-agents pattern) |
| `CLAUDE.md` | Modify | Update "Merge protocol" section: remote CI on self-hosted runner is the authoritative pre-merge gate; local `--pre` is advisory edit-loop only; on CI failure, ci-rca agent auto-files a rec (do not manually fix until the rec is reviewed in a `/plan` session) |
| `.gitignore` | Modify | Add `logs/.complexity-warnings.json` and `logs/.execution-state.json` to the "S3-managed log files" section -- these are transient local execution artefacts, not git-tracked state |
| `.claude/commands/plan.md` | Modify | Insert `git pull --rebase origin main` between the existing preflight invocation and the preflight-report read at Step 1 -- self-healing for tracked-file divergence (today's conflict class) |
| `.agents/workflows/plan.md` | Modify | Same change as `.claude/commands/plan.md` -- per Decision 58, `.agents/` is the canonical interactive workflow layer; the `.claude/` file is the Claude Code consumer. Both must stay in sync. |
| `.claude/agents/scheduled/ci-rca.md` | Create | Self-contained agent definition (system prompt + tool allowlist + RCA methodology + rec-filing template). Methodology: fetch failing CI run logs via `gh run view <run-id> --log-failed`, diagnose root cause with evidence, call `python -m scripts.ops_data_portal file_rec --source ci_rca --priority critical --title <concise> --context <root-cause-with-evidence> --acceptance <unambiguous-condition>`. Explicit "do not propose autonomous fix" rule. No dedup logic (per architect direction -- exploration overlap with planning agent is acceptable). |
| `.github/workflows/ci-rca.yml` | Create | Trigger: `on: workflow_run: workflows: ["<CI workflow name>"], types: [completed]`. Guard: `if: github.event.workflow_run.conclusion == 'failure'`. Runs on `[self-hosted, linux]`. Steps: (1) checkout, (2) inject `CLAUDE_CODE_OAUTH_TOKEN` from repo secret, (3) invoke `claude -p` referencing `.claude/agents/scheduled/ci-rca.md` and `${{ github.event.workflow_run.id }}`, (4) on rec successfully filed, post comment to originating PR via `gh pr comment <pr-num> --body "ci-rca filed rec-XXX: <title>"`. Loop guard: `ci-rca.yml` is not in its own `workflows:` filter |
| `scripts/session_preflight.py` | Modify | Add "CI RCA Recs (open)" section. Athena query: `SELECT id, title, priority, created_timestamp FROM ops_recommendations_current WHERE source = 'ci_rca' AND status IN ('open', 'in_progress') ORDER BY created_timestamp DESC LIMIT 5`. Add `ci_rca_recs` array to preflight JSON output. Surface in stdout alongside existing Priority Queue table. **Use the existing `_run_athena_query` AWS-CLI-subprocess helper** -- do NOT introduce `awswrangler` as a preflight dependency (per Decision 50, `awswrangler` is a Lambda-only dep; the preflight pattern uses subprocess + `aws athena start-query-execution`). Mirror the existing pattern. |
| `.claude/skills/planning/SKILL.md` | Modify | Add one-line interpretation rule in **Preflight Constraints**: `**ci_rca_recs non-empty** -- Surface as planning context: "[N] CI RCA rec(s) open -- these block the merge gate; recommend addressing before new feature work."` |
| `.agents/skills/planning/SKILL.md` | Modify | Same change as `.claude/skills/planning/SKILL.md` -- per Decision 58, `.agents/` is the canonical interactive workflow layer. Both must stay in sync. |

## Bundled Recommendations
None. This is greenfield work driven by CI failures observed on 2026-05-11, not from the open-rec queue. The full preflight is included as Context for traceability.

## Infrastructure Dependencies
| Item | Type | Timing | Notes |
|------|------|--------|-------|
| `aws_iam_policy.github_runner_ci` | IAM policy update | Pre-merge (`terraform apply`) | Additive only -- three new `Statement` entries; existing statements unchanged. No resource recreation. |
| `terraform plan` output | Review artefact | Pre-apply | Must be presented to human before `terraform apply` per terraform/CLAUDE.md hard rule |
| Lambda deployment | Not applicable | -- | No Lambda-packaged files in scope. Decision 67 (Lambda deferral) does not apply. |
| CI workflow name discovery | Read-only | Pre-create `ci-rca.yml` | Must identify the precise name of the main CI workflow (likely `CI` or `ci` -- read `.github/workflows/ci.yml` `name:` field) to populate the `workflow_run` filter. Loop prevention depends on this being precise. |

## Acceptance Criteria
- [ ] Remote CI (Verification Harness V3) passes on `agent/ci-merge-gate-hardening` -- no `s3:DeleteObject`, `glue:DeleteTable`, or "Unable to verify/create output bucket" errors
- [ ] `SchemaIntegrityVerifier` output contains neither `REQUIRED_FIELDS` nor `TABLE_NAME` in any drift report
- [ ] `SchemaIntegrityVerifier` does not falsely flag `ingested_at`/`trade_date` as missing from `ops_recommendations`
- [ ] `DataQualityVerifier` errored-count drops materially (the cascading symptom should clear once Athena queries succeed)
- [ ] `.gitignore` causes `logs/.complexity-warnings.json` and `logs/.execution-state.json` to be untracked -- preflight no longer emits `log_sync_result.status == "conflict"` for these two files
- [ ] Both `.claude/commands/plan.md` AND `.agents/workflows/plan.md` Step 1 include `git pull --rebase origin main` -- belt-and-suspenders for future tracked-file divergence (Decision 58: canonical + consumer in sync)
- [ ] `docs/DECISIONS.md` contains `## Decision 72: RCA-as-Plan-Source for CI Merge Gate Failures` with the standard sections (Status, Date, Problem, Decision, Rationale, Related)
- [ ] `CLAUDE.md` "Merge protocol" section explicitly names remote CI as authoritative and instructs developers to wait for the ci-rca rec on failure (rather than manually patching)
- [ ] `.github/workflows/ci-rca.yml` exists, triggers on `workflow_run` with `conclusion == 'failure'`, runs on the self-hosted runner, and does not list itself in the `workflows:` filter (loop prevention)
- [ ] `.claude/agents/scheduled/ci-rca.md` is self-contained -- includes system prompt, tool allowlist, methodology, rec-filing template, and explicit "do not propose autonomous fix" rule
- [ ] `scripts/session_preflight.py` emits a "CI RCA Recs (open)" section and adds `ci_rca_recs` to the JSON output
- [ ] Both `.claude/skills/planning/SKILL.md` AND `.agents/skills/planning/SKILL.md` document the `ci_rca_recs` preflight interpretation rule (Decision 58: canonical + consumer in sync)
- [ ] End-to-end smoke test: a deliberately-failing CI run triggers `ci-rca.yml`, which files a rec with `source="ci_rca"` that lands in the warehouse via the next `OpsWriter.compact()` / staging-drain cycle (typically a few minutes; the smoke procedure runs an explicit `sync_ops sync` between the file_rec call and the Athena re-read to make visibility deterministic) and is surfaced by the next preflight run
- [ ] `ci-rca.yml` PR-comment step is guarded by `if:` conditional checking `github.event.workflow_run.pull_requests[0].number != ''` -- non-PR failures (e.g., pushes to main) must not break the workflow

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | Confirm Terraform IAM additions present | `.venv/Scripts/python.exe -c "t=open('terraform/ec2_runner.tf').read(); assert all(x in t for x in ['s3:DeleteObject','s3:GetBucketLocation','glue:DeleteTable','glue:CreateTable','glue:UpdateTable']); print('OK')"` | Prints `OK` | Add missing action strings to `aws_iam_policy.github_runner_ci` policy block |
| 2 | [pre-deploy] | Terraform plan shows additive IAM only, no destroys | `terraform -chdir=terraform plan -no-color 2>&1 | grep -E "(Plan:\|will be (created\|destroyed))"` | One update on `aws_iam_policy.github_runner_ci`; zero destroys | If destroys appear, the policy JSON re-ordered -- restructure additions to preserve existing statements |
| 3 | [pre-deploy] | SchemaIntegrityVerifier ClassVar fix works locally | `.venv/Scripts/python.exe -c "from scripts.verifiers.schema_integrity import SchemaIntegrityVerifier; import asyncio; r=asyncio.run(SchemaIntegrityVerifier().verify()); m=r.message or ''; assert 'REQUIRED_FIELDS' not in m and 'TABLE_NAME' not in m; print(r.status)"` | No ClassVar names appear in output; status is `PASS` or genuine drift (not false positives) | If ClassVar names still appear, confirm the edit changed `__dataclass_fields__.keys()` to `dataclasses.fields()` and added `import dataclasses` |
| 4 | [pre-deploy] | SchemaIntegrityVerifier injected_cols fix works | `.venv/Scripts/python.exe -c "from scripts.verifiers.schema_integrity import SchemaIntegrityVerifier; import asyncio; r=asyncio.run(SchemaIntegrityVerifier().verify()); m=r.message or ''; assert 'ops_recommendations' not in m or ('ingested_at' not in m and 'trade_date' not in m); print('OK')"` | `ingested_at`/`trade_date` do not appear as missing for `ops_recommendations` | If still present, confirm the `injected_cols` block was deleted entirely (not just modified) |
| 5 | [pre-deploy] | `.gitignore` covers the two state files | `git check-ignore logs/.complexity-warnings.json logs/.execution-state.json` | Both paths emitted | Add missing path(s) to `.gitignore` |
| 6 | [pre-deploy] | `/plan` command Step 1 has rebase line in BOTH canonical (.agents) and consumer (.claude) | `.venv/Scripts/python.exe -c "assert 'git pull --rebase origin main' in open('.claude/commands/plan.md').read() and 'git pull --rebase origin main' in open('.agents/workflows/plan.md').read(); print('OK')"` | Prints `OK` | Insert the line at Step 1 in both files (Decision 58 sync rule) |
| 7 | [pre-deploy] | Decision 72 present with required sections | `.venv/Scripts/python.exe -c "t=open('docs/DECISIONS.md').read(); assert '## Decision 72' in t and 'RCA-as-Plan-Source' in t and 'ci_rca' in t and 'Related:' in t.split('## Decision 72')[1].split('## Decision')[0]; print('OK')"` | Prints `OK` | Add missing section(s) -- Status, Date, Problem, Decision, Rationale, Related |
| 8 | [pre-deploy] | CLAUDE.md Merge protocol updated | `.venv/Scripts/python.exe -c "t=open('CLAUDE.md').read(); s=t.split('## Merge protocol')[1].split('##')[0]; assert 'ci-rca' in s.lower() and 'authoritative' in s.lower(); print('OK')"` | Prints `OK` | Add the missing language to the Merge protocol section |
| 9 | [pre-deploy] | ci-rca agent file is self-contained | `.venv/Scripts/python.exe -c "t=open('.claude/agents/scheduled/ci-rca.md').read(); assert all(x in t for x in ['gh run view','file_rec','ci_rca','do not propose autonomous fix']); print('OK')"` | Prints `OK` | Add any missing element |
| 10 | [pre-deploy] | ci-rca workflow has loop guard and failure filter | `.venv/Scripts/python.exe -c "t=open('.github/workflows/ci-rca.yml').read(); assert 'workflow_run' in t and \"conclusion == 'failure'\" in t and 'ci-rca' not in t.split('workflows:')[1].split(']')[0]; print('OK')"` | Prints `OK` (filter does not name self) | Adjust trigger filter to exclude this workflow's own name |
| 11 | [pre-deploy] | Preflight emits the new section | `.venv/Scripts/python.exe -m scripts.session_preflight 2>&1 | grep -E "CI RCA Recs"` | Section header appears (count can be 0 if no ci_rca recs yet) | Add the section to `session_preflight.py` print-output path |
| 12 | [pre-deploy] | Preflight JSON contains `ci_rca_recs` field | `.venv/Scripts/python.exe -c "import json; d=json.load(open('logs/.preflight-report.json')); assert 'ci_rca_recs' in d; print(type(d['ci_rca_recs']).__name__)"` | Prints `list` | Add the field to the JSON report builder |
| 13 | [pre-deploy] | Planning skill documents the new interpretation rule in BOTH canonical (.agents) and consumer (.claude) | `.venv/Scripts/python.exe -c "assert 'ci_rca_recs' in open('.claude/skills/planning/SKILL.md').read() and 'ci_rca_recs' in open('.agents/skills/planning/SKILL.md').read(); print('OK')"` | Prints `OK` | Add the one-line bullet under Preflight Constraints in both files (Decision 58 sync rule) |
| 14 | [pre-deploy] | Local `python -m scripts.validate` passes | `.venv/Scripts/python.exe -m scripts.validate` | Exit 0 | Address whatever check fails (lint/format/unit/etc.) |
| 14a | [pre-deploy] | ci-rca.yml PR-comment step is guarded for non-PR events | `.venv/Scripts/python.exe -c "t=open('.github/workflows/ci-rca.yml').read(); assert 'pull_requests[0].number' in t and ('if:' in t.split('gh pr comment')[0].split('\n')[-3:][0] or 'if:' in t.split('gh pr comment')[0]); print('OK')"` | Prints `OK` -- the gh pr comment step has an `if:` conditional referencing `github.event.workflow_run.pull_requests[0].number` | Add the `if:` guard to the PR-comment step so push-to-main failures do not break the workflow |
| 14b | [pre-deploy] | Preflight uses subprocess helper, not awswrangler | `.venv/Scripts/python.exe -c "t=open('scripts/session_preflight.py').read(); assert 'awswrangler' not in t and 'ci_rca' in t; print('OK')"` | Prints `OK` -- `awswrangler` is NOT imported by preflight; ci_rca query uses existing AWS-CLI-subprocess pattern | Refactor the new `_fetch_ci_rca_recs` to use the existing `_run_athena_query` helper |
| 15 | [post-deploy] | Runner can DeleteObject on tmp/ | `aws iam simulate-principal-policy --policy-source-arn $(aws iam get-role --role-name agent-platform-runner --query 'Role.Arn' --output text --profile company-aws-profile) --action-names s3:DeleteObject --resource-arns "arn:aws:s3:::agent-platform-agent-logs/tmp/x.parquet" --profile company-aws-profile --query "EvaluationResults[0].EvalDecision" --output text` | `allowed` | Re-check the Resource ARN in the new IAM statement -- prefix must match `tmp/*` not `/tmp/*` |
| 16 | [post-deploy] | Runner can DeleteTable in trading_formulas_db | `aws iam simulate-principal-policy --policy-source-arn $(aws iam get-role --role-name agent-platform-runner --query 'Role.Arn' --output text --profile company-aws-profile) --action-names glue:DeleteTable --resource-arns "arn:aws:glue:eu-west-2:REDACTED-ACCOUNT-ID:table/trading_formulas_db/telemetry_process_events" --profile company-aws-profile --query "EvaluationResults[0].EvalDecision" --output text` | `allowed` | Check that all three Glue resources (catalog, database, table) are listed in the new Statement |
| 17 | [post-deploy] | Runner can GetBucketLocation on BOTH buckets | `for B in agent-platform-data-lake agent-platform-agent-logs; do aws iam simulate-principal-policy --policy-source-arn $(aws iam get-role --role-name agent-platform-runner --query 'Role.Arn' --output text --profile company-aws-profile) --action-names s3:GetBucketLocation --resource-arns "arn:aws:s3:::$B" --profile company-aws-profile --query "EvaluationResults[0].EvalDecision" --output text; done` | Both invocations return `allowed` | Confirm both bucket ARNs are listed in the `S3BucketLocation` Statement with NO `/*` suffix |
| 18 | [post-deploy] | Full CI passes on feature branch | Push branch; then `gh run watch $(gh run list --branch agent/ci-merge-gate-hardening --workflow=CI --limit 1 --json databaseId --jq '.[0].databaseId')` | Exit 0; Verification Harness V3 section shows no FAIL for `AthenaViewsVerifier`, `SchemaIntegrityVerifier`, `DataQualityVerifier`, or `CausalChainVerifier` (DQ may show genuine row-level failures separate from infrastructure errors) | Inspect `gh run view --log-failed` and address; re-run iteratively |
| 19 | [post-deploy] | End-to-end ci-rca smoke (on separate throwaway branch) | On a separate branch, intentionally inject a failing assertion in `scripts/verifiers/data_quality.py` (e.g., `raise RuntimeError("smoke")`), push, wait for CI to fail, then: `gh run list --workflow=ci-rca.yml --limit 1 --json conclusion --jq '.[0].conclusion'` | `success` | If ci-rca run fails: inspect `gh run view --log-failed`; common causes are missing `CLAUDE_CODE_OAUTH_TOKEN` secret, runner Python venv missing, or `claude -p` invocation syntax wrong |
| 20 | [post-deploy] | Smoke-filed rec reaches Athena | After step 19, run `.venv/Scripts/python.exe -m scripts.sync_ops sync` then `.venv/Scripts/python.exe -c "import json; recs=[json.loads(l) for l in open('logs/.recommendations-log.jsonl')]; assert any(r.get('source')=='ci_rca' for r in recs); print('OK')"` | Prints `OK` | If no ci_rca rec: confirm the agent invocation actually called `file_rec` (check workflow logs); confirm portal had AWS creds (instance profile + DynamoDB read for ID allocation) |
| 21 | [post-deploy] | Smoke-filed rec surfaces in preflight | After step 20, run `.venv/Scripts/python.exe -m scripts.session_preflight 2>&1 | grep -A 5 "CI RCA Recs"` | Section shows at least one entry referencing the synthetic failure | If empty: confirm the new Athena query in `session_preflight.py` runs (no SQL syntax error) and the rec's status is `open` |
| 22 | [post-deploy] | Smoke artefact cleanup | After step 21, delete throwaway branch and close smoke-filed rec via `python -m scripts.ops_data_portal update_rec --id rec-XXX --status closed --resolution "smoke test artefact"` | Throwaway branch removed; rec closed | Manual cleanup if portal call fails |

## Constraints
- No rescue agents or workaround loops (Decision 55) -- the ci-rca agent diagnoses and files a rec; it never proposes or executes an autonomous fix
- Single Portal Invariant (CLAUDE.md) -- ci-rca writes through `file_rec` only; never direct `Edit`/`Write` to `logs/.recommendations-log.jsonl`
- Warehouse-as-source-of-truth invariant (CLAUDE.md) -- no replay-from-cache anywhere in this plan; the new preflight query reads from Athena (`ops_recommendations_current` view), not from local JSONL
- Lambda deployment deferred (Decision 67) -- no Lambda-packaged files in scope; not applicable
- STRATEGIC plans banned (Temporary Operational Constraint) -- treating the 10-file scope as IMPLEMENTATION per explicit architect override; the file-count heuristic is advisory, not a hard limit
- Terraform plan must be presented to human before `terraform apply` (terraform/CLAUDE.md)
- IAM precedence: `terraform apply` precedes any Lambda code deploy -- N/A here (no Lambda changes)
- Agent-First Repository -- the ci-rca agent file is self-contained (one file, machine-parseable); no human-readable companion document
- Precision Context Injection (CLAUDE.md) -- the ci-rca agent calls `get_rec_write_guidance()` before `file_rec()` so the agent has authoritative field semantics in hand when composing the rec

## Context

### Why this work
The CI failure tail surfaced on 2026-05-11 has four distinct error signatures, but only three are root causes:
1. `s3:DeleteObject` denied on `agent-platform-agent-logs/tmp/compact-*` -- runner role IAM gap
2. `glue:DeleteTable` denied on `trading_formulas_db` catalog -- runner role IAM gap
3. `Unable to verify/create output bucket agent-platform-data-lake` -- `s3:GetBucketLocation` not granted on the data lake bucket (Athena uses this to verify the enforced workgroup output)
4. `DataQualityVerifier: 128 errored` -- cascading symptom of (3); 128 matches the locally-defined check count, so all DQ queries are erroring at Athena execution, not failing on data

A fourth distinct bug surfaced in `SchemaIntegrityVerifier`:
- Verifier uses `model_cls.__dataclass_fields__.keys()` for dataclasses. Empirical: this internal dict includes `ClassVar` entries. The public `dataclasses.fields()` filters them correctly. Switching API fixes the `REQUIRED_FIELDS`/`TABLE_NAME` false positives across all 7 telemetry tables.
- Verifier injects 4 column names (`created_timestamp`, `last_updated_timestamp`, `ingested_at`, `trade_date`) into `local_fields`. Empirical: Pydantic `Recommendation.model_fields` already contains the first two; every telemetry dataclass already declares the last two. The other combinations (SCD2 cols on telemetry; `ingested_at`/`trade_date` on `ops_recommendations`) are not actual columns -- they're false positives. Per architect: `trade_date` on `ops_recommendations` is derived in views from `DATE(created_timestamp)`, not stored. Removing the injection block resolves these.

### Why the architectural change (Decision 72)
Decision 60 already establishes the two-tier validation architecture. Decision 55 already establishes the RCA-first principle for executor failures. Decision 71 already establishes the cc-scheduled-agents pattern (headless `claude -p` on the self-hosted runner, OAuth token, scheduled trigger).

What is *missing* is the application of Decision 55's RCA-first principle to the CI merge gate itself. Today, when CI fails, the developer either: (a) manually reads logs and patches, (b) writes a workaround, or (c) the failure is silent until the next time someone looks at the branch. None of these scale, and (b) is the workaround anti-pattern Decision 55 was meant to prevent.

Decision 72 closes this gap by extending the cc-scheduled-agents infrastructure to a `workflow_run`-triggered (not cron-triggered) instance: the ci-rca agent. On every CI failure, it runs headlessly, diagnoses the root cause with evidence from `gh run view --log-failed`, and files a rec with `source="ci_rca"` and `priority="critical"`. The rec is consumed via the normal `/plan` → `/implement` flow.

The elegance of using `source="ci_rca"` rather than a separate `RCA-{slug}.md` artefact type: it reuses the existing rec lifecycle, the existing portal write path, the existing /plan workflow, the existing executor-eligibility semantics. There is no second surface to drift. The hot signal ("what just broke") is discriminable from the cold backlog ("what's queued for executor") purely by the `source` field, surfaced via an additional preflight section.

### Why bundle the hygiene fixes
Today's preflight emitted `log_sync_result.status == "conflict"` because `logs/.complexity-warnings.json` and `logs/.execution-state.json` are tracked but should not be (they violate the lakehouse invariant -- neither outbox nor Athena-derived cache; just transient local execution artefacts). Adding to `.gitignore` eliminates the conflict class for those files. Adding `git pull --rebase origin main` to `/plan` Step 1 is the belt-and-suspenders backstop for any *other* tracked-file divergence (session log, decisions index, etc.) that a runner or another worktree may have pushed since last local sync.

### Empirical evidence captured during planning
```
=== TelemetrySessions ===
has model_fields: False
has __dataclass_fields__: True
__dataclass_fields__ keys: ['REQUIRED_FIELDS', 'TABLE_NAME', 'branch', 'ci_outcome', ...]
dataclasses.fields:        ['branch', 'ci_outcome', ...]   # ClassVar names absent -- this is the correct API

=== Recommendation ===
has model_fields: True
model_fields keys: [..., 'created_timestamp', ..., 'last_updated_timestamp', ...]
```

This confirms the verifier bug is purely in `schema_integrity.py` -- `telemetry_schemas.py` does not need modification.

### Key prior decisions this plan honours
- Decision 50: Iceberg ops data store
- Decision 51: Local-first outbox
- Decision 55: RCA-first autonomous executor (extended to CI gate by Decision 72)
- Decision 56: SCD2 schema simplification
- Decision 60: Two-tier validation architecture (presubmit + edit-loop)
- Decision 61: Scheduled-agent findings via `source` field
- Decision 67: Lambda deployment deferred (not in scope here)
- Decision 68: Self-hosted EC2 runner as canonical CI environment
- Decision 71: cc-scheduled-agents Cron Mechanism (the technical pattern ci-rca reuses)

### Known gotchas
- Athena workgroup uses `enforce_workgroup_configuration = true` (terraform/main.tf:238). This forces queries through the workgroup's output location; `awswrangler` cannot override. The `s3:GetBucketLocation` permission is required because Athena verifies the bucket before query execution.
- `terraform plan` must be presented to human (terraform/CLAUDE.md). Do not `terraform apply` without explicit approval.
- The CI workflow's `name:` field must be read precisely before authoring `ci-rca.yml` -- the `workflow_run.workflows:` filter is exact-match.
- `CLAUDE_CODE_OAUTH_TOKEN` is already configured as a repo secret (per CLAUDE.md runbook section 9). No additional secret provisioning needed.
- Glue `DeleteTable` requires permissions on **three** ARNs: `catalog`, `database/trading_formulas_db`, and `table/trading_formulas_db/*`. Granting only on `catalog` is insufficient.
- The ci-rca workflow must NOT list its own workflow name in the `workflow_run.workflows:` filter -- otherwise a failure in `ci-rca.yml` itself would trigger a recursive invocation. The filter should reference only the main CI workflow.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (currently `agent/ci-merge-gate-hardening`)
- [ ] `docs/PROJECT_CONTEXT.md` read by the implementing agent
- [ ] `docs/DECISIONS.md` Decisions 55, 60, 61, 67, 68, 71 read for context
- [ ] All 10 files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable via the Verification Plan
- [ ] AWS SSO session active for `company-aws-profile` profile (run `aws sso login --profile company-aws-profile` if expired)
- [ ] `gh` CLI authenticated for the repository
- [ ] Terraform CLI on PATH (or use `.venv/Scripts/python.exe -m scripts.validate` to bypass the local Terraform check, since CI handles it)

## Ordered Execution Steps

1. **Fix verifier bug** -- edit `scripts/verifiers/schema_integrity.py`:
   - Add `import dataclasses` at the top of the file (alongside existing imports)
   - Change line 93 from `local_fields = set(model_cls.__dataclass_fields__.keys())` to `local_fields = {f.name for f in dataclasses.fields(model_cls)}`
   - Delete lines 98-102 (the `injected_cols` block and its update call) entirely
   - Run Verification Plan step 3 and step 4. If they fail, do not proceed -- diagnose and fix.

2. **Update `.gitignore`** -- add to the "S3-managed log files" section:
   ```
   logs/.complexity-warnings.json
   logs/.execution-state.json
   ```
   Run Verification Plan step 5.

3. **Update `/plan` command in BOTH files** -- per Decision 58, `.agents/` is canonical and `.claude/` is the Claude Code consumer. Make the identical edit to both:
   - `.agents/workflows/plan.md` (canonical) -- Step 1
   - `.claude/commands/plan.md` (consumer) -- Step 1
   Insert a new bash block after the existing preflight call and before "Read `logs/.preflight-report.json`":
   ```bash
   git pull --rebase origin main
   ```
   Brief explanation: "Self-healing for tracked-file divergence (logs, session state, etc.) pushed by the CI runner or another worktree."
   Run Verification Plan step 6.

4. **Add Decision 72 to `docs/DECISIONS.md`** -- insert at the top (after the file header, before Decision 71):
   - Heading: `## Decision 72: RCA-as-Plan-Source for CI Merge Gate Failures (Decided)`
   - Sections: Status (Decided), Date (2026-05-11), Problem, Decision, Rationale, Related (Decisions 55, 60, 61, 68, 71)
   - Problem: Today, CI failures on feature branches require manual diagnosis. There is no automated surfacing of root cause, and developers may write workarounds rather than fix the underlying issue (Decision 55 anti-pattern). The cc-scheduled-agents pattern (Decision 71) provides the infrastructure to extend RCA-first diagnosis to the CI merge gate.
   - Decision: On CI failure (`workflow_run.conclusion == 'failure'`), a `workflow_run`-triggered GitHub Actions workflow (`.github/workflows/ci-rca.yml`) invokes `claude -p` headlessly on the self-hosted runner. The ci-rca agent diagnoses the root cause from the failed CI logs and files a rec with `source="ci_rca"`. The agent does not propose or execute any autonomous fix. The rec is consumed via the normal `/plan` → `/implement` flow. The new preflight section "CI RCA Recs (open)" surfaces these recs in any subsequent planning session.
   - Rationale: Reuses cc-scheduled-agents infrastructure (Decision 71); reuses ops_recommendations as the single queue (Decision 50); reuses `source` discriminator (Decision 61); honours the no-autonomous-fix invariant (Decision 55); preserves human-in-the-loop architectural judgment.
   - **Consequences** (per Decision 71 pattern): document that `workflow_run` workflows execute in the context of the *default branch* but check out at `head_sha` of the triggering run -- so a PR that modifies `.claude/agents/scheduled/ci-rca.md` and itself fails CI will invoke ci-rca with the PR's potentially-broken agent file. This is the desired behaviour for forward progress (the PR author needs feedback on their own changes), but operators should be aware that a malformed agent definition in a PR can cause that PR's ci-rca run to fail.
   Run Verification Plan step 7.

5. **Update `CLAUDE.md` Merge protocol section** -- edit to add:
   - Explicit statement that remote CI (`validate.py` on the self-hosted runner) is the *authoritative* pre-merge gate
   - Explicit statement that local `--pre` is *advisory* and exists only to shorten the edit loop -- it does not gate merges
   - Explicit instruction: on CI failure, the ci-rca agent will file a rec with `source="ci_rca"`; the next `/plan` will surface it; do not manually patch the failure until the rec is reviewed in /plan
   Run Verification Plan step 8.

6. **Create `.claude/agents/scheduled/ci-rca.md`** -- self-contained agent definition. Structure:
   - Frontmatter (name, description, tools allowlist)
   - System prompt: "You are a CI failure diagnosis agent. Your job is to read failed CI run logs, identify the root cause with evidence, and file a recommendation. You DO NOT propose or execute autonomous fixes."
   - Input contract: invoked with `${{ github.event.workflow_run.id }}` as the failing-run identifier
   - Methodology section: (a) fetch logs via `gh run view <run-id> --log-failed`; (b) identify the first failing step and the precise error signature; (c) classify root cause (IAM gap, schema drift, dependency gap, environment, code regression, etc.); (d) gather supporting evidence from the logs (specific lines, error codes, resource ARNs); (e) call `python -m scripts.ops_data_portal get_rec_write_guidance` to load authoritative field semantics; (f) call `python -m scripts.ops_data_portal file_rec --source ci_rca --priority critical --title <concise problem> --context <root cause + evidence + log references> --acceptance <unambiguous condition for the fix>`
   - Explicit rule: "Do not propose or execute autonomous fix. The architect reviews and acts on the rec via /plan."

7. **Confirm main CI workflow name** -- the planning cross-LLM critique already verified that `.github/workflows/ci.yml` has `name: CI`. Use the literal string `CI` as the `workflow_run.workflows:` filter value. (Re-grep at implement-time to confirm the field has not been renamed: `grep "^name:" .github/workflows/ci.yml`.)

8. **Create `.github/workflows/ci-rca.yml`** -- the workflow file with:
   - Trigger: `on: workflow_run: workflows: ["CI"], types: [completed]`
   - Guard: `if: github.event.workflow_run.conclusion == 'failure'`
   - Job runs on `[self-hosted, linux]`
   - Steps: checkout (with `ref: ${{ github.event.workflow_run.head_sha }}`), set up Python via existing venv, export `CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}`, invoke `claude -p --output-format json --max-turns 30 "Apply the .claude/agents/scheduled/ci-rca.md instructions to failed CI run ${{ github.event.workflow_run.id }}"`, capture the rec ID from the output
   - **PR-comment step MUST be guarded** by `if: ${{ github.event.workflow_run.pull_requests[0].number != '' }}` -- this prevents step failure on push-to-main events (which have no associated PR). Use `gh pr comment ${{ github.event.workflow_run.pull_requests[0].number }} --body "ci-rca filed <rec-id>: <title>"`
   - Loop prevention: the `workflows:` filter must contain ONLY `"CI"` -- never `ci-rca.yml` itself
   Run Verification Plan step 10 and step 14a.

9. **Update `scripts/session_preflight.py`** -- add a new function that queries Athena for open ci_rca recs using the **existing `_run_athena_query` helper pattern** (subprocess + `aws athena start-query-execution`). Do NOT import `awswrangler` -- per Decision 50 it is a Lambda-only dependency, and the preflight script's existing Athena calls use the AWS-CLI-subprocess pattern. Mirror that pattern:
   ```python
   def _fetch_ci_rca_recs() -> list[dict]:
       """Return up to 5 open CI-RCA recs from Athena. Returns [] on any failure."""
       sql = (
           "SELECT id, title, priority, created_timestamp "
           "FROM ops_recommendations_current "
           "WHERE source = 'ci_rca' AND status IN ('open', 'in_progress') "
           "ORDER BY created_timestamp DESC LIMIT 5"
       )
       # Re-use the existing _run_athena_query helper (subprocess + aws CLI).
       # Pattern matches how other Athena queries are issued by this script today.
       try:
           rows = _run_athena_query(sql)   # returns list[dict] or [] on error
           return rows or []
       except Exception as exc:
           logger.warning("preflight: ci_rca query failed: %s", exc)
           return []
   ```
   - Add `ci_rca_recs` field to the JSON report
   - Add print-stdout section under "CI RCA Recs (open)" after the existing Priority Queue table
   Run Verification Plan step 11, step 12, and step 14b.

10. **Update planning skill in BOTH files** -- per Decision 58, `.agents/` is canonical and `.claude/` is the Claude Code consumer. Make the identical edit to both:
    - `.agents/skills/planning/SKILL.md` (canonical)
    - `.claude/skills/planning/SKILL.md` (consumer)
    In each file's Preflight Constraints section, add:
    ```
    - **`ci_rca_recs` non-empty** -- Surface as planning context: "[N] CI RCA rec(s) open -- these block the merge gate; recommend addressing before new feature work." Non-blocking but high priority.
    ```
    Run Verification Plan step 13.

11. **Update `terraform/ec2_runner.tf`** -- modify the `policy = jsonencode({...})` block of `aws_iam_policy.github_runner_ci`. Add three new `Statement` entries (do not modify existing ones):
    - `Sid: "S3DeleteTmp"`, `Effect: "Allow"`, `Action: ["s3:DeleteObject"]`, `Resource: ["${data.aws_s3_bucket.runner_agent_logs.arn}/tmp/*"]`
    - `Sid: "S3BucketLocation"`, `Effect: "Allow"`, `Action: ["s3:GetBucketLocation"]`, `Resource: [data.aws_s3_bucket.runner_data_lake.arn, data.aws_s3_bucket.runner_agent_logs.arn]` -- belt-and-suspenders: both buckets are used as Athena query result destinations (data-lake by the workgroup config, agent-logs by `session_preflight.py:_ATHENA_OUTPUT_LOCATION`); granting on both eliminates the next-likely failure
    - `Sid: "GlueTableMutations"`, `Effect: "Allow"`, `Action: ["glue:DeleteTable", "glue:CreateTable", "glue:UpdateTable"]`, `Resource: ["arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.runner.account_id}:catalog", "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.runner.account_id}:database/trading_formulas_db", "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.runner.account_id}:table/trading_formulas_db/*"]`
    Run Verification Plan step 1 and step 2.

12. **Present `terraform plan` to human** -- run `terraform -chdir=terraform plan -no-color` and surface the full output. WAIT for explicit human approval before `terraform apply`. (terraform/CLAUDE.md hard rule.)

13. **Apply Terraform** (post-approval) -- `terraform -chdir=terraform apply`. Confirm one resource update on `aws_iam_policy.github_runner_ci`; zero destroys. Run Verification Plan steps 15, 16, 17.

14. **Run local validate** -- `.venv/Scripts/python.exe -m scripts.validate`. Run Verification Plan step 14. Address any failures iteratively.

15. **Push branch and watch CI** -- `git push -u origin agent/ci-merge-gate-hardening`, then Verification Plan step 18. Iterate on any CI failures.

16. **End-to-end ci-rca smoke test** -- on a separate throwaway branch, inject a deliberate failure, push, and verify the ci-rca pipeline end to end. Run Verification Plan steps 19, 20, 21.

17. **Smoke cleanup** -- Verification Plan step 22.

18. **Execute Verification Plan** -- re-run all 22 steps in order; loop until all pass. If any V3 step fails unrecoverably, stop and analyze root cause (Decision 55) -- file a rec rather than working around the failure.

19. **Report** -- summarise: what was implemented, verification results, any open follow-ups (likely: the orphaned outbox entry `9afe2393-3465-499b-88cd-68a947a0e6e5.jsonl` with missing `source` field, observed during planning preflight -- this is a candidate follow-up rec, not in this plan's scope).
