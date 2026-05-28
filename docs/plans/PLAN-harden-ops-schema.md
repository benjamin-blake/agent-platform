# Plan

## Intent
Harden the Recommendation schema to enforce deterministic data integrity and purge legacy regression vectors (dec- IDs, permissive type coercion) from the operational source of truth.

## Plan Type
IMPLEMENTATION

## Verification Tier
V2

## Branch
agent/harden-ops-schema

## Phase
Phase 1: Core Infrastructure (2 weeks) ✅ COMPLETE (Maintenance/Hardening)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/executor/jsonl_store.py` | Modify | Remove permissive validators, tighten ID rules (allowing rec-, agent-, test-), and forbid extra fields. |
| `scripts/test_coverage_checker.py` | Modify | Remove legacy waiver for `data_quality_runner.py`. |
| `logs/.recommendations-log.jsonl` | Modify | Sanitize historical records: remove `dec-` entries, fix malformed types. |
| `tests/test_executor_jsonl_store.py` | Modify | Restore strict validation tests, remove "permissive" test cases. |
| `tests/test_ops_data_portal.py` | Modify | Restore strict validation tests. |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `Recommendation` model in `jsonl_store.py` rejects `dec-` IDs but allows `rec-`, `agent-`, and `test-`.
- [ ] `Recommendation` model rejects malformed dates and empty strings for non-string fields.
- [ ] `Recommendation` model supports SCD2 fields (`created_timestamp`, `last_updated_timestamp`, `row_num`, `_rn`) but forbids other unknown fields.
- [ ] `logs/.recommendations-log.jsonl` contains zero `dec-` prefix entries.
- [ ] `logs/.recommendations-log.jsonl` is fully compliant with the hardened schema.
- [ ] `scripts/validate.py` passes all gates, including coverage for `data_quality_runner.py`.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Clean log data | `python scripts/scratch/cleanup_recs.py` | "Log cleaned: 31 records removed, 545 updated" | Script fails or dec- records remain |
| 2 | [pre-deploy] | Run schema tests | `pytest tests/test_executor_jsonl_store.py` | 100% pass (asserting failures on bad data) | Permissive behavior persists |
| 3 | [pre-deploy] | Coverage verification | `pytest --cov=scripts.data_quality_runner tests/test_data_quality_runner.py` | 100% coverage (if tests added) | Coverage < 100% |
| 4 | [pre-deploy] | Full validation | `python scripts/validate.py --scope python` | All gates PASS | Coverage waiver still exists or schema fails |

## Constraints
- No new `dec-` entries in the recommendation log.
- No permissive `coerce_*` logic in `Recommendation` model.
- `model_config = ConfigDict(extra="forbid")`.

## Context
- The previous implementation added permissive validators to avoid blocking CI on legacy data.
- SCD2 fields are added to the model to support Athena/S3 write-through metadata.
- `data_quality_runner.py` waiver is removed; new tests will be added to satisfy coverage if necessary, or the file will be refactored.

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main`
- [ ] copilot-instructions.md read
- [ ] DECISIONS.md read
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. Create a one-shot cleanup script `scripts/scratch/cleanup_recs.py` to:
    - Filter out `dec-` prefix IDs from `logs/.recommendations-log.jsonl`.
    - Coerce legacy malformed fields (empty strings to None, lists to actual lists).
    - Write back a clean, verified JSONL.
2. Run the cleanup script and verify the log.
3. Modify `scripts/executor/jsonl_store.py`:
    - Remove `coerce_empty_to_none`, `coerce_list_fields`, `coerce_int_fields`, `coerce_bool_fields`.
    - Update `validate_id` to strictly allow `rec-`, `agent-`, `test-` and reject `dec-`.
    - Add SCD2 metadata fields to `Recommendation` model.
    - Set `extra="forbid"`.
4. Create `tests/test_data_quality_runner.py` to provide 100% coverage for the legacy script, allowing the waiver removal.
5. Modify `scripts/test_coverage_checker.py` to remove `data_quality_runner.py` from `excluded_names`.
6. Update `tests/test_executor_jsonl_store.py` and `tests/test_ops_data_portal.py` to match the strict schema.
7. **Execute Verification Plan** -- run each step. Loop until pass.
8. Report: Implementation of strict schema and cleanup of 31 legacy records.
