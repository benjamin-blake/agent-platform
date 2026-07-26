# AUDIT: dependency declarations, update automation, and lifecycle closure

You are a staff-level build, release, and software-supply-chain reviewer. Execute this brief
verbatim in a fresh session. It is self-contained: do not ask clarifying questions and do not wait
for input. Everything needed is below or in the repository.

## TASK

Audit dependency management at `origin/main`: Python requirements and lock resolution; Lambda
package and layer dependency inputs; workflow-local installs; GitHub Actions, pre-commit, Terraform,
native-tool, managed-layer, and extension dependencies; dependency inventory and validation;
Dependabot coverage; and the full dependency-PR path through CI, policy, merge, deployment, and
failure recovery. Answer Q1..Q7, rate each surface against VD1..VD10, adjudicate the candidate
observations, and recommend a risk-tiered target state. Produce exactly
`audits/dependency-management-<sha>.yaml` and `audits/dependency-management-<sha>.md`, where `<sha>`
is the short audited `origin/main` SHA. The ONLY files you create or modify in the repository tree
are those two deliverables. Regenerating gitignored caches during SETUP is expected and is not a
breach; never commit them. You draft; the human disposes of the PR.

## CANDIDATE OBSERVATIONS VS VERDICTS

This brief supplies facts and hypotheses, not conclusions. ASSUME NO CANDIDATE IS A REAL DEFECT
UNTIL YOU TRACE IT. A run that merely confirms the candidates below has failed. Seek counterexamples,
compensating controls, deliberately excluded surfaces, and issues not seeded here.

The seeded candidate registry is C1..C15 in GROUNDING MAP. Map every seeded candidate exactly once
using `candidate_ids` on a finding or `candidate_id` on a rejection. A candidate may map to only one
of those records. After recon, sort executor-discovered candidate titles lexicographically and assign
ids C16 upward; record one only if adjudicated into one of those two collections:
- CONFIRMED defect with no adequate owning item -> `findings`, classification `novel`.
- Real gap with an owning item whose remedy is inadequate -> `findings`, classification
  `planned-insufficient`.
- Real gap with an adequate but unbuilt owning remedy -> `findings`, classification `planned-unbuilt`.
- Fully covered by an owning item, or not a defect because a property-matched control exists ->
  `rejected_candidates`, naming that item or control.

Do not inherit severity from this prompt. Assign it only after tracing behavior and testing controls.

## READ FIRST - DISAMBIGUATION TRAPS

- "Dependency graph" can mean the first-party Python import graph produced by
  `scripts/dependency_graph.py` or the external package/component inventory. The latter is the
  target; use the former only as evidence for declaration completeness.
- "Requirements" can mean `requirements.txt`, `requirements-fast.txt`, `requirements-dev.txt`,
  `requirements.lock`, a temporary Lambda requirements file, or a manifest's `pip_packages`.
  Establish the role and authority of each before comparing them.
- "Auto-merge" can mean enabling GitHub-native auto-merge on one PR, a workflow issuing a merge,
  or an agent's PR lifecycle. Treat these as different mechanisms with different credentials and
  failure modes.
- "Dependabot visibility" is not vulnerability visibility. Version updates, security updates,
  dependency-graph submission, and vulnerability alerts are distinct capabilities.
- "CI green" is not necessarily deploy-safe when a dependency is embedded in a Lambda layer,
  generated ZIP, native executable, or extension.
- "Runtime-provided" may mean standard library, Lambda base runtime, AWS-managed layer, custom
  layer, native executable, or downloaded DuckDB extension. Do not infer who updates it.
- "Lockfile synchronized" may describe a subset-presence check rather than installation from the
  lock. Trace both generation and consumption.
- "Orphaned" may describe an open PR, branch without PR, conflict, superseded update, failing
  check, disabled auto-merge request, or abandoned human review. Classify observed examples.

## SCOPE

Rate these built surfaces separately:
- S1 Python declarations: `requirements.txt`, `requirements-fast.txt`, `requirements-dev.txt`,
  `requirements.lock`, `pyproject.toml`, and any other discovered Python manifest.
- S2 Lambda and generated dependency inputs: `scripts/build_lambda_config.py`,
  `scripts/build_lambda_packaging.py`, `scripts/lambda_manifest.py`, every
  `src/lambdas/*/manifest.yaml`, attached layer declarations, and version SSOTs under
  `config/lambda/`.
- S3 Workflow-local and tool dependencies: named `pip install` arguments, GitHub Action `uses:`
  references, `.pre-commit-config.yaml`, Terraform CLI pins, native tools, downloaded binaries,
  managed layers, and extensions referenced by build/deploy paths.
- S4 Inventory and consistency enforcement: `scripts/checks/deps/**`,
  `scripts/import_governance.py`, dependency portions of `scripts/checks/_scaffolding.py`, their
  registry wiring and tests, plus any SBOM, vulnerability, license, EOL, or provenance checks.
- S5 Dependabot configuration: `.github/dependabot.yml`, all applicable package ecosystems and
  directories, grouping/schedule/limits, security-update behavior, ignored dependencies, and
  generated-file behavior.
- S6 Dependency-PR CI and protection: `.github/workflows/ci.yml`, relevant workflow permission and
  event filters, `terraform/github/repo.tf`, `.github/CODEOWNERS`, and structural CI guards.
- S7 PR lifecycle and deployment closure: any automation that labels, updates, queues, approves,
  enables auto-merge, merges, closes, or escalates dependency PRs; governed Lambda deployment and
  Terraform apply paths only as consumers of merged dependency changes; post-merge validation and
  forward-fix mechanisms.

Out of scope: trading strategy quality and performance; changing application code; redesigning
general CI except where dependency PRs exercise it; changing Terraform apply classification;
executing a production deployment; evaluating individual package quality except where needed to
demonstrate policy; and editing any audited surface.

Trust nothing quoted here: obtain every file, line, identifier, count, branch state, and artifact
sample by reading the audited tree. Record every non-resolving or materially moved anchor in
`meta.stale_anchors`; correct your working understanding and proceed.

## SETUP

Derive the audited base once and inspect it read-only:

```bash
git status --short
if git fetch origin main; then
  BASE_REF=origin/main
elif git rev-parse --verify origin/main >/dev/null 2>&1; then
  BASE_REF=origin/main
else
  BASE_REF=HEAD
fi
BASE_SHA=$(git rev-parse --short "$BASE_REF")
```

Immediately switch to the audit branch described in COMMIT / PR MECHANICS, then run
`bin/venv-python -m scripts.session.preflight --roadmap-detail full` and perform all reads from that
working tree. Do not install or upgrade dependencies for reconnaissance. Existing
read-only validation commands may be run when they do not mutate tracked files.

If fetch fails but `origin/main` resolves locally, use that ref, set `meta.degraded_fetch=true`, add
a semicolon-delimited `fetch: <failure and consequence>` entry to `meta.contract_notes`, and
downgrade claims depending on remote freshness to HYPOTHESIS. If neither fetch nor `origin/main`
resolves, use the current `HEAD` as `BASE_REF`, set both `base_branch: local-head` and
`meta.degraded_fetch=true`, record `fetch: no origin/main; audited local HEAD` in contract notes,
and proceed. The branch and filenames still use the resulting short SHA.

If the working tree is dirty before branch creation, do not erase changes. Run
`AUDIT_WT=$(mktemp -d)/dependency-audit`, `git worktree add "$AUDIT_WT" "$BASE_REF"`, `cd "$AUDIT_WT"`,
then perform the COMMIT / PR MECHANICS there. Record `worktree: <path>` in contract notes. If branch
creation reports that the exact branch already exists, append `-rerun-$(date -u +%Y%m%d%H%M%S)` to
the branch name only; filenames and `audited_commit` remain unchanged.

The displayed preflight command always writes `logs/.preflight-report.json`. With working
credentials it also calls the repository's warm sync, which may drain the sanctioned legacy ops
outbox before pulling the recommendations cache; this external operational side effect is expressly
permitted for this SETUP command and is not a tracked-tree write. It does not refresh recommendations
when credentials or the reader are unavailable. After it runs, read `recs_read_status` in the report:
anything other than `ok`, a missing recommendations cache, or command failure is cache-gen failure.
In that case do NOT abort - set
`meta.degraded_dedup=true`, mark every `roadmap_crossref.confidence` as HYPOTHESIS and
`dedup_hit_count=null`, and proceed. Dedup uses ownership status current at audit execution, not a
reconstruction of status at the audited SHA; record the cache generation date in contract notes.
If an optional read-only command fails for an unrelated environment reason, record it in
`meta.contract_notes`, downgrade affected confidence, and continue.

## NORTH STAR

Judge each surface against these principles. They are bars to argue against, not absolutes:
- NS1 Complete inventory: every external component has an accountable maintenance owner (the
  repository person, team, or automation explicitly responsible for disposition), purpose, runtime/build consumer,
  update authority, and lifecycle state.
- NS2 Role-true authority: each closure has one authoritative declaration or a mechanically
  enforced derivation chain; duplicate declarations cannot drift silently.
- NS3 Reproducible resolution: reviewed inputs recreate tested and deployed bytes for every
  production artifact, Lambda package/layer, native binary, and extension. Dev-only tools may use a
  weaker policy only when CI resolves and tests the proposed version before merge. Pins must not
  freeze updates invisibly.
- NS4 Risk-proportionate automation: routine changes flow with little human toil while security,
  major, infrastructure, native, and production-critical changes receive property-matched review.
- NS5 Evidence before merge: required checks exercise the behavior that the changed dependency can
  break, including build and smoke evidence when ordinary unit tests are insufficient.
- NS6 Closed lifecycle: every update is merged, rejected, superseded, or escalated within a defined
  time; no branch or PR waits forever without an owner.
- NS7 Least-privileged supply chain: update and merge identities cannot approve or bypass controls
  beyond their policy. Test integrity controls by class: Python resolution through a declared
  registry plus lock/hash policy appropriate to its closure; GitHub Actions through immutable SHA
  or an argued vendor/tag control; native downloads through checksum/signature or immutable internal
  artifact; managed layers through versioned ARN; extensions through versioned URL plus verified
  byte source. The executor judges compensating controls against these named properties.
- NS8 Deployment closure: merging an input update predictably refreshes the consuming artifact and
  verifies it through the repository's governed channel.
- NS9 Observable maintenance: latency, failures, stale updates, vulnerability exposure, and EOL
  status are visible and actionable without creating alert fatigue.

## THE QUESTIONS

### Q1 - Declaration completeness

Are all external dependencies declared in an authoritative, machine-readable manifest that the
appropriate updater or scanner can discover? Verdict: `complete|partial|incomplete`. Trace
third-party imports and build/install/download operations back to a declaration. Distinguish direct,
transitive, optional, lazy, platform-specific, runtime-provided, native, extension, and tool-only
dependencies. Inventory every direct repository input and every first-level component intentionally
packaged, downloaded, attached, or loaded at runtime. For deeper transitive internals, assess the
resolver/lock/vulnerability mechanism as a class; do not enumerate Action internals, provider
internals, shared-library closures, managed-layer contents, or extension internals package-by-package.

### Q2 - Dependabot visibility

Is every updateable dependency surface covered by an appropriate Dependabot ecosystem and directory,
or by an explicit alternative with equal lifecycle closure? Equal lifecycle closure means all six
properties: update discovery, change proposal, protected testing, disposition, consuming-artifact
refresh where applicable, and stale/failure escalation. Verdict: `complete|partial|incomplete`.
Assess supported manifest formats, nested directories, Python lists, generated files, Terraform
roots, pre-commit hooks, GitHub Actions, ignored components, security updates, and what the current
group actually edits.

### Q3 - Declaration integrity and reproducibility

Do requirements, lockfiles, Lambda inputs, runtime layers, workflow installs, and deployment
fingerprints stay synchronized without divergent authorities or silent freezes? Verdict:
`strong|adequate|weak|absent`. Trace generate -> validate -> install/build -> fingerprint -> deploy.
Apply the counterfactual: if one declaration changed alone, which standing check would fail before
the old dependency remained deployed or a different version was resolved?

### Q4 - Update lifecycle

Does a Dependabot PR have a reliable path through creation, CI, review/policy adjudication, merge,
post-merge validation, deployment when applicable, and failure recovery? Verdict:
`closed-loop|partially-closed|orphan-prone`. Identify the exact present stopping point and ownership.
Ownership evidence, strongest first, is an explicit contract/roadmap assignment, CODEOWNERS entry,
workflow/configured automation, then the repository's named sole maintainer. Git history alone is
not ownership. If none applies, record no explicit owner rather than guessing.
Apply the counterfactual: if the human ignored all dependency PRs for 30 days, what deterministic
mechanism would merge, close, supersede, or escalate each class?

### Q5 - Automation policy

Judge the overall policy `sufficient|partial|insufficient` in the Q5 answer. Separately choose a
target mechanism per update class in `automation_policy`, using
`auto-merge|queued-auto-merge|human-review|prohibited-auto-merge`. Cover patch, minor, major,
security, runtime, dev/test, GitHub Actions, Terraform providers, pre-commit, Lambda-only, native,
and extension updates. Compare at least: GitHub-native auto-merge enabled by a least-privileged
workflow; direct workflow merge; a merge queue; scheduled maintenance; Renovate; and deliberate
manual review. Do not assume maximal automation is best. For each class specify gates, deployment
effects, rollback/forward-fix behavior, stale handling, and why the identity can or cannot bypass.
Record the six-way mechanism comparison once in `automation_options_comparison`, not redundantly in
every class. Numeric SLO proposals are executor judgment: recommend ranges, identify their evidence,
and label policy choices rather than implying an existing standard. Use only the bounded PR sample,
current official vendor guidance, and repository cadence/ownership evidence; if those do not support
a numeric range, recommend a measurement period instead of inventing one.

### Q6 - Industry-practice comparison

Rate the repository `leading|aligned|partial|lagging` against every property in this EXTERNAL
CHECKLIST, recording `met|partial|missed` and evidence property-by-property:
1. authoritative manifests or mechanically synchronized authorities per deployed closure;
2. reproducible lock/digest resolution where determinism is required;
3. automated inventory and import/build-closure-to-manifest validation;
4. CI on dependency PRs using protected required checks;
5. branch protection preventing merge before those checks pass;
6. risk-tiered patch/minor/major and runtime/dev/infrastructure policy;
7. explicit, distinct security-update handling;
8. policy based on trusted Dependabot metadata, not branch-title parsing alone;
9. grouping, schedule, PR-limit, cooldown/noise, stale, and supersession controls;
10. artifact build and smoke evidence for packaged/runtime dependencies;
11. post-merge detection, escalation, recovery, and update ownership;
12. immutable references/provenance/integrity and least-privileged automation;
13. a reasoned Dependabot-versus-Renovate/queue/manual choice;
14. update latency, remediation latency, stale age, recurring failure, and EOL observability.

Use current official vendor documentation as external evidence; a current product reference page
controls over an older tutorial, and a dated vendor changelog controls only for behavior introduced
there. Start with GitHub's official Dependabot
automation, configuration-options, supported-ecosystems, security-update, auto-merge, permissions,
and dependency-review documentation. Browse current sources; cite URLs and access date in the report.
If browsing fails, do not abort: set `meta.degraded_external_research=true`, rate external claims
HYPOTHESIS in prose, rely on repository evidence for findings, and do not award `leading`.

### Q7 - Questions the requester did not ask

Answer each of these 16 semicolon-delimited seeds in its own `question_answers[].answers` row and add
at least one executor-discovered question, for at least 17 rows total: transitive vulnerability visibility;
whether the lock is consumed or only checked; import-to-distribution mapping; lazy/optional imports;
native and managed-layer ownership; GitHub Action mutability; Terraform and pre-commit coverage;
licenses/provenance/SBOM; batching versus bisectability; unmaintained/EOL packages; Dependabot-token
and secret behavior; deployment of merged Lambda changes; rollback versus forward-fix; security and
ordinary update SLOs; whether stale-update monitoring itself can become noisy or orphaned; and
whether accountable maintenance ownership and escalation survive 30 days of human absence.

## RUBRIC

Emit exactly 70 rubric rows: every cross-product cell S1..S7 x VD1..VD10. Use
`strong|adequate|weak|absent|n/a`. `n/a` is correct and costless; do not invent applicability.
Use `n/a` only when the surface cannot own or influence the property described by that dimension;
state that structural reason in `note`.
- VD1 inventory completeness (Q1, Q7)
- VD2 updater visibility (Q2, Q6)
- VD3 authority and synchronization (Q1, Q3)
- VD4 resolution reproducibility (Q3, Q6)
- VD5 CI effectiveness (Q3, Q4, Q6)
- VD6 merge-policy safety (Q4, Q5, Q6)
- VD7 lifecycle closure (Q4, Q5, Q7)
- VD8 deployment closure (Q3, Q4, Q5)
- VD9 vulnerability and supply-chain posture (Q6, Q7)
- VD10 operability and observability (Q4, Q5, Q7)

## DEEP-DIVES

### DD-A - Closure-to-declaration trace (feeds Q1-Q3)

Enumerate third-party Python imports with AST or bounded `rg`, then map import name to distribution
and consuming runtime. Separately enumerate install/download sources: all tracked requirements and
locks, `pip_packages`, package lists/constants, workflow `pip install`, action `uses:`, pre-commit
repos, Terraform providers, custom/managed Lambda layers, native binaries, and DuckDB extensions.
For each class record authority, updater, pin style, validation, consumer, and deploy trigger. Do not
list every transitive lock entry in the report; summarize and attach only exceptions as evidence.

### DD-B - Dependabot behavior trace (feeds Q2, Q4-Q6)

Trace current ecosystem entries against discovered manifests using current GitHub documentation.
Establish whether grouped updates span the manifest files that the PR itself identifies as members
of its group. From all repository PRs targeting `main` whose author login is the Dependabot app,
sample the five with greatest `updated_at` (or all if fewer), whether open or closed; there is no
time-window cutoff. Determine which workflows run for Dependabot PRs, what token permissions
they receive, whether required checks gate them, and whether any actor currently enables auto-merge.

### DD-C - Build/deploy counterfactuals (feeds Q3-Q5)

For each deployable closure, ask: if only this dependency version changes, does the correct artifact
rebuild; does its identity/hash change; does CI test or smoke it; does the governed channel deploy it;
and can ignore/lifecycle settings preserve the old runtime silently? Static reasoning is sufficient;
do not build or deploy. A control property-matches only if it exercises the same property and would
fail under the hypothesized break.

## GROUNDING MAP

This map spends cognition on judgment, not grep. Verify every anchor against the audited base before
relying on it; stale lines go in `meta.stale_anchors`.
- C1 - `.github/dependabot.yml:1-23` declares root `pip` and `github-actions` weekly update entries, each
  with a minor/patch group and five-PR limit.
- C2 - `requirements.txt:1-39` declares the root runtime direct dependencies; `requirements-fast.txt:1-17`
  declares the fast-CI subset; `requirements-dev.txt:1-14` declares dev/test tools.
- C3 - `pyproject.toml:1-36` contains pytest, Ruff, and coverage configuration and no visible project
  dependency table at this anchor.
- C4 - `scripts/build_lambda_config.py:30-59` defines `PROD_DEPS` and `DUCKLAKE_DEPS` as Python lists;
  compare their constraints and members to all tracked manifests without presuming a defect.
- C5 - `scripts/build_lambda_packaging.py:130-159,207-239` writes those lists to temporary requirements
  files and installs them into layers.
- C6 - `src/lambdas/data-pipeline/manifest.yaml:52-65` declares `pyyaml` in `pip_packages`; other active
  manifests include empty lists and notes describing dependencies supplied by layers.
- C7 - `scripts/import_governance.py:52-95` checks that root requirements top-level names have pins in
  `requirements.lock`; trace what it intentionally does not claim.
- C8 - `.github/workflows/ci.yml:6-10,16-67` runs PR validation for PRs targeting main and installs fast
  plus dev requirements before `scripts.validate --pre`.
- C9 - `terraform/github/repo.tf:81-107` configures PR protection and required `pr-validate` and
  `terraform-validate` checks with strict-up-to-date disabled.
- C10 - `terraform/github/repo.tf:126-135` configures default read-only workflow permissions and disallows
  Actions from approving PR reviews.
- C11 - `.pre-commit-config.yaml:3-19` pins two external hook repositories.
- C12 - `terraform/main.tf:3-6`, `terraform/personal/main.tf:16-27`,
  `terraform/bootstrap/main.tf:14-17`, and `terraform/github/main.tf:14-17` declare provider
  constraints in multiple roots; committed lockfiles exist under at least two roots.
- C13 - `docs/plans/PLAN-dependency-declarations-ci-config.yaml:16-48,274-283` records a proposed and
  subsequently retained scope that separates runtime/dev/fast/lock roles and treats Lambda
  dependency lists separately. Determine implementation state from the audited tree and history.
- C14 - `logs/.recommendations-log.jsonl` may contain an open recommendation titled "Move DUCKLAKE_DEPS
  out of a Python list literal into a Dependabot-watchable requirements file". Resolve its current
  id and status from the generated cache; do not trust an id quoted by prior context.
- C15 - Repository workflow files contain direct named `pip install` arguments in addition to
  requirements-file installs. Enumerate them and judge whether each is an authority, bootstrap
  input, or harmless repetition.

## EMPIRICAL PASS

Sample exactly the deterministic set defined in DD-B: the five greatest `updated_at` values, or all
when fewer exist. Describe whatever ecosystem/state mix results; do not substitute for diversity.
Use GitHub read APIs if available; never modify a
PR. For each sample record: dependency class, created/updated age, files changed, checks triggered,
check conclusion, review/auto-merge state, merge/close outcome, and the counterfactual reason it
would or would not eventually leave the queue without a human. Tag repository-only deductions
`static` and PR/API observations `observed`; observed findings outrank static findings at equal
severity. If GitHub read access fails, set `meta.degraded_empirical=true`, use local refs/caches if
available, cap confidence at HYPOTHESIS for lifecycle frequency claims, and proceed.

## METHOD

P1 establish the audited base and generate caches. P2 inventory every S1..S7 surface and verify
anchors. P3 perform DD-A and reconcile declarations with actual consumers. P4 perform DD-B and the
bounded empirical pass. P5 perform DD-C without builds or deployments. P6 rate each rubric cell and
answer Q1..Q7. P7 deduplicate every surviving candidate. P8 assign severity and sequence changes.
P9 compute per-surface and overall maturity LAST. Do not draft the executive report before P8.

## DEDUP DISCIPLINE

Before filing any finding, search `docs/ROADMAP-PLATFORM.yaml` candidate decisions and tier items,
`docs/DECISIONS.md` decision headers/bodies, `docs/plans/`, and the generated
`logs/.recommendations-log.jsonl`. Record exact search terms, item ids, and hit count. A hit triggers
a sufficiency assessment or rejection, never automatic rediscovery. A finding without a recorded
negative search is HYPOTHESIS.

Do not flag these deliberate constraints merely for existing:
- the fast PR tier omits heavy runtime wheels to control hosted-runner disk/time (Decision 135-era
  affected-set design); judge compensating post-merge/build evidence instead;
- main protection uses `strict=false` (Decision 76/83); judge whether required checks and merge
  policy property-match the dependency risk;
- workflow permissions default read-only and cannot approve reviews (Decision 83); preserve least
  privilege rather than proposing removal by default;
- Lambda dependencies may live in managed/custom layers rather than function ZIP manifests
  (Decision 79/125); require explicit ownership, not duplication;
- Terraform and Lambda production changes must use governed deploy paths (Decision 126); never
  recommend an updater bypass;
- post-merge red uses forward-fix rather than auto-revert (Decision 73);
- the open DUCKLAKE_DEPS recommendation, if still open, owns only what its current context and
  acceptance actually cover; assess sufficiency.

## OUTPUT

Write valid YAML at `audits/dependency-management-<sha>.yaml` with this exact shape and pinned enums:

```yaml
audit:
  meta:
    audited_commit: "<audited base short sha>"
    base_branch: main
    model: "<self-reported model, free text>"
    methodology_version: 1
    scope_surfaces: [S1, S2, S3, S4, S5, S6, S7]
    degraded_dedup: false
    degraded_fetch: false
    degraded_external_research: false
    degraded_empirical: false
    degraded_publish: false
    contract_notes: ""
    stale_anchors: [{prompt_anchor: "file:start-end", resolved_anchor: "file:start-end|null", note: ""}]
  question_answers:
    - {q: Q1, verdict: complete, basis: [], prose: ""}
    - {q: Q2, verdict: complete, basis: [], prose: ""}
    - {q: Q3, verdict: strong, basis: [], prose: ""}
    - {q: Q4, verdict: closed-loop, basis: [], prose: ""}
    - {q: Q5, verdict: sufficient, basis: [], prose: ""}
    - q: Q6
      verdict: leading
      basis: []
      prose: ""
      external_checklist: [{property: "", rating: met, evidence: ""}]
    - q: Q7
      answers: [{question: "", answer: "", basis: []}]
  per_surface_assessment:
    - {surface: S1, maturity: frontier, strengths: "", top_gaps: []}
  rubric_ratings:
    - {surface: S1, dimension: VD1, rating: strong, evidence: "file:line|item-id", note: ""}
  automation_policy:
    patch: {verdict: auto-merge, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    minor: {verdict: auto-merge, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    major: {verdict: human-review, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    security: {verdict: queued-auto-merge, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    runtime: {verdict: human-review, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    dev_test: {verdict: auto-merge, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    github_actions: {verdict: human-review, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    terraform_providers: {verdict: human-review, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    pre_commit: {verdict: auto-merge, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    lambda_only: {verdict: human-review, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    native: {verdict: prohibited-auto-merge, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
    extensions: {verdict: human-review, mechanism: "", gates: "", deployment_effect: "", recovery: "", stale_handling: "", rationale: "", confidence: CONFIRMED}
  automation_options_comparison:
    - {option: github-native-auto-merge, strengths: "", weaknesses: "", fit: ""}
  findings:
    - id: DEPEND-01
      surface: S1
      question: Q1
      dimension: VD1
      title: ""
      candidate_ids: [C1]
      evidence: "file:line|item-id"
      evidence_kind: static
      current_behavior: ""
      ideal_behavior: ""
      gap: ""
      compensating_controls_considered: ""
      change_type: unify
      proposed_change: ""
      acceptance: ""
      severity: medium
      severity_rationale: ""
      confidence: CONFIRMED
      roadmap_crossref: {classification: novel, item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, confidence: CONFIRMED, note: ""}
      effort: S
      depends_on: []
      sequencing: {safe_to_queue_now: true, blocked_behind: [], note: ""}
  rejected_candidates:
    - {candidate_id: C2, candidate: "", why_dismissed: "", compensating_control: "", control_property_match: "", decision_or_item_id: ""}
  summary:
    total_findings: 0
    novel_count: 0
    planned_insufficient_count: 0
    planned_unbuilt_count: 0
    top_improvements: []
    highest_leverage_change: null
    overall_maturity: nascent
```

The abbreviated examples have mandatory cardinalities: seven `per_surface_assessment` rows, one
for every S1..S7; exactly 70 `rubric_ratings` rows; exactly 14 Q6 `external_checklist` rows in the
listed order; exactly 12 `automation_policy` keys shown; and six
`automation_options_comparison` rows for the options named in Q5. Every automation-policy object
uses the patch example's exact fields, including `recovery`; all fields other than enum/boolean
fields are scalar strings. The six option values, in order, are
`github-native-auto-merge|direct-workflow-merge|merge-queue|scheduled-maintenance|renovate|manual-review`.
`basis` and `top_gaps` contain
finding-id strings only. Q7 `basis` also contains finding ids only. `strengths`, `prose`, and
`answer` carry inline file:line or URL evidence for claims that have no finding. A stale-anchor
entry uses exactly `{prompt_anchor, resolved_anchor, note}`; use `resolved_anchor: null` when absent.
Contract notes are one scalar with semicolon-delimited `<category>: <fact and consequence>` entries.
An empty `basis` is correct when the answer is supported only by strengths or rejected candidates;
cite those controls directly in `prose` and never manufacture a finding. A finding's scalar
`question` is the question most directly answered by its proposed change; other question answers
may reference the same finding id in `basis`. For a rejected candidate with no decision/roadmap id,
set `decision_or_item_id` to a file:line control anchor. Use ISO `YYYY-MM-DD` access dates per URL.
Every applicable `weak|absent` rubric cell must cite a finding id in `note` or cite a rejected
candidate's property-matched explanation; otherwise the output is invalid. Every `partial` Q6 row
must name its property-matched control in `evidence`. Finding ids are unique and contiguous
`DEPEND-01..N`, ordered severity then surface then title; every finding-id reference must resolve.

The example values illustrate shape only; choose allowed values from these enums:
- Q1/Q2 `complete|partial|incomplete`; Q3 `strong|adequate|weak|absent`; Q4
  `closed-loop|partially-closed|orphan-prone`; Q5 `sufficient|partial|insufficient`; Q6
  `leading|aligned|partial|lagging`.
- checklist `met|partial|missed`; rubric `strong|adequate|weak|absent|n/a`.
- automation `auto-merge|queued-auto-merge|human-review|prohibited-auto-merge`.
- roadmap classification `novel|planned-insufficient|planned-unbuilt`.
- change_type `add|rescope|enforce|unify|persist|clarify|retune_gate`.
- severity `critical|high|medium|low`; confidence `CONFIRMED|HYPOTHESIS`;
  evidence_kind `static|observed`; effort `XS|S|M|L`; maturity
  `frontier|strong|solid|nascent`.

COUNTING INVARIANT: `findings[]` is the SOLE enumerated list; `total_findings = len(findings) =
novel + planned_insufficient + planned_unbuilt`; fully-covered candidates live in
`rejected_candidates`, NOT findings; `rubric_ratings`, `question_answers`, `automation_policy`, and
`automation_options_comparison` are systems-of-record referenced FROM findings, never re-counted;
`top_improvements` and `highest_leverage_change` MUST be finding ids (or null when none).

`control_property_match` is REQUIRED whenever a compensating control causes dismissal: name the
property exercised, cite mechanism or file:line, and explain why the control would FAIL if the
defect were real. CONFIRMED requires file:line tracing or an observed sample; less is HYPOTHESIS.

Write `audits/dependency-management-<sha>.md` as the human-first report, no more than 1500 words:
verdict table Q1..Q6 plus a Q7 answer row; recommended automation-policy table; strengths; surviving findings ordered by
severity and leverage; a 90-day target sequence; rejected intuitions/controls; degraded-mode notes;
and external source links with access date. Do not reproduce the YAML finding schema verbatim.

## SEVERITY + MATURITY

Assign severity after judgment:
- critical: a dependency path can introduce or preserve compromised/unreviewed code in a trusted
  production artifact, or automation can merge/deploy while bypassing its intended safety verdict.
- high: a weakness materially reduces declaration, reproducibility, vulnerability, merge, or
  deployment guarantees and property-matched controls are insufficient.
- medium: lifecycle, synchronization, visibility, ambiguity, or operational weakness with a clear
  fix and bounded impact. low: clarity or low-impact maintenance friction.

A compensating control lowers severity or dismisses only if it exercises the same property and
would fail under the defect counterfactual. A nearby test that cannot catch the break does not count.

Compute maturity LAST, top-down, first match wins. For each surface, count only findings whose
`surface` equals that surface; its frontier tier requires zero critical/high, without the global
checklist gate. For overall maturity, count all findings and apply the checklist gate:
- frontier: zero applicable critical/high findings and, for overall only, every Q6 checklist
  property is `met|partial`, never `missed`;
- strong: zero critical and at most one high;
- solid: at most one critical;
- nascent: otherwise.

The top rating remains reachable when `partial` is supported by an argued property-matched control.

## COMMIT / PR MECHANICS

Derive the base once with the SETUP degraded paths: attempt `git fetch origin main`; set
`BASE_REF=origin/main` if it resolves, otherwise `BASE_REF=HEAD`; then
`BASE_SHA=$(git rev-parse --short "$BASE_REF")`. Use that SHA in filenames,
`meta.audited_commit`, and branch name. Create
`git switch -c audit/dependency-management-$BASE_SHA "$BASE_REF"` (or the specified rerun suffix).
The repository's audit workflow expressly authorizes this clean audit-branch exception to the
normal harness-session branch convention so the PR diff contains exactly two files. If `BASE_REF`
is `HEAD`, pushing/opening a PR may be impossible: still write and commit the two deliverables,
record `publish: unavailable without origin` in contract notes, and end after the failed push - do
not abort the audit or invent a remote.

Parse the YAML before commit:

```bash
bin/venv-python -c "import pathlib,yaml; p=next(pathlib.Path('audits').glob('dependency-management-*.yaml')); yaml.safe_load(p.read_text()); print(p)"
git diff --check
git status --short
git add audits/dependency-management-<sha>.yaml audits/dependency-management-<sha>.md
git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign -m "audit(dependency-management): findings and report"
git push -u origin HEAD
```

Repository-wide validation is advisory outside CI. If `bin/venv-python -m scripts.validate --pre`
fails for an unrelated reason, record it in `meta.contract_notes`; never fix it outside the write
boundary. Derive repository identity without guessing:
`REPO_SLUG=$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')`,
then split the single `owner/repo` value at `/`. Call `mcp__github__create_pull_request` with exactly
that owner and repo, `base="main"`, `head="$(git branch --show-current)"`, title
`audit: dependency management (declarations, updates, and automation)`, ready for review, and body
containing the YAML `summary` block in a fenced YAML block plus a 2-3 sentence lede.

If the initial push fails, do not retry, change permissions, or improvise: set
`meta.degraded_publish=true`, add `publish: push failed - <reason>` to contract notes, amend locally,
and END THE TURN. If the push succeeds but PR creation fails, make the same metadata-only amendment
and perform exactly one follow-up `git push --force-with-lease`; this is the sole allowed follow-up,
not a retry of PR creation. Whether that metadata push succeeds or fails, END THE TURN and report
the PR-creation failure. Otherwise, after PR creation, END THE TURN. Do not
poll, merge, subscribe, approve, or enable auto-merge on your own audit PR.

## GUARDRAILS

- The ONLY tracked files created or modified are the two named audit deliverables.
- Never install, upgrade, merge, close, approve, deploy, apply Terraform, or change repository settings.
- Never expose credentials, account identifiers, private hostnames, alpha, or strategy performance.
- Do not convert a sampled failure into a population claim; label scope and confidence.
- Do not recommend granting broad write/approval permission merely to make automation convenient.
- Fewer than approximately eight surviving findings is a valid result - state it; do not pad.
- Precision over volume. Findings must be actionable, deduplicated, and property-grounded.
