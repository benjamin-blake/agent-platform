# Plan

## Intent
Fix the broken data pipeline so that ALL Iceberg tables (7 telemetry + 3 ops) are populated with real data from local workflows. Without working drain and compaction, the outbox is a dead end -- telemetry, recommendations, and decisions written locally never reach S3 or Athena. This blocks the Phase E Cloud Analysis Agent and makes the autonomous improvement loop blind.

## Plan Type
IMPLEMENTATION

## Verification Tier
V3

## Branch
agent/platform-telemetry-pipeline-fix

## Phase
Phase Platform (automation infrastructure)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| config/config.company.yaml | Modify | Add `s3_agent_logs_bucket` key under `aws:` section |
| scripts/ops_writer.py | Modify | Make `_bucket()` resolve from config when env var is unset |
| config/README.md | Modify | Document the new `aws.s3_agent_logs_bucket` config key |
| tests/test_ops_writer.py | Modify | Add tests for config-based bucket resolution |
| scratch/verify_pipeline.py | Create | VP verification script for post-deploy causal chain |

## Bundled Recommendations
None.

## Acceptance Criteria
- [ ] `config/config.company.yaml` has `aws.s3_agent_logs_bucket: agent-platform-agent-logs`
- [ ] `OpsWriter._bucket()` resolves from config when `S3_LOG_BUCKET` env var is unset and `ENVIRONMENT=company`
- [ ] `OpsWriter._bucket()` returns the env var when it IS set (Lambda unchanged)
- [ ] After a session open/close + drain + compact cycle, the `telemetry_sessions` record is queryable in Athena
- [ ] After `drain_pending()` + compact, `ops_recommendations` records flow to Iceberg
- [ ] `python -m scripts.validate` exits 0

## Verification Plan
| # | Phase | Action | Command | Expected Outcome | Fix If |
|---|-------|--------|---------|-------------------|--------|
| 1 | [pre-deploy] | Unit tests pass | `python -m pytest tests/test_ops_writer.py -q --tb=short` | All pass, exit 0 | Fix test or implementation logic |
| 2 | [pre-deploy] | Validate passes | `python -m scripts.validate` | Exit 0 | Fix lint/import errors |
| 3 | [post-deploy] | Lambda deploy (ops_writer.py is Lambda-packaged) | `python -m scripts.build_lambda --deploy` | Deploy succeeds, no import errors | Fix config import (guard with try/except) |
| 4 | [post-deploy] | Lambda cold-start verification | `aws lambda invoke --function-name agent-platform-scheduled-agent-dispatcher --payload '{"force_agent":"doc-freshness"}' --cli-binary-format raw-in-base64-out --cli-read-timeout 900 --profile company-aws-profile /tmp/lambda-out.json && cat /tmp/lambda-out.json` | StatusCode 200, agents_failed 0 | Fix import path in Lambda context |
| 5 | [post-deploy] | PRODUCE + TRANSPORT + COMPACT + QUERY (causal chain) | `AWS_PROFILE=company-aws-profile ENVIRONMENT=company python scratch/verify_pipeline.py` | Script produces a session record, drains to S3, compacts, queries Athena, asserts row exists with correct fields. Prints PASS. | Fix bucket resolution, drain path, or compact logic |
| 6 | [post-deploy] | GATE: validate_telemetry confirms pipeline works | `AWS_PROFILE=company-aws-profile python -m scripts.validate_telemetry` | telemetry_sessions verdict not FAIL. Exit 1 acceptable (other tables need executor run). | Pipeline regression |

## Constraints
- AWS profile `company-aws-profile` required for S3 and Athena operations
- `S3_LOG_BUCKET` value is `agent-platform-agent-logs` (from terraform/scheduled_agents.tf)
- Must not break Lambda handlers (env var takes priority over config -- Lambda always has it set)
- Must not break pytest (telemetry writes are no-ops under PYTEST_CURRENT_TEST)
- Config resolution order: env var > config file
- Lazy import of `src.common.config` inside `_bucket()` to avoid import-time failures

## Context
- **Root Cause:** `OpsWriter._bucket()` returns `""` when `S3_LOG_BUCKET` env var is unset. All write paths (`write()`, `emit()`) early-return on empty bucket. `drain()` calls `write()`, so outbox flush silently no-ops. `compact()` reads from S3 staging (populated by `write()`), so compaction finds nothing. Local outbox is a dead end.
- **Single fix point:** `_bucket()` is called by `write()`, `emit()`, and `compact()`. Fixing it once fixes ALL consumers without redundant env var mutations in calling code.
- **Why 2 tables work:** Lambda handlers have `S3_LOG_BUCKET` set via Terraform env vars. They bypass the broken config path entirely.
- **Same bug in ops pipeline:** `ops_data_portal.py` calls `OpsWriter().write("ops_recommendations", ...)`. Same silent no-op.
- **Decision 51:** Outbox is local-first for crash resilience. drain() MUST run before compact() -- drain pushes outbox -> S3, compact reads S3 -> Iceberg.
- **Config pattern:** `src/common/config.py` resolves `ENVIRONMENT=company` -> `config.company.yaml`. Used by `migrate_schema.py`. Same pattern extends naturally.
- **Known gotcha (awswrangler 3.x):** `temp_s3_dir` -> `temp_path` rename.
- **Known gotcha (Iceberg integer promotion):** Integer columns promoted to bigint.

## Pre-Implementation Checklist
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts -- Decision 51 requires drain to work)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add `s3_agent_logs_bucket` to config.company.yaml

Add under the `aws:` section in `config/config.company.yaml`:

```yaml
  # Agent logs and telemetry staging
  s3_agent_logs_bucket: agent-platform-agent-logs
```

**Acceptance:** `grep -q "s3_agent_logs_bucket" config/config.company.yaml`

---

### Step 2: Fix `_bucket()` in OpsWriter to resolve from config

Modify `scripts/ops_writer.py` -- change the `_bucket()` method:

```python
def _bucket(self) -> str:
    bucket = os.environ.get(_BUCKET_ENV_VAR, "").strip()
    if bucket:
        return bucket
    # Fallback: resolve from config (company VM without env var)
    try:
        from src.common.config import config  # noqa: PLC0415
        return config.get("aws.s3_agent_logs_bucket", "")
    except Exception:
        return ""
```

This is the single fix point. All consumers -- `write()`, `emit()`, `compact()`, and any code calling these via `drain()` or `drain_pending()` -- automatically benefit.

**Acceptance:** `grep -q "s3_agent_logs_bucket" scripts/ops_writer.py && python -c "import os; os.environ.pop('S3_LOG_BUCKET', None); os.environ['ENVIRONMENT']='company'; from scripts.ops_writer import OpsWriter; b=OpsWriter()._bucket(); assert b == 'agent-platform-agent-logs', f'got: {b}'; print('OK')"`

---

### Step 3: Add tests for bucket resolution

Modify `tests/test_ops_writer.py`:

Add `TestBucketResolution` class:
- `test_env_var_takes_priority`: Set S3_LOG_BUCKET env var, assert `_bucket()` returns it regardless of config
- `test_config_fallback`: Unset S3_LOG_BUCKET, set ENVIRONMENT=company, assert `_bucket()` returns `agent-platform-agent-logs`
- `test_no_env_no_config`: Unset S3_LOG_BUCKET, mock config.get to raise, assert `_bucket()` returns `""`

**Acceptance:** `python -m pytest tests/test_ops_writer.py -q --tb=short`

---

### Step 4: Update config/README.md

Add documentation for the new key:

```markdown
| `aws.s3_agent_logs_bucket` | S3 bucket for agent logs, telemetry staging, and ops data compaction. Used by OpsWriter when `S3_LOG_BUCKET` env var is unset. Lambda handlers use the Terraform-set env var instead. |
```

**Acceptance:** `grep -q "s3_agent_logs_bucket" config/README.md`

---

### Step 5: Create scratch/verify_pipeline.py

Create a VP verification script that runs the full causal chain:

```python
"""End-to-end pipeline verification: produce -> drain -> compact -> query.

Usage: AWS_PROFILE=company-aws-profile ENVIRONMENT=company python scratch/verify_pipeline.py
"""
```

The script must:
1. Call `session_preflight --open-session` to produce a telemetry_sessions record
2. Call `session_postflight --close-session` to finalize it
3. Check local outbox has the file OR S3 has the batch
4. Call `sync_ops.drain()` to push outbox -> S3
5. Call `OpsWriter().compact("telemetry_sessions")` to push S3 -> Iceberg
6. Query Athena for the record (poll for completion)
7. Assert the row has non-null session_id, workflow, outcome
8. Print PASS/FAIL with details

**Acceptance:** `python scratch/verify_pipeline.py --help`

---

### Step 6: Run test suite and validate

Run `python -m pytest tests/test_ops_writer.py -q --tb=short` -- all tests must pass.

Run `python -m scripts.validate` -- must exit 0.

**Acceptance:** `python -m scripts.validate`

---

### Step 7: Lambda build and deploy

Since `scripts/ops_writer.py` is in `_LAMBDA_SCRIPTS`, rebuild and deploy:

1. `python -m scripts.build_lambda --deploy`
2. Invoke Lambda to verify cold-start works with the new config import

**Acceptance:** `python -m scripts.build_lambda --deploy`

---

### Step 8: Execute Verification Plan (CAUSAL CHAIN)

Run each VP step (1-6) from the table above:

- VP#1-2: Pre-deploy gates (tests + lint)
- VP#3-4: Lambda deploy + cold-start proof
- VP#5: **The critical causal chain** -- produce, transport, compact, query, assert
- VP#6: Validation tool confirms improvement

VP#5 is the end-to-end proof. If it prints PASS with a real Athena row containing non-null session_id, workflow, and outcome dated today -- the pipeline is proven for ALL tables.

If any VP step fails: fix the code, re-run tests + validate, re-attempt. Do NOT merge with failing verification.

---

### Step 9: Report

Report: what was implemented, verification results (actual outcomes from VP steps), the specific pipeline verification output, and any bugs found and fixed.
