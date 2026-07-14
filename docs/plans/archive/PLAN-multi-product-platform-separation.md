# Plan

## Intent
Capture, as a citable design record, how the platform hosts multiple products on two orthogonal axes -- a unified operational data plane keyed by `project_id` origin for same-owner products (extending the monorepo + `project_id` model), plus a packaged substrate for the one cross-IP-boundary case (the day job) -- extending the North Star's continuous-improvement loop across N products rather than one.

## Plan Type
REPORT-ONLY

## Verification Tier
V1

## Plan Path
docs/plans/PLAN-multi-product-platform-separation.md

## Phase
Platform-axis architecture deliberation (`docs/ROADMAP-PLATFORM.yaml`). Does not map to a current `tier_item`; admitted under the planning skill's soft-warn exception `user_explicit_out_of_scope` (human explicitly requested forward-looking architecture work). Informs a future substrate-extraction tier but commits no tier work. Product roadmap phase is unaffected (per the roadmap-disambiguation rule, this is platform context).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/plans/PLAN-multi-product-platform-separation.md | Create | This REPORT-ONLY wrapper plan (the planning artefact). |
| docs/INTENT-multi-product-platform.md | Modify | The substantive deliverable: the multi-product platform topology design record. Drafted earlier this session, citations refreshed to Decision 78, then re-centered on the two-axis reconciliation (unified `project_id` data plane + IP-forced code separation) per the plan-critique gate; extends the monorepo + `project_id` INTENT. |

## Bundled Recommendations
None. (343 open recs scanned; no genuine alignment -- the 3 keyword hits were incidental.)

## Infrastructure Dependencies (if applicable)
N/A. No `.tf` files in scope; no Lambda-packaged files in scope. No Infrastructure or Lambda Deployment Assessment required.

## Acceptance Criteria
- [ ] `docs/INTENT-multi-product-platform.md` exists and is plain ASCII (no emojis, no em-dashes).
- [ ] Zero environment/phase taxonomy-lint violations on the deliverable (the two reserved adjacencies absent).
- [ ] The deliverable cites Decision 78 (ratifying CD.31) for the per-domain table-format choice, and does not treat CD.31 as a pending/live locus.
- [ ] The three planes (Substrate / Automation / Data) named in the summary table are used consistently in the per-product opt-in table.
- [ ] The deliverable passes the Step 10 multi-perspective report critique with PROCEED, or an explicitly accepted deferral recorded in the deliverable's Open Decisions.
- [ ] Both scope files land on `main` via the Decision 76 squash-merge flow.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | pre-merge | Replicate the taxonomy lint, axis A (no product-phase token used as an "environment") | `! grep -qEi '(research\|backtest_canonical\|paper\|live_small\|live_full)[ \t]+environment' docs/INTENT-multi-product-platform.md` | exit 0 (no match) | a match -> rephrase the offending adjacency; product states are phases, not environments |
| 2 | pre-merge | Replicate the taxonomy lint, axis B (no platform-tier token used as a "phase") | `! grep -qEi '(sandbox\|sit\|prod\|production\|staging)[ \t]+phase' docs/INTENT-multi-product-platform.md` | exit 0 (no match) | a match -> rephrase; platform tiers are environments, not phases |
| 3 | pre-merge | Citation currency: cites Decision 78 as the ratifier and does not treat CD.31 as pending/live | `grep -q 'Decision 78 (ratif' docs/INTENT-multi-product-platform.md && ! grep -qiE 'inheriting the CD\.31\|CD\.31[^)]*(pending\|proposed\|settled)\|Not re-opening CD\.31' docs/INTENT-multi-product-platform.md` | exit 0 | fails -> recite the per-domain choice to Decision 78 (originating proposal CD.31) |
| 4 | pre-merge | ASCII-only (catches em-dashes and emojis) | `! grep -nP '[^\x00-\x7F]' docs/INTENT-multi-product-platform.md` | exit 0 (all ASCII) | non-ASCII byte -> replace (em-dash -> ` -- `; drop emoji) |
| 5 | pre-merge | Plane-name consistency (all three planes present as bold headers) | `for p in Substrate Automation Data; do grep -q "\*\*$p\*\*" docs/INTENT-multi-product-platform.md || { echo "missing $p"; exit 1; }; done` | exit 0; all three named | a plane missing -> reconcile the summary table with the per-product opt-in table |

## Constraints
- **Concern-separation only.** The deliverable draws repo/package boundaries; it does NOT alter account topology or the Decision-77 two-axis environment/phase taxonomy, and does not touch the reserved vocabulary.
- **The IP wall is absolute.** No employer code, data, or domain-tier telemetry enters the personal account, the personal lakehouse, or a personal repository. The design must be correct even if day-job meta-telemetry never flows.
- **REPORT-ONLY.** No recommendations filed; no executor work queued. STRATEGIC plan-type is suspended (Decision 67 / AGENTS.md Temporary Operational Constraints); this is a design record, not a STRATEGIC plan.
- **Single Portal invariant preserved.** The deliverable's proposed `product` dimension in the ops portal is DEFERRED, not implemented here; when implemented it must route through `scripts/ops_data_portal.py` (Decision 69/78, invariant preserved at the primitive level) and respect the executor self-modification boundary (Decision 44).
- **Plain ASCII.** No emojis, no em-dashes (AGENTS.md).
- No rescue agents or workaround loops (Decision 55).

## Context
- **Rebase performed at planning time.** Branch was 1 commit behind `origin/main`; the diverging commit was `#55` (CD.31 ratification -> Decision 78). Overlapping files were `docs/DECISIONS.md` and `docs/ROADMAP-PLATFORM.yaml` -- the exact surfaces this deliverable cites. Rebased onto `origin/main` per the human's "write the plan" direction so the deliverable cites current decisions and the critique gates evaluate against the live tree.
- **Decision-scout verdict: FLAGS_FOUND (no BLOCK).** Flags resolved in the deliverable: Decision 78 [WARN] (CD.31 now ratified -> citations refreshed; CD.31 retained as the originating proposal pointer); Decision 78 [NOTE] (NS.1 generalized to "S3 + open table format" -> framing tracked); Decision 50 [RELATED] (superseded by 78 -> no ops-Iceberg-as-end-state phrasing). CITE list applied: Decision 77 (two-axis taxonomy; anchors the no-account-multiplication Non-Goal), Decision 67 (REPORT-ONLY framing), Decision 75 (frame-lock; the dependency inversion is a conscious frame choice), Decision 76 (merge mechanics).
- **Generalizes KG.1** from one product to N. Recorded as deferred Open Decision OD-5 in the deliverable; NOT edited into `docs/ROADMAP-PLATFORM.yaml` here, to keep this plan atomic and avoid editing a file `main` just touched.
- **Deliverable pre-existed the gates.** It was committed earlier this session before the mandatory gates ran; this plan brings it through decision-scout (done), plan-critique (Step 9), and the multi-perspective report critique (Step 10) retroactively, per the human's explicit request to follow the `/plan` procedure.
- **Merge mechanics:** Decision 76 web flow -- GitHub MCP PR, fast `--pre` tier event-driven via `subscribe_pr_activity`, squash-merge via `merge_pull_request`. The INTENT file does not exist on `main`, so no remote-edit conflict.
- **Reconciliation with `docs/INTENT-aws-migration-platform-evolution.md` Part 2 (plan-critique REVISE finding, resolved):** the deliverable was re-centered on two orthogonal axes -- a unified platform data plane keyed by `project_id` origin (the migration INTENT's already-designed dimension, adopted not redesigned) and a code/repo axis that separates only where the day-job IP boundary forces it. The deliverable now EXTENDS, and does not supersede, the monorepo + `project_id` commitment; split-repo for same-owner products stays deferred. The earlier "believed distinct" framing was wrong -- the two documents answer the same question and are now explicitly reconciled, with the sibling INTENT cited in the deliverable's Builds-on / Companion documents.
- **Open question for the Step 10 critique (non-blocking):** keep the KG.1 generalization deferred (OD-5) or fold the small roadmap edit in (leaning defer).

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main` (`claude/affectionate-davinci-wpjOD`)
- [x] docs/PROJECT_CONTEXT.md read
- [x] DECISIONS.md read (Decisions 78, 77, 75, 67, 76, 50 relevant)
- [x] All files in Scope table located and readable
- [x] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. [DONE in planning] Author `docs/INTENT-multi-product-platform.md`: dependency-inversion thesis; three-plane model (Substrate / Automation / Data) with per-product opt-in; IP/egress wall (NS.2 in reverse); meta/domain telemetry tiering; repo topology; tenancy mechanics; the context-management dividend; Open Decisions + Non-Goals + Constraints.
2. [DONE in planning] Rebase onto `origin/main` (pick up Decision 78); refresh the deliverable's CD.31 -> Decision 78 citations and the generalized NS.1 framing; add the Decision 75 frame note and Decision 67 REPORT-ONLY anchor.
3. **Execute Verification Plan** -- run each VP step; loop until all pass.
4. Plan-critique gate (workflow Step 9) -- fresh-context subagent runs the `plan-critique` skill against this PLAN; revise and re-run until PROCEED.
5. Multi-perspective report critique (workflow Step 10) -- at least two parallel fresh-context subagents (architect + adversarial risk) critique the deliverable; synthesize, present, revise until convergence (both PROCEED, or human-accepted deferral).
6. Merge both scope files to `main` via the Decision 76 squash-merge flow.
7. Report: deliverable landed, gate verdicts, and which Open Decisions remain deferred.
