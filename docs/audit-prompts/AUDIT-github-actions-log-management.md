# GITHUB ACTIONS LOG MANAGEMENT AUDIT

## TASK

Audit the repository's GitHub Actions observability and presentation system across the workflow definitions in
`.github/workflows/`, local composite actions in `.github/actions/`, and the supporting code and contracts that produce,
retrieve, condense, retain, validate, or consume Actions diagnostics. Answer Q1-Q6. Judge both the checked-in design and a
bounded sample of recent Actions runs. Write exactly two deliverables,
`audits/github-actions-log-management-<base-short-sha>.yaml` and
`audits/github-actions-log-management-<base-short-sha>.md`. The ONLY files you create or modify in the repository tree are
those two deliverables. You draft; the human disposes. Do not implement fixes, edit audited surfaces, merge, or self-approve.

## CANDIDATE OBSERVATIONS VS VERDICTS

This prompt supplies observed facts and hypotheses to save discovery time. It does not supply findings. ASSUME NO CANDIDATE
IS A REAL DEFECT UNTIL YOU TRACE IT. A run that merely confirms the candidates below has failed. Look for disconfirming
evidence, property-matched controls, and important conditions absent from the candidate set.

Adjudicate each candidate as exactly one of:

- `confirmed-defect`: emit one or more `findings` with `roadmap_crossref.classification: novel` unless dedup changes it.
- `planned-insufficient`: an owning item exists, but its remedy does not cover the demonstrated property; emit a finding with
  classification `planned-insufficient`.
- `planned-unbuilt`: an owning item covers the property but is not realized; emit a finding with classification
  `planned-unbuilt`.
- `planned-fully-covered`: put it in `rejected_candidates`, citing the sufficient owner.
- `not-a-defect`: put it in `rejected_candidates`, naming the evidence or property-matched compensating control.
- `indeterminate`: put it in `rejected_candidates`, state what evidence was unavailable, and do not imply a verdict.

Do not infer deletion from `unsupported`. Q3 inventories lifecycle evidence; any removal recommendation must separately show
that the surface has no live trigger/caller, no deliberate retention owner, no recovery role, and no runtime evidence.

## READ FIRST - DISAMBIGUATION TRAPS

- "GitHub Actions" can mean workflows in `.github/workflows/` or local composite actions in `.github/actions/`. Inventory
  both, but apply the correct caller model: event-triggered workflows need no YAML caller; composite actions use step-level
  `uses:` and do not use `workflow_call`.
- Actions run logs are not repository operational data under `logs/`, AWS CloudWatch logs, or scheduled-agent finding logs.
  Those are context-only unless they are inputs to or outputs from an Actions run.
- GitHub scheduled workflows are not Claude scheduled-agent prompts or Lambda-dispatched scheduled agents.
- Workflow filename, workflow display `name`, job id, displayed job `name`, step `name`, check-run name, commit-status context,
  artifact name, and diagnostic identifier are different naming surfaces. Do not collapse them into one score.
- A surface with few runs may be manual recovery, bootstrap, reconciliation, scheduled, temporarily gated, prototype, or
  designed-unbuilt. Absence of recent runs alone is not orphan evidence.
- Concise output is not necessarily complete output. Treat summaries, annotations, artifacts, failed-step logs, and raw logs
  as layers of progressive disclosure; test whether condensation preserves the decisive property.
- CI-RCA is both a workflow and a downstream agent consumer of other workflow logs. Audit its own presentation separately
  from its log-ingestion behavior.
- `CI`, `Main Canary`, and repository validation tiers have distinct trigger and governance roles. Similar commands do not
  establish duplication or orphaning.

## SCOPE

Built surfaces:

1. Every `*.yml` and `*.yaml` under `.github/workflows/` at the audited commit.
2. Every `action.yml` or `action.yaml` under `.github/actions/` at the audited commit.
3. Direct supporting producers/consumers and validators discovered from those manifests, initially including
   `scripts/ci_rca/`, `scripts/check_workflow_agent_safety.py`, `scripts/verify_ci_workflow.py`,
   `scripts/checks/ci_guards/`, and `scripts/checks/registry.py`. Stop after one invocation/import/caller edge. Trace a deeper
   dependency only when that one-hop component delegates the audited diagnostic property to it.
4. Governing contracts and decisions explicitly named by path, identifier, or `Decision N` text in those surfaces, especially CI-RCA lifecycle, deployment paths,
   validation tiers, branch protection, and failure-loud behavior.
5. Recent GitHub run metadata and diagnostics within EMPIRICAL PASS bounds.

Designed-unbuilt surfaces are in scope only when a current contract, roadmap item, Decision, or recommendation explicitly
describes a future Actions logging, presentation, or lifecycle mechanism. Label them designed-unbuilt and do not rate them as
if operational.

Out of scope: changing workflows; general AWS/CloudWatch logging design; application telemetry; trading behavior; evaluating
the quality of an RCA's domain diagnosis except where presentation/retrieval is the property under review; generic repository
documentation style; billing optimization unrelated to Actions log/artifact retention.

Vocabulary:

- `condensed surface`: run/job metadata, annotation, check output, step summary, PR comment, commit status, or bounded evidence
  artifact intended to avoid full-log ingestion.
- `decisive evidence`: the smallest evidence that identifies the failed property, affected surface, trustworthy outcome, and
  next action without hiding a materially different cause.
- `bounded retrieval`: a command or API query whose returned material is limited by failed job/step, explicit fields, artifact,
  line/byte cap, or fixed sample count.
- `property-matched control`: a control that exercises the same property and would fail if the alleged defect were real.
- `active`: a checked-in surface with a reachable trigger/caller plus repository or sampled runtime evidence supporting its
  current purpose.
- `retained`: no current execution is demonstrated, but an explicit current decision, contract, recovery role, or temporary
  constraint deliberately keeps it.
- `designed-unbuilt`: specified as future state but not represented as a functioning production surface.
- `unsupported`: after the bounded trace, no reachable trigger/caller, current owner, deliberate-retention evidence, or sampled
  runtime evidence was found. This is not synonymous with safe-to-delete.
- `indeterminate`: required evidence was unavailable within the bounds.
- `current owner`: a non-terminal structured item, or a Decision/contract not superseded for the audited property. A closed
  item is historical evidence unless its acceptance remains the realized mechanism.

Obtain every file, line, inventory count, and size by reading the audited tree. Trust no number quoted here; re-derive it.
Record an anchor when it does not resolve or its cited lines no longer support the fact. Record pure line drift with the new
anchor; put changed behavior in `contract_notes` and do not rely on the old claim.

## SETUP

Run from the repository root:

```bash
git fetch origin main
export BASE_FULL_SHA=$(git rev-parse origin/main)
export BASE_SHA=$(git rev-parse --short=12 origin/main)
git branch --show-current
git diff --quiet origin/main --
test -z "$(git status --porcelain=v1 --untracked-files=all)"
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

Derive both variables exactly once. The clean-tree commands prove the current tracked tree and non-ignored untracked set equal
`origin/main`, so ordinary path reads inspect `BASE_FULL_SHA`. Remain on the harness-assigned non-main branch and do not create
another branch. If on `main` or either clean-tree command fails, report and end without writing. Preflight may regenerate only
gitignored files; those are outside the tracked-file write boundary and must never be committed.

If `git fetch origin main` or base resolution fails, do not improvise against another tree and do not write deliverables. Put
the exact failure in the final chat response and end the turn because the audited base and terminal mechanics cannot be made
trustworthy.

If preflight otherwise fails, record it in `contract_notes`, downgrade affected evidence, and proceed only if the audited tree
and write boundary remain trustworthy. If cache generation fails because credentials or egress are unavailable: do NOT abort - set `meta.degraded_dedup=true`, mark
every `roadmap_crossref.confidence=HYPOTHESIS` and `dedup_hit_count=null`, and proceed. If GitHub run/API access is unavailable,
set `meta.degraded_runtime=true`, downgrade every runtime-dependent conclusion to HYPOTHESIS, complete the static pass, and
record the failed command in `meta.contract_notes`. If an individual historical artifact expired or cannot be downloaded,
record it in `meta.runtime_evidence_gaps`, do not replace it with an unbounded sample, and continue. If an anchor no longer
resolves, re-find the concept in the audited tree, append the old anchor and resolution to `meta.stale_anchors`, and cite the
new location. Never abort for these degraded evidence paths.

Permitted read-only runtime commands include `gh workflow list --limit 100`, `gh run list --limit 100`, `gh run view --json`
with explicit fields, and `gh api` limited to two 100-item pages with `--jq` projection. Raw-log endpoints follow EMPIRICAL
PASS. Also permitted are bounded `rg`, `sed`, `find`, `git log`, and repository scripts through `bin/venv-python`. Do not print secrets,
environment dumps, AWS identities, confidential identifiers, or raw API authorization material.

Whenever this prompt says `prefer`, `applicable`, `decisive`, or permits a delegated-property trace, the executor owns that
evidence-based judgment and records its rationale. These are assigned judgments, not requests for human clarification.

## NORTH STAR

These principles are the bar you judge each surface against, not absolutes to pattern-match:

- Progressive disclosure: a collaborator or agent sees outcome and next action first, bounded causal evidence second, raw
  detail last.
- Machine-addressable diagnostics: important results have stable names, typed outcomes, and retrievable structured evidence.
- Failure fidelity: condensation, fallback, masking, and best-effort notification never create a wrong-but-trusted green or
  erase a materially different cause.
- Economical cognition: an agent pays for judgment, not ingestion of hundreds of thousands of irrelevant lines.
- Lifecycle legibility: each workflow/action has a demonstrable trigger or caller, current purpose, governance owner, and
  retirement or retained-state explanation.
- Public professionalism: unfamiliar external collaborators can understand purpose, status, impact, and recovery without
  private context or unexplained local jargon.
- Proportionate governance: high-value conventions are mechanically enforced; low-value uniformity is not mandated merely for
  cosmetic sameness.
- Secure and economical retention: logs and artifacts retain diagnostic value without unnecessary exposure, duplication, or
  cost.

## THE QUESTIONS

Q1. Is GitHub Actions output optimized for machine and agent consumption, including bounded retrieval, structured summaries,
stable diagnostic identifiers, annotations, downloadable evidence, and progressive disclosure? Verdict enum:
`optimized|partial|unoptimized`.

Q2. Do failure paths expose concise, actionable, trustworthy diagnostics at workflow, job, step, summary, annotation, and
artifact layers without requiring an agent to ingest or grep an unbounded raw log? Verdict enum:
`sufficient|partial|insufficient`.

Q3. For every workflow and local composite action, what is its demonstrated lifecycle state and what action, if any, follows?
The Q3 question answer uses verdict `complete|partial|insufficient`; it points to `lifecycle_inventory`, which is the sole
per-surface decision block. Inventory verdict enum: `active|retained|designed-unbuilt|unsupported|indeterminate`. Disposition
enum: `keep|clarify-owner|instrument|consolidate|retire-candidate|no-action`. `retire-candidate` requires all four negative
traces defined under CANDIDATE OBSERVATIONS VS VERDICTS and remains a human decision, never an instruction to delete.

Q4. Are workflow names, filenames, job identifiers, displayed job names, step names, annotations, summaries, failure messages,
and artifact names governed by a coherent, accessible, professional convention? Verdict enum:
`consistent|partial|inconsistent`. Separately answer whether a new mechanically enforced convention is warranted; options
`yes-full|yes-risk-based|documentation-only|no-new-convention`.

Q5. How does the system compare with this external industry-practice checklist? Verdict enum:
`leading|aligned|partial|below-bar`. Add `external_checklist` to Q5, rating every property `met|partial|missed`. `partial` means
substantial capability with a bounded residual gap or property-matched control named in evidence; `missed` means absent or
ineffective.

1. progressive disclosure; 2. bounded machine retrieval; 3. structured failure envelopes; 4. native annotations;
5. job/step summaries; 6. machine-readable evidence artifacts; 7. raw-log noise discipline; 8. anti-false-green controls;
9. stable searchable naming; 10. accessible professional messaging; 11. lifecycle ownership and retirement evidence;
12. retention and cost policy; 13. secret/confidential-data safety; 14. external-action supply-chain hygiene;
15. local reproducibility of important logic; 16. automated conformance; 17. negative-path testing;
18. distinct cancelled/timed-out/skipped/degraded/failed outcomes; 19. workflow purpose and recovery discoverability;
20. non-duplicative use of GitHub checks, statuses, summaries, annotations, artifacts, and PR comments. Each row also lists
`applies_to` from `workflows|composite-actions|log-pipeline`, the sole maturity applicability map.

Q6. What relevant questions did the requester not ask? Seed at least: whether diagnostic surfaces form a stable agent API;
whether truncation can bias diagnosis; whether artifact expiry prevents later RCA/dedup; whether fork PRs see safe but useful
diagnostics; whether cancellation/concurrency obscures root cause; and whether log-volume growth has a measurable budget. Extend
the list when evidence warrants. Q6 uses `{q: Q6, answers: [{question, answer, basis: [finding ids]}]}` and no verdict.

## RUBRIC

Rate every workflow and composite action by path. Rate supporting code/contracts once as `log-pipeline`; do not create
per-module rubric surfaces. Each gets VD1-VD9 rows. `n/a` is correct and costless when structurally inapplicable.
`per_surface_assessment` has exactly three category rows: `workflows`, `composite-actions`, and `log-pipeline`.

- VD1 agent retrieval efficiency - serves Q1/Q2.
- VD2 failure signal quality and recovery action - serves Q2/Q4.
- VD3 structured observability and progressive disclosure - serves Q1/Q2/Q5.
- VD4 trustworthiness and anti-false-green behavior - serves Q2/Q5.
- VD5 lifecycle and ownership evidence - serves Q3/Q5.
- VD6 naming, accessibility, and professional presentation - serves Q4/Q5.
- VD7 governance and enforceability - serves Q4/Q5.
- VD8 retention, confidentiality, and cost discipline - serves Q1/Q5/Q6.
- VD9 external-collaborator usability - serves Q2/Q4/Q5.

## DEEP-DIVES

DD-A - Diagnostic path. For each sampled failure, trace producer command -> step outcome -> job/run metadata -> annotation or
summary -> artifact/status/comment -> agent/human retrieval. Identify the earliest layer containing decisive evidence and the
minimum bounded retrieval that obtains it. Feeds Q1, Q2, Q5.

DD-B - Orphan/lifecycle trace. For every checked-in workflow and composite action, trace event configuration or every local
`uses:` caller; then search current contracts, Decisions, roadmap items, validators, CODEOWNERS if applicable, and bounded git
history/runtime evidence. Do not equate an event trigger with proof of useful execution, or lack of a YAML caller with orphaning.
Feeds Q3.

DD-C - Naming system. Compare filename, display name, job/check identity, step names, artifacts, annotations, diagnostic codes,
and collaborator-facing messages. Distinguish harmless stylistic variance from variance that breaks search, API selection,
branch protection, automation, or comprehension. Feeds Q4, Q5.

DD-D - Failure-fidelity counterfactual. Ask per sample: if the decisive failing command and its raw output disappeared, would
the remaining condensed surfaces identify the failed property and recovery? If feature/failure code were deleted, would a
claimed negative-path guard still fail? Would a truncation, `continue-on-error`, fallback, timeout, or cancellation produce the
same visible result for materially different causes? Feeds Q2, Q5.

## GROUNDING MAP

This map spends your cognition on judgment, not grep. Verify every anchor in the audited tree before relying on it; facts below
are neutral observations, not defects.

- `.github/workflows/ci.yml:1-16` defines display name `CI`, push/pull-request triggers, and job ids.
- `.github/workflows/ci.yml:64-83` runs the fast validation tier and uploads a 14-day affected-selection manifest on `always()`.
- `.github/workflows/ci.yml:131-147` runs the full validation tier and uploads a 14-day pytest JUnit artifact on `always()`.
- `.github/workflows/ci.yml:155-166` describes a provider-mirror degraded path that prints to stdout and the step summary.
- `.github/workflows/ci-rca.yml:1-20` defines `CI RCA`, its watched workflow set, and named exclusions delegated to a contract.
- `.github/workflows/ci-rca.yml:158-178` fetches failed-run logs and begins a best-effort jobs-JSON path.
- `scripts/ci_rca/fetch_logs.py:55-117` builds `gh run view --log-failed` with a whole-log fallback and writes successful stdout.
- `scripts/ci_rca/fetch_logs.py:120-137` emits a native error annotation after bounded fetch attempts fail.
- `scripts/check_workflow_agent_safety.py:1-16` defines a focused guard for masked headless-agent invocations with no output
  assertion; `:64-95` scans workflow run steps.
- `scripts/checks/ci_guards/validate_composite_action_manifests.py:58-85` enumerates local composite manifests and enforces one
  metadata-expression invariant.
- `.github/workflows/cost-reconciliation.yml:69-94` writes a no-snapshot result or cost table to the step summary.
- `.github/workflows/main-canary.yml:54-60` uploads the canary JUnit artifact.
- `.github/workflows/reconcile.yml:575-583` downloads a fresh reconcile plan through a GitHub-native artifact handoff.
- `.github/workflows/terraform-apply-sandbox.yml:158-194` emits distinct convergence read, parse, and red-refusal annotations.
- `.github/workflows/deploy-prod-lambdas.yml:106-138` uses a best-effort role-assumption step followed by an explicit
  false-green guard and warning path.
- `scripts/checks/registry.py:100-110` and `:180-190` register targeted workflow and composite-action checks in validation tiers.
- `docs/contracts/ci-rca-lifecycle.yaml` is the named lifecycle contract for the CI-RCA watched-workflow set.
- `docs/contracts/deploy-paths.yaml` is the intent-to-trigger and recovery index for deployment/reconciliation paths.
- `docs/DECISIONS.md` Decision 55 governs fail-loud/false-green reasoning; Decision 73 and amendments govern the validation
  tiers; Decision 83 governs branch protection and advisory monitors; Decision 135 governs affected-set selection evidence;
  Decision 142 governs cause-anchored CI-RCA fingerprints; Decisions 125/126 govern deployment/reconciliation separation.

Candidate observations to adjudicate:

- Workflow display names exhibit title-case and lowercase-kebab forms.
- Most jobs rely on their job id rather than an explicit displayed job `name`; many external `uses:` steps omit step `name`.
- Step-summary writes, native annotations, artifact publication, and diagnostic identifiers appear on some but not all workflow
  surfaces.
- No repository-wide naming/presentation contract or validator was found during prompt composition; targeted validators exist.
- Scheduled/manual-only workflows require purpose and runtime traces before lifecycle judgment.
- `tf-gated-apply-prototype.yml` is manual-only and carries `prototype` in its name; its current status must be adjudicated.
- CI-RCA has a structured JUnit path for selected pytest failures and a raw failed-log ingestion path with a whole-log fallback.
- `.github/workflows/ci-rca.yml:164` labels a `test -s` backstop as a Decision 143 mitigation, while the Decision 143 header in
  `docs/DECISIONS.md` names privileged-verb Lambda decomposition; adjudicate this reference rather than relying on it.
- Large raw logs can exceed an agent harness's direct-read allowance; determine from sampled behavior which bounded native or
  repository-provided retrieval layers actually avoid that path.

## EMPIRICAL PASS

Inventory every checked-in workflow and composite action statically. Consider the last 90 days and sample no more than 30
runs total and 3 per workflow. Allocate in order: failed deploy/reconcile/apply; failed required CI/security; failed RCA/monitor;
matched successes; then remaining workflows by most recent run. Do not exceed caps to fill coverage. Inspect no more than 10 full raw logs, only after condensed surfaces fail to answer the
trace. Before any full-log fetch, record which bounded metadata, failed-job/step, annotation, summary, and artifact retrievals
were attempted. Never print or copy more than 400 lines from a raw log into working output; use bounded `rg`, `sed`, `head`, or
`tail` windows. Do not place raw logs in deliverables.

For unsampled surfaces, a static trigger/caller plus current ownership may support `active`; use `indeterminate` only when
required evidence is unavailable, not merely because sampling omitted it. For each sample record evidence_kind `observed`,
run conclusion, failure layer, decisive-evidence layer, attempted retrievals
in order (including failures), smallest successful retrieval, whether full-log access was required, and DD-D result. Static-only claims use evidence_kind `static`.
Observed findings outrank static findings at equal severity. Runtime absence is not proof of orphaning.

## METHOD

P1. Re-derive the surface inventory, anchors, names, callers, triggers, and validators from the audited tree.
P2. Trace governing contracts, decisions, current roadmap ownership, and deliberate constraints.
P3. Execute DD-A through DD-D, keeping facts separate from judgments.
P4. Run the bounded empirical pass and record degraded evidence explicitly.
P5. Rate rubric cells and answer each question from traced evidence; do not compute maturity yet.
P6. Apply dedup discipline and adjudicate every supplied candidate in `candidate_adjudications`.
P7. Assign severity only after property judgment and compensating-control analysis.
P8. Synthesize the lifecycle inventory, convention verdict, external checklist, findings, report, and maturity LAST.

## DEDUP DISCIPLINE

Before filing each finding, search `docs/ROADMAP-PLATFORM.yaml` candidate decisions and tier items,
`docs/DECISIONS.md` decision headers/bodies, and `logs/.recommendations-log.jsonl`. Record exact search terms and total hit count
in `roadmap_crossref`. A hit requires a sufficiency assessment: use `planned-insufficient`, `planned-unbuilt`, or
`rejected_candidates`; never present owned work as a fresh discovery. A finding without a recorded negative search is
HYPOTHESIS. Do not read the whole large governance sources when targeted YAML projections or `rg` suffice.
Count one hit per matching structured roadmap item, Decision entry, or recommendation row, not per textual occurrence.
Behavioral evidence controls confidence; a positive ownership hit changes classification but does not prevent CONFIRMED.

Do not flag these deliberate constraints by themselves: Decision 55 fail-loud posture; Decisions 60/73's two validation
tiers and `validate.py` source-of-truth role; Decisions 62/83 advisory scheduled monitors; Decision 83 GitHub-hosted runner and
branch-protection design; Decision 135's affected-selection artifact; Decision 142's JUnit-first fingerprint with log-tail
fallback; Decisions 125/126's governed deploy/reconcile separation; current executor/scheduled-agent freezes in AGENTS.md; a
composite action lacking `workflow_call`; or low execution frequency for manual recovery/bootstrap/probe workflows. You may
find an implementation-fidelity or presentation gap, but do not relitigate the policy without property-level evidence.

## OUTPUT

Write valid YAML at `audits/github-actions-log-management-<base-short-sha>.yaml` with this exact shape and pinned enums:

```yaml
audit:
  meta:
    audited_commit: <base-short-sha>
    base_branch: main
    model: <self-reported model name, free text>
    methodology_version: 1
    scope_surfaces: [workflows, composite-actions, log-producers-consumers, governance, sampled-runs]
    degraded_dedup: false
    degraded_runtime: false
    contract_notes: ""
    stale_anchors: []
    runtime_evidence_gaps: []
  question_answers:
    - {q: Q1, verdict: optimized|partial|unoptimized, basis: [], prose: ""}
    - {q: Q2, verdict: sufficient|partial|insufficient, basis: [], prose: ""}
    - {q: Q3, verdict: complete|partial|insufficient, basis: [], prose: ""}
    - {q: Q4, verdict: consistent|partial|inconsistent, convention_disposition: yes-full|yes-risk-based|documentation-only|no-new-convention, basis: [], prose: ""}
    - q: Q5
      verdict: leading|aligned|partial|below-bar
      basis: []
      prose: ""
      external_checklist:
        - {property: <one of the 20 named Q5 properties>, applies_to: [workflows|composite-actions|log-pipeline], rating: met|partial|missed, evidence: ""}
    - {q: Q6, answers: [{question: "", answer: "", basis: [<finding-id|file:line|run-id|inventory:path|rubric:surface:dimension>]}]}
  per_surface_assessment:
    - {surface: workflows|composite-actions|log-pipeline, maturity: frontier|strong|solid|nascent, strengths: "", top_gaps: []}
  rubric_ratings:
    - {surface: <name>, dimension: VD1|VD2|VD3|VD4|VD5|VD6|VD7|VD8|VD9, rating: strong|adequate|weak|absent|n/a, evidence: "file:line|run-id|artifact", note: ""}
  lifecycle_inventory:
    - {surface: <path>, kind: workflow|composite-action, verdict: active|retained|designed-unbuilt|unsupported|indeterminate, trigger_or_callers: [], ownership_evidence: [], runtime_evidence: [], disposition: keep|clarify-owner|instrument|consolidate|retire-candidate|no-action, rationale: "", confidence: CONFIRMED|HYPOTHESIS}
  empirical_samples:
    - {run_id: <id>, workflow: <name>, conclusion: success|failure|cancelled|timed_out|skipped|neutral|action_required|stale|unknown, failure_layer: <run|job|step|n/a>, decisive_evidence_layer: metadata|annotation|summary|status|comment|artifact|failed-step-log|full-log|none, attempted_retrievals: [], smallest_successful_retrieval: "", full_log_required: true|false, counterfactual_result: "", evidence_kind: observed}
  candidate_adjudications:
    - {candidate_id: C01, candidate: "", adjudication: confirmed-defect|planned-insufficient|planned-unbuilt|planned-fully-covered|not-a-defect|indeterminate, output_refs: [<finding-id|rejected-candidate-index>], note: ""}
  findings:
    - id: GAL-01
      surface: <name|shared>
      question: Q1|Q2|Q3|Q4|Q5|Q6
      dimension: VD1|VD2|VD3|VD4|VD5|VD6|VD7|VD8|VD9
      maturity_categories: [workflows|composite-actions|log-pipeline]
      title: ""
      evidence: "file:line|run-id|artifact"
      evidence_kind: static|observed
      current_behavior: ""
      ideal_behavior: ""
      gap: ""
      compensating_controls_considered: ""
      change_type: add|rescope|enforce|unify|persist|clarify|retune_gate
      proposed_change: ""
      acceptance: ""
      severity: critical|high|medium|low
      severity_rationale: ""
      confidence: CONFIRMED|HYPOTHESIS
      roadmap_crossref: {classification: novel|planned-insufficient|planned-unbuilt, confidence: CONFIRMED|HYPOTHESIS, item_ids: [], dedup_search_terms: [], dedup_hit_count: 0, note: ""}
      effort: XS|S|M|L
      depends_on: []
      sequencing: {safe_to_queue_now: true, blocked_behind: [], note: ""}
  rejected_candidates:
    - {candidate: "", adjudication: planned-fully-covered|not-a-defect|indeterminate, why_dismissed: "", compensating_control: "", control_property_match: "", decision_or_item_id: ""}
  summary:
    total_findings: 0
    novel_count: 0
    planned_insufficient_count: 0
    planned_unbuilt_count: 0
    top_improvements: []
    highest_leverage_change: null
    maturity_workflows: frontier|strong|solid|nascent
    maturity_composite_actions: frontier|strong|solid|nascent
    maturity_log_pipeline: frontier|strong|solid|nascent
```

Assign C01 onward to candidate-observation bullets in order; every candidate has one ledger row and an output reference. The Q5 checklist contains exactly 20 rows, in the Q5 order. `empirical_samples.conclusion` uses GitHub's possible run
conclusion vocabulary pinned above; map absent/null to `unknown` and explain it. Empty `findings` is valid; when empty,
`highest_leverage_change` is null and `top_improvements` is empty.

COUNTING INVARIANT: `findings[]` is the SOLE enumerated list; `total_findings = len(findings) = novel +
planned_insufficient + planned_unbuilt`; fully-covered candidates live in `rejected_candidates`, NOT findings;
`rubric_ratings`, `question_answers`, `lifecycle_inventory`, and `empirical_samples` are systems-of-record referenced FROM
findings, never re-counted; `top_improvements` and `highest_leverage_change` MUST be finding ids, except
`highest_leverage_change` is null when there are zero findings.

`control_property_match` is REQUIRED whenever a compensating control is the reason for dismissal: name the property the
control exercises, cite where it operates, and state why the control would FAIL if the defect were real. CONFIRMED requires
behavior traced to file:line or an observed sampled artifact; anything less is HYPOTHESIS.

Write the companion report at `audits/github-actions-log-management-<base-short-sha>.md`, at most 1500 whitespace-delimited
words including headings and tables. Lead with direct
answers to Q1-Q6, then highest-leverage findings, strengths, lifecycle exceptions, and sequencing. Do not restate the entire
YAML inventory or checklist.

## SEVERITY AND MATURITY

Assign severity after judgment, never from prompt framing:

- critical: the diagnostics can produce a wrong-but-trusted outcome, conceal a security-relevant failure, or allow an
  irreversible governed action to proceed on an unsound visible verdict.
- high: a retrieval/presentation/lifecycle weakness materially reduces the guarantee and property-matched compensating controls
  are insufficient.
- medium: ambiguity, inconsistency, excessive diagnostic cost, unsupported lifecycle, or governance gap with a clear fix.
- low: clarity, wording, cosmetic consistency, or discoverability improvement with limited operational effect.

A control lowers severity or supports dismissal only if it exercises the same property and would fail if the defect were real.
A control that cannot catch the break is not compensating.

Compute maturity LAST for exactly the three category aggregates, top-down, first match wins. A checklist property applies to a
category exactly when its `applies_to` contains it. A finding counts for its listed `maturity_categories`; a shared finding
lists every affected category:

- frontier: zero critical/high findings for that surface and every applicable Q5 external-checklist property is `met` or
  `partial`, never `missed`.
- strong: zero critical and at most one high.
- solid: at most one critical.
- nascent: otherwise.

Frontier remains reachable when a `partial` Q5 rating is justified by an argued property-matched compensating control.

## COMMIT / PR MECHANICS

Validate only the deliverables before commit:

```bash
bin/venv-python - <<'PY'
from pathlib import Path
import os, yaml
sha = os.environ["BASE_SHA"]
p = Path(f"audits/github-actions-log-management-{sha}.yaml")
data = yaml.safe_load(p.read_text(encoding="utf-8"))
assert isinstance(data, dict) and "audit" in data
assert Path(f"audits/github-actions-log-management-{sha}.md").is_file()
PY
git status --short
git add "audits/github-actions-log-management-${BASE_SHA}.yaml" "audits/github-actions-log-management-${BASE_SHA}.md"
git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign -m "audit(github-actions-log-management): GitHub Actions log management audit"
git fetch origin main
git rebase origin/main
git push -u origin HEAD
```

If YAML validation or the exact two-file diff fails, correct only the deliverables; if it cannot pass, end without committing.
Retry a commit once with the pinned identity. Stop on rebase conflict. Retry push or PR creation once only for an explicitly
transient error; otherwise report it and end. Repo-wide `bin/venv-python -m scripts.validate --pre` is advisory outside CI. If it fails for an unrelated pre-existing or
environmental reason, record the exact command and concise result in `meta.contract_notes`; do not fix it. A clean YAML parse
and exact two-file diff are the pre-push gates.

Open a ready-for-review PR with `mcp__github__create_pull_request`, base `main`, head set to the current harness branch, title
`audit: GitHub Actions log management (workflows and composite actions)`. The body contains a 2-3 sentence lede followed by
the YAML `summary` block in a fenced `yaml` block. Then END THE TURN. Do not poll, merge, subscribe, self-approve, or implement
findings. The human disposes of the PR.

## GUARDRAILS

- The ONLY repository-tree writes are the two named audit deliverables. Generated gitignored caches from SETUP are allowed but
  never committed.
- Do not expose confidential account identifiers, ARNs, credentials, secret values, internal attack-surface hostnames, or
  private trading information in commands, evidence, deliverables, commit, or PR.
- Do not change, delete, dispatch, enable, disable, or rerun workflows. Read-only inspection only.
- Do not turn naming uniformity into a finding without showing impact on search, automation, accessibility, or professionalism.
- Do not call a surface orphaned from absence of recent runs alone. Use Q3's evidence and verdict rules.
- Do not prescribe a new external service when GitHub-native metadata, checks, summaries, annotations, or artifacts satisfy the
  same property; compare operational cost and security boundary.
- Fewer than 5 surviving findings is a valid result - state it; do not pad. Zero is valid.
- Precision over volume. Preserve strengths and rejected candidates so the report is not a defect catalog.
- End after PR creation. No polling, merging, subscription, self-approval, or implementation.
