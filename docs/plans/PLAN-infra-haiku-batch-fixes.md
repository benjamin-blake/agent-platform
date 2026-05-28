# Plan

## Intent
Reduce technical debt and improve system reliability by fixing a batch of S/M effort code quality issues from open recommendations, while also automating session startup friction (venv activation and SSO login) that repeatedly blocks planning sessions.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-haiku-batch-fixes

## Phase
Phase 1: Core Infrastructure (maintenance)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `src/common/config.py` | Modify | Fix `validate()` to reject empty strings for required fields |
| `src/data/feature_engine.py` | Modify | Log warning and continue retry loop on malformed JSON (no score field) |
| `src/execution/async_engine.py` | Modify | Widen circuit breaker to catch `Exception` (excluding cancellation) |
| `src/meta_learner/gating_network.py` | Modify | Add `.eval()` mode in `compute_model_weights()` inference path |
| `setup.py` | Modify | Make pre-commit path cross-platform (Windows `.venv/Scripts/pre-commit` vs Unix `.venv/bin/pre-commit`) |
| `scripts/build_lambda.py` | Modify | Add `validate_bucket_exists()` check before upload |
| `tests/test_plan_audit.py` | Modify | Add tests for `parse_scope_table`, `get_changed_files`, `file_existed_on_main`, `paths_match`, `normalise` |
| `docs/RECOMMENDATIONS.md` | Modify | Mark 2 resolved items (database.py connection reuse, setup.py AWS config) |
| `.github/prompts/plan.prompt.md` | Modify | Auto-activate venv and auto-run `aws sso login` at Step 0 |
| `tests/test_config.py` | Modify | Add test for empty string rejection in validate() |
| `tests/test_feature_engine.py` | Create | Add test for retry behavior on malformed JSON (no score field) |
| `tests/test_async_engine.py` | Create | Add test for widened circuit breaker exception handling |
| `tests/test_meta_learner.py` | Create | Add test for `.eval()`/`.train()` mode switching in inference |
| `tests/test_build_lambda.py` | Create | Add test for `validate_bucket_exists()` function |
| `tests/test_setup.py` | Modify | Add test for cross-platform pre-commit path logic |

## Acceptance Criteria
- [ ] `config.validate()` raises `ValueError` when a required field is empty string `""`
- [ ] `_fetch_fear_greed_index()` logs warning on malformed JSON and retries (does not break loop)
- [ ] `async_engine.trading_loop()` circuit breaker catches all exceptions except `KeyboardInterrupt`, `SystemExit`, `asyncio.CancelledError`
- [ ] `gating_network.compute_model_weights()` calls `self.gating_network.eval()` before inference
- [ ] `setup.py` pre-commit install works on both Windows and Unix
- [ ] `build_lambda.py` validates bucket exists before attempting upload (logs warning and exits on missing bucket)
- [ ] `tests/test_plan_audit.py` covers `parse_scope_table`, `get_changed_files`, `file_existed_on_main`, `paths_match`, `normalise`
- [ ] `tests/test_feature_engine.py` covers retry behavior on malformed JSON
- [ ] `tests/test_async_engine.py` covers widened circuit breaker exception handling
- [ ] `tests/test_meta_learner.py` covers `.eval()`/`.train()` mode switching
- [ ] `tests/test_build_lambda.py` covers `validate_bucket_exists()` function
- [ ] `tests/test_setup.py` covers cross-platform pre-commit path for `win32` and `linux`
- [ ] `RECOMMENDATIONS.md` has 2 items marked as resolved (database.py connection reuse, setup.py AWS config)
- [ ] `plan.prompt.md` Step 0 auto-activates venv if `venv_ok: false` and auto-runs SSO login if `sso_status: "expired"`
- [ ] All tests pass: `pytest tests/`
- [ ] Validation passes: `python scripts/validate.py`

## Constraints
- Python 3.12+, type hints required
- Windows developer (bash syntax for terminal, Python for automation)
- No Docker on company VM
- AWS profile: `company-aws-profile` only

## Context
- These are all from open recommendations in `docs/RECOMMENDATIONS.md`
- The venv/SSO friction has been observed in multiple sessions (see friction_patterns in preflight report)
- Phase 1 is complete; this is maintenance work clearing technical debt

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
> **Execute these in sequence. Do not substitute the Scope table as a work list.**

1. **Fix `config.py` validate() empty string check**
   - In `src/common/config.py`, modify the `validate()` method
   - Change the check from `if self.get(key) is None` to `if not self.get(key)` (catches both `None` and `""`)
   - This ensures empty strings are rejected for required fields

2. **Add test for config.validate() empty string rejection**
   - In `tests/test_config.py`, add a test that verifies `validate()` raises `ValueError` when a required field is set to `""`
   - Use a temporary config file with `aws.region: ""` and verify the exception

3. **Fix `feature_engine.py` retry loop on malformed JSON**
   - In `src/data/feature_engine.py`, modify `_fetch_fear_greed_index()`
   - Change the `break` after `if score is not None` block to `logger.warning("Malformed response (no score field), retrying...")` followed by `continue` (not `break`)
   - Only break after all 3 retries exhausted

4. **Add test for feature_engine retry behavior**
   - Create `tests/test_feature_engine.py`
   - Add a test that mocks the requests.get response to return valid JSON without the `score` field
   - Verify that the function logs a warning and retries (use mock to verify 3 attempts)
   - Verify it returns `None` after exhausting retries

5. **Fix `async_engine.py` circuit breaker exception handling**
   - In `src/execution/async_engine.py`, modify `trading_loop()`
   - Change `except (ConnectionError, TimeoutError) as e:` to `except Exception as e:`
   - Keep the existing `except (KeyboardInterrupt, SystemExit):` and `except asyncio.CancelledError:` handlers BEFORE the general Exception handler
   - This ensures all unexpected errors are counted by the circuit breaker

6. **Add test for async_engine circuit breaker**
   - Create `tests/test_async_engine.py`
   - Add a test that verifies the circuit breaker counts generic `Exception` (e.g., `ValueError`)
   - Verify that after 5 consecutive failures, the loop breaks with critical log
   - Use asyncio test utilities and mock the market_data_stream

7. **Fix `gating_network.py` missing eval() mode**
   - In `src/meta_learner/gating_network.py`, modify `compute_model_weights()`
   - Before the `with torch.no_grad():` block, add `self.gating_network.eval()`
   - After the inference, add `self.gating_network.train()` to restore training mode
   - This ensures Dropout layers are disabled during inference

8. **Add test for gating_network eval/train mode**
   - Create `tests/test_meta_learner.py`
   - Add a test that verifies `compute_model_weights()` sets the network to eval mode during inference
   - Verify the network is restored to train mode after inference
   - Use `torch.nn.Module.training` attribute to check mode

9. **Fix `setup.py` cross-platform pre-commit path**
   - In `setup.py`, modify `install_precommit()`
   - Replace hardcoded `.venv/Scripts/pre-commit` with a platform check:
     ```python
     import sys
     pre_commit_path = ROOT / ".venv" / ("Scripts" if sys.platform == "win32" else "bin") / "pre-commit"
     ```

10. **Add bucket validation to `build_lambda.py`**
    - In `scripts/build_lambda.py`, add a `validate_bucket_exists()` function that uses `aws s3api head-bucket` to verify the bucket exists
    - Call it in `main()` after `resolve_bucket()` and before `upload_to_s3()`
    - If bucket doesn't exist, print error message and exit with code 1

11. **Add test for build_lambda bucket validation**
    - Create `tests/test_build_lambda.py`
    - Add a test that mocks subprocess.run for `aws s3api head-bucket`
    - Test both success case (bucket exists) and failure case (bucket doesn't exist)
    - Verify the function returns True/False appropriately

12. **Add test for setup.py cross-platform pre-commit path**
    - In `tests/test_setup.py`, add a test that mocks `sys.platform` as `"win32"` and verifies the pre-commit path uses `Scripts/`
    - Add a second test that mocks `sys.platform` as `"linux"` and verifies the path uses `bin/`

13. **Add tests for `plan_audit.py` untested functions**
    - In `tests/test_plan_audit.py`, add tests for:
      - `parse_scope_table()`: test with valid table, empty table, malformed table
      - `get_changed_files()`: mock subprocess calls, test both origin/main and HEAD fallback
      - `file_existed_on_main()`: mock subprocess, test exists/not-exists cases
      - `paths_match()`: test exact match, partial match, backslash normalization
      - `normalise()`: test forward/backward slash conversion
    - Target: at least 5 new tests covering these functions

14. **Mark resolved items in RECOMMENDATIONS.md**
    - In `docs/RECOMMENDATIONS.md`, add strikethrough markup to:
      - `database.py:103-119 PostgresClient recreates connection` — already fixed (has connection reuse check)
      - `setup.py reads ~/.aws/config without FileNotFoundError` — code no longer exists
    - Add resolution notes with date

15. **Update `plan.prompt.md` for venv/SSO automation**
    - In `.github/prompts/plan.prompt.md`, modify Step 0:
    - If `venv_ok: false`:
      - Run `source .venv/Scripts/activate` **once**
      - Re-run `python scripts/session_preflight.py` to verify
      - If still `venv_ok: false` after one attempt, STOP and report — do not retry again
    - If `sso_status: "expired"` or `"unknown"`:
      - Run `aws sso login --profile company-aws-profile` **once** automatically
      - If the command fails, STOP and report — do not retry
      - Continue only after login completes successfully

16. Run `pytest tests/` — all tests must pass before proceeding

17. Run `python scripts/validate.py` — must exit 0

18. Report what was implemented and any design decisions made during implementation
