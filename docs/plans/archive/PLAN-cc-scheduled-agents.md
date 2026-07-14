# Plan

## Intent
Establish the architecture and phase decomposition for migrating from disabled Lambda-based scheduled agents to Claude Code scheduled agents (cron-driven, log-only, auto-merge-via-PR), starting with rec-curator. Advances the North Star by retiring brittle automation infrastructure (Lambda dispatcher + findings-processor + GitHub Models dedup) in favour of a single ingestion path through OpsWriter -> Iceberg -> Athena views.

## Plan Type
REPORT-ONLY

## Verification Tier
V1

## Branch
agent/cc-scheduled-agents

## Phase
Platform (parallel with Phase 2 schema backfill)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/plans/PLAN-cc-scheduled-agents.md | Create | Architectural reference and 5-phase implementation manifest. Each phase becomes its own /plan cycle. |

## Bundled Recommendations
- **rec-589** (Monitor or optimize Athena polling bottleneck in Lambda dispatcher) -- to be marked SUPERSEDED by this migration. Status change executed via `python -m scripts.ops_data_portal --close rec-589 --resolution "superseded by cc-scheduled-agents migration"` during Phase 1 planning.
- **rec-595** (Document `_delete_postmortems_from_iceberg` 120s blocking poll) -- NOT bundled. Lives in ops_data_portal, independent of this migration. Stays open.

## Acceptance Criteria
- [ ] Report contains an Architecture & Design Rationale section covering: (a) auto-merge-via-PR scoping, (b) hook+settings defense-in-depth permission model, (c) per-run timestamped findings file pattern, (d) findings-processor retirement rationale, (e) SCD2-via-Athena-view as source-of-truth principle.
- [ ] Report contains a Decisions Register listing the discrete decisions made during the planning session.
- [ ] Report contains a Phase Manifest with 5 phases, each with: goal, scope sketch, dependencies, verification tier estimate, risks.
- [ ] Report contains an Open Questions section listing items deferred to phase planning.
- [ ] Report contains a Risks & Rollback Strategy section.
- [ ] Report contains an Out of Scope (Today) section.
- [ ] Report committed to branch `agent/cc-scheduled-agents`.
- [ ] Plan critique gate (PROCEED) passed.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm report file exists | `test -f docs/plans/PLAN-cc-scheduled-agents.md && echo OK` | Prints `OK` | File missing -- re-run plan workflow |
| 2 | [pre-deploy] | Confirm Architecture section present | `grep -c "^# Architecture & Design Rationale" docs/plans/PLAN-cc-scheduled-agents.md` | Output `1` or higher | Section missing -- add it |
| 3 | [pre-deploy] | Confirm Decisions Register section present | `grep -c "^# Decisions Register" docs/plans/PLAN-cc-scheduled-agents.md` | Output `1` or higher | Section missing -- add it |
| 4 | [pre-deploy] | Confirm Phase Manifest present with 5 phases | `grep -E "^## Phase [1-5] --" docs/plans/PLAN-cc-scheduled-agents.md \| wc -l` | Output `5` | Wrong phase count -- review manifest |
| 5 | [pre-deploy] | Confirm Open Questions section present | `grep -c "^# Open Questions" docs/plans/PLAN-cc-scheduled-agents.md` | Output `1` or higher | Section missing -- add it |
| 6 | [pre-deploy] | Confirm Risks & Rollback section present | `grep -c "^# Risks & Rollback Strategy" docs/plans/PLAN-cc-scheduled-agents.md` | Output `1` or higher | Section missing -- add it |
| 7 | [pre-deploy] | Confirm Out of Scope section present | `grep -c "^# Out of Scope" docs/plans/PLAN-cc-scheduled-agents.md` | Output `1` or higher | Section missing -- add it |
| 8 | [pre-deploy] | Confirm rec-589 noted in Bundled Recommendations | `grep -c "rec-589" docs/plans/PLAN-cc-scheduled-agents.md` | Output `2` or higher (Bundled section + Decisions register) | rec-589 missing -- add to bundled recs |
| 9 | [pre-deploy] | Confirm plan committed on agent branch | `git log --oneline -1 -- docs/plans/PLAN-cc-scheduled-agents.md` | Shows a commit hash and message | Plan not committed -- commit it |

## Constraints
- This is a REPORT-ONLY plan: no implementation steps execute. Each of the 5 phases below becomes its own `/plan` -> manual `/implement` cycle.
- The autonomous executor is currently non-functional; each phase plan must be implemented manually. Phase plans must NOT be sent to `/implement` while the executor is broken; they must be executed by an interactive agent under the planning workflow's implementation methodology.
- Phase ordering must respect strangler-fig sequencing: legacy findings-processor stays active until the new pipeline has run successfully for at least 1 cron cycle.
- **Single Portal Invariant** (CLAUDE.md): scheduled agents must never write directly to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl`. All canonical writes go through `ops_data_portal`.
- **Branching invariant**: agents must never edit on `main`. The new permission model must coexist with the existing `never_on_main.py` PreToolUse hook.
- No rescue agents or workaround loops (Decision 55).
- All changes must be Bash-shell-syntax compatible (no PowerShell-only commands in agent prompts or scripts).

## Context
- The Lambda dispatcher was disabled via PR for `agent/disable-lambda-agents` (see `docs/plans/PLAN-disable-lambda-agents.md`). EventBridge rule `agent-platform-hourly-scheduled-agents` is set to DISABLED; dispatcher env var `SCHEDULED_AGENTS_ENABLED=false` provides a redundant kill-switch. Repo-root `CLAUDE.md` "Re-enable Lambda scheduled agents" runbook documents the rollback path.
- The findings-processor Lambda is still ACTIVE, S3-event-triggered on the `agents/` prefix. It performs (a) union of all agent findings, (b) priority-queue routing via `overwrite_jsonl`, (c) GitHub Models semantic dedup of new agent recs into `recommendations/agent-recommendations.jsonl`. This Lambda is in-scope for retirement (Phase 5).
- Current rec-curator artefacts live at `.github/prompts/scheduled/rec-curator.prompt.md` and `.github/agents/rec-curator.agent.md` (deep-frozen legacy under `.github/`). New Claude Code surface lives under `.claude/`.
- The OpsWriter write-through path in `scripts/s3_log_store.py:142-175` (and the priority-queue branch at `scripts/s3_log_store.py:240-252`) already routes appends for `.recommendations-log.jsonl` -> `ops_recommendations` and `priority-queue/.priority-queue.jsonl` -> `ops_priority_queue` Iceberg tables, with `queue_run_id` UUIDs auto-allocated per run. Phase 1 reuses or extends this routing.
- The reader (`scripts/session_preflight.py`) reads the rec log via Athena views (`sync_ops.pull` queries `ops_recommendations_current`) but reads the priority queue from the local JSONL file (`PRIORITY_QUEUE_FILE` constant). Phase 2 migrates this read.
- The preflight session at the start of THIS planning session surfaced an existing bug in `ops_recommendations_current`: `INVALID_VIEW: Column '_rn' is ambiguous`. This bug must be considered when designing the new `ops_priority_queue_latest_run` view (Phase 1) -- avoid the same anti-pattern.
- DECISIONS.md is the authoritative location for new architectural decisions. Phase 1 should file a new decision documenting findings-processor retirement.
- ROADMAP phase: Platform (parallel with Phase 2 schema backfill).
- The Anthropic-hosted `schedule` skill (CronCreate / CronList / CronDelete) is the cron mechanism. Each cron firing runs in a fresh sandbox; the agent commits and PR-merges from inside that sandbox.

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main` (currently on `agent/cc-scheduled-agents`).
- [x] docs/PROJECT_CONTEXT.md read in full.
- [x] DECISIONS.md context loaded via preflight (5 open decisions, strategic_review_due=true).
- [x] PLAN-disable-lambda-agents.md read for migration context.
- [x] schedule.yaml, rec-curator.prompt.md, rec-curator.agent.md, findings_processor_handler.py, run_scheduled_agent.py, s3_log_store.py, log-storage.md read.
- [x] Acceptance criteria reduced to structural checks suitable for REPORT-ONLY V1.

## Ordered Execution Steps
1. Author this report (the report itself is the artefact -- no further code changes).
2. **Execute Verification Plan** -- run each step. Loop until pass.
3. Submit to plan-critique gate; revise per critique output until PROCEED.
4. Commit approved plan; output REPORT-ONLY confirmation message.

---

# Architecture & Design Rationale

## North Star alignment
The current scheduled-agent pipeline is brittle (multiple Lambdas, GitHub Models API dependency, mixed storage patterns) and the dispatcher is disabled. Replacing it with Claude Code scheduled agents that emit per-run findings to git-tracked files, drained through the existing OpsWriter -> Iceberg -> Athena pipeline, eliminates infrastructure surface and consolidates on one ingestion pattern. This advances the North Star by reducing automation friction, producing reliable queryable feedback signals, and aligning the scheduled-agent surface with the planning/implementation workflow that already runs on Claude Code.

## Why Claude Code scheduled agents (not new Lambdas)
- **Easier iteration**: agent prompts are markdown files; no zip-build-deploy cycle.
- **Fewer auth surfaces**: Anthropic-hosted sandbox handles its own credentials; no Copilot SDK / OAuth token plumbing (recall the `ghp_` vs `gho_` gotcha already documented in `CLAUDE.md`).
- **Better isolation**: each cron firing runs in a fresh sandbox, eliminating state-bleed between runs.
- **Native fit**: scheduled agents and interactive sessions both run on Claude Code, sharing skills, hooks, and conventions. The `never_on_main.py` and similar safety primitives already exist and can extend cleanly.

## Auto-merge-via-PR (not direct push to main)
The agent creates / fast-forwards onto a feature branch, commits, opens (or reuses) a PR, and runs `gh pr merge --auto --squash`. CI gates the merge -- malformed JSONL or out-of-scope edits never reach `main`. Branch protection stays intact. The PR provides a per-run audit trail. The long-lived branch convention `agent/scheduled-agents` is established now so future agents can batch commits onto the same PR (multi-agent batching is out of today's scope but the branch convention reserves the seat).

## Hook + settings defense-in-depth
The agent must only edit files under `logs/agents/{name}/` and `logs/.ops-outbox/`. Two layers enforce this:
- **PreToolUse hook** (`.claude/hooks/scheduled_agent_log_only.py`): the load-bearing wall. Detects scheduled-agent context (env var or working-directory marker -- TBD Phase 3), denies any `Edit`/`Write`/`MultiEdit`/`NotebookEdit` outside permitted paths, runs JSONL schema validation on write content. Modeled on the existing `never_on_main.py` pattern.
- **Settings layer** (scoped settings.json block): the sign on the door. Declarative `permissions.allow`/`permissions.deny` documenting policy.

The portability concern (settings being harness-agnostic) is YAGNI: the hook is ~30 lines and would be re-implemented in a day if the harness ever changed. Both layers cost little; defense-in-depth is the right choice for autonomous-agent permissions on a self-improving system.

## Per-run timestamped files (not canonical JSONL writes)
Agents write findings to `logs/agents/{name}/{ts}.jsonl`. Three reasons:
1. **Concurrency safety**: per-run filenames never collide -- multi-agent batched commits on a shared branch don't race on file locks.
2. **Single Portal Invariant preservation**: the agent never writes canonical state (`.recommendations-log.jsonl`, `priority-queue/...`). Only `ops_data_portal` writes canonical state. The agent emits findings; the portal allocates IDs and routes to Iceberg.
3. **Audit granularity**: 1:1 mapping between cron firings and files; clean rollback by reverting a single commit.

## Findings-processor retirement
Today the findings-processor Lambda dedups, routes priority-queue items, and calls GitHub Models for semantic dedup of new recs. With Iceberg+Athena views as the source of truth, every job it does is replaced by simpler primitives:
- **Union of all agent findings** -> Iceberg table `ops_agent_findings` (or extension of `ops_recommendations` with a `proposed_by` field -- decided in Phase 1), queried as needed.
- **Priority-queue routing** -> direct write to `ops_priority_queue` via OpsWriter (already wired). Athena view `ops_priority_queue_latest_run` returns the latest run via `queue_run_id` filter.
- **Semantic dedup of new recs** -> dropped. Replacement: agent does title-equality dedup against open recs (it already has read access to the rec log), root-cause recs land as findings, humans triage in the next session.

This eliminates a Lambda, an external API dependency (GitHub Models), and an entire S3-event-driven control flow. Disabled via the same two-layer pattern as the dispatcher (env-var kill-switch + Terraform disable).

## SCD2-via-Athena-view as source of truth
Today's storage uses two patterns: SCD2-append-only Iceberg (for the rec log) and full-replacement S3 JSONL (for the priority queue via `overwrite_jsonl`). After migration, only the SCD2 pattern remains. The Athena view `ops_priority_queue_latest_run` filters by latest `queue_run_id` to surface "the current ranking", which matches the natural semantic of a priority queue (full-replace per run, but expressed as append-only with a run ID). The local JSONL becomes a write-only buffer drained via outbox; no consumer reads it after Phase 2.

## Branch convention: `agent/scheduled-agents`
Long-lived branch shared across all future scheduled agents. Single CI run amortises across multiple agent commits in the same window (future-state). For today's single-agent scope: rec-curator commits per run, auto-merges per run, branch is recreated from main if it was merged out the previous day. Agents that find an existing open PR fast-forward / rebase onto it before committing.

## Cron firing semantics
The Anthropic `schedule` skill (CronCreate) registers a recurring job that fires at the cron expression (UTC). Each firing receives a fresh sandbox with the repo cloned; the agent runs to completion, commits, and exits. The sandbox is destroyed after the firing -- there is no persistent state between firings beyond what the agent commits. This is good: it forces all state to flow through git + the outbox, matching the architecture above.

---

# Decisions Register

Decisions made during the 2026-05-05 planning session. Each subsequent phase plan must respect these.

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | rec-589 superseded by this migration | Lambda dispatcher is being retired; the polling bottleneck recommendation is moot. |
| D2 | Auto-merge via `gh pr merge --auto --squash` (not direct push to main) | Preserves branch protection + CI gates; provides audit trail; coexists with `never_on_main.py`. |
| D3 | Branch is `agent/scheduled-agents` (long-lived, shared across agents) | Multi-agent batched commits future-state; single CI run amortises cost. |
| D4 | Per-run timestamped findings files at `logs/agents/{name}/{ts}.jsonl` | Concurrency-safe; preserves Single Portal Invariant; audit granularity. |
| D5 | PreToolUse hook + settings layer for log-only enforcement (both, not either) | Defense-in-depth: hook is enforcement, settings are documentation. |
| D6 | rec-curator runs on `claude-opus-4-7` | User preference for the strategic curation work; matches the model used for the legacy Bedrock invocation. |
| D7 | Cron schedule `0 8 * * *` UTC, same as legacy | Behavioural continuity; queue is fresh by start of UK working day. |
| D8 | findings-processor Lambda will be retired (Phase 5) | All its responsibilities are subsumed by OpsWriter + Iceberg + Athena views. |
| D9 | Strangler-fig retirement: findings-processor stays active until new pipeline has run successfully for >=1 cycle | Rollback safety; legacy is the safety net during cutover. |
| D10 | No per-entry counter on priority-queue items; dedup via `queue_run_id` | Natural composite key matches full-replace-per-run semantic; `queue_run_id` is already allocated by `s3_log_store.py:243`. |
| D11 | Athena view `ops_priority_queue_latest_run` becomes the canonical priority-queue read source | SCD2-native; one consistent storage pattern across all ops tables. |
| D12 | Semantic dedup of new agent-proposed recs is dropped (was done by GitHub Models) | Replaced by simpler title-equality dedup performed by the agent itself; humans triage anything that slips through. |
| D13 | New surfaces live under `.claude/` (not `.github/` legacy paths) | `.github/` is deep-frozen legacy per CLAUDE.md instruction architecture; new work targets the canonical Layer 4 (skills/hooks). |
| D14 | Settings + hook layered enforcement; no Antigravity-style `.agents/skills/` migration in this plan | Out-of-scope for the rec-curator first cut; can be added later without retrofit. |
| D15 | Scheduled-agent execution model: Anthropic-hosted sandbox via `schedule` skill, not GitHub Actions runner | No new GitHub Actions OIDC plumbing required; SCP blocks on OIDC remain irrelevant. |

---

# Phase Manifest

Five phases. Each becomes its own `/plan` -> manual `/implement` (executor offline) cycle. Each phase plan MUST cite this report in its `## Context` section.

## Phase 1 -- Substrate

**Goal**: stand up the data plumbing that all subsequent phases depend on.

**Likely scope**:
- New Iceberg table `ops_agent_findings` (or extension of `ops_recommendations` with `proposed_by` field -- decide during Phase 1 planning, see Q4).
- New Athena view `ops_priority_queue_latest_run` filtering by latest `queue_run_id`. Avoid the `_rn` ambiguity that affects `ops_recommendations_current`.
- New `ops_data_portal --enqueue-findings <path>` interface (or equivalent helper) that reads a per-run findings JSONL and routes entries to the appropriate Iceberg table via OpsWriter / outbox.
- Confirm `.gitignore` does not exclude `logs/.ops-outbox/` (or add a tracking exception so commits include outbox entries).
- Mark rec-589 as superseded (status change via portal).
- File a new DECISIONS.md entry: "Findings-processor retirement and SCD2-via-Athena-view as source of truth".

**Dependencies**: none (foundation phase).

**Verification tier estimate**: V3 (real Iceberg DDL + real Athena query + real outbox round-trip).

**Risks**:
- Iceberg schema migration may interact with existing `ops_recommendations` writes; test carefully against staging first.
- New view may hit the same `INVALID_VIEW: Column '_rn' is ambiguous` issue currently affecting `ops_recommendations_current`; investigate root cause and avoid the anti-pattern.
- Iceberg integer promotion (existing gotcha): if the new table has integer columns, ensure `int` vs `bigint` typing matches existing promoted types.

## Phase 2 -- Reader migration

**Goal**: shift `session_preflight.py`'s priority-queue read from local JSONL to the new Athena view.

**Likely scope**:
- `scripts/session_preflight.py`: replace `PRIORITY_QUEUE_FILE` reads with Athena view query (model on the existing `sync_ops.pull` Athena patterns).
- Update `docs/contracts/log-storage.md`: deprecate the local JSONL read path; document Athena view as canonical.
- Tests for the new read path; ensure local-mode fallback behaviour is explicit (decision required: fail closed, or fall back to legacy file -- see Q6).
- Optional: feature flag (env var or settings) for one-cycle ability to revert to the local JSONL read.

**Dependencies**: Phase 1 must be complete (view exists, schema confirmed).

**Verification tier estimate**: V3 (preflight is a real workflow that humans run; needs to demonstrate Athena read works end-to-end).

**Risks**:
- Athena cold-start latency may slow preflight noticeably; benchmark and consider caching.
- Offline mode (no SSO) needs a graceful fallback -- currently the file read works without SSO; the view read will not. Decide fallback semantics during Phase 2 planning (probably: keep the local JSONL as a stale-but-readable fallback for offline use, fresh from the last drain).

## Phase 3 -- Agent infrastructure

**Goal**: build everything the rec-curator agent needs to run on Claude Code scheduling, except the actual cron registration (deferred to Phase 4).

**Likely scope**:
- New agent prompt at `.claude/agents/scheduled/rec-curator.md` (port from `.github/prompts/scheduled/rec-curator.prompt.md` with output-path adjustment to `logs/agents/rec-curator/{ts}.jsonl` and removal of S3-direct-write language).
- New PreToolUse hook at `.claude/hooks/scheduled_agent_log_only.py` (path-restriction + JSONL schema validation). Coexist with `never_on_main.py` -- both hooks fire; both must pass.
- Settings additions (scoped block) declaring `permissions.allow`/`deny` for scheduled agents.
- New `validate.py` check (`validate_scheduled_agent_logs`) enforcing: (a) only `logs/agents/**` and `logs/.ops-outbox/**` files modified on the branch, (b) JSONL schema valid, (c) per-run filename matches `{ts}.jsonl` pattern, (d) no canonical-state file modifications.
- Test coverage for hook, validate check, and any helper scripts (per `test_coverage_checker` requirements).
- Manual rec-curator dry-run: invoke the prompt locally; confirm it commits to `agent/scheduled-agents`, opens (or reuses) a PR, runs `gh pr merge --auto`, the outbox is enqueued, and the next preflight drains correctly.

**Dependencies**: gates on Phase 1 (the agent calls the new portal interface). Can run in parallel with Phase 2 as long as Phase 3's manual dry-run does not require the migrated reader (it doesn't -- it can still read the local JSONL during Phase 3 development).

**Verification tier estimate**: V3 (manual end-to-end dry-run: invoke the agent prompt locally, confirm it commits + opens PR + auto-merges + outbox is enqueued + drain pushes to Iceberg).

**Risks**:
- The `schedule` skill's per-agent identity surface is unknown -- the hook needs to identify "this is a scheduled agent run" reliably. Confirm during Phase 3 planning (env var, working-directory marker, or skill-provided context).
- JSONL schema enforcement at hook time requires the hook to parse `tool_input.content`; verify Claude Code's hook payload structure exposes this for `Write`/`Edit` tools.
- `gh pr merge --auto --squash` requires a GitHub PAT in the sandbox; figure out how the schedule skill provides credentials. May need a Secrets Manager fetch or a sandbox-injected token.

## Phase 4 -- Cutover & monitor

**Goal**: enable the cron, observe the first run end-to-end, confirm the new pipeline produces correct outputs.

**Likely scope**:
- Register rec-curator via the `schedule` skill (`CronCreate`) with `0 8 * * *` UTC, model `claude-opus-4-7`, prompt `.claude/agents/scheduled/rec-curator.md`.
- Wait for first cron firing; observe end-to-end (agent runs -> commits -> PR auto-merges -> next preflight drains outbox -> Iceberg gets updated -> Athena view returns latest run).
- Manually verify priority-queue entries match expected ranking heuristics by comparing to the last legacy run's output.
- Update `docs/SESSION_LOG.md` and `docs/CHANGELOG.md` with the rollout entry.

**Dependencies**: gates on Phase 3 (agent infrastructure ready) AND Phase 2 (reader expects new view).

**Verification tier estimate**: V3 (real cron firing, real PR, real merge, real Iceberg write, real Athena read).

**Risks**:
- First-run failures (auth, missing files, schema mismatch) require quick diagnosis. Document the rollback path in the Phase 4 plan: cancel cron via `CronDelete`, leave dispatcher disabled, legacy findings-processor stays active.
- Time-boxed: if the cron firing produces no output or wrong output within the first 24 hours, a phase-4-rollback plan must restore the legacy flow.
- Auto-merge may fail if branch protection requires reviews; either disable that requirement for `agent/scheduled-agents` or use a bot account / branch-protection exception.

## Phase 5 -- Findings-processor retirement

**Goal**: disable the findings-processor Lambda using the same two-layer pattern as the dispatcher.

**Likely scope**:
- Add `FINDINGS_PROCESSOR_ENABLED` env var kill-switch in `src/data/handlers/findings_processor_handler.py` (return early if not `"true"`).
- Terraform: disable the S3 bucket notification on the `agents/` prefix (or set the Lambda's event source mapping to inactive). Set `FINDINGS_PROCESSOR_ENABLED=false` in the Lambda env block.
- Update `CLAUDE.md` operational runbook with re-enable instructions (mirror the existing dispatcher rollback section).
- File a DECISIONS.md update marking the findings-processor retirement decision as resolved (closed) and archiving to `DECISIONS_ARCHIVE.md`.

**Dependencies**: gates on Phase 4 (must observe at least one successful new-pipeline cycle before retirement). Strangler-fig sequencing.

**Verification tier estimate**: V3 (real Lambda invocation post-disable -- confirm it returns the disabled-status response; real S3 PutObject to `agents/` -- confirm the Lambda is not triggered).

**Risks**:
- Premature retirement breaks the rollback path. Phase 4 must demonstrate at least one successful cycle before Phase 5 starts.
- Other consumers (if any) of `findings/unified.jsonl` or `recommendations/agent-recommendations.jsonl` may break; grep for readers before retirement (see Q8).

---

# Open Questions

Items that must be resolved during phase planning. Listed by the phase that should answer each.

| # | Question | When |
|---|----------|------|
| Q1 | Is `logs/.ops-outbox/` gitignored? If yes, the agent's commits won't include outbox entries -- need an exception. | Phase 1 |
| Q2 | Exact `ops_data_portal` enqueue interface: does `--enqueue-findings <path>` already exist, or do we add it? Is there a Python API equivalent? | Phase 1 |
| Q3 | Does the `schedule` skill expose per-agent identity to the PreToolUse hook (env var, working dir, payload)? | Phase 3 |
| Q4 | Should root-cause recs go to a new `ops_agent_findings` table, OR extend `ops_recommendations` with a `proposed_by` field? | Phase 1 |
| Q5 | Does the Athena `ops_recommendations_current` view's `_rn` ambiguity bug also threaten the new `ops_priority_queue_latest_run` view? Is there scaffolding to reuse? | Phase 1 |
| Q6 | Offline-mode fallback for preflight when SSO is unavailable: keep reading the local JSONL as fallback, or fail closed? | Phase 2 |
| Q7 | Does the agent's auto-merge PR need a separate CI workflow, or do existing checks cover the new validate.py rules? | Phase 3 |
| Q8 | Are there any other consumers of `findings/unified.jsonl` or `recommendations/agent-recommendations.jsonl` beyond the findings-processor? | Phase 5 |
| Q9 | How does the `schedule` skill provide GitHub credentials to the sandbox so `gh pr merge --auto` can run? | Phase 3 |
| Q10 | Does Anthropic's `schedule` skill billing model affect cadence decisions? Should rec-curator stay daily or move to weekly? | Phase 4 |

---

# Risks & Rollback Strategy

## Strangler-fig sequencing (D9)
- Phase 5 (findings-processor retirement) MUST NOT begin until Phase 4 has demonstrated at least one successful end-to-end cycle. The legacy pipeline is the rollback path during Phase 3-4 development.
- If Phase 4 fails, the rollback is: (a) cancel the cron via `CronDelete`, (b) leave the dispatcher disabled (it was already), (c) the legacy findings-processor stays active so any leftover S3 writes still process correctly.

## Per-phase rollback notes
- **Phase 1**: Iceberg DDL is reversible via `DROP TABLE`. Athena view drop is trivial. Portal interface change should be additive (new flag, not a replacement) to avoid breaking existing callers.
- **Phase 2**: Reader migration must keep a feature flag (env var or settings) that allows reverting to local JSONL read in one-line. Document in the Phase 2 plan.
- **Phase 3**: All artefacts are new files; rollback is `git revert`. The hook becomes inert if no scheduled-agent context is detected.
- **Phase 4**: Cron deletion is one `CronDelete` call. PRs in flight can be closed unmerged. Branch `agent/scheduled-agents` can be deleted.
- **Phase 5**: env-var flip + Terraform revert restores the findings-processor. Lambda code is unchanged so re-enable is instant.

## Cross-phase risks
- **Schema drift**: rec-curator's output JSON schema must remain stable through phases. Lock the schema in Phase 1 and reference it in Phase 3.
- **DynamoDB ID allocation**: agent emits findings without IDs; portal allocates on enqueue. Ensure the portal's allocation logic handles the new finding types.
- **Branch-protection coupling**: auto-merge requires CI to be green and any required reviewers satisfied. Phase 3 may need to introduce a branch-protection exception for `agent/scheduled-agents`.
- **Sandbox credentials**: the `schedule` skill must provide GitHub auth in the sandbox or the merge step fails. Phase 3 (Q9) resolves this.

---

# Out of Scope (Today)

Items deliberately deferred to future planning sessions:

- **Multi-agent batched commits to `agent/scheduled-agents`**. Today's scope: rec-curator commits and auto-merges per run. Future: doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality run on the same shared branch and amortise CI cost. Will require a coordination mechanism (branch lock, retry-on-rebase, or windowed batching) -- separate planning session.
- **Migration of doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality** to Claude Code scheduled agents. These follow the same pattern as rec-curator. After rec-curator is proven, each gets its own /plan -> /implement cycle (5 small plans, not one big one).
- **Retirement of the dispatcher Lambda code itself** (currently disabled but deployed). Retirement = remove from `build_lambda.py` and Terraform. Defer until all six scheduled agents have migrated.
- **Semantic dedup replacement for new agent-proposed recs**. Dropped today; rely on title-equality dedup. If duplicates accumulate, future planning session can add a curator-pass that runs over `ops_agent_findings` table.
- **Athena view performance optimisation**. If preflight is slowed by view queries, Phase 2 may add caching, but tuning Iceberg partitioning / view rewrites is a separate concern.
- **Cost monitoring / budgets** for Claude Code scheduled agents. The `schedule` skill's billing model needs investigation; budget instrumentation is its own plan.
- **Promotion of `proposed_by: rec-curator` findings to canonical recs**. Today: humans triage. Future: a curator-pass (or a manual workflow) promotes accepted findings to `ops_recommendations` with proper IDs.
- **Antigravity skill migration** (`.agents/skills/`). New scheduled-agent surface lives under `.claude/`; migration to `.agents/` for cross-harness portability is a future concern.
- **Backfill of historical priority-queue data** into the new Iceberg table. The legacy `priority-queue/.priority-queue.jsonl` represents only the most recent run; there is no history to backfill. New runs accumulate naturally from cutover.
- **Fixing the existing `_rn` ambiguity bug in `ops_recommendations_current`**. Surfaced during preflight. Track separately as a recommendation; not blocking this migration.

---

# Phase 1 Implementation Summary

Implemented 2026-05-05 on branch `agent/cc-scheduled-agents-phase-1` per `docs/plans/PLAN-cc-scheduled-agents-phase-1.md`.

## What was built

- **`enqueue_findings(path, profile) -> dict`** in `scripts/ops_data_portal.py`: bulk-ingestion entrypoint for scheduled-agent JSONL findings files. Pre-validates each entry against the Recommendation schema before routing to `file_rec()`, so schema-invalid entries are counted as `invalid` even in offline mode. Returns `{enqueued, invalid, skipped}`.
- **`--enqueue-findings PATH` CLI flag** wired into the `ops_data_portal` mutually-exclusive action group.
- **`.gitignore` carve-out**: `logs/.ops-outbox/**` (replacing the old `logs/.ops-outbox/` with trailing slash) plus `!logs/.ops-outbox/ops_recommendations_pending/` and `!logs/.ops-outbox/ops_recommendations_pending/*.json`. The trailing-slash form prevented git traversal and blocked negation patterns; the `**` form allows them.
- **Decision 61** filed in `docs/DECISIONS.md`: "Scheduled-agent findings flow through ops_recommendations via the source field" -- records the architectural intent, the rejection of the new-table approach, and the Phase 5 retirement deferral.
- **rec-589** ("Monitor or optimize Athena polling bottleneck in Lambda dispatcher") marked `superseded` with resolution "superseded by cc-scheduled-agents migration".
- **4 new unit tests** in `tests/test_ops_data_portal.py` (TestEnqueueFindings class + CLI dispatch test).

## What was NOT built (and why)

- **`ops_agent_findings` Iceberg table**: unnecessary. The existing `source` field on `ops_recommendations` discriminates findings by origin. Adding a second table would duplicate the offline-resilient outbox + drain cycle without architectural benefit.
- **`ops_priority_queue_latest_run` Athena view**: unnecessary. The existing `ops_priority_queue_current` view (terraform/iceberg_tables.tf:1042-1051) already implements the latest-run-by-`queue_run_id` semantic using a correlated subquery. Building a second identical view adds maintenance burden with no benefit.

## Open Questions closed

| Q | Answer |
|---|--------|
| Q1: Is `logs/.ops-outbox/` gitignored? | YES - confirmed at `.gitignore:115`. Carve-out added (this plan). The trailing-slash pattern blocked negation; fixed to `**` form. |
| Q2: Exact `ops_data_portal` enqueue interface | `enqueue_findings(path: Path, profile: Optional[str] = None) -> dict` returning `{enqueued, invalid, skipped}` + `--enqueue-findings PATH` CLI flag. |
| Q4: New table OR extend `ops_recommendations`? | Extend -- use existing `source` field. No new table. Decision 61 filed. |
| Q5: Does the new view risk the same `_rn` ambiguity? | No new view. Existing `ops_priority_queue_current` uses a correlated subquery, not ROW_NUMBER(), so no `_rn` issue. |

Q3, Q6, Q7, Q8, Q9, Q10 remain deferred to Phases 2-5.

## Gotchas observed

- **`_rn` ambiguity in `ops_recommendations_current`**: confirmed at preflight (`INVALID_VIEW: Column '_rn' is ambiguous`). The Terraform definition uses `row_num` but the stored Glue view references `_rn`. Out of scope here; recommend filing a separate rec to fix the view DDL.
- **Dual definition of `ops_priority_queue_current`**: defined in both `terraform/iceberg_tables.tf:1042-1051` and `ops_writer.py:553-558`. Benign (idempotent CREATE OR REPLACE) but any future semantic change must be made in both locations. Consolidation deferred.
- **`S3_LOG_BUCKET` not set in agent sessions**: `OpsWriter.write()` is a no-op without this env var, so drain results are local-only until the variable is set. V3 verification worked around this by explicitly setting the variable for staging and compact calls.

## Commit references

PR squashed-merge SHA: TBD (to be filled in at merge time). Branch: `agent/cc-scheduled-agents-phase-1`.

## For Phases 2-5

The Phase 1 substrate is complete. The key architectural anchor is **Decision 61**: scheduled-agent findings flow through the existing `ops_recommendations` table (via `source` field) and the existing outbox drain cycle. No further substrate work is needed.

- The canonical priority-queue read view is `ops_priority_queue_current` (NOT a new view).
- The canonical findings write path is `ops_data_portal.enqueue_findings(path)`.
- Phase 2 (reader migration) can begin immediately. Phase 3 (agent script scaffolding) and Phase 4 (cron wiring) follow per the Phase Manifest. Phase 5 (findings-processor retirement) must wait until Phase 4 demonstrates at least one successful end-to-end run (D9 sequencing constraint).

---

# Critique Outcome

Plan-critique gate (zero-context, automated) executed 2026-05-05 against this plan with `docs/PROJECT_CONTEXT.md`, `docs/ROADMAP.md`, and `docs/DECISIONS.md` as supporting context. Result: **PROCEED**.

Critique-confirmed findings (no revisions required):
- North Star alignment: 5/5.
- No conflicts with Decisions 51 (Local-First Outbox), 55 (RCA-First), 56 (SCD2 simplification). Correctly supersedes Decision 37 (Lambda scheduled agents).
- Phase ordering and dependencies validated.
- All Verification Plan steps contain executable commands.
- **Q1 confirmed**: critique reading of `.gitignore` verified that `logs/.ops-outbox/` is currently gitignored. Phase 1 MUST add a tracking exception (`!logs/.ops-outbox/` or path-specific carve-out) before agent commits will include outbox entries.
