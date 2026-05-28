# Plan

## Intent
Eliminate the class of silent credential and drain failures that have been routing ops recommendations
to the pending outbox instead of DynamoDB throughout the session lifecycle. After this lands, every
pre and postflight automatically ensures SSO is active, drains pending recs, and syncs to S3 --
requiring zero credential management from any agent or developer.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/ops-session-drain-automation

## Phase
Phase Platform (Automation Infrastructure) -- parallel track to Phase 1 (Core Infrastructure, COMPLETE)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/sync_recommendations.py` | Modify | Add `_SSO_PROFILE` constant; use as fallback in `next_id()` (line 63) and `seed_counters()` (line 117) |
| `scripts/ops_data_portal.py` | Modify | Add `_SSO_PROFILE` constant; add `profile: str \| None = None` to `drain_pending()`; fix drain line 244 to pass profile; fix `_delete_postmortems_from_iceberg` line 384 fallback; clean up CLI drain path |
| `scripts/ops_writer.py` | Modify | Add `_SSO_PROFILE` constant + Lambda-safe fallback in `_get_client()` (lines 137-142) and the `compact_all()` Athena client block (lines 618-623): use `_SSO_PROFILE` unless `AWS_LAMBDA_FUNCTION_NAME` is set |
| `scripts/session_preflight.py` | Modify | Rename `_ATHENA_PROFILE` → `_SSO_PROFILE` (line 44 + 6 usage sites); set `S3_LOG_BUCKET` default at startup; move `_handle_sso_startup` before `_sync_ops_pull`; add `drain_pending()` call after SSO confirmed; remove `s3_log_bucket_set` gate from sync |
| `scripts/session_postflight.py` | Modify | Add `_SSO_PROFILE` constant; add SSO re-check block before section 7c drain; pass `_SSO_PROFILE` to `drain_pending()` |
| `tests/test_sync_recommendations.py` | Modify | Add test: `next_id()` with `None` profile and no `AWS_PROFILE` env var calls `boto3.Session(profile_name=_SSO_PROFILE)` |
| `tests/test_ops_data_portal.py` | Modify | Add test: `drain_pending()` calls `_next_id` with SSO profile when no profile argument given |
| `tests/test_ops_writer.py` | Modify | Add tests for Lambda-safe fallback: non-Lambda env uses `_SSO_PROFILE`; Lambda env (`AWS_LAMBDA_FUNCTION_NAME` set) uses `None` (default credential chain) |
| `tests/test_session_preflight.py` | Modify | Add test verifying SSO startup precedes the ops pull step in `run_preflight()` |

## Bundled Recommendations
- **rec-633** (High/S): ops_data_portal DynamoDB client missing SSO profile fallback, pending drain
  uncoordinated with OpsWriter outbox. This plan is the implementation of rec-633 and closes it.

## Acceptance Criteria
- [ ] `grep -c '_SSO_PROFILE' scripts/sync_recommendations.py` returns `>= 1`
- [ ] `grep -c '_SSO_PROFILE' scripts/ops_data_portal.py` returns `>= 1`
- [ ] `grep '_SSO_PROFILE' scripts/session_postflight.py` returns a match
- [ ] `grep 'setdefault.*S3_LOG_BUCKET' scripts/session_preflight.py` returns a match
- [ ] SSO startup call precedes `_sync_ops_pull()` in `session_preflight.py`
- [ ] `drain_pending()` in `scripts/ops_data_portal.py` accepts a `profile` parameter
- [ ] `OpsWriter._get_client()` and Athena client block use Lambda-safe `_SSO_PROFILE` fallback
- [ ] `pytest tests/test_sync_recommendations.py tests/test_ops_data_portal.py tests/test_ops_writer.py tests/test_session_preflight.py -q` exits 0 (including new tests)
- [ ] `.venv/Scripts/python.exe -m scripts.ops_data_portal --drain` exits 0 without "credentials missing" warning
- [ ] `.venv/Scripts/python.exe -m scripts.build_lambda --deploy` exits 0 and Lambda is updated with the new `ops_writer.py`
- [ ] `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness` exits 0 after deploy

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-----------------|--------|
| 1 | [pre-deploy] | `_SSO_PROFILE` constant present in all credential-allocation files | `.venv/Scripts/python.exe -c "files=['scripts/sync_recommendations.py','scripts/ops_data_portal.py','scripts/ops_writer.py','scripts/session_postflight.py']; bad=[f for f in files if open(f).read().count('_SSO_PROFILE')<1]; assert not bad, f'Missing _SSO_PROFILE: {bad}'; print('ok')"` | `ok` | Add missing constant to each failing file |
| 2 | [pre-deploy] | `S3_LOG_BUCKET` default wired in preflight | `.venv/Scripts/python.exe -c "import re; c=open('scripts/session_preflight.py').read(); assert re.search(r'setdefault.*S3_LOG_BUCKET', c), 'setdefault not found'; print('ok')"` | `ok` | Add `os.environ.setdefault("S3_LOG_BUCKET", "agent-platform-agent-logs")` near start of `run_preflight()` |
| 3 | [pre-deploy] | SSO startup precedes pull in preflight | `.venv/Scripts/python.exe -c "lines=open('scripts/session_preflight.py').read().splitlines(); sso=next(i for i,l in enumerate(lines) if '_handle_sso_startup' in l and 'sso_status' in l); pull=next(i for i,l in enumerate(lines) if '_sync_ops_pull()' in l); assert sso < pull, f'SSO at {sso} is AFTER pull at {pull}'; print(f'ok: SSO at {sso}, pull at {pull}')"` | `ok: SSO at N, pull at M` where N < M | Swap the blocks -- SSO must come before pull |
| 4 | [pre-deploy] | `drain_pending()` accepts `profile` parameter | `.venv/Scripts/python.exe -c "from scripts.ops_data_portal import drain_pending; import inspect; p=inspect.signature(drain_pending).parameters; assert 'profile' in p, 'profile param missing'; print('ok')"` | `ok` | Add `profile: str \| None = None` to `drain_pending()` signature |
| 5 | [pre-deploy] | All new and existing tests pass in affected modules | `.venv/Scripts/python.exe -m pytest tests/test_sync_recommendations.py tests/test_ops_data_portal.py tests/test_ops_writer.py tests/test_session_preflight.py -q` | All green, no failures | Fix the failing test; if a mock is broken, re-read the changed code path |
| 6 | [pre-deploy] | Full test suite exits clean | `.venv/Scripts/python.exe -m pytest --tb=short -q` | Exit 0 | Investigate any new failures introduced by signature or ordering changes |
| 7 | [post-deploy] | Lambda built and deployed with updated `ops_writer.py` | `.venv/Scripts/python.exe -m scripts.build_lambda --deploy` | Exits 0; Lambda function code updated | Syntax error in `ops_writer.py`: run `ruff check --fix scripts/ops_writer.py` and retry |
| 8 | [post-deploy] | Lambda runtime loads new `OpsWriter` with SSO fallback | `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness` | Exit 0; no import or credential error in CloudWatch | Check CloudWatch `/aws/lambda/agent-platform-scheduled-agent-dispatcher`; likely a packaging error -- re-run build step |

## Constraints
- `_handle_sso_startup` in `session_preflight.py` already calls `aws sso login --profile company-aws-profile` interactively when status is "expired" and hard-exits if the login fails. Do not re-implement this -- only reorder it.
- The postflight SSO re-check must NOT call `sys.exit`. It is best-effort (wrapped in `try/except`) and continues regardless. Only preflight hard-exits on SSO failure.
- `OpsWriter.write()` is already guarded by `PYTEST_CURRENT_TEST` -- giving `S3_LOG_BUCKET` a default via `setdefault` will not cause tests to write to S3.
- `s3_log_bucket_set` must remain in the preflight JSON report (other tooling reads it). Keep the variable; only remove the warning block and the `and s3_log_bucket_set` condition on the sync gate.
- **Lambda-safe fallback pattern**: `ops_writer.py` is Lambda-deployed; SSO profiles do not exist in Lambda. Any `_SSO_PROFILE` fallback in that file MUST be guarded: `profile or os.environ.get("AWS_PROFILE") or (None if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else _SSO_PROFILE)`. For non-Lambda files (`sync_recommendations.py`, `ops_data_portal.py`) the direct fallback is fine.
- `session_preflight.py` uses `_ATHENA_PROFILE = "company-aws-profile"` (line 44). Rename to `_SSO_PROFILE` at line 44 and update all 6 usage sites. Do not change the underlying string value.
- No rescue agents or workaround loops (Decision 55).

## Context
- **rec-633 root cause**: `sync_recommendations.next_id()` uses `profile or os.environ.get("AWS_PROFILE")` with no constant fallback. When called without `--profile` and `AWS_PROFILE` is unset, `boto3.Session(profile_name=None)` falls back to default credential resolution, which cannot find the SSO token. `sync_ops.py` already has `_SSO_PROFILE = "company-aws-profile"` and always passes it -- this plan brings `sync_recommendations.py` and `ops_data_portal.py` to parity.
- **drain double-bug**: `drain_pending()` has no `profile` parameter, so its internal `_next_id("recommendations")` call (line 244) cannot forward the profile. The CLI workaround (`os.environ["AWS_PROFILE"] = args.profile`) only helps the `--drain` CLI path and leaves the `session_postflight.py` call with no profile at all.
- **Preflight ordering bug**: `_sync_ops_pull()` runs at line 948, BEFORE `_handle_sso_startup()` at line 958. So pull always runs against a potentially expired session, silently failing. Reordering is a 1-for-1 block swap -- no logic changes.
- **S3_LOG_BUCKET double-gate**: `sync_ops_sync()` in preflight is gated on `sso_status == "ok" AND s3_log_bucket_set`. Since `S3_LOG_BUCKET` is unset in the developer environment, sync is silently skipped even when SSO is valid. `os.environ.setdefault()` gives it a value at preflight start, making the gate purely SSO-dependent as intended.
- `session_preflight.py` uses `_ATHENA_PROFILE = "company-aws-profile"` (line 44, 6 usage sites). Rename to `_SSO_PROFILE` for grep-consistency. The `_SSO_PROFILE` constant added to `session_postflight.py` must be the same value.
- `ops_writer.py` has two credential-blind spots: `_get_client()` at lines 137-142 (S3 client) and the Athena client block at lines 618-623 inside `compact_all()`. Both use `os.environ.get("AWS_PROFILE")` with no fallback. The Lambda-safe pattern resolves both. `ops_writer.py` is in `_LAMBDA_SCRIPTS` (build_lambda.py line 45).
- Decision 51 (Local-First Outbox + Bidirectional Sync): drain is local-first; this plan formalises that drain runs at both session open and session close.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` decisions checked (Decision 51, Decision 55)
- [ ] All 7 files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable via VP commands above

## Ordered Execution Steps

1. **`scripts/ops_writer.py`** -- Lambda-safe SSO fallback (S3 client + Athena client):
   - After module constants, add: `_SSO_PROFILE = "company-aws-profile"`
   - `_get_client()` lines 137-142: change
     ```python
     profile = os.environ.get("AWS_PROFILE")
     if profile:
         session = _boto3.Session(profile_name=profile)
         ...
     else:
         self._client = _boto3.client("s3", region_name="eu-west-2")
     ```
     to:
     ```python
     _is_lambda = bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
     profile = os.environ.get("AWS_PROFILE") or (None if _is_lambda else _SSO_PROFILE)
     if profile:
         session = _boto3.Session(profile_name=profile)
         ...
     else:
         self._client = _boto3.client("s3", region_name="eu-west-2")
     ```
   - Apply the same pattern to the Athena client block at lines 618-623 in `compact_all()`.
   - Run `ruff check --fix scripts/ops_writer.py` after editing.

2. **`scripts/sync_recommendations.py`** -- profile fallback (foundation):
   - After `_AWS_REGION = "eu-west-2"` (line 32), add: `_SSO_PROFILE = "company-aws-profile"`
   - Line 63: `_profile = profile or os.environ.get("AWS_PROFILE")` → `_profile = profile or os.environ.get("AWS_PROFILE") or _SSO_PROFILE`
   - Line 117: identical one-line change in `seed_counters()`

3. **`scripts/ops_data_portal.py`** -- profile fallback + drain fix:
   - After `_PENDING_OUTBOX = ...` (around line 44), add: `_SSO_PROFILE = "company-aws-profile"`
   - `drain_pending()` signature: `def drain_pending(profile: str | None = None) -> dict:`
   - Line 244: `rec_id = _next_id("recommendations")` → `rec_id = _next_id("recommendations", profile=profile or _SSO_PROFILE)`
   - Line 384 (`_delete_postmortems_from_iceberg`): `_profile = profile or os.environ.get("AWS_PROFILE")` → `_profile = profile or os.environ.get("AWS_PROFILE") or _SSO_PROFILE`
   - CLI drain path (lines 697-700): remove `if args.profile: os.environ["AWS_PROFILE"] = args.profile`; change `result = drain_pending()` → `result = drain_pending(profile=args.profile)`

4. **`scripts/session_preflight.py`** -- rename + ordering + defaults + drain:
   - Line 44: rename `_ATHENA_PROFILE = "company-aws-profile"` → `_SSO_PROFILE = "company-aws-profile"`; update all 6 usage sites (lines 188, 196, 233, 264, 297, 755).
   - Before `venv_ok = check_venv()` (line 935), add: `os.environ.setdefault("S3_LOG_BUCKET", "agent-platform-agent-logs")`
   - Move the `_sync_ops_pull()` try/except block (lines 946-951) to AFTER `sso_status = _handle_sso_startup(check_sso_status())` (currently line 958)
   - After the SSO line (now confirmed valid), add a best-effort `drain_pending()` call:
     ```python
     try:
         from scripts.ops_data_portal import drain_pending  # noqa: PLC0415
         _drain = drain_pending()
         if _drain.get("drained", 0) > 0:
             print(f"[preflight] Drained {_drain['drained']} pending rec(s)", file=sys.stderr)
     except Exception:  # noqa: BLE001
         pass
     ```
   - Delete the S3_LOG_BUCKET warning block (lines 960-965)
   - Line 980: change `if sso_status == "ok" and s3_log_bucket_set:` → `if sso_status == "ok":`

5. **`scripts/session_postflight.py`** -- SSO re-check + drain profile:
   - After module-level imports (around line 40), add: `_SSO_PROFILE = "company-aws-profile"`
   - Before section 7c (before line 675), insert a best-effort SSO re-check:
     ```python
     # Re-check SSO -- token may expire during long sessions; best-effort, never blocks close.
     try:
         from scripts.sync_ops import check_sso as _check_sso  # noqa: PLC0415
         if not _check_sso(_SSO_PROFILE):
             subprocess.run(["aws", "sso", "login", "--profile", _SSO_PROFILE], check=False, timeout=300)
     except Exception as exc:  # noqa: BLE001
         print(f"WARNING: SSO re-check before drain skipped: {exc}", file=sys.stderr)
     ```
   - Line 679: `drain_result = drain_pending()` → `drain_result = drain_pending(profile=_SSO_PROFILE)`

6. **`tests/test_ops_writer.py`** -- Lambda-safe fallback coverage:
   - In `TestOpsWriterWrite` (or a new `TestOpsWriterGetClient`), add two tests:
     - `test_get_client_uses_sso_profile_outside_lambda`: unset `AWS_LAMBDA_FUNCTION_NAME`, mock `boto3.Session`, call `OpsWriter()._get_client()`, assert `boto3.Session` was called with `profile_name=_SSO_PROFILE`.
     - `test_get_client_uses_default_chain_in_lambda`: set `AWS_LAMBDA_FUNCTION_NAME=test-fn`, mock `boto3.client`, call `OpsWriter()._get_client()`, assert `boto3.client` was called (not `boto3.Session`) -- i.e. no profile was passed.

7. **`tests/test_sync_recommendations.py`** -- profile fallback coverage:
   - In the existing `TestNextId` class, add `test_uses_sso_profile_fallback_when_no_env_var`: mock `boto3.Session`, ensure `AWS_PROFILE` is unset, call `next_id("recommendations")` with no `profile` arg, assert `boto3.Session` was called with `profile_name=_SSO_PROFILE`.

8. **`tests/test_ops_data_portal.py`** -- drain profile coverage:
   - In the existing `TestDrainPending` class, add `test_drain_passes_sso_profile_to_next_id`: create one pending file, mock `_next_id` to return `"rec-900"`, mock `OpsWriter`, call `drain_pending()` with no args, assert `_next_id` was called with `profile=_SSO_PROFILE` (or at minimum `profile` was not `None`).

9. **`tests/test_session_preflight.py`** -- ordering coverage:
   - Add `test_sso_startup_precedes_pull`: mock `_handle_sso_startup`, `check_sso_status`, and `_sync_ops_pull`; run the preflight main flow; assert `_handle_sso_startup` was called before `_sync_ops_pull` by capturing call order.

10. **Build and deploy Lambda** (VP#7): `.venv/Scripts/python.exe -m scripts.build_lambda --deploy`. Confirm exit 0.

11. **Smoke test Lambda runtime** (VP#8): `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test doc-freshness`. Confirm exit 0.

12. **Execute Verification Plan** -- run each VP step sequentially. Loop on any failure until all 8 pass.

13. **Close rec-633** via portal:
    `.venv/Scripts/python.exe -m scripts.ops_data_portal --profile company-aws-profile --update-rec rec-633 --status closed --execution_result success --execution_branch agent/ops-session-drain-automation --resolution "Added Lambda-safe _SSO_PROFILE constant to ops_writer.py, sync_recommendations.py, and ops_data_portal.py; fixed drain_pending() profile passthrough; renamed _ATHENA_PROFILE to _SSO_PROFILE in session_preflight.py; set S3_LOG_BUCKET default; reordered SSO before pull; added preflight and postflight drain automation."`

14. **Report**: confirm all 9 files changed, Lambda smoke test result, VP pass/fail counts, rec-633 closed.
