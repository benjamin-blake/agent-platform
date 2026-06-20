# INTENT: Agent-Native Terraform CI/CD Architecture

Status: PROPOSED -- candidate decision **CD.NN** (ratify as a numbered Decision via the log-decision path
when Wave 1 ships, matching CD.31->Decision 78 / CD.33->Decision 81).
Scope: single-account sandbox PLATFORM environment (`terraform/personal/` + `terraform/github/`).
Extends (does NOT overturn): Decision 77 (auto-apply guard), Decision 35 (apply human-gated), Decision 76
(async wake), Decision 89 / CD.20 (`main-protection` ruleset).
**Design-of-record for the architecture below.** The tier_items' canonical home is `docs/ROADMAP-PLATFORM.yaml`
(transcribed from Section 8 post-review); this doc is design rationale, NOT the source-of-record for the
tier_items themselves.
Cross-reference: the T2.16b retrospective records the failure modes; THIS doc owns the CI architecture.

---

## 1. Problem

Three gaps surfaced by the T2.16b RDS->Neon migration (the iterative-grant churn of PRs #75-#77):

1. **Apply failures are non-sticky and unobserved.** `terraform-apply-sandbox.yml` runs decoupled from
   validate-CI. A failed apply is a single red run; a later unrelated green run visually supersedes it, and the
   failure never reaches the `ci-rca` agent. There is no durable "is main converged?" signal.
2. **No speculative plan before merge.** `terraform plan` first runs *post-merge* inside the auto-apply
   pipeline, so neither human nor agent sees the diff (or the guard's verdict) before deciding to merge.
3. **The self-grant bootstrap.** The `github_ci_apply` CI role cannot grant itself privileges through the
   guarded pipeline it gates -- every PR touching its own policy reds its push run (the guard fail-closes on
   IAM-sensitive diffs), forcing manual branch-first applies from a privileged terminal (the laptop-apply
   anti-pattern).

## 2. Current state (what is already live)

| Capability | State | Evidence |
|---|---|---|
| Deterministic auto-apply guard (fail-closed on destroy/IAM/trust) + LLM subagent plan review | LIVE | `scripts/terraform_apply_guard.py`, `terraform-apply-sandbox.yml` (Decision 77) |
| `main-protection` branch ruleset, `enforcement = "active"` | LIVE | `terraform/github/repo.tf:55` -- requires `pr-validate` + `terraform-validate`, linear history, PR-required, `required_approving_review_count = 0`, `strict_required_status_checks_policy = false`, **`bypass_actors` admin `bypass_mode = "always"`** |
| Async PR wake (`signal-green` comment + `subscribe_pr_activity`) | LIVE but **PR-scoped only**; **unsubscribes at merge** | Decision 76; `ci.yml` `signal-green` fires on `pull_request`; the subscribe tool is open-PR-scoped and won't deliver if a PR Steward watches -- no post-merge/push wake surface |
| Native S3 state locking | LIVE | `terraform/personal/main.tf` (`use_lockfile = true`) |
| `ci-rca` agent | LIVE; scoped to `['CI','Main Canary']`; **cron runs DO reach it** (`head_branch == default_branch` holds for `schedule`) | `.github/workflows/ci-rca.yml:8,30` -- `terraform-apply-sandbox` is NOT yet in its `workflows:` |
| PR-context AWS role (`github_ci_pr`) state-read scope | **athena/* + iceberg/* only (NO `tfstate`)** | `terraform/personal/oidc.tf` -- a speculative plan cannot read state with this role |
| `workflow_run.pull_requests[]` on push-triggered workflows | **EMPTY** | `docs/plans/PLAN-ci-merge-gate-hardening.md` (ci-rca guards it with `!= ''`) -- a post-merge workflow cannot get the PR number from this field |
| Speculative `terraform plan` on PRs | **ABSENT** | plan only runs in `terraform-apply-sandbox.yml` on push to main |
| Durable convergence signal (advisory + server-side precondition) | **ABSENT** | `main-protection` requires `terraform-validate` (syntax), not apply-success |
| GitHub Environment + required-reviewer gate for the apply | **ABSENT** (no repo precedent) | only `deploy.yml`'s `environment` *input string* exists; no job-level `environment:` object anywhere |
| Scheduled drift detection | **ABSENT** | no cron `terraform plan` workflow |

The apply-workflow's comment "Branch protection / required status checks are not available" is **stale** --
`main-protection` is live. The controls this design needs are the genuine net-new work.

## 3. Design principles (agent-native)

- **Asynchrony over raw speed.** The metric is agent-*blocking* time, not wall-clock convergence. **The design
  baseline is: the agent merges, ends its turn, and runs post-apply validation on its next planning session** --
  the durable convergence record (5.5) is the source of truth, read on the next turn. A same-turn **post-merge
  wake is a best-effort optimisation only** (Wave 1 attempts it; the design does NOT depend on it): the apply
  workflow resolves the originating PR from the merge commit SHA (GitHub "PRs associated with a commit" API --
  `workflow_run.pull_requests[]` is empty for push events) and comments there. **This likely fights the
  `subscribe_pr_activity` contract** (unsubscribe-at-merge, no delivery under a PR Steward, open-PR-scoped), so
  Wave 1 proves it live or keeps the next-session baseline -- never a `sleep`/`/loop` poll (Decision 76).
- **Plan anywhere, apply only in CD.** Local/web-container `plan` stays (fast, read-only). Local/manual `apply`
  is eliminated -- including for gated changes, which move to a gated *CD* apply, not a laptop apply.
- **Native controls gate; the guard polices content.** GitHub branch-protection + Environments own
  *authorization to merge/deploy*; the Decision-77 guard narrows to *plan-content policy* (no destroy/IAM/trust
  in an auto-apply). A Decision-75 frame-challenge: the guard was partly a workaround for the absence of branch
  protection, which is now live.
- **Convergence is anchored server-side.** The apply job *refuses to run* against a red convergence record --
  unbypassable by any merge-path actor, independent of whether any agent is watching. This is the **sole hard
  block**. A PR-time `terraform-converged` status is an **advisory signal only** (NOT a required check):
  required would either wedge the autonomous fix-merge once a record goes red, or be bypassed by the
  admin-`always` merge anyway.
- **Drift alarms, never auto-remediates** (Decision 55).
- **Privilege-tiering.** The pipeline cannot manage its own privileges; the CI/CD role's own IAM lives in a
  separate tier applied out-of-band.

## 4. Target architecture (flow)

```
PR opened ─▶ [speculative plan: NET-NEW read-only github_ci_plan role, fork-gated] ─▶ redacted diff + guard's PREDICTED verdict as PR comment
   │                                                                                          │
   │                                                                          human/agent reviews a SPECIFIC plan
   ▼                                                                                          ▼
required checks: pr-validate, terraform-validate ; advisory: terraform-converged(reads record; pass-on-absent) ─▶ squash-merge
   │
   ├─ routine (guard PASS) ─▶ apply job: PRECONDITION reads record (refuse if red) ─▶ apply SAVED plan (stale ⇒ STOP) ─▶ write record (apply-identity-only; ALWAYS-run, red-on-failure) ─▶ [best-effort: resolve PR from merge SHA + comment to wake] ─▶ post-apply validation (baseline: next planning session, reads record)
   │
   └─ high-blast (guard FAIL-CLOSED: IAM/trust/destroy) ─▶ job declares Environment tf-gated-apply ─▶ required reviewer approves JOB EXECUTION ─▶ apply (privileged role; OIDC trust pinned to refs/heads/main) ─▶ write record
                                                                                                                                                          │
cron ─▶ [drift: wrap `terraform plan`; 0=clean / 2=drift / 1=error / lock-fail=skip] ─▶ drift ⇒ record-red + file rec DIRECTLY via ops portal (alarm only)
```

## 5. Component designs

### 5.1 Speculative plan on PRs
A `terraform plan` job on infra PRs, running under a **net-new PR-context role `github_ci_plan`** (trust
`refs/pull/*`; **`tfstate/personal/*` read-only** + broad `Describe/Get/List`; zero mutate; no secret-value
reads). The existing `github_ci_pr` role is scoped to `athena/*` + `iceberg/*` and **cannot read tfstate**, so
this role is genuinely new (Wave 2). **Fork-PR gating is mandatory** (mirror `ci-rca.yml`'s fork/default-branch
gate): granting `tfstate` read to a `refs/pull/*`-trusted role must not expose full infra state to fork
contributors. The job posts the plan summary + the guard's **predicted** verdict (auto-applyable vs would-be-
gated) as a **redacted** PR comment (`-no-color`, no raw `show -json`, suppress `sensitive`, minimise ARNs).
**Open question:** restrict speculative comments to `terraform/personal/**`, or also `terraform/github/**`?

### 5.2 Apply-the-saved-plan (not re-plan-at-merge)
The exact `plan.bin` reviewed on the PR is persisted (Actions artifact) and applied at merge. **Terraform's own
staleness guard is load-bearing**: `terraform apply <saved-plan>` *refuses* to apply if the state serial moved
since the plan was produced. Given `main-protection` has `strict_required_status_checks_policy = false`, this
matters. **On staleness the run STOPS** (errors + files a rec) -- it does NOT silently re-plan-and-apply, which
would apply a diff nobody reviewed; a human/agent re-opens with a fresh plan. The persisted `plan.bin` is
**plaintext and may surface sensitive values**, so the artifact is access-controlled (short retention, private)
and treated as sensitive.

### 5.3 Routine auto-apply, async
Unchanged guard + LLM-review for guard-PASS plans, plus a **server-side convergence precondition** (5.5). For
re-engaging the agent post-apply, **the baseline is next-planning-session re-check** of the convergence record
(authoritative). A same-turn **post-merge wake is best-effort only**: the apply workflow resolves the
originating PR from the merge commit SHA (`GET /repos/{owner}/{repo}/commits/{sha}/pulls` -- NOT
`workflow_run.pull_requests[]`, empty for the push-triggered apply) and comments on it, and the agent would hold
its PR subscription through apply (a convention change in the implement skill). **But this likely fights the
`subscribe_pr_activity` contract** (unsubscribe-at-merge; no delivery under a PR Steward; open-PR-scoped), so
Wave 1 *attempts and proves* it live -- and on failure simply keeps the next-session baseline (never a poll,
Decision 76). The design does not depend on the wake.

### 5.4 Gated CD apply (high-blast-radius)
IAM/trust/destroy plans (the guard's fail-closed set) route to a job that declares a **GitHub Environment**
(`tf-gated-apply`) with a **required reviewer**. **The Environment gates JOB EXECUTION** -- the apply job does
not start until a human approves.

**Security model:** we do **NOT** rely on an `environment:` claim in the OIDC `sub` as an authorization boundary
-- that claim is minted by *any* job merely declaring the environment (a known GitHub footgun). The privileged
apply role's OIDC trust stays **pinned to `refs/heads/main`** (as today). The boundary is "the privileged apply
job will not execute without reviewer approval," enforced by the Environment protection rule, not the token. No
workflow uses a job-level `environment:` today, so **Wave 3 prototypes one first** and verifies a non-gated
workflow declaring the same environment cannot bypass the reviewer.

**Single-account scope (Decision 77 clause 5):** an in-account approval gate, NOT a revival of Decision 24's
retired multi-account promotion. **Solo-dev / agent reality:** the agent **cannot approve its own deployment**,
so gated changes intentionally **pause agent autonomy**. The routine/gated split (Section 6) keeps the gate rare.

### 5.5 Sticky convergence signal
The apply job writes a **convergence record** -- a small S3 object (`.../tfstate/personal/sandbox/
convergence.json`, `{commit, status, plan_sha, ts}`) -- with **write-IAM restricted to the apply identity
alone** (the integrity anchor; a commit status alone is spoofable). **The record write is an always-run step
(`if: always()`) that writes `status=red` on apply failure** -- otherwise a failed apply would skip the write
and leave the record at its prior green value, defeating the precondition in exactly the case it must catch.
**The sole hard block is server-side: the apply job reads this record as a precondition and refuses to apply
when main is non-converged** (an *absent* record = first-apply-allowed) -- unbypassable by any merge-path actor.
A PR-time **`terraform-converged`** status is **advisory only -- NOT added to `main-protection`
`required_status_checks`**: making it required would either wedge the autonomous path (once a record is red, the
agent cannot merge the fix that clears it) or be bypassed by the admin-`always` merge regardless, so it does no
useful blocking. It **passes-on-absent-record** (the first *apply* writes the first record -- never a human
seed, preserving the apply-only write-IAM invariant) and surfaces the red state for visibility. Net: a broken
apply blocks the next *apply* server-side regardless; the advisory status just makes it visible.

**Amendment (2026-06-10, pre-Wave-1 design review; mirrored in T2.20's roadmap entry):**
(a) **Unlatch = dispatch-ack.** A red record blocks all push-triggered applies, and a refusal never
overwrites the record. Clearing requires a `workflow_dispatch` acknowledge-and-retry run whose input names the
red record's commit (or rec id); only a successful apply from that path writes green. The dispatch actor +
input are the audit trail; the agent may dispatch via the MCP actions trigger after the rec review (Decision
55/72), so autonomy is preserved. Auto-allow-descendants is rejected: on linear-history main every commit is a
descendant, so the latch would never latch.
(b) **Applies serialize** via a workflow `concurrency` group (`cancel-in-progress: false`), closing the
read-precondition -> apply -> write-record race between rapid merges and keeping state-lock-timeout noise out
of ci-rca.
(c) **The record lives in its own S3 prefix** (e.g. `convergence/personal/sandbox.json`), NOT under `tfstate/`
as sketched above: the advisory PR status reads it at PR time, and "`github_ci_pr` cannot read tfstate" must
stay cleanly auditable -- the PR role gets read on the record prefix only. Write-IAM is
**pipeline-writer-identity-only** via a shared record-writer policy ("apply identity alone" would contradict
5.6's drift red-flip: the drift identity joins at Wave 5). Never PR roles, never laptops. `plan_sha` is null
until Wave 2 introduces saved plans.
(d) **Refusals dedupe; framing scoped.** A refusal-while-red carries a distinguishable failure marker and
ci-rca dedupes it against the open red-record rec (coordinate with T1.13's structured taxonomy). The
forced-failure verification rec is closed via `update_rec` annotated as synthetic. "Unbypassable" means by
merge-path actors -- NOT against workflow self-edit; that residual is Wave 4 plus the CD.35 authority budget
(detail points 6-9), and Decision text must not overclaim.

### 5.6 Drift detection
A scheduled workflow runs `terraform plan` for drift. **Exit-code handling is explicit** (not assumed from
`-lock-timeout`): `terraform plan` acquires the state lock and **errors (exit 1) on a held lock -- it does not
skip**; `-detailed-exitcode` returns 0=no-change / 2=drift / 1=error, and a lock-timeout is a 1 that collides
with real errors. The drift job **wraps the plan and distinguishes a lock-acquisition failure (skip this cycle,
no alarm) from a genuine error (alarm) from drift (exit 2 -> alarm + rec)**. Drift ⇒ flip the convergence record
+ file a rec. **Alarm only -- never auto-`apply`** (Decision 55).

### 5.7 RCA wiring (two distinct paths)
- **Apply failures** (push-to-main `terraform-apply-sandbox`) file `source=ci_rca` recs by **adding
  `terraform-apply-sandbox` to `.github/workflows/ci-rca.yml`'s `workflows:` trigger** (today only
  `['CI','Main Canary']`). ci-rca's `head_branch == default_branch` gate fits push-to-main. (Wave 1.)
- **Drift** (the `schedule`-triggered workflow) **files its rec DIRECTLY via the ops portal**, NOT through
  ci-rca: drift is a structured state-vs-code delta, not a CI-log *failure* with logs to root-cause, so it does
  not fit ci-rca's log-RCA model. (Cron runs *do* reach ci-rca -- `Main Canary` is a cron workflow in its
  `workflows:` list, so cron `head_branch` is the default branch -- so the reason is model-fit, not gating.)
  (Wave 5.)

### 5.8 Privilege-tiering / bootstrap root
The CI/CD role's *own* IAM (`github_ci_apply`'s policy) and other "manage-the-manager" resources move into a
separate **`terraform/bootstrap/`** root with its own state, applied by the privileged tier (PlatformAdmin, via
the gated path in 5.4) out-of-band. This breaks the self-grant cycle: the pipeline never plans its own
permissions. **Absorbs rec-2079** (consolidate `IAMRoleReconcile` + `IAMPlatformRolesRead`). Baseline is the
post-Phase-2 `github_ci_apply` state now on main (`oidc.tf`, #82). The bootstrap root's state bucket/lock + apply
identity are **provisioned once by a documented one-time admin action**, then never managed by the pipeline.

### 5.9 Guard <-> native-controls reconciliation
- **GitHub native controls** own *authorization*: required checks (`pr-validate`, `terraform-validate`), linear
  history, the Environment reviewer gate.
- **The Decision-77 guard** narrows to *content policy*: classify a plan as auto-applyable (routine) vs gated
  (IAM/trust/destroy) and feed the predicted verdict to the PR (5.1). It remains fail-closed; it stops
  *deciding who may merge*.
A Decision-75 frame-challenge made concrete.

## 6. The autonomy boundary (routine vs gated)

| Change class | Path | Who acts | Agent-autonomous? |
|---|---|---|---|
| Data/compute resources, tags, non-IAM config (guard PASS) | speculative plan -> merge -> apply saved plan (async, server-side convergence precondition) | agent end-to-end | YES |
| IAM/role/trust changes, `delete`/`destroy` (guard FAIL-CLOSED) | speculative plan -> merge -> Environment reviewer approval -> gated CD apply | human approves; CD applies | NO (by design) |
| The CI/CD role's *own* IAM | `terraform/bootstrap/` root, privileged tier, out-of-band | PlatformAdmin | NO (by design) |
| Drift correction | alarm + rec only | human triages via `/plan` | N/A (never auto) |

## 7. Build vs buy

**Build (DIY in GitHub Actions) -- chosen.** The existing guard + LLM-review is already past Atlantis's feature
set, and in-repo workflows preserve agent-legibility over an external control plane. Rejected-for-now: Terraform
Cloud free tier (speculative plans + state, but drift is paid + off-repo control plane); Atlantis (self-hosted
server, no native drift); Spacelift/env0 (external SaaS, over-tooled for one sandbox). Revisit at multi-account
(`live_full`).

## 8. Roadmap decomposition (transcribe to ROADMAP-PLATFORM.yaml AFTER the zero-context reviews)

Each item is a **standalone IMPLEMENTATION plan** (Decision 67 STRATEGIC-suspension; never STRATEGIC). All V3.
`depends_on` logical; ids assigned at transcription. "Files touched" spans CI / IAM / instruction surfaces.

| Wave | Item | Depends on | Effort | Exit criteria (behavioural) | Files touched |
|---|---|---|---|---|---|
| **1 (first)** | **Convergence substrate + apply-RCA + post-merge wake (best-effort)**: apply job writes the S3 convergence record (apply-identity-only write-IAM; **always-run, red-on-failure**) + reads it as a server-side precondition; **advisory** `terraform-converged` status (pass-on-absent; NOT a required check); add `terraform-apply-sandbox` to `ci-rca.yml`; attempt the best-effort post-merge wake (resolve PR from merge SHA + comment; hold subscription) with next-session re-check as the baseline | -- (extends live CD.20) | M | Force an apply failure -> the record is written `red` by the always-run step -> the NEXT apply is refused server-side AND a `source=ci_rca` rec is filed AND the advisory `terraform-converged` shows red; a passing apply writes the first record from absent; the post-merge wake is proven live OR the next-session baseline is confirmed | `terraform-apply-sandbox.yml`, `.github/workflows/ci-rca.yml`, `terraform/personal/oidc.tf`, implement skill (hold-subscription-through-apply), `terraform/CLAUDE.md` |
| **2** | **Speculative plan + apply-saved-plan**: NET-NEW `github_ci_plan` role (PR-trusted, `tfstate` read-only, fork-gated); PR plan job posts redacted diff + predicted guard verdict; persist access-controlled `plan.bin`; merge applies the saved plan; **stale ⇒ STOP + rec** | Wave 1 | M | A PR shows the redacted plan diff + verdict; the merge applies the *same* `plan.bin`; a deliberately staled plan **errors and files a rec** (no silent re-apply); fork PRs cannot read `tfstate` | `terraform/personal/oidc.tf`, `terraform-apply-sandbox.yml`, planning skill (Infra assessment) |
| **3** | **Gated CD apply via GitHub Environment**: create `tf-gated-apply` Environment + required reviewer; route guard-fail-closed plans through a job declaring it; OIDC trust **stays pinned to `refs/heads/main`** (Environment gates execution, not the token); retire the manual branch-first convention | Wave 1 | L | An IAM/destroy change auto-routes to the Environment, blocks on approval, then applies in CD; a non-gated workflow declaring the same `environment:` still cannot bypass the reviewer | AGENTS.md (Safety), `docs/contracts/environment-taxonomy.md`, implement skill, `terraform/personal/oidc.tf` |
| **4** | **Privilege-tiering / bootstrap root**: `terraform/bootstrap/` root + own state for the CI/CD role's own IAM; migrate `github_ci_apply` policy; absorb rec-2079; one-time admin provisioning of the bootstrap state/identity | Wave 3 | L | A change to `github_ci_apply`'s own policy applies via the bootstrap tier with NO red push run on the main pipeline | `terraform/CLAUDE.md`, `docs/contracts/environment-taxonomy.md`, `terraform/personal/oidc.tf` |
| **5** | **Drift detection**: scheduled `terraform plan` with explicit exit-code handling (0=clean/2=drift/1=error/lock-fail=skip); drift -> record-red + a rec filed **directly via the ops portal** (NOT ci-rca -- drift is a state-delta finding, not a CI-log failure); alarm-only | Wave 1 | S | An out-of-band console change is detected within one cron cycle and filed as a rec via the portal; a held lock skips the cycle without alarming; no auto-apply | new drift workflow, `scripts/ops_data_portal.py` (invoke), `terraform/CLAUDE.md` |
| **X (cross-cutting)** | **Convention synchronization + guard narrowing + decision**: consolidate the apply-model convention to `docs/contracts/environment-taxonomy.md` as SoT; reduce AGENTS.md + terraform/CLAUDE.md to a one-line reference; light-touch the implement skill's human-gated-action example; narrow the guard to content-policy (5.9); ratify CD.NN as a numbered Decision | Waves 1-4 | S | The apply-model statement lives in ONE SoT, the others reference it; `prompt_compliance.py` passes; Decision N logged | `docs/contracts/environment-taxonomy.md`, AGENTS.md, `terraform/CLAUDE.md`, implement skill, `scripts/terraform_apply_guard.py` |

## 9. Instruction-surface synchronization

The apply-model convention ("apply is human-gated EXCEPT the sandbox auto-apply...") lives in **three** surfaces
today, duplicated -- itself drift-by-design: `AGENTS.md:24` (Safety), `terraform/CLAUDE.md:10`, and
`docs/contracts/environment-taxonomy.md:35-36` (the per-environment table). A **fourth** surface, the implement
skill (`SKILL.md:95`), carries only a *tangential* mention ("awaiting a human-gated action e.g. terraform apply
-> mark BLOCKED") that needs a light touch when the gated path changes. (The planning skill and
`src/data/handlers/CLAUDE.md` carry an unrelated IAM-precedence rule -- "apply before Lambda deploy" -- NOT this
convention; they are out of scope.) Wave X **consolidates the canonical statement into
`docs/contracts/environment-taxonomy.md`** (source of truth) and reduces AGENTS.md + terraform/CLAUDE.md to a
one-line reference (agent-first collocation rule). Edits execute in the Waves' IMPLEMENTATION plans -- NOT here.

## 10. Decision logging

Add **CD.NN** to the roadmap now (codename, alongside the tier_items). Ratify as a numbered **Decision N** when
Wave 1 ships (CD.31->Decision 78 / CD.33->Decision 81 precedent). The Decision records the guard<->native-controls
division (5.9), the routine/gated autonomy boundary (Section 6), the corrected Environment-gates-execution
security model (5.4), the advisory-not-required convergence check (5.5), and the rejected
guard-self-grant-exception.

## 11. Risks / known gaps / open questions

- **Convergence-record integrity (primary anchor).** Rests on apply-identity-only write-IAM, the always-run
  red-on-failure write (5.5), AND the server-side apply precondition. Wave 1 acceptance must prove all three.
- **Post-merge wake is best-effort and likely fights the subscription contract.** `subscribe_pr_activity`
  unsubscribes at merge, won't deliver under a PR Steward, and is open-PR-scoped -- so a held-subscription wake
  on a merged PR is probably-broken, not merely unproven. The **design baseline is next-planning-session
  re-check** (poll-free); Wave 1 attempts the live wake but nothing depends on it.
- **Speculative-plan exposure.** Even redacted, plans leak topology into PR comments; `github_ci_plan` must be
  genuinely least-priv and fork-gated. Open: plan-comment `terraform/github/**` too, or only
  `terraform/personal/**`?
- **Environment gating has no repo precedent.** No job-level `environment:` exists; Wave 3 prototypes one and
  proves a non-gated workflow declaring the same environment cannot bypass the reviewer.
- **`terraform-converged` is advisory, not required.** A required check would wedge the autonomous fix-merge
  (the agent cannot merge the fix that clears a red record) or be admin-bypassed anyway. The server-side apply
  precondition is the sole hard block; the advisory status is for visibility.
- **Bootstrap-root chicken-and-egg.** State bucket/lock + apply identity provisioned by a documented one-time
  admin action, then never managed by the pipeline.
- **Lock contention.** Drift cron + auto-apply + gated apply share one S3 lockfile; the drift job's explicit
  lock-fail=skip handling (5.6) is required so a stuck apply does not cascade.

## 12. Scoping guards (decision-alignment, from the decision-scout gate)

- **Decision 67 (STRATEGIC suspended):** every Section-8 wave is a standalone IMPLEMENTATION plan.
- **Decision 24 (multi-account superseded):** the 5.4 Environment is a single-account approval gate
  (Decision 77 clause 5), not multi-account promotion.
- **Decision 44 / 79 (executor boundary):** CI/CD pipeline files are build-tooling, not executor machinery;
  this design touches none of Decision 44's boundary table.
- **Decision 55:** drift + apply failures alarm and file recs; nothing auto-remediates.
