# Plan

## Intent
Resolve, with repo-grounded evidence, whether this repository should adopt Bazel
(versus Pants, versus a do-less "good CI caching + pytest" baseline) as its
build/test substrate -- a question raised as a deviation from the deferred
`scripts/validate.py` monolith decomposition. The substantive deliverable is
`docs/INTENT-bazel-feasibility.md`: a skeptical claims-verification matrix that
falsifies ten load-bearing claims (C1-C10) from a prior first-principles Bazel
design conversation against actual repo state at commit `ddb85a0`. The verdict
gates whether any subsequent build-tool plan is authored and -- the key outcome --
decouples the validate.py decomposition (which proceeds tool-free) from the
build-tool question. No code, config, or BUILD files are produced.

## Plan Type
REPORT-ONLY

## Verification Tier
V1 (documentation deliverable; acceptance is section-existence, claim-to-artefact
traceability, and dead-link absence -- no pytest, no code changed). Tier per Decision 48.

## Branch
claude/magical-darwin-iHRH4

## Phase
Platform hygiene / build-tooling direction. Forecloses premature build-tool adoption
and unblocks the deferred validate.py decomposition (the Decision 43 complexity-waiver
remediation). Not tied to a specific roadmap wave.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `docs/INTENT-bazel-feasibility.md` | Create | Substantive deliverable. Verdict + C1-C10 claims-verification matrix + blockers + quantified findings + design-vs-reality table + tool-choice (Bazel/Pants/do-less) + phased do-less recommendation + validate.py decomposition linkage + unverifiable-claims register. |
| `docs/plans/PLAN-bazel-feasibility.md` | Create | This planning artefact. |
| `docs/DECISIONS.md` | Modify (gated) | Add `## Decision 80` recording the verdict (build-tooling direction). Written ONLY after the Step 10 report-critique gate returns PROCEED, so the record reflects the critiqued verdict. Warehouse-ID reconciliation is a follow-up via `scripts.ops_data_portal` (per the Decision 77 precedent). |

## Bundled Recommendations
None bundled. A REPORT-ONLY plan produces no executor work, and the STRATEGIC freeze
is retained (Decision 67/79). The follow-on validate.py decomposition IMPLEMENTATION
plan will triage open validate.py recs (e.g. the `test_validate.py` main()-path
integration-coverage gap and the SLOC/CC hard-gate recs noted in
`PLAN-ci-cd-architecture.md`'s bundle list).

## Infrastructure Dependencies
None. No `.tf` files in scope. No Lambda-packaged files in scope. Decision 79
(Lambda-deploy clause lifted; per-Lambda manifests) and Decision 67 (STRATEGIC freeze
retained) are both acknowledged in the INTENT document; neither produces a deploy or
DEFERRED step (REPORT-ONLY, docs-only).

## Acceptance Criteria
- [ ] `docs/INTENT-bazel-feasibility.md` exists and contains all required sections: Verdict; Claims-Verification Matrix (C1-C10); Blockers; Quantified Findings; Design Assumptions vs Repo Reality; Tool-Choice Assessment; Recommendation; Linkage to validate.py Decomposition; Unverifiable Claims; Relationship to Existing Decisions; Constraints.
- [ ] Every quantified claim in the matrix is traceable to a repo artefact (path and/or number); no claim rests on general Bazel knowledge.
- [ ] The assessment engages Decision 75's frame-challenge explicitly (the verdict reads as conscious choice, not frame-locked toward "adopt Bazel").
- [ ] No markdown link or backticked path references a file absent from the repo.
- [ ] Plan Type is REPORT-ONLY; no STRATEGIC declaration anywhere (Decision 67/79 freeze); the phased recommendation is narrative-only (no `file_rec`).
- [ ] `bin/venv-python -m scripts.validate --pre` passes on the docs-only change.
- [ ] Step 9 plan-critique gate returns PROCEED on this PLAN.
- [ ] Step 10 multi-perspective report-critique gate (>=2 zero-context subagents) returns PROCEED on the INTENT deliverable, OR the human accepts current state with documented deferrals.
- [ ] (Gated on Step 10 PROCEED) `docs/DECISIONS.md` gains `## Decision 80:` recording the verdict, internally consistent with the INTENT document.

## Verification Plan
- Section-existence: grep the eleven required `##` headers in the INTENT doc.
- Claim traceability: each matrix row cites a path or number; spot-check against the cited artefact.
- Dead-link check: every backticked path / `](...)` in the INTENT doc resolves to an existing file.
- `bin/venv-python -m scripts.validate --pre` (lint/format/prompt validators; doc-only change).
- No pytest: no code changed (Tier V1, Decision 48).

## Constraints
- Read-only assessment: only `docs/` files are written. No edits to scripts/, src/, terraform/, config/. No BUILD/WORKSPACE/MODULE.bazel/`pants.toml` files.
- STRATEGIC freeze (Decision 67, retained by Decision 79): no STRATEGIC plan; no executor recommendations minted from the phased recommendation.
- Agent-first (Decision 65): the INTENT doc is a durable decision-input artefact (sibling to `docs/INTENT-*.md`), graduating to Decision 80 -- not a transient query-result summary.
- No model identifier appears in any committed artefact (chat-only).
- Do not soften negatives: the cycles, the 3.12-vs-3.13 version gap, and the weak test-quality baseline are stated as blockers.

## Context
Repo state at `ddb85a0` (rebased onto origin/main this session). Decisive evidence
already gathered (full numbers in the INTENT doc's Quantified Findings):
- Single-language Python (121 first-party modules / ~36.5k SLOC) + Markdown (287 files / ~70k LOC); no compiled build; the only artifact is a Lambda zip.
- First-party import graph: 121 nodes, 215 edges, sparse (avg fan-out 1.78). Dependency closure: median 0.8%, p90 23.1%, max 33.9% (`scripts.validate`).
- THREE static-graph cycles that are module-acyclic at runtime -- artifacts of function-local deferred imports (the same 104 `noqa: PLC0415` objects): the `scripts/verifiers` package (6-node, collapses by removing one late import in `harness.py:151`), an `ops_data_portal`+executor 5-node, and `execute_recommendation`<->`batch`. Real Bazel friction (declare-and-cycle vs omit-and-sandbox-ImportError), but it binds `import-linter` equally -- not a Bazel-discriminating blocker.
- `scripts/validate.py`: 2744 lines (Decision 43 waiver records 1198), the single highest-closure module (33.9%), the lone real `importlib`/`spec_from_file_location` user, 38 `validate_` functions with no registry; its test is 2950 lines with 262 `patch(` sites + 62 monkeypatch.
- No dependency lockfile (unpinned `>=`); torch 1.1 GB and pysr->Julia defeat a clean hermetic closure.
- Python 3.12 everywhere (durable functions need 3.13+). Coverage `fail_under=37`, scoped to `src/` only (excludes all of scripts/). No mutation or property testing. `--disable-socket` already enforces test hermeticity.
- Decision 79 (today) chose per-Lambda manifests with "no transitive resolution" + a `validate_lambda_manifest_coverage` gate -- the repo's own direction is explicit-manifest, anti-transitive-closure.

## Pre-Implementation Checklist
- [x] Decision-scout gate run (FLAGS_FOUND: Decision 67 WARN handled via REPORT-ONLY + narrative-only recommendation; CITE 43/60/73/75).
- [x] Branch rebased onto origin/main (`ddb85a0`).
- [x] Quantitative investigation complete (graph / cycles / closure / dynamic-census / deps / loop / coverage).
- [x] User refinements incorporated (affected-set check selection, not static tier; validators stay a local package, not a Lambda).

## Ordered Execution Steps
1. [done in this pass] Write `docs/INTENT-bazel-feasibility.md`.
2. [done in this pass] Write this PLAN.
3. Step 9: plan-critique gate on the PLAN (invoke the `plan-critique` skill).
4. Step 10: multi-perspective report-critique gate -- >=2 zero-context subagents adversarially check the INTENT doc's claims; converge on a clean round or document deferrals.
5. If PROCEED: add `## Decision 80` to `docs/DECISIONS.md` reflecting the critiqued verdict.
6. `bin/venv-python -m scripts.validate --pre`; commit; `git push -u origin claude/magical-darwin-iHRH4`.
7. Per the web merge flow (Decision 76): open the PR via the GitHub MCP tools, await the fast `--pre` tier event, then squash-merge.

## Constraints (post-merge)
- The validate.py decomposition is a SEPARATE IMPLEMENTATION plan (not STRATEGIC): an
  acyclic check-plugin registry (`base` leaf < `checks` < `registry`), inputs-declared
  affected-set selection for the PR/edit tier with `always` for global invariants, the
  full set on main, and `import-linter` contracts forbidding the `checks -> registry`
  back-edge. Step one of that plan fixes the `scripts/verifiers` cycle as the reference
  refactor.
- The do-less baseline (`import-linter` + a lockfile) is the only build-adjacent tooling
  recommended now; Bazel/Pants remain deferred pending a measured signal defined in the
  INTENT doc's Recommendation section.
