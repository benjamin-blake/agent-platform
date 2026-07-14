---
title: Postflight Integration (The Hard Gate)
slug: agent/postflight-hard-gate
date: 2026-05-01
status: draft
plan_type: IMPLEMENTATION
verification_tier: V3
---

# Intent
Complete the "Verification Foundation" by refactoring the executor's post-implementation flow to enforce deterministic hard gates. This ensures that no V3 (integration) plan can be merged into `main` unless the telemetry pipeline is verified as operational and the data quality assertions pass.

# Context
- The Orchestrator and Sensor Suite (Outbox, Schema, Causal-Chain) are implemented and functional.
- Currently, `postflight.py` runs verifiers as a non-blocking check at the end of the session.
- `data_quality_runner.py` is not yet integrated into the autonomous merge gate.
- This is the final step to institutionalize "Due Diligence" in the agentic control plane.

# Scope
| File | Action | Description |
| ---- | ------ | ----------- |
| `scripts/executor/postflight.py` | Modify | Move verifier gate before merge; make mandatory for V3. |
| `scripts/validate.py` | Modify | Add `--verifiers` flag and integrate into `--scope all`. |
| `scripts/verifiers/data_quality.py` | Create | New verifier to parse `logs/debug/dq-latest.json` and report FAIL on critical regressions. |
| `scripts/verifiers/__init__.py` | Modify | Register `DataQualityVerifier`. |
| `tests/test_postflight_gates.py` | Create | Unit tests to verify that merge is aborted on verifier failure. |

# Verification Plan
| Step | [Tag] | Command | Expectation |
| ---- | ----- | ------- | ----------- |
| 1. Unit Tests | [pre-deploy] | `python -m pytest tests/test_postflight_gates.py` | Ensures `finalize()` correctly blocks merge on verifier failure. |
| 2. DQ Verifier | [pre-deploy] | `python -m scripts.verifiers.harness --verifier DataQualityVerifier` | Detects failures in the latest DQ report. |
| 3. Local Gate | [pre-deploy] | `python -m scripts.validate --verifiers` | Runs the full suite locally and returns non-zero exit on failure. |
| 4. Finalize Proof | [post-deploy] | `python -m scripts.executor.postflight --rec-id rec-XXX --no-merge` | Verifies that the full gate (including CausalChain) is triggered during postflight. |

# Implementation Steps

## 1. Implement `DataQualityVerifier`
- Create `scripts/verifiers/data_quality.py`.
- Logic:
    - Read `logs/debug/dq-latest.json`.
    - If `verdict == "FAIL"`, return `VerifierStatus.FAIL` with a summary of failed checks.
    - If file is missing or stale (>1h), return `VerifierStatus.SKIPPED` (Advisory).
- Register in `scripts/verifiers/__init__.py`.

## 2. Refactor `postflight.py` Hard Gate
- Locate `finalize()` function.
- Move the `_run_verifiers_gate()` call to occur **after** CI wait but **before** `merge_pr()`.
- Update `_run_verifiers_gate()` to return `False` (blocking) if:
    1. The plan is `V3` (Integration).
    2. Any verifier with `severity == HARD_GATE` returns `FAIL`.
- Ensure that if `_run_verifiers_gate()` returns `False`, `finalize()` returns `None` and does not attempt the merge.

## 3. Harden `validate.py`
- Add `--verifiers` argument to the CLI.
- When set, it should call `scripts.verifiers.run_all_verifiers(tier_filter=None)` and exit with code `1` if any hard verifier fails.
- Integrate this check into `--scope all` if `AWS_PROFILE` is detected.

## 4. Safety Audit
- Review `scripts/verifiers/harness.py` one last time to ensure exception handling in `main()` doesn't accidentally return `0` when it should return `1`.
- Verify that `CausalChainVerifier` is correctly tagged as `V3` so it doesn't block local `V2` (unit) work.
