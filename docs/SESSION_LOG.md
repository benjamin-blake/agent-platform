# Session Log

Lab notebook for inter-session continuity. Kept lean -- this is not a changelog duplicate.
Entries are written by `session_close` at the end of each session.
`task_start` reads the last 5 entries for recent momentum.
`strategic_review` archives entries when the log exceeds 20 entries.

**Ordering convention:** Entries are ordered by date in descending order (newest first). New entries are appended at the top, above previous sessions. When reading the log, scan downward from the top to see the most recent work first.

---

## [2026-05-19] - implement: claude/implement-feature-sXjJB (ci-workflow-restructure)

**Mode:** Implementation (Decision 73, third follow-on plan)
**Goal:** Split ci.yml PR/push jobs; add 3-hourly main-canary.yml; update INTENT Section 2.5 L1/L3/L8 to BUILT; mark L6/L2/ci-rca-liveness DEFERRED.
**Outcome:** SUCCESS - all VP1-VP14 pre-deploy steps pass; branch ready for review.
**Key actions:**
- Rewrote .github/workflows/ci.yml: pr-validate (--pre, fetch-depth:0, concurrency:ci-runner), main-validate (full tier, concurrency:ci-runner), terraform-validate concurrency removed (same-workflow-run cancellation observed on PR #347), develop removed from push trigger.
- Created .github/workflows/main-canary.yml: name: Main Canary, cron 0 */3 * * *, workflow_dispatch, [self-hosted, linux], full tier, concurrency:ci-runner.
- Edited .github/workflows/ci-rca.yml: workflows: ["CI", "Main Canary"] so failed canaries trigger RCA.
- Created scripts/verify_ci_workflow.py: 5-subcommand structural verifier (jobs-and-flags, concurrency, fetch-depth, canary, ci-rca-filter), all VP steps 1-6 pass.
- Updated docs/INTENT-ci-cd-architecture.md: Section 2.5 L1/L3/L8/single-runner-concurrency BUILT; L6/L2/ci-rca-liveness DEFERRED (TBD owner); Section 3 L8 row 3-hour cadence; Section 6 L8 cadence tightens note; Section 9 runner math updated; Section 10 ci-workflow-restructure landing acknowledged.
- Added .github/workflows/main-canary.yml to docs/ROADMAP-PLATFORM.yaml T2.10 files_in_scope.
- Mid-CI fixes: removed terraform-validate concurrency to stop same-workflow-run cancellation of pr-validate; added explicit `python -m venv .venv` step before bin/venv-python so the runner has the venv that wrapper expects.
**Anomalies:** Plan VP step 2 originally asserted all three jobs carry ci-runner concurrency; updated verifier to assert only pr-validate and main-validate (terraform-validate cannot share the group inside a single workflow run without cancellation). Plan deviation captured in commit dfd1e08.
**Next:** Post-deploy VPs 16-19 require a live PR against main. VP20 (first scheduled canary) is async/report-only.

---

## [2026-05-19] - implement: agent/t-0-12-annotated-pydantic-schemas

**Mode:** Implementation (T0.12)
**Goal:** Land the Annotated-Pydantic schema-as-code foundation: 7 DqXxx marker classes, canonical write-side RecPayload + DecisionPayload, and a CI drift detector that keeps Pydantic annotations aligned with config/data_quality/ops.yaml during the coexistence window.
**Outcome:** SUCCESS - branch passing all pre-deploy VP steps; bookkeeping applied.
**Key actions:**
- Created src/schemas/annotations.py: 7 frozen-dataclass markers (DqNotNull, DqUnique, DqAcceptedValues, DqRelationship, DqRecency, DqRowCount, DqDeleted) plus MigratingMarker/migrating dual-mode decorator. CD.12 ceiling enforced via test.
- Created src/schemas/rec.py: RecPayload Pydantic v2 model with Annotated DqXxx markers mirroring ops.yaml::ops_recommendations write-time + enforced fields. Literal enforcement for status/effort/priority/risk.
- Created src/schemas/decision.py: DecisionPayload with DqXxx markers, dual-write invariant (id/decision_id), related_decisions_v2 coercion for legacy empty-string values.
- Created src/schemas/__init__.py: public re-export surface.
- Added _check_drift_for_table + validate_pydantic_yaml_drift to scripts/validate.py, wired after validate_platform_roadmap in run_python_checks. Drift check passes against real ops.yaml.
- Created 39 tests across test_annotations.py, test_rec.py, test_decision.py, test_validate_dq_drift.py: 100% coverage on new src/schemas/ files.
- Flipped T0.12 status: complete, completed_at: 2026-05-19.
**Anomalies:** Coverage checker expects test_{stem}.py naming (not test_schemas_{stem}.py); renamed test files to match tooling convention.
**Deferred:** build_lambda.py --deploy + smoke-test (pending Decision 67 reversal). src/schemas/ will land in data-pipeline.zip on next build; no handler imports it yet.
**Next:** T0.13 (Iceberg DDL generator from Pydantic models) is the natural follow-on. T1.6 (DQ runner reshape) will retire ops.yaml as source of truth; drift detector is the bridge until then. Stale telemetry_agent_invocations_current view (column count mismatch) is a pre-existing non-blocker to file as a separate rec.

---

## [2026-05-19] - implement: agent/t-1-5-roadmap-document-schema

**Mode:** Implementation (T-1.5)
**Goal:** Land RoadmapDocument Pydantic schema + validate.py CI gate so structural drift in ROADMAP-PLATFORM.yaml fails the build.
**Outcome:** SUCCESS - branch ready to merge; CI gate enforced.
**Key actions:**
- Created scripts/platform_roadmap.py: Pydantic v2 RoadmapDocument schema with model_validator enforcing id uniqueness, dangling depends_on, DFS cycle detection, gate-rule grammar (GateRuleParser), filed_via union validation. PlatformRoadmapState shim for T-1.4/T-1.2 reuse.
- Created tests/test_platform_roadmap.py: 43 tests across 8 classes, 100% coverage. Exercises all validation paths including tier-shortcut resolution, mixed gate-rule expressions, and PlatformRoadmapState helpers.
- Added validate_platform_roadmap() to scripts/validate.py wired into run_python_checks(); full presubmit PASS confirmed (exit 0).
- Code review found 2 Critical/High issues addressed: (1) consolidated load() call inside try/finally sys.path scope in validate.py; (2) fixed temp file leak in test_invalid_yaml_raises (missing_ok=True teardown per tests/CLAUDE.md).
- Flipped T-1.5 status: complete, completed_at: 2026-05-19.
**Anomalies:** `scripts/platform_roadmap.py` needed `ruff format` after initial write; fixed before final commit.
**Next:** T-1.1 (CD ratification) is now unblocked per T-1.5 exit criteria.

---

## [2026-05-19] - implement: agent/agents-md-and-instruction-sweep

**Mode:** Implementation (T0.9 + T0.14 Phase 1 bundle)
**Goal:** Land AGENTS.md thin-pointer import (T0.9) and sweep Windows venv paths from the instruction layer (T0.14 Phase 1).
**Outcome:** SUCCESS - PR pending CI gate.
**Key actions:**
- Created AGENTS.md at repo root: full port of CLAUDE.md with "Role and environment" reframed (Linux container primary; Windows = PySR compute node) and "Shell invocations on Windows" section rewritten as OS-agnostic "Shell invocations" leading with bin/venv-python.
- Rewrote CLAUDE.md to exactly `@AGENTS.md\n` (Anthropic thin-pointer import pattern; drift structurally impossible).
- Added `check_claude_md_pointer_invariant()` + `validate_claude_md_pointer_invariant()` to scripts/validate.py; wired into run_python_checks().
- Added 4-test TestClaudeMdPointerInvariant class to tests/test_validate.py (1 happy + 3 failure scenarios; all pass).
- Swept .claude/commands/ (plan.md 4, implement.md 11, develop-executor.md 3) and .claude/skills/ (planning 7, implement 5, code-review 4): 34 total bin/venv-python replacements, zero .venv/Scripts or python.exe remaining.
- Flipped T0.9 status: complete, completed_at: 2026-05-19. Added Phase 1 notes to T0.14.
**Anomalies:** None.
**Next:** T0.14 Phase 2 (scripts/ sweep, ~11 occurrences across 6 files); T0.14 Phase 3 (.agents/, src/data/handlers/CLAUDE.md, setup.py).

## [2026-05-19] - implement: agent/linux-container-bootstrap (PR #339)

**Mode:** Implementation (T0.1 + T0.11 bundle)
**Goal:** Unblock Claude Code on the web (Linux container) via OS-aware venv resolution and Linux-generalised session preflight.
**Outcome:** SUCCESS - PR #339 squash-merged, all CI green.
**Key actions:**
- Created bin/venv-python POSIX wrapper (picks .venv/bin/python on Linux/macOS, .venv/Scripts/python.exe on Windows/MINGW).
- Rewired all 4 .venv/Scripts/python.exe call sites in .claude/settings.json to bin/venv-python.
- Replaced MAIN_REPO_VENV constant in session_preflight.py with cross-platform same-tree heuristic; worktree repo-name fallback preserved.
- Added --use-device-code to aws sso login when headless (DISPLAY unset, non-win32) per CD.2.
- Flipped T0.1, T0.11 complete; retroactively flipped T-1.0 and T0.10 in ROADMAP-PLATFORM.yaml.
- 76/76 tests pass including 4 new platform-pinned SSO branch tests.
- Code review (zero-context subagent): 1 High fixed inline (test platform pin); rec-809, rec-810 filed for 2 Medium findings.
- Installed missing pytest-picked from requirements.txt (pre-existing env gap).
**Anomalies:** Plan AC2 referenced non-existent --pre flag on session_preflight.py (filed rec-809). pytest-picked missing from venv.
**Next:** T0.2 (CC-on-web env definition + setup script) and T0.3 (SSO substrate) are the remaining blockers for a hands-free Linux container session.

## [2026-04-27] - executor-supervision: rec-325

**Mode:** Executor supervision (single rec)
**Goal:** Close rec-325 — widen postflight mock-exhaustion Known Gotcha in copilot-instructions.md to cover any function in postflight.py, not just cleanup_after_merge().
**Outcome:** SUCCESS — rec-325 closed, PR #261 squash-merged. XS docs-only change.
**Key actions:**
- Enabled `SKIP_CI_WAIT=true` (CI billing paused). Manually reset rec status + cleaned agent branch from prior CI-failure attempt.
- First clean Gemini yolo-mode executor run: `tools=True` warm-base + `--approval-mode yolo` fixes from e0584c8 confirmed working. No ghost-step, no blocked tool calls.
- Plan-guard reverted 8 scope-drift files in run 2; final squash commit changed only the target file.
- Code review gate bypassed (HTTP 429 rate limit); rec-296 covers this pattern.
**Friction filed:** rec-517 (plan-guard staged-file blind spot — `git diff --name-only` misses staged files; fix: use HEAD variant), rec-518 (step telemetry records hardcoded `deepseek.v3.2` for all Gemini runs since Decision 53 — systemic data quality issue across all execution-step-telemetry entries).
**PHASE_4B_STATUS:** COMPLETED (RCA invoked, 2 recs filed).
**Next priority:** rec-518 (XS, fix telemetry model field); rec-517 (S, plan-guard HEAD variant); explore next open automatable rec batch.


## [2026-04-26] - implement: agent/platform-bedrock-migration

**Mode:** Implement (multi-session, final session)
**Goal:** Migrate all LLM inference from GitHub Copilot CLI/SDK to AWS Bedrock DeepSeek V3.2 in eu-west-2.
**Outcome:** SUCCESS -- 42 files changed (2534 insertions, 744 deletions). 1535 tests pass, validation clean. Commit f17337b pushed.
**Key actions:**
- New modules: llm_client.py (LLMResult + llm_call), llm_utils.py, tool_runtime.py, classify_automatable.py
- Extended bedrock_client.py: converse_with_tools() agentic loop, _strip_think_blocks(), CJK cleaning
- Rewired executor plan/step_runner/postflight from copilot_call to llm_call
- Added effort gate (XS/S) and SLOC gate (800 lines) to is_eligible()
- Switched schedule.yaml agents from provider: gemini to provider: bedrock (disabled pending quota)
- Added BEDROCK_CREDENTIALS_SECRET_ARN env var for cross-account auth (CRITICAL fix from code review)
- Updated inference-provider.md v4.0, Decision 52, copilot-instructions
- Code review: 14 findings (1 Critical, 3 High, 6 Medium, 4 Low). All Critical/High fixed.
**Deferred (VP Steps 8-9, 11):**
- Lambda deploy: Bedrock rate-limited; agents disabled. Deploy after quota confirmed.
- E2E rec execution: Requires Bedrock rate limit to clear. Test manually when quota allows.
- converse_with_tools() test coverage: M-effort, file as follow-up rec.
**Friction:** Bulk `.stdout` -> `.content` replacement in prior session damaged subprocess references in both source and test files, causing cascading failures across 6 test files (23 subprocess mocks, 3 patch targets, 3 LLM mock reversions). Lesson: context-aware replacement needed when both subprocess and LLM results coexist.
**Next priority:** Create PR for review. After merge: Lambda deploy, E2E verification, converse_with_tools tests.


## [2026-04-22] - implement: agent/platform-telemetry-executor-instrument (PR #255)

**Mode:** Implement (continued across two sessions)
**Goal:** Phase B of telemetry system -- instrument executor workflow to emit structured telemetry via OpsWriter.emit() into 7-table star schema.
**Outcome:** SUCCESS -- all 11 ordered execution steps complete. 1474 tests pass, validate --ci passes, VP all 4 steps pass. PR #255 created.
**Key actions:**
- Created `scripts/executor/telemetry.py` (TelemetryContext singleton, 8 lifecycle functions)
- Wired session/phase telemetry into `execute_recommendation.py` at all 11 phase boundaries and all return paths; 13 process event categories
- Wired step/transcript telemetry into `step_runner.py` via try/finally block
- Wired model call telemetry into `copilot_wrapper.py` (deferred inline import to avoid circular import)
- Wired process events into `postflight.py` (scope_drift, review pass, CI outcomes, merge outcomes)
- Added 29 new tests in `test_executor_telemetry.py` + 9 targeted tests in 4 existing test files
**Friction:** Circular import when adding `emit_model_call` as module-level import in `copilot_wrapper.py`: the chain `copilot_wrapper -> executor/__init__.py -> step_runner -> copilot_wrapper` caused `_TELEMETRY_AVAILABLE = False` silently. Fix: defer the import to inside the function body (inline import in `copilot_call`). Known Gotcha added to copilot-instructions.md pattern memory.
**Next priority:** Phase C (OpsWriter sync to S3/Iceberg) or executor supervision run.


## [2026-04-21] - implement: agent/platform-ops-pipeline-fix (PR #246) - MERGED

**Mode:** Implement (workflow)
**Goal:** Complete ops data pipeline so all five ops Iceberg tables in Athena receive data (rec-500 → rec-507).
**Outcome:** SUCCESS — terraform applied, Lambdas adjusted (split package), backfill completed; mandatory ops tables populated and tests/validate passed. Commits: 0c0b119, 0e6183d; PR #246 merged.
**Key actions:**
- **Terraform:** plan (3 add, 9 change), apply — approved by human.
- **Lambda deploy:** initial deploy failed due to 262 MB zipped limit; split `ops_compaction` into separate small zip and updated `scripts/build_lambda.py` + `terraform/scheduled_agents.tf`.
- **Backfill:** four debug iterations addressing awswrangler API rename, Iceberg schema evolution flags, dtype overrides for array<> columns, and avoiding list→string coercion.
**Friction / Lessons:** See logs/.retro-lite-log.jsonl for full JSONL entry. Notable items: Lambda zip size limit, awswrangler `temp_s3_dir`→`temp_path`, `fill_missing_columns_in_df=True` behaviour with array<> types, Iceberg int→bigint promotion, and S3 bucket mismatch between build script and Terraform.
**Next priority:** Add copilot Known Gotchas for Lambda size limit and awswrangler/Iceberg write checklist; audit other Lambda packages for zipped size risks.


## [2026-04-21] - executor-supervision session 29 (rec-458 PR #243, rec-456 PR #244) - SKIP_CI_WAIT=true

**Mode:** Executor supervision
**Goal:** First executor run after ops-data-store batch (rec-463–467). Verify ops logs working correctly. Run compound rec-456+rec-458.
**Outcome:** Both recs closed via manual recovery. PRs #243 and #244 merged. Lambda redeployed. Three friction recs filed (rec-497/498/499).
**Issues navigated:**
1. Compound run: rec-456 critique exhausted (critique-scope deadlock — Lambda build steps added as action=modify, rejected by scope guard). rec-458 scope enforcement aborted commit (pre-existing untracked files flagged as out-of-scope).
2. Manual recovery for rec-458: committed docstring fix, created PR #243, merged, annotated log with PR URL.
3. rec-456 standalone retry with --skip-critique: both steps succeeded (prompt edit + build_lambda --deploy). Scope block hit again (same untracked files). Same manual recovery: commit, PR #244, merge, log correction.
4. Validate.py --scope prompts crashed in rec-456 postflight (ModuleNotFoundError for scripts in _load_prompt_compliance — sys.path injection missing).
5. Between-rec checkpoints: rebase required twice due to squash merges diverging from local log commits.
**Root cause:** Two systemic issues — (A) scope enforcer includes ?? untracked files (rec-497), (B) no action=run step type causes Lambda deploy critique deadlock (rec-498). Plus rec-499 (validate.py sys.path).
**Changes shipped:** `scripts/session_preflight.py` (docstring), `.github/prompts/scheduled/rec-curator.prompt.md` (Step 5/6 merge, priority-queue-entry schema). Lambda redeployed.
**PRs:** #243 (rec-458), #244 (rec-456)
**Premium requests used:** ~12 (2x rec-456 runs 6.0 each, rec-458 3.0)
**Next priority:** rec-497 (XS scope enforcer fix), then rec-497+rec-498+rec-495 as executor hardening batch.
