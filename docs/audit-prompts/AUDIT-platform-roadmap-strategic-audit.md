# PLATFORM ROADMAP STRATEGIC AUDIT

You must be GPT-5.6 Sol, a model created by OpenAI. Before doing any setup or
repository work, inspect the session's model indicator supplied by the host UI
or system metadata; do not infer identity from your own prose. If no
authoritative indicator is visible, or it does not say GPT-5.6 Sol, stop
and reply only: `This audit requires GPT-5.6 Sol. Start a new GPT-5.6 Sol
session and paste this prompt verbatim.` Do not approximate the audit with a
different model.

## TASK

Perform a report-only strategic audit of `docs/ROADMAP-PLATFORM.yaml`, the
canonical platform roadmap. Judge its feature completeness, its position
against frontier AI-software-development practice, its improvement and
simplification opportunities, its highest-leverage development sequence, and
the assumptions that determine its judgments. Use `docs/ROADMAP-PRODUCT.yaml`
and shipped platform surfaces only as evidence and dependency context. Answer
Q1-Q7. Produce exactly `audits/platform-roadmap-strategic-audit-<sha>.yaml` and
`audits/platform-roadmap-strategic-audit-<sha>.md`, where `<sha>` is derived in
COMMIT / PR MECHANICS. The ONLY files you create or modify in the repository
tree are those two deliverables. Regenerating gitignored caches during SETUP is
permitted but never commit them. You draft; the human disposes. Do not edit the
roadmaps, code, contracts, decisions, recommendations, or operational data.

## CANDIDATE OBSERVATIONS VS VERDICTS

This prompt supplies neutral facts and candidate hypotheses, not conclusions.
ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT. A run that merely
confirms the candidates below has failed. Seek disconfirming evidence and
identify strengths with the same rigor used for gaps.

Adjudicate each candidate as exactly one of:

- `confirmed_defect`: trace supports a gap not adequately owned by existing
  work; emit a finding with `roadmap_crossref.classification: novel`.
- `planned-insufficient`: an owning roadmap item exists, but its stated remedy
  would not close the property-level gap; emit a finding with that
  classification.
- `planned-unbuilt`: an adequate owning item exists but is not complete; emit a
  finding with that classification.
- `planned-covered`: an owning item fully covers the candidate; place it in
  `rejected_candidates`, not findings.
- `not-a-defect`: evidence or a property-matched compensating control defeats
  the candidate; place it in `rejected_candidates`.

Do not infer severity from this prompt's emphasis. Assign severity only after
tracing behavior and compensating controls.

## READ FIRST - DISAMBIGUATION TRAPS

- `docs/ROADMAP-PLATFORM.yaml` is the target. `docs/ROADMAP-PRODUCT.yaml` is
  context only: read its platform dependencies and capability demands, but do
  not audit trading strategy, alpha, performance, or product prioritization.
- Feature completeness has three separate meanings: `mvp_complete` means one
  autonomous recommendation iteration proceeds from an observed system signal
  through diagnosis, proposed change, independent verification, governed
  delivery, and post-change outcome measurement without a required human action
  between those states; policy-defined exceptional escalation does not make the
  base path incomplete. `product_enabling`
  means planned product phases have the platform capabilities they depend on;
  `mature_platform` means the roadmap covers the durable end-state properties
  in NORTH STAR and the external checklist. Never collapse these meanings.
- Roadmap quality, planned-design quality, shipped implementation, and observed
  operation are distinct evidence layers. Attribute a single-surface finding to
  that `surface`; consolidate a cross-surface root cause as `surface: shared`
  and enumerate all `affected_surfaces`. Do not treat roadmap prose as proof of
  implementation.
- Frontier design is not frontier operation. Naming a technique is not evidence
  that it is enforced, evaluated, or improving outcomes.
- Maximum autonomy is not automatically frontier practice. Calibrated autonomy,
  bounded action, independent verification, and escalation can be stronger.
- Simplification means eliminating or unifying machinery while retaining named
  properties. Deferral means valid work is postponed. Record them separately.
- `strategic: true` on a tier item is sizing metadata. The temporarily suspended
  STRATEGIC plan type is a different concept.
- A feature-complete roadmap need not be final. It may instead provide a sound
  mechanism for evidence-driven evolution.
- Existing prompts named `AUDIT-PROMPT-platform-roadmap-audit.md` and
  `AUDIT-platform-roadmap-mvp-triage.md` target consistency and MVP triage. They
  are dedup evidence, not substitutes for this combined strategic audit.

## SCOPE

Rate these five surfaces independently:

1. `roadmap-control-surface` - designed and partly built: roadmap schema,
   statuses, dependencies, gates, decisions, exit criteria, and agent use.
2. `agent-development-system` - built plus designed-unbuilt: orient, plan,
   implement, verification, context, tools, model routing, and feedback loops.
3. `delivery-and-governance` - built plus designed-unbuilt: CI/CD, deployment,
   security, observability, reversibility, and operational controls.
4. `data-and-learning-loop` - built plus designed-unbuilt: operational data,
   telemetry, causal measurement, evaluation, and recursive improvement.
5. `autonomous-execution` - primarily designed-unbuilt: executor orchestration,
   containment, verification delegation, recovery, and lifecycle closure.

Assign evidence by its primary asserted property: roadmap representation and
agent consumption -> `roadmap-control-surface`; developer-agent cognition and
tool use -> `agent-development-system`; build/deploy/security/operational
control -> `delivery-and-governance`; telemetry/evaluation/learning evidence ->
`data-and-learning-loop`; unattended action orchestration and recovery ->
`autonomous-execution`. When one root cause materially affects multiple primary
properties, use `shared` rather than duplicating it.

Use the following evidence boundaries:

- Primary target: all of `docs/ROADMAP-PLATFORM.yaml`.
- Product dependency context: only platform dependency edges, phase capability
  requirements, and platform-related gates in `docs/ROADMAP-PRODUCT.yaml`.
- Shipped-evidence context: repository files cited by active or completed tier
  items plus their direct imports, tests, generated contracts, and invoking
  workflows when needed to trace claimed behavior, bounded by METHOD and
  EMPIRICAL PASS. Uncited implementations may be inspected only when a targeted
  identifier search indicates they implement an in-scope capability.
- Governance context: targeted decisions, contracts, open recommendations, and
  existing audit reports or prompts found through dedup searches.
- Out of scope: trading alpha, strategy quality or performance, confidential
  cloud values, live infrastructure mutation, roadmap edits, recommendation
  filing, and relitigation of ratified choices solely because another design is
  fashionable.

Vocabulary:

- `coverage-complete`: every capability required by a named frame is shipped or
  adequately owned by an executable closure path.
- `executable closure path`: at minimum, a roadmap owner with non-vacuous exit
  criteria, resolved dependencies, a governed delivery mechanism, and an
  observable completion test; an aspirational title alone is insufficient.
- `operational-complete`: every required capability is shipped and has evidence
  appropriate to its claimed behavior. Q1 reports both coverage and operational
  verdicts for each frame; its overall verdict is operational.
- `frontier`: evidence-backed use of current best practices with outcome
  measurement, not novelty or complexity for its own sake.
- `property-matched control`: a control exercises the same property as the
  alleged defect and would fail if that defect were real.
- `judgment criterion`: the standard used to decide completeness, quality,
  priority, or acceptable risk.
- `reframing assumption`: an assumption whose plausible reversal changes a
  verdict, priority ordering, scope boundary, or architecture choice.
- `critical path`: the shortest dependency-valid sequence that closes the
  named outcome while preserving required controls.

Obtain every count, status, identifier, line, and size by reading the audited
tree. Trust no number quoted here. Re-derive facts and record non-resolving or
meaning-changed anchors in `meta.stale_anchors`; do not silently substitute a
nearby fact.

## SETUP

After the model check, run:

```bash
git fetch origin main
test -z "$(git status --porcelain)" || { echo "Working tree is not clean"; exit 1; }
git rev-parse --short origin/main > /tmp/platform-roadmap-strategic-audit-base-sha
git switch -c audit/platform-roadmap-strategic-audit-$(cat /tmp/platform-roadmap-strategic-audit-base-sha) origin/main
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

Derive the base SHA exactly once into the named `/tmp` file. Read that file in
later independent shell invocations; never re-run `git rev-parse` for the base.
The resulting `origin/main` tree is the audited tree and that SHA is used in
both filenames and `meta.audited_commit`.

The `audit/...` branch is a deliberate audit-deliverable exception to the
general harness `claude/...` branch rule: it starts at the exact audited base so
the PR contains only the two reports. Consequently the `claude/*` CI-green
comment wake is inapplicable. This executor opens the PR for human disposal and
ends without waiting, so it neither subscribes nor merges.

The `origin` remote is a required executor-environment precondition, not a claim
about the prompt-composition checkout. If fetch or branch creation fails, do not audit a different tree. Stop without
writing deliverables and report the exact failure. If cache generation fails
because credentials or egress are unavailable, do not abort: set
`meta.degraded_dedup: true`, set every `roadmap_crossref.dedup_hit_count: null`,
keep all affected cross-reference conclusions `HYPOTHESIS`, record the failure
in `meta.contract_notes`, and proceed using repository-resident sources. If an
anchor no longer resolves, add it to `meta.stale_anchors`, re-locate the concept
by identifier, and treat the supplied statement as untrusted until re-derived.
If preflight fails for any other reason, or creates a tracked file, record the
failure in `meta.contract_notes`, remove only tracked files it created without
touching pre-existing changes, downgrade dependent claims, and proceed from
repository evidence. If generated files cannot be distinguished from
pre-existing changes, stop without writing deliverables. The write boundary
governs tracked repository content; the named `/tmp` file, Git metadata, and
explicitly permitted gitignored caches are not deliverables and never enter the
commit. If a contextual test cannot run because of missing dependencies or external
services, record it in `meta.contract_notes`, downgrade only dependent claims,
and proceed. Never repair setup, credentials, dependencies, or unrelated gates.

Read root `AGENTS.md`, `docs/PROJECT_CONTEXT.md`, both roadmap files under the
scope limits above, and the targeted governing sources cited below. Use targeted
YAML projections for large roadmap and JSONL sources rather than printing them
wholesale after your initial target read.

## NORTH STAR

Judge each surface against these non-absolutist principles. They are bars for
reasoned judgment, not rules that automatically produce findings:

- `P1 outcome closure`: the platform closes a useful autonomous iteration and
  measures whether it improved the system.
- `P2 evidence before trust`: important claims and actions have independent,
  non-vacuous verification tied to real outcomes.
- `P3 bounded autonomy`: authority, blast radius, reversibility, escalation,
  and recovery match uncertainty and consequence.
- `P4 agent-first legibility`: typed, machine-parseable, discoverable sources of
  truth minimize rediscovery and ambiguity across model tiers.
- `P5 causal learning`: telemetry joins intent, context, action, verification,
  cost, and outcome sufficiently to support causal improvement rather than
  activity reporting.
- `P6 simple operations`: every persistent mechanism earns its cognitive and
  operational cost for a sole developer; one authority exists per semantic
  concern.
- `P7 adaptability`: model, tool, compute, and product assumptions can change
  without avoidable migration or governance deadlock.
- `P8 delivery integrity`: planned capability has an explicit path through
  build, deploy, observe, reconcile, and retire-old-path lifecycle states.

## THE QUESTIONS

Answer every question as a first-class `question_answers` entry.

### Q1 - FEATURE COMPLETENESS

Is the platform roadmap feature-complete under each of `mvp_complete`,
`product_enabling`, and `mature_platform`? Add `completeness_frames`, one entry
per frame with separate coverage and operational verdicts from
`complete|substantially_complete|materially_incomplete|not_assessable`, evidence,
missing capabilities, limitations, and basis finding IDs. The Q1 overall verdict
uses the same enum and is the least favorable assessable operational verdict;
explain why. Sampling caps constrain implementation evidence: state coverage
limitations rather than generalizing beyond sampled and traced surfaces.
Ignore `not_assessable` frames when taking the least favorable verdict. If all
three are `not_assessable`, the overall verdict is `not_assessable`.

### Q2 - FRONTIER AI SOFTWARE DEVELOPMENT

Does the roadmap push frontier software development through AI best practice?
Verdict: `frontier|advanced|conventional|behind_practice|not_assessable`.
Populate `external_checklist` for every property below with
  `met|partial|missed|n/a` and evidence, separately for every applicable scope
  surface, producing exactly 80 rows (16 properties x 5 surfaces). `partial`
  means the property is incompletely realized AND a property-matched control
  preserves the intended guarantee; name it. Incomplete without such a control
  is `missed`. Judge applicability; `n/a` is valid and
costless when structurally inapplicable.

`met` requires the property to be explicit in roadmap design, implemented where
the audited frame claims it is shipped, and supported by observed evidence when
the property concerns runtime behavior. If implementation or required runtime
evidence is absent, it cannot be `met`.

External checklist properties:

1. typed narrow self-describing tools;
2. precision context injection and bounded context consumption;
3. model portability and evidence-based capability-tier routing;
4. evaluation-driven development with outcome-linked metrics;
5. independent verification and explicit anti-vacuity tests;
6. durable traces supporting causal failure analysis;
7. explicit autonomy levels and human escalation boundaries;
8. reversible idempotent actions with bounded blast radius;
9. agent identity, provenance, and authorization separation;
10. prompt, skill, tool, policy, and model versioning;
11. behavioral regression detection;
12. adversarial, fault-injection, and degraded-mode testing;
13. measured cost, latency, reliability, and quality trade-offs;
14. continual-improvement loops that test whether changes improve outcomes;
15. multi-agent coordination only where measured benefit exceeds overhead;
16. graceful degradation when models, credentials, or external systems fail.

Use current primary sources for external practice if browsing is available,
bounded to at most 12 sources and favoring official model-provider guidance,
peer-reviewed research, and first-party engineering publications dated within
the last 24 months. Older standards or undated living documentation are allowed
only when a current primary source identifies them as current; record that basis.
Record URLs and access dates under
`meta.external_sources`. If browsing is unavailable, do not abort: record that
in `meta.contract_notes`, restrict Q2 to the pinned checklist, and cap its
verdict at `advanced` because frontier currency was not externally checked.
Use the current UTC date from the session environment for the 24-month window.
When primary sources conflict, report the property-level disagreement and judge
fitness for this platform rather than voting or silently selecting one source.

### Q3 - ROADMAP IMPROVEMENTS

What should be added, removed, rescoped, strengthened, unified, or resequenced?
Verdict: `major_changes|required_changes|targeted_changes|no_material_changes`.
Choose the first match: `major_changes` when three or more surfaces need
high-severity change; otherwise `required_changes` when any critical/high
finding must close for a named completeness frame; otherwise `targeted_changes`
when any finding survives; otherwise `no_material_changes`.
Every proposed improvement must be a finding with a concrete change,
acceptance condition, effort, dependencies, and safe sequencing. A finding is a
property gap or opportunity with material benefit, not necessarily a defect;
`novel` is valid for a newly identified improvement opportunity.
A shared high-severity finding counts once for every entry in its
`affected_surfaces` when applying the three-surface threshold.

### Q4 - SIMPLIFICATION

Where can the roadmap or intended platform be simplified without materially
weakening P1-P8? Verdict:
`substantial_simplification|targeted_simplification|little_simplification|not_assessable`.
For each simplification name what is removed or unified, which properties must
survive, the migration/retirement implication, and the net reduction in
authorities, workflows, services, or maintained concepts. A deferral alone is
not simplification. Include temporary migration cost and report net reduction
after transition rather than gross removals.

Choose Q4's verdict by first match: `substantial_simplification` when accepted
changes remove at least three total authorities/workflows/services/concepts or
one entire persistent service; otherwise `targeted_simplification` when any
accepted simplification has a positive net removal; otherwise
`little_simplification` when only zero-net clarity changes survive; otherwise
`not_assessable` when evidence cannot support the calculation.

### Q5 - WHAT TO DEVELOP FIRST

What are the most important areas to develop first? Verdict:
`clear_sequence|sequence_with_assumptions|blocked|not_assessable`. Return a
maximum of five ordered `priority_sequence` entries. Each contains rank,
finding or roadmap IDs, outcome unlocked, why now, prerequisite, and a
counterfactual: what remains impossible if this step is skipped. Respect the
dependency graph; do not rank by severity alone.

### Q6 - QUESTIONS NOT ASKED

What important matters did the requester not ask about? This entry has no
verdict. Return 1-5 `answers`, each with question, answer, and basis finding IDs;
stop when additional questions would not change a verdict, priority, control,
or decision trigger.
Seed consideration with: what evidence would falsify the roadmap's north star;
what should deliberately never be automated; what recurring operating cost a
sole developer inherits; how roadmap completion is reconciled with observed
outcomes; and what would trigger a platform redesign. Extend beyond these.

### Q7 - ASSUMPTIONS AND REFRAMING

What assumptions drive the roadmap's judgments, and which plausible changes
would reframe them? Verdict:
`robust_to_assumptions|partially_sensitive|highly_sensitive|not_assessable`.
Populate `assumption_register`. Examine at least: sole-developer capacity;
executor freeze duration; model capability and reliability trends; model and
cloud cost curves; public-repository boundary; AWS-centered operating model;
workload scale and latency; telemetry availability and causal identifiability;
human review tolerance; product-roadmap stability; regulatory or security
requirements; and the premise that autonomy is the highest-leverage route to
faster iteration. For each, state current assumption, repository evidence,
plausible reversal, affected judgment criteria, changed verdict or priority,
early indicator, and confidence. Do not claim an assumption merely because a
choice exists; show the inferential dependency.

## RUBRIC

Rate every scope surface against every dimension using
`strong|adequate|weak|absent|n/a`:

- `VD1 outcome-and-capability-coverage` serves Q1 and Q5.
- `VD2 frontier-agent-practice` serves Q2.
- `VD3 evidence-and-feedback-quality` serves Q1, Q2, and Q7.
- `VD4 safety-and-trustworthiness` serves Q2, Q3, and Q6.
- `VD5 architectural-coherence` serves Q1, Q3, and Q4.
- `VD6 simplicity-and-operability` serves Q4 and Q6.
- `VD7 sequencing-and-leverage` serves Q3 and Q5.
- `VD8 assumption-robustness` serves Q7.
- `VD9 adaptability-and-option-value` serves Q2, Q3, and Q7.
- `VD10 roadmap-governance-quality` serves Q1, Q3, and Q5.

`n/a` is correct and costless where a dimension does not structurally apply.
Never invent a rating or finding to fill a cell.

## DEEP-DIVES

### DD-A - COMPLETENESS CHAIN

Trace product platform needs -> platform capability -> tier item -> dependency
and gate -> exit criteria -> shipped evidence or explicit unbuilt state. Apply
the counterfactual: if the named implementation were deleted, would roadmap
validation or operational verification detect loss of the capability? Feed Q1,
Q3, and VD1/VD10.

### DD-B - RECURSIVE IMPROVEMENT CHAIN

Trace intent/context -> action -> telemetry -> durable identity and joins ->
outcome/verification -> diagnosis -> proposed improvement -> guarded delivery
-> post-change evaluation. Identify where correlation is mistaken for causal
evidence. Apply the counterfactual: could every component report success while
the system's decisions become worse? Feed Q2, Q5, Q6, and VD3.

### DD-C - SIMPLICITY AND AUTHORITY MAP

For roadmap, agent workflow, deployment, operational data, verification, and
executor state, name each semantic authority and each projection/cache. Look
for two writable authorities, duplicate gates, parallel lifecycle mechanisms,
or mechanisms retained after migration. Apply the counterfactual: if one
surface disappeared, would another preserve the same property without semantic
loss? Feed Q3, Q4, and VD5/VD6.

### DD-D - ASSUMPTION STRESS TEST

For each material assumption, compare the base case with at least one plausible
reversal. Recompute affected completeness frames, frontier checklist entries,
simplifications, and priority sequence. Feed Q5, Q7, VD8, and VD9.

## GROUNDING MAP

This map spends your cognition on judgment, not grep. Verify every anchor in
the audited tree before relying on it; stale anchors are leads, not evidence.

- `docs/ROADMAP-PLATFORM.yaml:182-188` defines deferred-post-MVP semantics;
  `:197-198` states the platform-MVP boundary.
- `docs/ROADMAP-PLATFORM.yaml:251-267` states NS.1-NS.5: durable storage,
  ownership, economic compute placement, agent-first design, and typed tools.
- `docs/ROADMAP-PLATFORM.yaml:473`, `:569`, `:583`, `:747`, `:842`, `:1121`,
  and `:1157` locate candidate decisions governing agent tooling, typed reads,
  the executor freeze, executor substrate, validation, verification delegation,
  and agent-turn telemetry. Re-derive each state and governing items.
- `docs/ROADMAP-PLATFORM.yaml:5926`, `:5945`, and `:6528` locate causal-chain
  verification, cloud analysis, and telemetry reconciliation work.
- `docs/ROADMAP-PLATFORM.yaml:6656-6869`, `:7104`, and `:7196` locate active
  executor orchestration, persona, lifecycle, verification-delegation, and
  containment work. Re-derive status and dependency edges.
- `AGENTS.md:33` defines the three governed deployment intents.
- `AGENTS.md:38-45` defines SLOC decomposition as a model-portability control.
- `AGENTS.md:54-64` states the temporary STRATEGIC-plan constraint.
- `AGENTS.md:79-96` defines the agent-first repository policy.
- `AGENTS.md:122-160` defines warehouse authority and cache boundaries.
- Existing audit prompts under `docs/audit-prompts/` provide dedup evidence;
  their authoring-time facts and verdict framing are not authoritative.

Candidate hypotheses to adjudicate:

- Capability coverage may differ materially among the three Q1 frames.
- The roadmap may contain frontier architectural intent without enough observed
  outcome evidence to justify a frontier operational rating.
- Causal verification and telemetry may be gating capabilities for recursive
  improvement, or property-matched controls may already provide enough proof.
- The number of governance mechanisms may be necessary defense-in-depth, or it
  may impose avoidable sole-developer operational load.
- Pending decisions and temporarily frozen execution paths may change the
  critical sequence, or the roadmap may already route around them adequately.
- Some planned work may preserve option value; other work may be speculative
  complexity whose triggering assumption is not explicit.
- Product-enabling completeness may be hidden by weak cross-roadmap traceability,
  or existing dependency contracts may cover it.
- Current priorities may assume autonomy is the bottleneck when data quality,
  evaluation validity, product uncertainty, or operational simplicity is more
  limiting.

## EMPIRICAL PASS

Use observed evidence where repository artifacts exist, with these hard caps:

- Sample at most 5 recently completed platform tier items across distinct tiers.
- Sample at most 5 active items, prioritizing the Q5 critical path.
- Sample at most 3 recent implementation plans and their resulting diffs/tests.
- Sample at most 3 verifier or telemetry latest-run artifacts.
- Sample at most 3 governed deployment workflows across different intents.
- Consult at most 12 external sources for Q2.

Candidate universes are closed as follows: completed and active item universes
are their respective status projections from `tier_items`; plan candidates are
tracked `docs/plans/PLAN-*.yaml`; verifier/telemetry candidates are tracked
files whose basename contains `latest` under `logs/debug/` or `audits/`;
deployment candidates are tracked `.github/workflows/*.yml` files containing a
`deploy`, `reconcile`, or `terraform` job identifier. For an item, sample the
first existing `files_in_scope` path in lexicographic order plus the direct
trace permitted by SCOPE. Assign its primary surface using the ownership rule
in SCOPE; spanning artifacts retain one primary surface for sampling and may
support shared findings. If a class cap is smaller than five, diversification
is best-effort and stops at the cap.

Do NOT exceed these bounds. For each class, order candidates by latest git
commit timestamp affecting the artifact, descending; break ties by
repository-relative path ascending. Walk that order and first take one candidate
from each previously-unsampled scope surface, then fill remaining slots in
order. "Recent" means this ordered selection, with no time cutoff. For each sample record selection
method, evidence, and a counterfactual check: would the evidence still pass if
the claimed feature code, policy, or outcome linkage were deleted? Cite an
existing executable test/command and its result when safe; otherwise label the
counterfactual `static` and explain why execution would breach the write or
safety boundary. Tag evidence `static` or `observed`. If a sample class has no
artifact, is stale, or would expose confidential operational data, record the
class and reason in `meta.contract_notes`, do not substitute another class, and
downgrade only dependent claims. At equal severity, observed findings outrank static
ones. Missing runtime evidence is not automatically a defect; judge whether the
roadmap promises it and whether a property-matched alternative exists.

## METHOD

Execute in order:

1. Read instructions, establish scope, re-derive roadmap vocabulary and state.
2. Build capability and authority maps without assigning verdicts.
3. Trace DD-A through DD-D and record evidence both for and against candidates.
4. Run the bounded empirical pass and external check. Also perform at least one
   open-ended discovery search derived from P1-P8 rather than supplied
   candidates, and record its terms in `meta.contract_notes`.
5. Rate rubric cells; use `n/a` where appropriate.
6. Perform dedup searches before creating any finding.
7. Assign defect class, severity, effort, and sequencing after controls are
   considered.
8. Answer Q1-Q7, then compute maturity LAST.
9. Write YAML first, validate its invariants, then write the companion report.

Do not synthesize early. Preserve disagreement between evidence layers until
the final question answers.

## DEDUP DISCIPLINE

Before filing each finding, search:

- `docs/ROADMAP-PLATFORM.yaml` candidate decisions and tier items;
- relevant `docs/DECISIONS.md` and `docs/DECISIONS_ARCHIVE.md` headers/entries;
- `logs/.recommendations-log.jsonl` if cache generation succeeded;
- existing `docs/audit-prompts/` and `audits/` artifacts.

Record exact search terms and hit count. A hit requires a sufficiency judgment:
adequately planned -> `rejected_candidates`; adequate but unbuilt ->
`planned-unbuilt`; insufficient remedy -> `planned-insufficient`. A negative
search means zero exact or semantically relevant ownership hits across all
available named surfaces; mixed or adjacent hits are positive and require the
sufficiency judgment. Never file it as novel merely because it remains open. A finding without a recorded negative
search is `HYPOTHESIS`.

`dedup_hit_count` counts distinct ownership records - one tier item, candidate
decision, decision header, recommendation row, or prior-audit finding - not
textual occurrences or matching files. Multiple matches within one ownership
record count once.

Do not flag these deliberate constraints by themselves: Decision 67's temporary
STRATEGIC-plan freeze; Decision 93's autonomous-loop MVP boundary; Decisions
73/83/101's public-repository boundary; Decision 84's warehouse/cache authority;
Decision 86's prose-architecture freeze; Decision 126's governed deployment
paths; Decision 128's SLOC decomposition policy; the sole-developer context; or
a ratified architecture choice. You may find a defect in an unhandled
consequence, changed premise, missing reversal trigger, or failure to meet the
chosen design's own property.

## OUTPUT

The YAML must parse with `yaml.safe_load` and use this exact structure. Strings
may be block scalars. Empty lists are allowed; omitted required keys are not.

```yaml
audit:
  meta:
    audited_commit: <BASE_SHA>
    base_branch: main
    model: GPT-5.6 Sol
    methodology_version: 1
    scope_surfaces: [roadmap-control-surface, agent-development-system, delivery-and-governance, data-and-learning-loop, autonomous-execution]
    degraded_dedup: false
    contract_notes: ""
    stale_anchors: []
    external_sources: [{title: "", url: "", accessed: YYYY-MM-DD}]
    sample_manifest:
      - {class: completed_item|active_item|implementation_plan|latest_run|deployment_workflow, artifact: "path|item-id", primary_surface: "", selected_by: "latest commit timestamp, path tie-break", evidence_kind: static|observed, counterfactual: "", command_or_static_reason: ""}
  evidence_ledger:
    capability_map: [{capability: "", frame: mvp_complete|product_enabling|mature_platform, owner_ids: [], shipped_evidence: [], closure_path: ""}]
    authority_map: [{concern: "", authority: "", projections: [], evidence: "file:line"}]
    deep_dive_traces: [{deep_dive: DD-A|DD-B|DD-C|DD-D, trace: "", evidence: [], result: ""}]
    discovery_searches: [{principle: P1|P2|P3|P4|P5|P6|P7|P8, terms: [], result: ""}]
  question_answers:
    - q: Q1
      verdict: complete|substantially_complete|materially_incomplete|not_assessable
      basis: [PRA-01]
      prose: ""
      completeness_frames:
        - {frame: mvp_complete|product_enabling|mature_platform, coverage_verdict: complete|substantially_complete|materially_incomplete|not_assessable, operational_verdict: complete|substantially_complete|materially_incomplete|not_assessable, evidence: "", missing_capabilities: [], basis: [], coverage_limitations: ""}
    - q: Q2
      verdict: frontier|advanced|conventional|behind_practice|not_assessable
      basis: []
      prose: ""
      external_checklist:
        - {surface: roadmap-control-surface|agent-development-system|delivery-and-governance|data-and-learning-loop|autonomous-execution, property: "", rating: met|partial|missed|n/a, compensating_control: "none", evidence: "", coverage_limitations: ""}
    - {q: Q3, verdict: major_changes|required_changes|targeted_changes|no_material_changes, basis: [], prose: ""}
    - {q: Q4, verdict: substantial_simplification|targeted_simplification|little_simplification|not_assessable, basis: [], prose: ""}
    - q: Q5
      verdict: clear_sequence|sequence_with_assumptions|blocked|not_assessable
      basis: []
      prose: ""
      priority_sequence:
        - {rank: 1, ids: [], outcome_unlocked: "", why_now: "", prerequisite: [], skipped_counterfactual: ""}
    - q: Q6
      answers:
        - {question: "", answer: "", basis: []}
    - q: Q7
      verdict: robust_to_assumptions|partially_sensitive|highly_sensitive|not_assessable
      basis: []
      prose: ""
      assumption_register:
        - {assumption: "", repository_evidence: "file:line|item-id", plausible_reversal: "", affected_judgment_criteria: [], changed_verdict_or_priority: "", early_indicator: "", confidence: CONFIRMED|HYPOTHESIS}
  per_surface_assessment:
    - {surface: roadmap-control-surface|agent-development-system|delivery-and-governance|data-and-learning-loop|autonomous-execution, maturity: frontier|strong|solid|nascent, strengths: "", top_gaps: []}
  rubric_ratings:
    - {surface: "", dimension: VD1|VD2|VD3|VD4|VD5|VD6|VD7|VD8|VD9|VD10, rating: strong|adequate|weak|absent|n/a, evidence: "file:line|item-id", note: ""}
  findings:
    - id: PRA-01
      surface: roadmap-control-surface|agent-development-system|delivery-and-governance|data-and-learning-loop|autonomous-execution|shared
      questions: [Q1]
      dimensions: [VD1]
      affected_surfaces: [roadmap-control-surface]
      title: ""
      evidence: "file:line|item-id"
      evidence_kind: static|observed
      current_behavior: ""
      ideal_behavior: ""
      gap: ""
      compensating_controls_considered: ""
      change_type: add|remove|rescope|enforce|unify|persist|clarify|resequence|retune_gate
      proposed_change: ""
      acceptance: ""
      severity: critical|high|medium|low
      severity_rationale: ""
      confidence: CONFIRMED|HYPOTHESIS
      roadmap_crossref:
        classification: novel|planned-insufficient|planned-unbuilt
        item_ids: []
        dedup_search_terms: []
        dedup_hit_count: 0
        note: ""
      effort: XS|S|M|L
      depends_on: []
      sequencing: {safe_to_queue_now: true, blocked_behind: [], note: ""}
      simplification_effect: {authorities_removed: 0, workflows_removed: 0, services_removed: 0, concepts_removed: 0, temporary_migration_cost: "none", properties_preserved: []}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "", control_property_match: "", decision_or_item_id: ""}
  summary:
    total_findings: 0
    novel_count: 0
    planned_insufficient_count: 0
    planned_unbuilt_count: 0
    top_improvements: []
    highest_leverage_change: ""
    maturity_roadmap_control_surface: frontier|strong|solid|nascent
    maturity_agent_development_system: frontier|strong|solid|nascent
    maturity_delivery_and_governance: frontier|strong|solid|nascent
    maturity_data_and_learning_loop: frontier|strong|solid|nascent
    maturity_autonomous_execution: frontier|strong|solid|nascent
```

If there are zero findings, `highest_leverage_change` is `none`; otherwise it
must be a finding ID. `simplification_effect` is required for every finding;
use zeros and an empty list when the finding is not a simplification.

Meta invariants: `methodology_version` is exactly `1`; `scope_surfaces` is
exactly the five-item list shown and drives completeness/rubric iteration;
`degraded_dedup` controls dedup confidence and null hit counts; every
`stale_anchors` entry is cited in the affected evidence note; every
`contract_notes` limitation names the affected question, checklist row, rubric
cell, or finding; and every `external_sources` entry is cited by at least one Q2
checklist evidence field. Use `external_sources: []` when browsing is degraded.
Every empirical sample is recorded once in `sample_manifest`; capability,
authority, deep-dive, and candidate-blind discovery work is recorded in
`evidence_ledger`, which is evidence scaffolding and never a second finding
list.

COUNTING INVARIANT: `findings[]` is the SOLE enumerated list;
`total_findings = len(findings) = novel + planned_insufficient +
planned_unbuilt`; fully-covered candidates live in `rejected_candidates`, NOT
findings; `rubric_ratings`, `question_answers`, completeness frames, checklist,
priority sequence, and assumption register are systems-of-record referenced
FROM findings, never re-counted; `top_improvements` and
`highest_leverage_change` MUST be finding ids, except the pinned zero-finding
`none` value.

`questions`, `dimensions`, and `affected_surfaces` are non-empty lists using
only their displayed enums. Use them to consolidate one root cause that serves
multiple questions or dimensions. A `shared` finding must name every affected
scope surface; its severity counts against each named surface's maturity.

`control_property_match` is REQUIRED whenever a compensating control causes a
dismissal: name the exercised property, cite the mechanism or file:line, and
state why the control would fail if the defect were real. `CONFIRMED` requires
implementation presence traced to file:line or behavior shown by an observed
sample. A static trace confirms only what the implementation encodes, never its
runtime effect. Claims beyond that evidence are `HYPOTHESIS`.

The companion Markdown report is the human executive layer, at most 1500
words. Use sections: Verdicts; Feature Completeness; Frontier Practice;
Improvements and Simplifications; Develop First; Assumptions That Reframe the
Roadmap; Questions Not Asked. Reference finding and roadmap IDs; do not create
new findings in prose.

## SEVERITY AND MATURITY

Assign severity after judgment:

- `critical`: the roadmap can direct a wrong-but-trusted irreversible or
  materially unsafe act, or declare the autonomous loop complete on unsound
  evidence.
- `high`: a gap materially reduces outcome closure, causal trust, containment,
  or delivery integrity and property-matched controls are insufficient.
- `medium`: redundancy, ambiguity, sequencing error, or inconsistency has a
  clear material fix.
- `low`: clarity or maintainability weakness with limited behavioral effect.

A compensating control lowers or dismisses a finding only if it exercises the
same property and would fail when the alleged defect is present. A control that
cannot catch the break does not count.

Compute maturity LAST per surface, top-down, first match wins:

- `frontier`: zero critical/high findings affecting the surface and every Q2
  checklist row whose `surface` equals that surface is `met` or `partial`, never
  `missed`.
- `strong`: zero critical and at most one high.
- `solid`: at most one critical.
- `nascent`: otherwise.

Frontier remains reachable when a `partial` rating has an argued
property-matched compensating control. Do not foreclose the top rating because
the implementation differs from fashionable practice.

## COMMIT / PR MECHANICS

Validate before committing:

```bash
bin/venv-python - <<'PY'
from pathlib import Path
import yaml
sha = Path("/tmp/platform-roadmap-strategic-audit-base-sha").read_text().strip()
for suffix in ("yaml", "md"):
    path = Path(f"audits/platform-roadmap-strategic-audit-{sha}.{suffix}")
    assert path.is_file(), path
data = yaml.safe_load(Path(f"audits/platform-roadmap-strategic-audit-{sha}.yaml").read_text())
a = data["audit"]
assert a["meta"]["audited_commit"] == sha
surfaces = {"roadmap-control-surface", "agent-development-system", "delivery-and-governance", "data-and-learning-loop", "autonomous-execution"}
assert a["meta"]["methodology_version"] == 1
assert set(a["meta"]["scope_surfaces"]) == surfaces and len(a["meta"]["scope_surfaces"]) == 5
qas = a["question_answers"]
assert [q["q"] for q in qas] == [f"Q{i}" for i in range(1, 8)]
check = next(q for q in qas if q["q"] == "Q2")["external_checklist"]
assert len(check) == 80
assert len({(r["surface"], r["property"]) for r in check}) == 80
assert {r["surface"] for r in check} == surfaces
assert {r["rating"] for r in check} <= {"met", "partial", "missed", "n/a"}
rubric = a["rubric_ratings"]
assert len(rubric) == 50
assert len({(r["surface"], r["dimension"]) for r in rubric}) == 50
assert {r["rating"] for r in rubric} <= {"strong", "adequate", "weak", "absent", "n/a"}
findings = a["findings"]
ids = [f["id"] for f in findings]
assert len(ids) == len(set(ids)) and all(i.startswith("PRA-") for i in ids)
classes = [f["roadmap_crossref"]["classification"] for f in findings]
s = a["summary"]
assert s["total_findings"] == len(findings)
assert s["novel_count"] == classes.count("novel")
assert s["planned_insufficient_count"] == classes.count("planned-insufficient")
assert s["planned_unbuilt_count"] == classes.count("planned-unbuilt")
assert len(findings) == s["novel_count"] + s["planned_insufficient_count"] + s["planned_unbuilt_count"]
refs = set(ids)
assert set(s["top_improvements"]) <= refs
assert s["highest_leverage_change"] in refs or (not findings and s["highest_leverage_change"] == "none")
assert all(set(f["affected_surfaces"]) <= surfaces and f["affected_surfaces"] for f in findings)
assert len(next(q for q in qas if q["q"] == "Q5")["priority_sequence"]) <= 5
assert 1 <= len(next(q for q in qas if q["q"] == "Q6")["answers"]) <= 5
assert len(Path(f"audits/platform-roadmap-strategic-audit-{sha}.md").read_text().split()) <= 1500
PY
git status --short
```

The status output must contain only the two deliverables. Repo-wide validation
is advisory outside CI. You may run
`bin/venv-python -m scripts.validate --pre`; if it fails for an unrelated or
environmental reason, record the exact result in `meta.contract_notes` and do
not fix it. A clean YAML parse and two-file boundary are the pre-push gates.

Then:

```bash
BASE_SHA=$(cat /tmp/platform-roadmap-strategic-audit-base-sha)
git add audits/platform-roadmap-strategic-audit-$BASE_SHA.yaml audits/platform-roadmap-strategic-audit-$BASE_SHA.md
git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign -m "audit(platform-roadmap-strategic-audit): strategic assessment"
git fetch origin main
git rebase origin/main
git push -u origin HEAD
```

If the rebase conflicts, stop, report the conflict, and do not push or modify
the two deliverables to resolve it. The human decides whether to rerun the audit
against the newer base; never change `meta.audited_commit` after analysis.

Open a ready-for-review PR using `mcp__github__create_pull_request` with
`base=main`, the current audit branch as `head`, and title
`audit: platform roadmap strategic assessment (platform surfaces)`. The body is
a 2-3 sentence lede followed by the YAML `summary` block in a fenced YAML
block. Then END THE TURN. Do not poll, merge, subscribe, self-approve, edit the
roadmap, or file recommendations.

## GUARDRAILS

- The closed write boundary is exactly the two audit deliverables. Local
  gitignored cache regeneration is permitted and never committed.
- No AWS, warehouse, roadmap, decision, recommendation, infrastructure, or
  deployment writes.
- Never expose account identifiers, credentials, internal hostnames, trading
  alpha, or performance information.
- Do not turn preference into defect. Judge properties and consequences.
- Do not count planned-unbuilt work as absent from the roadmap; distinguish
  coverage from implementation.
- Do not pad. Fewer than approximately 8 surviving findings is a valid result;
  state it plainly. Zero is valid if supported.
- Precision over volume. Consolidate findings with one root cause and use
  dependencies for distinct causes.
- Do not ask clarifying questions. Named degraded paths cover anticipated
  failures; otherwise make the narrowest evidence-preserving judgment and mark
  it `HYPOTHESIS`.
- End after opening the PR. The human decides whether and how findings change
  the roadmap.
