# INTENT: Agent-Native Terraform CI/CD Architecture

Status: PROPOSED -- candidate decision **CD.NN** (ratify as a numbered Decision via the log-decision path
when Wave 1 ships, matching CD.31->Decision 78 / CD.33->Decision 81).
Scope: single-account sandbox PLATFORM environment (`terraform/personal/` + `terraform/github/`).
Extends (does NOT overturn): Decision 77 (auto-apply guard), Decision 35 (apply human-gated), Decision 76
(async wake), Decision 72 / CD.20 (`main-protection` ruleset).
Source-of-record for: the platform-roadmap tier_items transcribed from Section 8 (ids assigned at transcription).
Cross-reference: the T2.16b retrospective records the failure modes; THIS doc owns the CI architecture. Do not
double-author the CI tier_item.

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
| `main-protection` branch ruleset, `enforcement = "active"` | LIVE | `terraform/github/repo.tf:55` -- requires `pr-validate` + `terraform-validate`, linear history, PR-required, `required_approving_review_count = 0`, `strict_required_status_checks_policy = false`, admin bypass `always` |
| Async event-driven merge/wake (`signal-green` comment + `subscribe_pr_activity`) | LIVE | Decision 76 |
| Native S3 state locking | LIVE | `terraform/personal/main.tf` (`use_lockfile = true`, no DynamoDB table) |
| `ci-rca` agent (filed on `validate.py` CI failure) | LIVE | `.github/workflows/ci-rca.yml` (Decision 72/73) |
| GitHub-hosted CI via OIDC (self-hosted runner retired) | LIVE | CD.21; `github-ci-branch` / `github-ci-pr` roles |
| Speculative `terraform plan` on PRs | **ABSENT** | plan only runs in `terraform-apply-sandbox.yml` on push to main |
| Durable convergence signal / required convergence check | **ABSENT** | `main-protection` requires `terraform-validate` (syntax), not apply-success |
| GitHub Environment + required-reviewer gate for the apply | **ABSENT** | only the legacy `deploy.yml` references an environment |
| Scheduled drift detection | **ABSENT** | no cron `terraform plan` workflow |

The apply-workflow's comment "Branch protection / required status checks are not available" is **stale** --
`main-protection` is live. The controls this design needs (convergence required-check; Environments) are the
genuine net-new work.

## 3. Design principles (agent-native)

- **Asynchrony over raw speed.** The metric is agent-*blocking* time, not wall-clock convergence. The agent
  merges, ends its turn, and an apply-complete webhook wakes it -- absorbing apply latency without a human in
  the loop or a spinning agent. (Extends Decision 76.)
- **Plan anywhere, apply only in CD.** Local/web-container `plan` stays (fast, safe, read-only). Local/manual
  `apply` is eliminated -- including for gated changes, which move to a gated *CD* apply, not a laptop apply.
- **Native controls gate; the guard polices content.** GitHub branch-protection + Environments own
  *authorization to merge/deploy*; the Decision-77 guard narrows to *plan-content policy* (no destroy/IAM/trust
  in an auto-apply). This is a Decision-75 frame-challenge: the guard was partly a workaround for the absence of
  branch protection, which is now live.
- **Convergence is sticky and unforgeable.** "main is converged" is a durable record written only by the apply
  identity; a non-converged main blocks new merges. Failure cannot be masked by a later green run.
- **Drift alarms, never auto-remediates** (Decision 55). On an auto-apply system, auto-correcting drift risks
  clobbering a deliberate out-of-band change or oscillation.
- **Privilege-tiering.** The pipeline cannot manage its own privileges. The CI/CD role's own IAM lives in a
  separate tier applied out-of-band.

## 4. Target architecture (flow)

```
PR opened ──▶ [speculative plan, read-only role] ──▶ post redacted diff + guard's PREDICTED verdict as PR comment
   │                                                          │
   │                                            human/agent reviews a SPECIFIC plan
   ▼                                                          ▼
required checks: pr-validate, terraform-validate, terraform-converged(reads main's convergence record) ──▶ merge (squash)
   │
   ├─ routine change (guard PASS: no destroy/IAM/trust) ──▶ auto-apply the SAVED plan ──▶ convergence record ──▶ apply-complete webhook wakes agent ──▶ post-apply validation
   │
   └─ high-blast change (guard FAIL-CLOSED: IAM/trust/destroy) ──▶ GitHub Environment (required reviewer) ──▶ human approves ──▶ gated CD apply (privileged role, OIDC-scoped to the environment) ──▶ convergence record
                                                                                                                                                                          │
cron ──▶ [drift detect: terraform plan -detailed-exitcode, -lock-timeout] ──▶ non-empty ⇒ flip convergence record red + file source=ci_rca rec (alarm only)
```

## 5. Component designs

### 5.1 Speculative plan on PRs
A `terraform plan` job on PRs touching `terraform/personal/**` (or `terraform/github/**`), running under a
**read-only plan role** (broad `Describe/Get/List`, zero mutate, no `secretsmanager:GetSecretValue` on secret
*values*). It posts the plan summary + the guard's **predicted** verdict (auto-applyable vs would-be-gated) as a
PR comment. **Comment redaction is mandatory**: `-no-color`, no raw `terraform show -json`, suppress
`sensitive` values and minimise ARNs -- the agent auto-posts, so the comment is a standing data-exposure
surface. The predicted verdict lets the agent decide the merge path before merging.

### 5.2 Apply-the-saved-plan (not re-plan-at-merge)
The exact `plan.bin` reviewed on the PR is persisted (Actions artifact) and applied at merge. **Terraform's own
staleness guard is the safety net**: `terraform apply <saved-plan>` *refuses* to apply if the state serial
moved since the plan was produced -- it fails closed. Given `main-protection` has
`strict_required_status_checks_policy = false` (branches merge without being up-to-date), this fail-closed
behaviour is load-bearing: a stale saved plan errors rather than applying a diff nobody reviewed, and the
pipeline falls back to a re-plan. "What you reviewed is what applies, or nothing applies."

### 5.3 Routine auto-apply, async
Unchanged guard + LLM-review path for guard-PASS plans, plus: on apply completion the workflow emits an
**apply-complete signal** (the `signal-green` mechanism, extended) that wakes the subscribed agent session for
post-apply validation. The agent never `sleep`/`/loop`s (Decision 76).

### 5.4 Gated CD apply (high-blast-radius)
IAM/trust/destroy plans (the guard's existing fail-closed set) route to a job targeting a **GitHub Environment**
with a **required reviewer**. The privileged apply role's IAM **trust policy is OIDC-scoped to that
environment** (`...:environment:tf-gated-apply` in the `sub` claim), so the privileged role is assumable *only*
from the gated job -- never from a branch, a laptop, or the routine pipeline. This is the native implementation
of Decision 35 (human-gated apply) and replaces the manual branch-first apply convention.

**Single-account scope (Decision 77 clause 5):** the Environment is an *in-account approval gate*, NOT a
revival of Decision 24's retired multi-account (`sandbox/staging/production`) promotion model. One AWS account
until the product `live_full` trigger.

**Solo-dev / agent reality:** a GitHub Environment reviewer gate means *a human clicks approve* -- the agent
**cannot approve its own deployment** (it is the triggering actor). This is correct for IAM/destroy and means
**gated changes intentionally pause agent autonomy.** The design's job is to make the routine/gated split clean
(Section 6) so the agent rarely hits the gate.

### 5.5 Sticky convergence signal
The apply job writes a **convergence record** -- a small S3 object (e.g. `s3://.../tfstate/personal/sandbox/
convergence.json` carrying `{commit, status, plan_sha, ts}`) -- with **write-IAM restricted to the apply
identity alone** (the integrity anchor; a commit status alone is spoofable by anything that can write its
context). A PR-time required job **`terraform-converged`** reads that record and **fails if main's last apply
did not converge**, and is **added to `main-protection`'s `required_status_checks`**. Net: a broken apply
blocks the *next* merge until a successful apply flips the record -- unmaskable by an unrelated green run. (This
is Decision 73's forward-fix/merge-pause made terraform-aware.)

### 5.6 Drift detection
A scheduled workflow (cron; `main-canary.yml` is the template) runs `terraform plan -detailed-exitcode` with
`-lock-timeout` so it coexists with the native S3 `use_lockfile` (a held lock ⇒ skip this cycle, do not error
the canary). Non-empty plan ⇒ flip the convergence record + file a `source=ci_rca` rec. **Alarm only -- never
auto-`apply`** (Decision 55). Catches both out-of-band drift and a prior non-converged apply.

### 5.7 RCA wiring
Apply-failure and drift both file `source=ci_rca`, `priority=critical` recs via the existing ops portal
transport (Decision 71/72), so they surface in the next `/plan` under "CI RCA Recs (open)" -- the same
treatment `validate.py` failures get today.

### 5.8 Privilege-tiering / bootstrap root
The CI/CD role's *own* IAM (`github_ci_apply`'s policy) and other "manage-the-manager" resources move into a
separate **`terraform/bootstrap/`** root with its own state, applied by the privileged tier (PlatformAdmin, via
the gated path in 5.4) out-of-band. This permanently breaks the self-grant cycle: the pipeline never plans its
own permissions. **Absorbs rec-2079** (consolidate `IAMRoleReconcile` + `IAMPlatformRolesRead`). Baseline is the
post-Phase-2 `github_ci_apply` state now on main (`oidc.tf`).

### 5.9 Guard <-> native-controls reconciliation
With `main-protection` live and Environments added, responsibilities re-divide:
- **GitHub native controls** own *authorization*: required checks (incl. `terraform-converged`), linear history,
  and the Environment reviewer gate.
- **The Decision-77 guard** narrows to *content policy*: classify a plan as auto-applyable (routine) vs
  gated (IAM/trust/destroy), and feed the predicted verdict to the PR (5.1). It remains fail-closed; it stops
  *deciding who may merge*.
This is the Decision-75 frame-challenge made concrete.

## 6. The autonomy boundary (routine vs gated)

| Change class | Path | Who acts | Agent-autonomous? |
|---|---|---|---|
| Data/compute resources, tags, non-IAM config (guard PASS) | speculative plan -> merge -> auto-apply saved plan (async) | agent end-to-end | YES |
| IAM policy / role / trust changes, `delete`/`destroy` (guard FAIL-CLOSED) | speculative plan -> merge -> GitHub Environment approval -> gated CD apply | human approves; CD applies | NO (by design) |
| The CI/CD role's *own* IAM | `terraform/bootstrap/` root, privileged tier, out-of-band | PlatformAdmin | NO (by design) |
| Drift correction | alarm + rec only | human triages via `/plan` | N/A (never auto) |

## 7. Build vs buy

**Build (DIY in GitHub Actions) -- chosen.** The existing guard + LLM-review is already past Atlantis's
feature set, and in-repo workflows preserve agent-legibility (the agent-first repo ethos) over an external
control plane. Alternatives recorded as rejected-for-now: Terraform Cloud free tier (gives speculative plans +
state, but drift detection is paid and it adds an off-repo control plane), Atlantis (PR-comment plan/apply, but
self-hosted server + no native drift), Spacelift/env0 (encode all of this but external SaaS, over-tooled for one
sandbox). Revisit on multi-account (`live_full`).

## 8. Roadmap decomposition (transcribe to ROADMAP-PLATFORM.yaml after the zero-context reviews)

Each item is a **standalone IMPLEMENTATION plan** (Decision 67 STRATEGIC-suspension -- author as one larger
IMPLEMENTATION plan or split into atomic IMPLEMENTATION plans; never STRATEGIC). All are V3 (live
Terraform/IAM/CI). `depends_on` are logical; ids assigned at transcription.

| Wave | Item (logical) | Depends on | Effort | Exit criteria (behavioural) | Instruction files touched |
|---|---|---|---|---|---|
| **1 (first)** | **Convergence substrate**: apply job writes the S3 convergence record (restricted write-IAM); `terraform-converged` PR job reads it; add it to `main-protection` `required_status_checks`; wire apply-failure -> `source=ci_rca` rec | -- (extends live CD.20) | M | Force an apply failure -> next PR's `terraform-converged` check is RED until a successful apply; a `source=ci_rca` rec is filed | `terraform/CLAUDE.md`, AGENTS.md (Safety) |
| **2** | **Speculative plan + apply-saved-plan**: read-only plan role; PR plan job posts redacted diff + predicted guard verdict; persist `plan.bin`; merge applies the saved plan (terraform staleness guard) | Wave 1 | M | A PR shows the plan diff + verdict in a comment; the merge applies the *same* `plan.bin`; a deliberately staled plan fails closed and re-plans | `terraform/CLAUDE.md`, planning skill (Infra assessment) |
| **3** | **Gated CD apply via GitHub Environment**: create the Environment + required reviewer; OIDC-scope the privileged apply role's trust to the environment; route guard-fail-closed plans through it; retire the manual branch-first convention | Wave 1 | L | An IAM/destroy change auto-routes to the Environment, blocks on approval, then applies in CD; the privileged role is NOT assumable off-environment | AGENTS.md (Safety), `docs/contracts/environment-taxonomy.md`, implement skill |
| **4** | **Privilege-tiering / bootstrap root**: `terraform/bootstrap/` root + state for the CI/CD role's own IAM; migrate `github_ci_apply` policy; absorb rec-2079 | Wave 3 | L | A change to `github_ci_apply`'s own policy applies via the bootstrap tier with NO red push run on the main pipeline | `terraform/CLAUDE.md`, `docs/contracts/environment-taxonomy.md` |
| **5** | **Drift detection**: scheduled `plan -detailed-exitcode` (`-lock-timeout`); non-empty -> convergence-red + `source=ci_rca` rec; alarm-only | Wave 1 | S | An out-of-band console change is detected within one cron cycle and filed as a rec; no auto-apply occurs | `terraform/CLAUDE.md` |
| **X (cross-cutting)** | **Convention synchronization + guard narrowing**: consolidate the apply-model convention to `environment-taxonomy.md` as SoT; reconcile the guard to content-policy-only (5.9); land CD.NN as a numbered Decision | Waves 1-4 | S | The 6 instruction surfaces agree and reference one SoT; `prompt_compliance.py` passes; Decision N logged | all 6 (Section 9) |

## 9. Instruction-surface synchronization

The "manual branch-first apply" convention is currently written across **six** surfaces -- itself drift-by-design:
`AGENTS.md` (Safety), `terraform/CLAUDE.md`, `docs/contracts/environment-taxonomy.md`, the **planning** skill,
the **implement** skill, `src/data/handlers/CLAUDE.md`. Wave X **consolidates the canonical statement into
`docs/contracts/environment-taxonomy.md`** (source of truth) and reduces the others to a one-line reference
(agent-first collocation rule). These edits are *named* by the tier_items and executed by the Wave's
IMPLEMENTATION plan -- NOT in this REPORT-ONLY session.

## 10. Decision logging

Add **CD.NN** to the roadmap now (codename, alongside the tier_items). Ratify as a numbered **Decision N** via
the log-decision path when Wave 1 ships (CD.31->Decision 78, CD.33->Decision 81 precedent). A full
`DECISIONS.md` entry now would ratify an unbuilt design. The Decision records the guard<->native-controls
division (5.9), the routine/gated autonomy boundary (Section 6), and the rejected guard-self-grant-exception.

## 11. Risks / known gaps / open questions

- **Convergence-check authority.** The whole anti-masking property rests on the S3 record's write-IAM being
  apply-identity-only. If any other principal can write it, the gate is theatre. (Wave 1 acceptance must prove
  write-restriction.)
- **Speculative-plan exposure.** Even redacted, plans leak resource topology into PR comments; the read-only
  plan role must be genuinely least-privilege. Open: do we plan-comment `terraform/github/**` (which touches
  repo/security config) or restrict speculative comments to `terraform/personal/**`?
- **Required-check bootstrapping.** Adding `terraform-converged` to `main-protection` before the apply job ever
  writes a record would red every PR. Wave 1 must seed an initial green record (or make the check pass on
  "no record yet") to avoid a deadlock.
- **Gated-apply throughput.** Every IAM/destroy change now blocks on a human approval click. Acceptable, but it
  caps the agent's autonomous infra velocity at exactly the fail-closed set -- monitor that the set stays
  narrow.
- **Bootstrap-root chicken-and-egg.** The `terraform/bootstrap/` root needs its own state bucket/lock and an
  apply identity that is itself not managed by the pipeline -- bootstrap it manually once (a documented,
  one-time admin action), then never again.
- **Lock contention.** Drift cron + auto-apply + gated apply share one S3 lockfile; `-lock-timeout` + skip-on-held
  must be specified or a stuck apply cascades.

## 12. Scoping guards (decision-alignment, from the decision-scout gate)

- **Decision 67 (STRATEGIC suspended):** every Section-8 wave is a standalone IMPLEMENTATION plan; no STRATEGIC
  plan is authored downstream.
- **Decision 24 (multi-account superseded):** the Section-5.4 Environment is a single-account approval gate
  (Decision 77 clause 5), not a multi-account promotion pipeline.
- **Decision 44 / 79 (executor boundary):** CI/CD pipeline files are build-tooling, not executor machinery;
  this design touches none of Decision 44's boundary table.
- **Decision 55:** drift + apply failures alarm and file recs; nothing auto-remediates.
