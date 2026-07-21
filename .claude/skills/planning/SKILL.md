---
name: planning
description: Deep methodology and rules for software planning, complexity assessment, and verification tier design. Use this when running the /plan workflow or when architecting new features.
model: opus[1m]
required-context:
  - logs/.preflight-report.json
  - docs/PROJECT_CONTEXT.md
  - docs/ROADMAP-PLATFORM.yaml
---

# Planning Methodology & Rules

You are using this skill to augment the `/plan` workflow. Apply these deep instructions when executing the workflow steps. You must NEVER initiate modifications to source code or global instructions (docs/PROJECT_CONTEXT.md, skills) during a planning session. SOLE EXCEPTION: roadmap-bookkeeping edits to `docs/ROADMAP-PLATFORM.yaml` / `docs/ROADMAP-PRODUCT.yaml` proposed by the Tier Item Freshness Gate (status closeouts, criteria re-grounding) -- and only after explicit human confirmation; these reconcile roadmap DATA with reality, they implement nothing. The planning phase ends with the commitment of the PLAN artifact. Implementation only begins after an explicit /implement trigger with ANOTHER agent.

## Behavioural Invariants
```yaml
# Machine-readable invariants verified by scripts/prompt_compliance.py
preflight_run: true                # session_preflight.py must run at Step 1
harness_branch: true               # work on the harness-assigned session branch; do NOT create agent/ branches
decision_scout_gate: true          # @decision-scout must be invoked at Step 6a before presentation
critique_gate: true                # @plan-critique must be invoked before completion
report_critique_gate: report-only  # REPORT-ONLY plans must run Step 10 multi-perspective deliverable critique
never_on_main: true                # no file edits while on main branch
```

## Preflight Constraints (Workflow Step 1)
When reading `logs/.preflight-report.json`, apply these conditionals:
- **`venv_ok: false`** -- Verify `bin/venv-python -c "import sys; print(sys.executable)"` resolves to the venv interpreter and rerun preflight. If still false, STOP.
- **`creds_status: "unavailable"`** -- **Static-key recovery (non-fatal, Decision 60):** the static-key assume-role chain has no interactive login. Verify it with `aws sts get-caller-identity --profile agent_platform`; if the `agent_static` key was rotated, refresh `~/.aws/credentials`. Do NOT block -- continue in degraded mode (credential-dependent verifiers are skipped, emitting SKIPPED). Autonomous executors never attempt recovery.
- **`log_sync_result.status == "committed"`** -- Print: "Session logs synced to main ([N] file(s) committed)." Continue.
- **`log_sync_result.status == "conflict"`** -- STOP. Print error and require human resolution.
- **`uncommitted_changes` non-empty** -- Ask human: "Resume, stash, or discard?". Wait.
- **`main_freshness.status == "fetch_failed"`** -- Informational. Surface: "Could not refresh `origin/main` ([error]). Critique and Scope-overlap checks will use the stale local main ref." Continue.
- **`main_freshness.commits_behind > 20`** -- Surface as planning context warning: "Branch is N commits behind `origin/main`. Plan-critique (Step 9) reads `docs/PROJECT_CONTEXT.md`, `DECISIONS.md`, and `ROADMAP-PLATFORM.yaml` from the working tree; if these have moved on main, the critique evaluates against stale context. Recommend rebasing before continuing." Non-blocking but prompt the human to decide.
- **`main_freshness.commits_behind > 0`** -- Retain `main_freshness.main_files_changed_since_branch` for the Step 4 Main Divergence Assessment. Non-blocking at this step.
- **`cron_review_fresh: false`** -- Note to human (non-blocking).
- **`ops_outbox` non-empty** -- Entries in migrated-table or `*_pending` dirs are ANOMALIES (Decision 84 I-4: those outboxes are retired and never drained) -- re-file the content via the portal and delete the files. Legacy staging dirs (telemetry/session_log/execution_plans) drain via `bin/venv-python -m scripts.sync.ops sync`. If that fails, STOP.
- **`open_recommendations > 0`** -- Surface counts and ask whether to address. Wait.
- **`non_automatable_recommendations > 0`** -- Informational. Surface counts; do not require per-rec discussion. Individual review is suspended per Decision 73 until CD.17 / T4.2 reverses (Decision 67's Lambda-deploy clause was lifted by Decision 79; the STRATEGIC clause survives).
  - If `non_automatable_softcap_breached` is true (count > 250), surface as a planning context note.
- **`friction_patterns` non-empty** -- Surface repeated patterns as planning context.
- **`metrics_anomalies` non-empty** -- Surface anomalies as planning context.
- **`data_quality.last_run.verdict == "FAIL"`** -- Surface as planning context: "Data quality checks failing ([N] failures across [tables]). Run `bin/venv-python -m scripts.data_quality_runner` for details." Non-blocking but relevant if the plan touches data pipelines or table schemas.
- **`data_quality.last_run` is null** -- Note: "Data quality checks have never been run. After fixing the pipeline, run `bin/venv-python -m scripts.data_quality_runner` to establish a baseline." Non-blocking.
- **`ci_rca_unresolved_recs` non-empty** -- **HARD BLOCK** at commitment time. `/plan` cannot scope unrelated work while any unresolved ci-rca rec exists. Proceed only to scope work that satisfies one of the three Related-Work conditions (see Step 8) OR has a logged deferral rationale in the new plan's Context section. (Legacy: if the report only has `ci_rca_recs` and no `ci_rca_unresolved_recs`, treat all entries as HARD BLOCK.) Full triage surfacing and the SOFT PROMPT / HARD ALERT classification is `/orient`'s responsibility -- run `/orient` for the full ci-rca visibility layer.
- **`ci_rca_likely_resolved_recs`, `ci_rca_liveness_alert`, `forward_fix_recursion_alert`** -- Full triage (SOFT PROMPT, HARD ALERT, forward-fix recursion) is surfaced by `/orient`. If still unresolved when `/plan` runs, apply the close or triage guidance from the orient skill.
- **`budget_bypass_alert` non-null** -- **Informational**. Surface the count and recent bypass reasons as planning context: "Fast-tier budget bypassed N times in 7 days." Repeated `--ignore-budget` use indicates fast-tier drift and likely warrants a planning session to revisit the budget or identify which check is slow.

### What Telemetry Health Represents

The preflight `telemetry_health` section reports operational health of the telemetry and ops data pipelines:

1. **Telemetry store status** (stub, Decision 84): the old Athena telemetry tables are retired, so the preflight reports a single `telemetry-store: not migrated (Phase 4)` check with NO queries issued. Session metrics return when telemetry re-lands on DuckLake (Decision 84 Phase 4 / tier_item T2.36). Until then, do not gate plans on session counts/staleness.

2. **Data quality coverage** (from `config/agent/data_quality/*.yaml`): how many declarative checks (not_null, unique, accepted_values, relationships, row_count, recency) are defined across how many tables. This answers: "Do we have visibility into data correctness?"

3. **Last DQ run result** (from `logs/debug/dq-latest.json`): the verdict (PASS/FAIL), pass/fail/warn counts, and timestamp of the most recent `bin/venv-python -m scripts.data_quality_runner` execution. This answers: "When we last checked, was the data actually correct?"

Together these form a three-layer health picture:
- **Pipeline health**: Is data flowing? (session count > 0, staleness < 72h)
- **Quality coverage**: Do we have checks defined? (checks_defined > 0)
- **Quality state**: Are the checks passing? (last_run.verdict == PASS)

If pipeline health is critical (no sessions in 7 days), the plan should prioritise pipeline fixes before adding new features. If quality coverage is zero, any plan touching data write paths should include adding YAML checks. If the last DQ run failed, the plan should note which tables are affected.

## Follow-on /plan mode (in_progress items with open criteria)

When intent targets an `in_progress` tier_item (one with open criteria remaining), `/plan`
operates in **follow-on mode**. This is the common case -- most items take N follow-on plans.

### Trigger
- `/orient` emits a follow-on `/plan <item-id>: follow-on -- <name>` prompt for any in_progress
  item where `needs_followon_plan` is True (open criteria AND no in-flight plan covers them).
- The human selects one of these prompts, or names an in_progress item directly.

### Follow-on /plan protocol
1. **Load state.** Read the item's `exit_criteria[]` from `docs/ROADMAP-PLATFORM.yaml`; identify
   which criteria have `status: open`. Load any prior PLAN-*.yaml files that reference this item
   (via their `closes_criteria` field or the item id in their Phase/Context) and the item's
   `progress_note` to understand what has already shipped.
2. **Scope the NEXT slice only.** Plan the minimum work to close one or more open criteria -- do
   NOT re-plan work already met/rehomed. The plan's scope, acceptance criteria, and VP steps are
   constrained to what is needed to flip the chosen open criteria.
3. **Declare closes_criteria.** The plan document MUST include a `closes_criteria:` field listing
   each item-criterion the plan commits to close on a verified VP pass, in `<item-id>:<crit-id>`
   format (e.g. `T-1.23:c2`). The plan's acceptance_criteria should 1:1 map onto the chosen open
   criteria -- each AC corresponds to a closes_criteria ref.
4. **Cross-reference the Freshness Gate.** Before committing, run the Tier Item Freshness Gate
   (below) on the parent item: check if any open criterion is already satisfied by recent work
   (silent-completion check). If so, propose a criterion status flip to `met` as a roadmap
   bookkeeping step before scoping the next slice.

### Status-Trusted-Never-Inferred constraint
`/plan` NEVER flips criterion statuses or item status during planning. Criterion flips happen only
in `/implement`'s bookkeeping walk, on a verified VP pass, for explicitly declared closes_criteria.
See T2.20 lesson. Never infer `met` from prose, file existence, or commit activity.

### closes_criteria field format
Each entry is a string `"<item-id>:<crit-id>"` matching exactly one ExitCriterion in the roadmap:
- `item-id` must be a real tier_item id in the roadmap.
- `crit-id` must be an id within that item's exit_criteria (e.g. `c1`, `c2`, ...).
- `validate.py` enforces referential integrity: a closes_criteria ref to a nonexistent
  item:criterion fails CI (check (iii) in validate_platform_roadmap).

## Platform Roadmap Eligibility (Workflow Step 2)

Broad orientation -- surfacing `next_eligible`, `strategic_pending`, the eligibility summary, the soft-warn exception category list, and ci-rca triage -- is the responsibility of `/orient`. Run `/orient` before `/plan` to choose what to work on; `/plan` assumes a specific item (or ci-rca rec) has already been selected. The orient skill (`.claude/skills/orient/SKILL.md`) holds the full eligibility display and triage rules.

Retained here: the per-item **Tier Item Freshness Gate** (below), which fires at commitment time once intent resolves to a specific tier_item id. `/orient` references that gate; it does not re-author it.

**Soft-warn exception categories** (used by the Tier Item Freshness Gate firing condition): `ci_rca`, `hotfix`, `security_advisory`, `ad_hoc_rec`, `user_explicit_out_of_scope`. When the human's stated intent matches one of these and names no tier_item, the Freshness Gate is skipped. Do NOT reject the session -- issue a soft warning and proceed. Reject only when the intent *claims* tier_item alignment but the referenced id does not exist or its depends_on are not satisfied.

## Clarification (Workflow Step 3)
Decompose the human's input into structured components:
| Component | Question to answer |
|-----------|-------------------|
| **Goal** | What outcome does the human actually want? (not just what they said) |
| **Constraints** | What explicit limits were stated? (time, scope, technology, cost) |
| **Acceptance criteria** | How will the human know when this is done? |
| **Affected areas** | Which files, modules, or infrastructure will be touched? |
| **Phase alignment** | Does this fall within the current roadmap phase? Does it depend on something not yet built? |

If the request is vague or missing key information, ask between 2 and 5 questions -- ranked by impact, no padding questions. Wait for answers before continuing.

## Tier Item Freshness Gate (Workflow Step 3, fires once intent resolves to tier_items)

Firing point: AFTER the Step 3 clarification has mapped the intent to one or more
`tier_items[].id` values, and BEFORE any Step 4 assessment or Step 8 Scope is written. If
the intent matches a soft-warn exception category (ci_rca, hotfix, security_advisory,
ad_hoc_rec, user_explicit_out_of_scope) and names no tier_item, this gate is skipped.
Scope: per-touched-item only -- this gate re-verifies the items THIS session plans against;
it is not a roadmap-wide staleness sweep (that is a periodic audit's job, e.g. the
2026-06-09 platform-roadmap audit).

The roadmap can lag the repo: items go stale when decisions ratify, surfaces move, or
sibling work absorbs their scope (2026-06-09 roadmap audit, findings F-008/F-013/F-016/F-017).
Before scoping ANY tier_item -- whether picked from `next_eligible` or named by the human --
re-verify it against the repo. Eligibility computation alone is NOT sufficient grounds to
plan an item. Run four checks, cheapest first:

1. **Silent-completion check.** Re-adjudicate the item's `exit_criteria[]` against the repo
   (executable criteria via subprocess; prose criteria with the implement skill's conservative
   bias). If ALL criteria already hold, do NOT plan the item -- propose a status closeout
   instead: stage `status: complete` + `completed_at` + a note citing the evidence, present it
   to the human, and on confirmation land it as a small roadmap-bookkeeping commit. Precedent:
   T-1.9 sat `not_started` after its T-1.9 session-log audit deliverable had already landed, and
   a downstream item (T2.15) was citing the deliverable as existing.
2. **Stale-reference check.** Verify every `files_in_scope` path exists or is marked `# new`;
   scan the item's intent/exit_criteria for surfaces or substrates that ratified decisions have
   retired (e.g. the EC2 runner per CD.21/Decision 73, Bedrock per CD.28, SSO per CD.26, direct
   Iceberg/Athena access for tables cut over to the DuckLake closed boundary per CD.31/CD.33/
   Decision 81). A stale reference does not block planning -- but the plan MUST include
   re-grounding the item's text as an explicit Scope row, and the implementation follows the
   CURRENT architecture, never the stale instruction.
3. **Supersession / redundancy check.** Search the roadmap for sibling tier_items or ratified-CD
   amendment notes that have absorbed or superseded the item's scope (`rg` the item's key
   artefacts across `tier_items[]` and `candidate_decisions[]`). Fully absorbed -> propose
   closing the item out (`status: reserved` with a supersession note, preserving the id)
   instead of planning duplicate work. Partial overlap -> the plan names the boundary
   explicitly and cross-references the sibling.
4. **Gating-decision and gate-rule check.** Read the item's `related_candidate_decisions` and
   any `decision_required_before`; check each referenced CD's `state` in the roadmap. If a
   gating CD is pending, surface it: starting is allowed (bootstrap allowance) but COMPLETION
   is gated, and ratification currently transits the ops portal (see the roadmap
   agent_instructions "ratification vehicle" note). Also grep `cross_tier_gates[]` for rules
   naming the item or its tier and adjudicate them by hand (e.g. a grace_period_elapsed window
   that has not elapsed makes an eligible-by-deps item not actually startable -- T5.2/G.10 is
   the canonical case). This manual check stands in for the blocked-on-CD and gate-evaluation
   preflight surfacing until T-1.20 lands.

Output discipline: every closeout or re-grounding this gate proposes is staged as a roadmap
edit in the plan's Scope table (or its own micro-commit on human confirmation) -- never
applied silently, never dropped silently. If the gate finds nothing, say so in one line and
continue. Closeouts replace dead work; they do not become an excuse to skip the human
confirmation gate (Step 6b).

## Suggest Aligned Recommendations
Search `logs/.recommendations-log.jsonl` for open recommendations that align with the current task (ensure cache is fresh via `bin/venv-python -m scripts.sync.ops pull` during preflight):
1. Extract keywords from the task description (file paths, module names, concepts)
2. Match against `title`, `file`, and `context` fields of open recommendations
3. Present top 3-5 matches (if any):
> "These open recommendations may align with your task:
> - **rec-XXX**: [title] (effort: [effort], priority: [priority])
>
> Want to bundle any into this session? Say 'include rec-XXX' or 'skip'."

## Recommendation Relevance Gate (Workflow Step 3, fires before bundling any rec)

Before adding any open recommendation to the plan's `bundled_recommendations` list, re-check
its relevance using `scripts/rec_relevance.py`. Recs can go stale between filing and the
current session (target file deleted, decision ratified, sibling plan already fixed it).

### Protocol
For each candidate rec identified via "Suggest Aligned Recommendations":
```bash
bin/venv-python -c "
from scripts.rec_relevance import evaluate_rec_relevance
import json, pathlib
cache = pathlib.Path('logs/.recommendations-log.jsonl')
rows = [json.loads(l) for l in cache.read_text().splitlines() if l.strip()]
rec = next((r for r in rows if r.get('id') == 'rec-NNNN'), None)
verdict, evidence = evaluate_rec_relevance(rec, run_acceptance_probe=False)
print(verdict, '|', evidence[:120])
"
```

**Verdict handling:**
- **`relevant` or `unknown`** -- proceed; offer to bundle normally.
- **`satisfied`** -- do NOT bundle. Surface the evidence and the proposal command from
  `propose_or_close_rec(rec_id, 'satisfied', evidence, deterministic=False)` (planning time:
  never deterministic). Wait for operator to run the closure command, then proceed without bundling.
- **`superseded`, `duplicate`, `contradicted`, `stale_target`, `blocked_by_decision`** -- do NOT
  bundle. Present the `propose_or_close_rec` output and wait for operator decision. Remove from
  candidate list regardless of outcome.

**Constraints:**
- `run_acceptance_probe=False` is mandatory at planning time (Decision 55: no auto-closure from
  semantic judgment). Acceptance probes run only at `/implement` time.
- Never call `_make_reader()` inside this gate (Decision 88: use read-cache only).

## Documentation Artefact Design

When a plan creates or modifies documentation artefacts, apply these rules:

- Canonical field documentation pattern: ops.yaml extended contract. Add `description`
  and `semantics` metadata fields directly to the column entry in ops.yaml or
  telemetry.yaml. These fields are ignored by the DQ runner and consumed by agents.
  Do not create a separate briefing doc for the same information.
- Decision 86 routing rule -- no new standing prose-architecture docs under docs/:
  route forward intent to tier_items, rationale to Decisions, field semantics to contracts.
  Creating a new docs/INTENT-*.md or any equivalent standing prose-architecture doc is
  forbidden. The validate.py intent-doc-freeze guard enforces this on-disk.
  Existing INTENT docs are grandfathered via docs/intent-migration/MANIFEST.yaml and
  retire as extraction waves complete.

## Infrastructure & Lambda Assessment (Workflow Step 4)
**Infrastructure:** If `.tf` files are in scope, add an "Infrastructure Dependencies table" to the plan. Lambda handlers must accept a `force_{param}` event field. Pre-merge vs Post-deploy timing must be specified.

**Speculative-plan expectations (CD.35 Wave 2 / T2.21, active):** When `.tf` files under `terraform/personal/` are in scope, the plan must account for the speculative-plan pipeline: a PR-time plan is reviewed and saved, then re-applied at merge with no re-plan (Decision 77 no-TOCTOU), gated by the deterministic guard; IAM/trust/destroy diffs route to the human-gated path instead of auto-applying, and a stale saved plan recovers only via the human-reviewed acknowledge-and-retry path (never a silent re-plan-and-apply). `docs/contracts/environment-taxonomy.md` is the sole SoT for the full pipeline mechanics (guard classification, saved-plan persistence, convergence-record shape); tier_item T2.21 tracks the pipeline's own completion. Do not re-derive the mechanics here -- name the required checks and point to that contract.

**Lambda Deployment:** Use the manifest-derived file patterns (`bin/venv-python -m scripts.lambda_manifest --list-patterns`) to determine which scope files are Lambda-packaged, and `compute_affected_artifacts(changed_files)` to identify which active artifact(s) are affected. For each affected active artifact (status: active in its `src/lambdas/<slug>/manifest.yaml`), the plan MUST include per-Lambda build, deploy, smoke-test, and model ID validation steps (V3). Stub artifacts (status: stub) require no deploy step -- V1 suffices. Note: `config/agent/` is NOT Lambda-packaged and does NOT trigger this assessment. If `.tf` modifies IAM, terraform apply must precede Lambda deploy. (CD.16 + Decision 79)

**Deploy channel by artifact class (Decision 125):** consult `docs/contracts/build-lambda.yaml`'s `deploy_channels` section (pointer-only; `docs/contracts/environment-taxonomy.md` section 5 is the sole classification SoT) to determine which channel an affected artifact deploys through:
- **`terraform_personal_filemd5_coupled`** (the four `terraform/personal`-managed DuckLake Lambdas): the plan emits the governed decoupled code-deploy CD channel VP steps -- grep-only / CI-delegated per Decision 119 (name the required CI check or workflow as the authoritative verifier; no local `terraform init`/`plan` for `terraform/personal`). The bare local `bin/venv-python -m scripts.build_lambda --ducklake-only --deploy` invocation is break-glass only (Decision 125) and must never be the default VP step for this class. If the governed channel does not yet exist for the touched artifact, the plan must file a follow-on rec for it rather than defaulting to the local invocation.
- **`decoupled_build_pipeline`** (the `data-pipeline`/`ops-compaction` targets in `src/data/handlers/`): local `bin/venv-python -m scripts.build_lambda --deploy` remains the routine deploy step -- these are not `terraform/personal`-managed, so Decision 125's channel gating does not apply to them.

## Complexity Assessment (Workflow Step 4)
- **Scope files > 5** OR **estimated steps > 8** --> suggests classifying as **STRATEGIC**.
  This is a heuristic, not a hard rule. **Freeze override (active):** while the executor
  freeze is in effect per AGENTS.md Temporary Operational Constraints, the STRATEGIC
  classification is suspended -- author as a single larger IMPLEMENTATION plan, or split
  into multiple atomic IMPLEMENTATION plans during this planning session. The heuristic
  is informational only during freeze.
- If STRATEGIC (only valid when freeze is lifted), Work Areas must have precise lists, clear order, and concrete names.
- If IMPLEMENTATION (and complex), execution steps must have explicit pre/post-conditions.
- **Presentation Rule:** The classification MUST be presented to the human and confirmed, not assumed.
- **SLOC decompose-by-default (Decision 128):** when a scope file's projected change would cross its `config/sloc_budgets.yaml` budget (or past 500 SLOC if currently unregistered), plan the crossing as a decomposition step (facade package, Decision 80/104/124 pattern), not a budget raise. A raise is a deliberate, Decision-cited exception -- do not default to it, and do not plan a bare `--update-sloc-budgets` re-seed as the fix (Decision 128 / B2: it no longer auto-seeds new oversized files).


## Data-Model Assessment (Workflow Step 4)
Conduct this assessment if a table (DDL/schema), a `field_semantics` entry, or a warehouse write path is
in scope. Generalizes Precision Context Injection (Decision 66) to the data-modeling layer -- surface
the standard at design time, before the plan commits to a schema, not as a post-rejection error. Full
rules and the write-mode table live in `docs/contracts/data-modeling-standard.yaml`; AGENTS.md carries
the ambient summary. Walk order:

1. **Grain**: state "one row per ___" in one sentence. If it cannot be stated, the design is not ready
   for the remaining steps.
2. **merge_key + history/current split**: identify the business key the table merges on, and whether
   the table needs a Type-1 current projection alongside its history table (SCD2) or history-only
   (append_only).
3. **Identity**: ULID, minted once at the write boundary -- never client-side, never a natural-key
   primary key.
4. **Join / correlation keys**: identify session/trace FKs and cross-table join keys the new table
   participates in; consult `docs/contracts/_joins.yaml`.
5. **Write mode**: SCD2 (mutable-entity ops tables) vs append_only (insert-once event/telemetry tables)
   -- grain-first, NOT "default to SCD2" (telemetry/event tables are insert-once append_only with no
   SCD2 envelope, Decision 96).
6. **Partitioning** (CD.9): every table is partitioned; name the partition column.
7. **Reject-CRUD checklist**: no in-place UPDATE/DELETE as the default write path, no
   one-row-per-entity mutation model, a read cache is never a write source (AGENTS.md
   Warehouse-as-source-of-truth invariant).
8. **Fable escalation**: for load-bearing/novel calls only -- a NEW table, a NEW identity scheme, or a
   `merge_key` change -- dispatch a `model:"fable"` advice-consult per the `overseer` skill's Fable
   Advice-Consult Protocol before committing the design. Routine, already-settled calls (an additional
   column on an existing SCD2 table, a grain that matches an existing sibling table) do not need
   escalation.

**Framing reminder**: append-only/SCD2 as a family is the design default/prior, explicitly NOT a ban on
sanctioned exceptional physical deletes (Decision 70) or lifecycle-closure paths (Decision 103).


## Main Divergence Assessment (Workflow Step 4)
After Scope is identified, intersect the prospective Scope file list with `main_freshness.main_files_changed_since_branch` from the preflight report. If any Scope file appears in that list:

> "Main has changed [list of overlapping files] since this branch diverged. Planning against the stale branch view risks decisions that conflict with what is already on main (e.g., a Decision Record you cite has been amended, a tier_item you target has been retired). Recommend rebasing BEFORE writing the plan: `git fetch origin main && git rebase origin/main`. Options: (1) rebase now and re-enter `/plan`, (2) proceed and accept the risk, (3) abort."

**Rebase phase distinction (assessment time)**: do NOT auto-rebase here. This is the assessment-time rule -- surface the divergence, wait for the human's choice. Auto-rebase happens only at commit-flow time (the Pre-Push Rebase step in the implement skill), NOT here. See AGENTS.md `## Git-ops procedure` as the canonical git-ops authority for the full rebase phase distinction.

If the human chooses (2), record the deferral as a line in the plan's Context section: "Branch was N commits behind main at planning time; overlapping files: [list]. Rebase deferred per human decision."

If `main_freshness.status != "ok"`, this assessment cannot run -- note in the plan's Context section and continue.

## Verification Tier Guidelines (Workflow Step 5)
Classify deterministically. Highest tier wins.
- **V1 (Static):** Docs, configs, markdown.
- **V2 (Unit):** Python source with no external integration. Must exercise real code paths.
- **V3 (Integration):** External systems, Terraform, Lambdas. Must tag steps as `[pre-deploy]` or `[post-deploy]`.

**Provider-init egress (terraform roots only):** a terraform root using a third-party
(github.com-hosted) provider (e.g. `kislerdm/neon` in `terraform/personal`) cannot `terraform
init`/`validate`/`plan` from a stock CC-web session -- the outbound proxy blocks the provider's
github.com checksum fetch. Author local terraform VP steps as grep-only, plus `terraform fmt
-check` ONLY when terraform is present (fmt needs no provider install); delegate `terraform
validate`/`plan` to CI -- name the required `terraform-validate` check and the speculative-plan job
as the authoritative verifiers, never a local `terraform validate`/`init`/`plan` invocation. See
`terraform/CLAUDE.md` and Decision 119 for the constraint and CI-delegation contract.

**VP Design Rationale:**
When writing Verification Plan steps, ask: "If this feature had a subtle bug (wrong column name, missing permission, off-by-one filter), would this step catch it?" If no, the step is too shallow.

**Anti-patterns to reject:**
- Structural-only: `grep -q "def my_function" src/module.py` -- proves existence, not function
- Test-only: "Run pytest" -- proves mocked paths work, not the real integration
- Existence-only: "Confirm the Athena view was created" -- does not confirm it returns correct data
- Import-only: "Confirm `import module` succeeds" -- loading without error is not verification
- Terraform-only: "Confirm `terraform apply` succeeded" -- infrastructure existing is not enough
- Prose-only VP step: VP step describes what to check but has no executable command -- the implement agent will substitute a weaker check

**Hermetic authoring (T3.15 / VF-01):** author `pre-deploy` VP steps hermetic where possible --
narrow, deterministic, creds-free commands with no network or AWS calls -- and mark them
`hermetic: true`. The `validate_vp_replay` check (`--pre` tier) independently re-executes every
`phase: pre-deploy` + `hermetic: true` step of a diff-added/modified PLAN-*.yaml, so a hermetic
pre-deploy step that fails on the PR tree cannot go green on self-report alone -- this is the
independent re-execution of the per-change proof named in VF-01 /
`docs/INTENT-verification-system.md`. Never mark a step hermetic if its command transitively
invokes `scripts/validate.py --pre` or the full check sequence -- the replay would recurse into
itself. Steps that must invoke pytest, deploy infrastructure, or otherwise cannot run hermetically
stay `hermetic: false` (the default) and are excluded from replay with a printed reason, not
silently skipped.

**Graduation disposition authoring (T3.21, enforced VF-05):** every `phase: pre-deploy` VP step
must carry a `graduation` field -- one of `graduate`, `waive`, or `not-applicable`.
`validate_graduation_completeness`'s plan-PR leg (`--pre` and full tiers) fails a diff-added or
diff-modified `PLAN-*.yaml` that leaves any pre-deploy step's disposition unset (see the
implement skill's Bundled Recommendation Relevance Re-check-adjacent "Verification Graduation"
section for what happens with each disposition at implement time). Classify each pre-deploy step
at plan-authoring time:
- **`graduate`** -- the step's command is expressible as one of the six canonical primitive
  slots in `scripts.verification_checks.CANONICAL_SLOTS` (command_exit_zero,
  command_output_matches, file_presence, grep_count, test_selector, metric_under_threshold) AND
  is hermetic-or-cheap enough to run as a standing regression guard. Requires
  `graduation_check_id`: a stable, human-readable slug (e.g. `"kernel-slot-count-eq-6"`,
  matching the registry's `check_id` convention) that the implementing session will use verbatim
  as the registry row's identity -- pick it now so the plan-implement-registry linkage is fixed
  at plan time, not improvised later.
- **`waive`** -- the step is kernel-expressible in principle but graduating it now is
  impractical (e.g. it depends on this session's transient repo state, or duplicates an
  already-graduated check). Requires `graduation_waiver_reason`: a substantive, specific reason
  (not "not needed" or "skip") -- the plan-critique gate reviews this reason for honesty.
- **`not-applicable`** -- the step is NOT kernel-expressible: it requires multiple commands,
  human/LLM judgement, live infrastructure (a V3 deploy/invoke), or wall-clock/credential state.
  No extra field required.

Classification is a judgement call with a known non-deterministic seam (a command's
kernel-expressibility is not mechanically decidable in general) -- the plan-critique gate is the
honesty check on this call, applied before the fix exists (so there is no pressure to wave
through a finished implementation). When genuinely unsure between `graduate` and
`not-applicable`, prefer `not-applicable` and let plan-critique push back if it disagrees --
a false `not-applicable` is a missed regression guard; a false `graduate` becomes a mandatory
`waive`-with-reason detour at implement time (harmless, but adds a step).

## Candidate Decision Ratification (Workflow Step 5b, when the plan realizes/ratifies a CD)

Fires when the plan's scope realizes the work a pending `candidate_decision` (CD.NN) gates, OR the
CD was surfaced by `/orient`'s "Ratifiable CDs" subsection (`platform_roadmap.ratifiable_cds` --
pending CDs carrying `realization_evidence`). Ratification is a first-class lane shared across
`/orient` (surface), `/plan` (draft, this section), and `/implement` (execute) -- see
`docs/contracts/candidate-decision-ratification.yaml` for the canonical shape and referential guard
this drafting step must satisfy.

**Protocol:**
1. Confirm the CD's `realization_evidence` (or equivalent corroborating evidence gathered this
   session) actually establishes the gated work is realized/live -- do not draft a ratification for
   a forward-intent CD (Decision 55: no unilateral judgement calls; a CD with no realization
   evidence is not a ratification candidate, full stop).
2. Add a **ratification block** to the plan (own section, distinct from `scope`/`execution_steps`)
   containing:
   - The full drafted Decision text (title, body, any amendments to other Decisions/CDs it
     narrows or supersedes) -- including explicit **reversal conditions** if the ratified state
     could later be undone (e.g. a swap-back to a prior architecture). A ratification with no
     reversal conditions when the realized state is reversible is incomplete.
   - The exact `bin/venv-python -m scripts.ops_data_portal --backfill-decisions-md` (or
     `--file-decision` single-row alternative) command sequence /implement will run.
   - The exact roadmap-flip diff: `state: ratified` + `ratified_as: dec-NNN` + `filed_via:
     ops_decisions:dec-NNN` (canonical shape; same NNN in both fields) on the target CD entry.
3. This is a DRAFT only. Do not run the portal write or the roadmap flip during `/plan` --
   Decision 105 / the plan's own constraints reserve execution for `/implement` behind an
   execution-time human confirmation gate. Planning-time writes here would make the Step 6b
   confirmation gate meaningless (the write would already be done before the human signs off).
4. The Step 6b Confirmation Gate (below) and the Critique Gate (Workflow Step 9) ARE the human
   sign-off on the drafted Decision text -- do not add a separate approval step. If Decision-Scout
   (Step 6a) flags a contradiction with the drafted text, resolve it before presenting.

**Numbering-race note:** decision numbers are not reserved at draft time. Re-check the current max
`## Decision NNN:` header in `docs/DECISIONS.md` at `/implement` execution time -- a concurrent PR
may have claimed the drafted number. The referential guard (`validate_candidate_decision_ratification`)
catches any resulting header mismatch, so shifting to the next free number at execution time is safe.

## Decision Scout Gate (Workflow Step 6a, pre-presentation)

This gate fires BEFORE Step 6b's presentation to the human. Its job is to surface any active decisions the proposed approach must cite, contradict, or pivot around -- without paying the cost of loading the full DECISIONS.md (large -- near its Decision 134 size ceiling) into the planning agent.

**Example prompt body:**
> "You are running the decision-scout gate in a fresh context window. Invoke the `decision-scout` skill via the Skill tool. The skill needs the following inputs (use them in your scout analysis):
> - Intent: [1-2 sentences from clarification]
> - Proposed approach: [paragraph synthesis]
> - Scope files: [list from Step 4]
> - Verification Tier: [V1 | V2 | V3]
> - Explicitly cited decisions: [list of IDs the human mentioned, or 'none']
>
> Return the skill's `## Decision Scout Report` output verbatim, including the final `Verdict:` line. Do not edit any files."

**Dispatch shape:**
- `subagent_type: "general-purpose"` (needs `Skill`, `Read` access)
- `description: "Decision scout gate"`
- `prompt:` a self-contained brief per the example above, supplying Intent (Step 3), Proposed approach (Steps 3-5 synthesis), Scope file list (Step 4), Verification Tier (Step 5), and any decision IDs already cited by the human. Instruct the subagent to invoke the `decision-scout` skill via the `Skill` tool and return the structured `## Decision Scout Report` output verbatim.

**Verdict handling:**
- **NO_FLAGS** -> Proceed to Step 6b. Include the scout's CITE list in the presentation as "Decisions this plan must reference." Record in the plan template's `context:` list: "Decision-scout verdict + CITE list (verbatim decision ids)" and "gates: decision-scout=<verdict>; plan-critique=<verdict> after <N> round(s))".
- **FLAGS_FOUND** -> Surface each WARN/NOTE flag to the human in Step 6b's presentation under a "Decision Flags" section. Human chooses per-flag: pivot, defer with note, or accept-as-is. If the human pivots on any flag in a way that changes the proposed approach materially, re-dispatch this gate against the revised approach before re-presenting.
- **BLOCK** -> STOP. Do NOT present the original approach for confirmation. Surface the BLOCK contradiction and propose pivots, then re-dispatch the gate against the revised approach. Confirming a known-blocking approach would invite the human to ratify a plan that contradicts an active decision.
- **Gate-error:** if the gate subagent errors or returns output missing the required `Verdict:` line, the gate has NOT completed -- re-dispatch; never proceed past an incomplete gate. Likewise, if the report's "Decisions triaged: N of M" line is missing, or N != M, treat the gate as incomplete and re-dispatch -- a mismatch means the scout truncated its read of DECISIONS.md.

**Why a subagent and not inline grep, and the Lambda migration contract:** see the `decision-scout` skill -- it owns the isolation rationale and the stable-interface contract for when DECISIONS.md is replaced by a Lambda-backed tool query.

**Convergence rule:**
Do not loop more than 3 times. If the gate keeps returning BLOCK after 3 revisions, escalate to the human: "After N revisions the decision-scout still flags BLOCK on [decision N]. Continued pivoting suggests either the underlying intent contradicts the decision (re-scope the request) or the decision needs to be revisited (file a recommendation to revise the decision). How would you like to proceed?"

## Confirmation Gate (Workflow Step 6b)
Wait for explicit 'write the plan' (or clear equivalent) before proceeding. Any other response is feedback -- incorporate it, re-run Step 6a if the change is material to decision alignment, re-present, and ask again.
IT IS **CRITICAL** THAT YOU DO NOT PROCEED UNTIL THE HUMAN CONFIRMS THE PLAN.

## Create Branch (Workflow Step 7)
See AGENTS.md `## Git-ops procedure` as the canonical git-ops authority for branching topology (DEV vs ADMIN containers, AWS profiles, harness branch vs never agent/).

Verify you are on the harness branch and not on `main`:
```bash
git branch --show-current
```
If the result is `main`, STOP.

Derive the plan slug from the task description (independent of the branch name). The plan filename is `docs/plans/PLAN-{slug}.yaml` (schema-validated by `scripts/roadmap/plan_document.py`; the legacy `PLAN-{slug}.md` form is DEPRECATED per T1.11 / CD.22 -- never author new .md plans; tooling warns on the .md path for one release cycle, then it is removed). After writing and approving the plan, it is merged to `main` via a GitHub MCP PR so a fresh `/implement` session can read it by explicit path.

## PLAN-{slug}.yaml Template (Workflow Step 8)
The plan is a YAML document validated against the `PlanDocument` Pydantic schema (`scripts/roadmap/plan_document.py`, enforced by `validate.py` in both tiers). Unknown keys FAIL validation (`extra="forbid"`). Use exactly this structure -- comments document field semantics:
```yaml
schema_version: 1                  # int; must be 1
slug: "{slug}"                     # must match the filename PLAN-{slug}.yaml
intent: >-                         # 1-2 sentences: how this work contributes toward the North Star
  ...
plan_type: IMPLEMENTATION          # IMPLEMENTATION | STRATEGIC | REPORT-ONLY
verification_tier: V2              # V1 | V2 | V3
plan_path: docs/plans/PLAN-{slug}.yaml   # must equal docs/plans/PLAN-{slug}.yaml (slug consistency)
phase: >-                          # product phase from docs/ROADMAP-PRODUCT.yaml and/or platform tier_item id
  ...
scope:                             # min 1 entry; only files listed here may be modified
  - file: path/to/file.py
    action: Create                 # Create | Modify | Delete
    purpose: why this file changes
bundled_recommendations: []        # included open recs (list of str), or []
infrastructure_dependencies: []    # list of str; populate when .tf files appear in scope
acceptance_criteria:               # min 1; each independently verifiable
  - verifiable condition 1
verification_plan:                 # min 1 step; step ids must be unique
  - step: 1
    phase: pre-deploy              # pre-deploy | post-deploy
    action: exercise the feature
    command: executable shell command   # REQUIRED non-empty -- prose-only VP steps fail the schema
    expected: specific expected result
    fix_if: what failure looks like
constraints:
  - limits from docs/PROJECT_CONTEXT.md and DECISIONS.md
  - No rescue agents or workaround loops (Decision 55)
context:
  - Relevant decisions, phase dependencies, known gotchas
  - "Decision-scout verdict + CITE list (verbatim decision ids)"                  # REQUIRED ITEM (WF-04a)
  - "gates: decision-scout=<verdict>; plan-critique=<verdict> after <N> round(s)" # REQUIRED ITEM (WF-08)
pre_implementation_checklist:
  - Branch confirmed not on main
  - docs/PROJECT_CONTEXT.md read
  - DECISIONS.md read
  - All files in scope located and readable
  - Acceptance criteria understood and verifiable
execution_steps:                   # REQUIRED non-empty for IMPLEMENTATION plans
  - Specific file to create/modify -- what it must do
  - Execute Verification Plan -- run each step; loop until pass; on unrecoverable V3 failure stop and RCA (Decision 55)
  - 'Report: what was implemented, verification results'
work_areas: []                     # STRATEGIC plans only (required there, forbidden otherwise);
                                   # entry shape: {area, scope, rationale, complexity: XS|S|M|L|XL}
rollback: optional rollback note   # optional str; omit if not applicable
```

After writing, validate before committing:
```bash
bin/venv-python -m scripts.roadmap.plan_document docs/plans/PLAN-{slug}.yaml
```

**Platform compatibility:** Verify shell commands are Linux/bash-compatible and use `bin/venv-python` for Python invocations.

## Related-Work Check (Workflow Step 8, when ci-rca recs are open)

If `ci_rca_unresolved_recs` is non-empty when writing the PLAN file (or `ci_rca_recs` if the report predates the correlation field), confirm the plan satisfies at least one of the following conditions before committing. A plan failing all three must include a logged deferral rationale in its Context section; otherwise write is refused.

1. **Same file**: the plan's Scope table includes the same file the ci-rca rec cites as `source_file`.
2. **Same Decision Record**: the plan addresses the same Decision Record the ci-rca rec references (if any).
3. **Same failure category**: the plan addresses the same failure category as the rec. Canonical categories: DQ check failure, schema verifier failure, validate.py false negative, terraform validate failure, pytest regression, mypy regression, prompt-compliance failure, V3 harness failure.

## Closure Obligation (Workflow Step 8, CONDITIONAL)

Apply this check when writing the PLAN file. It is CONDITIONAL -- additive plans that neither resolve recs nor retire a surface are exempt.

**Trigger conditions (either/both):**
1. **Rec-resolving plan**: the plan's scope or intent explicitly fixes one or more open recommendations. The plan MUST declare them in `bundled_recommendations` AND include a VP step that verifies each rec closed (e.g. grep the local cache after sync).
2. **Surface-retiring plan**: the plan's scope includes a `Delete` row OR an explicit `X -> Y` migration/cutover (file, Lambda, write path, config flag, or backend). The plan MUST include a stale-reference sweep VP step that confirms the old surface is unreachable or deleted.

**Enforcement:** a plan that meets a trigger condition but omits its closure obligation fails the plan-critique gate (see `plan-critique` skill, closure-obligation criterion). Surface the violation during Step 6 presentation and require the plan author to add the missing declaration or VP step before writing is allowed.

## Critique Gate (Workflow Step 9)
**DO NOT output the completion message until this step completes.**

Launch a zero-context Claude subagent via the `Agent` tool to run the `plan-critique` skill in a fresh context window. The fresh-context requirement is non-negotiable: it eliminates the cognitive bias the planning agent has from authoring the artefact. Do NOT invoke the `plan-critique` skill in the current session via the `Skill` tool (same context = same bias). Do not use `scripts.agent_development.run_skill` -- it is broken per rec-568; dispatch the gate via the `Agent` tool + `Skill` instead.

**Invocation shape:**
- `subagent_type: "general-purpose"` (needs `Skill`, `Read`, and `Grep` access)
- `description: "Plan critique gate"`
- `prompt:` self-contained, mentions:
  - The absolute path to `docs/plans/PLAN-{slug}.yaml` (a `.md` path is deprecated -- surface a deprecation warning and proceed)
  - Instruction to invoke the `plan-critique` skill via the `Skill` tool against that path
  - The skill's required-context files per its frontmatter (`docs/PROJECT_CONTEXT.md` full read; `docs/ROADMAP-PRODUCT.yaml`/`docs/ROADMAP-PLATFORM.yaml`/`docs/DECISIONS.md` targeted, not full-file -- see the `plan-critique` skill's Phase 1)
  - For IMPLEMENTATION plans: instruction to also read every file in the plan's Scope table
  - Requirement to return the skill's structured output verbatim, including the final `Recommendation: PROCEED / REVISE` line
  - Forbid file edits

**Example prompt body:**
> "You are running the plan-critique gate in a fresh context window. **First, run `git fetch origin main --quiet`** so the local `origin/main` ref is current. Then invoke the `plan-critique` skill via the Skill tool to critique `/abs/path/to/docs/plans/PLAN-{slug}.yaml`. Read `docs/PROJECT_CONTEXT.md` in full; extract only the roadmap items and decision sections the plan names per the skill's Phase 1 (do not load full ROADMAP-PLATFORM.yaml/ROADMAP-PRODUCT.yaml/DECISIONS.md). For IMPLEMENTATION plans, also read every file in the plan's Scope table. If `git diff origin/main -- docs/DECISIONS.md docs/ROADMAP-PLATFORM.yaml` shows divergence, note that the critique evaluates against the branch's (possibly stale) view of these docs. Return the skill's structured critique output verbatim, including the final `Recommendation:` verdict line. Do not edit any files."

Read the critique output returned by the subagent.
If it suggests revisions, update the plan with these fixes and re-launch the same subagent invocation against the revised plan. Each Agent call is a fresh window, so the re-launch genuinely re-evaluates.
Loop if REVISE. Proceed if PROCEED.
If the gate subagent errors or returns output missing the required `Recommendation:` line, the gate has NOT completed -- re-dispatch; never proceed past an incomplete gate.

Convergence rule: after 3 REVISE rounds, escalate to the human with the unresolved findings and options (accept-with-deferral / re-scope / abandon), mirroring the Step 6a decision-scout convergence rule.

This gate reviews the PLAN artefact, not the report deliverable. For REPORT-ONLY plans, the deliverable gets its own critique in Step 10.

## Report Critique Gate (Workflow Step 10, REPORT-ONLY only)

**Applies only when Plan Type is REPORT-ONLY.** For IMPLEMENTATION and STRATEGIC plans, Step 10 is a no-op; skip to Step 11.

**Why this gate exists:** the Step 9 `plan-critique` skill reviews the planning artefact (`PLAN-{slug}.yaml`) -- it checks that the PLAN is well-formed, has executable verification steps, aligns with decisions, etc. But for REPORT-ONLY plans, the substantive deliverable is a SEPARATE document (e.g. `docs/INTENT-{slug}.md`, `docs/REPORT-{slug}.md`) referenced from the PLAN's Scope table. That deliverable carries its own correctness burden -- design soundness, internal consistency, alignment with live repo state, blast radius of any proposed changes -- and needs independent fresh-context critique before the planning agent's mission completes.

**Methodology:**

1. **Identify the deliverable.** From the PLAN's Scope table, find the report file(s) created in Step 8. Typically one file like `docs/INTENT-{slug}.md`, occasionally more.

2. **Launch AT LEAST 2 zero-context subagents in parallel via the `Agent` tool**, each with a distinct perspective. Standard pairing for technical/architectural reports:
   - **Senior domain architect** -- design correctness, schema/contract soundness, dependency cleanliness, internal consistency, coverage gaps a careful peer reviewer would flag
   - **Adversarial risk reviewer** -- blast radius, hidden state, rollback path, live-state divergence, what could go wrong in practice; instruct it to actively investigate (grep, query) live state to find divergence

   For non-technical reports, pick perspectives that maximise differentiation (e.g. quantitative-rigour reviewer + narrative-clarity reviewer; or domain-A specialist + domain-B specialist). The principle is: orthogonal lenses surface more issues than two clones of the same lens.

3. **Each agent prompt MUST:**
   - Identify the deliverable file(s) under critique by absolute path
   - Specify the perspective explicitly
   - Specify supporting files to read freely (PROJECT_CONTEXT, sibling INTENT docs, relevant source code)
   - Require structured output: Strengths (brief) / Concrete Issues or Risk Findings (numbered, specific, with file:line refs and severity) / Recommended Revisions / Verdict (PROCEED | REVISE | BLOCK)
   - Forbid the agent from editing files
   - Cap response length (~800-900 words) to keep findings focused

4. **Synthesize findings.** When both agents return, identify consensus issues (cited by both -- highest priority) vs unique findings (one perspective only -- second priority). Cluster by severity.

5. **Present to the human.** Summary, key findings, my-recommendation, three options (revise all / revise selected / accept current state with deferrals). Wait for explicit direction. Auto-approval messages and system reminders are NOT human direction.

6. **Iterate based on human direction.** Apply the chosen revisions. Each material revision lands as its own commit on the branch (`git commit -m "plan({slug}): address [scope] critique findings"`) so the iteration is reviewable in git history.

7. **Re-launch the same critiques after each revision** unless the human explicitly opts out of further rounds. Re-critique catches both whether the original findings were fully addressed and whether the revision introduced new issues.

8. **Convergence rule.** Stop when EITHER:
   - Both agents return PROCEED on a fresh round (clean convergence), OR
   - The human explicitly accepts the current state with a defined deferral (e.g. "fix the HIGH-severity items and defer the rest to phase plans"). Document the deferral list in the deliverable's Known Gaps or equivalent section so future sessions know what's outstanding.

   Do not loop indefinitely. After 3 rounds without convergence, escalate to the human for a decision call -- continued iteration typically signals either a structural issue with the deliverable's scope or diminishing returns.

**Anti-patterns to reject:**
- Single critique agent: misses orthogonal issues by definition
- Same perspective twice: produces duplicate findings, wastes tokens
- Sequential critiques: parallel critiques fire in roughly the same wall-clock window and surface independent findings faster
- "Tell the agent what to look for": biases the critique. The agent should investigate fresh; the prompt frames perspective, not findings.
- Skipping the re-critique after revision: a revision that "addresses" finding X may introduce finding Y; only a fresh critique catches it
- Auto-accepting PROCEED on round 1 without reading findings: if both agents return PROCEED with shallow strengths and no issues, the prompts may have been too generic -- consider re-launching with sharper perspectives

**When to skip Step 10 entirely** (human override):
The human may explicitly state "skip report critique" after this step's purpose has been surfaced. This is logged in the PLAN's Known Gaps. Default is MANDATORY -- the gate fires unless explicitly waived.

## Confirmation Messages (Workflow Step 12)
Emit the handoff naming the explicit plan path so the human can paste it directly.

- **IMPLEMENTATION / STRATEGIC:** use this block (STRATEGIC scopes into recs; IMPLEMENTATION executes directly):
  ```
  Planning complete. The plan is merged to main at docs/plans/PLAN-{slug}.yaml.
  To implement, open a NEW Claude Code session and paste:

      /implement docs/plans/PLAN-{slug}.yaml

  Summary: {one line on what the plan does}.
  ```
- **REPORT-ONLY:** "Planning complete. The report deliverable at `[path]` has passed the multi-perspective critique gate and is merged to `main`. Review and edit if needed. The deliverable is the substantive output -- no `/implement` required. Decide which follow-on items (e.g. per-phase implementation plans referenced from the deliverable) to start, then open a new planning session for each."

**DO NOT PERFORM ANY FURTHER ACTIONS**
