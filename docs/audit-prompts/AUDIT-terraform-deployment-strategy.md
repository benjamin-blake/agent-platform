TASK

Audit this repository's agent-first Terraform deployment strategy. Preferred executor model order: (1) GPT-5.6 Sol with maximum/deep reasoning if the UI/harness exposes it; (2) GPT-5.5 Pro if exposed; (3) GPT-5.5. Record the actual model you are running as free text in `audit.meta.model`; if the harness hides the model name, write `model_hidden_by_harness`. Do not spend audit time proving model availability. Your target is not "add more gates". Your target is whether the current provisioning, Terraform apply, Lambda code deploy, drift/reconcile, convergence, and admin break-glass model gives agents as much safe operational control as possible in today's single-account sandbox environment, while deferring heavier human approval gates to future SIT/PROD or real-capital environments. Answer Q1-Q7, rate VD1-VD7 per surface, and propose simplification moves that reduce human interpretation, narrative sprawl, and premature gating without weakening deterministic safety. You will write exactly two deliverables: `audits/terraform-deployment-strategy-<origin-main-short-sha>.yaml` and `audits/terraform-deployment-strategy-<origin-main-short-sha>.md`. You draft the audit and open a review PR; the human disposes by reviewing, merging, closing, or translating findings into plans. The ONLY tracked files you create or modify in the repository tree are those two audit deliverables. The allowed untracked/gitignored setup side effects are `logs/.preflight-report.json`, `logs/.recommendations-log.jsonl`, `logs/.decisions-index.jsonl`, files under `logs/debug/`, and normal tool caches under `.pytest_cache/` or `__pycache__/`; never commit them.

CANDIDATE OBSERVATIONS vs VERDICTS

This prompt gives you facts and candidate hypotheses, not conclusions. ASSUME NO CANDIDATE IS A REAL DEFECT UNTIL YOU TRACE IT. A run that merely confirms the candidates below has failed. For each candidate C1-C8, adjudicate it into exactly one outcome. Multiple candidates may point to the same finding; when they do, cite the shared finding id in each relevant rejected/covered note rather than duplicating findings:

- CONFIRMED-defect: put it in `findings[]` with `roadmap_crossref.classification: novel`.
- Planned but insufficient: put it in `findings[]` with `roadmap_crossref.classification: planned-insufficient` and cite the owning item.
- Planned but unbuilt: put it in `findings[]` with `roadmap_crossref.classification: planned-unbuilt` and cite the owning item.
- Planned and fully covered: put it in `rejected_candidates[]`, not findings.
- Not a defect: put it in `rejected_candidates[]`, name the compensating control, and explain the property match.

Do not inherit severity from this prompt. Assign severity only after tracing behavior and assessing property-matched compensating controls.

READ FIRST / DISAMBIGUATION TRAPS

- Terraform root ambiguity: `terraform/personal/` is the live personal-account root. Legacy files directly under `terraform/` are retained as architectural-evolution artifacts unless a cited workflow or contract says otherwise.
- Provision vs code deploy: Terraform provisioning and Lambda code deploy are intentionally separate paths. Assess whether the separation is agent-first and simple, not whether everything should become Terraform.
- Product phase vs platform environment: product phases such as research/paper/live_full are not platform deployment environments. Platform environment terms are reserved by `docs/contracts/environment-taxonomy.md`.
- Sandbox vs future SIT/PROD: only sandbox is live today. Do not mark absence of full SIT/PROD gates as a current defect unless a current surface relies on them.
- Admin break-glass vs routine agent action: operator-only break-glass is context for exceptional trust/admin paths, not the desired routine shape.
- Audit execution vs implementation: you are auditing and writing deliverables only. Do not patch workflows, Terraform, scripts, contracts, docs, recommendations, or decisions.

SCOPE

In-scope surfaces. File paths are the canonical surface names for `scope_surfaces`, `per_surface_assessment.surface`, `rubric_ratings.surface`, `findings.surface`, and `human_gate_inventory.surface`. Files marked generated/optional may be absent until setup creates them; use the named degraded path if absent:

- `docs/contracts/deploy-paths.yaml`: deployment intent navigation for provision, deploy_code, reconcile, and admin_out_of_band.
- `docs/contracts/environment-taxonomy.md`: platform/product axis vocabulary, sandbox/SIT/PROD apply model, guard classification, and Lambda code/infra decoupling principle.
- `docs/contracts/build-lambda.yaml`: Lambda build/deploy registry and governed channel pointers.
- `terraform/CLAUDE.md`: Terraform directory operational guidance, routine CI apply explanation, and operator-only/break-glass context.
- `.github/workflows/terraform-apply-sandbox.yml`: speculative plan, saved-plan apply, deterministic guard, subagent review, gated apply, and convergence writes.
- `.github/workflows/reconcile.yml`: recovery action for a red apply pipeline or drifted convergence record; it may expose optional metadata inputs, but it must not require an operator-supplied target SHA.
- `.github/workflows/deploy-ducklake-lambdas.yml`: governed code-deploy channel for DuckLake Lambdas.
- `.github/workflows/deploy-prod-lambdas.yml`: governed code-deploy channel for prod-class Lambdas.
- `scripts/terraform_apply_guard.py`: deterministic guard over Terraform plan JSON.
- `terraform/bootstrap/authority_budget.json`: machine-readable in-budget IAM update table.
- `scripts/ci/reconcile_target.py`, `scripts/preflight/aws_infra.py`, and `scripts/verify_ci_workflow.py`: supporting checks and recovery/verification logic.
- `docs/DECISIONS.md` and `docs/DECISIONS_ARCHIVE.md`: rationale and historical constraints. Required decision IDs to inspect: 35, 76, 77, 83, 92, 94, 98, 119, 120, 125, 126, 127. You may inspect additional decisions only when an in-scope surface, sampled roadmap item, or sampled recommendation cites them directly.
- `docs/ROADMAP-PLATFORM.yaml`: roadmap/dedup source for existing planned simplifications.
- `logs/.recommendations-log.jsonl` (generated/optional): local read cache for dedup only. It may be absent before setup; never write it directly. If absent after cache generation fails, set `audit.meta.degraded_dedup=true` and skip recommendation sampling.

Out of scope:

- Product trading strategy, alpha quality, formula discovery, and capital allocation logic.
- Implementing any simplification you propose.
- Creating or editing recommendations, decisions, roadmap items, workflows, Terraform files, scripts, or contracts.
- Live AWS mutation, Terraform apply, Lambda deploy, GitHub variable changes, or admin recovery.

Vocabulary:

- Agent-first: routine operational control belongs to agents through deterministic tools, machine-readable contracts, CI workflows, and typed/structured recovery paths. Human action is reserved for risks that cannot yet be property-matched by deterministic controls or for future higher-risk environments.
- Deterministic control: a check, guard, workflow, or schema that produces a bounded machine-verifiable outcome without relying on human vibes.
- Human gate: a required human approval, explicit human command, or operator-only procedure.
- Premature gate: a human gate that appears to protect a future SIT/PROD/real-capital risk but slows today's sandbox agent loop without property-matching a current risk.
- Property-matched compensating control: a control that exercises the same safety property as the alleged missing/weak control and would fail if the defect were real. Borderline equivalence rule: if you cannot cite where the control observes the same input/state and blocks or alarms on the same bad outcome, treat the control as insufficient for dismissal, but you may lower confidence to HYPOTHESIS.
- Simplification move: a concrete change that removes surfaces, converts prose into structured contract/check logic, merges duplicate paths, or expands deterministic agent control.

Trust nothing quoted here. Obtain every file, line, and size by reading the file yourself. Re-derive all anchors from the repo and record any non-resolving anchor in `audit.meta.stale_anchors`.

SETUP

Run these commands from the repository root. If any setup step fails, follow the named degraded path and continue.

1. Establish the audited base:

```bash
git fetch origin main || true
git rev-parse --short origin/main || git rev-parse --short HEAD
```

Use this short SHA in both output filenames and in `audit.meta.audited_commit`. If there is no `origin` remote/ref in the execution environment, do not abort: use `git rev-parse --short HEAD`, set `audit.meta.contract_notes` to include `origin/main unavailable; audited HEAD`, and use `HEAD` as the audited base for filenames and branch naming.

2. Generate dedup/context caches:

```bash
bin/venv-python -m scripts.session.preflight --roadmap-detail full
```

IF cache-gen fails (creds/egress down): do NOT abort -- set `audit.meta.degraded_dedup=true`, mark every `roadmap_crossref` confidence as HYPOTHESIS and `dedup_hit_count=null`, proceed.

3. Optional structural checks, local-only and allowed to update gitignored caches/logs only:

```bash
bin/venv-python -m scripts.validate --pre
```

If this fails on files outside your two deliverables or on pre-existing repository state, do not fix it. Record a short note in `audit.meta.contract_notes` and proceed. If it fails because your YAML/report is malformed, fix only the two deliverables. Repo-wide validation is advisory for this audit; clean YAML parsing of your deliverable is the pre-push gate.

4. You may run targeted read-only commands such as `rg`, `sed`, `nl -ba`, `git show`, and inline or temporary Python/YAML readers through `bin/venv-python`; temporary parser files, if any, must live outside the repository or be deleted before commit. Do not run Terraform apply, Lambda deploys, GitHub workflow dispatches, AWS mutation, or any command that changes tracked files outside `audits/`.

NORTH STAR

Judge against these non-absolutist principles. They are bars for analysis, not pre-baked verdicts.

- NS1 Agent ownership by default: if an operation is routine in today's sandbox environment, the default path should be agent-executable or agent-routable.
- NS2 Human gates only where property-matched: human approval should protect trust expansion, irreversible/destructive action, real-capital exposure, or a risk not yet capturable by deterministic controls.
- NS3 Machine-readable over narrative: agent-facing deployment rules should live in structured contracts/checks where possible; prose should point, explain rationale, or carry exceptional procedure.
- NS4 Determinism before bureaucracy: prefer saved plans, guards, schemas, typed statuses, and convergence records over manual interpretation.
- NS5 Present/future separation: do not import future SIT/PROD ceremony into the current sandbox-only loop unless current behavior actually depends on it.
- NS6 Recovery is part of deployment: a red or drifted state should have an agent-routable recovery path with explicit degraded states, not an ambiguous human handoff.
- NS7 Public-repo safety remains load-bearing: simplification cannot expose AWS account IDs, ARNs, ExternalIds, internal hostnames, credentials, or trading alpha.

THE QUESTIONS

Q1 - Agent autonomy. Does the current Terraform/deployment strategy maximize agent operational control for the current sandbox-only platform reality? Verdict enum: `agent_first | mostly_agent_first | human_centered | fragmented`.

Q2 - Gate timing. Which current gates or human approval points are justified today, and which are premature controls that should be deferred until future SIT/PROD/real-capital environments? Verdict enum: `well_timed | mixed | over_gated | under_gated`.

Q3 - Deterministic controls vs human judgment. Where can human judgment be replaced by deterministic guardrails, machine-readable contracts, or agent-owned recovery workflows without weakening safety? Verdict enum: `high_simplification_potential | moderate_simplification_potential | low_simplification_potential`.

Q4 - Agent readability. Are the deployment rules structured for agents to consume efficiently, or are they spread across narrative docs, comments, decisions, and workflows in a way that forces expensive rediscovery? Verdict enum: `agent_optimized | acceptable | narrative_heavy | drift_prone`.

Q5 - External-practice fit. Assess the design against this external checklist, property by property: plan/apply identity; least privilege; separation of infrastructure and code deploys; auditable approvals for trust-expanding changes; deterministic policy gates; no silent green/no-op deploys; drift detection; recovery runbooks; environment separation proportional to risk; infrastructure supply-chain pinning. Verdict enum: `strong | adequate | weak | unsuitable`.

Q6 - Simplification roadmap. What concrete moves would simplify the deployment strategy while increasing, not decreasing, agent control? Verdict enum: `simplify_now | simplify_incrementally | defer`.

Q7 - Questions not asked. What additional autonomy, control-theory, requester-decision, or agent-operability questions should be answered? Include at least one answer separating what the requester likely wants decided from what the evidence can support. Use the special output shape under `question_answers`: `{q: Q7, prose: "", answers: [{question, answer, basis: [<finding ids>]}]}`.

RUBRIC

Rate each in-scope surface against these dimensions. Enum: `strong | adequate | weak | absent | n/a`. Use `n/a` where a dimension does not structurally apply.

- VD1 - Agent control surface: how much routine provision/deploy/reconcile behavior is agent-executable or agent-routable?
- VD2 - Gate appropriateness: are human gates reserved for genuinely irreversible, trust-expanding, or future-environment risks?
- VD3 - Determinism: are risk decisions encoded as guards, checks, contracts, typed statuses, or workflow outcomes rather than prose/human vibes?
- VD4 - Machine readability: are deployment rules concise, structured, and discoverable by agents?
- VD5 - Recovery autonomy: can red states be diagnosed, deduped, routed, and retried by agents?
- VD6 - Present-vs-future separation: does the surface avoid importing future SIT/PROD ceremony into today's sandbox loop?
- VD7 - Simplification leverage: would a change here remove surfaces, merge duplicate logic, convert prose to executable contracts, or expand deterministic agent control?

DEEP-DIVES

DD-A - Intent routing trace. Trace a representative infra-only Terraform change, Lambda code-only change, red convergence record, drift signal, in-budget IAM update, out-of-budget/trust/destroy change, and admin/bootstrap change. For each, identify the intended agent/human actor, trigger, gate, recovery, and where an agent would learn the path. Feeds Q1, Q2, Q4, Q6.

DD-B - Human-gate inventory. Build a table of every explicit human approval/operator-only point you find. For each, classify: current-risk property protected; whether a deterministic control already property-matches that risk; whether the gate is current-required, future-required, or candidate for conversion to agent-owned workflow. Feeds Q2, Q3, Q6.

DD-C - Prose-to-contract opportunity scan. Identify narrative surfaces that restate rules already owned by contracts/scripts/workflows. For each, decide whether it should remain as rationale, become a pointer, move into a structured contract, or be removed after extraction. Feeds Q4, Q6.

DD-D - Recovery autonomy trace. Trace how an agent discovers, dedups, and routes a red apply, stale saved plan, blocked guard verdict, bootstrap-window no-op deploy, deploy smoke failure, and drift record. Feeds Q1, Q5, Q6.

GROUNDING MAP

This map spends your cognition on judgment, not grep. Verify every anchor before relying on it. If a line moved, cite the new line and record the old/non-resolving anchor in `audit.meta.stale_anchors`.

Observed facts to verify:

- `docs/contracts/deploy-paths.yaml` says its purpose is to name triggers, actor roles, and recovery pointers for provision, deploy_code, reconcile, and admin_out_of_band; it also says apply-model and guard-classification rules live in `docs/contracts/environment-taxonomy.md`.
- `docs/contracts/deploy-paths.yaml` assigns `provision.actor_role: agent`, `deploy_code.actor_role: agent`, and `reconcile.actor_role: agent`; `admin_out_of_band.actor_role: operator`.
- `docs/contracts/deploy-paths.yaml` says infra changes are triggered by opening a PR touching `terraform/**`; CI plans and applies.
- `docs/contracts/deploy-paths.yaml` says reconcile is an input-free action that reads the red commit from the convergence record and re-applies it.
- `docs/contracts/environment-taxonomy.md` defines bootstrap, sandbox, SIT, and PROD on the platform environment axis, with only sandbox using auto-apply and SIT/PROD marked future dedicated accounts.
- `docs/contracts/environment-taxonomy.md` says the platform stays single-account until the product axis approaches live_full/full capital.
- `docs/contracts/environment-taxonomy.md` defines guard classifications: in-budget, out-of-budget, trust-diff, destroy/replace, and neon update/delete.
- `docs/contracts/environment-taxonomy.md` states Lambda code/infra decoupling principle for personal-account Lambdas.
- `docs/contracts/build-lambda.yaml` defines governed deploy channels for DuckLake functions, prod functions, and ops_compaction, with break_glass_only commands retained as non-default fallbacks.
- `scripts/terraform_apply_guard.py` evaluates Terraform plan JSON and returns blocking findings for destroy/replace, non-create neon changes, trust diffs, and out-of-budget IAM changes.
- `terraform/bootstrap/authority_budget.json` lists in-budget IAM resource types, actions, and managed role names.
- `.github/workflows/terraform-apply-sandbox.yml` contains both PR speculative-plan behavior and push-to-main apply behavior. Verify exact current behavior; do not rely on this summary.
- `.github/workflows/reconcile.yml` exists and is the landed reconcile workflow. Verify trigger and inputs.
- `.github/workflows/deploy-ducklake-lambdas.yml` and `.github/workflows/deploy-prod-lambdas.yml` contain scoped deploy role bootstrap-window handling, deploy-record freshness checks, and smoke gates. Verify exact current behavior.
- `terraform/CLAUDE.md` contains detailed Terraform operational guidance, including routine CI-mediated apply and operator-only/break-glass context. Verify whether it duplicates or points to contracts.
- `docs/contracts/environment-taxonomy.md` recommends committing provider lock files; verify `.gitignore` treatment before treating this as candidate supply-chain simplification.

Candidate hypotheses to adjudicate:

- C1: Agent-owned paths may be structurally present but too smeared across prose, workflow comments, decisions, and contracts for a cold agent to route efficiently.
- C2: Some current human gates may be inherited from future SIT/PROD or trust-expansion concerns and could be converted into deterministic sandbox controls.
- C3: The admin_out_of_band path may be correctly quarantined but still too prominent in agent-loaded guidance, increasing human-centered framing.
- C4: Reconcile may reduce human recovery, but its discoverability and handoff semantics may still require simplification.
- C5: Governed Lambda code deploys may have agent-owned default channels, but bootstrap-window role provisioning flags may still leave human/manual seams worth simplifying or explicitly future-deferring.
- C6: Provider lock-file handling may be a concrete simplify-and-harden move if current ignores are still present.
- C7: The contract/prose split may have improved, but there may be remaining duplicate claims whose maintenance cost exceeds their agent value.
- C8: The current strategy may already be appropriately agent-first, and the right simplification may be small extraction/pointer work rather than major architecture change.

EMPIRICAL PASS

Bounded sampling only; do not exceed these caps.

- Sample at most 3 plan files under `docs/plans/` that mention Terraform deploy/apply case-insensitively, selected by newest git commit touching the file (`git log -1 --format=%ct -- <file>`), tie-broken by reverse lexical filename order, falling back to reverse lexical filename order if git history is unavailable. For each, ask whether an agent had to carry special-case deployment knowledge not captured in contracts.
- Sample at most 5 open recommendations (`status == "open"`, case-sensitive) from `logs/.recommendations-log.jsonl` matching regex `terraform|apply|deploy|reconcile|drift|lambda deploy|admin` case-insensitively across `title`, `context`, `acceptance`, `verification`, `file`, and `tags`, ranked by priority Critical > High > Medium > Low; unknown priorities sort after Low; then newest ISO `date`; missing/invalid dates sort oldest. If the file is absent and cache generation failed, skip this sample and set degraded dedup.
- Sample at most 2 recent decisions beyond the named ones if they appear directly in cited surfaces.

For each empirical item, tag `evidence_kind: observed` if it is an actual sampled artifact, otherwise `static`. Observed findings outrank static findings at equal severity.

METHOD

P1 - Read setup outputs and establish audited base SHA.
P2 - For each in-scope surface, read the top-level purpose/trigger section plus every section containing the search terms `terraform`, `apply`, `deploy`, `reconcile`, `drift`, `guard`, `gated`, `break-glass`, `admin`, `agent`, or `operator`; this is the sufficiency bar for large files unless a cited section points deeper.
P3 - Trace DD-A through DD-D before rating maturity.
P4 - Run the empirical pass within the caps.
P5 - Adjudicate all candidates; add your own candidates where the evidence points.
P6 - Dedup every surviving finding against roadmap, decisions, and recommendations.
P7 - Fill question answers, per-surface assessments, and rubric ratings.
P8 - Assign severity and maturity last.
P9 - Write the YAML and companion report.
P10 - Validate YAML parse and commit only the two deliverables.

DEDUP DISCIPLINE

Before filing any finding, search the ownership surfaces:

- `docs/ROADMAP-PLATFORM.yaml` for tier items and candidate decisions.
- `docs/DECISIONS.md` and `docs/DECISIONS_ARCHIVE.md` for decided constraints.
- `logs/.recommendations-log.jsonl` for open/closed recommendations.

Record `dedup_search_terms` and `dedup_hit_count` for every finding. Count one hit per distinct owning item or recommendation ID, not per textual match; decision IDs count as hits only when they explicitly own remediation, not merely rationale. A hit means you assess sufficiency or put the candidate in `rejected_candidates`; do not rediscover planned work as novel. If cache generation failed, set `audit.meta.degraded_dedup=true`, set `dedup_hit_count=null`, and mark roadmap crossrefs HYPOTHESIS.

Deliberate constraints not to flag without property-matched analysis:

- The repository is public; do not propose committing AWS account IDs, ARNs, IAM ExternalIds, credentials, internal hostnames, or trading alpha.
- Absence of live SIT/PROD accounts is not a current defect; they are future-state until the product axis reaches the named trigger.
- More human approval is not inherently safer. Prefer deterministic agent-owned controls where they property-match the risk.
- Product phase advancement is not platform deployment.
- Lambda code deploy decoupling from Terraform is intentional.
- Branch protection and advisory statuses may be deliberately non-wedging to preserve forward-fix autonomy.
- Operator-only/admin paths may be justified for bootstrap, trust expansion, or break-glass, but evaluate whether their current prominence in agent-loaded surfaces is still appropriate.

OUTPUT

The YAML is the machine-readable audit record for future planning/recommendation work; the Markdown is the human review layer. No parser is guaranteed beyond YAML parsing, so every non-default meta flag or non-empty meta note you set (`degraded_dedup`, `contract_notes`, `stale_anchors`) must also be explained in the Markdown.

All top-level blocks shown below are mandatory. Empty arrays are allowed for `findings`, `human_gate_inventory`, `simplification_moves`, `rejected_candidates`, and dependency lists when the audit evidence supports emptiness. `rubric_ratings` must contain one row for every in-scope non-optional surface crossed with every VD1-VD7 dimension, unless the surface was absent under a named degraded path.

Write `audits/terraform-deployment-strategy-<origin-main-short-sha>.yaml` with this schema:

```yaml
audit:
  meta:
    audited_commit: <origin/main short sha>
    base_branch: main
    model: <executor model self-reported name>
    methodology_version: 1
    scope_surfaces: [<surface names>]
    degraded_dedup: false
    contract_notes: ""
    stale_anchors: []
  question_answers:
    - {q: Q1, verdict: agent_first|mostly_agent_first|human_centered|fragmented, basis: [<finding ids>], prose: ""}
    - {q: Q2, verdict: well_timed|mixed|over_gated|under_gated, basis: [<finding ids>], prose: ""}
    - {q: Q3, verdict: high_simplification_potential|moderate_simplification_potential|low_simplification_potential, basis: [<finding ids>], prose: ""}
    - {q: Q4, verdict: agent_optimized|acceptable|narrative_heavy|drift_prone, basis: [<finding ids>], prose: ""}
    - q: Q5
      verdict: strong|adequate|weak|unsuitable
      basis: [<finding ids>]
      prose: ""
      external_checklist:
        - {property: plan_apply_identity, rating: met|partial|missed, evidence: ""}
        - {property: least_privilege, rating: met|partial|missed, evidence: ""}
        - {property: infra_code_deploy_separation, rating: met|partial|missed, evidence: ""}
        - {property: auditable_trust_expanding_approvals, rating: met|partial|missed, evidence: ""}
        - {property: deterministic_policy_gates, rating: met|partial|missed, evidence: ""}
        - {property: no_silent_green_noop_deploys, rating: met|partial|missed, evidence: ""}
        - {property: drift_detection, rating: met|partial|missed, evidence: ""}
        - {property: recovery_runbooks, rating: met|partial|missed, evidence: ""}
        - {property: environment_separation_proportional_to_risk, rating: met|partial|missed, evidence: ""}
        - {property: infra_supply_chain_pinning, rating: met|partial|missed, evidence: ""}
    - {q: Q6, verdict: simplify_now|simplify_incrementally|defer, basis: [<finding ids>], prose: ""}
    - q: Q7
      prose: ""
      answers:
        - {question: "", answer: "", basis: [<finding ids>]}
  per_surface_assessment:
    - {surface: <surface>, maturity: frontier|strong|solid|nascent, strengths: "", top_gaps: [<finding ids>]}
  rubric_ratings:
    - {surface: <surface>, dimension: VD1|VD2|VD3|VD4|VD5|VD6|VD7, rating: strong|adequate|weak|absent|n/a, evidence: "file:line|file:line-line|item-id|semicolon-separated list", note: ""}
  human_gate_inventory:
    - {gate: "", surface: "", current_risk_property: "", deterministic_control_considered: "", verdict: current_required|future_required|convert_to_agent_owned|remove|unclear, rationale: "", basis: [<finding ids>]}
  simplification_moves:
    - {id: MOVE-01, title: "", target_surface: "", move_type: remove|merge|convert_to_contract|convert_to_check|convert_to_workflow|defer_to_future_env|clarify_pointer, agent_control_gain: "", safety_property_preserved: "", effort: XS|S|M|L, depends_on: [<finding ids or move ids>], basis: [<finding ids>]}
  findings:
    - id: TDS-01
      surface: <canonical file path|shared>
      question: Q1|Q2|Q3|Q4|Q5|Q6|Q7
      dimension: VD1|VD2|VD3|VD4|VD5|VD6|VD7
      title: ""
      evidence: "file:line|item-id"
      evidence_kind: static|observed
      current_behavior: ""
      ideal_behavior: ""
      gap: ""
      compensating_controls_considered: ""
      change_type: add|rescope|enforce|unify|persist|clarify|retune_gate|remove|defer
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
      depends_on: [<finding ids>]
      sequencing: {safe_to_queue_now: true|false, blocked_behind: [<finding or roadmap ids>], note: ""}
  rejected_candidates:
    - {candidate: "", why_dismissed: "", compensating_control: "", control_property_match: "", decision_or_item_id: ""}
  summary:
    total_findings: 0
    novel_count: 0
    planned_insufficient_count: 0
    planned_unbuilt_count: 0
    top_improvements: [<finding ids>]
    highest_leverage_change: <finding id|null>
    maturity_overall: frontier|strong|solid|nascent
```

COUNTING INVARIANT: `findings[]` is the SOLE enumerated list; `total_findings = len(findings) = novel + planned_insufficient + planned_unbuilt`; fully-covered candidates live in `rejected_candidates`, NOT findings; `rubric_ratings` / `question_answers` / `human_gate_inventory` / `simplification_moves` are systems-of-record referenced FROM findings, never re-counted. If `findings[]` is non-empty, `top_improvements` and `highest_leverage_change` MUST be finding ids. If `findings[]` is empty, use `top_improvements: []`, `highest_leverage_change: null`, and explain the no-finding result in `summary` and the companion report.

`control_property_match` is REQUIRED whenever a compensating control is the reason for dismissal: name the property the control exercises, cite where it operates, and state why the control would fail if the defect were real.

CONFIRMED requires behavior traced to file:line or an observed sampled artifact. File evidence may use `path:line`, `path:line-line`, or a short list separated by semicolons when behavior spans files. Anything less is HYPOTHESIS.

Also write `audits/terraform-deployment-strategy-<origin-main-short-sha>.md`, a companion report for a human, <= ~1500 words. It must summarize the autonomy posture, top simplification moves, gates to keep now, gates to defer to future environments, and the highest-leverage next move.

SEVERITY + MATURITY

Assign severity after judgment:

- critical = the deployment strategy can produce a wrong-but-trusted apply/deploy/recovery outcome, or an irreversible/trust-expanding action proceeds under an unsound agent verdict.
- high = a weakness materially reduces safe agent autonomy or deterministic safety, and compensating controls are insufficient.
- medium = redundancy, ambiguity, premature gate, or scattered source-of-truth with a clear simplification path.
- low = wording, discoverability, or minor pointer cleanup.

Compute maturity last, top-down, first match wins:

- frontier = 0 critical/high findings AND every Q5 external_checklist property is met or partial, never missed, AND at least one simplification move increases agent control without adding a human gate.
- strong = 0 critical findings AND <= 1 high finding.
- solid = <= 1 critical finding.
- nascent = otherwise.

The top rating remains reachable if you argue property-matched compensating controls. Apply the same maturity thresholds per surface using only findings whose `surface` is that surface or `shared`; use `shared` only when the gap necessarily spans multiple canonical file-path surfaces and cannot be assigned to one owner. Do not let this prompt's candidate framing foreclose a strong result.

COMMIT / PR MECHANICS

1. Derive the base once:

```bash
git fetch origin main || true
git rev-parse --short origin/main || git rev-parse --short HEAD
```

2. Create a clean audit branch from the audited base:

```bash
git status --short
git switch -c audit/terraform-deployment-strategy-<sha> origin/main || git switch -c audit/terraform-deployment-strategy-<sha> HEAD
```

This branch name is a task-specific `/audit` handoff instruction for the executor session and overrides the repo's routine harness-branch convention for this audit deliverable only; it does not override any higher-priority system/developer rule that forbids branch creation. It is not an `agent/` branch. If branch creation fails because the branch already exists, switch to it only if `git status --short` has no tracked-file changes; otherwise create `audit/terraform-deployment-strategy-<sha>-2`. If a higher-priority harness policy requires committing on the current non-main branch, keep the current branch and record that policy in `audit.meta.contract_notes`. If `git status --short` shows tracked-file changes before you write the two deliverables, abort and record the reason in your final message rather than guessing; allowed gitignored cache changes do not count as dirty for this rule.

3. Write only:

```text
audits/terraform-deployment-strategy-<sha>.yaml
audits/terraform-deployment-strategy-<sha>.md
```

4. Validate the YAML parses. If repo-wide validation fails for files outside your two deliverables, for pre-existing repository state, or after writing only allowed gitignored caches/logs, record it in `audit.meta.contract_notes`; do not fix unrelated files.

5. Commit without GPG signing if signing is unavailable:

```bash
git add audits/terraform-deployment-strategy-<sha>.yaml audits/terraform-deployment-strategy-<sha>.md
git -c user.name=Claude -c user.email=noreply@anthropic.com commit --no-gpg-sign -m "audit: terraform deployment strategy (<sha>)"
git push -u origin HEAD
```

6. Open a PR against `main` using the available GitHub PR tool. If push or PR creation fails because credentials/network/tooling are unavailable, do not invent another channel: leave the commit local, record the exact failed command and error in your final response, and still stop without modifying other files. Title:

```text
audit: terraform deployment strategy agent autonomy
```

Body: include the YAML `summary` block in a fenced code block plus a 2-3 sentence lede. Then END THE TURN. Do not poll CI. Do not merge. Do not subscribe. Do not self-approve.

GUARDRAILS

- Write boundary is closed: only the two `audits/terraform-deployment-strategy-<sha>.*` deliverables may be created or modified.
- Do not edit Terraform, workflows, scripts, contracts, recommendations, decisions, roadmap files, docs outside `audits/`, or logs.
- Do not run Terraform apply, Lambda deploy, workflow dispatch, or AWS mutation.
- Do not expose AWS account IDs, ARNs, IAM ExternalIds, credentials, internal hostnames, or trading alpha.
- Any number of surviving findings, including zero, is valid; state it and do not pad.
- Precision over volume. If the current system is already agent-first, say so and recommend small simplifications.
- A proposal that merely adds human gates without property-matching a current risk is suspect. Prefer deterministic agent-owned controls where possible.
