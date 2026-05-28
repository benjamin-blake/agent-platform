# Intent: Programmatic Verification System

This document defines the intent, architecture, and design boundaries for the repository's verification infrastructure. It is the authoritative specification for how every workflow -- manual, autonomous, and scheduled -- proves that implemented features actually work, that data pipelines flow end-to-end, and that system health is maintained over time.

**Motivation:** This document exists because of a systemic failure mode observed across 4+ telemetry implementation phases (April 2026): agents consistently declared work "complete" when unit tests passed and lint was clean, but the underlying data pipelines were broken. Five of seven telemetry tables remained empty for weeks despite multiple implementation sessions claiming success. The root cause was not faulty code -- it was the absence of deterministic, non-interpretable verification gates.

**Supersedes:** The Verification Plan (VP) framework in `/plan` and `/implement` workflows is retained for plan-level structure, but the enforcement mechanism shifts from LLM self-evaluation to programmatic harness execution. VP steps now reference registered verifiers rather than ad-hoc shell commands that agents self-assess.

**Builds on:** Decision 48 (Verification Tier Design), Decision 51 (Local-First Outbox + Bidirectional Sync), the existing `validate.py` infrastructure, and the `validate_telemetry.py` diagnostic tool created in Phase D.

---

## Problem Statement

### The Verification Bypass Pattern

Across 15+ autonomous implementation sessions, a consistent pattern emerged:

1. **Plans scope the tool, not the outcome.** A request to "validate the telemetry system end-to-end" was decomposed as "build a validation script." The tool was built correctly. The system remained broken.

2. **VP expected outcomes allow failure states.** VP steps used language like "identifies which tables are empty" and "exit code reflects actual state." These pass even when every table is empty -- because the diagnostic tool correctly reported the failure.

3. **No causal chain requirement.** No VP step ever required all five stages of end-to-end verification: PRODUCE -> TRANSPORT -> PERSIST -> QUERY -> ASSERT. Plans verified isolated stages (unit tests prove emit is called; Athena query starts successfully) without proving data flows between them.

4. **LLMs evaluate their own work.** The implement agent runs a VP command, reads the output, and decides whether it passes. This is cooperative self-evaluation -- the opposite of adversarial verification. When output is ambiguous ("0 rows returned, which is expected for empty tables"), the agent interprets charitably.

### Impact

- 5 of 7 telemetry Iceberg tables empty for 3+ weeks
- Ops recommendations pipeline silently broken (local JSONL never reaching Athena)
- Phase E (Cloud Analysis Agent) blocked -- cannot analyse data that doesn't exist
- Multiple human hours spent across sessions re-diagnosing the same root causes
- Erosion of trust in the autonomous improvement loop

### Root Causes (Technical)

| Failure | Root Cause | Detection Mechanism That Should Have Caught It |
|---------|-----------|-----------------------------------------------|
| Empty telemetry tables | `S3_LOG_BUCKET` env var unset in local sessions; `OpsWriter._bucket()` returns "" silently | A verifier that produces a record and reads it back from Athena |
| Broken Athena views | Views reference `premium_requests_total` column that doesn't exist | A verifier that executes each view and asserts >0 rows |
| Schema drift | Python dataclass adds columns but `ALTER TABLE` never executed | A verifier that compares Python schema to Athena DDL |
| FK orphans (potential) | Phases reference session_ids that might not exist in sessions table | A verifier that runs FK integrity JOINs |
| Ops recommendations not in Iceberg | Same `_bucket()` bug; `ops_data_portal.py` calls `write()` which no-ops | Same pipeline verifier, scoped to ops tables |

---

## North Star

The verification system exists to make a single guarantee: **if a verifier passes, the system works. If a verifier fails, the system is broken.** There is no ambiguity, no interpretation, and no override.

This is the missing middle layer of the quality pyramid:

```
Layer 3: LLM Judgment (code review, architectural alignment)
    - Advisory, not blocking
    - Can produce findings that create recommendations
    - Cannot override programmatic gates

Layer 2: Programmatic Verifiers (THIS DOCUMENT)          <-- NEW
    - Deterministic pass/fail
    - Cannot be interpreted, overridden, or weakened by an LLM
    - Run as hard gates before merge
    - Run as scheduled health checks post-merge

Layer 1: Structural Checks (validate.py, pytest, ruff)
    - Existing, fast, local-only
    - Proves code is well-formed
    - Does NOT prove the system works
```

The verification system occupies Layer 2. It answers the question Layer 1 cannot: "Does the system actually do what it's supposed to do?"

---

## Architecture

### Verifier Interface

Every verifier is a Python module in `scripts/verifiers/` that conforms to this interface:

```python
# scripts/verifiers/{name}.py
"""
Verifier: {Human-readable description}
"""

# --- Module-level metadata (used by autodiscovery) ---
COVERS: list[str] = [
    "scripts/ops_writer.py",      # Files this verifier validates
    "scripts/sync_ops.py",
]
TIER: str = "V3"                   # V1=static, V2=unit, V3=integration
REQUIRES_AWS: bool = True          # Whether AWS credentials are needed
REQUIRES_DEPLOY: bool = False      # Whether Lambda deploy must precede this


def main() -> int:
    """Run all checks. Return 0 (PASS) or 1 (FAIL).

    Output: JSON to stdout with structure:
    {
        "verifier": "telemetry_pipeline",
        "verdict": "PASS" | "FAIL",
        "checks": [
            {"name": "produce_session", "verdict": "PASS", "detail": "..."},
            {"name": "drain_to_s3", "verdict": "PASS", "detail": "..."},
            ...
        ],
        "timestamp": "2026-04-30T15:00:00Z",
        "duration_seconds": 45
    }
    """
    ...


if __name__ == "__main__":
    import sys
    sys.exit(main())
```

**Rules:**

1. **Verifiers must be pure observers of existing system state.** They read system state, they check invariants, they report results. They do NOT modify the system. **Exception:** Causal chain verifiers may produce minimal test records as part of their PRODUCE stage. Such records must be tagged for exclusion from analytics views (see Constraint 9: Test data tagging) and the production step must be clearly delineated within the verifier code. Test data production must be idempotent.

2. **Verifiers must be idempotent.** Running the same verifier twice with no intervening changes produces the same result.

3. **Verifiers must have their own tests.** `tests/test_verifiers/test_{name}.py` validates the verifier correctly classifies known-good and known-bad states using mocked backends.

4. **Verifiers output structured JSON.** The harness reads the JSON verdict field. Humans read the checks array for diagnostics. No prose parsing is required.

5. **Verifier results are immutable.** No LLM can amend, reinterpret, or override a result. The postflight harness reads the verdict and acts on it. This is the hard boundary.

6. **Exit code is the verdict.** 0 = PASS, 1 = FAIL. The JSON provides detail; the exit code provides the gate decision.

### Registry and Autodiscovery

The verifier registry is the filesystem itself. No YAML manifest to maintain:

```python
# scripts/verifiers/__init__.py
"""Verifier registry. Auto-discovers all verifier modules in this package."""

import importlib
import pkgutil
from pathlib import Path

def discover_verifiers() -> dict[str, dict]:
    """Scan scripts/verifiers/ and build registry from module metadata."""
    registry = {}
    pkg_path = Path(__file__).parent
    for importer, name, ispkg in pkgutil.iter_modules([str(pkg_path)]):
        if name.startswith("_"):
            continue
        mod = importlib.import_module(f"scripts.verifiers.{name}")
        registry[name] = {
            "covers": getattr(mod, "COVERS", []),
            "tier": getattr(mod, "TIER", "V2"),
            "requires_aws": getattr(mod, "REQUIRES_AWS", False),
            "requires_deploy": getattr(mod, "REQUIRES_DEPLOY", False),
            "module": mod,
        }
    return registry


def check_coverage(scope_files: list[str]) -> list[str]:
    """Return scope files not covered by any registered verifier."""
    registry = discover_verifiers()
    covered = set()
    for entry in registry.values():
        covered.update(entry["covers"])
    return [f for f in scope_files if f not in covered]
```

**Self-registration:** Drop a module in `scripts/verifiers/`, it appears in the registry. Delete it, it disappears. No manual updates to a manifest file.

### Harness

The harness orchestrates verifier execution:

```python
# scripts/verifiers/harness.py
"""Run verifiers by name, by scope, or from a plan's VP table."""

def run_verifiers(
    names: list[str] | None = None,
    scope_files: list[str] | None = None,
    tier: str | None = None,
    require_aws: bool | None = None,
) -> dict:
    """Run matching verifiers and return aggregate result.

    Returns:
        {"verdict": "PASS"|"FAIL", "results": {...}, "duration_seconds": N}
    """
    ...
```

The harness:
- Filters verifiers by name, scope (files they cover), tier, or AWS requirement
- Runs each in sequence (parallel execution is a future optimisation)
- Collects JSON output from each
- Returns aggregate: PASS only if ALL verifiers pass
- Writes results to `logs/debug/verification-{date}.json`

### Integration Points

The verification system integrates at four points in the workflow:

#### 1. validate.py --integration

```bash
# Fast local checks (existing, always runs)
python -m scripts.validate

# Full verification including V3 integration checks (opt-in)
python -m scripts.validate --integration
```

When `--integration` is passed and AWS credentials are available, `validate.py` invokes the harness for all verifiers matching the current branch's scope. This is the manual developer check.

#### 2. Executor Postflight (Hard Gate)

In `scripts/executor/postflight.py`, after acceptance passes but before merge:

```python
# After acceptance command passes...
if plan.verification_tier == "V3":
    from scripts.verifiers.harness import run_verifiers
    result = run_verifiers(scope_files=plan.scope_files)
    if result["verdict"] == "FAIL":
        emit_process_event(
            tier="exception",
            category="verification_gate_fail",
            severity="error",
            description=f"Verifier failed: {result}",
        )
        # ABORT MERGE. Do not proceed.
        return ExecutionResult.VERIFICATION_FAILED
```

This is non-negotiable. The executor cannot reason its way past a non-zero exit code. No prompt can override a Python `if` statement.

#### 3. Implement Workflow (VP Harness Call)

The implement skill's "Execute Verification Plan" step becomes:

```bash
python -m scripts.verifiers.harness --plan docs/plans/PLAN-{slug}.md
```

The harness reads the plan's VP table, maps VP steps to registered verifiers, and runs them. The implement agent sees PASS or FAIL. It cannot substitute weaker checks because the harness runs the actual verifier code, not a command the agent provides.

For VP steps that reference ad-hoc commands (not registered verifiers), the harness runs them as-is but flags them as "unregistered" in the output. Over time, all VP steps should reference registered verifiers.

#### 4. Scheduled Health Checks (Post-Merge Regression Detection)

A scheduled Lambda (or extension of the existing dispatcher) runs the full verifier suite daily:

```python
# In the scheduled agent handler or as a standalone scheduled check
from scripts.verifiers.harness import run_verifiers
result = run_verifiers(tier="V3", require_aws=True)
if result["verdict"] == "FAIL":
    # File a recommendation for each failed verifier
    for name, check_result in result["results"].items():
        if check_result["verdict"] == "FAIL":
            file_recommendation(
                title=f"Verifier {name} failing: {check_result['checks'][0]['detail']}",
                source="scheduled_verification",
                priority="Critical",
                automatable=True,
            )
```

No LLM in this loop. Detection is programmatic. Only the fix requires LLM involvement (the executor implements the recommendation).

---

## The End-to-End Definition

A recurring source of miscommunication between human and agent: the phrase "end-to-end" is interpreted differently depending on context. This document provides a lexical definition that all agents, prompts, and plans must use.

### End-to-End Verification (E2E)

A test that exercises the **complete data path** through all five stages:

| Stage | What It Proves | Example |
|-------|---------------|---------|
| 1. **PRODUCE** | The write path creates a record via the real production code (not a mock) | `open_session()` + `close_session()` writes a telemetry_sessions record |
| 2. **TRANSPORT** | The record moves through all intermediate storage layers | `drain()` pushes the outbox file to S3 staging |
| 3. **PERSIST** | The record reaches its final storage location | `compact()` writes from S3 staging to the Iceberg table |
| 4. **QUERY** | The record is readable from the query interface | Athena SELECT returns the row |
| 5. **ASSERT** | Specific field values in the query result match what was produced | `session_id`, `workflow`, `outcome` are non-null and match expected |

**A verification step that omits any of these 5 stages is NOT end-to-end**, regardless of what it is labelled. Specifically:

- Stages 1-2 only = TRANSPORT verification (proves data moves, not that it persists)
- Stages 1-3 only = PERSISTENCE verification (proves storage, not queryability)
- Stages 4-5 only = QUERY verification (proves the query works, not that the data was produced correctly)
- Stage 1 only = EMIT verification (proves the code runs, not that it has any effect)

When a plan, prompt, or human says "verify end-to-end," all 5 stages MUST be present. The critique agent and verifier coverage check enforce this mechanically.

### Causal Chain Verifiers

A **causal chain verifier** is a verifier that implements all 5 E2E stages in sequence within a single execution. It is the strongest form of verification because it proves the complete path in one atomic operation.

Structure of a causal chain verifier:

```python
def check_full_pipeline() -> dict:
    """PRODUCE -> TRANSPORT -> PERSIST -> QUERY -> ASSERT"""
    # Stage 1: PRODUCE
    session_id = produce_test_record()

    # Stage 2: TRANSPORT
    drained = drain_outbox()
    assert drained > 0, "Nothing drained"

    # Stage 3: PERSIST
    compacted = compact_table("telemetry_sessions")
    assert compacted > 0, "Nothing compacted"

    # Stage 4: QUERY
    rows = query_athena(f"SELECT * WHERE session_id = '{session_id}'")

    # Stage 5: ASSERT
    assert len(rows) == 1
    assert rows[0]["workflow"] is not None
    assert rows[0]["outcome"] is not None

    return {"verdict": "PASS", "detail": f"Record {session_id} verified in Athena"}
```

---

## Coverage Requirements

### Planning-Time Coverage Check

The planning skill MUST check verifier coverage before approving a V3 plan:

```
For each file in the plan's Scope table:
    If file is in any verifier's COVERS list:
        The plan's VP table MUST reference that verifier
    If file is NOT in any verifier's COVERS list AND plan is V3:
        The plan MUST either:
        (a) Include creating a new verifier in its scope, OR
        (b) Document why existing verification is sufficient

        Option (b) requires explicit human approval during plan critique.
```

The critique agent enforces this mechanically: it calls `check_coverage(scope_files)` and rejects plans with uncovered V3 files that don't include verifier creation.

### Critique-Time Rules

The plan critique agent adds these checks to its evaluation:

1. **VP Expected Outcomes must be binary.** Reject outcomes containing: "identifies", "reports", "reflects actual state", "shows which". Replace with: "exit 0", ">0 rows", "verdict PASS", "assert passes".

2. **V3 plans must reference a causal chain.** At least one VP step must cover all 5 E2E stages. If no registered causal chain verifier exists for the scope, the plan must create one.

3. **VP steps must not allow empty results to pass.** Reject expected outcomes like "returns QueryExecutionId" (proves the query runs, not what it returns). Require: "returns >0 rows with non-null X field".

4. **Diagnostic tools are not verification.** A plan that creates a diagnostic tool (like `validate_telemetry.py`) must ALSO include a VP step where the tool reports SUCCESS (exit 0), not merely "runs without error."

### Executor Boundary

Verifiers for system X cannot be modified in the same PR as code for system X. This prevents the conflict of interest where the implementer weakens the verifier to make their code pass.

**Enforcement:** `validate.py` checks: if both `scripts/verifiers/{name}.py` and any file in that verifier's `COVERS` list are modified in the same git diff, fail with: "Verifier {name} and its covered code cannot be modified in the same PR."

**Exception:** The initial creation of a verifier alongside its first version of the code it covers is permitted (you can't write a verifier for code that doesn't exist). This is detected by checking if the verifier file is in the `git diff --diff-filter=A` (added) list.

**Exception 2:** A PR that modifies ONLY the verifier (no changes to covered files) is permitted. This allows fixing broken verifiers without being blocked by the guard. Detected by checking if no file in the verifier's COVERS list appears in `git diff --name-only`.

---

## Verifier Catalogue (Target State)

These are the verifiers that should exist once the system is fully instrumented:

| Verifier | Type | Covers | What It Proves |
|----------|------|--------|---------------|
| `telemetry_pipeline` | Causal chain | ops_writer, sync_ops, executor/telemetry, session_postflight | Record produced locally reaches Athena with correct field values |
| `schema_integrity` | Static | telemetry_schemas.py, terraform/iceberg_tables.tf | Python dataclass fields match Iceberg DDL columns |
| `fk_integrity` | Query | All 7 telemetry tables | Child FK references resolve to existing parent rows |
| `athena_views` | Query | terraform/iceberg_tables.tf (views section) | All views execute without error and return >0 rows |
| `outbox_health` | Local | ops_writer.py, logs/.ops-outbox/ | No stale entries >24h, no corrupt JSONL, all files parseable |
| `lambda_cold_start` | Integration | build_lambda.py, all handler files | Each Lambda invokes successfully with StatusCode 200 |
| `ops_pipeline` | Causal chain | ops_data_portal.py, ops_writer.py | Recommendation/decision writes reach Iceberg |
| `market_data_health` | Query | src/data/handlers/fetch_handler.py | market_data table has records within expected freshness window |
| `executor_telemetry` | E2E | executor/telemetry.py, step_runner.py | An executor run populates phases, steps, model_calls, process_events, transcripts |

**Implementation priority:**
1. `telemetry_pipeline` (unblocks Phase E)
2. `schema_integrity` (already 80% built in `validate_telemetry.py`)
3. `outbox_health` (local-only, no AWS needed, catches the class of bug that caused this crisis)
4. `athena_views` (catches the broken views found by `validate_telemetry.py`)
5. Others as the system grows

---

## Automation: How New Verifiers Are Created

### Detection (Programmatic)

`validate.py` (or a pre-commit check) runs coverage analysis:

```python
def check_verifier_coverage_for_branch():
    """Check if the current branch's changed files are covered by verifiers."""
    changed_files = get_changed_files_on_branch()
    uncovered = check_coverage(changed_files)
    v3_uncovered = [f for f in uncovered if classify_tier(f) == "V3"]

    if v3_uncovered:
        logger.warning(
            "Files modified on this branch are not covered by any verifier: %s",
            v3_uncovered,
        )
        # This is advisory during transition period.
        # After Wave 3 (harness wired into postflight), this becomes a hard fail.
```

### Planning-Time Requirement

When the planner identifies uncovered files, it adds verifier creation to the plan scope. The critique agent enforces this. The generated plan step looks like:

```markdown
### Step N: Create verifier for {scope}

Create `scripts/verifiers/{name}.py` with:
- COVERS = [list of scope files]
- TIER = "V3"
- A causal chain check that exercises the modified write path
- Tests in `tests/test_verifiers/test_{name}.py`
```

### Template Generation

A generator script scaffolds new verifiers:

```bash
python -m scripts.verifiers.generate --name market_data_health \
    --covers src/data/handlers/fetch_handler.py \
    --tier V3 \
    --requires-aws
```

This creates the module skeleton with correct metadata, a placeholder `main()`, and a test file. The implement agent fills in the check logic.

---

## Relationship to Existing Infrastructure

### validate.py

`validate.py` remains the fast, local-only Layer 1 gate. It gains an `--integration` flag that invokes the verifier harness for Layer 2 checks. Without the flag, behaviour is unchanged.

**Additions to validate.py:**
- `--integration`: Run all verifiers matching the branch scope (requires AWS)
- `--coverage`: Report which scope files lack verifier coverage (advisory)
- The existing stale-outbox check (Decision 51) remains as a fast local check

### validate_telemetry.py

The existing `validate_telemetry.py` is a diagnostic tool, not a verifier. It reports population percentages and exit-codes based on table state. It will be decomposed into registered verifiers:

- `schema_integrity` verifier: absorbs the schema drift detection
- `fk_integrity` verifier: absorbs the FK orphan checks
- `athena_views` verifier: absorbs the view execution checks
- Population reporting remains as a diagnostic (not a gate) or is absorbed into the causal chain verifier

### Executor Postflight

The executor's `postflight.py` currently runs `validate.py` as a gate. The verifier harness becomes an additional gate:

```
Current:  validate.py pass? -> merge
Proposed: validate.py pass? -> verifier harness pass? -> merge
```

The verifier harness only runs if the plan is V3 and has scope files covered by registered verifiers. V1/V2 plans skip this gate (they have no integration to verify).

### Data Quality Framework (Existing Scaffold)

A declarative, dbt-style data quality framework already exists as a precursor to the verifier architecture. It covers **Layer 2** (query-type checks) for all 12 Iceberg tables in the star schema.

**Components:**

| File | Purpose |
|------|---------|
| `config/agent/data_quality/telemetry.yaml` | Declarative checks for 7 telemetry tables (~80 checks) |
| `config/agent/data_quality/ops.yaml` | Declarative checks for 5 ops tables (~50 checks) |
| `scripts/data_quality_runner.py` | Generic runner: compiles YAML to Athena SQL, executes, reports JSON |

**Check types defined:** `not_null`, `unique`, `accepted_values`, `relationships` (FK), `row_count`, `recency`, `expression` (arbitrary SQL predicates).

**Relationship to verifier architecture:** The DQ runner is the implementation mechanism for query-type verifiers. In Wave 2, `scripts/verifiers/data_quality.py` wraps the runner with the standard verifier interface (exit codes, JSON output, scope metadata). The YAML definitions remain the source of truth for what's checked; the verifier module provides the harness-compatible execution envelope.

**Preflight integration:** `scripts/session_preflight.py` exposes a `data_quality` field in the report JSON via `check_data_quality_coverage()`, reporting `tables_covered`, `checks_defined`, and `last_run` timestamp. Planning agents use this to assess telemetry health before scoping V3 plans.

**Schema coverage (12 tables):**

*Telemetry (7):* `telemetry_process_events`, `telemetry_sessions`, `telemetry_step_outcomes`, `telemetry_acceptance_results`, `telemetry_friction_events`, `telemetry_verification_results`, `telemetry_plan_audits`

*Ops (5):* `ops_recommendations`, `ops_decisions`, `ops_execution_runs`, `ops_north_star_metrics`, `ops_scheduled_findings`

### Telemetry

Verifier executions are themselves telemetered:

- `telemetry_process_events(tier=decision, category=verification_gate_pass)` when verifiers pass
- `telemetry_process_events(tier=exception, category=verification_gate_fail)` when verifiers fail

This enables the Cloud Analysis Agent (Phase E) to detect verification health trends: "verifier X has been failing for 3 consecutive sessions" triggers a Critical recommendation.

---

## Implementation Phasing

### Wave 1: Foundation (No External Dependencies)

**PLAN-verification-foundation**

1. Create `scripts/verifiers/__init__.py` with `discover_verifiers()` and `check_coverage()`
2. Create `scripts/verifiers/harness.py` with `run_verifiers()`
3. Create the verifier interface contract at `docs/contracts/verification.md`
4. Add `--integration` and `--coverage` flags to `validate.py`
5. Write tests for the harness and autodiscovery

**Gate:** `python -m scripts.verifiers.harness --list` shows the registry. `python -m scripts.validate --coverage` reports uncovered files.

### Wave 2: First Verifiers

**PLAN-verification-first-verifiers**

1. Port `validate_telemetry.py` schema checks into `scripts/verifiers/schema_integrity.py`
2. Create `scripts/verifiers/outbox_health.py` (local-only, no AWS)
3. Create `scripts/verifiers/athena_views.py`
4. Write tests for each verifier (known-good and known-bad scenarios)

**Gate:** `python -m scripts.verifiers.harness --tier V2` runs outbox_health and passes. `python -m scripts.verifiers.harness --tier V3` runs schema_integrity and athena_views against live Athena.

### Wave 3: Causal Chain + Executor Integration

**PLAN-verification-causal-chain**

1. Create `scripts/verifiers/telemetry_pipeline.py` (the E2E causal chain verifier)
2. Wire `harness.run_verifiers()` into `scripts/executor/postflight.py` as a hard gate
3. Update the implement skill to call the harness instead of self-evaluating VP steps
4. Add the same-PR guard to `validate.py`

**Constraint (Decision 44):** Step 2 modifies `scripts/executor/postflight.py`, which is an executor boundary file. The implementation plan for Wave 3 MUST route through `/plan` -> `/implement` (human-supervised), not autonomous executor. The executor cannot modify its own verification gate.

**Gate:** An executor run on a V3 plan triggers the verifier harness. If the verifier fails, the merge is blocked. Manually breaking the pipeline and running the executor results in a `verification_gate_fail` process event and no merge.

### Wave 4a: Planning Integration

**PLAN-verification-planning-integration**

1. Add coverage check to the critique agent's evaluation
2. Update the planning skill with the binary expected outcomes rule
3. Update critique agent with the E2E definition enforcement

**Gate:** A V3 plan with uncovered scope files fails critique unless it includes verifier creation. Critique rejects VP expected outcomes that use permissive language.

### Wave 4b: Scheduled Health Checks (Infrastructure)

**PLAN-verification-scheduled-checks**

1. Add daily scheduled verification as a Lambda agent or EventBridge cron
2. Wire regression detection into the recommendation pipeline (auto-file Critical recs on FAIL)
3. Add trend detection (3 consecutive FAILs = escalate to human)

**Gate:** Daily health check runs autonomously. Regressions that affect files not changed in any PR are detected within 24 hours and filed as recommendations.

### Future: Template Generator

`scripts/verifiers/generate.py` is deferred from the main waves. Agents can create verifier files directly from this INTENT spec without a generator. Implement only if verifier creation frequency exceeds 2 per week.

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| Filesystem as registry (no YAML) | Zero-maintenance. Self-registering. No sync issues between code and manifest. |
| Exit code as verdict (not LLM interpretation) | Eliminates the cooperative self-evaluation failure mode entirely. |
| Verifiers separate from verified code (same-PR guard) | Prevents conflict of interest. The implementer cannot weaken verification to pass. |
| Causal chain as strongest verification | Proves the complete data path in one atomic operation. Cannot be gamed by passing isolated stages separately. |
| Harness called by postflight, not by the agent | The agent cannot skip, substitute, or weaken the check. Python `if` statements don't negotiate. |
| Diagnostic tools retained alongside verifiers | Diagnostics (like validate_telemetry population reports) provide debugging context. Verifiers provide gates. Both are needed; they serve different purposes. |
| Verifiers must have their own tests | A verifier that incorrectly reports PASS on broken state is worse than no verifier. Tests prove the verifier correctly detects known-bad states. |
| Progressive enforcement (advisory -> hard gate) | Coverage checks start as warnings during Wave 1-2 transition. Become hard failures after Wave 3 when the harness is proven stable. Avoids blocking all work during bootstrapping. |
| E2E defined lexically (5 stages) | Eliminates miscommunication. "End-to-end" has one meaning in this codebase, enforced by the critique agent. |
| LLMs detect coverage gaps; programs enforce gates | Uses each system for what it's good at. LLMs reason about whether a verifier is needed (judgment). Programs decide whether the verifier passes (binary). |

---

## What This Does NOT Cover

1. **Code quality verification.** The code-review agent (LLM-based, Layer 3) handles style, architecture, and design judgment. Verifiers handle "does it work?"

2. **Test coverage enforcement.** `test_coverage_checker.py` already handles this. Verifiers are complementary, not a replacement.

3. **Human approval gates.** Terraform apply, production deployments, and architectural decisions remain human-gated. Verifiers cannot approve these -- they can only verify post-application state.

4. **Performance verification.** Latency SLAs, cost thresholds, and performance regression detection are future work (Phase E Cloud Analysis Agent). Verifiers focus on correctness, not performance.

5. **Security verification.** OWASP checks, credential scanning, and IAM policy verification are handled by existing tools (detect-secrets, AWS Config). Not duplicated here.

---

## Constraints

1. **Windows compatibility.** All verifier code uses `pathlib`. No shell-specific logic in check functions. Subprocess calls use list form.

2. **Test isolation.** Verifiers are no-ops when `PYTEST_CURRENT_TEST` is set. Tests for verifiers mock AWS backends.

3. **Import safety.** Verifier modules must be importable without AWS credentials. Defer boto3/awswrangler imports to function scope.

4. **Lambda compatibility.** `scripts/verifiers/__init__.py` must not import heavy dependencies at module scope (it will be imported transitively by scripts that are Lambda-packaged).

5. **No eval/exec.** Query generation uses f-strings with validated identifiers. Verifiers never construct executable code from runtime data.

6. **Graceful degradation.** If AWS credentials are unavailable, V3 verifiers skip with status "SKIPPED" (not FAIL). Only report FAIL for actual verification failures, not configuration absence.

7. **SKIPPED policy (postflight gate).** When V3 verifiers return SKIPPED (credentials unavailable), the postflight gate allows merge but emits a `verification_skipped` process event with severity `warning`. This preserves the intent without creating merge deadlocks during SSO expiry. The scheduled health check (Wave 4) catches regressions that slipped through SKIPPED gates.

8. **Timeout and retry.** Each verifier has a 120-second execution timeout. The harness retries once on FAIL before reporting aggregate FAIL. Total harness runtime is capped at 5 minutes per invocation. Verifiers exceeding timeout are reported as FAIL with detail "timeout exceeded."

9. **Test data tagging.** Causal chain verifiers that produce records must tag them for exclusion from analytics. Convention: set `session_id` with prefix `verify-{verifier_name}-` (e.g., `verify-telemetry_pipeline-2026-04-30T15:00:00Z`). Athena `_current` views and the Cloud Analysis Agent (Phase E) filter these prefixes from statistical analysis.

---

## File Reference

| File | Purpose |
|------|---------|
| `docs/INTENT-verification-system.md` | This document. Authoritative spec for verification architecture. |
| `docs/contracts/verification.md` | Interface contract. Verifier module requirements, JSON schema, exit codes. (Wave 1) |
| `scripts/verifiers/__init__.py` | Registry autodiscovery and coverage analysis. (Wave 1) |
| `scripts/verifiers/harness.py` | Orchestrates verifier execution, collects results. (Wave 1) |
| `scripts/verifiers/generate.py` | Template generator for new verifiers. (Wave 4) |
| `scripts/verifiers/telemetry_pipeline.py` | E2E causal chain: produce -> drain -> compact -> query -> assert. (Wave 3) |
| `scripts/verifiers/schema_integrity.py` | Python dataclass vs Athena DDL comparison. (Wave 2) |
| `scripts/verifiers/outbox_health.py` | Local outbox file integrity and freshness. (Wave 2) |
| `scripts/verifiers/athena_views.py` | All views execute without error. (Wave 2) |
| `scripts/verifiers/fk_integrity.py` | FK relationship validation across star schema. (Wave 2) |
| `scripts/verifiers/lambda_cold_start.py` | Each Lambda invokes successfully. (Wave 3) |
| `scripts/verifiers/ops_pipeline.py` | Ops data (recs, decisions) reach Iceberg. (Wave 3) |
| `scripts/validate.py` | Extended with `--integration` and `--coverage` flags. (Wave 1) |
| `scripts/executor/postflight.py` | Gains verifier harness call as hard gate. (Wave 3) |
| `config/agent/data_quality/telemetry.yaml` | Declarative DQ checks for 7 telemetry tables. (Existing) |
| `config/agent/data_quality/ops.yaml` | Declarative DQ checks for 5 ops tables. (Existing) |
| `scripts/data_quality_runner.py` | YAML-to-Athena-SQL compiler and executor. (Existing) |
| `scripts/session_preflight.py` | Reports `data_quality` coverage in preflight JSON. (Existing) |
| `terraform/iceberg_tables.tf` | Authoritative DDL for all 12 Iceberg tables. |
| `.agents/skills/planning/SKILL.md` | Updated with coverage check rules. (Wave 4) |
| `.agents/skills/plan-critique/SKILL.md` | Updated with binary outcomes enforcement. (Wave 4) |

---

**Last Updated:** April 30, 2026
