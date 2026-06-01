# Plan

## Intent

Land the verification/validation infrastructure into the platform roadmap so it is in place BEFORE the autonomous executor (T4) is built in earnest. Formalises the validation suite as a graduated, deduplicated, machine-curated asset and fixes how per-rec verification relates to repo-wide validation -- contributing to the autonomy North Star by making "every verification stays confirmed" a scalable guarantee rather than an unscalable re-run-everything promise.

## Plan Type

REPORT-ONLY

The substantive deliverable is the set of edits to `docs/ROADMAP-PLATFORM.yaml` (two new candidate decisions, two new tier items, an expanded T3.1, an amended T0.12.5, a CD.17 sequencing note, and a new known_gap). This PLAN file is the planning artefact pointing at those edits, per the planning-skill template and the `PLAN-executor-pivot-stepfn-durable-deepseek` precedent. No source code changes land here -- the verifier / mutation / registry / dead-test CODE lands in follow-on IMPLEMENTATION plans that the new tier_items describe.

## Verification Tier

V1

Static YAML only. Structural validation via `scripts/platform_roadmap.RoadmapDocument` Pydantic schema (exercised by `scripts/validate.py`). Substantive correctness via the Step 9 plan-critique fresh-context gate and the Step 10 multi-perspective deliverable critique (architect lens + adversarial lens in parallel).

## Plan Path

docs/plans/PLAN-verification-validation-roadmap.md

## Phase

Platform tier T3 (trust loop closure) + the T0.12.5 ops-contract ratification and the executor-facing `checks` field. Relates to T4 (executor) as a sequenced precondition. Does NOT advance any tier_item to `complete`; it adds/expands the tier_items future T3.x and T4.x atomic plans implement against.

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `docs/ROADMAP-PLATFORM.yaml` | Modify | Add CD.29 (validation-suite-as-graduated-asset model) + CD.30 (diff-coverage ratchet supersedes 100%-global). Expand T3.1 (typed checks kernel + graduation registry Class C contract + differential admission gate + hermeticity dependency). Add T3.6 (test-suite hermeticity audit) + T3.7 (meta-validation: mutation testing + deterministic dead-test detection + diff-coverage ratchet). Amend T0.12.5 (consolidate `acceptance`+`verification` into a single typed hard-gated `checks` field, folded into the ops_recommendations Class A contract ratification). Add CD.17 sequencing note (new T3 items precede but do not gate the reversal trigger). Add KG.13 (TIA + caching deferred to scale). |
| `docs/plans/PLAN-verification-validation-roadmap.md` | Create | This planning artefact. |

## Bundled Recommendations

None bundled. This is a roadmap-architecture change, not a rec implementation. The CODE that the new/expanded tier_items describe is filed via separate `/plan` sessions or `file_rec` after this lands.

## Infrastructure Dependencies

None for this plan. No `.tf` files in scope. The new tier_items describe future infrastructure (a GitHub Actions meta-validation workflow, the verifier harness, the graduation registry), but those land in subsequent atomic IMPLEMENTATION plans -- each independently subject to CD.16 per-Lambda gating + Decision 67 deferred-deployment markers where applicable. Note T3.7's meta-validation runner is explicitly a GitHub Actions schedule, NOT a Lambda, precisely to avoid the Decision 67 / CD.16 Lambda-deploy freeze.

## Acceptance Criteria

- [ ] `docs/ROADMAP-PLATFORM.yaml` validates against `scripts/platform_roadmap.RoadmapDocument` with no errors.
- [ ] CD.29 and CD.30 present in `candidate_decisions[]` with required fields; all their `gates` resolve to existing tier_items.
- [ ] CD.30 carries `narrowly_supersedes.decision_id: 48` (the 100%-coverage V2-tier minimum).
- [ ] T3.6 and T3.7 present in `tier_items[]` with resolvable `depends_on`; T3.1 `depends_on` includes T3.6.
- [ ] T3.1 expanded with the typed checks kernel, graduation registry (Class C contract reference), differential admission gate, and hermeticity dependency in intent + exit_criteria.
- [ ] T0.12.5 intent + exit_criteria amended for the single typed `checks` field; `related_candidate_decisions` includes CD.29.
- [ ] CD.17 detail carries the sequencing note (T3.6/T3.7/expanded-T3.1 precede but do not gate the reversal trigger); the trigger expression is structurally unchanged.
- [ ] KG.13 present in `known_gaps[]`.
- [ ] Step 9 plan-critique returns `Recommendation: PROCEED` on this PLAN artefact.
- [ ] Step 10 multi-perspective deliverable critique converges (architect + adversarial lenses PROCEED on a fresh round, OR human explicitly accepts current state with documented deferrals).

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | Validate roadmap structure | `bin/venv-python -m scripts.platform_roadmap` | `PASS: docs/ROADMAP-PLATFORM.yaml validates against RoadmapDocument schema.` | Schema error names the malformed field; correct and re-run |
| 2 | [pre-deploy] | Confirm CD.29 + CD.30 present and gates resolve | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8')); cds={c['id']:c for c in d['candidate_decisions']}; tis={t['id'] for t in d['tier_items']}; assert {'CD.29','CD.30'} <= set(cds); [None for cid in ['CD.29','CD.30'] for g in cds[cid]['gates'] if (g in tis or (_ for _ in ()).throw(AssertionError(g)))]; print('OK')"` | Prints `OK` | Add missing CD or fix a dangling gate reference |
| 3 | [pre-deploy] | Confirm T3.6/T3.7 present + T3.1->T3.6 dependency | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8')); tis={t['id']:t for t in d['tier_items']}; assert 'T3.6' in tis and 'T3.7' in tis; assert 'T3.6' in tis['T3.1']['depends_on']; print('OK')"` | Prints `OK` | Add the missing tier_item or the T3.1 dependency |
| 4 | [pre-deploy] | Confirm CD.30 supersession lineage on Decision 48 | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8')); cds={c['id']:c for c in d['candidate_decisions']}; assert cds['CD.30']['narrowly_supersedes']['decision_id']==48; print('OK')"` | Prints `OK` | Add/repair `narrowly_supersedes` on CD.30 |
| 5 | [pre-deploy] | Confirm T0.12.5 `checks`-field amendment | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/ROADMAP-PLATFORM.yaml',encoding='utf-8')); t=[x for x in d['tier_items'] if x['id']=='T0.12.5'][0]; assert 'CD.29' in t['related_candidate_decisions']; assert any('checks' in c for c in t['exit_criteria']); print('OK')"` | Prints `OK` | Amend T0.12.5 intent/exit_criteria + related_candidate_decisions |
| 6 | [pre-deploy] | Fast presubmit (lint/format/prompts + schema) | `bin/venv-python -m scripts.validate --pre` | Passes with no schema or prompt-compliance errors | Address the named failure and re-run |
| 7 | [pre-deploy] | Step 9 plan-critique gate (fresh-context Agent subagent) | (Dispatched via Agent tool; invokes `plan-critique` skill) | `Recommendation: PROCEED` | Address REVISE findings; re-dispatch until PROCEED |
| 8 | [pre-deploy] | Step 10 multi-perspective deliverable critique (two parallel Agent subagents -- architect + adversarial) | (Dispatched via Agent tool, two parallel calls) | Both verdicts PROCEED on a fresh round, OR human accepts with documented deferrals | Apply revisions per human direction; re-dispatch until convergence |

## Constraints

- AGENTS.md Temporary Operational Constraints: STRATEGIC plans suspended -- this plan is REPORT-ONLY (not STRATEGIC). The new/expanded tier_items (incl. T3.1 at effort L) are authored as IMPLEMENTATION and decompose into atomic IMPLEMENTATION plans at /implement time. Lambda-deploy freeze (Decision 67 / CD.16): this plan touches no Lambda-packaged file, and T3.7's runner is a GitHub Actions schedule (not a Lambda) by design.
- CLAUDE.md Branching hard rule: no edits while on `main`; this plan executes on `claude/deepseek-lambda-agent-tools-PP5Es`.
- CD.13 (agent-first machine-parseable artefacts): the new contract is YAML (`docs/contracts/verification-registry.yaml`, Class C per CD.25); roadmap edits stay structured.
- Decision 55 (RCA-first): deterministic gates only; the `quarantine` flake state and `source='mutation_survivor'` recs file recs rather than auto-retrying or auto-fixing. No rescue agents or workaround loops.
- CD.12 mark-then-drop: test/check retirement deprecates in the registry; a follow-on plan deletes. Never auto-delete, never an LLM scan.
- Single Portal Invariant: no edits to `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl`.

## Context

- **Why now**: T4.1 (executor substrate) already `depends_on [T2.1, T3.2]`, so the roadmap already sequences verification before the executor. This plan deepens T3.1 (currently too thin -- it has the verifier harness + the same-PR anti-gaming guard but lacks the graduation lifecycle, hermeticity, meta-validation, and TIA story discussed). T3.1 is `strategic: false`, so the verification foundation is buildable NOW under the freeze, unlike T4.2.
- **Decision-scout gate (FLAGS_FOUND) -- findings incorporated**:
  - CD.17 [WARN]: trigger expression left structurally unchanged; a sequencing note records that new T3 items precede but do not gate the reversal. (Human chose note-only over adding T3.6 to CD.17.gates.)
  - Decision 48 [WARN]: the 100%-coverage gate is Decision 48's V2-tier minimum, not just a validate.py mechanism. CD.30 names Decision 48 in `narrowly_supersedes` and the detail references Decision 60/73 for the unchanged two-tier structure.
  - CD.12 [NOTE]: CD.29 + T3.1 state the `checks` kernel is its own closed vocabulary, orthogonal to the CD.12 DQ markers, extendable only by a new CD.
  - Decision 62 [RELATED-tension]: T3.7 explicitly distinguishes its scheduled GH Actions workflow from the separate-scheduled-DQ-routine Decision 62 retired (mutation is too slow for presubmit + alarm-not-gate, not a merge gate).
  - Decision 61: `source='mutation_survivor'` reuses the source-field findings channel; no new findings table.
  - Decision 73: KG.13 cross-references the existing testmon upgrade note.
  - Decisions to cite: CD.12, CD.25, CD.16 + Decision 67, Decision 55, CD.27, CD.17, Decision 48/60/73, Decision 61. CD.28 demoted to awareness-only (no inference change).
- **Conceptual mapping affirmed**: roadmap "verifiers" (T3.1, in validate.py + postflight) = the cumulative VALIDATION; the executor's per-rec `acceptance`/`verification` (step_runner) = per-rec VERIFICATION. The two are distinct questions; neither subsumes the other. T3.1's same-PR guard is the anti-gaming integrity boundary.
- **Main divergence**: this planning agent did not run preflight (user-authorized skip); Main Divergence Assessment not computed. Scope is a single doc file (`docs/ROADMAP-PLATFORM.yaml`); plan-critique (Step 9) reads the working-tree roadmap which includes these edits.

## Pre-Implementation Checklist

- [x] Branch confirmed not on `main` (currently on `claude/deepseek-lambda-agent-tools-PP5Es`)
- [x] Roadmap read fully this session (all 3,380 lines)
- [x] Decision-scout gate run (FLAGS_FOUND; findings incorporated)
- [x] All files in Scope table located and editable
- [x] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

The substantive edits are applied in this REPORT-ONLY planning session (the deliverable IS the roadmap edits). Order chosen to keep the YAML structurally valid throughout:

1. Add CD.17 sequencing note (detail text only; trigger expression untouched).
2. Insert CD.29 + CD.30 into `candidate_decisions[]` (before `tier_items:`).
3. Expand T3.1 (intent, depends_on +T3.6, files_in_scope, exit_criteria, related_candidate_decisions, effort M->L).
4. Insert T3.6 + T3.7 into `tier_items[]` (before the T4 section comment).
5. Amend T0.12.5 (intent paragraph + exit_criterion + related_candidate_decisions +CD.29).
6. Append KG.13 to `known_gaps[]`.
7. **Execute Verification Plan** -- run steps 1-6 (structural checks) locally; fix and re-run on any failure. Step 7 (plan-critique) and Step 8 (multi-perspective deliverable critique) are dispatched via the Agent tool per the planning skill.
8. Iterate on Step 9 critique findings until `Recommendation: PROCEED`.
9. Iterate on Step 10 critique findings until both lenses converge on PROCEED, OR human explicitly accepts current state with documented deferrals captured in a Known Gaps note.
10. Report: planning agent's mission completes after the approved-deliverable commit lands and merges. Follow-on plans the roadmap now describes: (a) T3.6 hermeticity audit, (b) T3.1 atomic plans (verifier harness, checks kernel, verification-registry Class C contract, differential gate), (c) T3.7 atomic plans (mutation runner, dead-test detector, diff-coverage ratchet, meta-validation workflow), (d) the T0.12.5 contract ratification carrying the consolidated `checks` field.
