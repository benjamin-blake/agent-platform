---
title: Verifier Sensor Suite (Core Sensors)
slug: agent/verifier-sensor-suite
date: 2026-05-01
status: draft
plan_type: IMPLEMENTATION
verification_tier: V3
---

# Intent
Implement the "Layer 2" programmatic verification sensors required to give the autonomous executor a reliable feedback loop. By verifying outbox health, schema integrity, and the end-to-end telemetry causal chain, we move from "blind" execution to a system that can prove its own operational integrity before merging changes.

# Context
- Telemetry cannot currently be trusted as a "hard gate" because the pipeline (Produce → Transport → Persist → Query) is not verified in real-time.
- `OutboxHealthVerifier` exists but is too aggressive (fails on any file).
- `SchemaIntegrityVerifier` and `CausalChainVerifier` are missing.
- These sensors are mandatory prerequisites for Phase 2 operational governance (Decision 51).

# Scope
| File | Action | Description |
| ---- | ------ | ----------- |
| `scripts/verifiers/harness.py` | Modify | Add support for `--verifier NAME` filtering to allow targeted sensor verification. |
| `scripts/verifiers/outbox_health.py` | Modify | Update to fail only on "stale" files (> 24h) and support severity/tier. |
| `scripts/verifiers/schema_integrity.py` | Create | New verifier to compare Pydantic models against Athena/Iceberg DDLs using `ops_writer` logic. |
| `scripts/verifiers/causal_chain.py` | Create | New verifier to prove end-to-end telemetry flow using `telemetry.emit_process_event`. |
| `scripts/verifiers/__init__.py` | Modify | Register new sensors in the orchestrator registry. |
| `tests/test_sensors.py` | Create | Unit tests for verifier logic and state evaluation. |

# Verification Plan
| Step | [Tag] | Command | Expectation |
| ---- | ----- | ------- | ----------- |
| 1. Unit Tests | [pre-deploy] | `python -m pytest tests/test_sensors.py` | Verifier logic (without external IO) passes. |
| 2. Outbox Check | [pre-deploy] | `python -m scripts.verifiers.harness --verifier OutboxHealthVerifier` | Detects stale files (>24h) if seeded; passes if clean. |
| 3. Schema Check | [post-deploy] | `python -m scripts.verifiers.harness --verifier SchemaIntegrityVerifier` | Compares local models to Athena and reports no drift. |
| 4. Causal Chain | [post-deploy] | `python -m scripts.verifiers.harness --verifier CausalChainVerifier` | Successfully produces a nonce and queries it back from Athena. |

# Implementation Steps

## 1. Harden `OutboxHealthVerifier`
- Update logic to inspect the `mtime` of `.jsonl` files in `logs/.ops-outbox/`.
- Set `severity = HARD_GATE` for files older than 24 hours.
- Set `severity = ADVISORY` for files between 2 and 24 hours.
- Return `PASS` if no files are found or all are < 2 hours old.

## 2. Implement `SchemaIntegrityVerifier` (V3)
- Use `scripts/ops_writer.py` logic (e.g. `wr.catalog.get_table_columns`) to fetch the Iceberg schema for core ops tables.
- Iterate through `scripts/executor/jsonl_store.py` models (Recommendation, Session, etc.).
- Assert that all required fields in the Pydantic model exist as columns in the Athena table.
- Account for SCD2 metadata columns (`created_timestamp`, `last_updated_timestamp`) injected by `OpsWriter` (Decision 56).
- Report any drift as a `HARD_GATE` failure.

## 3. Implement `CausalChainVerifier` (V3)
- **Produce**: Use `scripts.executor.telemetry.emit_process_event()` to write a "heartbeat" event.
- **Nonce**: Generate a unique UUID `nonce` and include it in the `description`.
- **Poll**: Implement a polling loop (max 60s) with exponential backoff that queries `telemetry_process_events_current` in Athena for that specific `nonce`.
- **Verdict**:
    - `PASS`: Nonce found (Pipeline is verified).
    - `FAIL`: Nonce not found after polling (Pipeline is broken).
- Set `severity = HARD_GATE` and `tier = V3`.

## 4. Register Sensors and Update Harness
- Add `SchemaIntegrityVerifier` and `CausalChainVerifier` to `scripts/verifiers/__init__.py`.
- Update `scripts/verifiers/harness.py` to support `--verifier` argument to filter execution by class name.

## 5. System Validation
- Create `tests/test_sensors.py` to mock Athena/S3 responses and verify the verifiers handle failures (timeouts, drift, stale files) correctly.
