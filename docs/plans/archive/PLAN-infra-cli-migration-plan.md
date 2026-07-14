# Plan

## Intent

Establish the strategic roadmap for migrating from VS Code subagent-based workflow to GitHub Copilot CLI-based automation. This directly serves the North Star ("self-improving automated trading system") by reducing token costs, enabling deterministic telemetry capture, and unlocking CI-based autonomous implementation.

## Plan Type

REPORT-ONLY

This plan produces an analysis document and logged recommendations for human review. Each recommendation becomes a separate planning/implementation session. There are no implementation steps in this plan.

## Branch

agent/infra-cli-migration-plan

## Phase

Infra (workflow infrastructure, not tied to trading system phases)

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `logs/.recommendations-log.jsonl` | Modify | Append 29 recommendations from CLI migration analysis |
| `docs/plans/PLAN-infra-cli-migration-plan.md` | Create | This strategic plan document |

## Acceptance Criteria

- [x] All 29 recommendations logged to `logs/.recommendations-log.jsonl` with proper schema
- [x] Dependency graph established showing prerequisite relationships
- [x] Recommendations grouped into implementation phases (A/B/C/D)
- [x] Priority order within each phase documented
- [x] Effort estimates (XS/S/M/L) assigned to each recommendation

## Constraints

- No implementation code in this plan — each recommendation is a separate session
- Recommendations must follow existing JSONL schema
- Plan must be REPORT-ONLY type per planning rules

## Context

- **Source:** Comprehensive workflow analysis session (2026-03-30) reviewing `/plan` → `/implement` loop, subagent architecture, telemetry systems, and GitHub Copilot CLI capabilities
- **Trigger:** User requested migration feasibility study after reviewing CLI documentation
- **Decision 29:** Friction-Free Implementation Pattern applies — each recommendation implementation should follow the "Ordered Execution Steps + Acceptance Criteria" pattern

---

# GitHub Copilot CLI Migration Roadmap

## Executive Summary

The current VS Code-based workflow requires **2N + 3 subagent invocations** per N-step implementation session (N × `@step-validator`, N × `@retro-lite`, 1 × `@scope-guard`, 1 × `@code-review`, 1 × `@retrospective`). For a 10-step plan, that's 23 subagent calls with full context reconstruction overhead per call.

The GitHub Copilot CLI enables:
- **Programmatic subagent invocation** via `copilot -p "..." --agent <name>`
- **Deterministic permission control** via `--allow-tool` / `--deny-tool`
- **Native telemetry** via OpenTelemetry export
- **Session persistence** via `--share` transcripts and `/chronicle` commands
- **CI/CD integration** via non-interactive mode (`-p`, `-s`, `--no-ask-user`)

**Target state:** 2N+3 subagent calls → 2-5 LLM calls per session, with full telemetry capture and CI-based autonomous execution capability.

---

## Recommendations Registry

### Critical Priority (implement first)

| ID | Title | Effort | Dependencies | Phase |
|----|-------|--------|--------------|-------|
| rec-042 | **Status writeback: update rec status in JSONL after execution** | S | rec-009 | E |
| rec-032 | **Acceptance criteria verification: execute step acceptance commands** | S | rec-009 | E |
| rec-035 | **Context injection: inject target file content into CLI prompts** | M | rec-009 | E |
| rec-012 | Eliminate `@retro-lite` subagent calls (parent-direct writes) | S | None | A |
| rec-027 | Test nested subagents (subagent → CLI → subagent) | S | None | A |
| rec-005 | Enable OpenTelemetry export from CLI | S | None | A |
| rec-028 | Security: minimum permissions model | M | rec-027 | B |
| rec-002 | Replace per-step subagent calls with CLI invocations | L | rec-012, rec-027, rec-028 | B |

### High Priority

| ID | Title | Effort | Dependencies | Phase |
|----|-------|--------|--------------|-------|
| rec-034 | **Dependency resolution in eligibility check** | XS | rec-009 | E |
| rec-038 | **Cost budget: per-rec cost ceiling with fail-fast** | XS | rec-009 | E |
| rec-033 | **Batch orchestrator: sequential loop over eligible recs** | M | rec-009, rec-034, rec-042 | E |
| rec-041 | **Auto-merge with CI wait: poll CI and merge on pass** | S | rec-009, rec-030 | E |
| rec-021 | Archive resolved recommendations | XS | None | A |
| rec-006 | `--share` for automatic session transcripts | S | rec-005 | A |
| rec-029 | Full session capture and storage | M | rec-006 | A |
| rec-001 | Script-based session orchestration | M | rec-002, rec-003 | D |
| rec-003 | CLI hooks for branch/permission enforcement | M | rec-028 | B |
| rec-013 | Replace `@step-validator` with deterministic Python | M | rec-002 | B |
| rec-019 | Move cron_review to CLI scripted mode (GitHub Actions) | M | rec-002 | D |

### Medium Priority

| ID | Title | Effort | Dependencies | Phase |
|----|-------|--------|--------------|-------|
| rec-004 | Full orchestrator script | M | rec-001 | D |
| rec-007 | `/chronicle improve` for instructions updates | S | rec-005 | C |
| rec-009 | Build recommendations executor script | M | rec-010 | D |
| rec-010 | Triage field: automatable vs needs-human | XS | None | D |
| rec-011 | CI cron step for auto-fix (GitHub Actions) | M | rec-009, rec-010 | D |
| rec-015 | Drop prompt_compliance.py if using CLI hooks | S | rec-003 | B |
| rec-016 | Consolidate agent files (7→4) | S | rec-012, rec-013, rec-015 | B |
| rec-017 | Use `/fleet` for parallel subagent execution | S | rec-002 | D |
| rec-020 | CI-based implementation (GitHub Actions + CLI) | L | rec-004 | D |
| rec-023 | Split copilot_instructions.md into modular files | M | None | C |
| rec-024 | YAML frontmatter for structured plan parsing | M | None | C |
| rec-025 | Rollback mechanism | S | None | C |
| rec-026 | Cost tracking aggregation | M | rec-005 | C |

### Medium Priority (continued)

| ID | Title | Effort | Dependencies | Phase |
|----|-------|--------|--------------|-------|
| rec-036 | **Execution checkpointing: integrate with execution_state.py** | S | rec-009 | E |
| rec-037 | **Branch cleanup on failure: push partial work as draft PR** | S | rec-009 | E |

### Low Priority

| ID | Title | Effort | Dependencies | Phase |
|----|-------|--------|--------------|-------|
| rec-039 | **Diff capture: store git diff --stat in step telemetry** | XS | rec-009 | E |
| rec-040 | **Prompt template hashing: store prompt version in telemetry** | XS | rec-009 | E |
| rec-008 | Replace friction_analysis.py with `/chronicle tips` | S | rec-005 | C |
| rec-014 | Merge telemetry scripts into single module | S | None | C |
| rec-018 | Use `/delegate` for async cloud work | S | rec-002 | D |
| rec-022 | Plan file cleanup after merge | S | None | C |

---

## Implementation Phases

### Phase A: Foundation (HIGHEST PRIORITY)

**Goal:** Eliminate immediate token waste, establish CLI telemetry, unlock subsequent phases.

**Execution order:**

1. **rec-012: Eliminate `@retro-lite` subagent calls** (S, Critical)
   - Modify `implement.prompt.md` to have parent agent write friction JSON directly
   - Use existing `python scripts/run_retro_lite.py --append` for validation/dedup
   - Removes N subagent calls per session immediately
   - **Estimated token savings:** 30-50% per session

2. **rec-027: Test nested subagents** (S, Critical)
   - Experiment: VS Code agent invokes `copilot -p` via shell tool
   - Experiment: CLI `--agent` flag with custom agents
   - Document context inheritance, permission inheritance, failure modes
   - **Outcome informs:** rec-002, rec-003, all Phase B work

3. **rec-005: Enable OpenTelemetry export** (S, Critical)
   - Set env vars: `COPILOT_OTEL_FILE_EXPORTER_PATH`, `OTEL_SERVICE_NAME`
   - Validate traces appear in JSONL
   - Document OTel schema in `docs/GETTING_STARTED.md`
   - **Unlocks:** rec-006, rec-007, rec-008, rec-026, rec-029

4. **rec-006: `--share` for session transcripts** (S, High)
   - Add `--share="logs/transcripts/session-${SLUG}-$(date +%s).md"` pattern
   - Modify prompts to use this flag
   - **Unlocks:** rec-029

5. **rec-029: Session capture storage** (M, High)
   - Create `logs/transcripts/` directory structure
   - Build index file (`logs/.transcript-index.jsonl`)
   - Define archival policy (e.g., 90 days local, then S3/LFS)
   - **Outcome:** Complete audit trail for all sessions

6. **rec-021: Archive resolved recommendations** (XS, High)
   - Create `docs/RECOMMENDATIONS_ARCHIVE.md`
   - Move all strikethrough rows from `docs/RECOMMENDATIONS.md`
   - Add housekeeping step to `strategic_review.prompt.md`
   - **Outcome:** Reduce context token waste

**Phase A total effort:** 2×S + 2×M + 2×XS ≈ 4-6 implementation sessions

---

### Phase B: CLI Migration

**Goal:** Replace VS Code subagent architecture with CLI programmatic calls.

**Prerequisites:** Phase A complete (especially rec-012, rec-027, rec-005)

**Execution order:**

1. **rec-028: Security - minimum permissions model** (M, Critical)
   - Define permission profiles per workflow type:
     - `/plan`: `read`, `shell(git:*)`, `shell(python scripts/*)` — no `write` until confirmed
     - `/implement`: `read`, `write`, `shell(git:*)`, `shell(python:*)`, `shell(pytest:*)`
     - `/cron_review`: `read`, `shell(python:*)`, `write(logs/*)` — restricted write
   - Decide: baseline deny + explicit allow vs dynamic escalation via hooks
   - Document in `.github/copilot/settings.json` or equivalent
   - **Outcome:** Security model locked before any CLI automation

2. **rec-002: Replace per-step subagent calls with CLI invocations** (L, Critical)
   - Convert `@step-validator` to `copilot -p "Validate step ${N}..." --model gpt-4.1 -s`
   - Convert `@scope-guard` to CLI call (or replace with deterministic Python)
   - Update `implement.prompt.md` to use shell commands instead of `agent` tool
   - **Outcome:** N+1 subagent calls → 1-3 CLI calls

3. **rec-003: CLI hooks for enforcement** (M, High)
   - Create `.github/hooks/enforce-branch.json` (deny writes on main)
   - Create `.github/hooks/enforce-permissions.json` (deny dangerous tools)
   - Test hook execution in both VS Code and CLI contexts
   - **Outcome:** Real-time enforcement replaces after-the-fact compliance checking

4. **rec-013: Deterministic step-validator** (M, High)
   - Create `scripts/step_validator.py` with file-existence and content checks
   - Add LLM fallback for semantic validation (via CLI call)
   - Update `implement.prompt.md` to use hybrid approach
   - **Outcome:** Most validation is deterministic Python, LLM only when needed

5. **rec-015: Drop prompt_compliance.py** (S, Medium)
   - If CLI hooks (rec-003) provide real-time enforcement
   - Remove from `validate.py` scope detection
   - Archive to `scripts/archive/` for reference
   - **Outcome:** Remove redundant after-the-fact checker

6. **rec-016: Consolidate agent files** (S, Medium)
   - Remove `retro-lite.agent.md` (rec-012 makes it unnecessary)
   - Remove `step-validator.agent.md` (rec-013 replaces with Python script)
   - Merge `scope-guard.agent.md` into `session_postflight.py` (already does this check)
   - Keep: `code-review.agent.md`, `retrospective.agent.md`, `plan-critique.agent.md`, `prompt-reviewer.agent.md`
   - **Outcome:** 7 agents → 4 agents

**Phase B total effort:** 1×L + 2×M + 3×S ≈ 6-8 implementation sessions

---

### Phase C: Housekeeping (Parallelizable)

**Goal:** Clean up tech debt, improve tooling quality.

**Prerequisites:** None (can run in parallel with Phase B)

**Items (no strict order):**

| ID | Title | Effort |
|----|-------|--------|
| rec-007 | `/chronicle improve` integration | S |
| rec-008 | Replace friction_analysis.py | S |
| rec-014 | Merge telemetry scripts | S |
| rec-022 | Plan file cleanup | S |
| rec-023 | Modular instructions files | M |
| rec-024 | YAML plan frontmatter | M |
| rec-025 | Rollback mechanism | S |
| rec-026 | Cost tracking aggregation | M |

**Phase C total effort:** 5×S + 3×M ≈ 6-8 implementation sessions (parallelizable)

---

### Phase D: Automation (CI-Based)

**Goal:** Enable fully autonomous implementation and maintenance via GitHub Actions.

**Prerequisites:** Phase B complete (CLI migration)

**Execution order:**

1. **rec-010: Triage field for recommendations** (XS)
   - Add `"automatable": true/false` to JSONL schema
   - Update `migrate_recommendations.py` to support field

2. **rec-009: Recommendations executor script** (M)
   - `scripts/execute_recommendations.py`
   - Parse open recommendations, filter by priority/effort/automatable
   - Invoke `copilot -p "Plan and implement: ${TITLE}"` per item
   - Create feature branches, run validation, stop before push

3. **rec-011: CI cron auto-fix** (M)
   - `.github/workflows/auto-fix.yml`
   - Trigger: schedule (weekly) or workflow_dispatch
   - Run executor script for XS/S items
   - Create PRs for human review

4. **rec-019: cron_review via CI** (M)
   - `.github/workflows/cron-review.yml`
   - Replace local Task Scheduler with GitHub Actions
   - Use `copilot -p` for each file review
   - Commit results to `logs/`

5. **rec-001: Session orchestration script** (M)
   - `scripts/run_session.py`
   - Chain: preflight → implement → postflight
   - Support `--plan-only`, `--implement-only` flags

6. **rec-004: Full orchestrator** (M)
   - `scripts/run_session.sh` (wrapper)
   - Support parallel worktrees
   - Integration with CI dispatch

7. **rec-017: `/fleet` parallel execution** (S)
   - Update prompts to use `/fleet` for independent subagents
   - Example: code-review + retrospective in parallel

8. **rec-018: `/delegate` async work** (S)
   - Document when to use `/delegate` vs local execution
   - Add to `implement.prompt.md` as optional step

9. **rec-020: CI-based implementation** (L)
   - `.github/workflows/auto-implement.yml`
   - Trigger: workflow_dispatch with plan slug input
   - Full implementation loop on cloud runner
   - Stop at PR creation (human approves merge)

**Phase D total effort:** 1×XS + 5×M + 2×S + 1×L ≈ 8-10 implementation sessions

---

### Phase E: Executor Completeness (HIGHEST PRIORITY -- implements before Phase A-D resume)

**Goal:** Make the recommendation executor (rec-009) functionally complete for autonomous end-to-end execution. Without these, the executor is a scaffolding demo, not a working pipeline.

**Prerequisites:** rec-009 (executor exists -- already implemented)

**Execution order (strict -- each builds on the previous):**

1. **rec-042: Status writeback to JSONL** (S, Critical)
   - Without this, nothing else works in a loop. The executor reads recs but never marks them done.
   - Add `update_recommendation_status()` function. On success: status=closed. On failure: status=failed with failure_step and failure_reason.
   - **Briefing:** `docs/plans/briefings/BRIEFING-rec-042.md`
   - **Unlocks:** rec-033 (batch mode), all loop functionality

2. **rec-034: Dependency resolution in eligibility** (XS, High)
   - `is_eligible()` ignores the `dependencies` array. Executor will attempt recs whose prerequisites are not met.
   - Add dependency status check: all deps must have `status == "closed"`.
   - **Briefing:** `docs/plans/briefings/BRIEFING-rec-034.md`
   - **Unlocks:** rec-033 (batch mode needs correct ordering)

3. **rec-035: Context injection for CLI steps** (M, Critical)
   - **The single biggest improvement to execution success rate.** The CLI agent receives only the step description but no file content. In VS Code the agent has automatic workspace access; via CLI subprocess it is blind.
   - implement_step() must read target file(s) and inject content into the prompt before calling copilot.
   - **Briefing:** `docs/plans/briefings/BRIEFING-rec-035.md`

4. **rec-032: Acceptance criteria verification** (S, Critical)
   - **CRITICAL GAP:** implement_step() runs validate.py but never executes the step's own acceptance command. The acceptance field in parsed steps is decorative. Steps pass based on LLM output, not functional verification.
   - Must execute acceptance commands and check exit codes after validate.py passes.
   - **Briefing:** `docs/plans/briefings/BRIEFING-rec-032.md`

5. **rec-038: Cost budget / kill switch** (XS, High)
   - No per-rec or per-batch cost limit. A runaway execution could burn significant budget.
   - Add `--max-cost` flag (default $2.00 per rec). Fail-fast when exceeded.
   - **Briefing:** `docs/plans/briefings/BRIEFING-rec-038.md`

6. **rec-041: Auto-merge with CI wait** (S, High)
   - finalize() creates PR but does not wait for CI or merge. The loop cannot progress without this.
   - Extend finalize() to poll CI, merge on pass, return to main.
   - **Briefing:** `docs/plans/briefings/BRIEFING-rec-041.md`
   - **Dependency note:** rec-030 (auto-merge evaluation) is a parallel/future concern for criteria definition. This rec implements the merge mechanics independently.

7. **rec-033: Batch orchestrator** (M, High)
   - The outer loop: select eligible recs, topologically sort by dependencies, process sequentially.
   - Re-evaluate eligibility after each success (newly-closed rec may unblock others).
   - **Briefing:** `docs/plans/briefings/BRIEFING-rec-033.md`

8. **rec-036: Execution checkpointing** (S, Medium)
   - Process crash mid-execution loses progress. Integrate with existing `execution_state.py`.
   - **Briefing:** `docs/plans/briefings/BRIEFING-rec-036.md`

9. **rec-037: Branch cleanup on failure** (S, Medium)
   - Failed executions leave abandoned branches. Push partial work as draft PR.
   - **Briefing:** `docs/plans/briefings/BRIEFING-rec-037.md`

10. **rec-039: Diff capture in step telemetry** (XS, Low)
    - Store `git diff --stat` after each commit for audit.
    - **Briefing:** `docs/plans/briefings/BRIEFING-rec-039.md`

11. **rec-040: Prompt template hashing** (XS, Low)
    - Store SHA-256 hash of prompt template in plan telemetry for version tracking.
    - **Briefing:** `docs/plans/briefings/BRIEFING-rec-040.md`

**Phase E total effort:** 3×XS + 4×S + 2×M ≈ 7-9 implementation sessions

**Phase E critical path:** rec-042 → rec-034 → rec-035 → rec-032 → rec-038 → rec-041 → rec-033

---

## Effort Summary

| Phase | Items | Estimated Sessions | Cumulative |
|-------|-------|-------------------|------------|
| **E: Executor Completeness** | **11** | **7-9** | **7-9** |
| A: Foundation | 6 | 4-6 | 11-15 |
| B: CLI Migration | 6 | 6-8 | 17-23 |
| C: Housekeeping | 8 | 6-8 | 23-31 |
| D: Automation | 9 | 8-10 | 31-41 |

**Total:** 40 recommendations across 31-41 implementation sessions.

**Critical path:** E1(rec-042) → E2(rec-034) → E3(rec-035) → E4(rec-032) → E6(rec-041) → E7(rec-033) → A1 → A2 → B1 → B2 → D9

**Rationale for Phase E priority:** Phases A-D optimise the interactive VS Code workflow. Phase E makes the autonomous executor functional. The executor is the foundation for all CI-based automation in Phase D. Without Phase E, Phase D has no working executor to deploy.

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| CLI not available in VS Code context | rec-027 tests this explicitly; fallback to shell tool |
| Permission model too restrictive | rec-028 evaluates dynamic escalation hooks |
| OTel overhead affects performance | Start with metadata-only (no content capture) |
| Nested subagents don't work | Fallback to linear orchestrator script |
| CI runners lack Copilot license | Requires PAT with "Copilot Requests" permission |
| Executor runs without functional verification | rec-032 (acceptance verification) closes this gap |
| Executor cost overrun in batch mode | rec-038 (cost budget) with per-rec and per-batch limits |
| Failed recs re-executed infinitely | rec-042 (status writeback) prevents re-processing |

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Subagent calls per 10-step session | 23 | 2-5 |
| Token cost per session | Unmeasured | Tracked via OTel |
| Session audit coverage | Partial (JSONL logs) | 100% (transcripts) |
| Autonomous implementation capability | None | XS/S items via CI |
| Executor end-to-end success rate | Unmeasured | >70% for low-risk recs |
| Recs processed per batch | 0 (no batch mode) | All eligible in dependency order |
| cron_review reliability | Manual trigger | CI scheduled |

---

## Next Steps

1. **Start Phase E implementation** (executor completeness) -- this is now the highest priority
   - First: rec-042 (status writeback) -- without this, nothing loops
   - Second: rec-034 (dependency resolution) -- prevents wasted execution
   - Third: rec-035 (context injection) -- biggest success rate improvement
   - Fourth: rec-032 (acceptance verification) -- moves from "LLM says done" to "verified done"
2. After Phase E critical path (recs 042 → 034 → 035 → 032 → 038 → 041 → 033), resume Phase A
3. Phase A: Start with rec-012 (eliminate `@retro-lite`)
4. Run rec-027 experiment (nested subagents) in parallel with Phase A
5. After Phase A, reassess Phase B order based on rec-027 findings
6. Phase C can proceed independently once team capacity allows

---

## Pre-Implementation Checklist

> The implementing agent must verify all items before editing any file.
- [x] Branch confirmed not on `main`
- [x] copilot_instructions.md read (rules, gotchas, file router)
- [x] DECISIONS.md read (no conflicts with prior decisions)
- [x] All files in Scope table located and readable
- [x] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

> **This is a REPORT-ONLY plan. There are no implementation steps.**
>
> Each recommendation (rec-001 through rec-029) should be implemented in a separate planning session following the dependency order documented above.
>
> Suggested first session: **rec-012 (Eliminate @retro-lite subagent calls)**
