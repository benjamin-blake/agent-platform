# INTENT: CI/CD Architecture for an Agent-First Repository

**Status:** Authoritative design specification.
**Owner:** Solo developer + autonomous executor (Wave 4, future).
**Related Decision Record:** Decision 73 (`docs/DECISIONS.md`).

This document is the canonical specification for how validation, merging, and
environment promotion work in this repository. It supersedes the implementation
mechanism of Decision 60 (two-tier validation) and parts of Decision 72 (RCA-as-
plan-source merge gate), while preserving their underlying intent.

The model is designed for an agent-first repository operating under three hard
constraints:

1. **Branch protection is active but deliberately non-wedging** (Decision 83, amending Decision 89).
   The `main-protection` ruleset uses admin bypass-always, `strict = false`, and required checks
   = `pr-validate` + `terraform-validate` only. The forward-fix / convention-plus-tooling design
   is preserved.
2. **Multi-worktree parallelism is a first-class workflow.** Mechanisms that move
   `main` underneath active worktrees (e.g., auto-revert) are excluded.
3. **Agent throughput dominates the cost function.** Wall-clock latency on the
   recursive self-improvement loop matters more than minutes-on-runner.

---

## 1. Background: How Decision 60 Deviated from Day One

Decision 60 (2026-05-05) specified a two-tier validation model:

- `--pre` (edit-loop, target <=30 seconds): lint, format, prompt validation. No pytest, no AWS.
- default presubmit (target <=5 minutes): full check suite, including `pytest tests/ -m "not integration"` and AWS-touching invariants.

The deviation chronology shows the budget was unattainable at ratification:

| Date | Event |
|------|-------|
| 2026-05-01 | V3 verifier harness lands (PR #274). Adds Athena round-trips to `validate.py`. |
| 2026-05-05 | Decision 60 ratified. |
| 2026-05-05 | DQ runner wired into `validate.py` (PR #289). Same day as ratification. |
| 2026-05-06 to 2026-05-12 | 12 commits to `validate.py` adding source registry, write enforcement, schema verifier, IAM coverage, hollow-rec cleanup. |

Measured runtimes (May 2026 sample, 30 runs): median **18 min**, average **24
min**, max **50 min**. Queue time is ~0 (the self-hosted runner is idle 95% of
the time). The slowdown is internal: ~5 min in `validate_verification_harness`
(Athena round-trips), ~5 min in pytest fixtures acquiring boto3 and Athena
clients, plus the DQ runner sweep when stale.

Structural causes:

- **Budget had no enforcement mechanism.** Decision 60 stated <=5 min as a
  target but no assertion fired on breach. Each new check landed individually;
  none triggered a budget gate. Aggregate drift accumulated silently.
- **Full-tier marker-exclusion was empty by construction.** `validate.py` runs
  `pytest tests/ -m "not integration"` inside the *full* tier (not `--pre`).
  Only 2 tests carry `@pytest.mark.integration`; ~52 test files import boto3
  or Athena clients with no marker. The exclusion ran every CI invocation but
  excluded almost nothing. The failure is **not** that the fast tier had a
  failed sieve - `--pre` has no pytest invocation at all per Decision 60 - but
  that the full tier accumulated AWS-dependent work without compensating
  marker hygiene or isolation gating.
- **Fast tier had no scope discipline.** `--pre` exists, but its tier semantics
  are defined by *exclusion of check categories* (no pytest, no AWS) rather
  than by *diff scope*. As new static checks (DQ manifest gate, source
  registry CI guard, executor boundary) landed, they ran on all files
  unconditionally, so even a one-line edit triggered repo-wide scans. The
  budget held by virtue of these checks being individually fast, not by
  design.
- **Aspirational documentation drift.** The decision spoke as if the budget
  held; the implementation did not. There was no automated reconciliation
  between the documented contract and the runtime behaviour.

This INTENT document closes those gaps by specifying tiers with diff-aware
scope, an enforced budget assertion, marker hygiene, and explicit enforcement
surfaces (Section 2.5).

---

## 2. Two-Tier CI: Diff-Aware Fast, Comprehensive Full

> **TARGET STATE.** This section describes the architecture this INTENT
> commits to. Current state of `scripts/validate.py` and
> `.github/workflows/ci.yml` is as described in Section 1. The behaviours
> below land via the follow-on IMPLEMENTATION plan `validate-fast-tier-reshape`
> (Section 9). Until those plans land, `--pre` and the default presubmit
> behave per Decision 60.

The two tiers from Decision 60 survive. Their semantics are redefined.

### Fast tier (`--pre`)

| Property | Value |
|----------|-------|
| Scope | Diff-aware (`git diff --name-only origin/main`) |
| Static checks | `ruff check`, `ruff format --check` on changed files only |
| Type check | `mypy` on changed modules only. Reverse-import closure is **not** computed in v1 (no import-graph tool exists in the repo today). The full tier catches reverse-import breaks. |
| Tests | `pytest --picked` (git-status-based selection). `pytest-picked` to be added to `requirements.txt` by `validate-fast-tier-reshape`. Possible later upgrade to `pytest-testmon` if false-negatives accumulate. |
| Validate suite | Static `validate_*` checks that operate on changed scope; skip those requiring AWS |
| Excluded | V3 verifier harness, DQ runner sweep, AWS-touching pytest fixtures |
| Hard budget | <=5 minutes total (enforced - see below) |
| Triggered by | Local edit loop, PR CI on every push |

### Full tier (default, no flag)

| Property | Value |
|----------|-------|
| Scope | Entire repository |
| Static checks | `ruff`, `mypy`, all `validate_*` invariants on all files |
| Tests | `pytest tests/` unfiltered, including AWS-touching tests |
| Validate suite | All checks including V3 verifier harness and DQ runner |
| Hard budget | None (honest: 15-30 minutes) |
| Triggered by | Push to `main`, scheduled cron (hourly, with concurrency control - see Section 9), `workflow_dispatch` |

### Enforcement: budget assertion in `validate.py`

Fast tier exit logic asserts wall-clock elapsed <= budget. On breach,
`validate.py` exits non-zero with diagnostic:

```
ERROR: Fast tier exceeded budget (5 min). Elapsed: X min.
This tier has grown beyond its design contract. Either:
  1. Move the slow check to the full tier, or
  2. Optimise the check, or
  3. Open a planning session to revise this budget (requires Decision Record).
```

This converts the Decision 60 budget from documentation to gate.

### Budget breach durability

The assertion fires *after* the slow check completes; it does not prevent the
cost on the offending PR. To prevent silent aggregate drift recurrence
(Decision 60's failure mode where individually-small additions added up
imperceptibly), every assertion breach also files a `source="budget_breach"`
rec via `ops_data_portal.file_rec` containing: elapsed time, diff manifest,
dominant phase identified from phase timing. Repeated breaches accumulate as
recs and surface in preflight reports, making aggregate drift visible.

**Connectivity fallback for breach filing.** `ops_data_portal.file_rec`
requires Athena reachability. The breach-filing path handles connectivity
loss in three tiers, all without raising during validate.py import:

1. **Local / Claude-Code-on-web session:** the static-key assume-role chain
   auto-refreshes; there is no interactive login (the Decision 57 SSO-recovery
   pattern is superseded 2026-05-28 per CD.21 / Decision 73 -- see the
   PROJECT_CONTEXT credential model). Recovery: verify `aws sts
   get-caller-identity --profile agent_platform`; if the `agent_static` key was
   rotated, refresh `~/.aws/credentials` and retry `file_rec` once.
2. **CI (GitHub-hosted runner, CD.21 / Decision 73):** the OIDC role
   (`agent-platform-github-ci-branch` / `-pr`) supplies credentials via boto3's
   default chain without any login. The self-hosted EC2 runner (Decision 68) was
   retired 2026-05-28. No interactive recovery is attempted in CI; the `CI=true`
   guard remains.
3. **Both contexts, if portal still cannot reach Athena:** the rec is queued
   to the local outbox (`logs/.ops-outbox/`) per Decision 51 and drains on
   the next successful `ops_data_portal.sync()` call.

The breach is never silently dropped. The `ops_data_portal` import is
isolated to a function-local import inside the breach-filing path (not
module-level) so that `validate.py` never raises during import even if the
portal itself has a transient init issue.

### Budget breach escape hatch

Because the budget assertion lives in `validate.py` and `validate.py` is
itself a sync-merge path (Section 7), a faulty assertion or transient
slow-disk event could lock all agents out of the edit loop simultaneously.
To prevent this chicken-and-egg failure mode:

- `--ignore-budget` flag on `validate.py --pre` skips the assertion and files
  a `source="budget_bypass"` rec via `ops_data_portal.file_rec` containing the
  branch, elapsed time, diff manifest, and optional `--ignore-budget-reason`
  text. The outbox (Decision 51) handles offline-emergency persistence.
- The flag is intended for emergency use only. Repeated use (more than 3
  bypass recs in a rolling 7-day window) surfaces a soft alert in preflight
  via `session_preflight._check_budget_bypass_alert()`.
- The flag does NOT skip the work; it only skips the post-work assertion.
- The flag is disallowed when `CI=true` (CI guard in `validate.py:main()`).

Both budget breaches (`source="budget_breach"`) and bypass events
(`source="budget_bypass"`) route through `ops_data_portal.file_rec` and share
the same connectivity-recovery chain (outbox fallback, Decision 51). No local
JSONL audit file is written by any `--pre` invocation.

---

## 2.5 Enforcement Surfaces

The L1-L10 layered model (Section 3) requires several enforcement mechanisms.
None of them exist in code today. This table maps each gate to the file that
will own enforcement, the current build state, and the follow-on plan that
delivers it. The mapping is the contract: an INTENT claim about behaviour is
meaningful only when paired with a build state and an owning plan.

| Layer / Gate | Enforcement file | Current state | Owning follow-on plan |
|--------------|------------------|---------------|----------------------|
| L1 fast tier on PR CI | `.github/workflows/ci.yml` | BUILT (ci-workflow-restructure, 2026-05-19) | n/a |
| L2 fast-green-AND-no-ci-rca-rec evaluator | `.github/workflows/ci.yml` job step or `scripts/session_postflight.py` auto-merge wrapper, calling Athena via `ops_data_portal` for the rec query | DEFERRED -- see follow-up | TBD -- new plan required |
| L3 full tier on push to main | `.github/workflows/ci.yml` (push trigger retained; now runs default presubmit, no longer duplicating PR CI) | BUILT (ci-workflow-restructure, 2026-05-19) | n/a |
| L4 ci-rca diagnosis | `.github/workflows/ci-rca.yml` | BUILT (Decision 72) | n/a |
| L5 planning hard-block | `scripts/session_preflight.py` (preflight signal) and `.claude/skills/planning/SKILL.md` (planning rule) | BUILT (`planning-queue-governance`, commit a124c04, 2026-05-13) | n/a |
| L6 auto-merge pause | `scripts/session_postflight.py:run_push()` is the **primary** enforcement point (queries Athena for open ci-rca recs via `ops_data_portal` before invoking `gh pr merge`). A defence-in-depth secondary check lives in `.github/workflows/ci.yml` as a workflow-side gate. Primary fails closed; secondary catches drift if primary is bypassed. | DEFERRED -- see follow-up | TBD -- new plan required |
| L7 ci-rca rec closure on green | The full-tier workflow on the forward-fix PR's merge to main, which closes the rec via `ops_data_portal.update_rec` after a green run. Alternative: a separate watcher in `planning-queue-governance` that queries Athena periodically. | UNBUILT | `planning-queue-governance` (primary) |
| L8 hourly canary workflow | `.github/workflows/main-canary.yml` | BUILT (ci-workflow-restructure, 2026-05-19) | n/a |
| L8 single-runner concurrency | `concurrency: { group: ci-runner, cancel-in-progress: false }` on both canary and PR CI workflows | BUILT 2026-05-19 (ci-workflow-restructure), RETIRED 2026-05-28 (CD.21) -- each `ubuntu-latest` job runs on its own isolated runner; no host serialisation needed | n/a |
| L8 ci-rca liveness fallback | `scripts/session_preflight.py` Athena query for "main red but no ci-rca rec within 30 min" | DEFERRED -- see follow-up | TBD -- new plan required |
| Budget assertion | `scripts/validate.py` (post-work check in `main()` for fast tier exit; `_FAST_TIER_BUDGET_SECONDS = 300`) | BUILT (`validate-fast-tier-reshape`, 2026-05-13) | n/a |
| Budget breach rec filing | `scripts/validate.py` (`_file_budget_breach_rec` helper calling `ops_data_portal.file_rec` with `source="budget_breach"`; outbox fallback per Decision 51) | BUILT (`validate-fast-tier-reshape`, 2026-05-13) | n/a |
| Budget assertion escape hatch | `scripts/validate.py` (`--ignore-budget` flag; bypass events filed as `source="budget_bypass"` recs via `ops_data_portal.file_rec`; CI guard refuses flag when `CI=true`) | BUILT (`validate-fast-tier-reshape`, 2026-05-13) | n/a |
| Forward-fix recursion alert | `scripts/session_preflight.py` (counter of consecutive ci-rca recs in rolling 24h window) | UNBUILT | `planning-queue-governance` |
| L9 promotion to SIT | `.github/workflows/promote-staging.yml` | UNBUILT (months away, Phase Infra-Env) | Phase Infra-Env |
| L10 promotion to PROD | `.github/workflows/promote-production.yml` | UNBUILT (months away, Phase Infra-Env) | Phase Infra-Env |

---

## 3. The L1-L10 Layered Model

> **TARGET STATE.** L1-L8 are buildable in the follow-on plans named in
> Section 2.5. L9-L10 are deferred to Phase Infra-Env (months away). Current
> state per Section 1.

The merge/deploy pipeline is specified as ten layers.

| Layer | Trigger | Action | Failure Handling |
|-------|---------|--------|------------------|
| **L1** | PR push | Fast tier on PR CI (`--pre`) | PR cannot merge; fast feedback to agent or human |
| **L2** | Fast tier green AND no open ci-rca rec | Squash auto-merge to sandbox `main` | Blocked while sandbox main is red |
| **L3** | Push to `main` | Full tier on push-to-main CI | If fail -> L4 |
| **L4** | Full tier red on `main` | `ci-rca` files `source="ci_rca"`, `priority="critical"` rec | Rec is a hard block (see L5, L6); see Section 9 for ci-rca liveness fallback |
| **L5** | Open ci-rca rec exists | `/plan` sessions must address the rec first; no unrelated work scoped (see Section 5 for "related" definition) | Planning skill plus `session_preflight.py` enforce |
| **L6** | Open ci-rca rec exists | PR auto-merge paused for all branches | Branches can still be opened and fast-tier validated, but not merged |
| **L7** | `/implement` on the ci-rca rec | New branch (e.g., `agent/fix-ci-{rec-id}`), normal cycle, lands as new commit | Closes ci-rca rec on green; unblocks L5/L6 |
| **L8** | Cron every 3 hours during sandbox-only operation (tightens to hourly when Phase Infra-Env lands SIT); runs on GitHub-hosted `ubuntu-latest` (CD.21, no host serialisation needed) | Full tier on `main` | Catches AWS API drift, dependency drift, time-bombs not caused by any merge |
| **L9** | Scheduled daily (future, Phase Infra-Env) | If sandbox `main` has been green continuously >=24h, promote to SIT | Streak resets on any ci-rca rec opening |
| **L10** | Scheduled weekly (future, Phase Infra-Env) | If SIT `main` has been green continuously >=7d, promote to PROD | Streak resets on SIT failure |

---

## 4. Forward-Fix Merge Gate (Worktree-Safe)

The merge gate is **forward-fix only**. Auto-revert is explicitly excluded.

### Why no auto-revert

Auto-revert moves `main` underneath every worktree currently working against
it. A worktree mid-implement against `main@X` suddenly sees `main@parent(X)`
on next pull. Recovery is awkward (rebase replays the bad change) and
silently-corrupting (good changes can be reverted alongside the bad). For a
repository with N worktrees and an autonomous executor that will spawn more,
this is structurally hostile.

### Forward-fix flow

1. Full tier fails on `main`.
2. `ci-rca` agent diagnoses root cause (existing infrastructure, Decision 72).
3. `ci-rca` files a rec: `source="ci_rca"`, `priority="critical"`, with
   diagnosis text and the failing run URL.
4. The rec acts as a **hard block** on the planning queue (L5) and a
   **merge pause** on auto-merge (L6).
5. A new `/plan` session scopes the forward fix against the rec.
6. `/implement` lands the fix on a new branch via the normal cycle. Fast tier
   on PR, full tier on merge, ci-rca rec closes on green.

### Prior art and the worktree-safe adaptation

Optimistic merge with post-merge full validation is the shape used by Google
TAP (Test Analysis Platform) and Meta Sapling/TAP. Both of those systems pair
the optimistic merge with automated revert; this INTENT explicitly omits
revert in favour of forward-fix because worktree-based parallel development
makes auto-revert structurally hostile in this repository. The optimistic-
merge half is industry-standard; the worktree-safe forward-fix variant is a
sole-developer adaptation that trades main-red recovery time for worktree
stability.

---

## 5. Planning Queue Governance

The merge gate model demands changes to the planning queue rules.

### Hard block on ci-rca recs

While any rec with `source="ci_rca"` and `status="open"` exists:

- `/plan` cannot scope unrelated work. The next session must address the
  ci-rca rec first.
- `session_preflight.py` surfaces ci-rca recs at the top of the report with
  a HARD BLOCK marker.
- The planning skill rejects PLAN files for unrelated work while the block is
  active.

### Definition: "related" vs "unrelated" work

For L5 to be enforceable in code, "related" must be defined. A planning
session is allowed to scope work that is "related" to an open ci-rca rec
under any of the following conditions:

- The new plan's `Scope` table includes the same `source_file` field that
  the ci-rca rec cites.
- The new plan addresses the same Decision Record the ci-rca rec references
  (if any).
- The new plan addresses the same failure category as the rec (failure
  categories: DQ check failure, schema verifier failure, validate.py false
  negative, terraform validate failure, pytest regression, mypy regression,
  prompt-compliance failure, V3 harness failure).

A plan that does not satisfy any of these conditions must wait until the
ci-rca rec closes, OR explicitly document a deferral rationale in its
`Context` section. The planning skill enforces this at PLAN-file write time:
if a ci-rca rec is open and the new plan does not satisfy a relatedness
condition and lacks a deferral rationale, write is refused.

**`source_file` field is a ci-rca contract requirement.** The relatedness
conditions above rely on `source_file` being populated by the ci-rca agent
when it files recs. The ci-rca agent contract (`.claude/agents/scheduled/
ci-rca.md`) must populate `source_file` with the primary file implicated by
the failure diagnosis. Schema enforcement (a Pydantic gate on `file_rec`
calls with `source="ci_rca"` that refuses writes with empty `source_file`)
lands in the `planning-queue-governance` follow-on plan. Until that gate
lands, the relatedness check operates on best-effort `source_file` data and
may fall back to manual planner judgment with a logged rationale in the new
plan's `Context` section. The same field powers the forward-fix recursion
counter in Section 9; both consumers share the same contract.

### Worktree UX under active L5/L6 block

Multi-worktree parallel development continues during an active ci-rca block,
with the following behaviour:

- Worktrees mid-implement (branch already created, changes in progress) may
  continue working. Their fast tier runs locally and on PR CI.
- Their PRs cannot auto-merge while the block is active (L6 enforcement).
- Their PRs may open, accumulate fast-tier-green status, and wait in the
  queue.
- When the ci-rca rec closes and main returns to green, queued PRs flush in
  FIFO order through the standard auto-merge flow.
- Worktrees may continue creating new branches and running `--pre` locally;
  the block applies only to `/plan` scope decisions and to the merge step.
- The forward-fix branch (the one that addresses the ci-rca rec) is the only
  PR exempt from the L6 pause - it must be allowed through, otherwise the
  block self-perpetuates.

### Stop surfacing non-automatable mass

The current preflight protocol treats `non_automatable_recommendations > 0`
as MANDATORY discussion. With 178 such recs accumulated (and growing) pending
Wave 4 executor activation, this is operational noise.

Change: the planning skill no longer treats `non_automatable_recommendations`
as a mandatory discussion item. Counts still appear in the preflight report
(informational). The MANDATORY discussion rule fires only on ci-rca recs.

This change applies until Decision 67 is reversed and the executor is back
in service. At that point, the non-automatable backlog re-enters circulation
under whatever queue policy the executor design requires. To prevent the
backlog from growing unbounded during the deferral, a soft cap of 250
non-automatable recs is monitored; breach surfaces as an informational note
in the preflight report. The cap is configurable; 250 is the initial value.

### Configuration boundary

The merge-mode property (sync vs async PR gating) is **derived from the diff**,
not stored on individual recs. A path-prefix table (Section 7) computes the
mode at PR time. The `automatable` field on `ops_recommendations` retains its
existing semantics (executor self-modification boundary, Decision 44) and is
not extended. Conflating the two would expand the executor boundary into
files that are not self-modification risks, or force sync gating on files
well-covered by their tests.

---

## 6. Promotion Train (Future-State Design)

> **FUTURE STATE.** Implementation deferred to Phase Infra-Env. SIT and PROD
> environments do not exist today. **Months away at minimum.** The design is
> captured now so Phase Infra-Env has a concrete spec rather than a verbal
> vision.

Layers L9-L10 specify the multi-environment promotion design.

### Environments

Account-family targets per Decision 77 and `docs/contracts/environment-taxonomy.md`: the platform
stays SINGLE-ACCOUNT (the current personal account, sandbox only) until the product axis reaches
live_full approaching real capital -- that product event is the named trigger to stand up dedicated
SIT then PROD accounts. SIT/PROD are reserved vocabulary and future-state infrastructure.

| Environment | Account-family target | Agent-Initiated Changes | "Always Green" Invariant |
|-------------|-----------------------|-------------------------|--------------------------|
| Sandbox | current personal account (`agent_platform` runtime / `agent_platform_admin` provisioning) | YES (only environment agents touch) | NO - tolerates red, recovers via forward-fix |
| SIT | future dedicated account (not yet stood up; gated on the live_full trigger) | NO (automated promotion only; no agent-initiated work) | YES - must always be green |
| PROD | future dedicated account (not yet stood up; gated on the live_full trigger) | NO (automated promotion only; no agent-initiated work) | YES - must always be green |

### Promotion gates

| Promotion | Cadence | Gate |
|-----------|---------|------|
| Sandbox -> SIT | Scheduled daily | Sandbox `main` has been green continuously >=24h. Streak resets on ci-rca rec opening. |
| SIT -> PROD | Scheduled weekly | SIT `main` has been green continuously >=7d. Streak resets on SIT failure. |

### Why time + green-streak (not pure time)

A commit promoted exactly 24h after merge, where the previous 23h had main
green but the last hour has it red (active ci-rca rec), would inherit a
known-broken state. The "green streak" requirement excludes this case. This
is how Google TAP gates canary promotion: the canary tier must be green for
a defined window before promotion fires.

### L8 cadence at promotion-train activation

When Phase Infra-Env lands SIT and the L9 promotion gate begins consuming the green-streak signal, the L8 canary cadence tightens to hourly so the 24-hour streak window has 24 samples rather than 8. The cron expression flips from `0 */3 * * *` to `0 * * * *` at that time; runner-capacity implications are revisited per Section 9.

### Relationship to existing roadmap

`docs/ROADMAP-PRODUCT.md` Phase Infra-Env already describes a sandbox/staging/production
strategy with promotion workflows. This INTENT document does not supersede
that phase; it specifies the architecture Phase Infra-Env will build against.

---

## 7. Configuration: Merge-Mode as Derived Property

PRs need a gate-strictness decision at merge time. The choices considered:

| Option | Mechanism | Rejected because |
|--------|-----------|------------------|
| Per-rec `merge_mode` field | Author or agent sets on rec | Adds cognitive load; drift risk; agents must remember |
| Extend `automatable` to a structured field | `{ executor_safe: bool, merge_mode: str }` | Migration cost outweighs benefit; orthogonal axes don't compress cleanly |
| Path-prefix table (chosen) | Workflow YAML inspects diff and computes mode | Zero per-rec state; deterministic from diff; single source of truth |

### Path table (initial proposal, to be refined in follow-on plan)

| Path prefix | Merge mode | Rationale |
|-------------|------------|-----------|
| `terraform/**` | sync | IAM, infrastructure - main-red is expensive |
| `scripts/validate.py` | sync | Changes the merge gate itself |
| `scripts/ops_data_portal.py` | sync | Warehouse write surface |
| `scripts/session_preflight.py` | sync | Workflow surface for all sessions; breakage affects every subsequent session |
| `scripts/session_postflight.py` | sync | Auto-merge surface; faulty postflight masks gate failures (Risk Finding from INTENT critique) |
| `config/agent/executor/capabilities.yaml` | sync | Loaded at validate.py import; broken config fails-loud at import time |
| `src/data/handlers/**` | sync | Lambda code, deployment-adjacent |
| `.github/workflows/**` | sync | CI infrastructure |
| `requirements.txt`, `pyproject.toml` | sync | Dependency surface; broken dep resolution breaks all CI |
| `.claude/skills/planning/**`, `.claude/hooks/**` | sync | Workflow contract for every planning session |
| (default) | async (forward-fix model) | Most PRs; agent throughput wins |

The table itself is configuration. Refinement (additions/removals) is a
planning decision, not a code change to workflow logic.

---

## 8. Relationship to Existing Decisions and Sibling INTENT Documents

### Decision relationships

| Decision | Relationship |
|----------|--------------|
| Decision 44 (Executor Self-Modification Boundary) | Preserved unchanged. `automatable` field continues to mean "executor-safe to implement." |
| Decision 55 (RCA-First Executor) | Extended. The forward-fix model is RCA-first applied to CI failures: diagnose once, fix permanently, no rescue agents. |
| Decision 60 (Two-Tier Validation) | Implementation mechanism superseded. The two-tier abstraction survives; the tier definitions are redefined (exclusion-by-marker replaced by diff-aware selection). The 5-minute fast-tier budget is preserved but now enforced by assertion. |
| Decision 67 (Lambda + STRATEGIC plans deferred) | Acknowledged. The non-automatable backlog will re-enter circulation when Decision 67 is reversed. |
| Decision 68 (Self-Hosted Runner) | Compounds. Free CI minutes are what make hourly full-tier canary affordable. The runner is also the single point of failure for the L1-L8 stack (Section 9). |
| Decision 71 (cc-scheduled-agents) | Compounds. The infrastructure pattern for scheduled cron on the self-hosted runner is reused for the hourly canary (L8). |
| Decision 72 (RCA-as-Plan-Source for CI) | Extended. The ci-rca rec gains "hard block" semantics in the planning queue (L5) and "auto-merge pause" semantics in the merge workflow (L6). |
| Decision 89 (GitHub Branch Protection Not Available -- now active per Decision 83; previously conflated with Decision 72 in DECISIONS.md) | Amended by Decision 83: branch protection is now active (non-wedging); convention-plus-tooling design preserved. |

### Sibling INTENT documents

This INTENT interacts with two sibling documents:

- **`docs/INTENT-validation-architecture.md`** owns the flag semantics for
  `--pre` and the default presubmit. Per `docs/DECISIONS.md` Decision 60,
  migration steps 1-5 are **DONE** (anchor doc, DQ runner wiring, self-hosted
  runner stand-up, `--pre` parity freeze, flag consolidation). Step 6
  (scheduled postsubmit health checks) is **reframed by Decision 73 as the
  L8 hourly canary** in this INTENT. Step 7 (delete the migration-sequence
  section of validation-architecture once convergence is real) can be
  actioned when L8 plus the three follow-on IMPLEMENTATION plans named in
  Section 2.5 have landed. The flag-naming and tier-name contracts in
  validation-architecture remain authoritative; this INTENT redefines what
  each tier *does*, not what it is called.
- **`docs/INTENT-autonomous-improvement-control-plane.md`** owns the
  recursive self-improvement loop. The forward-fix merge gate and the
  ci-rca hard-block are two new edges in that loop's graph. The control-
  plane intent should be updated to reference this INTENT when it next
  changes.

---

## 9. Known Gaps and Deferrals

This INTENT document specifies a target architecture. Several elements are
deferred to follow-on work; this section enumerates them explicitly so future
sessions know what is outstanding.

### Deferred to follow-on IMPLEMENTATION plans

- **`validate.py` tier reshape** - `--pre` becomes diff-aware; tests selection
  via `pytest --picked`; budget assertion with `--ignore-budget` escape hatch;
  budget-breach rec filing; AWS pytest-marker audit and tag. Filed as a
  separate IMPLEMENTATION plan (proposed slug: `validate-fast-tier-reshape`).
- **Workflow restructure** - `.github/workflows/ci.yml` PR/main split; new
  `main-canary.yml` for hourly cron (BUILT 2026-05-19). The single-runner
  concurrency group (`ci-runner`) was RETIRED 2026-05-28 per CD.21 (each
  `ubuntu-latest` job gets its own isolated runner; no host serialisation needed).
  Auto-merge pause logic in `session_postflight.py` remains deferred.
  Slug: `ci-workflow-restructure`.
- **Planning queue governance changes** - `session_preflight.py` and the
  planning skill updates to enforce ci-rca hard block, define "related work"
  per Section 5, stop surfacing non-automatable mass, add ci-rca liveness
  fallback alert, add forward-fix recursion escalation. Filed as a separate
  IMPLEMENTATION plan (proposed slug: `planning-queue-governance`).
- **Path-prefix merge-mode table** - initial values proposed in Section 7;
  refinement and the workflow integration land in the workflow-restructure
  plan.

### Required dependencies

The architecture references tooling not yet declared in `requirements.txt`:

- `pytest-picked` for fast-tier test selection. Added by
  `validate-fast-tier-reshape`.
- (Possible future) `pytest-testmon` if coverage-map-based selection replaces
  git-status-based selection.

No other new external dependencies are introduced.

### Deferred to far-future activation

- **Layer 9 (Sandbox -> SIT promotion)** - depends on Phase Infra-Env building
  the SIT environment. **Months away at minimum.** No SIT account, profile,
  Terraform variables, or promotion workflow exist today.
- **Layer 10 (SIT -> PROD promotion)** - same dependency, plus an additional
  bake period after SIT exists. **Months away at minimum.** No PROD account
  or trading-go-live readiness exists today.
- **Executor priority-queue rule for ci-rca recs** - depends on Wave 4
  (Autonomous Executor) becoming operational, which itself depends on
  Decision 67 reversal (telemetry trust restoration). The L5/L6 enforcement
  for autonomous execution will need a small extension to the executor's
  ranking logic. Today the planning skill's enforcement (interactive sessions
  only) is sufficient because the executor is offline.
- **Telemetry-trust restoration** - when Decision 67 reverses, the
  non-automatable rec surfacing rule (Section 5) needs to be revisited. The
  current "stop surfacing them" rule is appropriate while the executor is
  offline; once the executor is back, the queue policy needs an explicit
  revisit. The Section 5 soft-cap (250 non-automatable recs) provides a
  forcing function if the backlog grows unmanageable before that revisit.
- **`pytest --picked` -> `pytest-testmon` upgrade** - first iteration uses
  `--picked` (git-status-based, conservative). If false-negatives accumulate,
  upgrade to testmon (coverage-map artifact persisted to S3 or cache). This
  is a future optimisation, not a blocker.

### ci-rca liveness gap and fallback contract

The forward-fix model (Section 4) treats ci-rca as a deterministic mechanism:
on red main, a rec is filed. In practice ci-rca is a 20-minute-timeout LLM
call running on the same self-hosted runner as PR CI, authenticated by an
OAuth token with a 90-day rotation (`CLAUDE.md` setup walkthrough). It can
fail (timeout, rate-limit, OAuth expiry, runner crash mid-call).

Fallback contract:

- If full-tier red on `main` persists for more than 30 minutes with no
  `source="ci_rca"` rec filed since the failure, the next `/plan` or
  `/implement` session starting on any branch surfaces a HARD ALERT in
  preflight: "Main is red and ci-rca has not filed a rec. Human triage
  required."
- The check is performed by `session_preflight.py` via two Athena queries:
  (a) latest `main` CI conclusion, (b) any `source="ci_rca"` rec created
  since the latest red-main timestamp.
- The 30-minute window accounts for ci-rca's 20-min timeout plus reasonable
  workflow latency.
- During such an alert, L6 auto-merge pause remains in effect (it is keyed
  on red-main, not on rec presence).

Owning follow-on plan: `planning-queue-governance`.

### Forward-fix recursion escalation

A bad forward-fix can itself fail full tier, opening a second ci-rca rec.
Recursive ci-rca recs are debuggable but unbounded by default.

Escalation contract:

- `session_preflight.py` computes a counter of consecutive `source="ci_rca"`
  recs that cite overlapping `source_file` fields, within a rolling 24-hour
  window.
- At count >= 3, the preflight surfaces a HARD ALERT: "Forward-fix recursion
  threshold exceeded. Pause autonomous work and triage manually."
- L5 hard-block remains in effect during the alert. L6 auto-merge pause
  remains in effect.
- The threshold is configurable; 3 is the initial value.

Owning follow-on plan: `planning-queue-governance`.

### Single-runner concurrency and L8 sequencing (RETIRED CD.21)

> **Retired 2026-05-28 (CD.21 / Decision 73).** The self-hosted EC2 runner was
> replaced by GitHub-hosted `ubuntu-latest` runners. Each job runs on its own
> isolated runner instance; there is no shared host to serialise against, so
> the `ci-runner` concurrency group is obsolete and has been removed from both
> `main-canary.yml` and `ci.yml`. The analysis below is preserved as history.

L8's canary originally ran full tier on the same self-hosted EC2 t3.medium
runner that also handled PR CI. A 28-minute canary triggered at the hour mark
would queue any concurrent PR CI for the canary duration, busting the L1
5-minute budget via queue time rather than work time.

Mitigation in v1 (now retired): both the L8 canary workflow and the PR CI
workflow declared `concurrency: { group: ci-runner, cancel-in-progress: false }`.
GitHub Actions' concurrency primitive ensured only one job per group ran at a
time. At 3-hour cadence: median ~18 min x 1 run / 180 min cadence = ~10%
baseline runner occupancy; worst-case 50 min x 1 / 180 min = ~28% worst-case
overlap with PR CI.

With GitHub-hosted runners (CD.21): each job gets its own runner; canary and
PR CI no longer contend for a shared resource. The concurrency group is
removed. L1 budget pressure from L8 is no longer a concern in this model.

### Budget assertion rollback risk

The budget assertion (Section 2) lives in `validate.py`, which is itself a
sync-merge path. A faulty assertion landing on main would block all agents
from passing fast tier until reverted, but the revert PR cannot land
because its full tier on main requires the same broken `validate.py` to
pass.

Mitigation: the `--ignore-budget` escape hatch (Section 2). Use is filed as a
`source="budget_bypass"` rec via `ops_data_portal.file_rec` for audit; the
outbox (Decision 51) ensures durability when Athena is unreachable. Repeated
use (>= 3 in 7 days) surfaces a soft alert in `session_preflight`. The flag is
intentionally disallowed in CI (`CI=true` guard in `validate.py:main()`) and
not exposed as an environment variable to prevent silent normalization.

### L8 cron runaway runbook

If the hourly canary begins consuming the runner so consistently that PR CI
times out or queues exceed acceptable latency, the manual recovery is:

1. Disable the `main-canary.yml` cron via `.github/workflows/` edit (sync
   merge per Section 7).
2. File a `source="planning"` rec to scope the cadence change.
3. Re-enable cron at reduced cadence after the rec is implemented.

This runbook is captured here rather than in CLAUDE.md because it pertains
to a workflow that does not yet exist.

### Risks not mitigated by this design

- **Cascade failures during the merge-pause window.** If ci-rca takes >1h
  to diagnose and the queue accumulates, throughput dips temporarily.
  Acceptable cost; no mitigation in scope.
- **Path-table maintenance.** The merge-mode path-prefix table will need
  curation as the repo evolves. No drift-detection enforcement is specified;
  this is a Section 7 limitation accepted in v1.
- **Self-hosted runner single point of failure.** The L1-L8 stack assumes
  the EC2 runner is available. If the runner fails, no PR or main CI runs,
  and ci-rca itself cannot fire (it runs on the same box). Recovery
  requires the runner runbook in `CLAUDE.md`. No GitHub-hosted runner
  fallback is configured for this INTENT's gates. This is the highest-
  remaining single-point-of-failure risk and is not mitigated in v1.
- **mypy fast-tier false negatives.** Section 2 specifies mypy on changed
  modules only (no reverse-import closure) for the fast tier. A type
  regression introduced in a base module may pass the fast tier on a PR
  that only touches a downstream consumer if mypy is not invoked on the
  base module. The full tier on push-to-main catches this; fast-tier
  miss-rate is the accepted cost of diff-aware scope in v1.
- **Section 7 sync labels conflate PR-time cost with promotion suitability.**
  A `sync` label on `terraform/**` means "main-red here is expensive on PR
  merge"; it does NOT mean "this commit gets a longer bake before SIT/PROD
  promotion." Promotion bake-time is governed by L9/L10 green-streak gates,
  independent of merge-mode. Reconciliation is a v2 concern when SIT exists.
- **L1 rollback chicken-and-egg.** Switching `ci.yml` from full -> fast on
  PR is a one-line YAML change. Reverting after a fast-tier-missed bug
  landed on main requires diagnosis through ci-rca, which this INTENT
  itself makes load-bearing. The `validate-fast-tier-reshape` plan must
  include an emergency-revert rollback step that bypasses ci-rca (e.g., a
  workflow_dispatch trigger for the full tier on the affected PR).
- **`--ignore-budget` could leak into CI.** Section 2 calls the flag
  local-only by intent, but `validate.py` does not refuse the flag when
  `CI=true` is detected. `validate-fast-tier-reshape` must add this CI
  guard (refuse `--ignore-budget` if `os.environ.get("CI") == "true"`).
- **Forward-fix branch exemption is convention-only.** Section 5 says the
  forward-fix branch is exempt from L6 auto-merge pause. The mechanism for
  identifying that branch (naming convention `agent/fix-ci-{rec-id}` or PR
  body reference to the ci-rca rec ID) is forgeable. Acceptable for solo-
  developer threat model; revisit if multi-agent concurrency increases.
- **Section 5 soft-cap on non-automatable recs (250) is informational
  only.** Not mapped to a Section 2.5 enforcement file. If the cap breaches
  the alert surfaces in preflight; no hard gate prevents accumulation.
  Acceptable for v1 while the executor is offline.

### Explicitly rejected risk concern

- **No continuous watchdog for ci-rca liveness fallback.** A round-2
  critique flagged that the 30-min liveness fallback (above) only fires
  when a `/plan` or `/implement` session starts. A "quiet weekend" with
  main red and ci-rca dead would not surface the alert until the next
  session. This concern is explicitly rejected as not load-bearing for v1:
  the sandbox-tolerant red-main model plus single-developer cadence makes
  next-session detection sufficient. The cost of a continuous watchdog
  (a separate cron workflow, more runner contention) outweighs the benefit
  at current scale. Revisit when (a) multiple autonomous agents operate
  concurrently, or (b) PROD exists and depends on sandbox green-streak.

---

## 10. Acceptance and Convergence

This INTENT document is the authoritative specification. Subsequent changes
to the CI/CD model land via:

- Amendments to this document (with Decision Record updates as required).
- Follow-on IMPLEMENTATION plans referenced in Section 2.5 and Section 9.

### Sequencing constraint (partially resolved)

**`planning-queue-governance` landed as commit a124c04 on 2026-05-13.** L5
enforcement (ci-rca HARD BLOCK, Related-Work Check, three preflight alert
bullets, and L5 hard-block + L2 auto-merge-pause semantics in
`.claude/skills/planning/SKILL.md`) is now in force. This INTENT may be cited
as in-force for L5 and the planning-queue features from that plan.

**`validate-fast-tier-reshape` landed on 2026-05-13.** Budget assertion
(Section 2), breach rec filing, bypass rec filing, budget bypass alert in
`session_preflight`, and `get_changed_files()` origin/main semantics are now
BUILT. The fast-tier contract is real. `ci-workflow-restructure` may now flip
PR CI to `--pre`.

**`ci-workflow-restructure` landed on 2026-05-19.** L1 (PR CI = fast tier), L3 (push-to-main = full tier, non-duplicate), L8 (3-hourly canary), and single-runner concurrency are now BUILT. L6 (auto-merge pause) is explicitly deferred per the planning conversation that scoped this plan; INTENT Section 2.5 L6 rows are marked DEFERRED. L2 and the ci-rca liveness fallback follow L6's deferral state. The INTENT is cite-as-in-force for L1/L3/L8; the deferred layers remain target-state.

The model is considered converged when:

1. Fast tier runs in <=5 min on typical diffs (enforced by assertion).
2. Full tier runs on every push to `main` and hourly via cron with concurrency
   control.
3. ci-rca recs hard-block the planning queue and pause auto-merge, with
   defined "related work" semantics (Section 5) and a liveness fallback
   (Section 9).
4. The non-automatable backlog is no longer surfaced as a mandatory discussion
   item (revisited when Decision 67 reverses; soft-capped at 250 in the
   interim).
5. Budget breaches file recs and surface in preflight (Section 2.5).
6. Sandbox/SIT/PROD promotion train is documented (Section 6) but not yet
   built (L9-L10 deferred).

Convergence is partial today: this INTENT document is the design artefact.
Implementation lands incrementally via the follow-on plans listed in
Section 2.5 and Section 9.
