# Plan

## Intent

Pivot the autonomous executor's compute substrate and LLM inference path in the platform roadmap, with both decisions persisted as new candidate_decisions (CDs) in `docs/ROADMAP-PLATFORM.yaml` and reflected in `docs/INTENT-provider-agnostic-executor.md`. This unblocks future T4 work against an architecturally clean substrate and removes a known economic anti-pattern (AWS Bedrock markup over native DeepSeek API pricing). Contributes to the autonomy North Star by making the executor's runtime topology (Step Functions + Lambda Durable Functions + Lambda) match the natural shape of an agentic plan->critique->implement->review loop, eliminating the 15-minute Lambda ceiling that drove the original Fargate decision.

## Plan Type

REPORT-ONLY

The substantive deliverables are the edits to `docs/ROADMAP-PLATFORM.yaml` (the platform roadmap state itself) and `docs/INTENT-provider-agnostic-executor.md` (the executor LLM integration intent doc). This PLAN file is the planning artefact pointing at those edits and exists per the planning-skill template. No source code changes land in this plan -- the Copilot SDK retirement (the only code-level cleanup directly implied by the pivot) is filed as a follow-on IMPLEMENTATION plan after the roadmap edits merge.

## Verification Tier

V1

Static documentation (YAML + markdown) only. Structural validation via `scripts/platform_roadmap.RoadmapDocument` Pydantic schema check exercised by `scripts/validate.py`. Substantive correctness via Step 9 plan-critique fresh-context gate and Step 10 multi-perspective deliverable critique (architect + adversarial reviewer in parallel).

## Branch

agent/executor-pivot-stepfn-durable-deepseek

## Phase

Platform-roadmap direction change. Not a single ROADMAP-PRODUCT phase. Relates to platform tier T4 (executor + autonomy) and the executor LLM-integration sub-architecture. Does NOT advance any tier_item to status complete; it rewrites the intent + substrate semantics that future T4.x atomic plans will implement against.

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Add CD.27 (Step Functions + Durable Functions + Lambda executor substrate, narrowly supersedes CD.11). Add CD.28 (DeepSeek-direct via LiteLLM as Tier-1 inference; Anthropic-direct as Tier-2 escape hatch; Bedrock fully retired from architecture, fully supersedes CD.7, supersedes Decision 40). Edit CD.7 (mark fully superseded by CD.28). Edit CD.11 (mark narrowly superseded by CD.27, Fargate retained for ECS Run Task escape hatch only). Edit CD.17 (rewrite Bedrock substrate references in `detail:` text; reversal trigger STRUCTURE unchanged). Edit CD.21 (autonomous-loop compute substrate reference: Fargate -> Step Functions + Durable Functions). Edit KG.7 (rewrite as "Anthropic Tier-2 escape-hatch availability"). Rewrite T4.1 (Step Functions state machine + per-step Lambda scaffolding, replaces Fargate task definition). Rewrite T4.2 (agent-persona Durable Functions + LiteLLM transport, replaces Fargate handler). Rewrite T4.3 (scheduled-agent loop via Step Functions). Light edit T4.4 (reference cleanup only). Rewrite T0.4 (Anthropic-direct + DeepSeek API key provisioning, replaces Bedrock model access requests). Annotate T0.3 IAM policy bedrock:InvokeModel as vestigial. Sweep T2.12 / T2.13 architecture diagram callouts (Fargate -> Step Functions). Edit cost_projection.current_scale.breakdown.bedrock_executor_inference + projected_100tb_scale.breakdown.bedrock_executor_inference + alternative_architectures_considered + reevaluation_triggers. Edit foundation_already_shipped if any Bedrock references remain (none expected). |
| `docs/INTENT-provider-agnostic-executor.md` | Modify | Rewrite Stage 4 runtime-selection table (Lambda 15-min-ceiling rejection invalidated by per-step decomposition; Step Functions + Durable Functions becomes leading candidate; Fargate via ECS Run Task as long-step escape hatch only). Rewrite Tier 1/2/3 provider tables (DeepSeek-direct = Tier 1, Anthropic-direct = Tier 2, OpenRouter = Tier 3 deferred unchanged; Bedrock removed from all primary tiers). Update Lessons table (add 2026-05 row for Bedrock-DeepSeek-markup discovery + pivot rationale). Update four-layer model target column where Bedrock-specific. Update Architecture box-and-arrow diagram. Update Credential Lifecycle table (Tier 1 = DeepSeek API key in Secrets Manager; Tier 2 = Anthropic API key in Secrets Manager funded by Max x5 programmatic pool with documented credit-pool spillover note). Update Health Signals (Bedrock 4xx/5xx -> DeepSeek 4xx/5xx + Anthropic 4xx/5xx). Update Migration Stages (Stage 1 entry criteria updated; Stage 4 runtime selection closed). Update Non-Goals if necessary. Update Triggers and Review Cadence if necessary. Close OQ 5 (container runtime in Stage 4) with the Step Functions + Durable Functions decision. Reframe OQ 6 (prompt cache breakpoint strategy) for DeepSeek native context caching (no client opt-in required) instead of Bedrock cachePoint. |
| `docs/plans/PLAN-executor-pivot-stepfn-durable-deepseek.md` | Create | This planning artefact. |

## Bundled Recommendations

None bundled. The pivot is a roadmap-architecture change, not a rec implementation. Follow-on work that this pivot enables (Copilot SDK retirement, T4.1 atomic plans, T4.2 atomic-persona Durable Function plans, llm_client.py LiteLLM transport) is filed via separate `/plan` sessions or via `file_rec` after this lands.

## Infrastructure Dependencies

None for this plan. No `.tf` files in scope. CD.27 + the rewritten T4.1 / T4.2 / T4.3 tier items describe future infrastructure (Step Functions state machines, per-step Lambdas, Durable Function configurations, ECS Run Task escape-hatch integration), but those land in subsequent atomic IMPLEMENTATION plans under T4.x, each of which is independently subject to the CD.16 per-Lambda gating + Decision 67 deferred-deployment markers in the planning skill.

## Acceptance Criteria

- [ ] `docs/ROADMAP-PLATFORM.yaml` validates against `scripts/platform_roadmap.RoadmapDocument` Pydantic schema with no errors (CI gate is `python -m scripts.validate --pre`)
- [ ] CD.27 and CD.28 present in `candidate_decisions[]` with the required fields (id, title, detail, gates, state, plus the appropriate `narrowly_supersedes` / `supersedes_decisions` references)
- [ ] CD.7 carries a `fully_superseded_by: CD.28` reference (or `state: superseded` marker, whichever the schema accepts; verify schema acceptance during write)
- [ ] CD.11 carries a `narrowly_superseded_by: CD.27` reference for the Fargate-as-executor-substrate clause
- [ ] CD.17 detail text no longer references Bedrock as the LLM substrate; reversal trigger expression structure unchanged (`T4.2.status == "complete" AND grace_period_elapsed(T4.2, 14) AND ...`)
- [ ] CD.21 detail text references Step Functions + Durable Functions (CD.27) as the autonomous-loop compute substrate
- [ ] KG.7 rewritten as "Anthropic Tier-2 escape-hatch availability" with appropriately reduced blast radius
- [ ] T4.1 / T4.2 / T4.3 intent + files_in_scope + related_candidate_decisions updated to reflect the new substrate; T4.4 reference cleanup only
- [ ] T0.4 rewritten for Anthropic-direct + DeepSeek API key provisioning (or retired with explicit reference to the replacement work in T4.x atomic plans)
- [ ] cost_projection edits land for both current_scale and projected_100tb_scale breakdowns; alternative_architectures_considered + reevaluation_triggers updated
- [ ] `docs/INTENT-provider-agnostic-executor.md` Stage 4 runtime selection table revised; Lambda rejection rationale removed; Step Functions + Durable Functions listed as primary; Fargate via ECS Run Task as escape hatch only
- [ ] INTENT Tier 1/2/3 table revised: DeepSeek-direct = Tier 1, Anthropic-direct = Tier 2, OpenRouter = Tier 3 deferred; Bedrock removed from primary tiers
- [ ] INTENT Lessons table has new 2026-05 entry capturing Bedrock-DeepSeek-markup discovery and pivot rationale
- [ ] INTENT credit-pool-spillover note recorded in Tier 2 provider rationale (Max x5 programmatic pool sized $100/mo, no rollover, spillover at API rates)
- [ ] grep audit: no remaining "Fargate" references in `docs/ROADMAP-PLATFORM.yaml` outside historical/escape-hatch contexts (i.e., ECS Run Task escape-hatch mentions in CD.27 / T4.x; CD.11 in retired-state context; CD.21 narrowly-supersedes reference)
- [ ] grep audit: no remaining "Bedrock" references in primary-substrate contexts in `docs/ROADMAP-PLATFORM.yaml` (vestigial `bedrock:InvokeModel` in T0.3 PlatformDev IAM policy is acceptable when annotated as such)
- [ ] Step 9 plan-critique fresh-context gate returns Recommendation: PROCEED on the PLAN artefact
- [ ] Step 10 multi-perspective deliverable critique converges (both architect lens and adversarial lens return PROCEED on a fresh round, OR human explicitly accepts current state with documented deferrals)

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | Validate ROADMAP-PLATFORM.yaml structure | `bin/venv-python -m scripts.validate --pre` | Validate passes with no schema errors for `RoadmapDocument`; CD.27 and CD.28 load; all `gates:` references resolve to existing tier_items; dependency cycles absent | Schema error names the malformed field; correct the YAML and re-run |
| 2 | [pre-deploy] | Confirm CD.27 and CD.28 are present and well-formed | `bin/venv-python -c "import yaml,sys; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml','r',encoding='utf-8')); ids=[c['id'] for c in d['candidate_decisions']]; assert 'CD.27' in ids and 'CD.28' in ids, ids; print('OK')"` | Prints `OK` | If absent, edit YAML to add the missing CD |
| 3 | [pre-deploy] | Confirm CD.7 + CD.11 supersession lineage written | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml','r',encoding='utf-8')); cds={c['id']:c for c in d['candidate_decisions']}; assert 'CD.28' in str(cds['CD.7']), 'CD.7 must reference CD.28'; assert 'CD.27' in str(cds['CD.11']), 'CD.11 must reference CD.27'; print('OK')"` | Prints `OK` | Add the missing reference (use `fully_superseded_by` / `narrowly_superseded_by` per schema acceptance) |
| 4 | [pre-deploy] | Confirm T4.1 / T4.2 / T4.3 reference CD.27 (and CD.28 where applicable) | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml','r',encoding='utf-8')); ti={t['id']:t for t in d['tier_items']}; rcds_42=set(ti['T4.2'].get('related_candidate_decisions',[])); assert 'CD.27' in rcds_42 and 'CD.28' in rcds_42, rcds_42; assert 'CD.27' in set(ti['T4.1'].get('related_candidate_decisions',[])), ti['T4.1'].get('related_candidate_decisions'); assert 'CD.27' in set(ti['T4.3'].get('related_candidate_decisions',[])), ti['T4.3'].get('related_candidate_decisions'); print('OK')"` | Prints `OK` | Add missing CD references to the affected tier_items |
| 5 | [pre-deploy] | Sweep for Fargate references outside permitted contexts (CD.11 retired, CD.21 narrowly-supersedes, CD.27/T4.x ECS-Run-Task escape-hatch) | `bin/venv-python -c "import re; t=open('docs/ROADMAP-PLATFORM.yaml','r',encoding='utf-8').read(); hits=[(i+1,line) for i,line in enumerate(t.splitlines()) if re.search(r'Fargate',line,re.I)]; [print(f'{i}: {l[:140]}') for i,l in hits]; print(f'TOTAL: {len(hits)}')"` | All printed lines are inside CD.11 retired-context blocks, CD.21 narrowly_supersedes blocks, CD.27 escape-hatch blocks, or T4.x escape-hatch language. Human-judgement check | Move any stray Fargate-as-primary references into the appropriate retired/escape-hatch context |
| 6 | [pre-deploy] | Sweep for Bedrock references in primary-substrate contexts | `bin/venv-python -c "import re; t=open('docs/ROADMAP-PLATFORM.yaml','r',encoding='utf-8').read(); hits=[(i+1,line) for i,line in enumerate(t.splitlines()) if re.search(r'Bedrock',line,re.I)]; [print(f'{i}: {l[:140]}') for i,l in hits]; print(f'TOTAL: {len(hits)}')"` | All printed lines are inside CD.7 fully-superseded context, vestigial-IAM-policy comments (T0.3), historical Lessons/Decisions references, or CD.28 supersession lineage. Human-judgement check | Edit any primary-substrate references that survived the pivot |
| 7 | [pre-deploy] | Confirm INTENT Tier 1 = DeepSeek-direct | `bin/venv-python -c "t=open('docs/INTENT-provider-agnostic-executor.md','r',encoding='utf-8').read(); assert 'Tier 1: DeepSeek' in t or 'DeepSeek' in t.split('### Tier 1')[1][:500], 'Tier 1 must name DeepSeek-direct'; print('OK')"` | Prints `OK` | Edit the INTENT Tier 1 heading to name DeepSeek-direct |
| 8 | [pre-deploy] | Confirm INTENT Stage 4 no longer rejects Lambda on 15-min ceiling alone | `bin/venv-python -c "t=open('docs/INTENT-provider-agnostic-executor.md','r',encoding='utf-8').read(); s4=t.split('### Stage 4')[1][:3000] if '### Stage 4' in t else ''; assert 'Step Functions' in s4 and 'Durable Functions' in s4, 'Stage 4 must name Step Functions + Durable Functions as primary candidate'; print('OK')"` | Prints `OK` | Add Step Functions + Durable Functions selection to Stage 4 |
| 9 | [pre-deploy] | Step 9 plan-critique gate (fresh-context Agent subagent) | (Dispatched via Agent tool with subagent_type=general-purpose; invokes `plan-critique` skill; returns structured critique) | Recommendation: PROCEED | Address REVISE findings; re-dispatch the gate until PROCEED |
| 10 | [pre-deploy] | Step 10 multi-perspective deliverable critique (two parallel Agent subagents -- architect lens + adversarial lens) | (Dispatched via Agent tool, two parallel calls; each returns structured findings on the YAML+INTENT deliverables) | Both verdicts: PROCEED on a fresh round, OR human explicitly accepts current state with documented deferrals captured in a Known Gaps section of the deliverable | Apply revisions per human direction; commit incrementally; re-dispatch critiques after each material revision until convergence |

## Constraints

- Honour AGENTS.md Temporary Operational Constraints: STRATEGIC plans suspended (this plan is REPORT-ONLY, not STRATEGIC, so the constraint does not bind directly but the freeze rationale informs the plan-type choice); Lambda deployment deferred (this plan touches no Lambda-packaged files -- new T4.x tier_items reference future Step Functions / per-step Lambda artefacts, but no build/deploy/smoke-test step is in this plan's scope per CD.16 + Decision 67).
- Honour CLAUDE.md "Branching" hard rule: no edits while on `main`; this plan executes on `agent/executor-pivot-stepfn-durable-deepseek`.
- Honour `CD.13` (agent-first repository): YAML edits prefer machine-parseable structure; markdown edits to INTENT remain in narrative form because that artefact predates CD.13 and a wholesale YAML conversion is out-of-scope for this pivot (would conflict with the Class B contract ratification wave under CD.25 / T-1.x).
- Honour Decision 55 (RCA-first executor): CD.27's substrate description must NOT permit retry-on-LLM-judgement-failure; Step Functions retry policies are deterministic-only; LLM-judgment failures escalate via the rec/RCA path.
- Honour the data-quality `single portal invariant`: no edits to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl` in this plan.
- No rescue agents or workaround loops (Decision 55).
- No `STRATEGIC` plan-type declaration (Decision 67 freeze + AGENTS.md Temporary Operational Constraints).

## Context

- **Pivot rationale (a) -- compute substrate**: Original CD.11 (Fargate-based executor) was made on the assumption that the per-rec plan->implement->PR loop is a single continuous process. The pivot recognises that the loop is naturally a state machine -- a deterministic graph of agent personas (plan, critic, decision-scout, implement, review) interleaved with deterministic glue (pick_rec, prepare_workspace, file_pr, emit_telemetry). Step Functions owns the graph; Lambda Durable Functions own the per-persona iterative LLM-tool loops (eliminating the 15-minute Lambda ceiling that originally drove Fargate); regular Lambdas own the cheap glue. Long-running deterministic steps that genuinely exceed 15 minutes (e.g., full pytest suite, terraform apply against personal account) use the Step Functions ECS Run Task synchronous integration as an escape hatch -- Fargate is not eliminated, demoted from "the executor's substrate" to "the long-step escape hatch within the executor's orchestrator." Industry-confirmed best practice per AWS-documented agentic LLM executor architecture in 2026; Lambda Durable Functions (released 2026) is documented as the cleanest fit for agentic iterative loops.
- **Pivot rationale (b) -- LLM inference**: Original CD.7 (LLM-stays-on-Bedrock) was made before the Bedrock DeepSeek price discovery. Actual numbers: Bedrock charges $0.62 input / $1.85 output per 1M tokens for DeepSeek V3.2; direct API charges $0.252 input / $0.378 output. Ratio: ~2.5x input, ~4.9x output. DeepSeek is additionally EXCLUDED from Bedrock's 50%-off Batch billing mode (which would otherwise mitigate the markup for batch workloads). DeepSeek's own native context caching ($0.0252 input cache-hit) is unavailable on Bedrock because Bedrock prompt caching covers only Anthropic + Nova model families. At cost-projection scale (Bedrock-DeepSeek executor inference was projected at $50-200/mo at scale), direct-API drops this to ~$10-40/mo plus near-free cache hits on repeated repository context. Sufficient to justify pivot on its own; aligns with INTENT-provider-agnostic-executor.md Non-Goal "single-vendor commitment" and the Lock-in Lessons table.
- **Pivot rationale (c) -- Anthropic-direct as Tier 2**: User has a Claude Code Max x5 subscription with a £100/mo Anthropic API credit (programmatic pool, June-2026-billing-change-aware). Anthropic-direct via LiteLLM is the warm-fetched escape hatch for Claude-class judgment when DeepSeek underperforms or has an outage. Funded by the credit pool at current scale; spillover at API rates if executor volume scales beyond pool sizing. Recorded as known-consideration in CD.28 -- not blocking; informs cost-monitoring guidance.
- **Decision lineage (cited per decision-scout flag results)**:
  - Decision 39 (Step Functions = canonical orchestrator, decided April 2026) -- CD.27 extends a ratified primitive; explicitly cited as precedent
  - Decision 40 (Copilot SDK + Bedrock planning, decided-deferred April 2026) -- CD.28 supersedes both halves; explicit `supersedes_decisions: [40]` on CD.28
  - Decision 47 (Bedrock revocation/restoration lesson) -- INTENT lock-in lesson preserved by Anthropic-direct serving the warm-fetched escape-hatch role in the new tier model
  - Decision 49 (Copilot SDK retirement, supersedes Decision 47) -- aligned; follow-on PLAN-retire-copilot-sdk file deletion lands separately
  - Decision 55 (RCA-first executor) -- CD.27 preserves this contract verbatim; Step Functions retry policies are deterministic-only
  - Decision 67 (STRATEGIC + Lambda deploy freeze) -- this plan is REPORT-ONLY V1 (no Lambda deploy steps); future T4.x atomic plans inherit CD.16 per-Lambda gating
  - Decision 68 (Self-hosted EC2 runner) -- intersects with T4.3 (scheduled-agent loop substrate) and CD.21 (CI runner OIDC migration on public-flip); CD.27 keeps T4.3 substrate compatible with both options and explicitly defers the choice to T4.3 implementation planning
- **Open question (carries into follow-on T4.1 atomic plans)**: Should the architecture migrate the scheduled-agent loop (T4.3) to Step Functions immediately, or retain the option of self-hosted runner cron until T4.x stability is verified? CD.27 should keep both options open; the choice falls to T4.3 atomic plans.
- **Known consideration on Anthropic Tier-2 credit pool**: Production fallback tied to a personal subscription credit relationship is recorded as a future-cost-monitoring item, not a blocker. If executor volume scales beyond Max x5 programmatic pool sizing, recommendation: file rec to provision an org-billed Anthropic API key as a credit-pool overflow path. INTENT already documents the underlying Anthropic billing model.
- **Main divergence at plan-write time**: Main moved forward by one commit (`8a1aa84 feat(t014-phase2): scripts/ Windows-assumption sweep`) between preflight and branch creation. The diff touched `docs/ROADMAP-PLATFORM.yaml` only for T0.14 progress note (lines 1769-1789 area). T0.14 is well outside this plan's edit zone (T0.4, T4.x, CD.27, CD.28, CD.7, CD.11, CD.17, CD.21, KG.7, cost_projection). No conflict; branch is up-to-date.

## Pre-Implementation Checklist

- [x] Branch confirmed not on `main` (currently on `agent/executor-pivot-stepfn-durable-deepseek`)
- [x] `docs/PROJECT_CONTEXT.md` read fully
- [x] `docs/DECISIONS.md` read (planning agent loaded the specific decisions flagged by the decision-scout subagent: 39, 40, 47, 49, 55, 67, 68; Step 10 critic subagents will read the full file in fresh context)
- [x] All files in Scope table located and readable
- [x] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Apply edits to `docs/ROADMAP-PLATFORM.yaml`** in the following order to keep the file structurally valid throughout:
   - (1a) Add new `CD.27` and `CD.28` entries to the `candidate_decisions[]` list in id order
   - (1b) Edit `CD.7` to mark fully superseded by CD.28; preserve the original `detail:` text for historical traceability
   - (1c) Edit `CD.11` to mark narrowly superseded by CD.27 (Fargate-as-executor-substrate clause); preserve Fargate-via-ECS-Run-Task as escape hatch
   - (1d) Edit `CD.17` `detail:` text to replace Bedrock-substrate references with DeepSeek-direct + Anthropic-direct path; preserve the reversal trigger expression structure verbatim
   - (1e) Edit `CD.21` `detail:` text replacing Fargate autonomous-loop-compute substrate reference with Step Functions + Durable Functions (CD.27)
   - (1f) Rewrite `KG.7` (Bedrock partial-denial contingency) as "Anthropic Tier-2 escape-hatch availability" gap with appropriately reduced scope
   - (1g) Rewrite `T4.1` intent + files_in_scope + decomposition_hints + exit_criteria + related_candidate_decisions for Step Functions state machine + per-step Lambda scaffolding
   - (1h) Rewrite `T4.2` intent + files_in_scope + exit_criteria + related_candidate_decisions for agent-persona Durable Functions + LiteLLM transport
   - (1i) Rewrite `T4.3` intent + files_in_scope + exit_criteria + related_candidate_decisions for Step Functions scheduled-agent loop
   - (1j) Light edit `T4.4` to update related_candidate_decisions cleanup only
   - (1k) Rewrite `T0.4` for Anthropic-direct + DeepSeek API key provisioning (retains user_action_required: true)
   - (1l) Annotate `T0.3` PlatformDev IAM policy `bedrock:InvokeModel` reference as vestigial-post-CD.28
   - (1m) Sweep T2.12 / T2.13 architecture diagram callouts (Fargate -> Step Functions)
   - (1n) Edit `cost_projection.current_scale.breakdown` and `cost_projection.projected_100tb_scale.breakdown` (delete bedrock_executor_inference; add deepseek_executor_inference + anthropic_escape_hatch_spillover); update `alternative_architectures_considered` if Bedrock referenced; update `reevaluation_triggers` to use DeepSeek-direct cost benchmark
2. **Apply edits to `docs/INTENT-provider-agnostic-executor.md`**:
   - (2a) Rewrite Stage 4 runtime-selection table -- Lambda + Step Functions + Durable Functions promoted to leading candidate; Fargate via ECS Run Task as escape hatch only; Lambda Container 15-min-ceiling rejection rationale REWRITTEN to clarify that per-step decomposition + Durable Functions checkpointing eliminates the original 15-min concern
   - (2b) Rewrite Tier 1 / 2 / 3 provider tables: Tier 1 = DeepSeek-direct via LiteLLM (primary); Tier 2 = Anthropic-direct via LiteLLM (warm-fetched, Max x5 programmatic-pool funded with credit-pool spillover note); Tier 3 = OpenRouter (deferred, unchanged)
   - (2c) Update Lessons table with new 2026-05 row: "Bedrock DeepSeek markup discovery (~2.5x input, ~4.9x output vs direct; DeepSeek excluded from Bedrock Batch) and pivot to direct API via LiteLLM"
   - (2d) Update four-layer model table (Layer 1 Target column: LiteLLM remains; underlying provider commentary edited)
   - (2e) Update Architecture box-and-arrow diagram (provider adapter box: "Bedrock primary" -> "DeepSeek-direct primary; Anthropic-direct escape hatch")
   - (2f) Update Credential Lifecycle table (drop Bedrock IAM row; Tier 1 = DeepSeek API key; Tier 2 = Anthropic API key)
   - (2g) Update Health Signals (Bedrock 4xx/5xx -> DeepSeek 4xx/5xx + Anthropic 4xx/5xx)
   - (2h) Close OQ 5 (container runtime in Stage 4) explicitly with the Step Functions + Durable Functions decision
   - (2i) Reframe OQ 6 (prompt cache breakpoint strategy) for DeepSeek native context caching (no client opt-in; hash-based) instead of Bedrock cachePoint
   - (2j) Mark the document `Status: DRAFT` -> retain DRAFT until the new CDs ratify via T0.7b log-decision Lambda (consistent with existing CD lifecycle); add a brief Update Log entry at the top recording this pivot
3. **Commit** the YAML + INTENT edits + the PLAN file in a single commit on branch `agent/executor-pivot-stepfn-durable-deepseek`. Commit message: `plan(executor-pivot-stepfn-durable-deepseek): pivot CD.7/CD.11/T4.x to Step Functions + Durable Functions + DeepSeek direct`
4. **Execute Verification Plan** -- run steps 1-8 (structural checks) locally; if any fail, fix the YAML/INTENT and re-run. Step 9 (plan-critique gate) and Step 10 (multi-perspective deliverable critique) are dispatched via the Agent tool per the planning skill methodology.
5. **Iterate on Step 9 critique findings** until Recommendation: PROCEED.
6. **Iterate on Step 10 critique findings** until both critics converge on PROCEED, OR human explicitly accepts the current state with documented deferrals captured in a Known Gaps section of the deliverable.
7. **Final commit** (may be empty if all revisions were committed incrementally during iteration). Commit message: `plan(executor-pivot-stepfn-durable-deepseek): approved plan`
8. **Report**: planning agent's mission is complete after the approved-plan commit lands. Follow-on plans are: (a) PLAN-retire-copilot-sdk (small IMPLEMENTATION, file deletion + reference sweep), (b) T4.1 atomic plans (Step Functions state machine, per-step Lambda scaffolding, IAM, observability), (c) T4.2 atomic-persona plans (one per Durable Function persona: plan_agent, plan_critic, decision_scout, implement_agent, code_reviewer), (d) T4.3 scheduled-agent migration plan, (e) llm_client.py LiteLLM transport rewrite (deferred until T4.2 atomic plans drive it).
