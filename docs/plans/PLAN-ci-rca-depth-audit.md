# Plan

## Intent
Audit the CI-RCA agent's analysis depth using rec-859 / CI run 26286390667 as a case study, and prescribe a deterministic methodology contract (structured context schema + evidence-bundle script + portal-level enforcement) that structurally prevents the agent from filing rescue-style remediation in place of root-cause analysis. North-Star contribution: closes a feedback-loop quality gap. The self-improving system optimises against the signals the RCA agent produces; if those signals are shallow, the system optimises against the wrong target. Decision 72 establishes the "RCA-as-Plan-Source" pattern as architectural intent; this plan operationalises it.

## Plan Type
REPORT-ONLY

## Verification Tier
V1

## Branch
`claude/exciting-babbage-Ck5Au` (Claude Code on the web session branch; per session start-up instructions). Deviates from the standard `/plan` convention of `agent/{slug}`. `find_plan.py` will not auto-resolve from this branch name; this is acceptable because the plan is REPORT-ONLY and does not invoke `/implement`.

## Phase
Phase Platform (automation infrastructure) -- methodology layer of the agent ecosystem. Touches the contract between scheduled agents and the ops portal, not any product code.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/plans/PLAN-ci-rca-depth-audit.md | Create | This planning artefact |
| docs/INTENT-ci-rca-methodology.md | Create | Substantive deliverable -- the RCA methodology contract for `source=ci_rca` recs |

## Bundled Recommendations
None. rec-859 (Refactor `scripts/product_roadmap.py` below 500-SLOC) is being implemented in parallel on a separate branch per the human; this plan deliberately does NOT touch `scripts/product_roadmap.py` or the SLOC violation directly. The two efforts are orthogonal: rec-859 fixes the instance, this plan fixes the methodology gap that produced shallow analysis of the instance.

## Infrastructure Dependencies
None. No `.tf` files in scope. No Lambda-packaged files in scope.

## Acceptance Criteria
- [ ] `docs/INTENT-ci-rca-methodology.md` exists and is non-empty
- [ ] Contains the structured context schema with all required sub-fields: `proximate_cause`, `why_chain` (min 3), `detection_gap` (with `earliest_viable_gate`, `actual_gate_that_caught_it`, `gap_explanation`), `recurrence_class`, `corrective_action`, `preventive_action`
- [ ] Defines the `scripts/ci_rca_evidence.py` script contract: inputs, computation steps, output schema, failure modes
- [ ] Defines portal-level enforcement rules in `ops_data_portal.file_rec()` for `source=ci_rca`
- [ ] Defines the cross-check rule between agent claims and the deterministic evidence bundle
- [ ] Lists at least 3 follow-on plan recommendations (schema enforcement, evidence script, prompt rewrite are required; SLOC promotion is the canonical concrete consumer)
- [ ] Includes rec-859 / CI run 26286390667 as the worked case study, with the why-chain that the current rec failed to surface
- [ ] References Decision 43 (SLOC limit), Decision 55 (no-autonomous-fix), Decision 66 (precision context injection), Decision 72 (RCA-as-Plan-Source)
- [ ] No emojis (agent-first repo invariant)
- [ ] Both parallel critique agents return `PROCEED` OR the human explicitly accepts the current state with documented deferrals

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | pre-commit | Deliverable exists and is non-trivial | `test -s docs/INTENT-ci-rca-methodology.md && wc -l docs/INTENT-ci-rca-methodology.md \| awk '{exit ($1 < 100) ? 1 : 0}'` | exit 0 (file exists and >= 100 lines) | File missing or too short -- expand |
| 2 | pre-commit | All required schema sub-fields named | `grep -cE '(proximate_cause\|why_chain\|earliest_viable_gate\|actual_gate_that_caught_it\|gap_explanation\|recurrence_class\|corrective_action\|preventive_action)' docs/INTENT-ci-rca-methodology.md` | `>= 8` | Add missing field definitions |
| 3 | pre-commit | Evidence script contract present and named | `grep -cE 'ci_rca_evidence(\\.py)?' docs/INTENT-ci-rca-methodology.md` | `>= 3` | Add evidence script section |
| 4 | pre-commit | Enforcement rules present | `grep -cE 'portal-level\|file_rec\|reject' docs/INTENT-ci-rca-methodology.md` | `>= 4` | Add enforcement section |
| 5 | pre-commit | Cross-check rule present | `grep -ciE 'cross-check\|deterministic computation\|bundle.*authoritative' docs/INTENT-ci-rca-methodology.md` | `>= 2` | Add cross-check semantics |
| 6 | pre-commit | rec-859 case study cited | `grep -c 'rec-859' docs/INTENT-ci-rca-methodology.md` | `>= 1` | Add case study |
| 7 | pre-commit | CI run 26286390667 cited | `grep -c '26286390667' docs/INTENT-ci-rca-methodology.md` | `>= 1` | Add run ID |
| 8 | pre-commit | Decision references present | `grep -cE 'Decision (43\|55\|66\|72)' docs/INTENT-ci-rca-methodology.md` | `>= 4` | Add missing Decision references |
| 9 | pre-commit | At least 3 follow-on plans listed | `grep -cE '^- PLAN-' docs/INTENT-ci-rca-methodology.md` | `>= 3` | Add follow-on plan list |
| 10 | pre-commit | No emojis | `bin/venv-python -c "import re,sys; d=open('docs/INTENT-ci-rca-methodology.md').read(); sys.exit(1 if re.search(r'[\\U0001F300-\\U0001FAFF\\U0001F600-\\U0001F64F\\u2600-\\u26FF\\u2700-\\u27BF]', d) else 0)"` | exit 0 | Remove emoji characters |
| 11 | pre-commit | `--pre` still green (sanity, no regressions from in-flight repo edits) | `bin/venv-python -m scripts.validate --pre > /tmp/pre.log 2>&1; grep -E 'Validation Summary' /tmp/pre.log` | non-empty (gate ran) | Investigate any regression |

## Constraints
- No emojis (agent-first repo invariant per CLAUDE.md)
- No edits to `scripts/validate.py`, `scripts/ops_data_portal.py`, or `.claude/agents/scheduled/ci-rca.md` this session (methodology-only; implementation deferred to follow-on plans)
- No rescue agents or workaround loops (Decision 55)
- Decision 43 SLOC limit is referenced but NOT modified -- this plan addresses *enforcement timing/placement*, not the policy
- Decision 67 freeze: all referenced follow-on plans must be authorable as IMPLEMENTATION type (no STRATEGIC plans during freeze)
- Methodology-only scope (per human direction): the deliverable describes WHAT the methodology should be; HOW to implement it is deferred to follow-on plans

## Context
- **ci-rca hard-block justification.** Preflight surfaces rec-859 (`ci_rca_recs` non-empty) which ordinarily blocks `/plan` from scoping unrelated work. This plan does not scope unrelated work -- it IS the ci-rca investigation. The soft-warn `ci_rca` exception from the planning skill applies. Related-Work conditions: (a) same Decision Record (Decision 43, SLOC limit), (b) same failure category (validate.py false negative -- a check that should have caught the violation at an earlier tier did not).
- **rec-859 is being implemented in parallel** on another branch (human confirmed). This plan does NOT subsume rec-859. rec-859 fixes the specific 810-SLOC file; this plan fixes the methodology gap that allowed the violation to be analysed shallowly.
- **The empirical confirmation.** Running `bin/venv-python -m scripts.validate --pre` against the current tree completes without invoking `validate_sloc_limits()`. Inspection of `scripts/validate.py` confirms: `validate_sloc_limits` is defined at line 1041 and called from `run_python_checks` at line 1945; `run_python_checks` is invoked from the full tier at line 2295 (gated on `scope in ("python", "all")`). The `--pre` branch (lines 2229-2290) returns at line 2284/2290 before falling through to the full tier. SLOC enforcement is structurally absent from the fast tier.
- **The deliverable is the substantive output.** Per the REPORT-ONLY plan-type contract, `docs/INTENT-ci-rca-methodology.md` carries the substance; `PLAN-ci-rca-depth-audit.md` (this file) is the planning artefact.
- **Decision 72 is the architectural anchor.** It establishes that ci-rca files recs which `/plan` consumes; this INTENT doc operationalises Decision 72 by defining what "files recs" must produce structurally.
- **Decision 66 (Precision Context Injection)** is the proximate pattern this work extends. The current `get_rec_write_guidance()` surfaces semantics for `title`/`context`/`acceptance` to prevent structurally-valid-but-semantically-thin content. This plan extends the same lever to structure the `context` field itself for `source=ci_rca`.
- **Multi-perspective critique gate is mandatory** (REPORT-ONLY plan; planning skill Step 10). Two parallel zero-context subagents: senior architect (does the schema have integrity, are field semantics tight enough?) + adversarial reviewer (does this just create more bureaucracy without changing agent behaviour? does the evidence script have hidden coupling?). Convergence rule: both PROCEED or human accepts with deferrals.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main` (`git branch --show-current` returns `claude/exciting-babbage-Ck5Au`)
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read (specifically Decisions 43, 55, 57, 66, 67, 68, 72)
- [ ] `.claude/agents/scheduled/ci-rca.md` read (current agent definition; methodology baseline)
- [ ] `scripts/validate.py` read (`validate_sloc_limits` at line 1041, `--pre` branch at 2229, full-tier entry at 2294)
- [ ] `scripts/ops_data_portal.py` read (specifically `file_rec` and `get_rec_write_guidance`)
- [ ] rec-859 context read from `logs/.recommendations-log.jsonl`
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Confirm branch is not `main` (`git branch --show-current`).
2. Confirm pre-implementation checklist files are loaded (Read each).
3. Write `docs/INTENT-ci-rca-methodology.md` with all sections specified in Acceptance Criteria.
4. Run Verification Plan steps 1-11. Loop until all pass.
5. Commit deliverable + plan together (`git add docs/plans/PLAN-ci-rca-depth-audit.md docs/INTENT-ci-rca-methodology.md && git commit -m "plan(ci-rca-depth-audit): initial plan and deliverable"`).
6. **Plan critique gate (Step 9 of /plan workflow):** launch zero-context subagent to run `plan-critique` skill on this PLAN file. Apply revisions if REVISE. Re-launch on each revised version.
7. **Report critique gate (Step 10 of /plan workflow, REPORT-ONLY mandatory):** launch 2 parallel zero-context subagents on `docs/INTENT-ci-rca-methodology.md`: senior architect + adversarial reviewer. Synthesise findings. Present to human. Iterate based on direction. Re-launch after each material revision. Convergence when both PROCEED or human explicitly accepts state with deferrals.
8. After all critique gates approve, commit any uncommitted revisions (`git commit -m "plan(ci-rca-depth-audit): approved plan"`; may be empty if revisions landed inline).
9. Output the REPORT-ONLY confirmation message per planning skill Step 12.
10. Close telemetry session (`bin/venv-python -m scripts.session_postflight --close-session --outcome success`).

## Work Areas (STRATEGIC plans only)
N/A -- this is REPORT-ONLY.
