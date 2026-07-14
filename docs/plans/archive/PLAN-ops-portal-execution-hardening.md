---
title: Ops Portal Execution Fields Hardening
slug: agent/ops-portal-execution-hardening
date: 2026-05-01
status: draft
plan_type: IMPLEMENTATION
verification_tier: V3
---

# Intent
Harden the executor operations logging pipeline to ensure critical telemetry fields—such as `execution_branch`, `execution_date`, `execution_steps`, `execution_pr_url`, and `created_timestamp`—are deterministically populated and verified. This corrects issues where execution fields were hardcoded, omitted, or mapped to midnight UTC dates, and ensures `VIEW_IS_STALE` errors are prevented post-compaction.

# Context
- `execution_branch` was manually passed in instead of being dynamically determined from the environment.
- `execution_date` was not automatically applied upon status change to `closed`.
- `execution_pr_url` must be captured directly from `gh pr create` output for determinism (with `gh pr view` fallback).
- `created_timestamp` was falling back to midnight UTC because it was mapped from a `YYYY-MM-DD` date string (Decision 56).
- Athena views become stale when the underlying Iceberg schema evolves via `OpsWriter.compact()`.

# Scope
| File | Action | Description |
| ---- | ------ | ----------- |
| `scripts/ops_data_portal.py` | Modify | Update `file_rec` to populate `created_timestamp` precisely and `update_rec` to auto-fill `execution_date` and `execution_branch` on closure. |
| `scripts/executor/jsonl_store.py`| Modify | Add `created_timestamp` field to `Recommendation` Pydantic model. |
| `scripts/ops_writer.py` | Modify | Prioritize `created_timestamp` over `date` fallback. Trigger `CREATE OR REPLACE VIEW` post-compaction on schema evolution. |
| `scripts/executor/postflight.py` | Modify | Capture `PR_URL` from `gh pr create` stdout (fallback to `gh pr view` if exists) and pass to telemetry update. |
| `scripts/execute_recommendation.py`| Modify | Ensure `execution_steps` is calculated from `len(plan.steps)` and passed to the portal update. |
| `scripts/data_quality_runner.py` | Modify | Add assertions for `closed` recommendations to ensure all `execution_*` fields and `created_timestamp` meet quality standards. |

# Verification Plan
| Step | [Tag] | Command | Expectation |
| ---- | ----- | ------- | ----------- |
| 1. Unit Tests | [pre-deploy] | `python -m pytest tests/` | Existing and updated tests pass. |
| 2. File test rec | [pre-deploy] | `python -m scripts.ops_data_portal --file-rec --title "Precision Test" --status open` | `created_timestamp` is a full ISO timestamp (with time), not midnight. |
| 3. Update test rec| [pre-deploy] | `python -m scripts.ops_data_portal --update-rec <ID> --status closed --execution_result success` | `execution_date` and `execution_branch` are auto-populated deterministically. |
| 4. Compaction | [post-deploy] | `python -m scripts.ops_writer --compact-all` | Record is pushed to Iceberg and view is refreshed if schema evolved. |
| 5. Cloud Verify | [post-deploy] | `python scripts/verifiers/athena_views.py` | The updated record is visible in Athena with correct execution metadata. |
| 6. DQ Runner | [post-deploy] | `python -m scripts.data_quality_runner` | The runner validates that all closed recs have the required execution metadata. |

# Implementation Steps

## 1. Schema Expansion in `jsonl_store.py`
- Add `created_timestamp: Optional[str] = Field(None, description="ISO-8601 creation timestamp")` to the `Recommendation` model.
- This ensures formal support for the transparent mapping mentioned in Decision 56.

## 2. Telemetry Hardening in `ops_data_portal.py`
- Update `file_rec()` to set `created_timestamp = datetime.now(timezone.utc).isoformat()`.
- Update `update_rec()`:
    - If `status == "closed"` and `execution_date` is missing, set it to `datetime.now(timezone.utc).isoformat()`.
    - If `status == "closed"` and `execution_branch` is missing, attempt to capture it via `git branch --show-current`.

## 3. Post-Compaction View Refresh in `ops_writer.py`
- In `_prepare_for_iceberg()`, use `record.get("created_timestamp")` as the primary source for the Iceberg `created_timestamp` column.
- In `compact()`, detect if `schema_evolution=True` resulted in a change and execute `CREATE OR REPLACE VIEW` for the associated `_current` view using the SQL from `terraform/iceberg_tables.tf`.

## 4. Capturing PR URL in `postflight.py`
- Modify `finalize()` in `scripts/executor/postflight.py` to capture the stdout of `gh pr create`.
- If `gh pr create` fails because the PR already exists, use the existing `gh pr view --json url` logic to retrieve the URL.
- Update the recommendation closure logic to use this captured URL for the `execution_pr_url` field.

## 5. Deterministic Steps in `execute_recommendation.py`
- Ensure `execution_steps` is consistently set to `steps_completed` and `execution_steps_total` is set to `len(plan.steps)` (if a plan exists).
- Pass these values explicitly to `ops_data_portal.update_rec` upon successful completion.

## 6. Data Quality Verifier
- Update `scripts/data_quality_runner.py` to add checks for:
    - `created_timestamp` has time components (is not UTC midnight).
    - `status == 'closed'` recs have non-null `execution_branch`, `execution_date`, and `execution_steps`.
