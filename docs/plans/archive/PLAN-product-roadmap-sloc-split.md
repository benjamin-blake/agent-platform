# Plan

## Intent
Refactor `scripts/product_roadmap.py` (currently 631 SLOC, 131 over Decision 43's 500-SLOC hard limit) by extracting the Pydantic schema models and `GateRuleParser` into a sibling module `scripts/product_roadmap_schema.py`. This satisfies open ci-rca rec-859 (which is currently blocking main CI), and aligns with Decision 43's stated rationale (agent comprehension of bounded files) rather than adding a transitional waiver.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/product-roadmap-sloc-split

## Phase
ci_rca_recovery -- ad-hoc soft-warn exception per AGENTS.md / planning skill (rec-859 is the open ci-rca rec; this work does not map to a PLATFORM tier_item).

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/product_roadmap_schema.py` | Create | Extract from `product_roadmap.py`: `GateRuleParser` class, all 23 Pydantic model classes (`GateHelper` through `KnownPlatformGap`), and the two module-level regex/constant declarations consumed only by model validators (`_SUPPORTED_VERSIONS`, `_OPS_DECISIONS_RE`). |
| `scripts/product_roadmap.py` | Modify | Remove the symbols extracted to `_schema`. Add a single top-level import-and-re-export block so the public API surface (`GateRuleParser`, `ProductRoadmapDocument`, `FivePropertyWaiver`, `load`, etc.) is unchanged for callers. Retain `ProductRoadmapDocument` (with its `_validate_graph` method), `_check_unique_ids`, `load`, `_item_dict`, `ProductRoadmapState`, `compute_state_dict`, the CLI, and the layer-shortcut constants (`_LAYER_SHORTCUT_RE`, `_AGGREGATE_LAYER_SHORTCUTS`, `_CANONICAL_LAYER_ORDER`) that are consumed by both `_validate_graph` and `ProductRoadmapState`. |
| `tests/test_product_roadmap_schema.py` | Create | Per-file coverage required by `test_coverage_checker.py` (Decision 43 enforcement). Exercises each Pydantic model's positive construction path, every `field_validator` / `model_validator` rejection branch, and `GateRuleParser` positive plus negative cases (unknown helper name, wrong arity, balanced/unbalanced parens, string-literal commas). Target: 100% line coverage of `scripts/product_roadmap_schema.py` when run in isolation (`pytest tests/test_product_roadmap_schema.py --cov=scripts/product_roadmap_schema`). |

## Bundled Recommendations
None. rec-855 (reserved-status five-property exemption), rec-856 (in_progress coverage), rec-857 (narrow `pytest.raises(Exception)`) touch the same file but are out of scope to keep this PR focused on the SLOC refactor.

## Infrastructure Dependencies (if applicable)
N/A -- no `.tf` files in scope.

## Acceptance Criteria
- [ ] `scripts/product_roadmap.py` SLOC <= 500 (no waiver added).
- [ ] `scripts/product_roadmap_schema.py` SLOC <= 500 (no waiver added).
- [ ] `bin/venv-python -m scripts.validate --pre 2>&1 | grep -q "All checks passed"` returns 0.
- [ ] `bin/venv-python -m pytest tests/test_product_roadmap.py tests/test_product_roadmap_state.py tests/test_session_preflight_product_roadmap.py` passes with no changes to those test files.
- [ ] `bin/venv-python -m pytest tests/test_product_roadmap_schema.py` passes.
- [ ] `bin/venv-python -m pytest tests/test_product_roadmap_schema.py --cov=scripts/product_roadmap_schema --cov-report=term` reports 100% line coverage for `scripts/product_roadmap_schema.py`.
- [ ] `bin/venv-python -m scripts.product_roadmap --check docs/ROADMAP-PRODUCT.yaml --platform docs/ROADMAP-PLATFORM.yaml` prints `PASS`.
- [ ] `bin/venv-python -m scripts.session_preflight` followed by `bin/venv-python -m scripts.product_roadmap --check-preflight-report logs/.preflight-report.json` prints `PASS`.
- [ ] Public symbol re-export verified: importing `GateRuleParser`, `ProductRoadmapDocument`, `FivePropertyWaiver`, `load`, `ProductRoadmapState`, `compute_state_dict` from `scripts.product_roadmap` continues to work without modification of any caller (verified indirectly by the existing-test acceptance row above, since those tests import these symbols).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | pre-deploy | Run new schema-module test file to confirm coverage and behaviour. | `bin/venv-python -m pytest tests/test_product_roadmap_schema.py --cov=scripts/product_roadmap_schema --cov-report=term-missing -q` | All tests pass; `scripts/product_roadmap_schema.py` line coverage == 100%. | If a validator branch is uncovered, add a targeted test case for the missing line(s). If a test fails, the schema model behaviour differs from pre-refactor -- diff against the original definition. |
| 2 | pre-deploy | Run pre-existing product_roadmap tests untouched to confirm the re-export surface preserves the public API. | `bin/venv-python -m pytest tests/test_product_roadmap.py tests/test_product_roadmap_state.py tests/test_session_preflight_product_roadmap.py -v` | All tests pass without modification. | If an import fails (`ImportError`), add the missing symbol to the re-export block in `scripts/product_roadmap.py`. If a behavioural test fails, the schema extraction altered semantics -- restore the original logic. |
| 3 | pre-deploy | Confirm SLOC limit cleared for both files. | `bin/venv-python -m scripts.validate --pre 2>&1 \| tee /tmp/validate-pre.log \| grep -q "All checks passed"` | Exit code 0. The log shows `All files within SLOC limits or waivered.` under the `=== SLOC limits (Decision 43) ===` section. | If SLOC still over: count the actual SLOC of the larger file with `bin/venv-python -c "lines=open('scripts/product_roadmap.py').read().splitlines(); print(sum(1 for ln in lines if ln.strip() and not ln.strip().startswith('#')))"` and remove an additional logical chunk (e.g., move the `_validate_graph` body to a helper in `_schema`). Do NOT add a waiver. |
| 4 | pre-deploy | Run the live PRODUCT-YAML validation through the CLI to catch any schema regression. | `bin/venv-python -m scripts.product_roadmap --check docs/ROADMAP-PRODUCT.yaml --platform docs/ROADMAP-PLATFORM.yaml` | stdout includes `PASS: product roadmap schema validation passed.` and a `platform_consumers:` summary line. Exit code 0. | If FAIL, the refactor altered validator semantics. Diff the new `_schema` module against the original models for any missed `field_validator` / `model_validator` / `model_config` parameter. |
| 5 | pre-deploy | Run session preflight end-to-end and confirm the `product_roadmap` block is structurally intact. | `bin/venv-python -m scripts.session_preflight && bin/venv-python -m scripts.product_roadmap --check-preflight-report logs/.preflight-report.json` | First command exits 0; second prints `PASS: preflight report has correct product_roadmap block shape` and exits 0. | If the preflight `product_roadmap` block is missing expected keys, the `compute_state_dict` call path is broken -- check that `ProductRoadmapState`, `compute_state_dict`, and `_item_dict` were not accidentally moved or had their references re-pointed. |

## Constraints
- Python 3.12+, type hints required, async for I/O (AGENTS.md).
- ruff formatting, line length 127 (AGENTS.md).
- No emojis in code, scripts, or docs (AGENTS.md).
- Default to no comments; only add a comment when the *why* is non-obvious (AGENTS.md).
- No `eval()` / `exec()`; no module-level raises (AGENTS.md).
- Never edit on `main` -- enforced by `.claude/hooks/never_on_main.py`; this plan is being executed on `agent/product-roadmap-sloc-split` (AGENTS.md).
- Acceptance commands must not contain `python -c` one-liners (PROJECT_CONTEXT.md, Pytest `-k` selector gotcha) -- the `Fix If` columns above use `python -c` only for diagnostics, never in acceptance.
- `__init__.py` is excluded from SLOC counting by `validate.py`, but this refactor is sibling-module style, not package conversion -- no `__init__.py` is created.
- No rescue agents or workaround loops (Decision 55) -- on V2 verification failure, root-cause then fix in place; do not paper over with a waiver.
- Re-exports MUST preserve every public name currently importable from `scripts.product_roadmap`: `GateRuleParser`, `GateHelper`, `DocumentMeta`, `FourLayerEntry`, `CurrentState`, `ThreeTierData`, `Environments`, `EvaluationMetrics`, `MinimumViableV1`, `PromotionFunnel`, `NorthStar`, `ContractGate`, `FivePropertyAttestation`, `FivePropertyTest`, `FivePropertyWaiver`, `TierItem`, `CandidateDecision`, `ResearchPoolDecision`, `CrossTierGate`, `RetiredItem`, `OutOfProductScope`, `OpenQuestion`, `KnownGap`, `KnownPlatformGap`. Use `# noqa: F401` on the import-and-re-export block if ruff complains, or define `__all__` in `_schema` and use `from scripts.product_roadmap_schema import *` (former is preferred for explicitness).

## Context
- **Decision 43 (Directed Growth Governance):** 500-SLOC hard limit per Python file enforced by `validate_sloc_limits()` in `scripts/validate.py`. Waivers (`# complexity-waiver: decision-43`) exist but are explicitly framed as Day-1 transitional for legacy files (validate.py, postflight.py, execute_recommendation.py); applying one to a new file like `product_roadmap.py` (created in PR #354, May 2026) directly inverts the decision's stated rationale ("monolith files degrade LLM execution quality"). Refactor is the canonical path.
- **rec-859 is a CI RCA rec (Critical priority)**, currently the sole entry in preflight's `ci_rca_recs`. Per the planning skill's hard-block rule, `/plan` cannot scope unrelated work while this is open; this plan directly addresses it (Related-Work Check condition #1: same file).
- **Note on rec-859 origin (from the rec context):** the rec was manually filed because the self-hosted runner IAM lacked `dynamodb:PutItem` at the time. rec-858 has since fixed the IAM gap (commit `a644c75`), so subsequent SLOC-violation recs will be filed automatically by ci-rca. This rec is the canonical open item for the `product_roadmap.py` refactor.
- **Test coverage enforcement (Decision 43 / `test_coverage_checker.py`):** for every changed `scripts/*.py`, a sibling `tests/test_{name}.py` must exist and reach 100% line coverage when invoked in isolation (the checker runs only the matching test file with `--cov={module}`, never the full suite). The new `scripts/product_roadmap_schema.py` therefore mandates the new `tests/test_product_roadmap_schema.py`.
- **Namespace migration discipline (`tests/CLAUDE.md`):** monolith-to-package refactors must update all `@patch("module.symbol")` call sites. None exist for `scripts.product_roadmap` today (`grep` confirmed: no `@patch.*product_roadmap` matches), so no test-site rewriting is required. The re-export pattern means future `@patch("scripts.product_roadmap.GateRuleParser")` calls will continue to work because the re-imported symbol lives in `scripts.product_roadmap`'s namespace as well as `scripts.product_roadmap_schema`'s.
- **Lambda Deployment Assessment:** N/A -- `scripts/product_roadmap.py` is not in `_LAMBDA_SCRIPTS` (it is a validate-time / preflight-time script, not a Lambda-packaged dependency).
- **Symbol-location decisions:**
  - `_SUPPORTED_VERSIONS`, `_OPS_DECISIONS_RE` move to `_schema` (only consumed by `DocumentMeta` validators).
  - `_LAYER_SHORTCUT_RE`, `_AGGREGATE_LAYER_SHORTCUTS`, `_CANONICAL_LAYER_ORDER` stay in `product_roadmap.py` (consumed by both `ProductRoadmapDocument._validate_graph` and `ProductRoadmapState` methods; keeping them next to their primary consumer avoids cross-module reach).
  - `_check_unique_ids` stays in `product_roadmap.py` (called only from `ProductRoadmapDocument._validate_graph`).
- **Caller surface (verified via `grep "from scripts.product_roadmap" --type=py`):**
  - `scripts/validate.py:1670` -- imports `load`.
  - `scripts/session_preflight.py:26` -- imports module as `product_roadmap_module`, uses `.compute_state_dict`.
  - `tests/test_product_roadmap.py:12,479,485,491,497,548,587` -- imports `GateRuleParser`, `ProductRoadmapDocument`, `load`, `FivePropertyWaiver`, `ProductRoadmapState`.
  - `tests/test_product_roadmap_state.py:8` -- imports `ProductRoadmapDocument`, `ProductRoadmapState`, `load`.
  - `tests/test_session_preflight_product_roadmap.py:14` -- imports `compute_state_dict`.
  None of these change.

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main` (`agent/product-roadmap-sloc-split`, created in Step 7 of /plan).
- [x] `docs/PROJECT_CONTEXT.md` read.
- [x] `docs/DECISIONS.md` Decision 43 read (governance rationale and waiver mechanism).
- [x] All files in Scope table located and readable (`scripts/product_roadmap.py` existing; new files paths verified writable).
- [x] Acceptance Criteria understood and verifiable -- every row has an executable command.

## Ordered Execution Steps
1. **Read** `scripts/product_roadmap.py` in full and the three existing test files (`tests/test_product_roadmap.py`, `tests/test_product_roadmap_state.py`, `tests/test_session_preflight_product_roadmap.py`) to map the precise public API surface to preserve. Pre-condition: branch is `agent/product-roadmap-sloc-split` (verify with `git branch --show-current`). Post-condition: agent has the list of public symbols to re-export.
2. **Create** `scripts/product_roadmap_schema.py` with: module docstring; `from __future__ import annotations` (preserves PEP 563 deferred evaluation for forward-string-references in validators such as `FivePropertyWaiver._check_non_empty` returning `"FivePropertyWaiver"`); stdlib + third-party imports (`re`, `sys`, `Any`, `Literal`, `BaseModel`, `ConfigDict`, `Field`, `ValidationInfo`, `field_validator`, `model_validator`); the two extracted constants (`_SUPPORTED_VERSIONS`, `_OPS_DECISIONS_RE`); `GateRuleParser`; and all 23 Pydantic model classes in their original declaration order (declaration order matters because validators with string forward-refs are resolved lazily). Pre-condition: step 1 complete. Post-condition: file exists, `bin/venv-python -c "from scripts.product_roadmap_schema import GateRuleParser, FivePropertyWaiver"` succeeds (one-time diagnostic only, not in acceptance).
3. **Modify** `scripts/product_roadmap.py`: delete the extracted code; add a single explicit re-export block of the form `from scripts.product_roadmap_schema import (GateHelper, DocumentMeta, ...all 22 model class names, GateRuleParser)  # noqa: F401` immediately after the stdlib imports; retain `_LAYER_SHORTCUT_RE`, `_AGGREGATE_LAYER_SHORTCUTS`, `_CANONICAL_LAYER_ORDER`, `_check_unique_ids`, `ProductRoadmapDocument`, `_item_dict`, `load`, `ProductRoadmapState`, `compute_state_dict`, and the `if __name__ == "__main__":` block; ensure `ProductRoadmapDocument._validate_graph` still references `GateRuleParser` (now imported via the re-export -- it resolves to the same class object). Pre-condition: step 2 complete. Post-condition: `bin/venv-python -m scripts.product_roadmap --check docs/ROADMAP-PRODUCT.yaml --platform docs/ROADMAP-PLATFORM.yaml` prints `PASS`.
4. **Create** `tests/test_product_roadmap_schema.py`: import each public class from `scripts.product_roadmap_schema`; write per-class construction tests with minimal valid data; for each `field_validator` / `model_validator`, write one positive case and one negative (rejection) case asserting the expected `ValueError` / `ValidationError`; for `GateRuleParser.validate`, cover (a) valid expression with known helper and correct arity, (b) unknown helper -> `ValueError`, (c) known helper with wrong arity -> `ValueError`, (d) nested parens and string-literal commas in argument counting; `_find_close` and `_count_args` are exercised transitively via `validate`. Pre-condition: step 3 complete. Post-condition: `bin/venv-python -m pytest tests/test_product_roadmap_schema.py --cov=scripts/product_roadmap_schema --cov-report=term-missing` reports 100% line coverage and all tests pass.
5. **Lint** the modified and new files: `bin/venv-python -m ruff format scripts/product_roadmap.py scripts/product_roadmap_schema.py tests/test_product_roadmap_schema.py` then `bin/venv-python -m ruff check --fix scripts/product_roadmap.py scripts/product_roadmap_schema.py tests/test_product_roadmap_schema.py`. Pre-condition: step 4 complete. Post-condition: both ruff commands exit 0.
6. **SLOC verification** in isolation: count both files using validate.py's exact formula and confirm both <= 500 BEFORE running the full presubmit (faster feedback). Diagnostic command (not part of acceptance): `bin/venv-python -c "import sys; [print(f, sum(1 for ln in open(f).read().splitlines() if ln.strip() and not ln.strip().startswith('#'))) for f in sys.argv[1:]]" scripts/product_roadmap.py scripts/product_roadmap_schema.py`. If either exceeds 500, return to step 3 and extract additional logical chunks (NOT add a waiver). Post-condition: both files <= 500 SLOC.
7. **Execute Verification Plan** -- run each of the 5 rows in the Verification Plan table in order. Loop until every step passes. Do NOT add a `# complexity-waiver: decision-43` annotation as a shortcut; the entire point of this plan is to clear the limit by reduction.
8. **Report**: summarise (a) the symbols moved, (b) final SLOC counts for both files, (c) the new test file's coverage percentage, (d) verification step results. Confirm rec-859 acceptance criterion is satisfied by quoting the relevant line from `validate --pre` output.
