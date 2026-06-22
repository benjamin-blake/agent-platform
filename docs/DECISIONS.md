# Open Decisions

This document tracks key architectural and operational decisions that need to be made as the system evolves.

## Decision 94: Correct Decision 92 point 3 -- github_ci_apply OIDC trust must also trust the environment sub (Decided)

**Status:** Decided
**Date:** 2026-06-22
**Warehouse ID:** dec-094 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Decision 92 point 3 ratified the CD.35 Wave 3 / T2.22 security model with the clause "The privileged
role OIDC trust stays pinned to refs/heads/main," on the stated premise that a GitHub Environment's
required-reviewer gate does NOT change the OIDC token's sub claim. The live VP7-VP11 end-to-end test
(2026-06-22) disproved that premise. When a job declares `environment: tf-gated-apply`, GitHub
OVERRIDES the OIDC sub to `repo:OWNER/REPO:environment:tf-gated-apply` (the environment claim REPLACES
the ref claim). With trust pinned to `refs/heads/main` only, the `gated-apply` job could never assume
`github_ci_apply` -- it failed `sts:AssumeRoleWithWebIdentity` (AccessDenied) on every run. The
T2.22 gated-apply path was non-functional as merged; all static gates (validate, terraform-validate,
unit tests, code review) passed and only live verification caught it.

**Decision:**
Correct Decision 92 point 3. `github_ci_apply`'s OIDC trust `sub` condition is a two-value
exact-match list, trusting BOTH:
- `repo:OWNER/REPO:ref:refs/heads/main` -- the routine auto-apply path (apply-sandbox job, no
  job-level environment), and
- `repo:OWNER/REPO:environment:tf-gated-apply` -- the gated-apply job (whose declared environment
  overrides the sub).

This is SAFE and does not weaken the security model: a token bearing
`sub=...:environment:tf-gated-apply` can ONLY be minted by a job that declares that environment, and
such a job cannot begin until the Environment's required reviewer approves. The environment sub is
therefore itself approval-gated -- belt-and-braces with the guard's fail-closed routing. The
Environment-gates-EXECUTION model of Decision 92 is unchanged; what is corrected is the false claim
that the sub stays `refs/heads/main`. `agent/*` and `pull/*` remain unable to assume the role.

The trust change is an IAM/trust change and was admin-applied locally (the gated CD path it fixes
could not apply it), then confirmed by a no-op merge (PR #222). Re-running VP7-VP11 with a throwaway
IAM tag then proved the gated path applies end-to-end: routed green -> reviewer approval -> assume-role
success -> saved plan.bin applied verbatim (no re-plan) -> convergence record green with plan_sha.

Secondary correction (VP10): the gated-apply always-run red-on-failure convergence write depends on
the same OIDC apply-role creds; a failure AT OR BEFORE the credentials step cannot write the red
record. The backstop is ci-rca, which triggers on the terraform-apply-sandbox workflow_run failure
conclusion independent of the record -- so a creds-stage failure still files a source=ci_rca rec and
is not silently masked. Documented at the record_write step; no code change required.

## Decision 93: Platform-MVP boundary + deferred_post_mvp lifecycle status (Decided)

**Status:** Decided
**Date:** 2026-06-20
**Warehouse ID:** dec-093 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The platform's telos is removing the human from the autonomous loop, which qualifies almost everything as "MVP-critical" -- there is no natural MVP boundary under that framing. Post-MVP hardening work (secrets rotation, backup/DR posture, devcontainer substrate, portal artefacts) competes on the same eligibility surface as critical-path items, making next-eligible noisy and sequencing ambiguous.

**Decision:**
Platform-MVP boundary defined as: "the autonomous loop closes end-to-end with no human in the critical path of one iteration (rec -> implement -> validate -> merge -> deploy -> observe -> next rec)." Introduces a `deferred_post_mvp` lifecycle status and the defer-by-exception rule to resolve the boundary without enumerating the MVP set upfront (which would trip the frame-lock anti-pattern, Decision 75).

**Boundary definition:**
An autonomous loop iteration is: a recommendation is filed, implemented by the agent, validated, merged, deployed, and produces the next observable state -- with no human in the critical path. When this closes end-to-end, the platform is at MVP. Everything after that is hardening / polish.

**Defer-by-exception rule:**
New platform work is MVP-critical by default; items leave MVP scope only by conscious deferral. The MVP set is never enumerated -- only the deferred set is. This avoids the frame-lock anti-pattern of committing to a fixed MVP surface before the autonomous loop is proven closed.

**deferred_post_mvp status semantics:**
- Living cousin of `reserved` (which marks tombstones/superseded items). Unlike `reserved`, a deferred item is REACTIVATABLE per-item by restoring status -> not_started.
- Excluded from next_eligible and tier-completion math (alongside `reserved`); a tier of [complete, deferred_post_mvp] is treated as complete and does not wedge active_tier().
- Absent from the lean preflight/orient digest, so parked items are excluded from the eligibility surface rather than displayed there. Recorded in a separate `deferred_post_mvp` bucket in the FULL compute_state (queryable on demand).
- No live platform item (status == not_started or in_progress) may depend_on a deferred_post_mvp item. The platform_roadmap.py model_validator enforces this at load time (fail loud at validation, never silently strand a dependent).

**PLATFORM-INTERNAL scoping:**
The no-live-dep restriction is enforced by platform_roadmap.py model_validator ONLY -- not added to product_roadmap.py. Cross-roadmap edges from ROADMAP-PRODUCT.yaml to deferred platform items (e.g. E.env.3 -> PLATFORM:T2.9) are permitted and remain dormant until product work begins, per the platform-first directive. These edges are revisited when the product roadmap is activated.

**Items parked (deferred_post_mvp) at Decision 93 ratification:**
- T2.8 (backup/DR posture for the personal account): clean leaf; hardening, not on the autonomous-loop critical path.
- T2.9 (secrets rotation policy + automation): hardening; platform edge T2.14 corrected (see below); product edge E.env.3 left dormant per platform-first directive.
- T2.11a (Codespaces devcontainer substrate): public-surface polish; not in the autonomous-loop critical path.
- T2.11b (public-portal artefacts): co-parked with T2.11a (depends_on T2.11a; same public-surface-polish category; downstream T2.12/T2.13 already complete so nothing live is stranded).

**T5.2 exclusion rationale:**
T5.2 (teardown) was considered but excluded: it is a near-due cost-saver (grace elapses ~2026-06-28), user_action_required, and currently eligible. Parking it would hide a billing-stopper from the eligibility surface.

**T2.14 depends_on edge correction:**
T2.14 (broker credential routing) declared depends_on: [T2.1, T2.9]. The T2.9 edge was incorrect: T2.14 provisions its own Secrets Manager surface and does not require rotation automation as a prerequisite. Edge re-pointed to depends_on: [T2.1]. Required for the no-live-dep invariant to pass with T2.9 parked.

**Related:** Decision 73 (sandbox-only / forward-fix posture -- the boundary is consistent with it, not a re-derivation), Decision 75 (frame-lock anti-pattern; defer-by-exception avoids it), Decision 80 (validate.py single source of truth; the invariant lives in platform_roadmap.py model_validator, picked up by validate_platform_roadmap via load()), Decision 86 (no new prose-architecture doc; boundary semantics live in Decision 93 + ROADMAP-PLATFORM.yaml agent_instructions only), Decision 90 (four-tier workflow; parked items are excluded from the next_eligible eligibility surface, not surfaced in an orient bucket).

---

## Decision 92: Ratify CD.35 -- agent-native Terraform CI/CD (Wave 1 shipped) (Decided)

**Status:** Decided
**Date:** 2026-06-19
**Warehouse ID:** dec-092 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
CD.35 (Agent-native Terraform CI/CD) specified a five-wave architecture ratified via the log-decision
path once Wave 1 / T2.20 shipped. Wave 1 is now SHIPPED AND PRODUCTION-PROVEN: the convergence
substrate landed in PRs #142 (#179 hardening, #185 SSM closure), real CONVERGENCE_RED latches fired
(rec-2236 @7678d3e, rec-2238 @bfa5229f), were refused server-side, filed as source=ci_rca recs, and
cleared via the dispatch-ack path -- behavioural proof of T2.20 exit criteria 1/2/4. The roadmap
still showed T2.20 not_started and CD.35 state:pending with a pending_log_decision_lambda clause.

**Decision:**
Wave 1 (T2.20) is SHIPPED. The following Wave-1-established architecture is ratified:

1. **Authorization division (INTENT 5.9):** native controls own AUTHORIZATION (required checks,
   linear history, GitHub Environment reviewer gate); the deterministic guard narrows to plan-CONTENT
   policy. The guard fails closed on IAM/trust/destroy changes and is never the authorization lock.

2. **Server-side convergence anchor -- sole hard block (INTENT 5.5):** the apply job writes a durable
   S3 convergence record (pipeline-writer-identity-only write-IAM; always-run, red-on-failure) and
   reads it as a precondition that refuses to apply against a red record. An absent record = first-apply-
   allowed (pass-on-absent). The record lives in its own S3 prefix outside tfstate/ so the PR role reads
   it without seeing tfstate. A red record clears ONLY via the workflow_dispatch acknowledge-and-retry
   path; a plain push never clears red (auto-allow-descendants rejected on linear-history main).
   terraform-converged is an ADVISORY PR status ONLY (not a required check -- required would wedge the
   autonomous fix-merge or be admin-bypassed; main-protection strict=false + bypass_mode=always, Decision 83).

3. **Routine-vs-gated autonomy boundary and Environment-gates-execution security model (ratified
   DIRECTION for Waves 2-5, INTENT 5.4 + 5.6):** routine (guard-PASS, non-IAM) changes ride the
   record-backed pipeline; high-blast changes (IAM/trust/destroy) route to a GitHub Environment whose
   required reviewer gates JOB EXECUTION. The privileged role OIDC trust stays pinned to refs/heads/main.
   [CORRECTED by Decision 94 (2026-06-22): the trust clause here is wrong. A job declaring
   environment: tf-gated-apply gets sub=repo:OWNER/REPO:environment:tf-gated-apply, so github_ci_apply
   must ALSO trust the environment sub (proven by VP9). The Environment-gates-EXECUTION model is
   unchanged; the environment sub is approval-gated and safe. See Decision 94.]

4. **Rejected guard-self-grant exception + privilege-tiering (INTENT 5.8, Wave 4):** the CI/CD role's
   own IAM moves to a separate terraform/bootstrap/ root applied out-of-band, breaking the self-grant
   cycle. Without that separation any automated handling of the fail-closed set is self-approval.

5. **Authority-budget + ratchet model (CD.35 points 6-9, ratified DIRECTION; concrete classification
   deferred to T2.23/T2.25):** an explicit permissions boundary on github_ci_apply plus boundary-
   propagation condition keys and deterministic in-budget/out-of-budget diff classification; auto-passes
   in-budget IAM changes, routes out-of-budget/trust/destroy to the Environment gate. Autonomy is earned
   and revocable PER CHANGE-CLASS: the budget widens on measured track record and narrows on incident
   (budget amendments via the bootstrap tier only; subagent review advises, never locks).

6. **Apply failures wire into ci-rca (Decision 72/55):** apply failures file source=ci_rca recs;
   drift detection (scheduled plan, alarm-only) files via the ops portal. Nothing auto-remediates.

Waves 2-5 and Wave X are RATIFIED DIRECTION -- architecture decided, implementation pending their
respective tier items (T2.21/T2.22/T2.23/T2.24/T2.25).

**Supersession of CD.35's pending_log_decision_lambda clause:**
CD.35's discipline_points contained a "does NOT edit DECISIONS.md while pending; ratified via the
log-decision path" clause and field filed_via: pending_log_decision_lambda. This Decision 92 DELIBERATELY
supersedes that clause -- the DECISIONS.md-edit + `ops_data_portal --backfill-decisions-md` ETL is the
sanctioned ratification path per Decision 84 (canonical source + ETL) and the Decision 90/91 precedents
(both ratified via the same path on 2026-06-18/19). The pending_log_decision_lambda mechanism is
superseded as of this Decision; CD.35 is now filed_via: ops_decisions:dec-092.

**Rationale:**
Mirrors CD.31->Decision 78 and CD.33->Decision 81: architecture ratified once the implementation
is production-proven. The DECISIONS.md-edit path (per Decision 84 + Decision 90/91 precedents) is
cleaner than the log-decision path, which required a separate Lambda invocation -- Decision 84 retired
the Lambda path for ops_decisions (DuckLake writer now owns it) and Decision 84 I-2 established backfill
ETL from DECISIONS.md as the rebuild path. Ratifying CD.35 here confirms that the DECISIONS.md-edit
+ backfill ETL is the canonical ratification path for all future candidate decisions.

**Related:** CD.35 (ratified here; filed_via: ops_decisions:dec-092), T2.20 (Wave 1 shipped),
T2.21-T2.25 (direction ratified; implementation pending), Decision 77 (guard fail-closed; narrowing is
T2.25/Wave X), Decision 83 (main-protection non-wedging; advisory-not-required advisory status),
Decision 84 (DECISIONS.md canonical source + ETL), Decision 90/91 (edit-and-backfill precedents),
Decision 55 (alarm + file recs; nothing auto-remediates), Decision 72 (RCA-as-plan-source).

---

## Decision 91: Ratify OQ.15 option (a) -- agent verb surface extends ducklake_writer/reader; T0.6 closed via supersession; CD.10 six-Lambda enumeration superseded (Decided)

**Status:** Decided
**Date:** 2026-06-18
**Warehouse ID:** dec-091 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
OQ.15 (opened 2026-06-09, audit F-008) asked whether the agent-facing verb surface should (a) extend
the ducklake_writer/ducklake_reader verb sets directly, or (b) use thin verb Lambdas fronting them.
The question was left open pending T0.6 plan time, but T0.6's original Terraform skeleton was never
built in the personal account -- instead the ducklake_writer/reader closed boundary shipped (T2.17/T2.19)
and T2.28 landed the NAMED_READS registry, realizing the functional scope of T0.6 via a different
mechanism. Six src/lambdas/<verb>/ stub mocks (log_rec, log_decision, query, update_rec, list_tools,
maintenance) and their work-root Terraform (lambda_tooling_platform.tf, lambda_tooling_outputs.tf,
never applied per CD.21) accumulated as dead artefacts. CD.10's six-Lambda enumeration remained
state:pending while the shipped architecture made it illustrative in practice (Decision 81 cl.2).
The roadmap carried stale files_in_scope / exit_criteria pointing at deleted stubs in six tier items
(T0.7a/b/c, T1.1/T1.2/T1.3) and stale query/ path comments in T2.5 and T2.7.

**Decision:**
1. Ratify OQ.15 option (a): the agent-facing verbs extend the ducklake_writer/ducklake_reader verb
   sets directly. This ratifies the shipped architecture per Decision 81 cl.2 (extensible verb surface,
   NOT a fresh design pick) and Decision 84 I-3 (named-verb closed boundary). The shipped routing is:
   scripts/ops_data_portal.py routes file_rec->write_ops/file_ops, update_rec->update_ops, and
   file_decision->write_ops on ducklake_writer; reads use the NAMED_READS registry
   (src/common/ducklake_scd2_schema.py) via ducklake_reader.named_read. Function-URL+AWS_IAM is
   live in terraform/personal/ducklake_lambdas.tf; PlatformDev/PlatformAdmin invoke via
   DuckLakeInvokeRuntime (platform_roles.tf:142-152 + AdminOps).
2. Close T0.6 (Lambda-tooling-platform Terraform skeleton) as realized-via-supersession. The verb
   surface T0.6 planned to provision is already live as the ducklake_writer + ducklake_reader closed
   boundary. T0.6's bootstrap_completion_exempt: true permits completion with CD.10 still state:pending.
3. Supersede CD.10's six-Lambda enumeration (log-rec, log-decision, query, update-rec, list-tools,
   maintenance as separate Lambdas). The enumeration was illustrative per Decision 81 cl.2; this
   decision records its supersession. CD.10's PlatformDev/PlatformAdmin two-principal allow-list is
   RETAINED -- realized in DuckLakeInvokeRuntime. CD.10 itself remains state:pending; only the
   six-Lambda enumeration clause is superseded.
4. Re-ground tier items T0.7a, T0.7b, T0.7c, T1.1, T1.2, T1.3 files_in_scope and exit_criteria to
   the named-verb writer/reader surface. Status remains not_started; likely silent-completion of each
   item is flagged in their notes for dedicated per-item closeout plans.
5. Delete the six src/lambdas/<verb>/ stub directories, tests/test_lambda_stubs.py,
   terraform/lambda_tooling_platform.tf, and terraform/lambda_tooling_outputs.tf. Retain
   terraform/lambda_tooling_iam.tf (agent_auth.tf circular reference + T1.15 ownership).

**Rationale:**
The Decision 81 cl.2 extensible-verb-surface and Decision 84 I-3 named-verb boundary together made option
(a) the natural landing point: fewer Lambdas, verb logic co-located with the schema gate, and the NAMED_READS
registry already provides the query-surface discovery needed for T0.7c/T1.2/T1.3. Option (b)'s per-verb SLO
benefit (T1.9) does not outweigh the added hop and the deployment blast radius of six separate Lambdas.
Recording the resolution now cleans the roadmap of stale artefacts and stops agents from planning against
deleted stub paths, while the conservative not_started status for T0.7x/T1.x preserves the formal closeout
gate for each item's unit-test coverage and import_mode edge cases.

**Related:** Decision 81 cl.2 (extensible verb surface superseding CD.10 six-Lambda enumeration),
Decision 84 I-3 (named-verb read boundary + I-2 writer-owned keyspace), Decision 79 (per-Lambda deploy
gating -- stubs are status:stub, no deploy step required), CD.10 (six-Lambda enumeration superseded here;
two-principal allow-list retained; state:pending unchanged), CD.33 (closed read/write boundary ratified),
OQ.15 (resolved to option (a) here), T0.6 (closed via supersession), T0.7a/b/c/T1.1/T1.2/T1.3
(re-grounded; still not_started), ROADMAP-PLATFORM.yaml.

---

## Decision 90: Four-Tier Workflow Architecture (Decided)

**Status:** Decided
**Date:** 2026-06-19
**Warehouse ID:** dec-090 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
Decision 42 established the Three-Tier Workflow Architecture: `/plan` -> `/implement` -> `/develop-executor`. Since then, a read-only orientation step `/orient` was added as the entry point to the pipeline (PR #183, 2026-06-18). Multiple instruction surfaces (AGENTS.md, `.claude/skills/orient/SKILL.md`) continue to cite Decision 42 as a "three-tier" architecture, misframing the pipeline for planning agents that now enter via `/orient`.

**Decision:**
The canonical end-goal workflow architecture is four tiers:

```
/orient -> /plan -> /implement -> /develop-executor
```

Tier responsibilities:
- `/orient` -- read-only orientation: surfaces eligible work, CI-RCA triage, ranked what-to-work-on, and up to N disjoint `/plan` prompts with an overlap matrix and keystone-first sequencing. Produces a chat reply only; writes nothing.
- `/plan` -- clarifies intent, runs preflight, produces `docs/plans/PLAN-{slug}.yaml`. Scopes work; does not execute code changes directly.
- `/implement` -- executes IMPLEMENTATION plans directly; scopes STRATEGIC plans into atomic recommendations the executor consumes.
- `/develop-executor` -- autonomous executor: consumes atomic recommendations from the priority queue.

**Current operational state (2026-06-19):** `/orient` -> `/plan` -> `/implement` only. Executor and STRATEGIC plans are frozen per Decision 67 / CD.17; `/implement` makes code changes directly during the freeze.

**Supersedes:** Decision 42 (Three-Tier Workflow Architecture). Supersedes Decision 42's framing; Decision 42's body is preserved intact with its status annotated "Superseded by Decision 90".

**Related:** Decision 42 (superseded here), Decision 67 (executor + STRATEGIC freeze; the current operational constraint), Decision 76 (.claude/ as the canonical interactive layer).

---

## Decision 88: Neon catalog egress is a first-class budget -- four standing access-pattern invariants + a measurement obligation; amends CD.34's "negligible add-on" (Decided)

**Status:** Decided
**Date:** 2026-06-16
**Warehouse ID:** dec-088 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
On 2026-06-15 the DuckLake-on-Neon catalog breached Neon's free-tier 5 GB/month egress cap and forced a paid-plan upgrade. CU-hours stayed well under quota -- the low-compute / high-egress signature of bulk metadata transfer, not computation. The catalog holds only METADATA (row data is S3 Parquet; inlining is disabled), so the egress was self-inflicted access-pattern amplification, code-verified to four sources: (D1) a daily full-catalog pg_dump DR job; (D2) a fresh cold DuckLake ATTACH on every reader/writer invocation with no warm reuse, amplified by DuckDB's postgres scanner sequential-COPY of `ducklake_file_column_stats` per query (ducklake #859); (D3) production catalog metadata never snapshot-expired, so D1/D2 grow unbounded; (D4) a preflight reader fan-out of ~9-10 calls per session plus a full-table resync after every portal write. Nothing treated catalog egress as a budgeted resource, and nothing measured it -- the breach was the first signal.

**Decision:**
1. Catalog egress is a FIRST-CLASS cost budget for the platform, ranked beside compute and storage. It protects the near-zero-cost operating posture (Decision 84 / Decision 81) and is governed by four standing access-pattern invariants that any code touching the catalog MUST uphold:
   (i) Reuse warm catalog connections across sequential invocations -- never a cold ATTACH per request where a container can hold one. A dead session (Neon scale-to-zero) is the one expected reopen condition (Decision 55: any other error still raises).
   (ii) Never re-query data already in the local read-cache. Preflight and other read paths serve from the rows the single warm-up sync already pulled; a genuinely-needed warehouse read uses a registered named verb (Decision 84 I-3), never an ad-hoc re-fetch of data in hand.
   (iii) Keep the catalog compacted: non-destructive merge runs on ALL live ops_* tables on a cadence sized to write rate (the smaller the `ducklake_file_column_stats` footprint, the smaller every read's per-query egress). Destructive expiry/cleanup/orphan deletion stays behind a proven restore drill (see clause 4).
   (iv) Size the DR dump cadence to the durability tier and the MEASURED egress, not to a habit. A daily full dump is not free when egress is metered.
2. Measurement obligation: catalog metadata size and Neon egress-by-source must be instrumentable on demand, so this budget is enforceable rather than aspirational. The `catalog_stats` maintenance action (read-only; reads the catalog's own Postgres metadata via psycopg2 -- no ATTACH, no data_path) is the supported measurement path (the DR bucket and direct CloudWatch reads are IAM-blocked from the dev role by design). It reports total catalog-metadata bytes (exact), the `ducklake_file_column_stats` row estimate (the #859 driver), and a per-ops_*-table breakdown. The dump size and implied monthly-egress numbers are folded into the Warehouse measurement record once the post-deploy `catalog_stats` invocation runs against the live catalog (the mechanism lands with this Decision; the figures are a post-deploy measurement step, not a planning-time guess).
3. CD.34 amendment: CD.34 called the daily pg_dump-to-S3 DR "a negligible add-on". That holds for STORAGE (a versioned, lifecycle-expired bucket) but is FALSE for EGRESS -- a daily full-catalog dump is a session-independent metered-egress line. The DR cadence is lowered daily -> weekly (cron(0 3 ? * SUN *)); paid-tier Neon's 7-day PITR provides finer-grained recovery BETWEEN weekly full dumps, preserving the durability floor while cutting the pg_dump egress line ~7x. The co-required freshness-alarm lookback widens from >25h to ~8 days (evaluation_periods/datapoints_to_alarm 25 -> 192) so a weekly dump never leaves the alarm in perpetual ALARM.
4. D3b deferral (destructive GC on ops_*) is OUT OF SCOPE and gated. Only non-destructive merge runs on production ops_*; expanding destructive expire_snapshots / cleanup_old_files / delete_orphaned_files to ops_* is gated by the rec-2113 pg_restore restore drill (T2.26 owns its retirement). GC_TABLE_SCOPE stays smoke-only until that gate clears -- compaction without a proven restore is not licensed to delete production catalog state (Decision 55).

**Rationale:**
The free-tier breach proved the cap is real and the access pattern, not the workload, drove it. Encoding catalog egress as a named budget with standing invariants prevents the class of mistake recurring: each invariant maps to a verified driver (i->D2, ii->D4, iii->D3, iv->D1), so a future change that reintroduces a cold-ATTACH-per-request or a read-cache re-fetch is checkable against a ratified rule rather than rediscovered via the next bill. The measurement obligation makes the budget enforceable -- a budget you cannot read is a wish. The work is shaped as one IMPLEMENTATION effort (Decision 67 / CD.17 STRATEGIC freeze). Form follows Decision 86: the durable rationale lives here, field/measurement semantics ride the maintenance action + ops.yaml, and no new standing prose-architecture doc is created (intent-doc-freeze compliant). Citation correction (2026-06-09 audit F-033): Decision 82 governs the DIRECT-vs-pooled endpoint basis and the EC8 churn-gate N=8->4 frame -- NOT the cold-resume warm-up; the preflight warm-up attribution to Decision 82 was a mis-citation and is corrected to this Decision's invariant (i).

**Related:** Decision 84 (DuckLake sole ops backend; named-verb closed boundary I-3; no write buffering I-4 -- the cache refresh is downstream of the synchronous writer commit, never a write source), Decision 81 (maintenance cadence design, clause 6 -- merge/GC primitives this tunes), Decision 82 (DIRECT-vs-pooled endpoint + EC8 churn-gate frame; the cold-resume warm-up is NOT Decision 82, audit F-033), Decision 55 (loud failure -- the warm-connection reopen handles ONE expected condition; GC stays gated), Decision 86 (deliverable routing; intent-doc-freeze), CD.34 (amended here: "negligible add-on" is storage-true / egress-false), rec-2113 (DR restore-drill HARD GATE that unlatches D3b), rec-2096 (cold+warm connect-latency measurement, closed by this work), rec-2244 (ducklake_reader 502 -- the downstream symptom relieved by removing this egress pressure; closes on operational confirmation, not this merge), rec-2087 (Neon egress IP-allow-list -- a separate access-control concern, left open), T2.18 / T2.19 / T2.26 (`docs/ROADMAP-PLATFORM.yaml`).

---

## Decision 87: Plans, plan-critiques, and plan-revisions as first-class warehouse entities; authority-flip deferred to the autonomous producer (T4.x) (Decided)

**Status:** Decided
**Date:** 2026-06-14
**Warehouse ID:** dec-087 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
`/plan` produces git-tracked `PLAN-{slug}.yaml` artefacts (Decision 85, `PlanDocument` schema_version 1) reviewed via PR (Decision 76 cl.3). This is correct for the interactive era but does not support the autonomous plan -> critique -> revision loop that T4.x requires: plans are not queryable, plan<->rec linkage is not first-class, critique verdicts are ephemeral subagent output, and revision directives have no machine-actionable home. We record the destination (plans as warehouse entities) and, separately, the deliberate decision NOT to build it now -- so neither is re-litigated.

**Decision:**
1. Plans, plan-critiques, and plan-revisions WILL become first-class warehouse entities. Destination state: warehouse-authoritative, on the DuckLake-on-Neon SCD2 substrate (Decision 84).
2. The authority-flip from git to warehouse is TIMED to the existence of the autonomous plan producer (`plan_agent`, a T4.x capability gated behind the CD.17 executor freeze) -- NOT now. For the interactive era, git/PR remains the authoritative approval surface, because `PLAN-{slug}.yaml` artefacts are human-authored, low-frequency, and diff-reviewed -- every property that favours git as source-of-truth. Warehouse-authoritative is the right model only once a machine produces plans at frequency.
3. Until the flip, `ops_plans` is a downstream read-projection of the git-authoritative `PLAN-{slug}.yaml`, populated by git->warehouse ETL. This is the legitimate write path under the Decision 84 warehouse-SoT invariant -- the same sanctioned "ETL from a non-warehouse source of truth" pattern as `DECISIONS.md -> ops_decisions`, not a read-cache-as-write-source violation. The warehouse-SoT invariant remains absolute for operational records (recs, decisions, queue); plans are scoped as projection-until-T4.x.
4. Lifecycle splits across three surfaces, by purpose:
   - `ops_plans` (SCD2) -- the plan document + status gate: `pending -> approved | rejected | needs-revision` (lifecycle-state closure per Decision 70).
   - `ops_plan_revisions` -- machine-actionable revision directives (the imperative: "change X -> Y"), authored by the critique agent for planning-agent consumption. A revision-request is to a plan what a rec is to the repo; the two may converge in shape later but are not unified now.
   - telemetry -- the critique's full deliberation/rationale (observability), for optimization and debugging. The imperative lives in `ops_plan_revisions`; the deliberation lives in telemetry; they are not duplicated.
5. RBAC is enforced at the verb layer, extending the Decision 84 closed writer boundary (I-2 writer-owned keyspace, I-3 named verbs) and the Decision 81 cl.2 extensible verb surface: planning agents get an `insert_plan` verb that hardcodes `status=pending` and cannot mutate status; critique agents get `set_plan_status` + `insert_revision` and cannot author plan bodies. All plan writes transit `ops_data_portal` (Single-Portal Invariant, Decisions 69/78); ids are writer-allocated atomically, never client-side.
6. Plans and recs remain distinct grains: a rec is WHAT work should be done; a plan is HOW to implement it. Planning and implementation stay sequentially coupled (the executor's runtime `ExecutionPlan` stays in-process; only its persisted document would ever join `ops_plans`). Decoupling -- where plans are written faster than implemented and can go stale against an evolving repo -- is gated on a plan-staleness story (base-commit pinning + divergence detection + re-validate-before-implement) that does not yet exist. Frame-lock-aware deferral per Decision 75.

**Rationale:**
No downstream warehouse consumer of plans exists today, and the ones that would (autonomous `plan_agent`, plan-revision loop) are far off behind CD.17/T4.2. Flipping authority now would route the interactive loop through warehouse round-trips it does not need, for no consumer -- building ahead of need. Recording the destination + timing now captures the design while it is fresh and prevents both re-litigation ("should plans be warehouse entities?") and premature build. Form follows Decision 86: rationale here, field/schema semantics to `docs/contracts/*` (the `ops_plans`/`ops_plan_revisions` schema + verb-RBAC contract, when built), forward build intent to T4.x tier_items (T4.5-T4.7). No standing prose-architecture doc is created (intent-doc-freeze compliant).

**Forward note:** At the T4.x authority-flip, Decision 85's git-authoritative clause for plans (and the plan-scoping of the Decision 84 invariant in cl.3 above) is superseded by warehouse-authoritative; until then both stand. Build work, when it lands, decomposes into atomic IMPLEMENTATION-type plans -- no STRATEGIC plan is authored under the CD.17 freeze (Decision 67 STRATEGIC clause).

**Related:** Decision 84 (DuckLake sole ops backend; writer-owned keyspace; named-verb boundary -- substrate + write-path precedent), Decision 85 (`PLAN-{slug}.yaml` / `PlanDocument` -- the entity promoted), Decision 76 cl.3 (web PR/merge -- preserved interactive approval surface), Decision 81 cl.2 (extensible verb surface), Decision 86 (forward-routing form; intent-doc-freeze), Decisions 69/78 (Single-Portal Invariant), Decision 70 (lifecycle-state closure), Decision 75 (frame-lock-aware deferral), Decision 57 (autonomous-improvement control plane -- the loop this extends), CD.17/T4.2 (executor-freeze gate), T4.5-T4.7 tier_items (forward build), `docs/ROADMAP-PLATFORM.yaml`.

---

## Decision 86: INTENT prose docs retired -- architectural intent routes to roadmap tier_items, Decisions, or contracts; supersedes CD.14 (Decided)

**Status:** Decided
**Date:** 2026-06-12
**Warehouse ID:** dec-086 (keyed on the decision number; synced to ops_decisions via `ops_data_portal --backfill-decisions-md` post-merge, per Decision 84)

**Problem:**
The 18 `docs/INTENT-*.md` documents (~10.5k lines of prose) were authored to persist the owner's architectural vision across agent sessions. Two failure modes emerged: (1) **deliverables get lost** inside long narrative docs -- an agent must read the whole document to find what is actually actionable; and (2) the docs **drift** from live roadmap/decision state (e.g. CD.14 enumerated 10 docs to handle when 18 now exist; `ops-decisions-graduation` is half-superseded by Decision 84; several docs describe the pre-CD.27/28 executor substrate that no longer exists). Prose is a human-facing surface in an agent-first repo (NS.4, CD.13); the roadmap's YAML dependency edges now serve the cross-session-persistence role the INTENT docs were created for, readable without parsing narrative.

The pending CD.14 chose to *demote* INTENT docs to "non-authoritative detail-companions" -- keeping the prose, stamping a footer, roadmap-wins-on-divergence. That preserves the drift surface (a second place agents must sync) rather than eliminating it.

**Decision:**
1. **CD.14 is SUPERSEDED.** Its demote-and-keep-prose model is replaced by extract-and-retire. The candidate decision is marked `state: superseded` (by this Decision) in `docs/ROADMAP-PLATFORM.yaml`, and tier_item `T5.5` is repointed from "demote + footer" to "extract content into tier_items/Decisions/contracts, then delete" -- mechanised by `docs/intent-migration/MANIFEST.yaml`. (This Decision is a *ratified* numbered entry under the DECISIONS.md numbering authority; ratifying it is the act that supersedes the *pending* CD.14 -- the roadmap-YAML edit lands in the Wave 0 follow-on.)
2. **Forward routing rule (the "stop the bleeding" clause).** No new *standing prose-architecture / deliberation documents* anywhere under `docs/` -- the rule forbids the BEHAVIOUR, not merely the `docs/INTENT-*.md` filename glob (a doc renamed `docs/design-foo.md` or `docs/INTENTS/foo.md` is the same anti-pattern). Architectural content routes to its canonical machine-parseable home by type:
   - **Forward-looking deliverables / sequencing** -> `docs/ROADMAP-PLATFORM.yaml` (or `ROADMAP-PRODUCT.yaml`) tier_items, with `depends_on` edges.
   - **Rationale / choices / trade-offs** -> `docs/DECISIONS.md` (numbered) or `candidate_decisions[]` (pre-ratification).
   - **Field/contract semantics** -> `docs/contracts/*.yaml`.
   - **Already-ratified content** (a feasibility verdict or arc that graduated to a Decision) -> a pointer to that Decision; preserve any still-live trigger/watch-signal as a tier_item before removing the prose (the manifest's `delete_pointer` disposition).
   - **Unbuilt exploratory direction** still referenced by a governing CD -> keep as a contract or a CD-gated future tier_item, not a standing prose doc (the manifest's `defer_or_contract` disposition).
   - Deliberation that genuinely needs a working document uses a REPORT-ONLY plan deliverable scoped to a single decision, not a standing INTENT doc.
3. **The existing 18 are grandfathered** and retired wave-by-wave per `docs/intent-migration/MANIFEST.yaml` (Waves 1-5), each with its own per-doc drift reconciliation. A `scripts/validate.py` guard (added in Wave 0) rejects new standing prose-architecture docs while allowing the grandfather set. The allowed set is DERIVED from the manifest -- a doc is permitted iff it has a `documents[]` entry with `disposition_state != done` -- so it shrinks automatically as each wave deletes a doc and flips its entry to `done`, with no hand-maintained list. Deleting a grandfathered doc requires the inbound-reference sweep (manifest findings X1/X2/X6/X7) to pass first.
4. **Enforcement is wired in Wave 0** (`PLAN-intent-migration-wave0-enforcement`): `.claude/commands/plan.md`, `.claude/skills/planning/SKILL.md` (Documentation Artefact Design), and `AGENTS.md` (Agent-First Repository) gain the routing rule; the roadmap bookkeeping (CD.14 supersession + T5.5 repoint) and the validate guard land there.

**Fast-track rationale:** This governance change is ratified directly (not filed as a pending CD that waits on the log-decision Lambda) because it is a *documentation-governance* rule with no infrastructure dependency, it is needed *now* to stop the corpus growing during the multi-wave extraction it authorises, and it only tightens an already-ratified direction (CD.13 markdown-with-prose retirement; NS.4 agent-first). The migration work it scopes is large (Wave 0 + ~5 extraction waves); each wave is an IMPLEMENTATION plan per the Decision 67 / CD.17 STRATEGIC-plan freeze.

**Related:** CD.14 (superseded here), CD.13 (agent-first exemplar -- this enacts its prose-retirement thesis), NS.4 (the repo is for agents), Decision 67 / CD.17 (STRATEGIC freeze -- all migration waves are IMPLEMENTATION type), Decision 85 / Decision 76 (PLAN-*.yaml planning artefacts), Decision 84 (DuckLake / ops_decisions backfill path; ducklake-consolidation INTENT graduates to it), Decision 80 (bazel-feasibility graduation target), Decision 57 (amends the "INTENT authoritative for domain" grants as docs retire), Decision 75 (frame-lock pointers preserved on delete), CD.32 (multi-product-platform exploratory record). Mechanised by `docs/intent-migration/MANIFEST.yaml`.

---

## Decision 85: Ratify CD.22 -- PLAN-*.yaml planning artefacts with PlanDocument schema; amends Decision 76 clause 3 (Decided)

**Status:** Decided
**Date:** 2026-06-11
**Warehouse ID:** dec-1091
**Renumbering note:** originally recorded as "Decision 84" by PR #127, allocated concurrently with the DuckLake-consolidation Decision 84 on a diverged branch (both 2026-06-11). Renumbered 85 at merge -- the consolidation number is cross-referenced from deployed Lambda code, contracts, and warehouse rows, so it keeps 84. PR #127's commit message and the dec-1091 warehouse id predate the renumber and are unchanged.

**Problem:**
CD.22 (pending, gates T1.11) prescribed migrating planning artefacts from PLAN-*.md to PLAN-*.yaml with Pydantic structural validation -- the last narrative-markdown artefact class in the planning pipeline (CD.13). Decision 76 clause 3 hard-codes the plan handoff artefact as `PLAN-{slug}.md`, which the migration supersedes.

**Decision:**
CD.22 is RATIFIED as implemented by T1.11. `PlanDocument` (`scripts/plan_document.py`, schema_version 1, `extra="forbid"`) is the canonical structure for `docs/plans/PLAN-{slug}.yaml`; `validate.py` enforces it in both the `--pre` and full presubmit tiers. `find_plan.py` resolves `.yaml` first; the `.md` path (find_plan.py, plan_audit.py, and the planning / implement / plan-critique skills in both skill roots) emits a deprecation warning for one release cycle, then is removed.

**Decision 76 clause 3 is AMENDED:** the handoff artefact reference reads `docs/plans/PLAN-{slug}.yaml` (was `.md`). The `find_plan.py` deprecation fallback is the transition bridge until the `.claude/commands/plan.md` / `implement.md` reconciliation rec lands.

Historical PLAN-*.md files remain in the working tree and commit history; none are retroactively converted (one-way, non-rolling migration). In-flight conversion list at implementation time (1 of 1): `PLAN-t1-11-plan-yaml-migration.md -> .yaml`.

**Rationale:** Mirrors the RoadmapDocument gate (T-1.5) and the Decision 79 ratify-in-implementing-PR precedent. The `.agents/skills/` mirrors were updated as voluntary legacy hygiene -- Decision 76 supersedes Decision 58's sync obligation; no sync obligation is claimed.

**Related:** CD.13, CD.22, T1.11, Decision 76 (clause 3 amended here), Decision 79 (ratification precedent), Decision 58 (superseded mirror rule), Decision 80 (registry-friendly check design).

---

## Decision 84: DuckLake is the sole ops-store backend; Athena ops estate retired; writer-owned keyspace; named-verb read boundary (Decided)

**Status:** Decided
**Date:** 2026-06-11

**Problem:**
The T2.19 recs-first cutover left the ops store straddling two warehouses. The retained Iceberg copy stopped being a coherent rollback target the day writes moved to DuckLake (reads would time-travel while writes kept landing in DuckLake); the offline outbox inverted its purpose on ephemeral CC-web containers (gitignored pending files die with the container); client-side DynamoDB id allocation left the write boundary unable to police its own keyspace (a colliding write_ops create silently MERGEs); half-migrated read semantics produced the rec-2170 silent false zero; and preflight burned minutes polling Athena tables dead since the 2026-05-28 account migration.

**Ratified premises:** All dev sessions run on Claude Code on the web (no local). All Athena-resident ops data is discardable. ops_decisions is recreatable from DECISIONS.md. The ops store is small and single-writer in practice.

**Decision (four invariants):**
- **I-1 Single backend.** DuckLake-on-Neon (closed reader/writer Function-URL boundary) is the only ops-store backend. The `OPS_STORAGE_BACKEND` rollback flag is deleted. The T2.19 cutover's flag-based rollback mechanism (an AGENTS.md source-of-truth provision, not a Decision 81 clause -- Decision 81 cl.7's closed boundary is RETAINED and extended) is retired. The Athena/Iceberg ops estate (tables, `_current` views, ops_compaction, OpsWriter ops paths, VarChar coercion) is demolished without data migration once live writers are repointed; demolition of non-recreatable tables is gated on the rec-2113 catalog-restore drill (T2.26 START GATE).
- **I-2 Writer-owned keyspace (scoped).** The ducklake_writer owns the `rec-NNN` keyspace: `file_ops` allocates the id inside the write transaction (counter row in the same catalog commit; OCC conflict is the serialization point; client idempotency ULID makes response-lost retries replay-safe). The DynamoDB counters table retires. Sanctioned exceptions: `dec-NNN` follows the human-assigned DECISIONS.md numbering (callers supply `decision_id`); `test-`/probe prefixes remain caller-keyed via write_ops.
- **I-3 Named-verb read boundary (staged).** Application reads use pre-established verbs registered server-side in the ducklake_reader; caller SQL is removed from application paths. `query_ops` is RETAINED for the DQ harness (its checks, including history-table checks, are not yet expressible as verbs) and is restricted/retired in a follow-up once a dq_check verb family exists. Structural `{column, value}` filters replace SQL-fragment row filters (closes rec-2170).
- **I-4 No write buffering (per-table staging).** The recs and decisions pending outboxes are deleted now; a failed write fails loudly at the call site (transient-5xx retry is licensed by the idempotency key). The OpsWriter staging outbox survives ONLY for the not-yet-migrated telemetry/session_log/execution_plans paths and retires with them (Phase 3/4).

**Operational consequences:** destructive Lambda actions gain explicit-confirm guards (create_ops_tables force_recreate; catalog_reinit loses its production-schema default); the telemetry preflight health check is stubbed until telemetry re-lands on DuckLake (Phase 4); catalog DR remains the existing ducklake_catalog_dr nightly pg_dump, with the restore-drill format gap tracked as rec-2113.

**Related:** Decision 81 (CD.33 architecture retained and extended), Decision 79 (per-Lambda deploy gating governs the reader/writer redeploys), Decision 70 (queue current-state semantics preserved inside the priority_queue_current verb), Decision 69 (Single Portal Invariant unchanged), Decision 55 (loud-failure doctrine), T2.26/T2.27 (roadmap carriers), docs/INTENT-ducklake-consolidation.md (full program).

---

## Decision 83: Branch Protection Now Active -- Amends Decision 89 Premise (Decided)

**Status:** Decided
**Date:** 2026-06-08
**Warehouse ID:** dec-1090

**Problem:**
Decision 89 declared GitHub branch protection "permanently unavailable" for this repository under the free GitHub plan (private-repo restriction on `required_status_checks`). The repository was made public 2026-05-30 (Decision 73 / CD.21), removing that restriction. The `terraform/github/` human-gated local apply (CD.20 / T2.12) has since landed, activating the `main-protection` ruleset. Multiple instruction surfaces still assert the false "permanently unavailable" premise, misleading autonomous planning sessions.

**Decision:**
The "permanently unavailable" premise of Decision 89 is reversed. The `main-protection` ruleset is active (`enforcement = "active"`). Configuration: admin `bypass_mode = "always"`, `strict_required_status_checks_policy = false`, required checks = `pr-validate` + `terraform-validate` only, `terraform-converged` advisory-only (CD.35). The ruleset is deliberately non-wedging so the forward-fix model, the Decision 76 squash-merge flow, and autonomous merge all continue to hold.

The merge-gate design consequences of Decision 89 are PRESERVED, not overturned. Convention-plus-tooling remains the effective gate. GitHub-native auto-merge (Decision 76 deferred follow-up) is now technically unblocked.

**Live-probe verification (2026-06-08):**
- Branch protection: `main` `protected: true` (GitHub API, authoritative).
- Dependabot: 5 `dependabot/pip/*` branches active (authoritative).
- GHAS secret-scanning + CodeQL: 403 on alert endpoints (web PAT lacks `security_events`); configuration evidence = `terraform/github/repo.tf` `secret_scanning status=enabled` + committed `.github/workflows/codeql.yml` + CodeQL workflow runs (`success`). Live-probe verification outstanding; one-time UI confirmation recommended.

**Related:** Decision 89 (premise reversed here; merge-gate design preserved), Decision 76 (foresaw reversal; deferred follow-up now unblocked), Decision 77 (guard rationale preserved -- guard is the plan-CONTENT control, not a branch-protection substitute), Decision 73 (public flip enabling the apply), Decision 75 (sanctioned premise correction).

---

## Decision 82: EC8 churn gate measures production invocation fan-out, not in-container thread contention (Decided)

**Status:** Decided
**Date:** 2026-06-07

**Problem:**
T2.17 EC8 (churn commit-latency) was red after PR #89's Branch-P investigation. The gate was implemented
as `action_churn` -- 8 `ThreadPoolExecutor` writers inside ONE Lambda container. Measured wall/cpu ratio
was 31.73x at 1024MB and 10.35x at 3008MB (account max). p95_cpu_ms ~862ms is already inside the
2000ms CD.33 budget; the ONLY failing term is scheduling delay from over-subscribing 8 CPU-bound DuckDB
engines onto <2 vCPU. Reaching budget in that model required ~6 vCPU (~10240MB), blocked by an AWS
account-age Lambda max-memory quota cap.

**Decision:**
Correct the EC8 measurement SUBJECT from "8 writers inside one container" to "N concurrent Lambda
invocations, each its own container/vCPU" -- the production write model ratified by CD.33 clause 3 /
Decision 81. This is a Decision-75 measurement-subject frame correction, not a budget relaxation.

**What is unchanged (NOT a Decision-55 relaxation):**
- Budget VALUES: `COMMIT_LATENCY_BUDGET_MS = 2000.0` and `OCC_COLLISION_RATE_BUDGET = 0.20` are UNCHANGED.
- Gate term: per-invocation wall p95 (`latency_ms`) -- the same term `action_churn` used. Switching the
  comparison to `commit_ms` (which excludes connect/cold-start) would be an implicit relaxation; wall
  is the pinned term.
- `OCC_MAX_ATTEMPTS` unchanged.
- Loud-fail semantics intact (Decision 81 clause 3): schema-gate reject and OCC-retry exhaustion still raise.

**What changes:**
- Concurrency level N steered `CHURN_WRITERS = 8 -> 4` (human steer, 2026-06-07). N is the fan-out
  width, NOT a budget VALUE; the 2000ms / 0.20 ceilings are untouched. Empirical basis below.
- EC8 gate: smoke-test fans out `CHURN_WRITERS=4` concurrent `_sigv4_invoke({"action":"churn_single"})`
  calls. A pre-warm phase first issues N concurrent `attach_check` invocations to bring N containers out
  of cold-start (cold-start is already covered by EC1 `lambda_attach`; EC8 measures warm steady-state).
  One setup invocation (`setup:true`) then pre-creates tables to avoid a CREATE race. The N bodies are
  aggregated into collision_rate + p95 wall + attribution breakdown (connect/commit/cpu/wall_cpu_ratio).
- Handler: new `action_churn_single` dispatches on `"churn_single"` -- setup path calls
  `create_scd2_tables(force_recreate=True)`; normal path runs ONE connect + ONE write
  (`_churn_one_single_write`, the production-representative single-commit unit, with a unique
  `writer_id` per invocation) and returns per-stage attribution. Connectionless action.
- The legacy `action_churn` (in-container 8-thread burst) is retained as an opt-in stress diagnostic
  via `--lambda-churn-incontainer`. A budget miss from that path is informational only, not a gate failure.
- `ducklake_writer` memory_size stays at 3008MB as baseline headroom (NOT reverted). Comment updated.
- The Lambda quota-increase requirement (filed as a blocker rec at PR #89) is WITHDRAWN; the frame
  correction removes the need for >3008MB to pass EC8.

**Empirical basis for N=8 -> N=4 (2026-06-07 live runs, warm containers, DIRECT endpoint):**
- Single warm invocation: wall 1078ms (connect 393ms + commit 681ms) -- well within budget.
- N=8 fan-out (post pre-warm): wall p95 2805ms FAIL. Degradation is concurrent-Neon saturation on the
  DIRECT endpoint -- 8 simultaneous ATTACHes inflate connect p95 393->1585ms and 8 simultaneous catalog
  writes inflate commit p95 681->2285ms. Not a DuckLake code defect; OCC sub-gate still passes (0.0).
- N=4 fan-out: wall p95 1160-1512ms across 3 runs, collision_rate 0.0 -- PASS with margin.
- N=4 remains a faithful OCC + multi-invocation concurrency exercise (CD.33 clause 3) on the unpooled
  DIRECT endpoint; if higher burst width is later required, the Neon pooled endpoint (pgBouncer) is the
  documented lever, tracked separately -- not a budget change.

**Rationale:**
Production ops writes (`file_rec`/`update_rec`) are independent single-commit Lambda invocations, each
its own container/vCPU. The 8-threads-in-one-container harness was harsher than and unrepresentative of
production, and CPU-starved in a way production never will. The architecturally-meaningful OCC-collision
sub-gate is preserved (and arguably exercised more faithfully) by N truly-concurrent invocations hitting
the same Neon catalog simultaneously. The concurrency model is OCC + multiple invocations per CD.33
clause 3; reserved-concurrency=1 or SQS FIFO are not the model.

**References:** CD.33 (production concurrency model, authoritative), Decision 81, Decision 75 (frame-
correction precedent), Decision 55 (no budget relax), Decision 79 (per-Lambda V3 gating). Catalog
authority: CD.34 (Neon), not Decision 78 clause 3.

---

## Decision 81: Ratify the DuckLake ops runtime architecture (CD.33); resolve OQ.7 / OQ.10 / OQ.11 (Decided)

**Status:** Decided
**Date:** 2026-06-04
**Warehouse ID:** dec-1089

**Problem:**
Decision 78 adopted DuckLake for the operational lakehouse but deferred the runtime architecture and four
open questions to T2.16-T2.19. T2.16 (RDS catalog) is complete; T2.17-T2.19 cannot proceed without a
ratified answer to: how the ops Lambdas are decomposed, how writer concurrency is enforced against
DuckLake's OCC (OQ.10), how inlining is flushed and where durability lives (OQ.11), whether an Athena
escape hatch survives DuckLake's lack of an external reader (OQ.7), how current-state reads avoid full
scans, and what the agent-facing portal surface is. CD.10's earlier six-Lambda enumeration was
illustrative, not a settled architecture.

**Decision:**
Ratify CD.33 as the authoritative DuckLake ops runtime architecture:
1. Three-artifact runtime split -- ducklake_writer / ducklake_reader / ducklake_maintenance -- partitioned
   by access pattern for IAM-principal, scaling, and deploy/blast-radius isolation, NOT for concurrency.
2. Supersede CD.10's six-Lambda enumeration. CD.10's verbs were illustrative; this decision commits only
   to the writer/reader/maintenance path split and the closed read/write boundary. The verb/tool surface
   behind writer and reader is deliberately left extensible and is NOT frozen by this decision.
3. Concurrency (OQ.10): concurrent writers + bounded application-level OCC retry (backoff+jitter, fixed
   ceiling, loud-fail on exhaustion) in ducklake_writer. Idempotency is grounded by the write-id mechanism
   (below): a monotonic ULID minted once and reused across retries is the history logical key (DuckLake has
   no engine PKs), and the append is `MERGE ... WHEN NOT MATCHED THEN INSERT` on it, so retries de-duplicate.
   ducklake_maintenance runs as a singleton; the writer-vs-expire_snapshots race is closed by a GC older_than
   grace exceeding max in-flight write duration. Reserved-concurrency=1 and SQS FIFO are rejected as
   over-serialising.
4. Portal surface = read + write categories; the sync category is eliminated because DuckLake's atomic
   catalog-snapshot commit removes the outbox/drain step. Writes are atomic at the catalog commit (no
   external sequencing); aborted commits leave orphan Parquet reclaimed by delete_orphaned_files. The
   Decision 69 Single-Portal invariant -- as carried forward by Decision 78 (which already superseded
   Decision 69) -- is PRESERVED: all writes transit scripts/ops_data_portal.py; only the transport changes.
5. ducklake_writer owns the schema-enforcement gate -- the single, un-bypassable write chokepoint; schema
   rejection and OCC-retry exhaustion fail loudly.
6. ducklake_maintenance is two deterministic scheduled cadences with no LLM / agent invocation: a daily
   non-destructive merge_adjacent_files (compaction; self-correcting) and a separately-cadenced GUARDED
   destructive GC (expire_snapshots -> cleanup_old_files -> delete_orphaned_files) behind a retention floor
   (expire 30d history / 7d current, never below the last 2 snapshots), an older_than deletion grace (>=7d),
   and a circuit breaker (abort+page at >20% files or >10GB; weekly cadence; no scheduled cleanup_all).
   OQ.11 resolved to option (c): inlining DISABLED (ducklake_default_data_inlining_row_limit=0) for
   governance tables so writes land in S3 immediately, eliminating the catalog-only durability window;
   per-table, telemetry may retain inlining.
7. Closed read/write boundary. OQ.7 resolved: no Athena escape hatch -- every read via the reader, every
   write via the writer, nothing out-of-band. Break-glass = the audited PlatformAdmin principal expanded to
   catalog+S3 read for non-routine inspect/repair; catalog DR = a daily PITR export to a dedicated S3 bucket
   with a tested restore runbook. History partitions by day(created_timestamp), current by bucket(N, id)
   (CD.9 ALTER at creation); a partition-prune smoke test gates T2.17/T2.19.
8. current write-through projection: reads come from a materialised Type-1 current table; each write is one
   DuckLake transaction (INSERT history + MERGE current from the in-hand delta). history is the append-only
   source of truth; current is rebuildable from history for DR (deterministically, ordering by
   last_updated_timestamp then ULID). Keys (no engine-enforced PK/FK): history PK = auto-generated monotonic
   ULID; rec_id is the natural key; last_updated_timestamp is high-precision, stable-per-write, ordering-only.
   DQ enforces ULID PK uniqueness, current-version uniqueness (structural via the current MERGE key on
   rec_id), and update_rec in-transaction referential existence.
9. OQ.12 (version/upgrade policy) remains a T2.17 implementation detail (clone-rehearsal default), not
   pre-empted here.

**Capability basis:** clauses 4(atomicity)/6(partition prune)/7(single-txn multi-table + MERGE)/8 were
VERIFIED against the official DuckLake documentation (ducklake.select) before ratification: multi-table
single-snapshot ACID transaction, MERGE INTO, no engine PK/FK (ULID is a logical key enforced by MERGE+DQ),
OCC + application retry, `ducklake_default_data_inlining_row_limit=0` + `ducklake_flush_inlined_data`,
`expire_snapshots`/`cleanup_old_files`/`delete_orphaned_files`/`merge_adjacent_files` semantics, and
`ALTER ... SET PARTITIONED BY` (post-ALTER-only) with `day()`/`bucket(N,col)` transforms and pruning. The
one verified caveat encoded into the design: DuckLake GC deletion safety is a soft time-based deferral, so
the `older_than` grace must exceed the max in-flight reader/writer duration. The write-id is RESOLVED
(ULID logical PK + stable high-precision timestamp); the only T2.17 code task is moving the `_prepare_record`
`now()` re-stamp out of the OCC-retry loop.

**Rationale:**
The split is by access pattern because that is what differs operationally -- a write principal that can
mutate the catalog, a read principal that cannot, and a maintenance principal that runs DDL -- so isolating
them isolates IAM blast radius and deploy risk; concurrency is handled by DuckLake's OCC, not by collapsing
the Lambdas. OCC retry beats reserved-concurrency=1 / SQS FIFO because ops writes are idempotent id-keyed
SCD2 appends, so a conflicted snapshot is safe to retry without serialising the whole write path. Inlining
is disabled for governance tables because the catalog-only durability window is an unacceptable data-loss
exposure for irreplaceable records; the resulting small files are a cheap, self-correcting cost paid down by
daily compaction, while destructive GC is decoupled onto a slower guarded cadence so it can never race a
slow reader or runaway a delete. current is materialised as a write-through Type-1 projection because
"latest per id" is unprunable, so deriving it at read time forces a full scan; a single atomic DuckLake
transaction across history+current keeps them from drifting without external orchestration. The closed
boundary (no Athena escape hatch) is not a limitation we tolerate but the design goal: a lakehouse where
every read and write is mediated and authorised, with one audited break-glass path for DR. The agent verb
surface is left open precisely to avoid re-committing CD.10's mistake of enumerating a "final" surface
prematurely.

**Related:** CD.33 (ratified here), CD.10 (six-Lambda enumeration superseded; the six are status:stub mocks,
confirming illustrative; two-principal allow-list retained; state:pending),
Decision 78 (adopted DuckLake; deferred this runtime architecture; superseded Decision 69), Decision 79
(per-Lambda deploy gating -- the DuckLake Lambdas deploy + smoke-test per CD.16), Decision 69 (Single-Portal
invariant preserved as carried forward by Decision 78),
CD.15 (typed query reader -- refined), CD.8 (DuckDB engine -- unchanged), CD.9 (partitioning via ALTER),
CD.24 (per-Lambda manifests), OQ.7 / OQ.10 / OQ.11 (resolved), OQ.12 (left to T2.17).

---

## Decision 80: Build-Tooling Direction -- defer Bazel/Pants now; do-less baseline; decompose validate.py tool-free (Decided)

**Status:** Decided
**Date:** 2026-06-04
**Warehouse ID:** dec-1088

**Problem:**
A first-principles design conversation proposed adopting Bazel to manage the `scripts/validate.py` monolith and the forthcoming CD.27 agent fleet. On a single-language (Python + Markdown), sub-scale (~36.5k first-party SLOC, one developer), agent-first repo with no compiled build, adopting a polyglot-scale build system risks frame-lock (Decision 75) and large ongoing BUILD-maintenance toil for benefits the repo largely already holds or has sequenced ahead in the roadmap.

**Decision:**
Per the evidence (a C1-C10 claims-verification matrix at commit `ddb85a0`, merged in PR #64):
1. **Do NOT adopt Bazel or Pants repo-wide now.** Only C1/C1b (premise) and C7/C8 (Bazel-specific cost) discriminate against Bazel; C3/C5/C10 bind the lighter do-less path equally (sequencing, not anti-Bazel); C9 (durable-functions readiness) is orthogonal to the build tool.
2. **Adopt the do-less baseline** -- `import-linter` (cycle + layering enforcement), a dependency lockfile, a wired revisit trigger, and a fail-closed edit-scope hook -- as the immediate-next IMPLEMENTATION plan (`PLAN-do-less-baseline`); not a STRATEGIC plan (Decision 67/79 freeze retained), no executor recs.
3. **Decompose `validate.py` tool-free** as a separate IMPLEMENTATION plan. This Decision ratifies the *direction* (a local importable check-registry, NOT a Lambda; `validate.py` stays the thin CLI so the "ci.yml-first" single-source-of-truth invariant holds); the registry *mechanism* (severity-bearing Check protocol, affected-set selection, producer/consumer ordering) is designed in that plan, not ratified here.
4. **Revisit a build orchestrator (evaluate Pants AND Bazel)** only on a wired trigger: executor `concurrency > 1` (T4.4 -- T4.1 owns emitting the concurrency signal) AND (a KG.13 test-impact/caching tier_item is filed OR a measured `_FAST_TIER_BUDGET_SECONDS` breach recurs). The CD.27 ~10-artifact fleet is a watch-signal, not a trigger (firing on it alone re-litigates Decision 79's deliberate "no transitive resolution").

**Rationale:**
At T4.1 concurrency = 1, the genuinely build-tool-only benefit (content-addressed fleet caching with reproducible multi-artifact builds) is roadmap-time-ordered to T4.4/KG.13; the dependency-closure "oracle" is already computable (`ast`/`networkx`, installed); reverse-closure test selection is roadmapped at KG.13, not yet present (`pytest --picked` is changed-test-file selection only). Decision 79 chose explicit per-Lambda manifests with "no transitive resolution" -- the opposite of Bazel's automatic-closure model. Bazel's sandbox is build-time hermeticity, not a live agent edit-scope guard; edit-scope containment for the CD.27 fleet is a present hook/IAM concern (cf. `.claude/hooks/never_on_main.py`), orthogonal to the build tool. The three module-import "cycles" are function-local deferred-import artifacts (the module-load graph is acyclic), so they are Bazel/Gazelle friction owed equally to `import-linter`, not a hard blocker.

**Consequences:**
- `PLAN-do-less-baseline` lands `import-linter` + a lockfile + the two wireable revisit-trigger arms + the edit-scope hook; an explicit owner-obligation is recorded that T4.1 emit the concurrency signal.
- The `validate.py` decomposition is a separate IMPLEMENTATION plan (its registry mechanism designed there); the dominant cost is the `test_validate.py` patch-path migration (239 of 262 patches bind off `validate.<symbol>`).
- No BUILD/WORKSPACE/`pants.toml` files are introduced.

**Related:** Decision 43 (validate.py SLOC waiver this remediates), Decision 60 / Decision 73 (two-tier diff-aware CI the do-less path extends), Decision 75 (Frame-Lock Anti-Pattern, applied to the assessment itself), Decision 67 / Decision 79 (STRATEGIC freeze retained; Lambda-deploy lifted); ROADMAP KG.13, T4.1/T4.4, CD.27 (revisit triggers); the bazel-feasibility supporting analysis (PR #64, commit `ddb85a0`; prose retired per Decision 86).

---

## Decision 79: Ratify per-Lambda packaging manifests + per-Lambda deploy/verify gating; lift Decision 67 Lambda-deploy clause (Decided)

**Status:** Decided
**Date:** 2026-06-03
**Warehouse ID:** dec-1086

**Problem:**
Blanket Lambda-deploy freeze (Decision 67) + whole-src/config copytrees in `build_lambda.py`: verification tier follows filesystem layout rather than the runtime import contract. Config bundled into inactive CLI Lambdas. Plans adding files under `src/` or `config/` incur blanket V3 + DEFERRED tax even when no Lambda handler imports the new code (T0.12 case). Lambda zips carry payload they do not need. Deploy boundary invisible to reviewers.

**Decision:**
Ratify CD.16 (per-Lambda deploy/verify gating) and CD.24 (per-Lambda packaging manifests) as the authoritative architecture. Concretely:

- **Manifest = SSOT:** Each Lambda artifact owns `src/lambdas/<slug>/manifest.yaml` (Pydantic-validated `LambdaManifest` schema). The manifest lists handlers, includes, assets (runtime filesystem reads), config paths, and pip packages. No transitive resolution.
- **Coverage invariant:** `validate_lambda_manifest_coverage` in `validate.py` fails CI if any `src/lambdas/<name>/` directory lacks a manifest.
- **Bundle-completeness gate:** `validate_lambda_bundle_completeness` stages each active artifact into a temp dir, checks handler import-resolution, and asserts every declared `assets[]`/`config[]` path is staged. Full presubmit tier (NOT `--pre`) per Decision 73.
- **Tier from manifest graph:** A plan modifying files named in any active manifest triggers V3 + per-Lambda deploy steps. Pure additions to `src/` or `config/` that no manifest references stay V2.
- **Reverse ONLY Decision 67 Lambda-deploy clause:** The blanket `DEFERRED: build_lambda.py --deploy` pattern is withdrawn. Per-Lambda build/deploy/smoke-test steps are required for plans that modify active artifacts.
- **STRATEGIC clause retained:** Decision 67's STRATEGIC-plan freeze survives via CD.17 / T4.2. Step 12d of plan-critique is unchanged.
- **runtime_config tier declared, fetch deferred:** The `runtime_config[]` manifest field declares SSM/AppConfig paths; the fetch mechanism is a separable follow-on.
- **Decision 44 boundary affirmed untouched:** `build_lambda.py`, `validate.py`, `lambda_manifest.py`, and the planning/critique SKILLs are NOT executor-machinery. `scripts/llm_client.py`, `scripts/llm_utils.py`, `scripts/tool_runtime.py` are executor-boundary files but are only NAMED in the data-pipeline manifest's `includes`, never edited.

**Rationale:**
CD.16 and CD.24 are ratified together because they are one coupled architecture, not two independent changes: CD.16 ("which Lambdas a plan must deploy/verify") is policy without mechanism until CD.24's manifests make "which files a Lambda bundles" authoritatively answerable. Splitting them would ship a gating rule that still infers scope from filesystem layout -- the exact defect being retired. The manifest graph is the single source of truth from which both the deploy-scope decision (`compute_affected_artifacts`) and the file-pattern registry (`derive_lambda_file_patterns`) derive, so the verification tier now follows the runtime import/asset contract instead of where a file happens to live.

Only Decision 67's Lambda-deploy clause is lifted -- not its STRATEGIC-plan clause -- because the two clauses gate on different, independent conditions. The Lambda-deploy freeze was a workaround for executor-telemetry trust leaking into deploy decisions; per-Lambda gating (now mechanically enforced) is the correct replacement, so that clause reverses here. The STRATEGIC-plan freeze gates on the executor pipeline being paused (CD.17 / T4.2), which is unchanged by this work; reversing it here would un-block plans whose recommendations still have no consumer. Amending Decision 67 in place (rather than superseding it) preserves the audit trail for the surviving clause.

**Related:** Decision 67 (Lambda-deploy clause LIFTED, STRATEGIC clause retained), Decision 78 (ratification-mechanism precedent), Decision 48 (deterministic tier classifier), Decision 44 (executor boundary), Decision 76 (web MCP merge flow), Decision 43 (SLOC governance), CD.13 (agent-first manifests), CD.16, CD.24 (ratified here).

---

## Decision 78: Adopt DuckLake for the operational lakehouse (Decided)

**Status:** Decided
**Date:** 2026-06-02
**Warehouse ID:** dec-1085

**Problem:**
The Iceberg-on-S3-metadata read path has proven operationally brittle for the ops/telemetry workload: the Athena-based reader is slow for interactive agent queries, the DuckDB-on-Iceberg snapshot read requires a full metadata scan on every invocation, and the staged CD.31 proposal formalises DuckLake v1.0 as the superior format for ops and telemetry tables -- a metadata-in-RDS-PostgreSQL + data-in-S3-Parquet open table format natively embedded in DuckDB that eliminates the Glue catalog dependency and enables sub-second DuckDB queries directly against S3 Parquet data. OQ.13 (the sole ratification-blocking open question, resolution_tier CD.31) is resolved here by generalising NS.1.

**Decision:**
1. Adopt DuckLake v1.0 for the operational lakehouse (ops and telemetry tables only). Full ratification of CD.31, enacted now including supersessions.
2. Scope: ops_recommendations, ops_decisions, ops_priority_queue, ops_execution_plans, ops_session_log, and all telemetry tables migrate to DuckLake. Product tables (D.lake.*, market_data Iceberg tier) REMAIN Iceberg per the KG.1 platform/product boundary. Market-data DuckLake assessment is deferred to FP-C.
3. Catalog backend: RDS PostgreSQL (db.t4g.micro, single-AZ, PITR enabled) as the DuckLake catalog metadata store -- a durable Glue-analog, NOT a query engine. DuckDB performs all computation against S3-backed Parquet data.
4. Supersedes Decision 50 (superseded by Decision 78: append-only-Iceberg write path -> append-only-DuckLake write path; same append semantics, new format).
5. Supersedes Decision 56 (superseded by Decision 78: SCD2 schema reproduced in DuckLake; optionally extended by ducklake_table_changes CDC and time-travel for richer audit).
6. Supersedes Decision 51 (superseded by Decision 78: JSONL-staging write path -> DuckLake writer in FP-B). CRITICAL: the Decision 69 Single-Portal primitive-level invariant is PRESERVED -- all ops writes continue to go through scripts/ops_data_portal.py; only the underlying staging mechanism changes from local-file outbox to DuckLake writer. The JSONL-staging path physically continues until FP-B/T2.19 migrates the write path.
7. Supersedes Decision 69 (superseded by Decision 78: JSONL outbox staging replaced by DuckLake writer in FP-B). The Single-Portal primitive-level invariant is PRESERVED, not removed. The portal abstraction layer (scripts/ops_data_portal.py) is unchanged; only the transport below it changes in FP-B.
8. Generalises NS.1 (OQ.13 resolution): NS.1 now reads "S3 + open table format at every scale" -- Iceberg for market-data/product tables, DuckLake for ops/telemetry per this decision.
9. Physical migration (OpsWriter replacement, DuckLake writer, SCD2 migration) is deferred to FP-B (T2.19), gated on T2.16/T2.17/T2.18. (Note: this clause originally read "Lambda deploy deferred per Decision 67"; Decision 79 subsequently lifted Decision 67's Lambda-deploy clause -- the DuckLake writer/reader Lambdas deploy + smoke-test per-Lambda per CD.16.)

**Rationale:**
DuckLake v1.0 eliminates the Glue catalog dependency while preserving S3 as the durable data plane, keeping NS.1 intact. The RDS catalog is a metadata store, not a query engine -- NS.3 actively supports a small managed cloud state-store for this role. The Single-Portal invariant is preserved at the abstraction level: the portal interface (scripts/ops_data_portal.py) is unchanged; only the underlying staging transport changes in FP-B/T2.19. Iceberg remains for product/market-data tables (KG.1 boundary), ensuring no cross-domain blast radius.

**Related:** CD.31 (ratified), Decision 50 (superseded by Decision 78), Decision 51 (superseded by Decision 78), Decision 56 (superseded by Decision 78), Decision 67 (interim ratification path used because T-1.1 is not_started; its Lambda-deploy clause was subsequently lifted by Decision 79, STRATEGIC clause retained), Decision 69 (superseded by Decision 78; Single-Portal invariant PRESERVED at primitive level -- portal abstraction unchanged)

---

## Decision 77: Two-Axis Environment/Phase Taxonomy + Sandbox Auto-Apply (Decided)

**Status:** Decided
**Date:** 2026-05-30
**Warehouse ID:** dec-1083 (warehouse title/number reconciliation to 77 is a follow-up via scripts.ops_data_portal; renumbered from 76 to resolve a parallel-authoring collision with the web-workflow-migration decision merged as Decision 76 in PR #10)

**Problem:**
`docs/INTENT-ci-cd-architecture.md` section 6 and Decisions 24/73 affirm a PLATFORM sandbox -> SIT
-> PROD promotion train as future-state, while `docs/ROADMAP-PRODUCT.yaml` retired_items (the "Phase
Infra-Env / Multi-account staging+production model" entry) retired a "sandbox -> staging ->
production" model as overkill. These describe TWO DIFFERENT axes that were being conflated: a
PLATFORM deploy axis (infrastructure) and a PRODUCT config-promotion axis (strategy lifecycle).
Separately, Decision 35 asserts "apply is never automatic", which -- read unconditionally -- blocks
the autonomous infrastructure-improvement substrate the North Star depends on, even for a mocked
sandbox where no real capital is at risk.

**Decision:**

1. **Two-axis taxonomy (the durable fix).** Establish `docs/contracts/environment-taxonomy.md` as
   the canonical vocabulary contract. The PLATFORM environment axis (sandbox / SIT / PROD) answers
   "does this break infrastructure / is the money real"; the PRODUCT phase axis (research,
   backtest_canonical, paper, live_small, live_full) answers "does this strategy deserve capital".
   Reserved vocabulary, enforced by `scripts/validate.py:validate_environment_taxonomy`:
   "environment" = platform axis only; product states are "phases"; "promotion" must be
   axis-qualified.

2. **Affirm the platform promotion train** (cite Decisions 24, 73). Section 6 of
   `INTENT-ci-cd-architecture.md` is the canonical platform-axis design. SIT and PROD remain
   future-state.

3. **Scope Decision 35.** Permit sandbox auto-apply on push to main behind the deterministic guard
   (`scripts/terraform_apply_guard.py`, fail-closed on any destroy / IAM / trust-policy change) plus
   a subagent plan review (`.github/workflows/terraform-apply-sandbox.yml`). SIT and PROD stay
   human-gated. This scopes -- does not overturn -- Decision 35: apply stays human-gated everywhere
   except the mocked sandbox, where the guard + review are the compensating gate (Decision 89 /
   CD.20: branch protection and required status checks are unavailable).

4. **Product promotion stays config-only.** CDP.6 / CDP.7 remain valid for the product axis:
   single-account, promotion-as-config-change. The ROADMAP-PRODUCT retirement is scoped to the
   product axis ONLY and does not touch the platform train.

5. **Single-account-until-live_full (load-bearing).** The platform stays SINGLE-ACCOUNT (the current
   personal account, sandbox environment only) until the product axis reaches live_full approaching
   real capital -- that product event is the named trigger to stand up a dedicated SIT then PROD
   account. Affirming the train as future-state does NOT re-introduce the multi-account posture
   CDP.7 retired.

6. **Re-base Decision 24 vocabulary.** "staging" is renamed "SIT" on the platform axis. Decision
   24's `envs/sandbox.tfvars` multi-tfvars model is superseded by the `terraform/personal/`
   partial-backend reality (`backend-sandbox.hcl`; a future SIT/PROD is a new backend-<env>.hcl).

**Rationale:**
- The conflation was structural: the same words ("sandbox", "staging", "promotion") meant different
  things on each axis, so one axis's retirement looked like it retired the other. A vocabulary
  contract with lint enforcement prevents re-conflation.
- The sandbox is mock-vs-real at one code version, not a version-skew tier; auto-applying it carries
  no real-capital risk, and the fail-closed guard forces every destroy / IAM / trust change onto the
  manual admin-apply path regardless.
- Single-account-until-live_full keeps the affirmation cheap: no new accounts are stood up until a
  concrete product event justifies them.

**Constraints:**
- The guard AND the workflow MUST fail closed: apply runs only on guard `success()`; the guard step
  carries no `continue-on-error`; any non-zero guard exit blocks apply; apply consumes the SAME plan
  file the guard inspected (no re-plan -- no TOCTOU).
- The bootstrap (S3 backend migration + apply role creation) is a one-time MANUAL admin apply under
  `agent_platform_admin`; the workflow takes over only afterwards.

**Related:** Decision 24 (Multi-Environment Deployment Strategy), Decision 35 (Terraform Workflow
Integration), Decision 73 (Two-Tier CI + promotion train), Decision 67 (STRATEGIC deferral; its
Lambda-deploy clause was lifted by Decision 79), Decision 72 (RCA-as-Plan-Source), Decision 89 (branch protection unavailable), CD.21 (GitHub-hosted
OIDC CI), `docs/contracts/environment-taxonomy.md`, `docs/INTENT-ci-cd-architecture.md` section 6.

---

## Decision 76: Claude-Code-on-the-Web Workflow Migration; .claude as Canonical Interactive Layer (Decided)

**Status:** Decided
**Date:** 2026-05-30

**Context:** `/plan` and `/implement` were authored for local dev (Windows + Git Bash): `agent/{slug}` branches, slug derived from branch name, merge via `gh` CLI with a `sleep`/`/loop` poll for CI. On Claude Code on the web the harness auto-creates a per-session branch (`claude/...`), `gh` is unavailable, and the container hibernates between turns -- a turn that ends while polling never resumes, stranding branches.

**Decision:**
1. Model: planning agent pinned to `opus[1m]` (Opus, 1M context); implement agent stays `sonnet`.
2. Branches: the `agent/{slug}` ceremony is removed. Agents work on the harness session branch; the plan slug is derived from the task, independent of the branch name.
3. Handoff: the planning agent merges `PLAN-{slug}.md` to `main` (PR -> fast PR-tier CI -> squash-merge via GitHub MCP) and emits a copy-paste handoff (`/implement docs/plans/PLAN-{slug}.md`); a fresh `/implement` session reads the plan from main by explicit path.
4. PR/merge: all GitHub ops use the GitHub MCP tools; waiting for CI is event-driven via `subscribe_pr_activity` (end the turn; the webhook wakes the session), never `sleep`/`/loop`.
5. Canonical layer: `.claude/commands/` + `.claude/skills/` are now the canonical interactive-workflow layer.

**Amends / Supersedes:**
- Amends Decision 89 ("GitHub Branch Protection Not Available"), clause 4 (`gh pr merge --squash` after CI): squash-merge policy preserved; transport changes to GitHub MCP `merge_pull_request(merge_method="squash")` because `gh` is unavailable on the web harness.
- Amends Decision 23 ("slug derived from branch name"): slug is decoupled from the branch; the anti-contamination intent (one tracked plan per unit of work, branched from main) is satisfied by the harness per-session auto-branch model.
- Supersedes Decision 58 ("`.agents` as canonical interactive workflow layer"): `.claude/` is now canonical; `.agents/` is demoted to legacy alongside `.github/` (no sync obligation).

**Unaffected:** Decision 25 (git worktrees) is a local-dev affordance, unchanged. Decisions 60/73 (two-tier CI, forward-fix) govern the tiers this flow waits on. Decision 67 keeps plans IMPLEMENTATION-type. Decision 44 keeps executor machinery out of scope.

**Deferred follow-up:** GitHub-native auto-merge (container fully out of the merge loop) is the robustness ceiling for the lost-webhook case; unblocked by Decision 83 (branch protection active, CD.20 applied 2026-06-08). Implementation is a follow-on task (configure GitHub-native auto-merge on the PR).

**Related:** Decision 89 (Branch Protection), 73, 60, 67, 44, 23, 25, 58, 55; CD.20, CD.21.

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
Decision 60 (2026-05-05) specified a two-tier validation model with a 5-minute fast-tier budget. The budget was unattainable at ratification: V3 verifiers (PR #274, 2026-05-01) and the DQ runner integration (PR #289, same day as Decision 60) placed ~10 minutes of Athena round-trips in the default presubmit tier on day zero. Twelve subsequent commits to `validate.py` between 2026-05-06 and 2026-05-12 compounded the drift. Measured runtimes show median 18 min, max 50 min -- a 3-10x violation of the documented budget. The structural causes are: (1) the budget had no enforcement mechanism, (2) the tier was defined by exclusion of a barely-used pytest marker (`@pytest.mark.integration` is set on exactly 1 of ~30 AWS-touching test files), and (3) post-merge CI ran on push-to-main duplicating PR CI on the same content. Additionally, with GitHub branch protection permanently unavailable (Decision 89), Decision 89 made remote CI the only merge gate -- yet the gate runs the same slow tier that should be reserved for comprehensive validation. The merge model conflates pre-merge gating with comprehensive validation, and the planning queue currently treats 178 accumulated non-automatable recommendations as mandatory discussion items, which is operational noise while the executor is offline pending Decision 67 reversal.

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
- Decision 89 (Branch Protection Unavailable): the forward-fix model is designed around branch protection being permanently unavailable. *(Premise reversed by Decision 83, 2026-06-08; design consequences preserved.)*

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

**Related:** Decision 44, Decision 55, Decision 60, Decision 67, Decision 68, Decision 71, Decision 72 (RCA-as-Plan-Source), Decision 89 (branch protection), `docs/INTENT-ci-cd-architecture.md`, `docs/ROADMAP-PRODUCT.md` (Phase Infra-Env).

---

## Decision 72: RCA-as-Plan-Source for CI Merge Gate Failures (Decided)

**Status:** Decided
**Date:** 2026-05-11

**Problem:**
CI failures on feature branches require manual diagnosis today. There is no automated surfacing of root cause, and developers may write workarounds rather than fix the underlying issue -- the anti-pattern Decision 55 was designed to prevent. The cc-scheduled-agents pattern (Decision 71) already provides the infrastructure to extend RCA-first diagnosis to the CI merge gate, but it has not been applied there.

**Decision:**
On CI failure (`workflow_run.conclusion == 'failure'`), a `workflow_run`-triggered GitHub Actions workflow (`.github/workflows/ci-rca.yml`) invokes `claude -p` headlessly on the self-hosted runner. The ci-rca agent reads the failed run logs via `gh run view <run-id> --log-failed`, identifies the root cause with evidence, and files a recommendation with `source="ci_rca"` and `priority="critical"` via `python -m scripts.ops_data_portal file_rec`. The agent does NOT propose or execute any autonomous fix. The rec is consumed via the standard `/plan` -> `/implement` flow. A new "CI RCA Recs (open)" section in `session_preflight.py` surfaces open `ci_rca` recs in every subsequent planning session.

**Rationale:**
Reuses the cc-scheduled-agents infrastructure (Decision 71) with a `workflow_run` trigger instead of cron. Reuses `ops_recommendations` as the single rec queue (Decision 50, superseded by Decision 78). Reuses the `source` field as a discriminator (Decision 61). Honours the no-autonomous-fix invariant (Decision 55). Preserves human-in-the-loop architectural judgment -- the ci-rca agent diagnoses and signals, the developer decides and acts via `/plan`.

**Consequences:**
`workflow_run` workflows execute in the context of the default branch but check out at the `head_sha` of the triggering run. A PR that modifies `.claude/agents/scheduled/ci-rca.md` and itself fails CI will invoke ci-rca with that PR's potentially-modified agent file. This is intentional (the PR author gets feedback on their own changes), but a malformed agent definition in a PR can cause that PR's ci-rca run to fail.

**Related:** Decision 50 (Iceberg ops store, superseded by Decision 78), Decision 51 (local-first outbox, superseded by Decision 78), Decision 55 (RCA-first executor), Decision 60 (two-tier validation), Decision 61 (source discriminator), Decision 68 (self-hosted runner), Decision 71 (cc-scheduled-agents pattern)

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

> **2026-05 migration update:** The self-hosted runner substrate referenced here was retired 2026-05-28 (CD.21). cc-scheduled-agents migrated to Claude Code scheduled agents on GitHub-hosted runners; see Decision 73.

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

**Related:** Decision 69 (ops pipeline consolidation, superseded by Decision 78), Decision 51 (local-first outbox, superseded by Decision 78)

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

**Related:** Decision 34 (state machine exit paths), Decision 46 (superseded), Decision 51 (outbox pattern for structured process events, superseded by Decision 78)

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

**Related:** Decision 48 (verification tier), Decision 51 (local-first outbox, superseded by Decision 78), Decision 55 (RCA-first executor), `docs/INTENT-autonomous-improvement-control-plane.md`

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

**Substrate:** A self-hosted GitHub Actions runner on EC2 with the same SSO configuration as the developer machine. Branch protection on `main` requires the workflow to pass; the workflow calls `python -m scripts.validate` with no flags. Zero billed minutes for the default tier. Reversible in 30 seconds. *(2026-06 migration note: runner retired per CD.21; CI now on GitHub-hosted OIDC runners. Branch protection is now active per Decision 83 / T2.12.)*

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

**Related:** Decision 48 (Verification Tier Design), Decision 51 (Local-First Outbox, superseded by Decision 78), Decision 55 (RCA-First Executor -- no rescue agents), Decision 57 (Interactive vs Autonomous SSO recovery), `docs/INTENT-validation-architecture.md`, `docs/INTENT-verification-system.md`, `docs/plans/PLAN-audit-ops-recs-dq-scalability.md` (Gap 2; Future Direction).

> **2026-05 migration update:** The self-hosted EC2 runner substrate referenced in the Substrate field and migration Steps 3-5 was retired 2026-05-28 (CD.21); CI now runs on GitHub-hosted runners (`ubuntu-latest`) with OIDC. The two-tier validation model and both named tiers are unchanged; the substrate switch is transparent to the validation contract. See Decision 73.

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
- The existing outbox drain cycle (Decision 51, superseded by Decision 78) is already offline-resilient. A second ingestion path would duplicate the reliability mechanism.
- The existing `ops_priority_queue_current` view avoids the `_rn` ambiguity bug present in `ops_recommendations_current`. Building a second identical view under a different name adds maintenance burden with no benefit.
- One fewer Iceberg table and one fewer view to keep in sync with the Terraform + OpsWriter dual-definition pattern.

**Closes Open Questions:** Q4 (New table OR extend? - extend via source field), Q5 (New view risk _rn ambiguity? - no new view needed).
**Deferred:** Q3, Q6, Q7, Q8, Q9, Q10 to Phases 2-5 per the strategic plan manifest.

**Related:** `docs/plans/PLAN-cc-scheduled-agents.md` (strategic plan), `docs/plans/PLAN-cc-scheduled-agents-phase-1.md` (this implementation), Decision 51 (Local-First Outbox, superseded by Decision 78), Decision 50 (Iceberg ops data store, superseded by Decision 78)

---

## Decision 89: GitHub Branch Protection Not Available -- CI Enforcement as the Only Merge Gate (Decided)

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
- Acceptance criterion "Main branch protection enabled" from PLAN-validate-two-tier cannot be met. Superseded by this decision. *(Superseded by Decision 83: criterion is now met.)*
- VP steps 9 and 10 from PLAN-validate-two-tier are permanently BLOCKED; they are retired here without resolution. *(Superseded by Decision 83: branch protection is now active.)*
- Any future migration to GitHub Pro or a public repository would unlock `required_status_checks` and should be revisited at that point. *(Superseded by Decision 83: the repository was made public 2026-05-30 per Decision 73 and the apply landed 2026-06-08.)*

**Related:** Decision 60 (Two-tier validation architecture), Decision 68 (Self-hosted EC2 runner), PLAN-validate-two-tier.

> **Amended by Decision 83 (2026-06-08):** Branch protection is now active. The `main-protection` ruleset is live (enforcement=active, non-wedging). The "permanently unavailable" premise is reversed; the merge-gate design consequences are preserved. See Decision 83 for live-probe verification and configuration details.

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

> **2026-05 migration update:** The self-hosted EC2 runner described here was retired 2026-05-28 per CD.21. CI migrated to GitHub-hosted runners (`ubuntu-latest`) with OIDC to the personal account; see Decision 73. The EC2 Terraform definition is retained in `terraform/ec2_runner.tf` as an architectural artefact (no longer applied).

---

## Decision 67: Lambda Deployment and STRATEGIC Plan Execution Deferred Pending Telemetry Readiness (Amended - Partially Active)

**Status:** Amended by Decision 79 (2026-06-03). Two clauses; each has its own status.

**[LAMBDA-DEPLOY CLAUSE -- LIFTED by Decision 79 / CD.16 + CD.24]**
The blanket `DEFERRED: build_lambda.py --deploy` pattern is withdrawn. Plans are now gated per
Lambda artifact (see Decision 79 + CD.16). Step 12b of plan-critique updated accordingly.
The blanket DEFERRED marker is no longer acceptable in lieu of active per-Lambda deploy steps.

**[STRATEGIC-PLAN CLAUSE -- RETAINED, pending CD.17 / T4.2]**
**Status:** Active -- remove when reversal condition is met
**Reversal condition:** Telemetry Athena tables (`telemetry_sessions`, `telemetry_process_events`,
`telemetry_model_calls`, `telemetry_phases`, `telemetry_steps`) confirmed operational end-to-end
with passing data quality checks AND executor re-enabled per CD.17 / T4.2.

**Effect on planning (STRATEGIC clause only):**
- STRATEGIC plans are blocked. All plans must be IMPLEMENTATION type.

**Effect on plan-critique (STRATEGIC clause only):** Step 12d blocks STRATEGIC plans while
this clause is active.

**Rationale (original, preserved):** The executor telemetry pipeline (telemetry_sessions etc.)
is not yet confirmed operational. Running executor-mediated recs risks silent telemetry loss.
Lambda dispatcher is separately disabled pending telemetry confirmation and scheduled-agent
migration completion. The Lambda-deploy half reverses per Decision 79; the STRATEGIC half
reverses when telemetry is confirmed and executor re-enabled (CD.17 / T4.2).

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

> **2026-05 migration update:** The SSO credential model and self-hosted EC2 runner referenced in the Rationale were superseded 2026-05-28 (CD.21); the presubmit DQ runner now executes on GitHub-hosted runners with OIDC. The core decision -- DQ as part of the presubmit tier, no separate Session E scheduling -- is unchanged. See Decision 73.

> **2026-06-16 amendment (premise revisit -- live-reader DQ):** The 2026-05 footnote held the "core decision ... unchanged" after CD.21. That stays true for the Session E MECHANISM itself (cron agent -> EC2 -> commit `dq-latest.json` -> auto-merge), which remains retired. But the load-bearing PREMISE of the no-separate-routine conclusion -- "the presubmit tier already has SSO credentials and runs before every merge," i.e. live DQ is cheap on the credentialed gate -- is now invalidated: CD.21 retired the SSO/EC2 substrate, Decision 73 measured ~10-min presubmit round-trips, and a DuckLake-reader 502 storm added ~17-20 min of DQ-verifier hangs plus merge-gate flapping (2026-06-15; PLAN-dq-gate-infra-resilience). For LIVE-READER-dependent DQ checks specifically (e.g. ulid_history_unique, current_merge_key_unique), the "no separate scheduled routine" conclusion is therefore DELIBERATELY REVISITED -- not reinterpreted: those checks move to a scheduled, non-gating MONITOR/canary that files recs (alarm-not-gate, CD.12), with uniqueness enforced STRUCTURALLY at write time (Decision 81 cl.3 MERGE-on-ULID + cl.8 current-MERGE-key) and only hermetic structural contract checks remaining on the merge gate. The silent-cron failure mode 62 worried about is mitigated by a persistent-unavailability alarm (Decision 74). This revisit is owned by roadmap tier_item T1.6 and is distinct from the GitHub-Actions-scheduled meta-validation (T3.7), which never re-introduced Session E. See docs/ROADMAP-PLATFORM.yaml (T1.6) and docs/plans/PLAN-dq-gate-to-monitor-roadmap.yaml.

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

**Decision status:** Decided -- April 2026 (Superseded by Decision 90)

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

> **2026-05 migration update:** The `company-aws-profile` credential referenced in the Agent SSO Profile Restrictions section was retired; the current model is the `agent_platform` static-key assume-role chain (Decision 73 / CD.21). The multi-environment promotion strategy (separate sandbox/staging/production AWS accounts) is architecturally superseded by the single personal-account model.

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
