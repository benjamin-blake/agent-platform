# Open Decisions

This document tracks key architectural and operational decisions that need to be made as the system evolves.

## Decision 75: Frame-Lock Anti-Pattern in Architectural Planning (Decided)

**Status:** Decided
**Date:** 2026-05-27
**Warehouse ID:** dec-081

**Problem:**
Architectural planning for the autonomous executor (CD.11, T4.1, `INTENT-provider-agnostic-executor.md` Stage 4) proposed Fargate, then Modal, then Fargate Spot via AWS Batch as candidate compute substrates -- all three options shared the unexamined assumption that the executor would be a monolithic Python process running an in-process agent loop. The Step Functions + per-step Lambda alternative -- which collapses 6 of T4.1's named subsystems into ~30 lines of Python, eliminates the substrate question entirely, aligns with NS.5 ("typed tools over HTTPS") and CD.10 ("Lambda per tool"), and uses primitives already in production (Decision 39 ratified Step Functions over Airflow; `terraform/data_pipeline.tf` ships a 5-Lambda Step Functions pipeline) -- was never raised during planning. It surfaced only when an outsider perspective, loaded without months of frame-locking context, asked "what if the executor isn't a long-running Python process?"

The miss was structural, not tactical. Three compounding biases produced it:

1. **Frame lock at the originating artefact.** `docs/INTENT-recommendation-executor.md:70` framed the executor as "Orchestrator entry point. Thin exception-catching wrapper around `_execute_recommendation_inner()` which contains all orchestration logic." Once the orchestration role was assigned to Python code, the substrate question became "what runs Python long enough?" not "what orchestrates workflows?" Step Functions never entered the executor conversation because the executor's frame was already locked to "Python orchestrator."

2. **Conceptual state machine versus managed state machine.** The executor INTENT Section 5.4 calls itself "State Machine (Work in Progress)" but the state machine being designed is a Python-internal lifecycle encoded in `_execute_recommendation_inner()` branches. The team simultaneously used Step Functions for the market data pipeline (Decision 39) but never applied the same pattern to the executor itself -- the term "state machine" carried two meanings and the conflation prevented the obvious application.

3. **Tool acquired after design committed; tool never retrofitted.** Decision 39 ratified Step Functions over Airflow at a time when the executor architecture was already in flight (`scripts/execute_recommendation.py` predates it). New capability landed in the toolkit, but no audit was triggered to ask "where else in the system could this newly-acquired capability apply?" The acquired tool stayed scoped to its original ETL use case.

**Decision:**

Recognise frame-lock as a named architectural-planning failure mode. Embed two mitigations that catch future instances:

1. **Frame-challenge phase in the plan-critique skill.** Add a mandatory phase to `.claude/skills/plan-critique/SKILL.md` and its `.agents/skills/plan-critique/SKILL.md` mirror (per Decision 58). The phase asks five questions designed to challenge the frame of a plan rather than its details:
   - What if the orchestrator wasn't this kind of thing? (Question the chosen primitive itself.)
   - What if this monolith were decomposed at a different boundary? (Question the unit of work.)
   - What existing platform primitives could absorb this custom code? (Question whether custom orchestration / retry / scheduling / state-machine / queue logic should be replaced by AWS-native primitives already in this codebase.)
   - What assumption from an earlier decision are we still carrying that the world has moved past? (Question whether constraints cited in the plan reference a Decision whose premise no longer holds.)
   - What tools or capabilities have been added since this approach was first conceived? (Question whether capabilities ratified by Decisions or added by infrastructure have retroactively changed the right shape of the work.)

   Plan-critique surfaces the answers in a new "Frame Challenge" field in its structured output. The critique recommends REVISE only when a frame challenge identifies a concrete contradiction with a Decision, a Roadmap item, or a North Star principle; otherwise the challenges are surfaced informationally for the human to consider.

2. **This decision IS the second mitigation.** Naming the failure mode and documenting it in DECISIONS.md lets future plan-critique runs flag candidate frame-lock instances by reference rather than re-deriving the diagnosis each session. Decisions 55 (RCA-First Executor) and 72 (RCA-as-Plan-Source) follow the same pattern: naming a failure mode lets agents detect and reference it by ID.

**Rationale:**

- The frame-lock pattern is detectable structurally if you know to look for it. The plan-critique skill currently challenges plan details against the existing frame; it does not challenge the frame itself. That gap is the institutional control that needs to exist.
- Two independent mitigations catch each other's misses. The skill update catches frame issues at plan time; the named Decision lets the skill and humans reference the pattern by ID rather than re-derive it.
- Cost is small: one skill section (mirrored), one Decision entry. No infrastructure change, no schema change, no runtime impact, no follow-on plans required.
- The cure for tool-acquired-after-design-committed is the same: a frame-challenge question explicitly asks "what tools have been added since this approach was conceived?" which catches the Decision 39 -> executor gap that produced this very Decision.

**Constraints:**
- The frame-challenge phase surfaces questions for human or critique-agent judgment; it does NOT enforce a particular answer. Detection by name is not automatic rejection. A plan can validly choose to carry forward an existing frame; the requirement is that the choice is conscious.
- Soft-warn semantics: plan-critique recommends REVISE only on concrete contradictions, not on every surfaced challenge. The cost of false-positive REVISE is friction in every planning session; the cost of false-negative is another frame-lock event. Bias toward surface-and-let-human-decide.

**Acknowledges:**
- Decision 39 (Step Functions over Airflow): the canonical case where ratified capability was not retrofitted into existing-design architecture.
- Decision 55 (RCA-First Executor): framing precedent for naming a failure mode as a Decision.
- Decision 58 (.agents as canonical interactive workflow layer): the skill update lands in both `.claude/skills/plan-critique/SKILL.md` and `.agents/skills/plan-critique/SKILL.md` per the cross-harness mirror rule.
- Decision 72 (RCA-as-Plan-Source for CI): framing precedent for systematic anti-pattern detection via named pattern reference.
- `docs/INTENT-recommendation-executor.md`: the source artefact whose framing locked the downstream chain (CD.11 Fargate, T4.1 XL Fargate decomposition, INTENT-provider-agnostic-executor Stage 4 substrate selection).
- `docs/INTENT-provider-agnostic-executor.md`: Stage 4 selection criteria considered six container runtimes (Lambda Container, Fargate, Batch, Modal, Cloud Run Jobs, EKS) without considering Step Functions as the orchestration layer above whichever runtime was chosen. Illustrative of the frame.

**Related:** Decision 39, Decision 55, Decision 58, Decision 72, `docs/INTENT-recommendation-executor.md`, `docs/INTENT-provider-agnostic-executor.md`, `docs/ROADMAP-PLATFORM.yaml` (CD.11, T4.1, T4.2)

---

## Decision 74: Pre-Install Claude Code CLI in Runner user_data + workflow_dispatch Escape Hatch (Decided)

**Status:** Decided
**Date:** 2026-05-22

**Problem:**
ci-rca runs `26284914206` and `26287172232` both failed at `Install Claude Code CLI` with `npm error code EACCES ... mkdir '/usr/lib/node_modules/@anthropic-ai'`. The runner's `npm install -g` runs as the `ubuntu` user, which lacks write access to the global node_modules directory. Although Ubuntu cloud AMIs grant passwordless sudo, the existing step did not use `sudo`. The result: every CI failure since 2026-05-22 produced no ci-rca rec -- the Decision 73 forward-fix model received zero failure signals while `ci_rca_liveness_alert` fired continuously (69.6 minutes elapsed at planning time, referencing run `26286390667`). Additionally, there was no mechanism to re-run ci-rca against a past failure without pushing a fake CI commit to trigger `workflow_run`.

**Decision:**
Two changes to restore and harden the harness:

1. **Sudo + pinned install in the workflow**: Replace `npm install -g @anthropic-ai/claude-code` with `sudo npm install -g @anthropic-ai/claude-code@2.1.148 --omit=dev --omit=optional && sudo npm cache clean --force`. Version pin `@2.1.148` locks the install to the version confirmed working as of 2026-05-22 (`npm view @anthropic-ai/claude-code dist.unpackedSize` returned 136KB unpacked). The `--omit` flags reduce install footprint on the 20GB volume (82% used, 3.6GB free).

2. **workflow_dispatch escape hatch**: Add `workflow_dispatch: inputs: run_id` trigger to `.github/workflows/ci-rca.yml` so the agent can be manually re-dispatched against any past CI run ID without pushing a fake commit. Enables `gh workflow run ci-rca.yml --ref <branch> -f run_id=26286390667` to retroactively diagnose the SLOC limit violation on `scripts/product_roadmap.py` (631 SLOC) from the triggering CI failure.

**Deferred:** Pre-baking the CLI in `terraform/ec2_runner.tf` user_data was planned but deferred. During implementation, `terraform plan` revealed that `data.aws_ami.ubuntu_22_04 { most_recent = true }` had resolved to a newer AMI (`ami-0adb4b73a38358d7c` -> `ami-02b81edd0fb821197`), causing the instance to be flagged for destroy-and-replace regardless of the user_data change. Recreating the production runner is out of scope. A follow-on plan should pin the AMI ID (removing `most_recent = true`) before attempting the user_data pre-bake apply.

**Rationale:**
- EACCES is structural: non-root npm global install on Ubuntu requires sudo. `sudo` is the minimal correct fix.
- Pinning prevents silent upgrades from breaking the harness; version bumps are explicit future plan changes.
- The `workflow_dispatch` trigger adds an operator escape hatch missing from Decision 72's original implementation without changing `workflow_run` semantics.
- The existing runner self-heals via the workflow YAML change -- no runner recreation is needed for the immediate fix.

**Constraints:**
- Existing runner is NOT restarted or recreated. The `sudo` fix self-heals on the next ci-rca dispatch after this branch merges.
- `CLAUDE_CODE_OAUTH_TOKEN` rotation (90-day expiry) deferred -- 90-day migration window to GitHub-hosted runners makes rotation unlikely to bite before migration lands.
- Version `@2.1.148` is current as of 2026-05-22. Future plans may bump.

**Acknowledges:**
- Decision 72 (RCA-as-Plan-Source): this decision hardens the harness Decision 72 introduced.
- Decision 73 (Forward-Fix CI model): this decision restores the failure-signal path Decision 73 depends on.
- Decision 68 (Self-Hosted Runner): terraform apply deferred due to pre-existing AMI drift triggering instance replacement; see Deferred note above.

**Related:** Decision 68, Decision 72, Decision 73, failed ci-rca run `26287172232`, triggering CI run `26286390667`

---

## Decision 73: Two-Tier Diff-Aware CI with Forward-Fix and Scheduled Promotion Train (Decided)

**Status:** Decided
**Date:** 2026-05-13

**Problem:**
Decision 60 (2026-05-05) specified a two-tier validation model with a 5-minute fast-tier budget. The budget was unattainable at ratification: V3 verifiers (PR #274, 2026-05-01) and the DQ runner integration (PR #289, same day as Decision 60) placed ~10 minutes of Athena round-trips in the default presubmit tier on day zero. Twelve subsequent commits to `validate.py` between 2026-05-06 and 2026-05-12 compounded the drift. Measured runtimes show median 18 min, max 50 min -- a 3-10x violation of the documented budget. The structural causes are: (1) the budget had no enforcement mechanism, (2) the tier was defined by exclusion of a barely-used pytest marker (`@pytest.mark.integration` is set on exactly 1 of ~30 AWS-touching test files), and (3) post-merge CI ran on push-to-main duplicating PR CI on the same content. Additionally, with GitHub branch protection permanently unavailable (Decision 72), Decision 72b made remote CI the only merge gate -- yet the gate runs the same slow tier that should be reserved for comprehensive validation. The merge model conflates pre-merge gating with comprehensive validation, and the planning queue currently treats 178 accumulated non-automatable recommendations as mandatory discussion items, which is operational noise while the executor is offline pending Decision 67 reversal.

**Decision:**
Adopt a ten-layer CI/CD architecture (L1-L10) as specified in `docs/INTENT-ci-cd-architecture.md`. The model preserves Decision 60's two-tier abstraction while redefining tier semantics and adding forward-fix merge gating and scheduled promotion design.

Key elements:

1. **Two tiers with new semantics.** Fast tier (`--pre`) becomes diff-aware (ruff/mypy on changed files only, `pytest --picked` for test selection, hard 5-min budget assertion). Full tier (default) runs everything end-to-end with an honest 15-30 min budget. The fast tier asserts wall-clock budget and fails non-zero on breach.

2. **PR gating uses fast tier.** PR CI runs `--pre`. Full tier runs on push to `main` and on hourly scheduled cron (L8 drift canary). The post-merge full tier replaces the previously-duplicate PR-then-main runs.

3. **Forward-fix merge gate, not auto-revert.** Auto-revert is excluded because it moves `main` underneath active worktrees -- structurally hostile to multi-worktree parallel development and to the future autonomous executor (Wave 4). On full-tier failure on `main`, `ci-rca` files a `priority="critical"`, `source="ci_rca"` rec; the rec hard-blocks the planning queue (L5) and pauses PR auto-merge (L6) until a forward-fix lands.

4. **Planning queue governance.** While an open ci-rca rec exists, `/plan` cannot scope unrelated work; `session_preflight.py` surfaces the block at the top of its report. Separately, the existing rule that treats `non_automatable_recommendations > 0` as MANDATORY discussion is suspended until Decision 67 reverses and the executor is back in service. Counts remain informational in the preflight report.

5. **Sandbox tolerates red `main`; SIT and PROD do not.** Sandbox is the only environment agents touch. Forward-fix recovers sandbox via the standard rec → plan → implement cycle, typically within hours. SIT and PROD inherit only sandbox commits that have been green continuously ≥24h (sandbox→SIT) or ≥7d (SIT→PROD); the green-streak resets on any ci-rca rec opening. SIT and PROD environments are months-away future work, deferred to Phase Infra-Env.

6. **Merge-mode is derived from the diff, not stored.** A path-prefix table (specified in INTENT Section 7) computes sync vs async gating from `git diff --name-only`. The `automatable` field on `ops_recommendations` retains Decision 44 semantics (executor self-modification boundary) and is not extended into merge-mode territory. Conflation was considered and rejected: actual file overlap between the two lists is near-zero, and unifying would either expand the executor boundary into non-self-modification files or over-gate executor-machinery PRs that are well-tested.

**Rationale:**

- *Agent-first throughput.* Sync pre-merge gating on a 30-minute full tier stalls the recursive self-improvement loop. Async with forward-fix unblocks agents after a 5-minute fast tier while preserving recovery via the existing rec/plan/implement infrastructure.
- *Worktree-safe.* Forward-fix touches `main` only via append; auto-revert moves `main` underneath worktrees, which is hostile to the parallel-execution pattern this repo already uses and will use more heavily in Wave 4.
- *Industry-aligned.* Optimistic merge with post-merge comprehensive validation and queued remediation is the canonical pattern at Google (TAP), Meta (Sapling/TAP), and AWS internal pipelines. The agent-first variant replaces "human notification" with "rec in priority queue"; the shape is identical.
- *Enforced budgets.* Decision 60's 5-minute fast-tier target becomes a runtime assertion. The decision becomes real when violation produces a visible failure, not when documentation says it should hold.
- *Time + green-streak promotion.* Bake time is the strongest test available against real-world conditions you cannot anticipate. Time alone is not enough -- a recently-broken commit promoted exactly 24h after merge would inherit a known-broken state. The green-streak window ensures only stable commits cross promotion gates.

**Supersedes / Amends:**
- Implementation mechanism of Decision 60 (tier definitions and enforcement). The two-tier abstraction and 5-minute fast-tier target survive; the exclusion-by-marker mechanism is replaced by diff-aware selection with an enforced budget assertion.
- Implicit "remote CI on every PR push and every main push" pattern in `.github/workflows/ci.yml`. The push-to-main trigger now runs the full tier (not duplicating the PR run); the PR trigger runs the fast tier.

**Acknowledges:**
- Decision 44 (Executor Self-Modification Boundary): preserved unchanged.
- Decision 55 (RCA-First Executor): the forward-fix model is RCA-first applied to the CI merge gate.
- Decision 67 (Lambda + STRATEGIC plans deferred): the non-automatable rec surfacing change reverts when Decision 67 reverses.
- Decision 68 (Self-Hosted Runner): compounds. Free CI minutes are what make the hourly L8 drift canary affordable.
- Decision 71 (cc-scheduled-agents): compounds. The scheduled-cron infrastructure pattern is reused for L8.
- Decision 72 (RCA-as-Plan-Source for CI): extended. ci-rca recs gain hard-block (L5) and merge-pause (L6) semantics.
- Decision 72 (Branch Protection Unavailable): the forward-fix model is designed around branch protection being permanently unavailable.

**Consequences:**
- Three follow-on IMPLEMENTATION plans are required to land the architecture: `validate-fast-tier-reshape`, `ci-workflow-restructure`, `planning-queue-governance`. Each is independently scoped and lands in its own PR.
- L9-L10 (sandbox/SIT/PROD promotion train) are designed in `docs/INTENT-ci-cd-architecture.md` but deferred to Phase Infra-Env activation. SIT and PROD environments do not exist today; building them is months-away work.
- The 178 non-automatable recommendations currently accumulating will not be surfaced for mandatory discussion until Decision 67 reverses and the executor returns to service. They remain queryable from `ops_recommendations`; only the planning-skill behaviour changes.
- Auto-merge pause (L6) and planning hard-block (L5) require enforcement code in `scripts/session_preflight.py`, the planning skill, and the workflow YAML. These changes land in the `planning-queue-governance` and `ci-workflow-restructure` plans respectively.
- Decision 60 remains in DECISIONS.md as the originating ratification; this decision amends rather than retires it. The 5-minute fast-tier budget and the two-tier abstraction are preserved; only the implementation mechanism is replaced.

**Known Gaps (mirrored from INTENT Section 9):**
- L9-L10 promotion train: months away minimum; depends on Phase Infra-Env, SIT/PROD accounts, and trading-go-live readiness.
- Executor priority-queue rule for ci-rca recs: depends on Wave 4 + Decision 67 reversal.
- `pytest --picked` may be upgraded to `pytest-testmon` later if false-negatives accumulate.

**Related:** Decision 44, Decision 55, Decision 60, Decision 67, Decision 68, Decision 71, Decision 72 (both), `docs/INTENT-ci-cd-architecture.md`, `docs/ROADMAP-PRODUCT.md` (Phase Infra-Env).

---

## Decision 72: RCA-as-Plan-Source for CI Merge Gate Failures (Decided)

**Status:** Decided
**Date:** 2026-05-11

**Problem:**
CI failures on feature branches require manual diagnosis today. There is no automated surfacing of root cause, and developers may write workarounds rather than fix the underlying issue -- the anti-pattern Decision 55 was designed to prevent. The cc-scheduled-agents pattern (Decision 71) already provides the infrastructure to extend RCA-first diagnosis to the CI merge gate, but it has not been applied there.

**Decision:**
On CI failure (`workflow_run.conclusion == 'failure'`), a `workflow_run`-triggered GitHub Actions workflow (`.github/workflows/ci-rca.yml`) invokes `claude -p` headlessly on the self-hosted runner. The ci-rca agent reads the failed run logs via `gh run view <run-id> --log-failed`, identifies the root cause with evidence, and files a recommendation with `source="ci_rca"` and `priority="critical"` via `python -m scripts.ops_data_portal file_rec`. The agent does NOT propose or execute any autonomous fix. The rec is consumed via the standard `/plan` -> `/implement` flow. A new "CI RCA Recs (open)" section in `session_preflight.py` surfaces open `ci_rca` recs in every subsequent planning session.

**Rationale:**
Reuses the cc-scheduled-agents infrastructure (Decision 71) with a `workflow_run` trigger instead of cron. Reuses `ops_recommendations` as the single rec queue (Decision 50). Reuses the `source` field as a discriminator (Decision 61). Honours the no-autonomous-fix invariant (Decision 55). Preserves human-in-the-loop architectural judgment -- the ci-rca agent diagnoses and signals, the developer decides and acts via `/plan`.

**Consequences:**
`workflow_run` workflows execute in the context of the default branch but check out at the `head_sha` of the triggering run. A PR that modifies `.claude/agents/scheduled/ci-rca.md` and itself fails CI will invoke ci-rca with that PR's potentially-modified agent file. This is intentional (the PR author gets feedback on their own changes), but a malformed agent definition in a PR can cause that PR's ci-rca run to fail.

**Related:** Decision 50 (Iceberg ops store), Decision 51 (local-first outbox), Decision 55 (RCA-first executor), Decision 60 (two-tier validation), Decision 61 (source discriminator), Decision 68 (self-hosted runner), Decision 71 (cc-scheduled-agents pattern)

---

## Decision 71: cc-scheduled-agents Cron Mechanism is GitHub Actions on Self-Hosted Runner (Decided)

**Status:** Decided
**Date:** 2026-05-09

**Problem:**
Parent plan PLAN-cc-scheduled-agents.md D15 specified the Anthropic-hosted `schedule` skill (CronCreate) as the cron mechanism for cc-scheduled-agents to avoid OIDC complexity and GitHub Actions billing. Decision 68 (self-hosted EC2 runner) resolved both concerns: CI minutes are free on the self-hosted runner, and `GITHUB_TOKEN` auto-injection by the GitHub Actions platform solves the credential problem that was the core unresolved risk (parent plan Q9).

**Decision:**
The cron mechanism for cc-scheduled-agents Phase 4 is a GitHub Actions scheduled workflow (`on: schedule: - cron: '0 8 * * *'`) running on `[self-hosted, linux]`. Claude Code CLI is invoked headlessly via `claude -p`. Auth uses `CLAUDE_CODE_OAUTH_TOKEN` (Max subscription, zero marginal API cost per invocation). The `schedule` skill (CronCreate) is not used for this project.

**Consequences:**
- Phase 3 (this plan) designs the agent for headless invocability via `claude -p --output-format json`.
- Phase 4 writes `.github/workflows/scheduled-agents.yml`. That file is not in Phase 3 scope.
- No Anthropic-hosted cron billing -- the scheduled workflow runs on the self-hosted EC2 runner.
- `CLAUDE_CODE_OAUTH_TOKEN` must be stored as a GitHub Actions repository secret. Setup walkthrough added to `CLAUDE.md`.

**Reverses:** Parent plan D15 (Anthropic-hosted `schedule` skill as cron mechanism).
**Closes Open Questions:** Q9 (GitHub credentials in GH Actions = `GITHUB_TOKEN` auto-injected by platform).
**Remaining Open Questions:** Q6, Q7, Q8, Q10 (deferred to Phases 4-5).
**Related:** Decision 68 (Self-hosted EC2 runner), `docs/plans/PLAN-cc-scheduled-agents.md`

---

## Decision 70: Physical Deletion of Bootstrap Records from ops_recommendations

**Status:** Decided
**Date:** 2026-05-09

**Problem:**
Five hollow bootstrap records (rec-608, rec-633, rec-001, rec-002, and one null-id record)
existed in the `ops_recommendations` Iceberg base table. These records were written via the
now-closed `append_jsonl -> s3_log_store` path before PR #304 closed the direct write bypass.
They had empty or null `status`, `title`, `source`, `effort`, and `priority` fields. Because
`update_rec` validates the `status` field against a Pydantic `Literal` type, passing a null or
empty `status` raises `ValidationError` before any write is attempted -- making `update_rec`
(the normal lifecycle closure path) non-viable for these records. The records fired
`HARD_GATE` on every DQ run since they appeared in `ops_recommendations_current`.

**Decision:**
Physically deleted all five records from Iceberg on 2026-05-09 via the three-step protocol:
`DELETE FROM trading_formulas_db.ops_recommendations WHERE <predicate>`, followed by
`OPTIMIZE ... REWRITE DATA USING BIN_PACK`, followed by `VACUUM`. Tombstone entries for
rec-608 and rec-633 removed from `dq_tombstones.yaml` (physical deletion supersedes the
tombstone check).

**Decision NOT to add a general-purpose `delete_rec` function to `ops_data_portal`:**
The portal's role is lifecycle management, not destruction. Physical deletion must remain
exceptional and deliberate -- the DQ enforcement ratchet and the `append_jsonl` bypass
closure are the prevention mechanisms. `_delete_postmortems_from_iceberg` remains private
for its narrow use case. Adding a public `delete_rec` would create a routine destructive
path where none is warranted.

**Rationale:**
Records with null/empty `status` cannot be closed via `update_rec` without either patching
the record's `status` first (which requires a write -- the same problem) or loosening the
Pydantic model (which degrades validation for all callers). Physical DELETE is the only
viable path for invalid bootstrap records that bypassed validation at insertion time.

**Related:** Decision 69 (ops pipeline consolidation), Decision 51 (local-first outbox)

---

## Decision 69: Ops Pipeline Consolidation -- Single-Portal Invariant Enforced at Primitive Level

**Status:** Decided
**Date:** 2026-05-09

**Problem:**
Five-CLI choreography (`update_rec`, `sync_ops drain`, `ops_writer --compact`, `ops_writer --refresh-views`, `sync_ops pull`) leaked internal pipeline layers to agents, enabling silent-failure composition. Root-cause analysis in `docs/INTENT-ops-pipeline-consolidation.md`. Three architectural failures composed into the 2026-05-09 incident: (1) `update_rec` read the existing record from JSONL (destructible cache) rather than from Athena (source of truth); (2) `OpsWriter.compact` swallowed credential errors as `return 0`, making failure indistinguishable from "no staging files"; (3) `sync_ops pull` overwrote the local cache destructively, silently discarding uncommitted writes.

**Decision:**
Three architectural fixes, enforced at the primitive level:
1. `update_rec` reads existing record from Athena `ops_recommendations_current` (source of truth). Raises `RuntimeError` if Athena is unreachable; write path retains outbox for offline resilience.
2. `OpsWriter.compact` raises `RuntimeError` on infrastructure failures (credential errors, network errors, schema mismatches). Returns `int` only for the "no staging files" success case.
3. `ops_data_portal.sync()` is the single flush primitive -- compacts, refreshes views, pulls local cache. Agents call this instead of managing the pipeline steps.
CLI hard-removal (`--drain` from ops_data_portal, `drain` and `pull` from sync_ops) enforces the boundary at the build level. `sync_ops.pull` renamed to `_rebuild_local_cache` (private) with a staging-file guard that refuses to run when unstaged writes exist.

**Rationale:**
Silent failures compose multiplicatively. Each individual silent-failure was benign in isolation; together they produced partial-record Iceberg writes that went undetected until the DQ runner ran. The fix must be at the primitive layer, not just in documentation or wrapper scripts.

**Related:** Decision 50 (Iceberg ops data store), Decision 51 (local-first outbox), Decision 57 (SSO recovery), Decision 67 (Lambda deployment deferred)

---

## Decision 55: RCA-First Autonomous Executor Architecture (Supersedes Decision 46)

**Status:** Decided
**Date:** 2026-04-28

**Problem:**
The rescue agent architecture (Decision 46) introduces a correction layer that hides executor infrastructure gaps. When the executor hits an unrecoverable failure, rescue agents attempt autonomous repair — but LLM-powered "judgement" recovery compounds failures by automating workarounds rather than fixing the root cause permanently. The rec-449 transcript demonstrates this concretely: a V3 misclassification in `planning.prompt.md` caused an unresolvable critique cycling deadlock; the supervisor's instinct was `--skip-critique` (workaround) rather than diagnosing and fixing the underlying prompt rule. Recovery agents would have automated the same workaround, locking in the gap indefinitely.

**Decision:**
Replace the rescue agent layer (Decision 46) with an RCA-first model. When the executor hits an unrecoverable failure, the correct response is:

1. **Stop cleanly** — emit a structured `process_event` record with `tier=exception` and the failure context.
2. **Invoke an RCA agent** — the agent diagnoses root cause and files a recommendation to fix the gap permanently.
3. **Do not attempt repair** — no rescue agents, no workaround automation.

**Deterministic recovery remains valid.** Pattern-matched recovery for well-understood failure classes (git retry, ruff auto-fix, CLI timeout retry) continues unchanged. The removal applies only to LLM-powered "judgement" recovery decisions.

**Key points:**
- Each failure class is diagnosed once and fixed by a rec, so improvements compound permanently.
- The executor is cheaper and simpler to reason about without a rescue dispatch layer.
- The three-outcome contract (RESOLVED/CANNOT_RESOLVE/TIMEOUT), graduated autonomy gates, and recursive rescue prevention (Decision 46) are replaced by a simpler model: stop cleanly, diagnose, file rec.
- `scripts/executor/rescue.py` (planned but not yet written) is cancelled.
- The SRE blameless postmortem pattern applied to autonomous systems: failures are learning signals, not emergencies to paper over.

**Rationale:**
- One correct fix costs one diagnosis call. N recovery attempts cost N×K LLM calls and may still fail.
- Supervisor hiding (workaround routing) decreases long-term reliability by preventing gap accumulation from becoming visible.
- Structured process events + RCA agent creates a queryable audit trail in Athena that rescue agents do not provide.
- Decision 46 was premature: the executor was not yet reliable enough to trust rescue agents, and the trust calibration mechanism (graduated autonomy gates) was complex and untested.

**Supersedes:** Decision 46 (Rescue Agent Architecture). The three-outcome contract and graduated autonomy gates are retired.

**Related:** Decision 34 (state machine exit paths), Decision 46 (superseded), Decision 51 (outbox pattern for structured process events)

---

## Decision 56: SCD Type 2 Schema Simplification for Ops Tables (Decided)

**Status:** Decided
**Date:** 2026-04-30

**Problem:**
The ops Iceberg tables (ops_recommendations, ops_session_log, ops_execution_plans, ops_decisions, ops_priority_queue) had a proliferation of confusing date/timestamp columns: `ingested_at` (pipeline ingestion time), `trade_date` (partition key derived from ingest date, misnamed since these are ops records not trades), and `date`/`string` columns on some tables (creation date for recs, session date). This caused three problems:
1. Callers had to know which timestamp field to use for SCD2 ordering (`ingested_at`) vs querying (`date`).
2. Views explicitly listed all columns, drifting from the underlying tables whenever new columns were added.
3. `trade_date` as a partition key is semantically wrong for operational metadata.

**Decision:**
Replace the old timestamp/partition scheme with clear SCD Type 2 semantics:
- **`created_timestamp timestamp`** — when the record was first created (maps from the caller's `date` field for recs/sessions, or from `ingested_at` for tables without a creation date field).
- **`last_updated_timestamp timestamp`** — when this specific version was written (replaces `ingested_at` as the SCD2 ordering column).
- **Partition by `day(last_updated_timestamp)`** — uses Iceberg partition transforms (spec v2), semantically correct (partition by when the version was last updated).
- **Remove `date`/`trade_date`** columns entirely from all 5 ops tables.
- **Views use `SELECT *`** with `ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY last_updated_timestamp DESC)` — prevents view-table drift on schema evolution.
- **`ops_priority_queue_current`** retains its correlated-subquery pattern (returns all entries from the latest curator run, not one row per entity).
- **Callers are NOT modified** — the write path maps the incoming `date` field from callers (ops_data_portal etc.) to `created_timestamp` transparently.

**Rationale:**
- Single developer context makes `SELECT *` in views acceptable (no risk of exposing unexpected columns to unknown consumers).
- `last_updated_timestamp` is a universally understood SCD2 version key; `ingested_at` implies pipeline-specific semantics.
- Partition transform `day(last_updated_timestamp)` is correct Iceberg v2 syntax; `trade_date` as a plain column partition was a leftover from the market_data table pattern.
- `created_timestamp` makes the creation date queryable as a proper timestamp (timezone-aware), replacing `date string` which required string-to-date parsing.

**Supersedes:** Timestamp and partition aspects of Decision 50. Decision 50 core (append-only Iceberg, ROW_NUMBER views, local-first dual write) remains in effect.

**Related:** Decision 50 (Iceberg ops data store), Decision 51 (local-first outbox)

---

## Decision 57: Autonomous Improvement Control Plane as Umbrella Architecture (Decided)

**Status:** Decided
**Date:** 2026-05-01

**Problem:**
The repository has several strong self-improvement components: telemetry schemas, process events, recommendations, executor automation, scheduled agents, verification intent, and interactive workflows. Without an umbrella architecture, these components can evolve independently and leave the recursive self-improvement loop open at the most important transitions: telemetry analysis, RCA writeback, recommendation prioritisation, and proof that a fix reduced the failure mode that caused it.

**Decision:**
Create `docs/INTENT-autonomous-improvement-control-plane.md` as the umbrella intent document for the recursive self-improvement loop. Existing subsystem intent documents remain authoritative for their domains:
- `docs/INTENT-telemetry-system.md` for telemetry schema and process events
- `docs/INTENT-verification-system.md` for programmatic verification and causal-chain checks
- `docs/INTENT-recommendation-executor.md` for executor lifecycle and boundaries
- `docs/contracts/instruction-architecture.md` for instruction layering

The control-plane intent defines the target loop: execution -> telemetry -> verifier results -> process events -> failure packets or anomaly clusters -> RCA -> portal-filed recommendations -> priority queue -> executor or interactive implementation -> verification -> telemetry delta.

**Rationale:**
The architecture review concluded that the design is unusually mature for a sole-developer system, but not fully closed operationally. The missing capability is not another isolated prompt or script; it is an explicit control-plane model that sequences telemetry trust, verification, executor RCA, workflow migration, state-machine events, and recommendation governance.

**Related:** Decision 48 (verification tier), Decision 51 (local-first outbox), Decision 55 (RCA-first executor), `docs/INTENT-autonomous-improvement-control-plane.md`

---

## Decision 58: `.agents` as Canonical Interactive Workflow Layer (Decided)

**Status:** Decided
**Date:** 2026-05-01

**Problem:**
The migration from VS Code to Antigravity created multiple workflow sources: `.github/prompts/` and `.github/agents/` for legacy VS Code, `.agents/workflows/` and `.agents/skills/` for the intended Antigravity split, and `.antigravity/workflows/` as an additional transitional workflow set. Multiple active sources increase drift risk and make it unclear which instructions agents should follow.

**Decision:**
`.agents/workflows/` and `.agents/skills/` are the canonical interactive workflow layer. `.github/prompts/` and `.github/agents/` are legacy VS Code compatibility artefacts. `.antigravity/workflows/` should either be removed or reduced to shims that delegate to `.agents` once Antigravity consumption semantics are confirmed.

Interactive workflows should be thin orchestration files. Deep methodology belongs in `.agents/skills/`. Deterministic gates belong in scripts. Operational writes belong in portals.

**Rationale:**
The migration is an opportunity to improve the workflow architecture rather than port large VS Code prompts verbatim. The split into workflows and skills matches `docs/contracts/instruction-architecture.md`, reduces context bloat, and gives the system one canonical place to evolve interactive behavior.

**Related:** `docs/contracts/instruction-architecture.md`, `docs/INTENT-autonomous-improvement-control-plane.md`

---

## Decision 59: Retrospective and Step Validation Move to Telemetry and State Machine (Decided)

**Status:** Decided
**Date:** 2026-05-01

**Problem:**
Legacy VS Code workflows used subagents such as step-validator, scope-guard, retro-lite, and retrospective to compensate for missing structured execution state and process telemetry. Migrating these subagents as-is would preserve chat-based supervision rather than advancing the target architecture.

**Decision:**
Do not migrate retrospective, retro-lite, step-validator, or scope-guard as LLM subagents by default. Their responsibilities move to deterministic mechanisms:
- Step validation becomes execution state plus acceptance and verifier results.
- Scope guard becomes a deterministic diff-vs-plan check.
- Retro-lite becomes structured `telemetry_process_events`.
- Retrospective becomes scheduled telemetry analysis, decision governance, and recommendation generation.

The concerns are still required; only the legacy LLM-agent implementation is retired. Temporary compatibility shims are allowed during migration, but new investment should target deterministic checks, process events, verifier results, and state-machine transitions.

**Rationale:**
LLM subagents are useful for judgement and RCA, but step completion, scope drift, verifier status, retry count, and session summaries are state-machine facts. Encoding those facts in telemetry makes the system queryable, auditable, and eligible for autonomous trend analysis. Recreating the old subagent model would add cost and preserve the failure mode where agents reconstruct what happened from chat rather than reading structured evidence.

**Related:** Decision 55 (RCA-first executor), `docs/INTENT-telemetry-system.md`, `docs/INTENT-verification-system.md`, `docs/INTENT-autonomous-improvement-control-plane.md`

---

## Decision 60: Two-tier validation architecture: presubmit (default) + edit-loop (`--pre`) (Decided)

**Status:** Decided
**Date:** 2026-05-05
**Amended:** 2026-05-09 (PLAN-validate-two-tier): edit-loop flag renamed `--quick` -> `--pre` by explicit user instruction during planning session. No semantic change to tier behaviour; the rename improves clarity by aligning the flag name with its position in the workflow (pre-commit edit-loop).

**Problem:**
`scripts/validate.py` has accumulated five execution surfaces (`--scope auto|all|python|terraform|docs|prompts`, `--integration`, `--ci`, `--quick`, `--verifiers`) plus advisory flags. Autonomous executors and human/agent implementations frequently call the wrong flag (e.g., `--quick` when integration was needed). Wall-clock budgets are implicit. The local `--ci` and the GitHub Actions workflow drift silently when checks are added to one path and not the other -- exactly the failure mode `validate.py` was created to prevent. The four-flag world is structurally hostile to bounded-execution autonomous agents.

**Decision:**
Migrate the surface to two named tiers:

- **Presubmit (default, no flag):** Runs the full python check suite, terraform checks, dependency health, prompt validation, V3 verifiers (when AWS available), and DQ runner auto-invoke when stale. Time budget: <= 5 minutes total. Called once per branch before merge by the developer or by the self-hosted CI runner.
- **Edit-loop (`--pre`):** Lint, format, prompt validation, copilot multipliers validation. Nothing that touches AWS, nothing that runs pytest. Time budget: <= 30 seconds. Called per-step during implementation.

`--scope`, `--ci`, `--integration`, and `--verifiers` are deleted in the consolidation step. `--coverage` is retained as an advisory and remains exit-0 unconditional.

**Substrate:** A self-hosted GitHub Actions runner on EC2 with the same SSO configuration as the developer machine. Branch protection on `main` requires the workflow to pass; the workflow calls `python -m scripts.validate` with no flags. Zero billed minutes for the default tier. Reversible in 30 seconds.

**Migration sequence (each step reversible):**
1. [DONE] Land the architectural anchor (`docs/INTENT-validation-architecture.md`) and this Decision Record.
2. [DONE] Wire DQ runner auto-invoke into `--integration` (closes Gap 2 of the audit; this plan).
3. [DONE] Stand up the self-hosted EC2 runner with SSO substrate (PR #310, Decision 68).
4. [DONE] Freeze `--pre` surface with parity tests. (`--quick` renamed to `--pre`; PLAN-validate-two-tier, 2026-05-09.)
5. [DONE] Consolidate flags: deleted `--scope`, `--ci`, `--integration`, `--verifiers`. CI workflow calls `python -m scripts.validate` with no flags. (PLAN-validate-two-tier, 2026-05-09.)
6. Add scheduled postsubmit health checks (Wave 4b of `INTENT-verification-system.md`).
7. Delete the migration-sequence section of the INTENT doc once convergence is real.

**Rationale:**
- *Agent-first.* Autonomous agents cannot reason about wall-clock budgets when the surface they call has no commitment to one. Two named tiers with explicit budgets remove the "which flag should I use" judgement call.
- *No silent fallbacks.* SSO-unavailable cases skip with actionable guidance (Decision 57); they never crash and never silently weaken the gate.
- *Substrate matters.* Without a cheap, deterministic CI substrate, "default tier on every PR" is unaffordable and consolidation is impossible. Self-hosted runner solves the cost problem without reintroducing the discretion problem of local-only validation.
- *Reversible by design.* The migration is a multi-step ratchet; each step can be halted or rolled back. The convergence (deletion of legacy flags) is the moment the architecture is real.

**Related:** Decision 48 (Verification Tier Design), Decision 51 (Local-First Outbox), Decision 55 (RCA-First Executor -- no rescue agents), Decision 57 (Interactive vs Autonomous SSO recovery), `docs/INTENT-validation-architecture.md`, `docs/INTENT-verification-system.md`, `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` (Gap 2; Future Direction).

---

## Decision 61: Scheduled-agent findings flow through ops_recommendations via the source field (Decided)

**Status:** Decided
**Date:** 2026-05-05

**Problem:**
The cc-scheduled-agents strategic plan (PLAN-cc-scheduled-agents.md) originally proposed a new `ops_agent_findings` Iceberg table and a new `ops_priority_queue_latest_run` Athena view to ingest structured findings from Claude Code scheduled agents. The plan was written before a full audit of existing infrastructure. Open Questions Q4 ("New table OR extend ops_recommendations?") and Q5 ("Does the new view risk the same _rn ambiguity?") were unresolved at planning time.

**Decision:**
Scheduled-agent findings flow through the existing `ops_recommendations` table via the `source` field. No new Iceberg table is created. No new Athena view is created.

Specific consequences:
- The `ops_agent_findings` Iceberg table proposed in the strategic plan is NOT built. The existing `source` field on `ops_recommendations` discriminates findings by origin.
- The `ops_priority_queue_latest_run` view proposed in the strategic plan is NOT built. The existing `ops_priority_queue_current` view (terraform/iceberg_tables.tf:1042-1051) already implements the latest-run-by-queue_run_id semantic via a correlated subquery, not ROW_NUMBER(), sidestepping the _rn ambiguity in `ops_recommendations_current`.
- The findings-processor Lambda will be retired in Phase 5 of the cc-scheduled-agents migration. Retirement is recorded here; the action is deferred.
- Ingestion of scheduled-agent findings is through `ops_data_portal.enqueue_findings(path)`, which routes entries through the existing offline-resilient outbox and drain cycle.

**Rationale:**
- The existing `source` field already discriminates record origins (used today for "executor-postmortem", "planning", etc.). No schema migration needed.
- The existing outbox drain cycle (Decision 51) is already offline-resilient. A second ingestion path would duplicate the reliability mechanism.
- The existing `ops_priority_queue_current` view avoids the `_rn` ambiguity bug present in `ops_recommendations_current`. Building a second identical view under a different name adds maintenance burden with no benefit.
- One fewer Iceberg table and one fewer view to keep in sync with the Terraform + OpsWriter dual-definition pattern.

**Closes Open Questions:** Q4 (New table OR extend? - extend via source field), Q5 (New view risk _rn ambiguity? - no new view needed).
**Deferred:** Q3, Q6, Q7, Q8, Q9, Q10 to Phases 2-5 per the strategic plan manifest.

**Related:** `docs/plans/PLAN-cc-scheduled-agents.md` (strategic plan), `docs/plans/PLAN-cc-scheduled-agents-phase-1.md` (this implementation), Decision 51 (Local-First Outbox), Decision 50 (Iceberg ops data store)

---

## Decision 72: GitHub Branch Protection Not Available -- CI Enforcement as the Only Merge Gate (Decided)

**Status:** Decided
**Date:** 2026-05-09

**Problem:**
PLAN-validate-two-tier required enabling `required_status_checks` branch protection on `main` (validate-python + terraform-validate) as the enforcement mechanism for the two-tier validation model. The GitHub REST API (`PUT /branches/main/protection`) returns HTTP 403 on private repositories under the free GitHub plan. The repository will remain on the free plan; upgrading to GitHub Pro is not planned.

**Decision:**
GitHub branch protection is permanently unavailable for this repository. The merge gate is enforced by convention and tooling rather than by GitHub API:

1. **Local pre-merge gate:** `python -m scripts.validate` (the default presubmit tier) must exit 0 before any PR is opened. This is the primary gate. The CLAUDE.md merge protocol documents it as mandatory.
2. **CI as a signal, not a lock:** The self-hosted runner runs `python -m scripts.validate` on every PR push. A failing CI job is a hard stop; the developer or agent must not merge a PR with a red CI status. This is enforced by convention rather than by GitHub API.
3. **Never-on-main hook:** The `.claude/hooks/never_on_main.py` pre-tool-use hook prevents direct file edits and commits on `main` within Claude Code sessions. This guards against the most common accidental-merge pattern.
4. **No squash-bypass:** All merges must be squash merges via `gh pr merge --squash` after CI passes. Direct `git push` to `main` is blocked only by the never-on-main hook; human discipline is required outside Claude Code sessions.

**Consequences:**
- Acceptance criterion "Main branch protection enabled" from PLAN-validate-two-tier cannot be met. Superseded by this decision.
- VP steps 9 and 10 from PLAN-validate-two-tier are permanently BLOCKED; they are retired here without resolution.
- Any future migration to GitHub Pro or a public repository would unlock `required_status_checks` and should be revisited at that point.

**Related:** Decision 60 (Two-tier validation architecture), Decision 68 (Self-hosted EC2 runner), PLAN-validate-two-tier.

---

## Decision 68: Self-Hosted EC2 Runner as Canonical CI Execution Environment (Decided)

**Status:** Decided
**Date:** 2026-05-08

**Problem:**
2000 min/month free tier exhausted at current PR velocity; branch protection disabled as workaround; cc-scheduled-agents Phase 4 blocked by per-run GitHub Actions billing (~23 CI minutes per agent PR).

**Decision:**
EC2 self-hosted runner (`t3.medium`, Ubuntu 22.04, `eu-west-2`) is the canonical CI execution environment. IAM instance role with `Ec2InstanceMetadata` credential delegation replaces the SSO profile requirement in CI. Cold-start only for Phase 1 (full checkout + pip install per job).

Note: initially planned as `t3.small` (2 GB RAM) but upgraded to `t3.medium` (4 GB RAM) during initial deployment after mypy exhausted available memory and OOM-killed the runner process mid-job. The 2 GB headroom on `t3.medium` accommodates mypy + pytest + runner process without swap pressure.

Warm runner is a named future phase requiring its own risk assessment: (a) hash-gate the venv against `requirements.txt` on every job pickup to prevent stale-dependency false-greens, (b) workspace reset on branch switch, (c) concurrency-safe workspace locking. Do not implement without this plan.

SCD data transfer boundary: code execution moves to the project's EC2 instance. AWS credentials never leave the instance (instance metadata; no env var injection into GitHub). Job logs stream to GitHub's log storage -- equivalent posture to GitHub-hosted runners. Tests must never print classified data values (symbol lists, strategy names) to keep log content non-classified.

**Consequences:**
- Branch protection (`required_status_checks`) can be re-enabled on `main` after a 1-week runner stability observation window.
- cc-scheduled-agents Phase 4 (daily cron auto-merge PRs) is unblocked.
- Zero billed CI minutes for all branch builds and scheduled agent merges.

**Related:** Decision 36 (AWS Auth -- no IAM users, no OIDC), Decision 37 (Lambda scheduled agents), Decision 60 (Two-tier validation architecture), `terraform/ec2_runner.tf`, `CLAUDE.md` runner ops runbook.

---

## Decision 67: Lambda Deployment and STRATEGIC Plan Execution Deferred Pending Telemetry Readiness (Active - Temporary)

**Status:** Active -- remove when reversal condition is met
**Reversal condition:** Telemetry Athena tables (`telemetry_sessions`, `telemetry_process_events`,
`telemetry_model_calls`, `telemetry_phases`, `telemetry_steps`) confirmed operational end-to-end
with passing data quality checks AND Lambda dispatcher re-enabled per the CLAUDE.md runbook.

**Effect on planning:**
- STRATEGIC plans are blocked. All plans must be IMPLEMENTATION type.
- Plans touching Lambda-packaged files must include a
  `DEFERRED: build_lambda.py --deploy + run_scheduled_agent.py --smoke-test
  (pending Decision 67 reversal)` step instead of active deployment steps.

**Effect on plan-critique:** Step 12b accepts the DEFERRED marker pattern rather than
recommending REVISE. Outputs a WARN noting the deferred deployment debt. Step 12d blocks
STRATEGIC plans while this decision is active.

**Rationale:** The executor telemetry pipeline (telemetry_sessions etc.) is not yet confirmed
operational. Running executor-mediated recs risks silent telemetry loss. Lambda dispatcher
is separately disabled pending telemetry confirmation and scheduled-agent migration completion.
Both gates reverse together.

---

## Decision 66: Precision Context Injection as Agent-First Design Principle (Decided)

**Status:** Decided
**Date:** 2026-05-08

**Problem:**
Agents composing fields that require LLM judgment (title, context, acceptance) frequently
produce thin or structurally-valid-but-semantically-empty values when they lack field
semantics in their context window. Storing semantics in ops.yaml (per Decision 65) solves
the documentation problem but not the runtime problem: an agent that never loaded ops.yaml
has no basis for producing a high-quality value.

**Decision:**
In an agent-first repository, the authoritative field semantics must be surfaced at the
moment the agent *composes* the value -- not stored passively in config, and not injected
as a post-rejection error message. Pre-composition context injection is categorically more
effective for LLM agents than post-failure correction: the agent self-evaluates against the
spec before writing rather than re-attempting after rejection.

The canonical implementation pattern is `get_rec_write_guidance()` (Wave 2 deliverable in
ops_data_portal): called before `file_rec()`, it returns the `semantics` text for each
LLM-judgment field from ops.yaml, forcing the spec into the agent's context before value
composition. Any portal function that writes agent-authored content must expose its semantic
contract proactively via this pattern.

This principle applies at all 5 instruction layers (docs/contracts/instruction-architecture.md).
The pattern generalises beyond ops_data_portal: any write gateway for agent-authored content
should expose field semantics before accepting a write, not only after rejecting one.

**Semantic Enforcement Architecture (Wave 2 addendum -- 2026-05-10):**

Formalised four enforcement tiers, each catching a different class of quality failure:

- **Tier A -- Pre-write injection:** `get_rec_write_guidance()` surfaces ops.yaml
  `description` + `semantics` + source registry to the agent before composition. Agents
  that call this before `file_rec()` self-evaluate against the spec and produce higher-quality
  values without being rejected. Auto-populated from ops.yaml column entries; no code change
  to `rec_write_guidance.py` required when new fields are added to ops.yaml.

- **Tier B -- Write-time deterministic rejection:** `file_rec()` validators enforce structural
  rules that are always correct regardless of repository state: path format (`_validate_file_path`),
  context length (`_validate_context_length` -- 80-char minimum), banned acceptance patterns
  (`lint_acceptance_command`), source registry membership (`validate_source`), and formula-derived
  fields (`automatable` from `compute_automatable`, `risk` from `compute_risk`). Validators are
  in `scripts/ops_data_portal.py`. Agents cannot override `automatable` or `risk` directly;
  the portal derives them from `config/executor_capabilities.yaml`.

- **Tier C -- Execution-time feasibility:** `validate_acceptance_feasibility()` in
  `scripts/executor/acceptance_lint.py` runs at executor invocation time, not write time.
  File existence and module availability checks are intentionally deferred here -- the target
  file may not exist until the executor creates it, so existence is context-dependent.

- **Tier D -- LLM semantic judge:** Not yet implemented. Intended to detect acceptance commands
  that are syntactically valid but semantically incorrect (e.g., grep for the wrong pattern,
  pytest for the wrong test class). Filed as a recommendation for a future session.

---

## Decision 65: ops.yaml Extended Contract is the Canonical Field Semantic Authority (Decided)

`config/data_quality/ops.yaml` (and `telemetry.yaml`) is the canonical field contract for
all DQ-governed tables. The `description` and `semantics` metadata fields within each column
entry define the field's semantic contract -- consumed by agents, ignored by the DQ runner.
This supersedes the separate human-readable briefing doc pattern (e.g.,
`docs/dq/ops-recommendations-remediation-briefing.md`). Do not create new briefing docs for
new tables. Add field context as `description` + `semantics` in the YAML directly. The briefing
doc for ops_recommendations is a legacy artefact; it is not maintained going forward. The
decision manifest YAML (`config/data_quality/decisions/{table}.yaml`) remains the remediation
state authority.

## Decision 64: Bootstrap Cohort Anchor for ops_recommendations is 2026-05-01 (Decided)

The bootstrap cohort for ops_recommendations consists of all records created before 2026-05-01
(the date the enforcement regime was established via Phase 3 ratchet PR #296 and formalised in
`docs/dq/DQ_REMEDIATION_METHODOLOGY.md`). All Class B (bootstrap artifact) temporal gates for
this table use `exclude_before: '2026-05-01'`. This anchor is fixed and must not be changed
retroactively. Bootstrap records are not corrupt -- they predate the rules. They age out of the
_current view as recommendations are closed or superseded.

## Decision 63: Execution Fields Excluded from ops_recommendations DQ Scope (Decided)

Execution fields (`execution_result`, `execution_date`, `execution_branch`, `execution_pr_url`,
`execution_steps`) are excluded from Phase 4 DQ remediation scope for ops_recommendations.
These fields record how a recommendation was executed, not its lifecycle state -- they are
telemetry, not ops state. They belong in `ops_execution_plans` or the telemetry tables.
Denormalising execution state into ops_recommendations creates two sources of truth that can
drift (rec says success, execution plan says failed). DQ enforcement for these fields is
deferred until execution state is normalised to the appropriate table (pending telemetry
maturity). Phase 4 decision manifest: `phase4_session: wave-4-deferred` for all five fields.

---

## Decision 62: No Separate DQ Scheduled Routine (Session E Elimination) (Decided)

**Status:** Decided
**Date:** 2026-05-06

**Problem:**
The original DQ enforcement strategy proposed a Session E architecture: a Claude Code cron agent would trigger an EC2 runner, which would execute the DQ runner, commit the resulting `dq-latest.json` to a branch, and auto-merge it. This introduced a separate scheduling concern, an EC2 runner dependency, a dedicated auto-merge flow, and additional operational complexity -- all separate from the existing validate.py presubmit tier.

**Decision:**
The Session E architecture is eliminated. DQ runs as part of `validate.py`'s presubmit tier on the EC2 self-hosted runner, which has SSO credentials. The presubmit tier auto-invokes the DQ runner when `logs/debug/dq-latest.json` is stale (>1h). No scheduling concern separate from validation itself.

Specific consequences:
- No Claude Code cron agent for DQ refresh.
- No dedicated EC2 runner separate from the self-hosted CI runner.
- No `dq-latest.json` PR/auto-merge flow.
- `ensure_fresh_dq_results()` in `scripts/validate.py` handles the auto-invoke when stale.

**Rationale:**
The presubmit tier on the self-hosted EC2 runner already has SSO credentials and runs before every merge. Tying DQ refresh to the validation lifecycle means freshness is enforced at merge time without a separate operational layer. The Session E architecture adds scheduling complexity and a separate failure mode (cron agent not running) that the presubmit model eliminates entirely.

**Related:** Decision 57 (Autonomous Improvement Control Plane), Decision 60 (Two-tier validation architecture), `docs/INTENT-dq-enforcement.md` (Phase 3 Decision Registry), `docs/INTENT-validation-architecture.md`

---

## Decision 51: Local-First Outbox + Bidirectional Sync for Ops Data (Decided)

**Status:** Decided
**Date:** 2026-04-23

**Problem:** Agent sessions lose operational writes when SSO expires (`OpsWriter.write()`
silently no-ops) and start with stale local JSONL data because nothing pulls from Athena.
The self-improvement loop cannot function if the system cannot reliably read its own
history or persist new observations.

**Decision:** Adopt a local-first outbox pattern:
- **Writes:** All writes go through OpsWriter.write(). On S3 failure, entries are written
  to a local outbox (`logs/.ops-outbox/{table}/{uuid}.jsonl`).
- **Reads:** Agents always read local JSONL files. A `sync_ops.py` script pulls the latest
  state from Athena `_current` views and overwrites local files.
- **Sync:** `sync_ops.py` runs drain-then-pull. Integrated into preflight (session start),
  postflight (session end), and executor between-rec checkpoints (drain only).
- **Enforcement:** validate.py warns on stale outbox entries (> 24h).

**Rationale:** Deterministic local reads (no network dependency for reads), no data loss
on SSO expiry (outbox persists until drain succeeds), idempotent flush (Iceberg deduplicates
via ingested_at), and structurally-enforced freshness via hooks in every session lifecycle phase.
Between-rec hooks call drain() only (not full sync()) to avoid 5x Athena query cost per rec.

**Supersedes:** Nothing -- additive layer on top of Decision 50.
**Related:** Decision 50 (Iceberg ops data store), `docs/contracts/ops-data-store.md`

---

## Decision 50: Append-Only Ops Data Store via Iceberg (Decided)

**Decision:** All operational structured logs (recommendations, execution plans, session telemetry,
decisions, priority queue) are stored as append-only Iceberg tables in Athena. Current state is exposed
via ROW_NUMBER() views. Parquet + gzip, partitioned by `trade_date`. Located in
`bblake-platform-agent-logs/iceberg/`. The `OpsWriter` class in `scripts/ops_writer.py` handles
staging uploads and Athena compaction. INSERT-only semantics (no MERGEs). Supersedes Decision 45.

**Problem:**
The dual-source JSONL+S3 pattern (Decision 45) causes: (1) merge conflicts on JSONL files when both
local and agent branches write concurrently, (2) no structured query capability -- recommendations
can only be analysed by parsing JSONL line by line, (3) no audit trail -- overwrite_jsonl() destroys
prior state, losing the history of priority queue runs and recommendation status changes, (4) schema
drift across write sites with no enforcement mechanism.

**Why append-only Iceberg over alternatives:**
- **Iceberg vs Delta Lake:** Iceberg is natively supported by Athena v3 (already provisioned). Delta
  Lake requires additional dependencies and a separate engine configuration.
- **Iceberg vs direct Athena INSERT:** Append-only Iceberg avoids MERGE complexity and matches the
  existing pattern of the `market_data` table. MERGE would require primary-key enforcement that Iceberg
  does not natively provide in Athena v3.
- **ROW_NUMBER() views vs MERGE:** Views are read-time deduplication -- zero write overhead, no
  locking, fully compatible with INSERT-only semantics. MERGE would require engine v3 MERGE DML
  which has higher failure risk and is slower.
- **Local JSONL retained in parallel:** Local JSONL files remain the source of truth for git-tracked
  artefacts and local development. OpsWriter write-through is best-effort and does not replace local
  writes. This allows gradual migration without breaking existing tooling.

**Write architecture:**
1. `s3_log_store.append_jsonl()` / `overwrite_jsonl()` complete their existing local/S3 writes
2. Write-through to `OpsWriter.write(table, entry)` staged at `staging/{table}/trade_date=.../batch-{uuid}.jsonl`
3. `session_postflight.run_auto()` calls `OpsWriter.compact_all()` at session close
4. `compact_all()` reads staging files, builds DataFrame, calls `awswrangler.athena.to_iceberg(mode="append")`
5. Views (`ops_*_current`) provide always-fresh current state via ROW_NUMBER() deduplication

**Constraints:**
- `awswrangler` is a Lambda-only dependency (via AWSSDKPandas layer). Local `compact()` gracefully
  returns 0 when `awswrangler` is unavailable.
- `OpsWriter` never raises exceptions to callers -- all failures are logged as warnings.
- `ops_decisions` has no automated write-through yet -- write site deferred to Phase 2.
- Local JSONL files continue to be written in parallel (no breaking change to existing tooling).

**Supersedes:** Decision 45 (S3 as Authoritative Source for Cloud-Produced Logs)

**Related:** Decision 48 (V3 Verification Tier), Decision 49 (Copilot SDK inference),
`docs/contracts/ops-data-store.md`

**Decision status:** Decided -- April 2026

---

## Decision 49: Copilot SDK as Lambda Inference Provider (Supersedes Decision 47)

**Decision:** The GitHub Copilot SDK (`github-copilot-sdk` v0.2.2) replaces AWS Bedrock as the inference provider for all Lambda-executed scheduled agents. Model IDs use Copilot SDK format (e.g., `claude-haiku-4.5`, `claude-sonnet-4.6`). Auth uses the existing Secrets Manager GitHub PAT.

**Problem:**
On April 2026, AWS Bedrock access was revoked in the sandbox account (REDACTED-ACCOUNT-ID) because the models were accepted without proper AI Steering Group approval. All 6 scheduled agents stopped functioning. The GitHub Models API (the previous fallback) lacks Claude and Gemini models -- only OpenAI, DeepSeek, and Grok models are available -- making it inadequate for quality-sensitive agents like rec-curator.

**Why Copilot SDK over alternatives:**
- **GitHub Models API:** No Claude, no Gemini. GPT-4.1-mini quality too low for rec-curator.
- **Bedrock (restored):** Would require AI Steering Group re-approval. Timeline unknown.
- **Copilot SDK:** Provides Claude Haiku 4.5 (0.33x multiplier), Sonnet 4.6 (1x), and other high-quality models. Uses existing GitHub PAT from Secrets Manager. Fits in Lambda zip (69 MB total). Confirmed working via live tests.

**SDK architecture:**
The SDK spawns a Copilot CLI subprocess via JSON-RPC. The CLI binary (~58 MB) is bundled in the pip wheel. Auth is via `SubprocessConfig(github_token=...)`. Sessions are created per-inference call with `tools=[]` to disable agent tool use.

**Model mapping:**
| Agent | Model | Multiplier |
|-------|-------|------------|
| doc-freshness, orphan-code, transcript-review, code-smell, prompt-quality | `claude-haiku-4.5` | 0.33x |
| rec-curator | `claude-sonnet-4.6` | 1x |

**Lambda packaging:**
SDK is pip-installed into `data-pipeline.zip` (not the deps layer) using `--platform manylinux_2_28_x86_64`. The CLI binary at `copilot/bin/copilot` must have executable permissions (0o755) in the zip. Total SDK footprint: ~69 MB (binary 58 MB + Python 1.2 MB + pydantic 9 MB + dateutil 0.6 MB).

**Constraints:**
- SDK is Public Preview (v0.2.2) -- pin version in `build_lambda.py` to prevent breakage
- `bedrock_client.py` is retained as dormant code -- available if Bedrock access is restored
- Lambda memory may need increase from 512 MB to 1024 MB if CLI subprocess causes OOM
- `_preload_rec_curator_context()` still required -- SDK `tools=[]` disables file reading

**Related:** Decision 47 (superseded), Decision 40 (Copilot SDK for executor -- still deferred, separate concern), Decision 48 (V3 verification tier), `docs/contracts/inference-provider.md`

**Decision status:** Decided -- April 2026

## Decision 48: Verification Tier Classification (Decided)

**Decision:** Every implementation plan must declare a Verification Tier (V1, V2, or V3) based on the files in scope. The tier determines the minimum verification standard the plan's Ordered Execution Steps must meet.

**Problem:**
The rec-curator pipeline (rec-448 through rec-451) shipped with passing acceptance criteria and 100% unit test coverage, but failed on first live invocation with 7 integration bugs. Root cause: acceptance commands verified file contents (V1/structural) or ran unit tests with mocked dependencies (V2), but no step required deploying and invoking the actual Lambda to verify end-to-end behaviour (V3). The existing Lambda Deployment Assessment (Step 5d, Decision 47) addresses Lambda-specific cases but does not generalise to other integration boundaries (e.g., cross-service contracts, S3 key agreements, API schemas).

**Tier Definitions:**

| Tier | Name | Scope Trigger | Minimum Verification |
|------|------|--------------|---------------------|
| V1 | Static | Files with no runtime effect: docs, prompts, configs, .md, .yaml (non-handler) | grep/file-existence acceptance; no pytest required |
| V2 | Unit | Pure Python logic: scripts/, src/ files with no external integration | pytest with 100% coverage (existing test_coverage_checker.py gate) |
| V3 | Integration | Files that interact with external systems: Lambda handlers (src/data/handlers/), schedule.yaml, Terraform, API contracts, cross-service data flows | Deploy + invoke + verify output. Iterative: if invocation reveals bugs, fix and re-invoke in the same session. Acceptance must be behavioural (invoke and check output), never structural (grep exists). |

**Classification Rules (deterministic):**
1. If ANY file in scope matches V3 triggers, the plan is V3 (highest tier wins)
2. If no V3 triggers but any file matches V2 triggers, the plan is V2
3. Otherwise V1

**V3 Scope Triggers (exhaustive list):**
- Files under src/data/handlers/
- .github/agents/schedule.yaml (deployed to Lambda)
- .github/prompts/scheduled/ (deployed to Lambda)
- terraform/*.tf files that create/modify resources with runtime effects
- Any file listed in _LAMBDA_SCRIPTS in scripts/build_lambda.py
- Any change that modifies a cross-service contract (S3 key paths, JSONL schemas consumed by another service, API response formats)

**V3 Ordered Execution Step Requirements:**
1. Deploy step: build and deploy the artifact (e.g., python -m scripts.build_lambda --deploy)
2. Invoke step: trigger the deployed artifact and capture output (e.g., --trigger-lambda NAME, aws lambda invoke)
3. Verify step: check the output matches expectations (e.g., parse S3 output, verify status code)
4. Fix-and-retry: if invocation reveals bugs, fix the code, redeploy, and re-invoke in the same session until the output is correct
5. Acceptance command must be behavioural: it must invoke the system and verify output, not just grep for file contents

**What this does NOT include:**
- Automated tier detection script (future enhancement -- deterministic based on file paths, suitable for a Python script in scripts/)
- Changes to test_coverage_checker.py (V2 enforcement is already working; V3 is a different layer)

**Related:** Decision 43 (Directed Growth Governance), Decision 44 (Executor Boundary), Decision 47 (Lambda Deployment Assessment -- V3 subset)

**Limitation:** Verification tier classification is documentation-enforced only. No automated detection currently exists. A future rec should add a deterministic tier classifier to validate.py based on scope file paths, closing the enforcement gap that motivated this decision.

**Decision status:** Decided -- April 2026

## Decision 44: Executor Self-Modification Boundary (Decided)

**Decision:** The executor (`scripts/execute_recommendation.py` and its submodules) must not modify files within its own machinery boundary. Recommendations targeting boundary files must have `automatable: false` and be implemented via `/plan` -> `/implement`.

**Problem:**
The executor generates code via LLM calls to implement recommendations. When the target files ARE the executor itself (or its prompts, instructions, or tests), the system is modifying the code that controls its own behaviour. This creates:
- (a) **Silent behavioural regression risk** -- a bad edit to `step_runner.py` affects all future recs
- (b) **Unreliable failure diagnosis** -- the diagnostic tooling may itself be broken
- (c) **Untestable changes** -- executor tests run inside the executor, creating circular validation

**Boundary table:**

| File pattern | Route | Reason |
|---|---|---|
| `scripts/execute_recommendation.py` | `/plan` -> `/implement` | The orchestrator itself |
| `scripts/executor/*.py` | `/plan` -> `/implement` | Executor submodules |
| `config/agent/executor/prompts/*.prompt.md` | `/plan` -> `/implement` | Executor prompts |
| `.github/instructions/executor-*.instructions.md` | `/plan` -> `/implement` | Supervisor/executor instructions |
| `.github/prompts/develop-executor.prompt.md` | `/plan` -> `/implement` | Supervisor prompt |
| `scripts/copilot_wrapper.py` | `/plan` -> `/implement` | LLM interface layer |
| `tests/test_execute_recommendation.py` | `/plan` -> `/implement` | Executor test infrastructure |
| `tests/test_executor_*.py` | `/plan` -> `/implement` | Executor submodule tests |
| `tests/test_copilot_wrapper.py` | `/plan` -> `/implement` | LLM interface tests |
| Everything else | Executor (`automatable: true`) | Normal product code |

Path updated by T-1.7 (config split). Mechanism unchanged.

**Enforcement:**
1. `validate_executor_boundary()` in `validate.py` -- rejects open recs with boundary file + `automatable: true`
2. `copilot-instructions.md` Known Gotchas documents the rule for all agents
3. `select_next_batch()` in `execute_recommendation.py` already excludes `automatable: false` recs from batch selection

**Exceptions:** None. If an executor boundary file needs changing, it goes through `/plan` -> `/implement`. The human reviews the plan and the implementation directly. `--fast` mode is not available for boundary files.

**Related:** Decision 42 (Three-Tier Workflow Architecture), Decision 43 (Directed Growth Governance)

**Decision status:** Decided -- April 2026

---

## Decision 43: Directed Growth Governance (Decided)

**Decision:** Enforce structural size limits, tool tier taxonomy, and responsibility manifests across all repository code, prompts, and agents. Every enforcement gate supports explicit waivers with decision-id references so legitimate orchestrators are not blocked.

**Problem:**
The autonomous, recursive self-improvement loop modifies prompts, scripts, and agents. Without structural limits, files grow unbounded -- `execute_recommendation.py` reached 3177 SLOC, `validate.py` 1198 SLOC. Agent context windows are finite; monolith files degrade LLM execution quality. Tool sprawl in agent frontmatter makes reasoning about risk impossible.

**Structural limits:**

| Dimension | Limit | Waiver pattern |
|---|---|---|
| Python file SLOC | 500 non-blank, non-comment lines | `# complexity-waiver: <decision-id>` anywhere in file |
| Cyclomatic complexity | 20 branch nodes per function | Same waiver comment in file |
| `.prompt.md` file token budget | 3000 lines | `# complexity-waiver: <decision-id>` in frontmatter comment |
| `.agent.md` file token budget | 1500 lines | Same |
| Responsibilities per orchestrator | 2 max | `max_responsibilities: 2` in frontmatter |
| Responsibilities per reviewer/scheduled/subagent | 3 max | `max_responsibilities: 3` in frontmatter |

**Tool tier taxonomy (T0-T3):**

| Tier | Permitted tools | Risk level |
|---|---|---|
| T0 | read, search | Safest -- read-only |
| T1 | T0 + terminal read (getTerminalOutput) | Terminal observation |
| T2 | T1 + file-edit (replace_string_in_file, create_file) | Standard executor |
| T3 | T2 + runInTerminal write | Highest risk -- explicit justification required |

**Day-1 waivers:** The following existing over-limit files receive `# complexity-waiver: decision-43` annotations and are targeted for reduction via Area A extractions in `PLAN-infra-directed-growth.md`: `validate.py` (1198 SLOC), `step_runner.py` (1285), `postflight.py` (1216), `plan.py` (1073), `execute_recommendation.py` (3177).

**Enforcement:** `validate.py` hard gates (SLOC, cyclomatic complexity, token budget, tool tier) -- all implemented via `PLAN-infra-directed-growth.md`. Governance configuration in `config/agent_governance.yaml` and `config/agent_tool_tiers.yaml`.

**Related:** Decision 42 (Three-Tier Workflow Architecture), Decision 44 (Executor Self-Modification Boundary)

**Decision status:** Decided -- April 2026

---

## Decision 42: Three-Tier Workflow Architecture (Decided)

**Decision:** Separate the human-agent workflow into three tiers with distinct responsibilities: `/plan` (strategic), `/implement` (scoping), `/develop-executor` (autonomous execution). Non-automatable recommendations must be surfaced and discussed in `/plan`, not accumulated silently.

**Problem:**
- `/plan` was overloaded: produced strategic decisions AND detailed execution steps
- `/implement` followed execution steps but had no scoping authority
- Non-automatable recs accumulated without resolution path
- Executor defaulted to single-rec mode, leaving throughput on the table

**Architecture (three-tier):**
```
Human Intent
     |
     v
/plan (STRATEGIC)
  - Decisions + Work Areas
  - Mandatory non-automatable rec discussion
  - Output: PLAN-{slug}.md with Work Areas table
     |
     v
/implement (SCOPING)
  - Research each Work Area
  - Break into atomic recs (effort <= M)
  - Create briefing files for complex recs
  - Output: Populated recommendations log
     |
     v
/develop-executor (AUTONOMOUS)
  - Compound execution (3-4 recs, effort <= M total)
  - Files friction recs on failure
  - Output: Code changes + PR
     |
     v
Friction recs (automatable: false)
     |
     v
Back to /plan preflight (mandatory discussion)
```

**Key design principles:**
1. **Separation of concerns** -- each agent has one job, can be tuned independently
2. **No open loops** -- every friction point has a resolution path
3. **Non-automatable recs surface** -- preflight shows them, `/plan` must discuss before proceeding
4. **Compound execution default** -- executor picks 3-4 recs (effort <= M, max 4) unless overridden
5. **Stale rec detection** -- rec-curator flags `automatable: false` recs older than 30 days

**Compound execution bounds:**
- Effort weights: XS=0.5, S=1, M=2, L=4, XL=8
- Max total effort per compound batch: M (=2)
- Max recs per batch: 4
- Prefer same-file recs (reduces merge conflicts)
- Prefer recs with shared dependencies

**Trade-offs accepted:**
- `/plan` sessions may be longer due to mandatory non-automatable discussion
- Compound execution may have harder-to-attribute failures (mitigated by per-rec telemetry)

**Related:** Decision 38 (workflow consolidation), Decision 40 (Copilot SDK deferred)

**Decision status:** Decided -- April 2026

---

## Decision 40: Executor Platform Migration — Copilot SDK + Bedrock Planning (Decided, Deferred)

**Decision:** Migrate the executor's LLM interface from raw Copilot CLI subprocess calls to the GitHub Copilot SDK, and adopt AWS Bedrock as the planning backend via the SDK's BYOK (Bring Your Own Key) capability. Implementation is deferred until the Copilot SDK reaches stable/v1.0 or a trigger condition is met.

**Problem:**
The executor (`scripts/execute_recommendation.py`) invokes the Copilot CLI via `subprocess.Popen` through `copilot_wrapper.py`. This works but has known friction:
- ~2-5s subprocess startup overhead per call (no persistent server)
- Plan output is prose, parsed by regex (`parse_steps_from_plan`), causing ~30% parsing failures that trigger costly retries
- No prompt caching -- each call (plan, critique, refine) pays full context cost
- No structured output enforcement -- the model can return any format
- `_PLAN_EXCLUDED_TOOLS` is a workaround for agentic models treating `@file` context as implementation tasks
- Sequential rec processing is slow; parallelisation is blocked by the subprocess model

**Options considered:**
- **AWS Bedrock direct (boto3 `converse` API):** Provides structured JSON output via `outputConfig.textFormat.jsonSchema`, prompt caching via `cachePoint` blocks in system prompts (5min/1h TTL), and multi-turn conversation in a single API call. Available in eu-west-2 with Claude Opus/Sonnet/Haiku. However, Bedrock is text-in/text-out -- no file system access, no tool use for implementation. Would require maintaining two separate LLM interfaces (Bedrock for planning, Copilot CLI for implementation).
- **GitHub Copilot SDK (`github-copilot-sdk`, Python):** Released post-project-start, currently Public Preview (v0.2.2, 39 releases in 3 months). Replaces subprocess management with async JSON-RPC to a persistent CLI server. Provides session hooks (`on_pre_tool_use`, `on_post_tool_use`), custom tools, permission handling, and streaming. Crucially, supports BYOK with Anthropic provider type -- meaning Bedrock models can be accessed through the SDK, combining SDK session management with Bedrock's structured output and prompt caching. This eliminates the need for two separate interfaces.
- **Stay on raw Copilot CLI:** Current approach. Works, is resilient, self-monitoring. Slow but stable. Compound execution and acceptance pre-flight (rec-186) mitigate the worst friction points.

**Decision:**
Adopt a single migration path: Copilot SDK with Bedrock BYOK. Do not implement Bedrock directly (avoids maintaining two LLM interfaces). Do not migrate now (SDK is unstable, API surface volatile). The current CLI-based system is adequate for the current phase of the project.

**Cost analysis:** Opus via Copilot CLI has a 3x premium request multiplier. A plan+critique+refine cycle costs ~$0.36-0.90 in premium requests, comparable to Bedrock's ~$0.40 direct cost. Cost is not a driver for migration.

**Trigger conditions for implementation (any one):**
1. Copilot SDK reaches v1.0 or "stable" designation
2. Executor retry rate exceeds 40% sustained over 2 weeks (structured output would eliminate parsing failures)
3. Executor throughput becomes the bottleneck for North Star progress (i.e., Phase 2/3 are complete and rec velocity is the constraint)

**Three-phase incremental migration (when triggered):**
1. **P1: SDK adoption** -- Replace `copilot_wrapper.py` subprocess management with `CopilotClient` async context managers. Persistent server mode eliminates startup overhead. Session hooks replace `_PLAN_EXCLUDED_TOOLS` and `validate_response()`. Implementation stays on Copilot CLI tools.
2. **P2: Bedrock planning backend** -- Configure BYOK with Anthropic provider for planning calls. Structured JSON output via `outputConfig.jsonSchema` eliminates `parse_steps_from_plan` regex. Prompt caching for system prompt + repo conventions. Critique loop runs as multi-turn conversation with cached prefix.
3. **P3: Unified multi-rec planning** -- Bedrock planner receives rec clusters from rec-curator, produces single optimised plan with per-rec step tagging. Parallel planning via `asyncio` + SDK async sessions.

**Trade-offs accepted:**
- Deferring means continued ~30% plan parsing failure rate (mitigated by existing retry + escalation logic)
- Deferring means no prompt caching (mitigated by the CLI's `--resume` session reuse)
- Single migration path (SDK+BYOK) creates a dependency on GitHub shipping BYOK for Anthropic/Bedrock -- if this feature is dropped, fall back to direct Bedrock for planning only

**Related:** rec-186 (acceptance pre-flight), rec-184 (compound critique), Decision 39 (Step Functions orchestration)

**Decision status:** Decided, deferred -- April 2026

---

## Decision 41: Scalable Feature Architecture -- Three-Layer Data Pipeline (Decided)

**Decision:** Adopt a three-layer data architecture (Raw -> Encoder -> Discovery) that removes interpretability as a constraint, enables model-agnostic discovery, and ensures constant discovery cost regardless of raw feature count.

**Problem:**
The current Phase 2 schema design hardcodes ~35 native columns with specific deltas (delta_price_1d, zscore_rsi_30d, etc.). This approach has scaling limits:
1. Adding new data sources requires schema changes and explicit delta definitions
2. Discovery cost scales with feature count (PySR explores O(features x depth x population))
3. At 1,000+ features, discovery becomes the compute bottleneck, not storage
4. Implicit assumption that formulas must be human-interpretable limits model diversity

**Industry context:**
Top quantitative firms (Renaissance, Two Sigma, Citadel) do NOT require interpretability for trading signals. They optimize for returns, not explanation. Interpretability is a human need, not a system need. Regulatory requirements (MiFID II, SEC) apply to client-facing asset management, not proprietary trading.

**Architecture (three-layer):**

```
RAW LAYER (Athena/Iceberg, append-only, normalized)
  market_data_raw, sentiment_raw, fundamentals_raw, alt_data_raw
  - Universal transforms applied automatically (all windows x all numeric columns)
  - 1,000+ columns over time -- storage is cheap
            |
            v
ENCODER LAYER (VAE or Transformer, trained daily/weekly)
  Input: 1000+
  Output: 64-128 latent dims
            |
            v
DISCOVERY LAYER (model-agnostic)
  PySR (symbolic), LightGBM, Attention NN, Future models
            |
            v
UNIFIED EVAL (Sharpe, DD, win rate)
```

**Key design principles:**
1. **Interpretability is not a constraint** -- the system evaluates models by performance metrics (Sharpe, drawdown, win rate), not human understanding. SHAP/attention weights provide debugging capability without requiring interpretable formulas.
2. **Universal transforms** -- global config defines windows (1d, 3d, 7d, 14d, 30d) and transforms (pct_change, zscore, ema_diff, rank_percentile) applied to ALL numeric columns automatically.
3. **Encoder absorbs feature growth** -- adding 100 new raw features has zero marginal discovery cost; encoder compresses to fixed 64-128 latent dimensions.
4. **Model-agnostic discovery** -- PySR, LightGBM, neural networks, and future models all compete on the same evaluation metrics. No model type is privileged.
5. **Automated pruning** -- weekly job removes features with >95% correlation or zero usage in winning models over 8 weeks.

**Trade-offs accepted:**
- Latent dimensions are not directly interpretable (debugging via SHAP/attention instead)
- Encoder training adds compute cost:
  - Lambda path (CPU-only, 1000 features, 50 epochs): ~$0.05-0.15/day (15-min Lambda x2 at $0.0000166667/GB-s)
  - SageMaker path (ml.m5.xlarge, 4 vCPU, 16 GB RAM): ~$0.23/hr; a 1-hr training job = ~$0.23/day
  - Decision threshold: start with Lambda; switch to SageMaker when training exceeds 10 minutes
- Initial implementation requires new infrastructure (encoder training pipeline, attention layer)

**Implementation path:**
1. Add `config/features.yaml` with global transform config (rec-201)
2. Create `src/data/transform_engine.py` for universal transform generation (rec-202)
3. Create `src/models/encoder.py` for VAE/Transformer encoder (rec-203)
4. Create `src/models/attention.py` for supervised attention layer (rec-204)
5. Add `feature_vectors` Iceberg table (rec-205)
6. Update `src/lab/pysr_factory.py` to consume latent + attention-selected features (rec-206)
7. Add parallel discovery runners (LightGBM, neural attention) (rec-206)
8. Unified evaluation in `src/lab/model_evaluator.py` (Sharpe, DD, win rate) (rec-207)

**Related:** Phase 2 (schema flattening), Phase 3 (formula integration), Decision 40 (Copilot SDK migration deferred), rec-201 through rec-209

**Decision status:** Decided -- April 2026

---

## Decision 39: Workflow Orchestration — Step Functions over Airflow (Decided)

**Decision:** Use AWS Step Functions as the primary orchestrator for all mixed deterministic + LLM workflows. Do not adopt Apache Airflow (open-source or MWAA).

**Problem:**
As more scheduled tasks and LLM agents are added, they will increasingly need to interoperate: a deterministic data fetch feeds an LLM analysis, whose output conditionally triggers another deterministic step. A suitable orchestrator must handle scheduling, dependency chaining, retries, and branching — and must work within the project's constraints (no Docker on company VM, cost-sensitive, AWS-native).

**Options considered:**
- **Apache Airflow (self-hosted):** Open-source and free, but requires Docker for the scheduler and workers — not runnable on company VM. Strong DAG tooling but highest operational burden; overkill below ~100 DAGs.
- **MWAA (Managed Airflow on AWS):** Removes the Docker dependency, provides full Airflow feature set. Eliminated due to ~$350/month minimum cost and the fact that Airflow's Python DAG model adds complexity that Step Functions' JSON state language avoids.
- **AWS Step Functions:** Already in use for the data pipeline. Natively handles deterministic/LLM interleave via Lambda states. `Choice` states branch on LLM output, `Parallel` states fan out data fetches, `Map` states iterate over tickers. Built-in retry with exponential backoff (critical for LLM API rate limits). Native timeout per state. Zero additional infrastructure cost — pay per state transition.
- **Custom DAG engine:** Rejected. Step Functions IS a managed DAG engine; building a custom one would duplicate its functionality at significant maintenance cost.

**Decision:**
Step Functions is the orchestrator. Each workflow is a Step Function state machine. Each state is typed as either `task` (deterministic Lambda) or `agent` (LLM-backed Lambda). EventBridge provides cron scheduling. SQS provides a rate-limit buffer when LLM API concurrency is constrained. SNS handles failure notifications.

**Future-state architecture:**
- `config/workflows/` — YAML workflow registry (schedule, steps, types, dependencies)
- `src/tasks/` — deterministic Lambda handlers
- `src/agents/` — LLM-backed Lambda handlers
- `src/workflows/` — Step Functions definitions (or Terraform-generated from YAML registry)
- A Terraform module reads workflow YAMLs and generates state machines + EventBridge rules

This scales from the current 5 agents to 30+ workflows without architectural changes. Airflow should be re-evaluated only if the workflow count exceeds ~50 and the YAML-registry pattern becomes limiting (cyclic dependencies, complex backfill logic, multi-team access).

**Related:** rec-164 (repo restructuring), rec-159 (Fear & Greed scraper PoC proves the task/agent pattern)

**Decision status:** Decided — April 2026

---

## Decision 38: Workflow Consolidation — Instruction Files, Gotcha Triage, and Session Automation (Decided)

**Decision:** Consolidate duplicate `copilot_instructions.md` (underscore) and
`copilot-instructions.md` (hyphen) into a single file; triage the gotcha list from ~33 to
~25 by removing tooling-enforced entries and condensing related groups; simplify
`implement.prompt.md` from 21 steps to 10; and add `session_postflight.py --auto` for
single-command session close.

**Problem:**
- Two instruction files with divergent content consumed extra context budget and created
  confusion about which was authoritative (VS Code loads the hyphen file)
- ~33 gotchas included many that were already enforced by tooling (pre-commit, preflight,
  validate.py) or had been subsumed into other entries
- `implement.prompt.md` at 21 steps was too long to survive context compaction mid-session,
  causing model confusion and requiring "prodding" to resume correctly
- Session close required 5+ separate commands; context compaction mid-session often caused
  agents to skip or mis-sequence them

**Decision:**
- Delete `copilot_instructions.md` (underscore); update all 7 references to point to the
  hyphen file
- Condense gotchas: remove tooling-enforced entries, merge related entries (Venv+Version
  Manager, Import Safety Patterns, Windows Subprocess, Athena/Iceberg, Test Isolation)
- Rewrite `implement.prompt.md` to 10 steps, with session close consolidated into a single
  `--auto` call
- Add `--auto` flag to `session_postflight.py` that executes validate→close→metrics→commit→push
  in sequence, returning a combined JSON status

**Trade-offs accepted:**
- Some historical context removed from gotcha condensation (e.g., specific error messages);
  mitigated by keeping the essential "what to do" guidance
- Shorter implement.prompt.md cannot self-document every edge case; relies on copilot-instructions
  as the primary reference for gotchas

**Decision status:** Decided — April 2026

---

## Decision 37: Lambda + GitHub Models API for Scheduled Agents (Decided)

**Decision:** Replace the GitHub Actions scheduled-agents workflow with AWS Lambda functions
that call the GitHub Models API directly, using a GitHub PAT stored in Secrets Manager.

**Context:**
- Decision 36 (GitHub Actions OIDC) was blocked by SCP denying `sts:AssumeRoleWithWebIdentity`
  from external IP ranges (GitHub Actions runner IPs)
- Static IAM users are also blocked (`iam:CreateUser` SCP)
- GitHub Models API (`https://models.github.ai/inference/chat/completions`) is compatible with
  the same free-tier models used via Copilot CLI, accessible via PAT authentication

**Implementation:**
- `aws_lambda_function.scheduled_agent_dispatcher` — reads `schedule.yaml`, runs due agents
  via GitHub Models API, writes findings to `agents/{name}/{timestamp}.jsonl`
- `aws_lambda_function.findings_processor` — triggered by S3 ObjectCreated on `agents/` prefix,
  unions findings to `findings/unified.jsonl`, compares against existing recs via Models API,
  appends new ones to `recommendations/agent-recommendations.jsonl`
- `aws_secretsmanager_secret.github_pat` — stores GitHub PAT (value set manually post-deploy)
- EventBridge hourly rule triggers dispatcher; S3 event notification triggers processor
- Lambda runs at `api.github.com` endpoint (no SCP restriction — Lambda egress is not blocked)

**Trade-offs:**
- Requires a GitHub PAT in Secrets Manager (manual step after `terraform apply`)
- PAT must have GitHub Models API access (same scope as Copilot CLI PAT)
- Lambda cold-start adds ~1s latency (acceptable for scheduled background work)
- Free tier: 150 requests/day, 15 requests/minute — sufficient for 4 agents/week

**S3 key layout:**
```
agents/{name}/{timestamp}.jsonl       ← raw findings per agent
findings/unified.jsonl                ← union of all findings
recommendations/agent-recommendations.jsonl  ← agent-generated recs (agent-NNN)
```

**Recommendation namespace separation:**
- Local: `logs/.recommendations-log.jsonl` (IDs: `rec-NNN`) — manual sessions, code review
- S3: `recommendations/agent-recommendations.jsonl` (IDs: `agent-NNN`) — Lambda-generated

**Decision status:** Decided — April 2026

---



## Decision 35: Terraform Workflow Integration (Decided)

**Decision:** Integrate terraform plan/apply gates into the `/plan` and `/implement` workflow for
infrastructure changes.

**Context:**
- Terraform files (.tf) were validated syntactically (terraform validate, fmt) but never
  planned/applied during implementation
- The `agent/infra-s3-logs` session created S3 bucket resources but had no verification they would
  actually deploy
- Infrastructure errors were discovered post-merge rather than during implementation

**Implementation:**
1. `plan.prompt.md` Step 4 (Infrastructure Assessment) adds Infrastructure Assessment section when scope includes .tf files
2. `plan.prompt.md` Step 4 embeds the terraform gate into the plan's Ordered Execution Steps and Verification Plan
3. `session_preflight.py` reports `terraform_pending` status
4. `validate.py` warns when terraform changes are pending (exit code 2 from detailed-exitcode)

**Rationale:**
- Catches infrastructure configuration errors during implementation, not post-merge
- Maintains human-in-the-loop for terraform apply (no auto-apply)
- Aligns with Decision 24 (agents use sandbox only; promotion is human-triggered)

**Trade-offs:**
- Adds friction to purely additive infrastructure changes
- Requires AWS SSO session for plan (not just validate)
- Mitigated by "defer to post-merge" option for low-risk additions

**Decision status:** Decided — April 2026

---

## Decision 26: Workflow Cost Optimisation via 2-Chat Model and Automation (Agent-decided -- pending review)

**Context:** The three-chat model (plan → implement → session_close) required re-serialization of conversation data between chats. Session close ran in isolation (Sonnet model, expensive) with no parent context, forcing manual context reconstruction. Pre-commit sanity was a separate agent invocation. Analysis showed that a merged architecture could eliminate serialization overhead and reduce token consumption by ~30%.

**Decision:** Restructure to a 2-chat model (plan + implement/close merged) with local automation layers:

**Architecture Changes:**
1. **Chat 1: Plan** — Creates branch, writes plan, invokes plan-critique (Gemini), commits plan
2. **Chat 2: Implement+Close** — Executes steps, closes session, auto-merges (all in parent context, no re-chat)
3. **Local Automation Layers:**
   - Pre-session: `scripts/session_preflight.py` (env check, recs, friction patterns)
   - Post-session: `scripts/session_postflight.py --validate/--commit/--push/--log-housekeeping` (replaces agent-based steps)

**Key Changes:**
- Session close Phase is now integrated into `/implement` prompt (Steps 19-25 absorbed from deleted `session_close.prompt.md`)
- `@retrospective` now runs on Haiku (not Sonnet) inside merged context — same task, lower cost, **better decision-making due to full context visibility**
- Pre-commit sanity agent deleted; functionality moved to `session_postflight.py --pre-commit-sanity` (deterministic, no token cost)
- `.github/prompts/plan.prompt.md` reduced from 418 to 281 lines (~33% trimming) — preflight output embedded directly, eliminates Steps 0-3b
- `session_preflight.py` produces 12-field JSON report (`logs/.preflight-report.json`), eliminates per-chat environment re-validation

**Cost Analysis:**
- Previous: 1 Sonnet (plan-critique) + 2-3 Opus (implement) + 1 Sonnet (session_close) + 1 Opus (plan) + ~8 free GPT-4.1 agents = ~4 expensive chats per session
- New: 1 Gemini (plan-critique) + 1 Opus (plan) + 1 Opus+Haiku (implement+close merged) + ~7 free GPT-4.1 agents = ~4 chats, but 33% fewer tokens in plan, Haiku cheaper than Sonnet, no serialization overhead
- Estimated savings: ~15-20% per session (composition: -30% plan.prompt.md size, +20% Sonnet→Haiku savings, -5% parallelized validation)

**Rationale:**
- **No context loss:** Retrospective now sees full conversation history (no serialization), produces better decisions
- **Lower cost:** Haiku + merged context is cheaper and more capable than Sonnet in isolation
- **Simpler UX:** Users never invoke session_close separately; it happens inside /implement
- **Parallelizable:** Concurrent feature planning now trivial (`git checkout main && /plan` while other feature in code review)
- **Deterministic validation:** Local automation is faster, more reliable, and cheaper than agent wrapping
- **Friction observability:** Clean sessions now recorded in log (previously silently skipped), enabling better cron analysis

**Rejected alternatives:**
- Single monolithic chat: Token limit exceeded for large implementations
- Keep session_close agent: Higher cost (Sonnet), isolated context, forces re-serialization after merge
- Validation-only agents before/after: Still requires agent invocation + token overhead; local scripting is 100x faster

**Files Changed:**
- Prompts: `plan.prompt.md` (-137 lines), `implement.prompt.md` (+integration of Steps 11-23), deleted `session_close.prompt.md`
- Agents: `retrospective.agent.md` (Sonnet → Haiku), deleted `pre-commit-sanity.agent.md`
- Scripts: New `session_preflight.py`, `session_postflight.py`; updated `run_retro_lite.py`, `session_metrics.py`, etc.
- Tests: `test_session_preflight.py` (11), `test_session_postflight.py` (11), `test_session_metrics.py` (7), `test_run_retro_lite.py` (10)
- Docs: Updated ARCHITECTURE.md, GETTING_STARTED.md, AGENT_WORKFLOW.md, copilot_instructions.md; added `.preflight-report.json` to .gitignore

**Status:** Agent-decided — pending human review. Implementation verified: 130/130 tests pass, validate.py exit 0, all pre-commit hooks pass.

---

## Decision 24: Multi-Environment Deployment Strategy (Decided)

**Context:** The repository currently deploys only to a sandbox AWS environment. Production trading requires a staging→production promotion path with appropriate access controls, rollback capabilities, and separation of concerns between code deployment and formula lifecycle.

**Decision:** Use GitHub Environments with single-branch promotion model:

**Branch Strategy:**
- All code lives on `main` — no separate branches for staging/production
- Promotion is a **deployment action**, not a branch merge
- Git tags (`sandbox-YYYY-MM-DD`, `staging-YYYY-MM-DD`, `prod-YYYY-MM-DD`) mark what SHA is deployed where

**GitHub Environments:**
- `sandbox`: Auto-deploys on every push to main; AWS credentials for sandbox account
- `staging`: Daily scheduled promotion (if sandbox CI green) OR manual trigger; separate AWS account
- `production`: Manual trigger with required reviewer approval; production AWS account

**Terraform Promotion (same code, different config):**
```
terraform/
  envs/
    sandbox.tfvars    # account_id, bucket_prefix, etc.
    staging.tfvars
    production.tfvars
```
- Push to main → auto `terraform apply -var-file=envs/sandbox.tfvars`
- Manual trigger to staging → `terraform apply -var-file=envs/staging.tfvars`
- Manual trigger to production → `terraform apply -var-file=envs/production.tfvars`

**Rollback Strategy:**
- `rollback.yml` workflow: checkout previous git tag, apply Terraform for that SHA
- **Orphaned resources (new resource in rolled-back-from version):** Terraform does NOT destroy resources missing from code. Options:
  1. Forward-fix: Add `removed {}` block to current code (Terraform 1.7+)
  2. Manual cleanup: `terraform state rm <resource>` then delete via AWS CLI/console
  3. Drift detection: AWS Config rules or Terraform Cloud detect out-of-band resources
- **Prevention:** AWS Service Control Policies (SCPs) block console creation; all infra via IaC only

**Emergency Escape Hatches:**
- `workflow_dispatch` with environment selector bypasses staged promotion
- Repo admin can bypass required reviewers for hotfixes
- Rollback workflow deploys previous tag directly

**Agent SSO Profile Restrictions:**
- Agents only see `company-aws-profile` profile (sandbox)
- Staging/production profiles (`company-aws-profile-staging`, `company-aws-profile-production`) exist in AWS config but are NOT referenced in any prompt or agent file
- Prevents accidental agent deployment to staging/production
- Human manually triggers promotion workflows via GitHub UI

**Formula Lifecycle vs Code Deployment (separate concerns):**
- Code deployment: GitHub Actions → sandbox/staging/production AWS accounts
- Formula lifecycle: Application logic within each environment (discovery → paper → live)
- Formulas are data in Iceberg tables, promoted by application code — not by CI/CD

**Rationale:**
- Single branch eliminates merge choreography between environment branches
- GitHub Environments provide audit trail, environment-specific secrets, and approval gates
- Git tags provide clear "what's deployed where" without inspecting Terraform state
- Formula promotion is continuous (performance-based) while code promotion is deliberate (CI-gated)
- Agent profile restriction prevents costly mistakes without blocking human operations

**Rejected alternatives:**
- Branch-per-environment (GitLab style): Creates dependency chains, forces merge order
- Separate Terraform PRs per environment: Unnecessary friction, same code applies to all
- Formula promotion as deployment action: Wrong abstraction — formulas are data, not code

**Status:** Decided — March 2026

---

## Decision 25: Git Worktree Parallel Development Workflow (Decided)

**Context:** Decision 23 enabled parallel planning via branch-specific plan files (`PLAN-{slug}.md`). However, true concurrent implementation still required checkout switching between branches, blocking one feature while working on another.

**Decision:** Support git worktrees as the recommended approach for parallel feature development:

**Worktree workflow:**
1. `/plan` creates branch `agent/{slug}` and optionally sets up worktree at `../agent-platform-{slug}`
2. Developer opens worktree in separate VS Code window
3. Each window has its own working directory, branch, and plan file
4. Commits/pushes work normally (worktrees share `.git`)
5. After merge, worktree is removed: `git worktree remove ../agent-platform-{slug}`

**Benefits:**
- True parallel implementation: work on feature B while feature A is in code review
- No context switching: each feature has its own window/terminal state
- Clean separation: no risk of committing to wrong branch

**Trade-offs:**
- Disk space: each worktree is a full working copy (~50MB excluding .git)
- Cognitive load: must remember which window is which feature
- Tooling: some VS Code extensions may not handle multiple workspaces well

**Guidance:**
- Use worktrees for features expected to overlap (e.g., parallel planning + implementation)
- Use traditional checkout for sequential work (most common case)
- Always remove worktrees after merge to avoid clutter

**Status:** Decided — March 2026

---

## Decision 27: Git Bash venv Activation Fix via setup.py (Agent-decided — approved)

**Context:** Windows developers using Git Bash experience venv activation failures due to Python's venv module generating `.venv/Scripts/activate` scripts with Windows backslashes. Git Bash interprets backslash sequences (\U, \G, etc.) as escape codes, corrupting PATH and causing cryptic import failures. This is the highest-friction recurring issue in the development loop.

**Decision:** Implement an idempotent `fix_venv_activate_for_git_bash()` function in `setup.py` that:
1. Converts Windows backslashes to forward slashes in VIRTUAL_ENV lines (C:\path → /c/path)
2. Leaves all other script content unchanged
3. Detects if already fixed (output contains forward slashes) and skips redundantly
4. Runs automatically during `python setup.py` invocation, right after venv creation

**Implementation:**
- Core mechanism: Regex substitution with path conversion helper function
- Placement: In `setup.py` main() immediately after `create_venv()` call
- Idempotency: Check for 'VIRTUAL_ENV="/' in file content; skip if found
- Platform compatibility: Forward slashes work on both Windows and Unix systems

**Rationale:**
- **Placement in setup.py (not shell script):** Pure Python automation is platform-agnostic and doesn't depend on Git Bash/bash availability. Aligns with repository's "Python scripts only for automation" rule.
- **Idempotent design:** Developers can run setup.py multiple times without fear of corruption (e.g., after branch switching or environment reset).
- **Universal scope:** Every developer who runs setup automation gets the fix automatically; no separate workaround steps needed.
- **Regex pattern choice:** Single targeted pattern (`r'VIRTUAL_ENV="([^"]+)"'`) minimizes risk of unintended modifications to script logic.

**Design Validation:**
Comprehensive test suite (5 tests) validated:
- Basic Windows→Git Bash path conversion including drive letter transformation
- Idempotency (running twice produces unchanged output)
- Graceful handling when `.venv/Scripts/activate` doesn't exist (early return)
- Content preservation (only VIRTUAL_ENV lines modified)
- Edge case coverage (multiple drive letters D:, E:, etc.)

**Status:** Agent-decided — approved by test suite (135/135 pass) and code review (0 Critical/High findings, 1 Low style suggestion implemented)

---

## Decision 23: Parallel Workflow with Branch-Specific Plans (Decided)

**Context:** The planning-implement-close workflow required sequential execution: PLAN.md was gitignored and persisted across branches, causing wrong-plan-loaded bugs. Log files written during session_close were left uncommitted after the PR was already created.

**Decision:** Move branch creation to the planning phase and use branch-specific tracked plan files:
- `/plan` creates `agent/{slug}` branch and writes `PLAN-{slug}.md` (tracked)
- `/implement` finds the plan file for the current branch (slug derived from branch name)
- Session Close Phase within `/implement` auto-merges after CI passes, with tiered conflict resolution
- Always branch from main (not from feature branches)

**Conflict resolution tiers (simplified):**
1. Auto-resolve: Append-only logs (SESSION_LOG.md, *.jsonl)
2. Auto-resolve: Structured docs (RECOMMENDATIONS.md, DECISIONS.md) — merge rows/sections
3. Escalate immediately: Code/config files (`.py`, `.tf`, `.prompt.md`) — human resolves

**Rationale:**
- Parallel features can now be planned while implementation is in-flight
- Plan files are tracked per-branch, eliminating cross-branch contamination
- Auto-merge on CI pass is safe because the Session Close Phase of `/implement` is reached only after all implementation steps and code review are complete
- Tiered conflict resolution handles expected concurrent doc edits without human intervention
- Always branching from main prevents dependency chains and isolates conflicts

**Rejected alternatives:**
- Branch from feature branches: creates dependency chains, must merge in order
- Single PLAN.md with branch name in content: still gitignored, still cross-contaminates
- Manual merge only: adds friction, delays integration, provides no additional safety (CI is the gate)

**Status:** Decided — March 2026

---
