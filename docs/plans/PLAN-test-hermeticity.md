# Plan

## Intent
Make the pytest unit suite hermetic (no clock, network, filesystem-order, test-order, or shared-state dependence) and enforce this permanently in CI via randomised order and network-block, satisfying the explicit precondition for CD.29 (validation hard-gate consolidation) and CD.27 (executor hermetic verify).

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Plan Path
docs/plans/PLAN-test-hermeticity.md

## Phase
T3 - Reliability & Observability

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `requirements.txt` | Modify | Add `pytest-randomly>=3.15` and `pytest-socket>=0.7` |
| `requirements-fast.txt` | Modify | Add `pytest-randomly>=3.15` and `pytest-socket>=0.7` |
| `pyproject.toml` | Modify | Add `--randomly-seed=last`, `--disable-socket`, AND `--allow-hosts=127.0.0.1,::1` (all three) to `[tool.pytest.ini_options]` addopts; register `network` marker. `--allow-hosts` is mandatory alongside `--disable-socket` so validate.py's `pytest tests/` invocation does not block localhost fixtures (in-process DuckDB/SQLite) |
| `tests/conftest.py` | Modify | Add autouse `_allow_network_for_integration` fixture re-enabling sockets for `@pytest.mark.integration` tests only |
| `tests/test_iceberg_reader.py` | Modify | Fix rec-2006: move module-level `_warehouse_available = _has_warehouse_credentials()` call (line 375) into a lazy fixture |
| `tests/test_ducklake_spike.py` | Modify | Fix BOTH module-level live calls (line 58 `_creds_available = _has_spike_credentials()` and line 59 `_ducklake_available = _has_ducklake_extension()`): defer each to a lazy fixture. `_has_ducklake_extension()` runs `INSTALL ducklake; LOAD ducklake` (a network download), so the integration tests gated on it require `@pytest.mark.network` or `@pytest.mark.integration` quarantine, not just credential-guard deferral |
| `scripts/validate.py` | Modify | Extend "Unit tests + coverage" invocation to pass `--disable-socket --randomly-seed=last` explicitly (fail CI if hermeticity flags are absent) |
| `tests/test_validate.py` | Modify | Add regression tests for the hermeticity assertion path (100% coverage of new validate.py lines, per Decision 48) |
| `docs/AUDIT-test-hermeticity.yaml` | Create | Machine-readable audit report: per-test root-cause class and disposition (fix / quarantine / integration-exempt) |

## Bundled Recommendations
- **rec-2006** (fix): Move `_warehouse_available = _has_warehouse_credentials()` module-level call in `tests/test_iceberg_reader.py` to a lazy fixture; acceptance: `grep -qF '_warehouse_available' tests/test_iceberg_reader.py` fails (line removed from module scope)
- **rec-612** (verify + close as already_implemented): Run `tests/test_scheduled_agent_handler.py` under the hermetic harness; all 42 tests pass — rec was filed before the fix was applied; close via `python -m scripts.ops_data_portal update_rec rec-612 status=already_implemented`

## Infrastructure Dependencies
None. No `.tf` files in scope.

## Acceptance Criteria
- [ ] `bin/venv-python -m pytest tests/ -m "not integration" --randomly-seed=12345 --disable-socket` exits 0 with zero failures
- [ ] `bin/venv-python -m pytest tests/ -m "not integration" --randomly-seed=99999 --disable-socket` exits 0 (order-independence confirmed across two distinct seeds)
- [ ] `bin/venv-python -m scripts.validate` (full suite, no flags) exits 0
- [ ] `docs/AUDIT-test-hermeticity.yaml` exists and contains an entry for every non-hermetic test identified during the audit run, each with `root_cause_class` and `disposition` fields
- [ ] rec-2006 closed (status=fixed) via ops portal
- [ ] rec-612 closed (status=already_implemented) via ops portal
- [ ] Module-level live calls removed from `tests/test_iceberg_reader.py` and `tests/test_ducklake_spike.py`
- [ ] `ruff check tests/ scripts/validate.py` exits 0 (no new lint violations)

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | pre-deploy | Install new packages into venv | `bin/venv-python -m pip install pytest-randomly pytest-socket --quiet && bin/venv-python -c "import pytest_randomly, pytest_socket; print('ok')"` | Prints `ok` | pip install error: check requirements.txt version pins; ensure venv active |
| 2 | pre-deploy | Confirm socket-block flags accepted by pytest | `bin/venv-python -m pytest --co --disable-socket --allow-hosts=127.0.0.1,::1 tests/ -q 2>&1 \| head -5` | Collection succeeds (no "unrecognised arguments" error) | pytest-socket not installed or wrong version |
| 3 | pre-deploy | Confirm random seed flag accepted | `bin/venv-python -m pytest --co --randomly-seed=12345 tests/ -q 2>&1 \| head -5` | Collection succeeds; seed line printed | pytest-randomly not installed |
| 4 | pre-deploy | Run unit suite seed A (order test) | `bin/venv-python -m pytest tests/ -m "not integration" --randomly-seed=12345 --disable-socket --allow-hosts=127.0.0.1,::1 -q 2>&1 \| tail -5` | `N passed` with zero failures/errors | See audit YAML for per-test disposition; quarantine tests must be marked integration or network |
| 5 | pre-deploy | Run unit suite seed B (order-independence) | `bin/venv-python -m pytest tests/ -m "not integration" --randomly-seed=99999 --disable-socket --allow-hosts=127.0.0.1,::1 -q 2>&1 \| tail -5` | Same pass count as seed A, zero failures | Test is order-dependent; add explicit setup/teardown isolation |
| 6 | pre-deploy | Confirm rec-2006 fix: no module-level warehouse call | `grep -n '_warehouse_available = _has_warehouse_credentials' tests/test_iceberg_reader.py; echo "exit:$?"` | No lines printed (exit:1 means grep found nothing — that's the success signal) | Module-level call still present; move to fixture |
| 6b | pre-deploy | Confirm ducklake fix: no module-level live calls | `grep -nE '_creds_available\s*=\s*_has_spike_credentials\|_ducklake_available\s*=\s*_has_ducklake_extension' tests/test_ducklake_spike.py; echo "exit:$?"` | No lines printed (exit:1 means grep found nothing — that's the success signal) | Module-level call still present; defer both to fixtures |
| 7 | pre-deploy | Confirm rec-612 tests pass under harness | `bin/venv-python -m pytest tests/test_scheduled_agent_handler.py --disable-socket --allow-hosts=127.0.0.1,::1 -q 2>&1 \| tail -3` | `42 passed` | Handler test mocks missing network calls; fix mock coverage |
| 8 | pre-deploy | Full validate (hermeticity assertion present) | `bin/venv-python -m scripts.validate 2>&1 \| tail -20` | All checks pass; "Unit tests + coverage" step shows `--disable-socket` in invocation log | validate.py not passing hermeticity flags; review the modified invoke_step call |
| 9 | pre-deploy | Audit YAML exists and is well-formed | `bin/venv-python -c "import yaml; d=yaml.safe_load(open('docs/AUDIT-test-hermeticity.yaml')); assert 'tests' in d and len(d['tests']) > 0; print(f'{len(d[\"tests\"])} entries')"` | Prints `N entries` (N > 0) | YAML missing or malformed; check file write step |
| 10 | pre-deploy | Lint clean | `bin/venv-python -m ruff check tests/conftest.py tests/test_iceberg_reader.py tests/test_ducklake_spike.py tests/test_validate.py scripts/validate.py` | Exit 0, no violations | Fix reported ruff errors before pushing |
| 11 | pre-deploy | New test_validate.py lines covered | `bin/venv-python -m pytest tests/test_validate.py --cov=scripts.validate --cov-report=term-missing -q 2>&1 \| grep -E "(TOTAL|validate)"` | Coverage for new hermeticity assertion lines shows 100% (no missing lines) | Add missing test cases for new code paths in validate.py |

## Constraints
- Do NOT modify any Bedrock-related test logic. CD.28 boundary: `PLAN-retire-bedrock-code-paths` owns that surface.
- Do NOT modify `scripts/verifiers/` runtime code. Verifier modules are integration-by-design; only their unit tests (which mock live calls) are in scope.
- T2.15 (CI verification-coverage restoration) is NOT bundled. Its three restorations are each individually gated on CD.17/T3.2/T3.3/T4.2; bundling would produce blocked work.
- `--disable-socket` addopt MUST be accompanied by `--allow-hosts=127.0.0.1,::1` to permit localhost fixtures (e.g. in-process DuckDB, SQLite).
- Hermeticity assertion (new validate.py lines) must land in the full presubmit tier only, NOT the `--pre` edit-loop tier. Decision 60/73 two-tier model: `--pre` runs lint/format/prompts; hermeticity is a test-execution check.
- No rescue agents or workaround loops (Decision 55). Any test that cannot be made hermetic cheaply is quarantined via `@pytest.mark.integration` or `@pytest.mark.network` + documented in the audit YAML with `disposition: quarantine`.
- All recommendation closes go through `python -m scripts.ops_data_portal` — never directly edit `logs/.recommendations-log.jsonl`.
- New recs touching `scripts/verifiers/` must be filed with `automatable: false` per Decision 44.

## Context
- T2.1 (pre-condition) is complete; T3.6 is fully unblocked.
- Decision 67/CD.16 Lambda-deploy freeze is NOT engaged: `tests/` is not Lambda-packaged.
- CD.29 (validation hard-gate consolidation) is explicitly gated on hermeticity being in place; this plan satisfies that gate.
- CD.27 (executor compute = Step Functions + Lambda Durable Functions) lists hermetic verify as a dependency; this plan satisfies that dependency.
- CD.30 (unified executor telemetry) is pending on T3.7; `docs/AUDIT-test-hermeticity.yaml` is an input to that work.
- Branch was current with main at planning time (0 commits behind).
- `pytest-randomly` and `pytest-socket` are NOT currently in requirements.txt, requirements-fast.txt, or pyproject.toml — both must be added.
- Current non-hermetic surface (from grep audit): ~27 test files reference live network calls (boto3/requests/urllib/yfinance/socket); 8 have clock dependence; 2 have module-level live calls (test_iceberg_reader.py + test_ducklake_spike.py); 1 has random-without-seed. Only 2 tests carry `@pytest.mark.integration` today.
- rec-612 was filed when 37 tests in test_scheduled_agent_handler.py were failing. All 42 now pass — the fix was applied in a prior session. Close as `already_implemented` after verifying under the hermetic harness.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` consulted (via decision-scout gate — NO_FLAGS, CITE list above)
- [ ] All files in Scope table located and read
- [ ] `tests/conftest.py` autouse fixture pattern understood (mirror `_clear_aws_credential_env` / `_block_llm_cli_subprocess` opt-out structure)
- [ ] `scripts/validate.py` "Unit tests + coverage" invocation read (lines 2075-2088)
- [ ] `pyproject.toml` `[tool.pytest.ini_options]` addopts read (current: `-v --strict-markers --tb=short --disable-warnings`)
- [ ] rec-2006 and rec-612 retrieved from ops portal before closing
