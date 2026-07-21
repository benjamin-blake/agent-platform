# AUDIT: Terraform deployment + IAM + CI strategy (redesign-grade design review)

You are a principal infrastructure / platform-security engineer running a self-contained design
review in a fresh session. Execute this prompt exactly as written. Do not ask clarifying
questions -- everything you need is here or in the repository at the current branch HEAD.

---

## 1. TASK

Audit the terraform deployment + IAM + CI strategy of a solo-developer, single-AWS-account,
public-repository ML trading platform, and produce three things in the two deliverable files:

1. A conformance grade of the repository against the REFERENCE SPECIFICATION in section 6,
   pressure-tested for fit (report BOTH repo-falls-short-of-spec gaps AND spec-is-overkill-here
   mismatches -- the spec is an industry-practice GUIDE, not a binding checklist).
2. A root-cause diagnosis (Q1) of why routine infrastructure deploys stall and require a human to
   run, or direct an agent to run, an admin-profile `terraform apply` to unblock them.
3. A target-state redesign blueprint (Q7) with a concrete, sequenced migration path.

You draft; the human disposes. The ONLY files you create or modify in the repository tree are the
two deliverables under `audits/` (section 14). Regenerating gitignored local caches per the SETUP
section is expected and is not a tree modification; never commit them.

Question stubs (full text in section 7): Q1 root cause; Q2 allow-list-vs-deny-list; Q3 role
count; Q4 workflow fleet; Q5 tf-gated-apply reality; Q6 roadmap sufficiency; Q7 redesign
blueprint; Q8 industry-practice rating; Q9 questions-not-asked.

Scope is the deployment / IAM / CI / identity core: REFERENCE SPEC sections 1-4, 6-9, plus the
gate / apply / rollback clauses 5.1, 5.5, 5.6. The data-verb / DQ-evidence clauses (5.2-5.4) are
OUT of deep scope -- mention them in one line under Q8 only if a checklist property depends on
them, otherwise ignore.

---

## 2. CANDIDATE OBSERVATIONS vs VERDICTS (read before anything it governs)

This prompt hands you FACTS and CANDIDATE hypotheses. It never hands you verdicts. Every
candidate below is a neutrally-phrased observation you must ADJUDICATE by tracing it in the
repository -- not a finding to confirm.

ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT. A run that merely confirms the candidates
below has failed. You are expected to reclassify, downgrade, merge, or reject candidates, and to
discover findings no candidate names.

Per-candidate adjudication and how each maps to the output contract (section 14):

- Traced to a CONFIRMED defect -> `findings[]`, `roadmap_crossref.classification = novel`.
- The owning roadmap item / decision exists but its remedy is insufficient or unbuilt -> `findings[]`,
  classification `planned-insufficient` or `planned-unbuilt` (cite the item id).
- Fully covered by an existing item or a property-matched compensating control -> `rejected_candidates[]`
  (name the control or item), NOT a finding.

Two framing hazards specific to this audit, stated so you neither over- nor under-report:

- BELIEF-NEUTRALITY (Q5 especially): the requester believes the gated-apply path "never worked";
  the roadmap marks it complete. NEITHER is authoritative. Trace the mechanism and the evidence
  (section 10, group I) and decide for yourself, per class of change.
- IMMUNITY IS NARROW: the deliberate-constraints do-not-flag list (section 13) stops you from
  reporting a decided constraint as a fresh DEFECT. It does NOT stop you from (a) rating that
  constraint in Q8's checklist as a gap-with-rationale, or (b) filing a `planned-insufficient`
  finding when open recommendations show a "closed" class still recurring. Pressure-testing for
  fit requires both.

CANDIDATE HYPOTHESES to adjudicate (neutral; each may resolve EITHER way -- "the design is
proportionate here" is a first-class outcome, not a failure to find something). These are leads,
not findings; the grounding map (section 10) holds the raw facts. Do not privilege them over
findings you discover independently:

- CH1: the guard's in-budget auto-apply window is narrow (see B). Hypothesis to test: this is the
  primary reason routine changes route to gated-apply/admin -- OR it is proportionate to the risk
  and the friction lies elsewhere.
- CH2: the permissions-boundary model (spec 6.1) is applied to a subset of roles (see E).
  Hypothesis: extending it would let more changes auto-apply -- OR the guard would still block them
  regardless, so boundary coverage is not the lever.
- CH3: the gated-apply job's assumed role is itself boundary-capped (see D). Hypothesis:
  out-of-boundary IAM changes cannot be applied by the gated job even after approval -- OR they can,
  and the "needs admin" experience has a different cause.
- CH4: role count (~E) and workflow count (~C/D and the fleet) are large. Hypothesis: one or both
  is excessive relative to what it accomplishes -- OR proportionate given the guarantees.
- CH5: the convergence / anti-masking / drift / health machinery is substantial (see C/D).
  Hypothesis: its operational cost is disproportionate to the single-account risk it bounds (NS-6)
  -- OR it is warranted.
- CH6: the agent runtime uses a single static-key identity that can assume an `iam:*` admin role
  (see E). Hypothesis: this is a material blast-radius / spec-conformance gap -- OR it is an
  accepted, well-bounded trade-off at this scale.
- CH7: the two planned-but-unbuilt items (T2.41, T2.42) are adjacent hygiene (see G). Hypothesis:
  the core fix for the deployment pain is NOT on the roadmap -- OR it is, somewhere you must find.
- CH8: the built pipeline may already be the right architecture with a few specific gaps (e.g. the
  out-of-budget red-record deadlock, group H) rather than an architecture that needs replacing.
  Hypothesis to hold open: a targeted-repair answer may beat a full-redesign answer.
- CH9 (the opposite pole -- test it too): a control may be dangerously THIN or MISSING, not
  overbuilt. Do not let the "is X excessive?" framing of CH1-CH8 blind you to a control that is too
  weak (candidate leads: the permissions-boundary coverage in E; the empty-reviewer-list bypass and
  the maskable apply-state in H). "The design is proportionate" and "a control is too thin" are BOTH
  reachable, non-defect-or-defect outcomes to weigh.

---

## 3. READ FIRST -- disambiguation traps

Each of these names two things or invites a plausible-but-wrong target. Internalize before you
trace, or you will burn cognition on the wrong object.

- "sandbox" is the name of the single live PLATFORM environment inside the ONE personal AWS
  account. It is NOT a separate AWS account and NOT a throwaway per-task cell. There is exactly
  one live account.
- "gated-apply" / "tf-gated-apply" names BOTH a GitHub Environment (`tf-gated-apply`) AND at least
  two workflow jobs (`gated-apply` in `terraform-apply-sandbox.yml`, `gated-apply-reconcile` in
  `reconcile.yml`). Be explicit about which you mean.
- "convergence record" is an S3 JSON anti-masking anchor (green/red apply-state latch). It is not
  terraform convergence in the mathematical sense and not a terraform lock.
- "the guard" is `scripts/terraform_apply_guard.py`, an AWS-IAM-plan-content classifier. It does
  NOT inspect `github_*` (GitHub-provider) resource diffs.
- Legacy root `terraform/*.tf` files are RETAINED-BUT-NOT-APPLIED architectural artifacts (CD.21).
  Only `terraform/personal/` (live), `terraform/bootstrap/` (manual admin apply), and
  `terraform/github/` (manual local apply) are real apply targets. Do not grade legacy root files
  as live attack surface; a duplicated role NAME across the live and legacy states is a hygiene
  observation, not a live privilege. ONE EXCEPTION applies to the static-key `agent-service-account`
  IAM user: its terraform resource sits in legacy-root `terraform/agent_auth.tf`
  (declared-but-not-applied there, targeting a different account), yet the runtime credential CHAIN
  it anchors is LIVE -- the personal-account `PlatformDev`/`PlatformAdmin` roles trust a user of that
  name in the personal account, and the live user exists out-of-band (Decision 113; groups E/F).
  Trace its actual live state; do not dismiss the static-key credential model as not-applied on the
  strength of this rule.
- Decision 35 ("no auto-apply; human-in-the-loop for apply") is SCOPED, not contradicted, by
  Decision 77 (sandbox DOES auto-apply behind the guard). Decision 24's multi-account model is
  architecturally SUPERSEDED by the single-account model (Decision 77). A superseded,
  company/work-account-scoped "OIDC-only, no IAM users" rule (in `docs/DECISIONS_ARCHIVE.md`, NOT
  the active `docs/DECISIONS.md` that section 13's dedup greps) does NOT govern the personal account
  -- do not flag the personal-account static-key IAM user as a "no IAM users" violation; the
  static-key model is a live, decided choice (Decision 113, do-not-flag item 4).
- Two roadmaps exist: `docs/ROADMAP-PLATFORM.yaml` (this audit) and `docs/ROADMAP-PRODUCT.yaml`
  (out of scope). "T-prefixed" tier items live in the platform roadmap.

---

## 4. SCOPE

In-scope surfaces (obtain every file/line/size by reading the file -- trust no number quoted in
this prompt; re-derive from the repo and record any non-resolving anchor in `meta.stale_anchors`):

- SURFACE guard -- `scripts/terraform_apply_guard.py` + `terraform/bootstrap/authority_budget.json`
  (the deterministic plan-content classifier and its in-budget table). Built.
- SURFACE apply-pipeline -- `.github/workflows/terraform-apply-sandbox.yml`,
  `.github/workflows/reconcile.yml`, `.github/workflows/terraform-drift.yml`,
  `.github/workflows/convergence-health.yml`, `.github/workflows/tf-gated-apply-prototype.yml`
  (the plan / apply / gate / drift / heal / convergence machinery). Built.
- SURFACE iam-identities -- `terraform/personal/oidc.tf`, `terraform/personal/platform_roles.tf`,
  `terraform/bootstrap/github_ci_apply.tf`, `terraform/agent_auth.tf` (legacy-root,
  declared-but-not-applied -- see group E for its live-vs-defined status),
  `terraform/personal/prod_lambdas.tf`, `terraform/personal/ducklake_lambdas.tf` and siblings
  (the CI/deploy roles, runtime roles, Lambda execution roles, the OIDC provider, the permissions
  boundary). Built.
- SURFACE apply-model -- `docs/contracts/deploy-paths.yaml`,
  `docs/contracts/environment-taxonomy.md`, `terraform/CLAUDE.md`,
  `docs/contracts/build-lambda.yaml` (the intent->trigger->recovery model, the two-axis taxonomy,
  the break-glass tier). Built (contracts); the target model is partly designed-unbuilt (see G).
- SURFACE workflow-fleet -- all of `.github/workflows/*.yml` as a set (count, overlap,
  per-file complexity). Built.

Out of scope, one line each: the trading/product logic; the DuckLake/ops data model except as an
apply target; REFERENCE SPEC 5.2-5.4 (data hydration, verb-replay evidence, DQ contracts);
`.github/workflows/claude.yml` / `codeql.yml` / `ghas-probe.yml` / `pr-conflict-signal.yml` except
as members counted under Q4.

Shared vocabulary: "in-budget" = a plan change the guard auto-passes (exit 0); "out-of-budget" =
an IAM-sensitive change the guard blocks (exit 2); "routed" = a workflow output signalling the
gated-apply job to take over; "break-glass" = the operator/human-directed out-of-band apply tier;
"deny-list / invariant model" = safety from a small set of hard denies at a boundary with
default-allow inside (REFERENCE SPEC section 1); "allow-list model" = safety from enumerating what
each identity may do.

Trust-nothing clause: obtain every file / line / size by reading the file. Every quoted anchor in
section 10 is a pointer to re-derive, not a fact to accept. Record any anchor that does not resolve
in `meta.stale_anchors` and lower the affected finding's confidence.

---

## 5. SETUP

Permitted setup, in order. Never abort on a failure -- set the named meta flag, downgrade the
affected confidences, and proceed.

1. `git fetch origin main` then `git rev-parse --short origin/main`. This sha is the audited tree;
   use it in the deliverable filenames, the branch name, and `meta.audited_commit`. If fetch fails
   (network), use `git rev-parse --short HEAD` and set `meta.contract_notes` to note the base could
   not be refreshed.
2. Generate the dedup caches (DEDUP DISCIPLINE in section 13 depends on them):
   `bin/venv-python -m scripts.session.preflight --roadmap-detail full`
   This populates `logs/.preflight-report.json` and `logs/.recommendations-log.jsonl`.
   IF cache-gen fails (creds/egress down): do NOT abort -- set `meta.degraded_dedup=true`, set every
   affected finding's `confidence` to `HYPOTHESIS` and its `roadmap_crossref.dedup_hit_count` to
   `null`, and proceed
   using `docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`, and any committed
   `logs/.recommendations-log.jsonl` read directly from disk instead.
3. Read the in-scope surfaces (section 4) and the GROUNDING MAP anchors (section 10) directly from
   the working tree. Read-only git and file reads only. Beyond the SETUP commands in steps 1-2 (the
   read-only `preflight` warehouse read is sanctioned), do NOT run `terraform`, `aws`, or any
   command that mutates state or calls a cloud-infrastructure API; this is a static + repo-history
   audit.

---

## 6. NORTH STAR -- the REFERENCE SPECIFICATION (an industry guide, pressure-tested for fit)

This specification is the ideal-state bar. Treat it as a strong industry-practice reference, NOT
as binding law: for EACH clause you judge whether it genuinely fits a solo-developer,
single-tenant, single-account, retail-scale, public-repo trading platform, or whether it is
big-organization machinery whose INTENT should be met more cheaply here. Every principle below is
a bar you argue each surface against -- not a pattern to match. Where a clause does not fit, say so
and name what meets its intent at this scale.

The requester has explicitly licensed the redesign (Q7) to propose AMENDING standing repository
Decisions where they are a root cause -- Decision 77 (single-account until the product reaches
`live_full` -- its final phase, real capital at full allocation) is specifically named as
revisitable. When a redesign proposal would reverse or amend a standing
Decision, flag that explicitly in the proposal (name the decision id and why); never silently
treat a decided constraint as a free defect, and never propose weakening the public-repo
confidential-data boundary (Decision 101).

Distilled principles the rubric and questions reference:

- NS-1 (spec 1.1): security is a small set of invariant DENIES at a hard perimeter, default-allow
  inside. Allow-list models that enumerate what identities may do grow monotonically and require
  perpetual human chasing.
- NS-2 (spec 1.2, 8.1): control lives at exactly two points -- org-level invariants no agent
  credential can reach, and plan-time policy evaluation of proposed changes. Identity-time
  permission review is not a control surface; observability replaces pre-approval.
- NS-3 (spec 1.3, 7.x): the human authors invariants and approves amendments to them -- never
  approves individual permission or infrastructure changes.
- NS-4 (spec 6.1): production IAM is safe STRUCTURALLY -- a boundary the mutation cannot detach is
  the cap; no IAM diff is human-reviewed.
- NS-5 (spec 3.1, 9.1): no static cloud credentials in repo, CI, or agent runtime; OIDC
  federation.
- NS-6 (fit-to-scale, this audit's addition): a solo-dev single-account system should reach the
  INTENT of NS-1..NS-5 with the LEAST machinery that achieves it. Proportionality is itself a
  first-class principle here; a control whose operational cost exceeds the risk it bounds at this
  scale is a finding, not a virtue.

The full specification follows verbatim (reproduced with ASCII punctuation). It is the sole source
for Q8's external checklist mapping and the frontier maturity tier.

> # Frontier Agent Platform Specification
>
> Normative reference model for an agent-first repository targeting recursive self-improvement on
> AWS. Audit instruction: compare the repository and its infrastructure against each numbered
> clause. Report conformance, gaps, and any control implemented via allow-list where this spec
> requires an invariant or plan-time policy.
>
> ## 1. Governing principle
> 1.1. Security is enforced by a small set of invariant denies at a hard perimeter, with
> default-allow inside. Allow-list models (enumerating what agents may do) are prohibited as a
> primary control: they grow monotonically and require perpetual human chasing.
> 1.2. Control is exercised at two points only: (a) organization-level invariants that no agent
> credential can reach, and (b) plan-time policy evaluation of proposed changes. Identity-time
> permission review is not a control surface.
> 1.3. The human role is authoring invariants and approving amendments to them - never approving
> individual permission or infrastructure changes.
>
> ## 2. Planes
> 2.1. Control plane - AWS Organizations management account holding SCPs, budget enforcement, the
> audit sink, and the cell-nuke system. No agent identity holds any credential here. Human
> break-glass access only.
> 2.2. Execution plane - disposable sandbox cells where all agent work occurs.
> 2.3. Durable plane - the production account(s). No interactive access for agents or humans;
> mutated only via clause 5.
> 2.4. Promotion plane - the git repository and its gate. The repository is the only durable
> artifact agents can write and the only path into the durable plane.
>
> ## 3. Identity classes (exactly three)
> 3.1. Agent identity - full AdministratorAccess inside its own sandbox cell; zero access to the
> durable plane, the control plane, or the protected path (7.1). Issued via OIDC federation; no
> static credentials anywhere in the system.
> 3.2. Deployer identity - a static role in the durable plane, assumable only by the promotion
> pipeline via OIDC trust conditioned on repository, branch, and environment claims.
> Broad-but-bounded (coarse permissions capped by permissions boundary and SCP); fine-grained
> control lives in gate policy, not in this role's policy.
> 3.3. Control identity - human-held, break-glass, defines classes 3.1 and 3.2. Never used by
> automation.
>
> ## 4. Sandbox cells
> 4.1. The unit of isolation is an AWS account, not an IAM role. One cell per agent, swarm, or task.
> 4.2. Cells are vended by an account-factory API that stamps invariants on creation. Agents may
> self-provision cells.
> 4.3. Invariants applied per cell via SCP, exactly three families: (a) deny all access to the
> boundary itself (Organizations, SCP, billing, audit-sink, factory APIs); (b) hard budget cap with
> automated freeze on breach, not alerting; (c) data perimeter - deny access to data classified
> above sandbox tier and deny egress outside an approved domain set.
> 4.4. Inside the invariants, everything is allowed, including creating arbitrary IAM. No approval
> workflow exists for in-cell actions.
> 4.5. Cells carry a TTL and are automatically destroyed (nuked) at expiry. No cell state is
> durable; durable output exits only through the repository.
> 4.6. CI presubmit executes inside a cell using the cell's admin role via OIDC. CI holds no
> permissions of its own to maintain.
>
> ## 5. Production mutation protocol
> 5.1. The durable plane is mutated exclusively by the deployer identity applying merged,
> gate-passed declarative code (Terraform + verb/pipeline code). No exceptions, including for
> humans.
> 5.2. To modify live behavior (verbs, schemas, DQ rules), the cell is hydrated with representative
> production state: schema clone plus zero-copy, snapshot, or masked/sampled data appropriate to
> the store. Hydration is read-only with respect to production.
> 5.3. Changes to data verbs must ship machine-checkable evidence in the PR: replay of a frozen
> input slice with output diff against golden results; SCD2 verbs prove deterministic recomputation
> and correct effective-dating; append-only verbs prove idempotence and non-mutation of history.
> 5.4. Data quality tests are versioned contracts in the repository, authored freely by agents in
> cells, promoted like any code.
> 5.5. The gate evaluates, in order: policy-as-code (e.g., OPA/Rego) against the Terraform plan
> JSON; data-contract and schema-compatibility checks; the evidence artifacts of 5.3; adversarial
> review by a second, independently prompted agent. Passing all gates auto-merges and auto-applies
> - no human in the loop.
> 5.6. Rollback is declarative: revert the commit; the deployer re-applies. Point-in-time recovery
> covers data-plane incidents.
>
> ## 6. IAM inside the durable plane
> 6.1. Agents may author arbitrary production IAM in Terraform. Safety is enforced structurally: an
> SCP in the durable plane denies role/policy creation and modification unless the mandatory
> permissions boundary is attached, and denies detaching or editing that boundary.
> 6.2. Consequently no IAM diff is ever human-reviewed; the boundary is the cap, the gate policy is
> the check.
> 6.3. The deployer identity's own policy, trust conditions, and the mandatory boundary document
> are amendable only via clause 7.
>
> ## 7. Amendment channel (the fixed point)
> 7.1. The following live in a protected path or separate repository requiring human sign-off
> (e.g., CODEOWNERS + enforced branch protection): SCPs and organization config; the mandatory
> permissions boundary; gate policy code; the gate workflow definition; the deployer identity's IAM
> and trust policy; the account factory; the nuke and freeze systems.
> 7.2. Agents may open proposals against the protected path; they can never merge them. This is the
> sole human approval in the system.
> 7.3. Nothing in the protected path may be modifiable, directly or transitively, by any agent or
> deployer identity. The audit must verify this transitively (e.g., no agent-writable pipeline can
> push to the protected path or assume a role that can).
>
> ## 8. Observability replaces pre-approval
> 8.1. All API activity (CloudTrail, gate decisions, deploy logs) streams to an immutable sink in
> the control plane, outside every agent and deployer identity's reach.
> 8.2. Detection is ex-post: anomaly detection over the sink with automated cell freeze. This is
> affordable because worst-case damage is bounded by budget cap x TTL x data perimeter.
> 8.3. Budget enforcement acts, it does not notify.
>
> ## 9. Audit checklist
> 9.1. No static cloud credentials exist in the repository, CI configuration, or agent runtime.
> 9.2. No agent identity can reach the durable plane or control plane by any direct or transitive
> path (role chains, resource policies, cross-account trusts).
> 9.3. Every sandbox cell has the three invariant families of 4.3 applied and a TTL with automated
> destruction.
> 9.4. The deployer role's trust policy binds OIDC subject claims to the exact repository, branch,
> and environment.
> 9.5. Every role in the durable plane carries the mandatory permissions boundary; the SCP of 6.1
> is present and covers all IAM mutation actions.
> 9.6. All items in 7.1 are in the protected path; branch protection is enforced at the platform
> level and cannot be modified by any agent-reachable identity.
> 9.7. Production is unreachable except through the gate: no console users, no SSH/SSM interactive
> access, no out-of-band apply path.
> 9.8. Verb changes in recent history carry the evidence artifacts of 5.3; DQ contracts exist
> in-repo and are exercised by the gate.
> 9.9. The audit sink is immutable and unreachable from agent and deployer identities; freeze
> automation is tested.
> 9.10. Any control implemented as a human-maintained allow-list of agent permissions is a
> nonconformance: replace with an invariant (clauses 4.3, 6.1) or a plan-time policy (clause 5.5).

---

## 7. THE QUESTIONS

Answer each in `question_answers[]` (section 14) with its pinned verdict (Q9 uses the verdict-less
shape shown in the schema), a `basis` list of
finding ids, and prose. Every question is first-class.

- Q1 ROOT CAUSE. Trace end-to-end WHY a routine infrastructure change can stall and require a
  human to run, or direct an agent to run, an admin-profile `terraform apply` to unblock. Follow a
  concrete change through guard -> route -> gated-apply -> outcome. Decide the PRIMARY cause.
  Verdict enum: `allow-list-iam-model` | `unactioned-roadmap` | `design-flaw` |
  `implementation-defect` | `multiple-compounding`. If `multiple-compounding`, rank the
  contributors.
- Q2 ALLOW-LIST vs DENY-LIST. Is the requester's diagnosis correct -- that the system uses an
  allow-list model where a deny-list / invariant model (boundary-as-cap + plan-time policy) would
  be superior? Identify precisely where the allow-list treadmill manifests and whether a deny-list
  model is FEASIBLE and BENEFICIAL for a single-account, solo-dev system (an SCP requires AWS
  Organizations; assess what substitutes for it at single-account scale). Verdict enum:
  `confirmed` | `partially-confirmed` | `refuted`.
- Q3 ROLE COUNT. Is the IAM role set excessive for what it accomplishes? Classify each live role
  by necessity (essential / consolidatable / removable). State whether the count is a symptom or a
  cause of the deployment pain, and sketch the minimal role set that preserves the current
  security properties. Verdict enum: `excessive` | `proportionate` | `insufficient`.
- Q4 WORKFLOW FLEET. Is the workflow count and per-file complexity excessive? Which workflows are
  essential, which are consolidatable, which are removable scaffolding? Assess the largest apply
  workflow's size and any duplicated apply/gate logic across workflows. Verdict enum: `excessive` |
  `proportionate` | `insufficient`.
- Q5 TF-GATED-APPLY REALITY. For WHICH classes of change does the gated-apply path actually work
  end-to-end? Trace the mechanism and weigh ALL the evidence in section 10 group I (the roadmap
  completion note with two successful applies; the later failed run; the boundary limit that
  constrains what the gated job's assumed role can apply). Distinguish in-boundary changes from
  out-of-boundary changes explicitly. This is belief-neutral: neither the requester's "never
  worked" nor the roadmap's "complete" is authoritative. Verdict enum: `works-all-in-scope` |
  `works-in-boundary-only` | `works-with-caveats` | `broken-in-practice`.
- Q6 ROADMAP SUFFICIENCY. Would executing the already-planned-but-unbuilt roadmap items in this
  territory (at minimum T2.41 and T2.42; search for others) actually resolve the deployment pain,
  or are they adjacent hygiene that leaves the core cause untouched? Is the core fix currently on
  the roadmap at all (scan `tier_items` AND `candidate_decisions`)? Verdict enum: `sufficient` |
  `partial` | `insufficient`.
- Q7 REDESIGN BLUEPRINT. Design the target-state deployment / IAM / CI architecture and a
  concrete, sequenced migration path from today's state. Populate the `disposition` block
  (section 14) with a per-component verdict. Decide whether moving toward multi-account / AWS
  Organizations is worth the investment for a solo dev, or whether the spec's INTENT is better met
  single-account -- argue the cost/benefit, do not assume. Where a proposal amends a standing
  Decision, flag it. Verdict enum for the question itself: `blueprint-provided`. The substance
  lives in `disposition` and prose.
- Q8 INDUSTRY-PRACTICE RATING. Rate the current design against the EXTERNAL CHECKLIST below,
  property by property, in this question's `external_checklist` field. This field is the SOLE
  source the frontier maturity tier reads. A `partial` rating REQUIRES an argued, property-matched
  compensating control in its `evidence`. Verdict enum for the question: `strong` | `adequate` |
  `weak` (a roll-up of the checklist).
  EXTERNAL CHECKLIST (assess each as met | partial | missed):
  - XC1 no static cloud credentials; OIDC federation across CI AND agent runtime.
  - XC2 least-privilege split of plan-time vs apply-time identity.
  - XC3 a mandatory permissions-boundary-as-cap on every mutation identity (structural, not an
    enumerated per-identity allow-list).
  - XC4 a deny-by-default invariant perimeter for the protected controls (SCP-class, or the
    single-account substitute).
  - XC5 plan-time policy-as-code evaluated against the plan JSON (e.g. OPA/Conftest/Sentinel) as
    the change gate.
  - XC6 no-TOCTOU apply: the exact reviewed plan artifact is applied, not a re-plan.
  - XC7 gates fail closed on destroy / trust / privilege-escalation diffs.
  - XC8 drift detection that alarms (not silent).
  - XC9 a tamper-evident deploy + audit record outside the mutating identity's reach.
  - XC10 declarative rollback (revert commit -> re-apply).
  - XC11 a protected amendment channel: the invariants / boundary / gate policy are not
    modifiable, directly or transitively, by the agent-reachable deploy identity.
  - XC12 bounded human involvement: a routine change needs no per-change human permission grant.
- Q9 QUESTIONS THE REQUESTER DID NOT THINK TO ASK. Answer AND extend these seeds, each with a
  `basis`:
  - Does the split-brain between the built allow-list guard and the (partially built) boundary
    model create a state where the deployer role is PERMITTED an IAM action the guard nonetheless
    blocks -- and what does that imply for the redesign?
  - Is the convergence-record / anti-masking machinery's operational cost proportionate to the
    single-account risk it bounds (NS-6)?
  - What is the blast radius if the single static-key credential (agent runtime) is compromised,
    given the roles it can assume?
  - Does gated-apply actually remove the human from routine deploys, or merely relocate the click?
    The `tf-gated-apply` Environment sets `prevent_self_review = false`, so the solo developer
    approves their OWN gated applies -- an approval click is still a human in the loop (the VD4 crux).
  - Add any others a principal reviewer would want answered.

---

## 8. RUBRIC

Rate each dimension per in-scope surface in `rubric_ratings[]`. Pinned enum:
`strong` | `adequate` | `weak` | `absent` | `n/a`. `n/a` is correct and costless where a dimension
does not structurally apply to a surface -- never manufacture a rating or a finding to fill a cell.

- VD1 deny-perimeter-vs-allow-list: is control an invariant/boundary, or a monotonically-growing
  enumeration? (serves Q2, Q8)
- VD2 least-privilege identity minimalism: role count and per-role scope proportionate; no sprawl.
  (serves Q3)
- VD3 plan-time-policy-as-control-surface: is safety a property of the proposed change, or of
  identity-time permission chasing? (serves Q1, Q2, Q8)
- VD4 routine-change autonomy: can a normal deploy complete with no human permission grant or admin
  escalation? (serves Q1, Q5)
- VD5 fail-closed correctness and anti-masking integrity: does the safety model fail safe; is
  apply-state observed and un-spoofable? (serves Q5, Q8)
- VD6 operational simplicity / comprehensibility: workflow count, file size, one-person cognitive
  load. (serves Q4)
- VD7 no-static-credentials / OIDC federation. (serves Q8)
- VD8 protected amendment channel: are the invariants themselves un-modifiable by the
  agent-reachable deploy identity, transitively? (serves Q7, Q8)

Every design-rating question (Q1-Q5, Q7, Q8) is served by at least one dimension, and every
dimension is referenced by at least one question or deep-dive. Q6 (roadmap sufficiency) and Q9
(open questions) are cross-cutting -- answered from the findings, not tied to a single dimension.

---

## 9. DEEP-DIVES

Each feeds named questions and needs end-to-end tracing beyond a rubric cell.

- DD-A (feeds Q1, Q4, Q5). The routine-change trace. Pick a concrete in-scope IAM change (e.g.
  adding a new grant to an existing role, or creating a new CI role). Trace it through:
  `terraform_apply_guard.py` verdict -> the workflow's exit-code branch -> routed=true ->
  the `gated-apply` job's assumed role and its permissions boundary -> whether that role can apply
  the change -> what happens if it cannot. State exactly where a human/admin becomes required and
  why.
- DD-B (feeds Q2, Q7). The allow-list vs deny-list structural analysis. Compare the guard's
  in-budget allow-list (which resource types / actions / role names auto-pass) against the
  boundary policy and the deployer role's own IAM grants. Determine whether the boundary model
  (spec 6.1) is fully built, partly built, or absent, and whether the guard's classification is
  stricter than, looser than, or aligned with what the boundary already permits.
- DD-C (feeds Q1, Q5). The recovery/deadlock trace. Trace what a human must do to clear a red
  convergence record produced by an out-of-budget (guard-blocked) change, and whether the
  automated paths (`workflow_dispatch` acknowledge-and-retry; the Reconcile action) can clear it.
  Cross-reference the open recommendations named in section 10 group H.
- DD-D (feeds Q4, Q7). The workflow-fleet consolidation analysis. Enumerate the workflow set, group
  by concern, and identify duplicated apply/gate logic and scaffolding. Propose the minimal set
  that preserves the current guarantees.

---

## 10. GROUNDING MAP

This map spends your cognition on judgment, not grep. Every entry was observed on disk, but you
MUST re-derive each anchor before relying on it (section 4 trust-nothing clause); record
non-resolving anchors in `meta.stale_anchors`. Facts are stated neutrally and carry no verdict.

A. THE GUARD -- `scripts/terraform_apply_guard.py`
- Exit codes (docstring ~:10-17): 0 = safe to auto-apply; 2 = BLOCKED (requires manual admin apply
  or gated-apply approval); 1 = parse/internal error (also blocks).
- `IAM_SENSITIVE_TYPES` (~:64-74) covers role, role_policy, policy, role_policy_attachment,
  openid_connect_provider, user, group.
- `evaluate_plan()` (~:159-206) order: delete -> neon -> trust-diff -> IAM. A `["delete"]` action,
  a non-create `neon_*` change, a differing `assume_role_policy`, or an out-of-budget IAM-sensitive
  change each produces a blocking finding.
- In-budget pass (`_classify_iam_change`, ~:110-130): true only when the change type is in the
  budget's `in_budget_resource_types`, the action set equals `in_budget_actions`, AND the target
  role is in `in_budget_managed_roles`. A missing/unparseable budget returns fail-closed.

B. THE AUTHORITY BUDGET -- `terraform/bootstrap/authority_budget.json`
- `in_budget_managed_roles` = `agent-platform-github-ci-branch`, `agent-platform-github-ci-pr`
  (two roles). `in_budget_resource_types` = `aws_iam_role_policy`, `aws_iam_role_policy_attachment`.
  `in_budget_actions` = `["update"]`. The comment states it mirrors the `IAMRoleWriteBounded`
  grant and is amendable only via the bootstrap tier.

C. THE APPLY PIPELINE -- `.github/workflows/terraform-apply-sandbox.yml`
- One file, four jobs: `apply-sandbox` (~:86), `speculative-plan` (~:584), `advisory-status`
  (~:821), `gated-apply` (~:909). Re-derive the total line count.
- Push path applies the SAVED plan.bin fetched from S3 (no re-plan; ~:319-348, :454-462); the guard
  runs at ~:358-383 with a three-way branch (exit 2 sets `routed=true` and exits 0); a subagent
  review is a second gate (~:385-452). `workflow_dispatch` is the only path that re-plans
  (~:350-356).
- The `gated-apply` job (~:909-1158) declares `environment: tf-gated-apply` (~:918), assumes the
  same apply role (~:935), and applies the saved plan verbatim after reviewer approval
  (~:1052-1060). Its own comments reference a prior gated-apply run (run_attempt 2) that failed
  producing no RCA signal (~:1146-1158).
- `.github/workflows/terraform-drift.yml` (re-derive line count) is a scheduled
  (`cron: 17 * * * *`) plan-only drift detector under the `github_ci_drift` role: it runs
  `terraform plan -detailed-exitcode` and, on drift, flips the convergence record red and files a
  `tf_drift` rec. No apply step, no `environment:` gate.
- `.github/workflows/convergence-health.yml` (re-derive line count) is a scheduled staleness sensor
  under the `github_ci_branch` role: it reads the convergence record and queries Actions for stuck
  gated approvals, filing/updating a `tf_convergence_stale` rec. Alarm-only, no apply.

D. THE GATED-APPLY ENVIRONMENT + RECONCILE DUPLICATION
- `terraform/github/environments.tf` (~:29-42): `github_repository_environment.tf_gated_apply`,
  `prevent_self_review = false`, reviewers from `var.gated_apply_reviewer_user_ids`,
  `deployment_branch_policy.protected_branches = true`. Header (~:18-24) notes the gated job
  assumes the existing apply role (trust unchanged) and the Environment is the gate; broader IAM
  beyond that role's scope "remain admin-gated".
- `terraform/github/**` and `terraform/bootstrap/**` are documented as NEVER auto-applied (their
  `CLAUDE.md` files); the Environment that gates the pipeline is itself created by a manual local
  apply.
- `.github/workflows/reconcile.yml` re-implements the guard->review->apply and
  guard-BLOCK->gated-apply pattern, including its own `gated-apply-reconcile` job with
  `environment: tf-gated-apply` (~:520).
- `.github/workflows/tf-gated-apply-prototype.yml` is a `workflow_dispatch`-only job that declares
  `environment: tf-gated-apply` and runs only `aws sts get-caller-identity` (applies nothing).

E. THE IAM IDENTITY SET (re-derive counts and boundary presence)
- `terraform/personal/oidc.tf`: one OIDC provider; six CI/deploy roles -- `github_ci_branch`
  (~:352, permissions_boundary ~:355), `github_ci_pr` (~:544, boundary ~:547), `github_ci_plan`
  (~:707, NO boundary), `github_ci_drift` (~:810, NO boundary), `github_ci_ducklake_deploy`
  (~:922, NO boundary), `github_ci_prod_deploy` (~:1048, NO boundary).
- `terraform/bootstrap/github_ci_apply.tf`: `github_ci_apply` role (~:28, permissions_boundary
  ~:31); trust lists BOTH `...:ref:refs/heads/main` AND `...:environment:tf-gated-apply` subs
  (~:60-63); a boundary-conditioned `iam:CreateRole` grant `IAMRoleCreateBounded` (~:285) and a
  two-role-scoped `IAMRoleWriteBounded` (~:303); the boundary policy `DataPlaneAllow` (~:605) uses
  per-service wildcards on `Resource=["*"]` plus `DenyIAMEscalation` (~:642).
- `terraform/personal/platform_roles.tf`: `platform_dev` (PlatformDev, ~:32, no boundary),
  `platform_admin` (PlatformAdmin, ~:224, no boundary) whose inline policy `IAMFull` grants
  `Action="iam:*"` on `Resource="*"` (~:258-260).
- The static-key runtime identity: the personal-account `PlatformDev` and `PlatformAdmin` roles
  (`terraform/personal/platform_roles.tf`, trust blocks ~:44 and ~:236) trust an IAM user
  `agent-service-account` in the personal account (`var.account_id`) via an `sts:ExternalId`
  condition. The terraform `aws_iam_user.agent_service_account` + `aws_iam_access_key` resource
  (holding `sts:AssumeRole` on the PlatformDev + PlatformAdmin ARNs) sits in legacy-root
  `terraform/agent_auth.tf` (~:30, `provider = aws.platform`), whose header states it is
  declared-but-not-applied and targets a different account; the live personal-account user of that
  name is maintained out-of-band (`terraform/CLAUDE.md` "Out-of-band IAM grants"). The static-key
  credential chain (a single access key that can assume PlatformDev daily-ops AND PlatformAdmin
  `iam:*`) is LIVE per Decision 113 regardless of which module's resource is applied. Re-derive the
  actual live definition; do not treat this as legacy-root not-applied hygiene (see section 3).
- Eight Lambda execution roles across `prod_lambdas.tf` / `ducklake_lambdas.tf` /
  `ducklake_maintenance*.tf` / `ducklake_catalog_dr.tf`, none carrying a boundary. Re-derive the
  full role census and how many of the total carry a permissions boundary.

F. THE APPLY MODEL + BREAK-GLASS TIER
- `docs/contracts/deploy-paths.yaml` defines four channels: `provision` (PR touching
  `terraform/**` -> CI plans+applies), `deploy_code` (governed Lambda channels; terraform not
  involved), `reconcile` (input-free heal action, landed), `admin_out_of_band` (human operator
  break-glass; quarantined procedure block).
- `docs/contracts/environment-taxonomy.md` is the SoT for the guard classification and the Axis A
  platform environment axis (bootstrap / sandbox / SIT [System Integration Test, a future dedicated
  account] / PROD); it states "role CREATES stay gated
  (new trust surface)".
- `terraform/CLAUDE.md` documents the operator-only / break-glass local apply as covering "the
  guard-BLOCK / out-of-budget-IAM cases the CD pipeline cannot yet apply on its own", and (in the
  DuckLake IAM closure section) an "iterative-discovery anti-pattern" of successive missing
  refresh-read IAM grants (~:308-322).

G. ROADMAP STATE (re-derive statuses from `docs/ROADMAP-PLATFORM.yaml`)
- The CD.35 terraform-CI/CD wave (the agent-native terraform CI/CD initiative, ratified as
  Decision 92) is marked BUILT: T2.20-T2.25, T2.34, T2.35 (`status: complete`).
  So the gated pipeline, guard, convergence anchor, drift alarm, bootstrap-root privilege tier,
  and authority budget all EXIST. Findings here are candidates for `planned-insufficient`, not
  `novel`.
- Planned-but-unbuilt in this territory: T2.41 (~:7077, "escape-hatch quarantine to a
  deploy-paths.yaml procedure block", exit criteria are prose-instruction-only), T2.42 (~:7122,
  "terraform-path hardening: layer replace policy, committed provider lockfile, content-addressed
  zips, deduped build bash"), T5.2 (old-account teardown, `user_action_required`).

H. OPEN RECOMMENDATIONS (verify each in `logs/.recommendations-log.jsonl`; titles quoted as
   observed at compose time -- re-derive to confirm)
- rec-2523 "Workflow deadlock: a guard-BLOCK red convergence record cannot be cleared by either
  automated path".
- rec-2461 "workflow_dispatch acknowledge-and-retry cannot clear an out-of-budget red convergence
  record".
- rec-2647 "P3a: workflow_dispatch + routed terraform/personal plan has no gated-apply path".
- rec-2648 "P3b: green convergence record can mask a pending out-of-budget IAM delta (drift gap)".
- rec-2703 "github_ci_apply lacks WRITE grants on the 3 T2.43 prod-class resources ...".
- rec-2757 "github_ci_apply still lacks 4 of 6 IAM grants from rec-2754 ...".
- rec-2307 "Add validation block to gated_apply_reviewer_user_ids to prevent empty-list bypass of
  the tf-gated-apply gate".
- rec-885 "lambda_tooling_iam.tf: PlatformAdmin iam:* on Resource=* should scope to account ARN".
- Open `source=tf_drift` recs exist (out-of-band infra drift detected). Re-derive the current set.

I. TF-GATED-APPLY PROOF EVIDENCE -- `docs/ROADMAP-PLATFORM.yaml` T2.22 (~:5963-5978)
- `status: complete`, `completed_at: "2026-06-22"`. The progress note records: a BLOCKING defect
  found at first end-to-end test (VP9: the gated job could not assume the apply role because the
  environment claim overrode the ref-only trust), fixed per Decision 94 (trust lists both subs);
  then a re-run (PRs #223/#225) with "two successful gated applies, apply + revert". Weigh this
  against group H's later failure evidence and the boundary limit (DD-A) when answering Q5.

J. GOVERNING DECISIONS / CONTRACTS (in `docs/DECISIONS.md` unless noted)
- Decision 77 (two-axis taxonomy + sandbox auto-apply; single-account until product live_full;
  EXPLICITLY revisitable by the redesign per the requester). Decision 92 (ratifies the agent-native
  CI/CD, guard = plan-content only, convergence record = sole hard block, authority budget +
  ratchet). Decision 94 (dual-sub OIDC trust). Decision 98 (new CI roles = admin-create; pipeline
  cannot mint roles). Decision 113 (static-key + chained AssumeRole; no SSO on the personal
  account). Decision 126 (two-verb deploy model; agents never self-direct apply; escape hatch
  demoted). Decision 129 (CI-role refresh-read drift declared a generator-fixed class). Decision
  101 (public-repo confidential-data boundary; NOT revisitable).

---

## 11. EMPIRICAL PASS

Sample real change history; observed findings outrank static ones at equal severity. Hard bounds
-- do NOT exceed:

- <= 12 most recent commits touching `terraform/personal/**` OR the in-scope workflows
  (`git log --oneline -n 40 -- terraform/personal .github/workflows/terraform-apply-sandbox.yml
  .github/workflows/reconcile.yml`, then read the relevant ones). For each sampled change apply the
  counterfactual: "under the current guard + budget, would this have auto-applied, routed to
  gated-apply, or fallen to admin break-glass?" Tag the aggregate in prose.
- <= 15 open recommendations whose title matches the terraform/IAM/deploy/convergence/gated-apply
  territory (grep `logs/.recommendations-log.jsonl`). Use these to corroborate or refute candidate
  findings; a live open rec on a candidate makes it `planned-insufficient` (an existing remedy that
  does not fully resolve the issue is insufficient), not `novel`.

Tag every finding's `evidence_kind` as `static` (from reading config/code) or `observed` (from
sampled history/recs). If the sampling caps prevent full coverage, say so in prose -- never imply
you swept everything.

---

## 12. METHOD

Phases, in order:

- P1 READ: the in-scope surfaces (section 4) and GROUNDING MAP anchors, from disk.
- P2 TRACE: run DD-A..DD-D end to end.
- P3 EMPIRICAL: the section 11 sampling, within bounds.
- P4 RATE: fill `rubric_ratings[]` per surface.
- P5 DEDUP: section 13 for every candidate finding before it is filed.
- P6 SYNTHESIZE: answer Q1-Q9; populate `disposition`; then, LAST, compute severity and maturity
  (sections 14-15). Synthesis and maturity computation are always last.

---

## 13. DEDUP DISCIPLINE

Before filing ANY finding, grep the ownership surfaces and record the search on the finding:

- `docs/ROADMAP-PLATFORM.yaml` (tier_items AND candidate_decisions), `docs/DECISIONS.md`, and
  `logs/.recommendations-log.jsonl`.
- Record `roadmap_crossref.dedup_search_terms` and `dedup_hit_count` on every finding. A hit means
  the territory is owned: classify `planned-insufficient` (owner exists, remedy inadequate),
  `planned-unbuilt` (owner exists, not yet built), or move the candidate to `rejected_candidates`
  (fully covered). A finding with NO recorded negative search is a HYPOTHESIS, not a CONFIRMED
  finding.
- If `meta.degraded_dedup=true` (SETUP step 2 failed), every `roadmap_crossref` is `HYPOTHESIS` and
  `dedup_hit_count=null`.

Deliberate-constraints do-not-flag list (do NOT report any of these as a fresh defect; each is a
decided constraint with its id). Immunity is narrow -- see section 2: you MAY still rate these in
Q8's checklist as gaps-with-rationale, and you MAY file a `planned-insufficient` finding where an
open rec shows a "closed" class recurring.

1. Apply is never agent-self-directed (Decision 126). 2. Sandbox auto-apply behind the fail-closed
guard is intentional, not "unguarded auto-apply" (Decision 77/92). 3. Single-account (no SIT/PROD
accounts yet) until product live_full (Decision 77) -- NOTE: the redesign Q7 is licensed to propose
amending THIS one. 4. Static-key + chained AssumeRole, no SSO on the personal account (Decision
113). 5. Bootstrap root and new CI-role creation are admin-only / out-of-band (Decision 92/98). 6.
`terraform-converged` is advisory, deliberately not a required check (Decision 83). 7. Branch
protection is non-wedging by design (admin bypass, strict=false) (Decision 83). 8. Enumerated
`iam:` reads / secrets grants (no wildcards) is intentional (Decision 35/129). 9. STRATEGIC plans
suspended; executor frozen; all plans IMPLEMENTATION-type (Decision 67). 10. Executor must not
modify its own code/prompts/tests (Decision 117). 11. Local `build_lambda --deploy` and the
local-init break-glass loop are demoted-not-deleted (Decision 120/125/126). 12. Legacy root
`terraform/*.tf` + `ec2_runner.tf` are retained-not-applied artifacts (Decision 68/CD.21). 13.
CC-web `claude/*` commits are unsigned; no `required_signatures` (Decision 76/83). 14. CI is
GitHub-hosted + OIDC; the EC2 runner is retired (CD.21). 15. Provider third-party init is
CI-delegated on CC-web; the S3 provider mirror is the sanctioned reversal (Decision 119/120). 16.
The redundant `AgentPlatformRuntime` inline policy and any interim DuckLake code/infra coupling are
tracked follow-ups (terraform/CLAUDE.md). 17. Public-repo confidential-data boundary: never emit
account IDs, ARNs, or ExternalIds in the deliverables (Decision 101) -- NOT revisitable. 18. The
recurring CI-role refresh-read IAM drift is a named, generator-fixed class (Decision 129/T2.34) --
immune from being reported as a NOVEL discovery, NOT from a sufficiency assessment.

---

## 14. OUTPUT

Write exactly two files, both stamped with the base short sha from SETUP step 1:

- `audits/terraform-deploy-redesign-<sha>.yaml` -- the structured audit (schema below).
- `audits/terraform-deploy-redesign-<sha>.md` -- a companion report, prose, <= ~1500 words: the
  executive layer a human reads first (the answer to Q1, the redesign's shape, the highest-leverage
  change, and the honest maturity call).

COUNTING INVARIANT: `findings[]` is the SOLE enumerated list. `total_findings = len(findings) =
novel_count + planned_insufficient_count + planned_unbuilt_count`. Fully-covered candidates live in
`rejected_candidates`, NOT findings. `rubric_ratings`, `question_answers`, and the `disposition`
block are systems-of-record referenced FROM findings, never re-counted. `top_improvements` and
`highest_leverage_change` MUST be finding ids -- EXCEPT when `findings[]` is empty (a valid result,
section 17): then set `top_improvements: []` and `highest_leverage_change: null`. Finding ids use
the prefix `DEP-` with a zero-padded sequence (`DEP-01`, `DEP-02`, ...).

```yaml
audit:
  meta: {audited_commit: <origin/main short sha>, base_branch: main,
         model: <your self-reported model name, free text>, methodology_version: 1,
         scope_surfaces: [guard, apply-pipeline, iam-identities, apply-model, workflow-fleet],
         degraded_dedup: false, contract_notes: "", stale_anchors: []}
  question_answers:
    - {q: Q1, verdict: <allow-list-iam-model|unactioned-roadmap|design-flaw|implementation-defect|multiple-compounding>, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: <confirmed|partially-confirmed|refuted>, basis: [], prose: ""}
    - {q: Q3, verdict: <excessive|proportionate|insufficient>, basis: [], prose: ""}
    - {q: Q4, verdict: <excessive|proportionate|insufficient>, basis: [], prose: ""}
    - {q: Q5, verdict: <works-all-in-scope|works-in-boundary-only|works-with-caveats|broken-in-practice>, basis: [], prose: ""}
    - {q: Q6, verdict: <sufficient|partial|insufficient>, basis: [], prose: ""}
    - {q: Q7, verdict: blueprint-provided, basis: [], prose: ""}   # substance in `disposition`
    - {q: Q8, verdict: <strong|adequate|weak>, basis: [],
       external_checklist: [{property: XC1, rating: <met|partial|missed>, evidence: ""}, ...XC12],
       prose: ""}   # external_checklist is the SOLE source the frontier maturity tier reads;
                     # a `partial` REQUIRES a property-matched compensating control in `evidence`
    - {q: Q9, answers: [{question: "", answer: "", basis: []}, ...]}   # note the different shape
  per_surface_assessment:
    - {surface: <guard|apply-pipeline|iam-identities|apply-model|workflow-fleet>,
       maturity: <derived>, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: <name>, dimension: VD1..VD8, rating: <strong|adequate|weak|absent|n/a>,
       evidence: "file:line|item-id", note: ""}
  disposition:   # Q7's per-component target-state verdict
    <component-name>: {verdict: <keep|retune|consolidate|replace|remove>, mechanism: "",
                       what_changes: "", cost: "", rationale: "", confidence: <CONFIRMED|HYPOTHESIS>}
    # components: guard, authority-budget, convergence-anti-masking, drift-detector,
    # convergence-health-sensor, speculative-plan-saved-plan, tf-gated-apply-environment,
    # gated-apply-jobs, break-glass-admin-tier, ci-deploy-role-set, permissions-boundary-coverage,
    # bootstrap-github-manual-modules, workflow-fleet, static-key-runtime-identity
    # (provider-mirror is do-not-flag item 15 -- mention it in prose if relevant, but it is not a
    #  required disposition verdict; it is out of the deep-scope surface set.)
  findings:
    - {id: DEP-01, surface: <surface|shared>, question: Q1..Q9, dimension: VD1..VD8, title: "",
       evidence: "file:line|item-id", evidence_kind: <static|observed>, current_behavior: "",
       ideal_behavior: "", gap: "", compensating_controls_considered: "",
       change_type: <add|rescope|enforce|unify|persist|clarify|retune_gate|consolidate|remove>,
       proposed_change: "", acceptance: "", severity: <critical|high|medium|low>,
       severity_rationale: "", confidence: <CONFIRMED|HYPOTHESIS>,
       roadmap_crossref: {classification: <novel|planned-insufficient|planned-unbuilt>,
                          item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""},
       effort: <XS|S|M|L>, depends_on: [<finding ids>],
       sequencing: {safe_to_queue_now: <true|false>, blocked_behind: [<finding|roadmap ids>], note: ""}}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "", control_property_match: "",
       decision_or_item_id: ""}
  summary: {total_findings: 0, novel_count: 0, planned_insufficient_count: 0,
            planned_unbuilt_count: 0, top_improvements: [<ids>], highest_leverage_change: <id>,
            maturity_guard: <>, maturity_apply-pipeline: <>, maturity_iam-identities: <>,
            maturity_apply-model: <>, maturity_workflow-fleet: <>}
```

`control_property_match` is REQUIRED whenever a compensating control is the reason for dismissal:
name the property the control exercises, cite where it operates, and state why the control would
FAIL if the defect were real. CONFIRMED requires the behavior traced to file:line or an observed
sampled artifact; anything less is HYPOTHESIS. A finding's `question` and `dimension` name the
PRIMARY one it serves; a finding that bears on several may reference the others in its prose and in
the relevant `question_answers[].basis`.

---

## 15. SEVERITY + MATURITY

Assign severity AFTER judgment, by defect class -- never inherit it from this prompt's framing. A
compensating control lowers severity only if it PROPERTY-MATCHES: it exercises the same property
AND would fail if the defect were real (apply the counterfactual to the control). A control that
cannot catch the break neither lowers severity nor justifies dismissal.

- critical = a deploy/IAM change can be applied wrong-but-trusted, OR an authority-escalating /
  irreversible act proceeds on an unsound gate (e.g. an approval gate that can be bypassed;
  apply-state that can be masked so a broken state reads converged).
- high = a weakness that materially forces admin escalation or breaks routine-change autonomy AND
  whose compensating controls you judged insufficient.
- medium = redundancy / ambiguity / inconsistency with a clear fix (e.g. duplicated apply logic; a
  single very large workflow).
- low = clarity / wording / documentation.

Maturity -- compute LAST, per surface, top-down, first match wins. Pin these thresholds:

- frontier = 0 critical AND 0 high findings on the surface, AND no property in Q8's
  `external_checklist` is rated `missed` (the checklist is global; a single `missed` property means
  no surface reaches frontier -- this is deliberate).
- strong = 0 critical AND <= 1 high.
- solid = <= 1 critical.
- nascent = otherwise.

Findings carry no open/closed status -- every finding is a fresh proposal, so all of a surface's
findings count. A `surface: shared` finding counts toward the maturity of each surface its prose
names as materially affected; a shared finding that names no specific surface counts against all
five surfaces.

The frontier rating remains reachable where you argued a property-matched compensating control
(so a `partial` never blocks it) -- the framing here must not foreclose it.

---

## 16. COMMIT / PR MECHANICS

1. Derive the base ONCE (SETUP step 1): `git fetch origin main`; `git rev-parse --short origin/main`.
   That sha is the audited tree and goes in the two filenames, the branch name, and
   `meta.audited_commit`.
2. `git switch -c audit/terraform-deploy-redesign-<sha> origin/main` so the PR diff is only the two
   deliverable files. (Degraded path: if `origin/main` cannot be resolved -- e.g. SETUP step 1's
   fetch failed -- base the branch off `HEAD` instead and note in `meta.contract_notes` that the PR
   diff may include commits beyond the two deliverables.) This is a deliberate, documented exception
   to the AGENTS.md `claude/*`
   session-branch rule: this session needs a clean two-file diff off the audited base. No CI
   signal-green comment wake applies here -- you end your turn without merging; the human disposes.
3. Repo-wide validation is advisory outside CI here: a clean YAML parse of the two deliverables is
   the real pre-push gate. If an unrelated `validate --pre` fails, record it in
   `meta.contract_notes` and do NOT fix it (write boundary).
4. Commit with `git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign`.
   `git push -u origin HEAD`.
5. Open the PR via `mcp__github__create_pull_request` (base=main, ready for review, title:
   `audit: terraform deployment + IAM + CI redesign review (deploy/IAM/CI/identity)`, body = a 2-3
   sentence lede plus the `summary` block in a yaml fence). Then END THE TURN -- do not poll, do
   not merge, do not subscribe, do not self-approve.

---

## 17. GUARDRAILS

- Write boundary, closed list: the ONLY files you create or modify in the repo tree are
  `audits/terraform-deploy-redesign-<sha>.yaml` and `.md`. Do not edit terraform, workflows,
  contracts, decisions, or the roadmap. Regenerating gitignored caches per SETUP is not a tree
  modification; never commit them. Never emit an AWS account id, ARN, or ExternalId in either
  deliverable (Decision 101).
- Fewer than ~8 surviving findings is a valid result -- state it plainly; do not pad. Precision
  over volume. A rejected candidate with a property-matched control is a real result, not a gap in
  your work.
- You draft; the human disposes. Do not merge, do not open follow-up work, do not file
  recommendations -- the deliverables are the entire output.
- If you finish with material uncertainty (an anchor that would not resolve, a trace you could not
  complete within the caps), say so in `meta.contract_notes` and lower the affected confidences
  rather than guessing.
