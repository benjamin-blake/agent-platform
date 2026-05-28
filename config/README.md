# Configuration Guide

This directory is split into three zones:

- **Root (shared):** `config.yaml`, `config.yaml.example`, `config.company.yaml`, `config.personal.yaml` -- runtime config loaded by `src.common.config`. Bundled into Lambda zips.
- **`lambda/<name>/`:** Per-Lambda runtime payloads. Bundled into `<name>.zip` by `scripts/build_lambda.py`. Initially empty placeholders for `data-pipeline` and `ops-compaction`.
- **`agent/<consumer>/`:** Agent-consumed config (DQ rules, executor prompts, copilot registry, IAM manifest). NOT bundled into any Lambda zip. Only Claude Code agents and CI scripts read from here.

## Configuration Files

### `config.company.yaml`
**Use on:** Company VM
**Purpose:** Formula discovery, AWS infrastructure management, SageMaker jobs
**Features:**
- Full AWS access (S3 read/write, Athena queries, SageMaker orchestration)
- Lab mode settings (PySR hyperparameters)
- Terraform deployment settings
- Lineage tracking configuration

### `config.personal.yaml`
**Use on:** Personal computer
**Purpose:** Live trading, formula testing, A/B tests, circuit breakers
**Features:**
- S3 read-only access to company formula buckets
- PostgreSQL local database settings
- Trading parameters (position sizes, latency thresholds)
- A/B testing configuration
- Meta-learner settings

### `config.yaml` (Active Configuration)
**What it is:** Symlink or copy of either `config.company.yaml` or `config.personal.yaml`
**How to use:**
```bash
# Company environment
cp config/config.company.yaml config/config.yaml

# Personal environment
cp config/config.personal.yaml config/config.yaml
```

**Alternative:** Set `TRADING_CONFIG` environment variable:
```bash
# Company
export TRADING_CONFIG=/path/to/config.company.yaml

# Personal
export TRADING_CONFIG=/path/to/config.personal.yaml
```

## Configuration Sections

### AWS (Company Only)
```yaml
aws:
  region: eu-west-2
  profile: your-aws-profile
  s3_discovery_bucket: agent-platform-formulas-discovery
  s3_staging_bucket: agent-platform-formulas-staging
  s3_production_bucket: agent-platform-formulas-production
  s3_data_lake_bucket: agent-platform-data-lake
  s3_agent_logs_bucket: agent-platform-agent-logs
  glue_database: trading_formulas_db
  athena_lab_workgroup: agent-platform-lab
  athena_prod_workgroup: agent-platform-production
```

| Key | Purpose |
|-----|---------|
| `aws.s3_agent_logs_bucket` | S3 bucket for agent logs, telemetry staging, and ops data compaction. Used by `OpsWriter` when `S3_LOG_BUCKET` env var is unset. Lambda handlers use the Terraform-set env var instead. |
<!-- Evidence: File_18 (config/config.company.yaml) -->

### Company S3 (Personal Only)
```yaml
company:
  s3_production_bucket: formulas-production
  s3_staging_bucket: formulas-staging
  s3_region: eu-west-2
  aws_profile: your-aws-profile  # Read-only access
  formula_sync_interval_seconds: 300  # 5 minutes
```

### PostgreSQL (Both)
```yaml
postgres:
  host: localhost  # postgres for Docker
  port: 5432
  database: trading
  user: trading
  # Password from environment variable: POSTGRES_PASSWORD
```

### Trading (Both)
```yaml
trading:
  max_position_size: 1000.0
  latency_threshold: 0.1  # 100ms
  min_signal_threshold: 0.1
```

### Lab (Company Only)
```yaml
lab:
  pysr_iterations: 100
  min_sharpe_ratio: 0.5
  backtest_period_days: 252  # 1 year
```

### SageMaker (Company Only)
```yaml
sagemaker:
  instance_type: ml.c5.2xlarge
  use_spot_instances: true
  max_runtime_seconds: 3600
```

### A/B Testing (Personal Only)
```yaml
ab_testing:
  enabled: true
  test_duration_days: 14
  traffic_split: 0.5  # 50/50
  min_trades_for_significance: 100
  evaluation_frequency_hours: 24
```

### Live Trading (Both)
```yaml
live:
  memory_retrieval_top_k: 10
  embedding_dim: 128
  max_active_formulas: 50
```

### Meta-Learner (Both)
```yaml
meta_learner:
  use_gating_network: true
  learning_rate: 0.001
  hidden_dim: 64
  weight_decay_rate: 0.1  # 10% per day for underperformers
  min_allocation_weight: 0.01  # Below this, demote to staging
  max_allocation_weight: 0.20  # Cap at 20% per formula
```

## Environment Variables

### Required for Both Environments
```bash
POSTGRES_PASSWORD=your-secure-password
AWS_PROFILE=your-aws-profile
```

### Optional Overrides
```bash
# Override config file location
TRADING_CONFIG=/path/to/custom-config.yaml

# Override specific settings
POSTGRES_HOST=custom-host
POSTGRES_PORT=5433
MAX_POSITION_SIZE=500.0
```

### Scheduled Agents

```bash
# S3 bucket for agent log output. When set, agents write findings to S3.
# When unset, falls back to local logs/ directory.
S3_LOG_BUCKET=agent-platform-agent-logs

# Optional: override the model used for ALL scheduled agents (ignores
# per-agent model in .github/agents/schedule.yaml). Useful for testing.
# Example values: gpt-5-mini, gpt-5.4
SCHEDULED_AGENT_MODEL=gpt-5-mini

# GitHub PAT with copilot scope. Required for scheduled agents running in
# GitHub Actions. The default GITHUB_TOKEN does not have this scope.
# Store as repository secret COPILOT_PAT — see docs/GETTING_STARTED.md.
GITHUB_TOKEN=ghp_your_pat_here
```

### Company Environment Only
```bash
# For SageMaker jobs
SAGEMAKER_ROLE_ARN=arn:aws:iam::YOUR_ACCOUNT_ID:role/SageMakerRole
```

### Personal Environment Only
```bash
# S3 access (if not using AWS SSO)
COMPANY_AWS_ACCESS_KEY_ID=xxx
COMPANY_AWS_SECRET_ACCESS_KEY=xxx

# Slack notifications
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx
```

## Switching Environments

### Method 1: Copy Config
```bash
# Switch to company environment
cp config/config.company.yaml config/config.yaml
python -m src.main --environment=company lab

# Switch to personal environment
cp config/config.personal.yaml config/config.yaml
python -m src.main --environment=personal live
```

### Method 2: Environment Variable
```bash
# Company environment
export TRADING_CONFIG=config/config.company.yaml
python -m src.main --environment=company lab

# Personal environment
export TRADING_CONFIG=config/config.personal.yaml
python -m src.main --environment=personal live
```

### Method 3: CLI Flag
```bash
# Auto-loads config based on environment flag
python -m src.main --environment=company lab
python -m src.main --environment=personal live
```
<!-- Evidence: File_53 (src/main.py) - argparse --environment flag implemented -->

## Validation

Check configuration is loaded correctly:
```python
from src.common.config import config

# Print current environment
print(f"Environment: {config.get('environment')}")

# Validate company settings
if config.get('environment') == 'company':
    assert config.get('aws.s3_discovery_bucket'), "Missing discovery bucket"
    assert config.athena_lab_workgroup, "Missing Athena workgroup"

# Validate personal settings
if config.get('environment') == 'personal':
    assert config.get('company.s3_production_bucket'), "Missing company S3 bucket"
    assert config.get('ab_testing.enabled'), "Missing A/B testing config"
```
<!-- Evidence: File_32 (src/common/config.py) - Config class uses get() for nested keys -->

## Troubleshooting

**Problem:** Config file not found

**Solution:**
```bash
# Check current directory
pwd

# Verify file exists
ls config/

# Set explicit path
export TRADING_CONFIG=$(pwd)/config/config.yaml
```

**Problem:** AWS credentials not found

**Solution:**
```bash
# Re-authenticate SSO
aws sso login --profile your-aws-profile

# Verify profile exists
cat ~/.aws/config | grep your-aws-profile

# Test access
aws sts get-caller-identity --profile your-aws-profile
```

**Problem:** PostgreSQL connection fails

**Solution:**
```bash
# Check Docker is running
docker ps | grep postgres

# Verify environment variable
echo $POSTGRES_PASSWORD

# Test connection
psql -h localhost -U trading -d trading
```

## Best Practices

1. **Never commit credentials**: Use environment variables or AWS SSO
2. **Use example files**: Create `.example` versions without secrets
3. **Validate on startup**: Check required settings before running
4. **Document changes**: Update this README when adding new config options
5. **Environment-specific**: Keep company and personal configs separate
6. **Version control**: Track config structure changes in Git

## Environment Variables

### `S3_LOG_BUCKET`

Controls where agent log files are read from and written to.

| Value | Behaviour |
|-------|-----------|
| unset (default) | Local fallback — logs written to `logs/` directory in repo |
| `agent-platform-agent-logs` | S3 mode — reads and appends go to the agent-logs S3 bucket |

**When to set:** GitHub Actions scheduled agents (e.g., `run_scheduled_agent`, `retro-lite`, `session_metrics`).
Setting this variable eliminates the need for git write access in scheduled workflows.

**Local development:** Leave unset. All scripts fall back to `logs/` directory automatically.

**Affected scripts:**
- `scripts/s3_log_store.py` — unified read/write module (the source of truth)
- `scripts/session_metrics.py`, `scripts/run_scheduled_agent.py`, `scripts/plan_audit.py`
- `scripts/north_star_tracker.py`, `scripts/executor/step_runner.py`
- `scripts/prompt_compliance.py`, `scripts/validate.py`, `scripts/session_preflight.py`

**Example (GitHub Actions):**
```yaml
env:
  S3_LOG_BUCKET: agent-platform-agent-logs
  AWS_PROFILE: your-aws-profile
```

---

### `copilot_model_routing.yaml`

**Purpose:** Provider-aware model routing configuration for the executor pipeline (rec-379, Decision 53).
**Active provider:** Gemini CLI (personal Google Pro plan, 1,500 req/day).
**Dormant provider:** Bedrock (reactivate via `LLM_PROVIDER=bedrock` if/when AWS quota throttling is resolved).

**Used by:** `scripts/model_registry.py` -- `resolve_model()`, `escalate_model()`, `resolve_provider()`.

**Structure:**
- `providers.gemini` -- model tier names to Gemini 3 model IDs (pro/flash/auto)
- `providers.bedrock` -- dormant DeepSeek/Opus model IDs
- `executor.roles` -- per-role effort-band to model-tier mappings
- `executor.roles.implementation.file_pattern_floors` -- file patterns that force pro tier
- `executor.escalation` -- tier escalation ladder (flash -> auto -> pro -> null/human)

**Interactive sessions** (VS Code Copilot Chat: `/plan`, `/implement`, agents) are NOT controlled by this config.
