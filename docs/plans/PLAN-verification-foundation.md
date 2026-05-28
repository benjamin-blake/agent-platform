# Plan - Verification Foundation & Telemetry Recovery

## Intent
Establish the Layer 2 Programmatic Verification framework (Wave 1/2) and fix the `OpsWriter` telemetry bug to restore executor reliability and provide deterministic hard gates for autonomous execution. This work is a prerequisite for backfilling Athena tables and moving toward a closed control loop.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/verification-foundation

## Phase
Phase 3: Autonomous Control Plane (Foundation)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/ops_writer.py` | Modify | Fix `_bucket()` resolution and add `ROOT` constant. |
| `scripts/verifiers/__init__.py` | Formalize | Verifier registry and discovery logic (currently skeleton). |
| `scripts/verifiers/harness.py` | Formalize | Base `Verifier` class and `VerifierResult` schema. |
| `scripts/verifiers/outbox_health.py` | Formalize | Verifier for local telemetry outbox status. |
| `scripts/verifiers/athena_views.py` | Formalize | Fix NameError (os) and align with SKIPPED logic. |
| `scripts/validate.py` | Modify | Integrate the verifier harness into the `--integration` flow. |
| `scripts/executor/postflight.py` | Modify | Implement the verifier gate; block on `FAIL`, warn on `SKIPPED`. |
| `tests/test_verifiers/` | Create | Comprehensive test suite (per-verifier files). |
| `.agents/skills/planning/SKILL.md` | Modify | Update SSO logic to support interactive recovery. |
| `.agents/skills/implement/SKILL.md` | Modify | Update SSO logic to support interactive recovery. |
| `.github/copilot-instructions.md` | Modify | Add Decision 57 rule (Interactive vs Autonomous SSO). |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `scripts/ops_writer.py` correctly resolves the S3 bucket using the `company` config fallback.
- [ ] `scripts/verifiers/` successfully discovered by the harness.
- [ ] `outbox_health` verifier correctly identifies files in `logs/.ops-outbox/`.
- [ ] `athena_views` verifier returns `PASS` when SSO is active and `SKIPPED` otherwise.
- [ ] `scripts/validate.py --integration` executes all registered verifiers.
- [ ] `scripts/executor/postflight.py` blocks PR merging ONLY if any V3 verifier returns `FAIL`.
- [ ] `pytest tests/test_verifiers/` passes.
- [ ] Lambda deployment succeeds and smoke test passes.
- [ ] `.agents/skills/` updated with "Interactive SSO Recovery" protocol.
- [ ] `copilot-instructions.md` codifies Decision 57.

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Run unit tests | `.venv/Scripts/python.exe -m pytest tests/test_verifiers/` | All tests pass | Debug mock logic or verifier code |
| 2 | [pre-deploy] | Run validation | `$env:PYTHONPATH='.'; .venv/Scripts/python.exe scripts/validate.py --integration` | Includes 'Verification Harness' section | Check `validate.py` hook |
| 3 | [pre-deploy] | Test bucket fix | `.venv/Scripts/python.exe scripts/ops_writer.py --test-bucket` | Returns 'bblake-platform-agent-logs' | Add CLI test arg to `ops_writer.py` |
| 4 | [pre-deploy] | Test gate | `.venv/Scripts/python.exe scripts/executor/postflight.py --test-verifiers` | Blocks on FAIL, warns on SKIPPED | Add CLI test arg to `postflight.py` |
| 5 | [post-deploy] | Smoke test Lambda | `.venv/Scripts/python.exe -m scripts.run_scheduled_agent --smoke-test rec-curator` | Output shows successful S3 write-through | Check `ops_writer.py` and Lambda logs |

## Constraints
- Windows PowerShell compatibility.
- Never raise exceptions in `OpsWriter`.
- FAIL blocks merge; SKIPPED does not (Decision 57).

## Context
- The executor is "unusable" due to broken telemetry.
- Layer 2 Programmatic Verification (V3) framework.

## Pre-Implementation Checklist
- [x] Branch confirmed not on `main`
- [x] copilot-instructions.md read
- [x] DECISIONS.md read
- [x] All files in Scope table located and readable
- [x] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
1. **Fix `scripts/ops_writer.py`**: Update `_bucket()` with `ROOT` resolution and `config.company.yaml` fallback. Add `--test-bucket` CLI argument.
2. **Implement `scripts/verifiers/harness.py`**: Create the `Verifier` interface and `VerifierResult` (PASS/FAIL/SKIPPED).
3. **Implement `scripts/verifiers/__init__.py`**: Create the discovery registry.
4. **Implement `scripts/verifiers/outbox_health.py`**: Implement the local outbox check.
5. **Implement `scripts/verifiers/athena_views.py`**: Implement the Athena connectivity check (returning `SKIPPED` on auth error).
6. **Implement `tests/test_verifiers/`**: Write tests for the harness and verifiers.
7. **Update `scripts/validate.py`**: Hook the verifier harness into `--integration`.
8. **Update `scripts/executor/postflight.py`**: Add the verifier gate logic and `--test-verifiers` CLI argument.
9. **Deploy Lambdas**: Run `python scripts/build_lambda.py --deploy`.
10. **Implement SSO Hotfix**: Update `.agents/skills/` and `copilot-instructions.md` with the Decision 57 "Interactive SSO Recovery" logic.
11. **Execute Verification Plan**: Run all steps in the VP table.
12. **Report**: Document the implementation results.
