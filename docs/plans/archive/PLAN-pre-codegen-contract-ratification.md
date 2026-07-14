# Plan

## Intent

Establish a pre-codegen contract ratification ritual as a load-bearing pattern in the platform. The deliverable is `docs/INTENT-pre-codegen-contract-ratification.md` plus a proposed Candidate Decision (CD.25) and a proposed roadmap edit set. Closes the drift class that today scatters field semantics across Pydantic models, Athena DDL, DQ YAML, and prose docs.

## Plan Type

REPORT-ONLY

## Verification Tier

V1 (the deliverable is documentation + a CD proposal + a YAML diff proposal; no executable Python lands in this plan).

## Branch

agent/pre-codegen-contract-ratification

## Phase

Platform tier T-1 (pre-migration hygiene). The pattern this plan establishes governs subsequent T0 / T1 / T3 work but does not depend on AWS migration progress. Anchors as a new tier item `T-1.11` (next free slot after the completed `T-1.10`).

## Scope

| File | Action | Purpose |
|------|--------|---------|
| `docs/INTENT-pre-codegen-contract-ratification.md` | Create | The substantive deliverable. Defines contract classes A/B/C, canonical home (`docs/contracts/{name}.yaml`), versioning + safe-evolution discipline, v0-provisional mechanism for Class B, cross-contract joins ratification, proposed CD.25 wording, proposed roadmap edits. |
| `docs/plans/PLAN-pre-codegen-contract-ratification.md` | Create | This planning artefact. |

No source code or runtime changes in this plan. All Python work is downstream (the ratification predecessor plans and the codegen plans they unblock).

## Bundled Recommendations

None. This plan establishes a pattern; the ratification predecessor plans it spawns will bundle aligned recommendations where they exist (notably any open recs concerning ops_recommendations field semantics, telemetry contract gaps, or Lambda verb design).

## Acceptance Criteria

- [ ] `docs/INTENT-pre-codegen-contract-ratification.md` exists on `agent/pre-codegen-contract-ratification`.
- [ ] The INTENT defines three contract classes (Class A: data schemas that become DDL; Class B: public agent surfaces / Lambda verb contracts; Class C: cross-system invariants) with at least two concrete examples per class.
- [ ] The INTENT defines `docs/contracts/{name}.yaml` as the canonical home for ratified contracts, with a worked schema (top-level + per-field structure).
- [ ] The INTENT defines the contract-versioning + safe-evolution discipline (`contract_version` field, `_contract_version` Iceberg column, forward-compat-only default, explicit `semantic_break: true` opt-in, append-only `previous_versions:` section).
- [ ] The INTENT defines the cross-contract joins ratification surface (either `docs/contracts/_joins.yaml` or a per-contract `joins:` section -- the deliverable selects one).
- [ ] The INTENT defines v0-provisional ratification for Class B contracts (re-ratification trigger semantics, where the trigger lives in the contract YAML, who fires the re-ratification).
- [ ] The INTENT proposes CD.25 wording (problem, decision, context, gates, decision_required_before).
- [ ] The INTENT proposes roadmap edits as a structured diff (new tier_items, modified `depends_on` edges) explicit enough that a follow-on IMPLEMENTATION plan can apply them mechanically.
- [ ] The INTENT enumerates known failure modes and explicit deferrals (Known Gaps section).
- [ ] Step 9 plan-critique gate returns `Recommendation: PROCEED` against PLAN-pre-codegen-contract-ratification.md.
- [ ] Step 10 multi-perspective critique gate (architect lens + adversarial risk lens) converges on the INTENT (either both PROCEED on a fresh round, or human-accepted with documented deferrals).
- [ ] Final PLAN + INTENT committed to `agent/pre-codegen-contract-ratification`.

## Verification Plan

| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm INTENT exists | `test -f docs/INTENT-pre-codegen-contract-ratification.md && wc -l docs/INTENT-pre-codegen-contract-ratification.md` | Returns line count > 200 (substantive doc, not stub) | Re-author missing sections per Acceptance Criteria |
| 2 | [pre-deploy] | Confirm three contract classes are defined | `grep -E "^### (Class A\|Class B\|Class C)" docs/INTENT-pre-codegen-contract-ratification.md \| wc -l` | Returns `3` | Add the missing class section |
| 3 | [pre-deploy] | Confirm contract YAML schema worked example present | `grep -c "contract_version:" docs/INTENT-pre-codegen-contract-ratification.md` | Returns >= 1 | Add the worked schema example |
| 4 | [pre-deploy] | Confirm semantic_break opt-in is defined | `grep -c "semantic_break" docs/INTENT-pre-codegen-contract-ratification.md` | Returns >= 2 (definition + at least one reference) | Add the missing definition or usage |
| 5 | [pre-deploy] | Confirm v0-provisional mechanism is defined | `grep -ci "v0.provisional" docs/INTENT-pre-codegen-contract-ratification.md` | Returns >= 3 | Add the missing v0-provisional sections |
| 6 | [pre-deploy] | Confirm CD.25 proposal is present | `grep -c "CD\.25" docs/INTENT-pre-codegen-contract-ratification.md` | Returns >= 1 | Add the CD proposal section |
| 7 | [pre-deploy] | Confirm roadmap edits are proposed | `grep -c "tier_items" docs/INTENT-pre-codegen-contract-ratification.md` | Returns >= 1 | Add the roadmap edits section |
| 8 | [pre-deploy] | Confirm Known Gaps section exists | `grep -c "## Known Gaps" docs/INTENT-pre-codegen-contract-ratification.md` | Returns 1 | Add the section listing explicit deferrals |
| 9 | [pre-deploy] | Run validate.py presubmit on the branch | `bin/venv-python -m scripts.validate --pre` | Pass (lint/format/prompts checks green; no code changes outside docs/) | Address ruff/format findings; re-run |
| 10 | [pre-deploy] | Step 9 plan-critique gate fires | Agent tool subagent invokes plan-critique skill in fresh context against PLAN file | Returns `Recommendation: PROCEED` (loop on REVISE) | Apply suggested revisions; re-launch |
| 11 | [pre-deploy] | Step 10 multi-perspective critique fires | Agent tool launches >=2 zero-context subagents in parallel (architect lens + adversarial risk lens) against the INTENT | Converges on PROCEED or human-accepted with documented deferrals | Apply revisions per human direction; re-launch |

## Constraints

- No rescue agents or workaround loops (Decision 55).
- STRATEGIC plan-artefacts suspended per Decision 67 / CD.17 — this plan is REPORT-ONLY, and the follow-on ratification plans it proposes are all REPORT-ONLY. Their downstream codegen plans are IMPLEMENTATION.
- Lambda deploys deferred per CD.17 — this plan does not deploy anything; deploy-side gating is irrelevant.
- No edits to `docs/ROADMAP-PLATFORM.yaml`, `docs/DECISIONS.md`, or any `src/`, `scripts/`, `terraform/`, `config/`, `tests/` content in this plan. The INTENT *proposes* edits; the actual edits land in a follow-on IMPLEMENTATION plan after CD.25 is ratified (or, during bootstrap, after the INTENT critique gates converge and the user signs off).
- Agent-First Repository: the canonical home for ratified contracts is `docs/contracts/{name}.yaml` (machine-parseable). Human-narrative INTENT-* documents stay episodic; contracts/ is durable.

## Context

- The pending AWS migration (per `docs/INTENT-aws-migration-platform-evolution.md`) is the reset point for many contracts. This INTENT lands the ritual that governs how new contracts in the personal account are designed, so the migration substrate inherits a sound discipline rather than carrying the current scatter forward.
- The Annotated-Pydantic schema-as-code foundation (T0.12, complete in commit `25ecf9b`) is the substrate this ritual builds on. T0.12 gives us machine-parseable enforcement markers; this plan adds the upstream **semantic ratification** step that those markers should encode.
- Telemetry tables were briefly populated by the now-paused executor and by interactive sessions, but the user has confirmed the data is unactioned and likely incorrect. Telemetry ratification is therefore treated as **greenfield Class A**, not "audit existing contracts." The personal-account migration is the natural reset point for telemetry data.
- The semantic-evolution problem (same column name, different meaning over time) is what Iceberg schema evolution does NOT solve. The versioning + forward-compat-only + `semantic_break` discipline proposed here closes that gap explicitly.

## Pre-Implementation Checklist

- [x] Branch confirmed not on `main` (`agent/pre-codegen-contract-ratification`)
- [x] `docs/PROJECT_CONTEXT.md` read
- [x] `docs/ROADMAP-PLATFORM.yaml` read (T-1 + T0 + T1 sections plus eligibility surface from preflight)
- [x] `docs/INTENT-aws-migration-platform-evolution.md` read (the strategic frame for the migration this ritual prepares for)
- [x] Current Pydantic model state read (`src/schemas/__init__.py`, `annotations.py`, `rec.py`, `decision.py`)
- [x] Current Athena DDL state read (`terraform/iceberg_tables.tf` ops + telemetry sections)
- [x] Current DQ YAML state read (`config/data_quality/ops.yaml` head)
- [x] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

1. **Write `docs/INTENT-pre-codegen-contract-ratification.md`** with all sections enumerated in the Acceptance Criteria. Target ~600-900 lines, structured for agent consumption (machine-parseable schemas, structured tables, explicit anti-patterns).
2. **Run verification steps 1-9** (`bin/venv-python -m scripts.validate --pre`, plus the structural greps on the INTENT). Fix any drift.
3. **Commit** the initial PLAN + INTENT to the branch: `git add docs/plans/PLAN-pre-codegen-contract-ratification.md docs/INTENT-pre-codegen-contract-ratification.md && git commit -m "plan(pre-codegen-contract-ratification): initial plan + INTENT"`.
4. **Fire Step 9 plan-critique gate.** Launch a `general-purpose` subagent via the Agent tool with a self-contained prompt naming the absolute path to PLAN-pre-codegen-contract-ratification.md and instructing it to invoke the `plan-critique` skill. Loop on REVISE; proceed on PROCEED.
5. **Fire Step 10 multi-perspective critique gate** on the INTENT deliverable. Launch in parallel: (a) senior architect lens reviewing design soundness, schema/contract correctness, dependency cleanliness, internal consistency; (b) adversarial risk reviewer reviewing blast radius, hidden state, rollback path, live-state divergence, what could go wrong in practice. Each agent returns structured output (Strengths / Concrete Issues / Recommended Revisions / Verdict). Synthesise findings, present to human, iterate.
6. **Iterate** on critique findings. Each material revision lands as its own commit (`git commit -m "plan(pre-codegen-contract-ratification): address [scope] critique findings"`). Re-launch critiques after each revision until convergence (both PROCEED on a fresh round, OR human-accepted with documented deferrals captured in the INTENT's Known Gaps section).
7. **Final commit** of the approved PLAN + INTENT (may be empty if revisions landed incrementally).
8. **Close telemetry session** with `bin/venv-python -m scripts.session_postflight --close-session --outcome success`.
9. **Stop.** The planning agent's mission ends here. Follow-on IMPLEMENTATION plans (applying the proposed roadmap edits, then ratifying each contract) start in fresh planning sessions after the user reviews the deliverable.
