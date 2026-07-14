---
title: Verifier Harness & Registry Orchestration
slug: agent/verifier-harness-orchestrator
date: 2026-05-01
status: draft
plan_type: IMPLEMENTATION
verification_tier: V2
---

# Intent
Establish the foundation of the "Verification Foundation" by hardening the `scripts/verifiers` harness and registry. This transition moves the system from a probabilistic LLM-based review model to a deterministic programmatic model where verifier outputs act as "hard gates" for V3 merge safety.

# Context
- The executor is currently non-functioning or "blind" because telemetry cannot be fully trusted.
- Programmatic verifiers exist (`harness.py`, `athena_views.py`) but lack clear severity levels (Advisory vs Hard Gate) and tier-based filtering (V1 vs V3).
- Verification logic is currently best-effort and does not reliably block merges in `postflight.py`.

# Scope
| File | Action | Description |
| ---- | ------ | ----------- |
| `scripts/verifiers/harness.py` | Modify | Add `VerifierSeverity` and `VerifierTier`. Implement CLI entry point. |
| `scripts/verifiers/__init__.py` | Modify | Update `run_all_verifiers` to support filtering by tier and severity aggregation. |
| `tests/test_verifier_harness.py`| Create | Unit tests for gating and filtering logic. |

# Verification Plan
| Step | [Tag] | Command | Expectation |
| ---- | ----- | ------- | ----------- |
| 1. Unit Tests | [pre-deploy] | `python -m pytest tests/test_verifier_harness.py` | Harness correctly handles PASS/FAIL/SKIPPED and HARD/ADVISORY. |
| 2. CLI Help | [pre-deploy] | `python -m scripts.verifiers.harness --help` | CLI exists and shows tier/severity filtering options. |
| 3. Mock Run | [pre-deploy] | `python -m scripts.verifiers.harness --tier V1` | Correctly filters and executes only relevant verifiers. |

# Implementation Steps

## 1. Harden Harness Data Models (`harness.py`)
- Add `VerifierSeverity` Enum: `ADVISORY` (warn only), `HARD_GATE` (block merge).
- Add `VerifierTier` Enum: `V1` (static), `V2` (unit), `V3` (integration).
- Update `Verifier` base class to include `severity` and `tier` as properties (with sensible defaults).
- Update `VerifierResult` to include `severity` for downstream decision making.

## 2. CLI Entry Point (`harness.py`)
- Implement `main()` in `harness.py` using `argparse`.
- Support `--tier {V1,V2,V3}` and `--severity {advisory,hard}` filters.
- Support `--json` output for programmatic consumption by `postflight.py` or `validate.py`.
- Exit with code `1` if any `HARD_GATE` verifier fails; exit `0` otherwise.

## 3. Intelligent Registry (`__init__.py`)
- Update `run_all_verifiers(tier_filter: Optional[VerifierTier] = None)` to allow scoping the run.
- Refactor registry to include severity/tier metadata if not fully encapsulated in classes.

## 4. Bootstrap Logic & Tests
- Create `tests/test_verifier_harness.py`.
- Test cases:
    - Mixed PASS/FAIL results: PASS if only ADVISORY fails, FAIL if any HARD_GATE fails.
    - Tier filtering: Ensure V3 verifiers are skipped when running with `--tier V2`.
    - Exception handling: Ensure the harness captures and reports verifier crashes as FAIL.
