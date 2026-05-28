# Plan

## Intent
Enable stateless cron agents by migrating append-only log files from git-tracked local storage to S3, eliminating the need for git write access and merge conflict handling in scheduled workflows.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-s3-logs

## Phase
Phase 1: Core Infrastructure (maintenance)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| terraform/data_pipeline.tf | Modify | Add IAM policy for GitHub Actions OIDC role to access agent-logs bucket |
| terraform/main.tf | Modify | Add `aws_s3_bucket.agent_logs` resource for `bblake-platform-agent-logs` |
| terraform/variables.tf | Modify | Add variable for agent logs bucket if needed |
| terraform/outputs.tf | Modify | Add output for agent logs bucket ARN |
| scripts/s3_log_store.py | Create | Unified S3 log read/write module with local fallback |
| scripts/executor/jsonl_store.py | Modify | Add S3 backend option for recommendations and plans |
| scripts/session_preflight.py | Modify | Read recommendations from S3 when available |
| scripts/run_cron_review.py | Modify | Read/write recommendations and rejections via S3 |
| scripts/classify_risk.py | Modify | Read recommendations via S3 |
| scripts/token_budget.py | Modify | Read recommendations via S3 |
| scripts/friction_analysis.py | Modify | Read retro-lite log, write friction analysis via S3 |
| scripts/metrics_analysis.py | Modify | Read session metrics, write metrics analysis via S3 |
| scripts/run_retro_lite.py | Modify | Write retro-lite log via S3 |
| scripts/session_metrics.py | Modify | Write session metrics via S3 |
| scripts/executor/step_runner.py | Modify | Write step telemetry via S3 |
| scripts/plan_audit.py | Modify | Write plan audit log via S3 |
| scripts/north_star_tracker.py | Modify | Write north star log via S3 |
| scripts/prompt_compliance.py | Modify | Read retro-lite log via S3 |
| scripts/validate.py | Modify | Read retro-lite log via S3 |
| tests/test_s3_log_store.py | Create | Tests for S3 log module |
| tests/test_executor_jsonl_store.py | Modify | Add tests for S3 backend |
| .github/copilot-instructions.md | Modify | Document S3 log bucket and access patterns |
| config/README.md | Modify | Document S3_LOG_BUCKET environment variable |
| .gitignore | Modify | Add S3-managed log files to prevent accidental commits |

## Log File Migration Matrix

| Log File | Size | Readers | Writers | Migration Priority |
|----------|------|---------|---------|-------------------|
| `.recommendations-log.jsonl` | 64KB | jsonl_store, session_preflight, classify_risk, token_budget, run_cron_review | jsonl_store, run_cron_review | **P0** - Critical path |
| `.retro-lite-log.jsonl` | 35KB | friction_analysis, prompt_compliance, validate | run_retro_lite | **P1** - Cron agents |
| `.execution-plans.jsonl` | 776KB | jsonl_store | jsonl_store (via plan.py) | **P1** - Executor |
| `.execution-step-telemetry.jsonl` | 19KB | - | step_runner | **P2** - Telemetry |
| `.session-metrics-log.jsonl` | 12KB | metrics_analysis | session_metrics | **P2** - Metrics |
| `.friction-analysis-log.jsonl` | 5KB | session_preflight | friction_analysis | **P2** - Analysis |
| `.metrics-analysis-log.jsonl` | 8KB | session_preflight | metrics_analysis | **P2** - Analysis |
| `.plan-audit-log.jsonl` | 4KB | - | plan_audit | **P3** - Low volume |
| `.token-budget-log.jsonl` | 178KB | - | token_budget | **P3** - Can stay local |
| `.rejected-suggestions.jsonl` | 0.2KB | run_cron_review | run_cron_review | **P1** - Cron agents |
| `.north-star-log.jsonl` | - | - | north_star_tracker | **P3** - Low volume |
| `.decisions-index.jsonl` | 5KB | - | one-off script | **SKIP** - Rarely updated |
| `.transcript-index.jsonl` | 0.1KB | - | transcript_index | **SKIP** - Rarely updated |

**Files to keep local (NOT migrated):**
- `.execution-state.json` - Checkpoint state, must be local for atomic read/modify/write (managed by `scripts/execution_state.py`)
- `.preflight-report.json` - Ephemeral, regenerated each session
- `.copilot-otel.jsonl` - Already gitignored, high volume telemetry

**Race condition mitigation:**
- `update_recommendation_status()` in jsonl_store.py uses read-modify-write pattern
- This function is ONLY used by the executor which runs sequentially (one rec at a time)
- Cron agents use `append_jsonl()` only (new recs), never modify existing entries
- Therefore: keep `update_recommendation_status()` as local-only operation; migrate only read operations to S3

## Acceptance Criteria
- [ ] `terraform plan` shows new S3 bucket `bblake-platform-agent-logs` will be created
- [ ] `terraform apply` creates bucket successfully (requires SSO login)
- [ ] `scripts/s3_log_store.py` exists with `read_jsonl()`, `append_jsonl()`, `list_keys()` functions
- [ ] `S3_LOG_BUCKET` environment variable documented in config/README.md
- [ ] All modified scripts work with `S3_LOG_BUCKET` unset (local fallback)
- [ ] All modified scripts work with `S3_LOG_BUCKET=bblake-platform-agent-logs` (S3 mode)
- [ ] `python -m pytest tests/test_s3_log_store.py -v` passes
- [ ] `python -m pytest tests/` passes
- [ ] `python scripts/validate.py` exits 0

## Constraints
- AWS SDK already available via `awswrangler` (used by data pipeline)
- boto3 available in Lambda layer
- Local fallback required for offline development
- Must not break existing local workflows when S3_LOG_BUCKET is unset
- Line length limit: 127 characters (ruff E501)
- Type hints required for all new functions

## Context
- **Decision 24**: Agents use `company-aws-profile` profile only
- **AWS Region**: eu-west-2
- **Existing buckets**: `bblake-platform-{data-lake, formulas-discovery, formulas-staging, formulas-production}`
- **Known Gotcha**: Optional dependencies should use try/except ImportError pattern

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable
- [ ] AWS SSO session active: `aws sso login --profile company-aws-profile`

## Ordered Execution Steps

### Step 1: Add S3 bucket resource to Terraform
**File**: terraform/main.tf
**Action**: modify
**Description**: Add `aws_s3_bucket.agent_logs` resource for bucket `bblake-platform-agent-logs` with versioning enabled. Add lifecycle policy to expire old versions after 90 days. Add tags for Project, Purpose, Phase.
**Acceptance**: `grep -q "agent_logs" terraform/main.tf && grep -q "agent-logs" terraform/main.tf`

### Step 2: Add Terraform outputs for agent logs bucket
**File**: terraform/outputs.tf
**Action**: modify
**Description**: Add output for `agent_logs_bucket_arn` and `agent_logs_bucket_name`.
**Acceptance**: `grep -q "agent_logs" terraform/outputs.tf`

### Step 3: Create S3 log store module
**File**: scripts/s3_log_store.py
**Action**: create
**Description**: Create unified S3 log read/write module with these functions:
- `get_backend() -> Literal["s3", "local"]` - returns "s3" if S3_LOG_BUCKET is set and valid, else "local"
- `read_jsonl(key: str) -> list[dict]` - reads all lines from S3 or local file, returns list of parsed JSON objects
- `append_jsonl(key: str, entry: dict) -> bool` - appends single JSON line to S3 or local file
- `list_keys(prefix: str) -> list[str]` - lists keys under prefix (S3) or files matching glob (local)
- Local paths map to `logs/{key}` relative to repo root
- S3 keys map to `{key}` in the bucket (e.g., `recommendations/2026-04-06.jsonl`)
- Use boto3 with profile from `AWS_PROFILE` env var or default
- Handle ImportError for boto3 gracefully (fall back to local)
**Acceptance**: `python -c "from scripts.s3_log_store import get_backend, read_jsonl, append_jsonl; print('ok')"`

### Step 4: Create tests for S3 log store
**File**: tests/test_s3_log_store.py
**Action**: create
**Description**: Create test file with:
- `TestGetBackend`: test returns "local" when S3_LOG_BUCKET unset, "s3" when set
- `TestReadJsonlLocal`: test reads local JSONL file, handles missing file, handles malformed JSON
- `TestAppendJsonlLocal`: test appends to local file, creates file if missing
- `TestListKeysLocal`: test lists files matching glob pattern
- Mock boto3 for S3 tests to avoid real AWS calls
**Acceptance**: `python -m pytest tests/test_s3_log_store.py -v`

### Step 5: Update jsonl_store.py with S3 backend (READ-ONLY for S3)
**File**: scripts/executor/jsonl_store.py
**Action**: modify
**Description**:
- Import `get_backend`, `read_jsonl` from `scripts.s3_log_store`
- In `load_recommendation()` and `load_all_recommendations()`: use S3 backend when available for READS
- **IMPORTANT**: Keep `update_recommendation_status()` LOCAL-ONLY to avoid race conditions. This function uses read-modify-write which is not safe for concurrent S3 access. The executor runs sequentially so local is safe.
- Add `S3_RECS_KEY = "recommendations/recommendations.jsonl"` constant
**Acceptance**: `grep -q "s3_log_store\|get_backend" scripts/executor/jsonl_store.py`

### Step 6: Update session_preflight.py with S3 backend
**File**: scripts/session_preflight.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- In `count_recommendations()`: use `read_jsonl()` with S3 backend
- In `read_friction_patterns()`: use `read_jsonl()` for friction analysis log
- In `read_metrics_anomalies()`: use `read_jsonl()` for metrics analysis log
**Acceptance**: `grep -q "s3_log_store\|read_jsonl" scripts/session_preflight.py`

### Step 7: Update run_cron_review.py with S3 backend
**File**: scripts/run_cron_review.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Read recommendations via `read_jsonl()`
- Read rejections via `read_jsonl()`
- Write new recommendations via `append_jsonl()`
- Write new rejections via `append_jsonl()`
**Acceptance**: `grep -q "s3_log_store\|read_jsonl\|append_jsonl" scripts/run_cron_review.py`

### Step 8: Update classify_risk.py with S3 backend
**File**: scripts/classify_risk.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Read recommendations via `read_jsonl()` in `main()`
**Acceptance**: `grep -q "s3_log_store\|read_jsonl" scripts/classify_risk.py`

### Step 9: Update token_budget.py with S3 backend
**File**: scripts/token_budget.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Read recommendations in `_count_recommendations_tokens()` via `read_jsonl()`
- Note: token budget log itself can stay local (high volume, local-only use)
**Acceptance**: `grep -q "s3_log_store\|read_jsonl" scripts/token_budget.py`

### Step 10: Update friction_analysis.py with S3 backend
**File**: scripts/friction_analysis.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Read retro-lite log via `read_jsonl()`
- Write friction analysis log via `append_jsonl()`
**Acceptance**: `grep -q "s3_log_store\|read_jsonl\|append_jsonl" scripts/friction_analysis.py`

### Step 11: Update metrics_analysis.py with S3 backend
**File**: scripts/metrics_analysis.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Read session metrics log via `read_jsonl()`
- Write metrics analysis log via `append_jsonl()`
**Acceptance**: `grep -q "s3_log_store\|read_jsonl\|append_jsonl" scripts/metrics_analysis.py`

### Step 12: Update run_retro_lite.py with S3 backend
**File**: scripts/run_retro_lite.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Write retro-lite log via `append_jsonl()`
**Acceptance**: `grep -q "s3_log_store\|append_jsonl" scripts/run_retro_lite.py`

### Step 13: Update session_metrics.py with S3 backend
**File**: scripts/session_metrics.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Write session metrics log via `append_jsonl()`
**Acceptance**: `grep -q "s3_log_store\|append_jsonl" scripts/session_metrics.py`

### Step 14: Update step_runner.py with S3 backend
**File**: scripts/executor/step_runner.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Write step telemetry via `append_jsonl()` in `_log_step_telemetry()`
**Acceptance**: `grep -q "s3_log_store\|append_jsonl" scripts/executor/step_runner.py`

### Step 15: Update plan_audit.py with S3 backend
**File**: scripts/plan_audit.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Write plan audit log via `append_jsonl()`
**Acceptance**: `grep -q "s3_log_store\|append_jsonl" scripts/plan_audit.py`

### Step 16: Update north_star_tracker.py with S3 backend
**File**: scripts/north_star_tracker.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Write north star log via `append_jsonl()`
**Acceptance**: `grep -q "s3_log_store\|append_jsonl" scripts/north_star_tracker.py`

### Step 17: Update prompt_compliance.py with S3 backend
**File**: scripts/prompt_compliance.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Read retro-lite log via `read_jsonl()` in `_parse_retro_log()`
**Acceptance**: `grep -q "s3_log_store\|read_jsonl" scripts/prompt_compliance.py`

### Step 18: Update validate.py with S3 backend
**File**: scripts/validate.py
**Action**: modify
**Description**:
- Import from `scripts.s3_log_store`
- Read retro-lite log via `read_jsonl()` in friction validation
**Acceptance**: `grep -q "s3_log_store\|read_jsonl" scripts/validate.py`

### Step 19: Update test_executor_jsonl_store.py with S3 tests
**File**: tests/test_executor_jsonl_store.py
**Action**: modify
**Description**:
- Add `TestS3Backend` class with tests for S3 mode
- Mock `s3_log_store.get_backend()` to return "s3"
- Verify functions use S3 backend when available
**Acceptance**: `python -m pytest tests/test_executor_jsonl_store.py -v`

### Step 20: Document S3_LOG_BUCKET in config README
**File**: config/README.md
**Action**: modify
**Description**: Add section documenting:
- `S3_LOG_BUCKET` environment variable
- Bucket name: `bblake-platform-agent-logs`
- When to use: GitHub Actions cron agents
- Local fallback behavior when unset
**Acceptance**: `grep -q "S3_LOG_BUCKET" config/README.md`

### Step 21: Update copilot-instructions.md with S3 bucket info
**File**: .github/copilot-instructions.md
**Action**: modify
**Description**: Add to AWS section:
- New bucket: `bblake-platform-agent-logs`
- Purpose: Agent log storage for cron workflows
- Add to File Router: s3_log_store.py location
**Acceptance**: `grep -q "agent-logs" .github/copilot-instructions.md`

### Step 22: Add IAM policy for GitHub Actions OIDC
**File**: terraform/data_pipeline.tf
**Action**: modify
**Description**: Add IAM policy granting `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` permissions on the `bblake-platform-agent-logs` bucket. Attach to the GitHub Actions OIDC role (if exists) or document that this will be needed when the cron workflow is implemented.
**Acceptance**: `grep -q "agent.logs\|agent_logs" terraform/data_pipeline.tf`

### Step 23: Update .gitignore for S3-managed logs
**File**: .gitignore
**Action**: modify
**Description**: Add entries for S3-managed log files to prevent accidental commits when running in local mode. Add comment explaining these are now managed via S3 in CI but local fallback still writes them:
- `logs/.recommendations-log.jsonl` (keep tracking for now, will untrack after S3 migration is stable)
- Note: Don't untrack yet — local fallback still uses these files. Just document the intent.
**Acceptance**: `grep -q "S3-managed\|recommendations-log" .gitignore`

### Step 24: Verify execution_state.py is unaffected
**File**: N/A
**Action**: verify
**Description**: Confirm that `scripts/execution_state.py` manages `.execution-state.json` locally and does not interact with the S3 log migration. This file must remain local for atomic checkpoint operations. Run: `grep -q "execution-state.json" scripts/execution_state.py && ! grep -q "s3_log_store" scripts/execution_state.py`
**Acceptance**: `python -c "from scripts.execution_state import load_checkpoint, save_checkpoint; print('ok')"`

### Step 25: Run pytest
**File**: N/A
**Action**: verify
**Description**: Run full test suite to verify all changes work together with local fallback (S3_LOG_BUCKET unset).
**Acceptance**: `python -m pytest tests/ -v`

### Step 26: Run validate.py
**File**: N/A
**Action**: verify
**Description**: Run full validation to ensure CI will pass.
**Acceptance**: `python scripts/validate.py`

### Step 27: Apply Terraform (manual step)
**File**: N/A
**Action**: verify
**Description**: After merge, run `terraform apply` to create the S3 bucket and IAM policy. This requires AWS SSO login and is intentionally a manual step.
**Acceptance**: Manual verification that bucket exists in AWS console.

### Step 28: Report implementation summary
**File**: N/A
**Action**: report
**Description**: Summarize what was implemented, confirm local fallback works, note that S3 bucket creation is a manual post-merge step.
**Acceptance**: N/A (human review)
