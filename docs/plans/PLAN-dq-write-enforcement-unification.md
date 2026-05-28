# Plan

## Intent
Close the three confirmed write-path bypass routes that produced invalid rows in
`ops_recommendations` after wave-2 DQ graduation, and implement the `ops.yaml` `write_time`
dispatch so the portal and DQ runner share one enforcement surface -- structurally eliminating
dual-maintenance drift in both configuration and code.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/dq-write-enforcement-unification

## Phase
Phase Platform (parallel track) -- DQ enforcement arc Phase 4, wave-3 continuation.

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/ops_data_portal.py` | Modify | Extract `_derive_computed_fields()`; fix `drain_pending()` (add `compute_automatable()`, replace `date.today()` with `datetime.now(timezone.utc)`); add `_load_write_time_validators(table)` reading `ops.yaml` `write_time: true` entries; replace `_REQUIRED_NONEMPTY` dispatch with loader in `file_rec()` and `drain_pending()` |
| `scripts/ops_writer.py` | Modify | Add null-row guard in `compact()` after column-drop: `df.dropna(how='all')` before Iceberg write to prevent ghost rows |
| `config/data_quality/ops.yaml` | Modify | Add `write_time: true` to `title.not_null`, `effort.not_null`, `effort.accepted_values`, `priority.not_null`, `priority.accepted_values`, `status.not_null` -- parity with `_REQUIRED_NONEMPTY` fields not yet covered |
| `tests/test_ops_data_portal.py` | Modify | Add `TestWriteTimeDispatch` class with 4 tests covering validator loading, drain automatable derivation, and created_timestamp full-precision requirement |
| `scripts/validate.py` | Modify | Add `validate_dq_manifest_gate()` check (presubmit tier): for every `enforced: true` test in ops.yaml, assert manifest field `enforcement_ready` is in `{READY_NOW, write_fix_deployed}`; emit actionable error per field |
| `src/data/handlers/findings_processor_handler.py` | Modify | Add `Recommendation.model_validate()` call before `append_jsonl()` S3 write; reject records missing required fields -- **DEFERRED: `build_lambda.py --deploy` + `run_scheduled_agent.py --smoke-test` pending Decision 67 reversal** |
| `config/data_quality/decisions/ops_recommendations.yaml` | Modify | Update `enforcement_ready` for `status`, `risk`, `source` to `write_fix_deployed`; update `title`, `effort`, `priority` to `READY_NOW` (temporal gate now in place); update `last_verdict` for all 4 formerly-failing checks after post-deploy cleanup |

## Bundled Recommendations
- rec-746 (dq-write-enforcement-unification) -- primary subject.

## Infrastructure Dependencies
None. No `.tf` files in scope.

## Acceptance Criteria
- [ ] `pytest tests/test_ops_data_portal.py -k "write_time_dispatch" -v` exits 0 (4 new tests pass)
- [ ] `pytest tests/test_ops_data_portal.py` exits 0 (no regressions)
- [ ] `_load_write_time_validators("ops_recommendations")` returns >= 6 validators sourced from `config/data_quality/ops.yaml`
- [ ] `drain_pending()` sets `automatable` (non-null) and `created_timestamp` as a full ISO datetime (not midnight) for any queued record
- [ ] `python -m scripts.validate` exits 0 with CI manifest gate check present
- [ ] `python -m scripts.data_quality_runner` reports `verdict: PASS` and `failed: 0` after post-deploy cleanup
- [ ] `findings_processor_handler.py` validates rec dict against `Recommendation` schema before S3 write

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|------------------|--------|
| 1 | [pre-deploy] | write_time_dispatch tests | `pytest tests/test_ops_data_portal.py -k "write_time_dispatch" -v` | All 4 tests pass | Fix dispatcher or test logic |
| 2 | [pre-deploy] | Validator loader count | `.venv/Scripts/python.exe -c "from scripts.ops_data_portal import _load_write_time_validators; vs = _load_write_time_validators('ops_recommendations'); print(len(vs))"` | Prints >= 6 | Verify ops.yaml `write_time: true` entries are parsed; check YAML path |
| 3 | [pre-deploy] | drain_pending created_timestamp precision | `.venv/Scripts/python.exe -c "from scripts.ops_data_portal import _derive_computed_fields; import datetime; f={'file':'scripts/ops_data_portal.py','effort':'M','status':'open'}; _derive_computed_fields(f); ts=f.get('created_timestamp',''); print(ts); assert 'T' in ts or ' ' in ts and len(ts) > 10, 'midnight fallback'"` | Full ISO timestamp printed with time component | Replace `date.today()` → `datetime.now(timezone.utc)` in `_derive_computed_fields` |
| 4 | [pre-deploy] | Full portal test suite | `pytest tests/test_ops_data_portal.py -v` | All tests pass | Fix regressions from refactor |
| 5 | [pre-deploy] | Full presubmit | `.venv/Scripts/python.exe -m scripts.validate` | Exit 0 | Fix specific failures reported |
| 6 | [post-deploy] | Supersede rec-001 | `.venv/Scripts/python.exe -m scripts.ops_data_portal --update-rec rec-001 --status superseded --resolution "Bootstrap test artifact; write-path validation gaps closed in dq-write-enforcement-unification"` | `rec-001.status = superseded` | Verify SSO (`aws sso login --profile company-aws-profile`) and retry |
| 7 | [post-deploy] | Delete ghost row (id IS NULL) | `.venv/Scripts/python.exe -c "import boto3,time; s=boto3.Session(profile_name='company-aws-profile'); a=s.client('athena',region_name='eu-west-2'); eid=a.start_query_execution(QueryString='DELETE FROM trading_formulas_db.ops_recommendations WHERE id IS NULL',WorkGroup='agent-platform-production')['QueryExecutionId']; st='RUNNING'; [time.sleep(2) for _ in range(30) if (st:=a.get_query_execution(QueryExecutionId=eid)['QueryExecution']['Status']['State']) not in ('SUCCEEDED','FAILED','CANCELLED')]; print(st)"` | Prints SUCCEEDED | Confirm engine v3 workgroup used; retry |
| 8 | [post-deploy] | DQ runner verdict PASS | `.venv/Scripts/python.exe -m scripts.data_quality_runner` | `verdict: PASS`, `failed: 0` | Identify remaining violations via Athena and address individually |

## Constraints
- No STRATEGIC plans (Decision 67)
- Lambda deployment deferred (Decision 67): `findings_processor_handler.py` changes committed but not deployed; include DEFERRED marker in execution step
- `ops.yaml` `write_time: true` metadata already present for `source`, `automatable`, `file`, `context`, `acceptance`, `risk` (wave-2-ops-rec-graduation, PR #321); this plan adds it for `title`, `effort`, `priority`, `status` to ensure full `_REQUIRED_NONEMPTY` parity
- `path_syntax` and `acceptance_lint` are write_time-only test names with no SQL; DQ runner skips unknown test types; portal dispatches them to existing `_validate_file_path()` and `lint_acceptance_command()` respectively
- `context.expression` has `python: "len(value.strip()) >= 80"` -- do NOT use `eval()`/`exec()`; dispatch to existing `_validate_context_length()` by matching the `python:` key to the named validator
- `created_timestamp` expression (`created_timestamp <= last_updated_timestamp`) is a cross-field SQL check with no `python:` equivalent; dispatch is deferred to DQ runner only -- do not attempt to enforce this at portal write time in this plan
- `Recommendation` Pydantic model keeps `Optional[bool]` for `automatable` and `Optional[str]` for `risk` to preserve deserialization of historical rows with null values; write-time enforcement is handled entirely by `_load_write_time_validators()` and `_derive_computed_fields()`
- CI manifest gate must validate combined ops.yaml + manifest state at CI time, after the manifest update in step 11 is committed to the PR branch
- `not_null` validator in `_load_write_time_validators` must be a named function (e.g. `def _check_not_null(v, col): ...`), not a lambda -- Python lambdas cannot contain `raise` statements

## Context
- wave-2-ops-rec-graduation (PR #321, merged 2026-05-11) added `write_time: true` metadata to ops.yaml explicitly deferring portal consumption to this plan
- Three confirmed bypass paths identified by subagent investigation: (1) `drain_pending()` missing `compute_automatable()` and using `date.today()` for `created_timestamp`; (2) `ops_writer.compact()` DataFrame column-drop producing all-null rows; (3) `findings_processor_handler.py` writing unvalidated model output to S3
- rec-001 "Test recommendation" (automatable=NULL, risk=NULL) and rec-742 `created_timestamp > last_updated_timestamp` both trace to the drain_pending() bugs
- Ghost row (id=NULL, all fields NULL) traces to the compact() DataFrame artifact
- All three rows were absent at PR #319 merge time (DQ passed); they appeared post-merge via the active bypass paths
- The architectural root cause: `drain_pending()` and `file_rec()` are two code paths for the same logical operation that diverged -- shared `_derive_computed_fields()` closes this gap permanently
- rec-594 (Pydantic Literal for status) is not bundled; it is a complementary hardening at the model layer that can follow independently

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] `docs/PROJECT_CONTEXT.md` read
- [ ] `docs/DECISIONS.md` read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Read `scripts/ops_data_portal.py` (full), `scripts/ops_writer.py` (lines 340-410, `compact()`), `tests/test_ops_data_portal.py` (full), `scripts/validate.py` (check registration pattern), `src/data/handlers/findings_processor_handler.py` (write path section near `append_jsonl`)
2. **Extract `_derive_computed_fields(fields: dict) -> None`** in `ops_data_portal.py`: calls `compute_risk(fields["file"], fields["effort"])` → sets `fields["risk"]`; calls `compute_automatable(fields["file"], fields["effort"])` → sets `fields["automatable"]`; sets `fields.setdefault("created_timestamp", datetime.now(timezone.utc).isoformat())`. Remove duplicate derivation blocks from `file_rec()` and `drain_pending()` and replace with a single `_derive_computed_fields(fields)` call in each.
3. **Implement `_load_write_time_validators(table: str) -> list[tuple[str, Callable]]`** in `ops_data_portal.py`: reads `config/data_quality/ops.yaml`; iterates `tables[table].columns`; for each test entry with `write_time: true`, builds a validator tuple `(field_name, validator_fn)`. Dispatch map: `not_null` → `lambda v, col: None if v else raise ValueError(f"{col} must be non-empty")`; `accepted_values` → validate against `params["values"]`; `path_syntax` → `_validate_file_path`; `acceptance_lint` → `lambda v, _: lint_acceptance_command(v)[0] or raise`; `expression` with `python:` key containing length check → `_validate_context_length`. Cache result to avoid repeated YAML reads.
3a. **Add `write_time: true` to `ops.yaml`**: in `config/data_quality/ops.yaml` under `ops_recommendations.columns`, add `write_time: true` to `title.not_null`, `effort.not_null`, `effort.accepted_values`, `priority.not_null`, `priority.accepted_values`, `status.not_null`. This ensures the loader covers all fields currently in `_REQUIRED_NONEMPTY` plus `status`.
4. **Refactor `file_rec()` and `drain_pending()`**: call `_derive_computed_fields(fields)` early (before DynamoDB call in `file_rec`, before OpsWriter call in `drain_pending`). Replace `_REQUIRED_NONEMPTY` loop with `_load_write_time_validators("ops_recommendations")` iterator. Remove `_REQUIRED_NONEMPTY` constant. Preserve `validate_source()`, `lint_acceptance_command()`, `_validate_file_path()` calls -- they are now dispatched via the loader but keep the explicit calls as fallback until tests confirm dispatch coverage.
5. **Fix `ops_writer.compact()`**: after `df = df.drop(columns=[_scd2_col])` (line ~420), add `df = df.dropna(how='all')` to remove rows where every field is NaN/None before the `wr.athena.to_iceberg()` write call.
6. **Harden `findings_processor_handler.py`**: import `Recommendation` from `scripts.executor.jsonl_store`; before `append_jsonl(...)` call, run `Recommendation.model_validate(rec_merged)` in a try/except; log `WARNING` and skip on `ValidationError`. Add inline comment: `# DEFERRED: build_lambda.py --deploy + run_scheduled_agent.py --smoke-test (pending Decision 67 reversal)`.
7. **Add `validate_dq_manifest_gate()` to `scripts/validate.py`**: parses all `config/data_quality/*.yaml` and all `config/data_quality/decisions/*.yaml`; for each ops.yaml column with any test having `enforced: true`, looks up the matching field in the decisions manifest; asserts `enforcement_ready` in `{READY_NOW, write_fix_deployed}`; on failure prints `DQ manifest gate: {table}.{field} is enforced: true but manifest shows enforcement_ready: {state}. Resolve before promoting enforcement.` Register in presubmit tier alongside existing checks.
8. **Add `TestWriteTimeDispatch` to `tests/test_ops_data_portal.py`**:
   - `test_write_time_validators_loaded`: assert `len(_load_write_time_validators("ops_recommendations")) >= 6`
   - `test_write_time_rejects_null_required_field`: call `file_rec` with `status=None` (or another write_time-enforced field); assert `ValueError` raised
   - `test_drain_pending_computes_automatable`: write a JSON file to `_PENDING_OUTBOX` missing `automatable`; call `drain_pending()` with mocked OpsWriter; assert resulting record has `automatable` set (not None)
   - `test_drain_pending_created_timestamp_full_precision`: same setup; assert `created_timestamp` in drained record contains a time component (not date-only midnight)
9. **Execute Verification Plan** -- run each VP step in order. Loop on failures. If V3 fails unrecoverably, stop and file a rec via `ops_data_portal` (Decision 55).
10. **Post-deploy data cleanup**: run VP steps 6 (supersede rec-001) and 7 (delete ghost row). Re-run VP step 8 (DQ runner) and confirm `verdict: PASS`.
11. **Update manifest** (`config/data_quality/decisions/ops_recommendations.yaml`): set `enforcement_ready: write_fix_deployed` for `status`, `risk`, `source`; set `enforcement_ready: READY_NOW` for `title`, `effort`, `priority` (temporal gate now in place via `exclude_before: 2026-05-01`); update `last_verdict: PASS` for all four formerly-failing checks; add `resolved_date: {today}` where applicable.
12. Report: what was implemented, verification results, DQ verdict before and after cleanup.
