# Plan

## Intent
Stand up the scheduled DuckLake table-maintenance pipeline (T2.18, FP-A slice) so the operational
lakehouse can bound S3 storage growth deterministically -- the unmaintained-storage gap that blocks
the T2.19 ops write/read cutover. This is the FP-A slice only; catalog-DR `pg_dump` and telemetry
small-file co-tuning are deferred to a separate FP-B plan, so T2.18 stays open after this lands.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Plan Path
docs/plans/PLAN-ducklake-maintenance.md

## Phase
Phase 2 (Platform) -- T2 tier, DuckLake operational lakehouse. Tier item T2.18
("DuckLake maintenance pipeline replacing ops_compaction"), depends_on [T2.16, T2.17] (both complete).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| src/common/ducklake_maintenance.py | Create | Maintenance primitives: wrap the DuckLake `CALL` sequence (flush_inlined_data -> merge_adjacent_files -> expire_snapshots -> cleanup_old_files -> delete_orphaned_files, + optional rewrite) with the CD.33 destructive-GC guardrails + circuit breaker. Pure deterministic SQL, no LLM. |
| src/lambdas/ducklake_maintenance/__init__.py | Create | Package marker. |
| src/lambdas/ducklake_maintenance/handler.py | Create | Lambda entrypoint dispatching `action=merge` (daily non-destructive) / `action=gc` (weekly guarded destructive) / `action=breaker_probe` (forced-threshold breaker test). Accepts `force_*` event fields (Lambda convention). Loud-fail maps to 4xx/5xx (no silent drop). |
| src/lambdas/ducklake_maintenance/manifest.yaml | Create | CD.24 per-Lambda manifest (`status: active`), mirroring ducklake_writer: includes ducklake_runtime + ducklake_maintenance + aws_profile; deps/extensions layers external. |
| terraform/personal/ducklake_maintenance.tf | Create | Lambda function (from S3) + write-scoped exec role (S3 Get/Put/**Delete**/List on the smoke prefix, Neon DSN read, CloudWatch PutMetricData, logs) + 2 EventBridge schedule rules/targets/permissions (daily merge, weekly GC) + log group + `reserved_concurrency = 1` (singleton) + circuit-breaker CloudWatch alarm -> existing SNS ops topic. |
| scripts/build_lambda.py | Modify | Extend the `--ducklake-only` build/deploy path to package + deploy the third function (`ducklake-maintenance.zip`); add to `_DUCKLAKE_*` function maps and `only_ducklake` deploy set. |
| scripts/ducklake_neon_smoke_test.py | Modify | Add post-deploy live invoke gates: `--lambda-maintenance-merge`, `--lambda-maintenance-gc`, `--lambda-maintenance-breaker`. |
| tests/test_ducklake_maintenance.py | Create | Unit tests for the maintenance primitives, guardrail computation, and circuit-breaker trip logic (mocked connection -- real code paths, not the live CALLs). |
| tests/test_ducklake_maintenance_handler.py | Create | Unit tests for handler dispatch, `force_*` handling, and loud-fail status mapping. |
| docs/runbooks/ducklake-catalog-operations.md | Modify | Add a maintenance-pipeline section: the two cadences, the guardrail constants, how to read the circuit-breaker alarm, and the manual-invoke runbook. |
| docs/ROADMAP-PLATFORM.yaml | Modify | T2.18 `progress_note` recording the FP-A landing + the FP-B remainder. Do NOT set `status: complete`. |
| docs/SESSION_LOG.md | Modify | Session entry. |

## Bundled Recommendations
None. (Open recs surfaced at preflight are not specific to the maintenance pipeline; none bundled.)

## Infrastructure Dependencies
| Item | Detail |
|------|--------|
| New resources | `aws_lambda_function.ducklake_maintenance`, `aws_iam_role.ducklake_maintenance` + inline policy, `aws_cloudwatch_log_group.ducklake_maintenance`, `aws_cloudwatch_event_rule` x2 (daily merge `cron(0 4 * * ? *)`, weekly GC `cron(0 5 ? * SUN *)`) + targets + `aws_lambda_permission` x2, `aws_lambda_function_url` (AWS_IAM, smoke-invoke ingress), `aws_cloudwatch_metric_alarm` (circuit-breaker page) -> existing SNS ops topic, `reserved_concurrent_executions = 1`. |
| Apply posture | **HUMAN-GATED** via `agent_platform_admin` (Decision 35 + 77). The new IAM role/trust trips the deterministic fail-closed guard (`scripts/terraform_apply_guard.py`), so this routes to the manual admin path, NOT push-to-main auto-apply. |
| IAM precedence | IAM (role + policy) must be applied BEFORE the code deploy: (1) `build_lambda --ducklake-only` uploads the zip to S3, (2) `terraform plan` -> present to human -> apply via `agent_platform_admin`, (3) `build_lambda --ducklake-only --deploy` updates the function code. (terraform CLAUDE.md IAM-precedence.) |
| Lambda deployment (CD.16 / Decision 79) | `ducklake_maintenance` is a NEW `status: active` artifact -> V3 per-Lambda build + deploy + smoke-test required (steps below). Layers reused from T2.17 (`ducklake-deps`, `ducklake-extensions`); no new layer build. |
| Timing | Terraform create + EventBridge rules = `[pre-deploy]` (apply). Live invoke gates = `[post-deploy]`. |

## Acceptance Criteria
- [ ] `src/common/ducklake_maintenance.py` exposes the full sequence `flush_inlined_data -> merge_adjacent_files -> expire_snapshots -> cleanup_old_files -> delete_orphaned_files (+ optional rewrite)` as composable primitives; `flush_inlined_data` is a no-op safety net (inlining `row_limit=0`).
- [ ] Two deterministic singleton cadences exist: a DAILY non-destructive `merge_adjacent_files` and a SEPARATELY-cadenced (weekly) guarded destructive GC. No LLM / agent invocation anywhere in the path (CD.33 clause 5 / Decision 81).
- [ ] Destructive-GC guardrails pinned as tunable constants: expire 30d history / 7d current, floor >= last 2 snapshots, file-deletion `older_than` grace >= 7d, weekly cadence, never `cleanup_all` in scheduled runs (CD.33 H1/R-3/O-3/M-3 / Decision 81 clause 6).
- [ ] Circuit breaker aborts the destructive run and pages (CloudWatch alarm -> SNS) when a single GC pass would delete > 20% of files OR > 10 GB; the abort raises (loud-fail, Decision 55) and deletes nothing on that pass.
- [ ] Singleton enforced: `reserved_concurrent_executions = 1` on the maintenance Lambda; a maintenance-singleton + merge/GC file-delta + commit-latency metric set is emitted to CloudWatch (CD.33 T2-d).
- [ ] GC and merge are table-scoped to `ducklake_smoke_*` for this slice; the handler carries an explicit, code-level forward-pointer (constant/comment + runbook note) that the scope GENERALISES at T2.19 to the full `ducklake_ops` catalog / real `ops_*` tables.
- [ ] "S3 storage confirmed stable": after a write-many-small-files -> merge -> GC cycle on the smoke tables, the tracked S3 object count is demonstrably lower than before GC (live VP).
- [ ] `ops-compaction` is UNCHANGED and still deployed (NON-GOAL: not retired this slice -- Iceberg ops writes are live until T2.19).
- [ ] Cadence mechanism documented as EventBridge-scheduled Lambda, with the CD.29 / Decision 62 rationale (no new GH Actions surface for non-CI work; consistent with the T2.17 Lambda posture; a single deterministic Lambda needs no Step Functions state machine per Decision 39).
- [ ] Per-Lambda V3 build + deploy + smoke-test for `ducklake_maintenance` all pass (Decision 79).
- [ ] T2.18 roadmap item carries a FP-A `progress_note` and remains `status: not_started`/open (NOT marked complete -- FP-B pending).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Unit-test the maintenance primitives + guardrail math + breaker trip on real code paths (mocked connection) | `bin/venv-python -m pytest tests/test_ducklake_maintenance.py tests/test_ducklake_maintenance_handler.py -q` | All pass; breaker test asserts a >20%-files scenario raises and deletes nothing | A guardrail constant is wrong or the breaker does not raise -> fix the primitive/threshold |
| 2 | [pre-deploy] | Validate the new manifest + bundle completeness (handler imports + assets resolve) | `bin/venv-python -m scripts.lambda_manifest --validate && bin/venv-python -m scripts.lambda_manifest --check-bundles` | `ducklake_maintenance` validates and bundles cleanly (no missing includes) | A required include is missing -> add to manifest `includes` |
| 3 | [pre-deploy] | Confirm `compute_affected_artifacts` flags ducklake_maintenance as an affected active artifact | `bin/venv-python -c "from scripts.lambda_manifest import compute_affected_artifacts; print(compute_affected_artifacts(['src/lambdas/ducklake_maintenance/handler.py','src/common/ducklake_maintenance.py']))"` | Output includes `ducklake-maintenance` under active artifacts | Manifest not discovered -> fix manifest path/status |
| 4 | [pre-deploy] | Terraform validate + plan the new resources | `terraform -chdir=terraform/personal validate && terraform -chdir=terraform/personal plan` | Plan adds the function, role, 2 schedules, log group, alarm, reserved-concurrency=1; no destroys; present plan to human | Validate error -> fix HCL; unexpected destroy -> stop (Decision 77 guard) |
| 5 | [pre-deploy] | Full presubmit (lint/format/tests/prompts/schema) | `bin/venv-python -m scripts.validate` | PASS (CI-identical suite) | Any failure -> fix before deploy; CI is the authoritative gate |
| 6 | [pre-deploy] | Build the maintenance zip (manifest-driven) | `bin/venv-python -m scripts.build_lambda --ducklake-only` | `ducklake-maintenance.zip` built + uploaded to S3 alongside writer/reader | Build error -> fix build_lambda `--ducklake-only` extension |
| 7 | [pre-deploy] | HUMAN-GATED apply (IAM before code) | `terraform -chdir=terraform/personal apply` (via `agent_platform_admin`, after human review of step 4 plan) | Resources created; role + policy live | Apply fails on guard -> route through admin path; partial failure -> re-plan |
| 8 | [post-deploy] | Deploy the function code | `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` | `agent-platform-ducklake-maintenance` code updated from S3 | Deploy error -> check function name map in build_lambda |
| 9 | [post-deploy] | Live MERGE gate: write many small files to smoke tables, then invoke merge; assert tracked file count drops | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-maintenance-merge` | `files_before > files_after`; `ok=true`; commit-latency metric emitted | merge CALL signature wrong for pinned DuckDB 1.5.3 -> correct the CALL; verify against the live engine |
| 10 | [post-deploy] | Live GC gate: invoke weekly GC (expire/cleanup/delete-orphaned); assert tracked S3 objects stable/lower and breaker NOT tripped on a normal pass | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-maintenance-gc` | `s3_objects_after <= s3_objects_before`; `breaker_tripped=false`; `cleanup_all` never invoked | Storage grows -> delete_orphaned/cleanup not wired; breaker false-positive -> re-tune threshold constant (FP-A default) |
| 11 | [post-deploy] | Live breaker gate: forced-threshold invoke trips the circuit breaker | `bin/venv-python -m scripts.ducklake_neon_smoke_test --lambda-maintenance-breaker` | Returns loud-fail (5xx / breaker error); deletes nothing; CloudWatch alarm metric emitted | Breaker does not trip / deletes anyway -> fix the pre-deletion guard before destructive CALLs |
| 12 | [post-deploy] | Confirm singleton + cadence wiring | `aws lambda get-function-concurrency --function-name agent-platform-ducklake-maintenance --profile agent_platform && aws events list-rules --name-prefix agent-platform-ducklake-maintenance --profile agent_platform` | `ReservedConcurrentExecutions=1`; two ENABLED schedule rules (daily merge, weekly GC) | concurrency unset / rule disabled -> fix terraform |
| 13 | [post-deploy] | Confirm ops-compaction untouched (non-goal regression check) | `aws lambda get-function --function-name agent-platform-ops-compaction --profile agent_platform --query 'Configuration.LastModified'` | LastModified unchanged from before this work (still deployed, still Iceberg) | If modified -> revert; ops-compaction must stay live until T2.19 |

## Constraints
- No rescue agents or workaround loops (Decision 55). If a live VP step fails unrecoverably, STOP and root-cause -- do not relax a guardrail constant to make a gate pass.
- Guardrail + budget constants are CD.33 / Decision 81 invariants. They are tunable knobs, but tuning to make a gate pass is a Decision-55 silent-degrade and is forbidden. Record real numbers.
- DuckDB pinned 1.5.3 / DuckLake v1.0 lockstep (OQ.12). The maintenance `CALL` signatures MUST be verified against the live pinned engine at VP time -- do not assume signatures from memory.
- Terraform apply is human-gated (Decision 35 + 77). The fail-closed guard must remain fail-closed; do not bypass.
- Only modify files in the Scope table. Out-of-scope bugs become recommendations via `scripts/ops_data_portal.py`.
- No emojis; ASCII hyphens only; ruff line length 127; type hints; `bin/venv-python` for all Python.

## Context
- **Last commit** `50b82d8` completed T2.17 (DuckLake Lambda runtime; EC8 churn-gate frame correction, Decision 82). T2.16 / T2.16b / T2.17 are all complete -- T2.18's deps are satisfied.
- **Decisions this plan cites** (from the decision-scout gate, NO_FLAGS verdict):
  - **Decision 81** -- ratifies CD.33, the governing authority: three-artifact split (writer/reader/**maintenance**), maintenance-as-singleton (clause 6), the exact GC guardrails (clause 6), inlining-disabled (resolves OQ.11) which is why `flush_inlined_data` is a no-op safety net.
  - **Decision 79** -- CD.16 + CD.24 per-Lambda manifest (SSOT) + per-Lambda V3 build/deploy/smoke gating for the new active artifact.
  - **Decision 78** -- CD.31 DuckLake adoption; physical `ops_*` migration deferred to T2.19 (basis for the smoke-tables-only scope and the ops-compaction non-goal).
  - **Decision 77** -- two-axis taxonomy + sandbox auto-apply; the new IAM/trust trips the fail-closed guard -> human-gated apply.
  - **Decision 48** -- V3 tier classification (Terraform + active Lambda handler -> behavioural acceptance).
  - **Decision 67** -- STRATEGIC suspended; this is correctly an IMPLEMENTATION plan.
  - **Decision 39 / Decision 62** -- support the EventBridge-scheduled-Lambda cadence over Step Functions / a new GH Actions surface.
- **Decision flags (NOTE, documented -- no pivot):** Decision 81 clause 3 / Decision 82 reject `reserved-concurrency=1`, but that rejection is scoped to the **writer's** OCC concurrency model. The maintenance pipeline is *intentionally* a singleton per Decision 81 clause 6, so `reserved_concurrent_executions = 1` is correct here. This is documented in `ducklake_maintenance.tf` and the runbook to pre-empt the keyword-collision reviewer flag.
- **Scope decision (human-confirmed):** GC + merge are table-scoped to `ducklake_smoke_*` and operate on the smoke DATA_PATH for this slice. The human approved the small scope ON THE CONDITION that the expansion at T2.19 is made EXPLICIT: a code-level forward-pointer (a named constant / comment in the handler and primitives) plus a runbook note must state that the scope generalises to the full `ducklake_ops` catalog and the real `ops_*` business tables at T2.19. This is a hard acceptance criterion, not a nicety.
- **FP-B (OUT of scope, separate later plan):** catalog DR (daily `pg_dump` of the Neon catalog -> versioned lifecycle S3 bucket, `cron(0 3 * * ? *)`, 30d retention, >25h freshness alarm -- CD.34 O-2) and telemetry small-file load co-tuning (higher-frequency merge for high-write-rate tables + circuit-breaker co-tune for the raised dead-file rate -- CD.34). Because these T2.18 exit criteria are NOT met by FP-A, T2.18 stays open after this plan.
- **Known gotcha:** `expire_snapshots` does NOT delete S3 objects -- `cleanup_old_files` + `delete_orphaned_files` MUST also run or storage grows unboundedly. This is the core reason the destructive GC cadence exists and why VP step 10 asserts on actual S3 object counts, not just snapshot expiry.
- Preflight: branch clean, `main` 0/0; creds OK (S3-reader ACCESS_DENIED warnings are the known Iceberg-metadata read fallback to Athena); telemetry WARN is the known `sessions-query TABLE_NOT_FOUND`; non-automatable rec soft-cap breached (303, informational under Decision 73). No open ci-rca recs.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (on `claude/platform-roadmap-plan-Z5kYz` or the implement session's harness branch)
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read (esp. 81, 79, 78, 77, 48, 67, 39, 62)
- [ ] All files in Scope table located and readable (T2.17 writer/reader + ducklake_lambdas.tf are the templates to mirror)
- [ ] Acceptance Criteria understood and verifiable
- [ ] Maintenance `CALL` signatures confirmed against the live pinned DuckDB 1.5.3 (not from memory)

## Ordered Execution Steps
1. **`src/common/ducklake_maintenance.py`** -- author the maintenance primitives mirroring `ducklake_runtime` style (single connection authority reused via `rt.open_connection`). Implement `flush_inlined_data` (no-op safety net), `merge_adjacent_files`, `expire_snapshots`, `cleanup_old_files`, `delete_orphaned_files`, optional `rewrite`; a `run_merge(con, tables)` (daily non-destructive) and a `run_gc(con, tables)` (weekly guarded destructive) orchestrator. Encode the guardrail constants (expire 30d/7d, floor >= 2 snapshots, grace >= 7d, breaker thresholds 20% files / 10 GB) as named module constants. The breaker computes the would-delete file count / bytes BEFORE issuing any destructive CALL and raises a loud-fail `DuckLakeMaintenanceError` if a threshold is exceeded. Never issue `cleanup_all`. Add a `GC_TABLE_SCOPE`/`MAINTENANCE_SCOPE_NOTE` constant carrying the explicit T2.19-expansion forward-pointer.
2. **`src/lambdas/ducklake_maintenance/{__init__.py,handler.py}`** -- handler dispatching `action` in {`merge`,`gc`,`breaker_probe`}, opening one connection via the runtime, accepting `force_*` event fields, emitting CloudWatch metrics, mapping loud-fail to 4xx/5xx (mirror `ducklake_writer/handler.py`). Table scope = `ducklake_smoke_*` with the forward-pointer comment.
3. **`src/lambdas/ducklake_maintenance/manifest.yaml`** -- `status: active`, `artifact: ducklake-maintenance.zip`, functions `[agent-platform-ducklake-maintenance]`, includes mirroring ducklake_writer plus `src/common/ducklake_maintenance.py`.
4. **`terraform/personal/ducklake_maintenance.tf`** -- function (from S3, layers reused), write-scoped exec role + inline policy (S3 Get/Put/Delete/List on smoke prefix, DSN read, PutMetricData scoped to a `DuckLakeMaintenance` namespace, logs), log group, 2 EventBridge rules + targets + lambda permissions, `reserved_concurrent_executions = 1`, Function URL (AWS_IAM), circuit-breaker metric alarm -> existing SNS ops topic, outputs for the smoke gates. Carry the reserved-concurrency NOTE comment.
5. **`scripts/build_lambda.py`** -- extend `--ducklake-only` to build `ducklake-maintenance.zip` and add the function to the `only_ducklake` deploy set + S3-key map.
6. **`scripts/ducklake_neon_smoke_test.py`** -- add `--lambda-maintenance-merge`, `--lambda-maintenance-gc`, `--lambda-maintenance-breaker` invoke gates (SigV4-sign the Function URL, assert on file/object deltas + breaker behaviour).
7. **`tests/test_ducklake_maintenance.py`** + **`tests/test_ducklake_maintenance_handler.py`** -- unit-test primitives, guardrail math, breaker trip, handler dispatch + loud-fail mapping (mocked connection; real code paths).
8. **`docs/runbooks/ducklake-catalog-operations.md`** -- add the maintenance-pipeline section (cadences, guardrail constants, breaker-alarm reading, manual-invoke runbook, reserved-concurrency NOTE, T2.19-expansion forward-pointer).
9. **`docs/ROADMAP-PLATFORM.yaml`** -- add a T2.18 `progress_note` (FP-A landed; FP-B remainder = catalog DR + telemetry co-tuning); leave status open.
10. **`docs/SESSION_LOG.md`** -- session entry.
11. **Execute Verification Plan** -- run each step in order. Loop until pass. The apply (step 7) is human-gated; the live invoke gates (9-13) run post-deploy. If a V3 step fails unrecoverably, STOP and root-cause (Decision 55) -- do not relax a guardrail to pass.
12. Report: what was implemented, the live VP results (real file/object-count deltas + breaker behaviour), and confirmation that ops-compaction is untouched and T2.18 remains open pending FP-B.
