# Plan

## Intent
Restore a green full-tier CI on `main` by marking the warehouse-parity tests as `integration`, so the post-DuckDB-migration read layer stays trustworthy and the planning queue is unblocked. Forward-fix for the ci-rca rec cluster rec-1999/rec-2000/rec-2001.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Plan Path
docs/plans/PLAN-warehouse-parity-integration-marker.md

## Phase
CI health forward-fix (ci_rca exception category; not a roadmap tier_item). Follows the DuckDB-on-Iceberg read-path swap merged in PR #23.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| tests/test_iceberg_reader.py | Modify | Add `@pytest.mark.integration` to `class TestWarehouseParity` so it is deselected from the `-m "not integration"` CI full tier and opts out of the `_clear_aws_credential_env` autouse fixture. |

## Bundled Recommendations
- **rec-1999** (ci_rca, Critical): "TestWarehouseParity defeated by _clear_aws_credential_env autouse in CI". This plan implements rec-1999's recommended fix and acceptance check. rec-2000 and rec-2001 are duplicate ci-rca filings for the same failure across different commit SHAs; this forward-fix resolves the underlying cause for all three. (Their diagnostic-quality divergence is being investigated separately by the user and is explicitly out of scope here.)

## Acceptance Criteria
- [ ] `class TestWarehouseParity` in `tests/test_iceberg_reader.py` carries the `@pytest.mark.integration` marker (rec-1999 acceptance: `grep -B2 'class TestWarehouseParity' tests/test_iceberg_reader.py | grep -q integration`).
- [ ] Under the CI selection `-m "not integration"`, the three `test_parity_*` tests are NOT collected (deselected), so the full-tier "Unit tests + coverage" step no longer fails on them.
- [ ] The three `test_parity_*` tests still exist and are collectable under `-m integration` (gated, not deleted).
- [ ] `bin/venv-python -m scripts.validate` "Unit tests + coverage" step passes locally (CI-equivalent full tier).

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Confirm the integration marker is applied to the class | `grep -B2 'class TestWarehouseParity' tests/test_iceberg_reader.py \| grep -q 'pytest.mark.integration' && echo MARKED` | Prints `MARKED` | Marker missing or placed on a method, not the class -- reapply above `class TestWarehouseParity`. |
| 2 | [pre-deploy] | Confirm parity tests are DESELECTED under CI selection | `bin/venv-python -m pytest tests/test_iceberg_reader.py -m "not integration" --collect-only -q 2>&1 \| grep -c 'test_parity_'` | Prints `0` (no parity tests collected) | Non-zero means the marker did not take -- check `--strict-markers` registration and decorator placement. |
| 3 | [pre-deploy] | Confirm parity tests still EXIST under the integration selection (not deleted) | `bin/venv-python -m pytest tests/test_iceberg_reader.py -m integration --collect-only -q 2>&1 \| grep -c 'test_parity_'` | Prints `3` | Fewer than 3 means a test was accidentally removed/renamed -- restore it. |
| 4 | [pre-deploy] | Run the file under the exact CI selection; unit tests pass, parity deselected | `bin/venv-python -m pytest tests/test_iceberg_reader.py -m "not integration" -p no:cacheprovider` | Exit 0; unit tests pass; 3 deselected; zero `test_parity_*` failures | Any `test_parity_*` failure means the class is still being collected -- re-verify step 1-2. |
| 5 | [pre-deploy] | Run the CI-equivalent full presubmit tier (the step that is red on main) | `bin/venv-python -m scripts.validate` | "Unit tests + coverage" step passes; no TestWarehouseParity failures | If it still fails on the parity tests, the marker/selection fix is incomplete -- return to step 1. Credential-dependent verifiers emitting SKIPPED in degraded mode is acceptable and unrelated. |

## Constraints
- Only `tests/test_iceberg_reader.py` is in scope. Do not modify `tests/conftest.py`, `src/common/iceberg_reader.py`, `scripts/aws_profile.py`, or `scripts/validate.py`.
- Do not remove or weaken the existing `@_skip_parity` skipif decorator -- it still provides graceful skipping for explicit `-m integration` runs when warehouse credentials are genuinely absent.
- Do not touch the ci-rca workflow or file/modify recommendations about the ci-rca agent's diagnostic quality -- the user is investigating that separately.
- No rescue agents or workaround loops (Decision 55). This is a forward-fix that aligns the test with its declared intent, not a CI bypass.

## Context
- **Root cause (collection-vs-execution credential skew):** `_warehouse_available = _has_warehouse_credentials()` is evaluated at module-import/collection time (`tests/test_iceberg_reader.py:375`), before any autouse fixture runs. On the OIDC CI runner `AWS_ACCESS_KEY_ID` is present at that moment, so `resolve_aws_profile()` (`scripts/aws_profile.py:32`) returns `None`, the reader uses ambient OIDC creds, `latest_snapshot()` succeeds, and the `@_skip_parity` skipif resolves to "do not skip". At test-execution time the `_clear_aws_credential_env` autouse fixture (`tests/conftest.py:54`) strips `AWS_ACCESS_KEY_ID` (its `integration`-marker opt-out at line 65 does not fire, because the class lacks that marker), so `resolve_aws_profile()` now falls through to the named `agent_platform` profile, which does not exist on the runner. `GlueCatalog` raises, `latest_snapshot()` returns `None`, and the three `assert snap_id is not None` assertions fail. The skip guard decided "don't skip" using credentials the runner then took away.
- **Why the fix works:** the module docstring already declares these as "Parity tests (integration, require warehouse credentials)". `scripts/validate.py` runs both the full tier ("Unit tests + coverage") and `--pre` with `pytest ... -m "not integration"`, and `integration` is a registered marker in `pyproject.toml` (`--strict-markers` safe). Adding `@pytest.mark.integration` deselects the class from those CI tiers (turning main green, matching the tests' stated intent) and opts it out of the `_clear_aws_credential_env` fixture, so any explicit `-m integration` run keeps the OIDC creds and resolves to ambient credentials.
- **Decision flag (Decision 73, NOTE -- no pivot):** Decision 73 previously criticised defining CI tiers "by exclusion of a barely-used `@pytest.mark.integration` marker." Here the marker is used to express genuine integration semantics (these tests require live warehouse credentials), not as a tier-shaping hack; `validate.py` still drives selection via `-m "not integration"`. This aligns the test with current reality rather than reintroducing a tier mechanism.
- **Decisions cited:** Decision 72 (RCA-as-Plan-Source for CI merge-gate failures -- the origin authority for this forward-fix), Decision 73 (two-tier diff-aware CI; full-tier-on-main failure -> ci-rca rec -> forward-fix path), Decision 48 (Verification Tier Classification -- pure pytest/marker scope with no V3 triggers is V2). CD.21 is relevant context (GitHub-hosted OIDC runners have ambient `AWS_ACCESS_KEY_ID` and no named `agent_platform` profile) but is a roadmap-code annotation, not a ratified Decision record.
- **Residual (noted, intentionally out of scope):** even when deselected, the module-level `_has_warehouse_credentials()` still executes a live Glue/S3 call at collection time on every pytest run (marker deselection happens post-collection). A transient AWS error there could fail collection of the whole file. Making that evaluation lazy is a reasonable follow-up but was explicitly deferred to keep this fix minimal per the human's "just the test fix" scope.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] docs/PROJECT_CONTEXT.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. In `tests/test_iceberg_reader.py`, add `@pytest.mark.integration` as a class decorator on `TestWarehouseParity`, stacked above the existing `@_skip_parity` decorator (leave `@_skip_parity` in place):
   ```python
   @pytest.mark.integration
   @_skip_parity
   class TestWarehouseParity:
   ```
2. **Execute Verification Plan** -- run each step in order. Loop until all pass. The authoritative gate is step 5 (`scripts.validate` "Unit tests + coverage"), mirroring the CI full tier that is red on main.
3. Report: the one-line change applied, and the verification results (especially that the three `test_parity_*` tests are deselected under `-m "not integration"` and that the full-tier unit step passes).
