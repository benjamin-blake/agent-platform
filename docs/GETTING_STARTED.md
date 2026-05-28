# Getting Started Guide

This guide provides setup instructions for both **Company Environment** (formula discovery on AWS) and **Personal Environment** (live trading on Docker).

---

## Workflow Overview

The repository uses a **multi-model agent-assisted workflow** with cross-family quality gates and free automated monitoring throughout each session.

### Standard Development Loop

1. **Plan** — Invoke `#prompts:plan` to describe what you want.
   - Runs `session_preflight.py` to check environment, recommendations, friction patterns
   - Agent asks clarifying questions
   - Creates feature branch `agent/{slug}` immediately (not deferred)
   - Writes `PLAN-{slug}.md` (tracked, branch-specific file committed to feature branch)
   - Automatically invokes `@plan-critique` (Gemini 2.5 Pro) as a mandatory gate
   - You must approve the plan before proceeding to Implement

2. **Implement** — Invoke `/implement` when ready (you are on the feature branch).
   - Reads `PLAN-{slug}.md` from current branch
   - Executes Ordered Execution Steps with automated per-step validators (free GPT-4.1 agents)
   - Captures friction via `@retro-lite` after each step
   - Runs scope-guard check at midpoint
   - Offers optional code review at end
   - **Session Close Phase** (no separate chat needed):
     - Validates code via `session_postflight.py --validate`
     - Runs retrospective with full merged context (Haiku)
     - Commits and pushes via `session_postflight.py --commit/--push`
     - Auto-merges PR after CI passes
     - Cleans up local and remote branch

### Free Monitoring Agents (GPT-4.1, 0x cost)

These run automatically during `/implement` — do not skip them:

| Agent | When | Purpose |
|-------|------|----------|
| **@step-validator** | After each Ordered Execution Step | Binary PASS/FAIL check that the step matched its spec |
| **@scope-guard** | At ~50% implementation completion | Compares git diff vs Scope table, flags unplanned changes |
| **@retro-lite** | After each step + end of session | Captures friction, missing context, deviations; output persisted by parent via `scripts/run_retro_lite.py` |

Additionally:
- **Pre-commit sanity checks** (automated, no agent) — Run via `session_postflight.py --pre-commit-sanity` before commit. Checks branch alignment, orphaned TODOs, scope drift.

### Key Entry Points

| What you want | Invoke |
|---|---|
| Start any feature/fix | `#prompts:plan` (starts on main) |
| Implement the plan | `/implement` (on the feature branch created by plan) |
| Parallel planning while implementing | `git checkout main && #prompts:plan` (creates separate `agent/{slug2}` branch) |
| Commit without full close | `#prompts:git_add_commit_message` |
| Update docs for feature branch | `#prompts:documentation` |
| Full documentation audit | `#prompts:documentation` (triggers audit routing) |
| Monthly holistic review | `#prompts:strategic_review` |

See [AGENT_WORKFLOW.md](./AGENT_WORKFLOW.md) for the complete loop diagram, decision points, and escape hatches.

---

## Unified Session Telemetry

Both workflows (manual `/plan`+`/implement` and automated `execute_recommendation.py`) write to a shared session telemetry log at `logs/.session-telemetry.jsonl`. Each entry is a session envelope containing:

- `workflow` -- `"manual"`, `"executor"`, or `"cron"`
- `branch`, `rec_id`, `plan_slug` -- cross-references to the specific work
- `outcome` -- `"merged"`, `"failed"`, `"abandoned"`, `"completed"`
- `steps_total`, `steps_completed`, `premium_requests`, `friction_count`
- `files_changed`, `lines_delta`

This provides a single queryable timeline of all work across all workflows. The executor also writes friction data to `logs/.retro-lite-log.jsonl` using the same schema as manual sessions, so `friction_analysis.py` sees a complete picture.

**Log storage:** When `S3_LOG_BUCKET` is set (e.g. in GitHub Actions cron workflows), all log reads and writes go to S3 via `scripts/s3_log_store.py`. When unset (local development), logs fall back to local `logs/` files. See `config/README.md` for the `S3_LOG_BUCKET` environment variable documentation.

**Required shell profile entry for local sessions** (enables OpsWriter write-through to Iceberg):

```bash
export S3_LOG_BUCKET=agent-platform-agent-logs  # enables OpsWriter write-through to Iceberg
```

Add this to your `~/.bashrc` or `~/.bash_profile`. Without it, `OpsWriter.write()` silently no-ops locally and ops tables will not receive data from local sessions. The preflight check (`python -m scripts.session_preflight`) warns when this is unset with active SSO.

---

## VS Code Workspace Setup

The `.vscode/settings.json` file includes workspace-specific settings:

- **`github.copilot.chat.runCommand.enabled`**: Allows Copilot to execute terminal commands without manual approval. This is safe for this workflow because:
  - Commands are constrained to the repo directory
  - Pre-commit hooks validate all changes before commit
  - All automation uses deterministic Python scripts

---

## Choose Your Environment

### Company Environment
**Where:** Company VM
**Purpose:** Formula discovery, research, infrastructure deployment
**Requires:** AWS SSO access, Terraform, SageMaker permissions
**Go to:** [Company Environment Setup](#company-environment-setup)

### Personal Environment
**Where:** Personal computer
**Purpose:** Live trading, formula testing, circuit breakers
**Requires:** Docker, S3 read-only access
**Go to:** [Personal Environment Setup](#personal-environment-setup)

---

## Company Environment Setup

Use this environment for formula discovery and AWS infrastructure management.

### Prerequisites

- **Python 3.12+**: `python --version`
- **Docker**: `docker --version`
- **AWS CLI v2**: Download from https://awscli.amazonaws.com/AWSCLIV2.msi
- **Terraform 1.0+**: `terraform version`
- **GitHub CLI (`gh`)**: `winget install GitHub.cli`, then `gh auth login` (select GitHub.com, HTTPS, browser auth). Verify: `gh auth status`. Required for CI feedback loop and automated PR creation (`session_close` Steps 5b, 5c, 5d).
- **AWS SSO Access**: To your AWS account

### Step 1: Configure AWS SSO

Add the following to `~/.aws/config`:

```ini
[profile your-aws-profile]
sso_session = your-aws-profile
sso_account_id = <your-account-id>
sso_role_name = AdministratorAccess
region = eu-west-2
output = json

[sso-session your-aws-profile]
sso_start_url = https://your-sso-portal.awsapps.com/start
sso_region = eu-west-2
sso_registration_scopes = sso:account:access
```

Authenticate:
```bash
aws sso login --profile your-aws-profile
```

Verify:
```bash
aws sts get-caller-identity --profile your-aws-profile
# Should show Account ID and assume role session
```

### Step 2: Install Dependencies

```bash
cd agent-platform

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows PowerShell
# or: source .venv/bin/activate  # Mac/Linux

# Install packages
pip install -r requirements.txt
```

### Step 3: Configure Application

```bash
# Copy company config
cp config/config.company.yaml config/config.yaml

# Edit with your settings (if needed)
# Leave defaults for initial deployment
```

### Step 4: Deploy AWS Infrastructure

```bash
cd terraform

# Copy example variables
cp terraform.tfvars.example terraform.tfvars

# Edit terraform.tfvars (update S3 bucket name if needed - must be globally unique)

# Deploy
terraform init
terraform plan -var="aws_profile=your-aws-profile"
terraform apply -var="aws_profile=your-aws-profile"

# Note the outputs (bucket names, Athena workgroup, etc.)
```

**What gets created:**
- S3 buckets: `formulas-discovery`, `formulas-staging`, `formulas-production`
- Glue catalog database with Iceberg table for `formula_lineage`
- Athena workgroups for lab and production queries
- CloudWatch dashboards for monitoring
- Cost Explorer budgets and alerts

### Step 5: Run Lab Mode (Formula Discovery)

```bash
cd ..

# Set environment
python -m src.main --environment=company lab
```

**What this does:**
1. Queries Athena for historical market data
2. Runs PySR symbolic regression (may take 30-60 minutes)
3. Backtests discovered formulas
4. Uploads formulas with lineage to `formulas-discovery` bucket
5. Appends metadata to Iceberg `formula_lineage` table

### Step 6: Verify Deployment

```bash
# Check S3 buckets exist
aws s3 ls --profile your-aws-profile | grep formulas-

# Query lineage table
aws athena start-query-execution \
  --query-string "SELECT COUNT(*) FROM formula_lineage" \
  --query-execution-context Database=trading_formulas_db \
  --work-group agent-platform-lab \
  --profile your-aws-profile

# Check CloudWatch dashboards
# Navigate to: AWS Console → CloudWatch → Dashboards
```

### Company Environment Commands

```bash
# Run formula discovery
python -m src.main --environment=company lab

# Data pipeline: dry run (no AWS needed)
python -m src.data.pipeline --dry-run --symbols HSBA.L BP.L
python -m src.data.pipeline --dry-run --universe ftse_100 --date 2026-03-20

# Query Athena for formulas
aws athena start-query-execution \
  --query-string "SELECT * FROM formula_lineage ORDER BY created_at DESC LIMIT 10" \
  --work-group agent-platform-lab \
  --profile your-aws-profile

# Check costs
aws ce get-cost-and-usage \
  --time-period Start=2026-01-01,End=2026-01-31 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --profile your-aws-profile
```

### Deploying Lambda Changes

Lambdas use zip packaging deployed via S3 (no Docker on company VM).
All five handlers share the same code package (`src/` + `config/`).

```bash
# Build + deploy Lambda code (Python)
python scripts/build_lambda.py

# Or skip S3 upload (build locally only)
python scripts/build_lambda.py --skip-upload

# Force a specific bucket
python scripts/build_lambda.py --bucket agent-platform-data-lake
```
```

#### Trigger Pipeline Manually

On Windows, `--input (Get-Content ... -Raw)` strips embedded quotes during PowerShell argument expansion. Use `[System.IO.File]::WriteAllText` (no BOM) and `file://` to bypass this:

```powershell
# Write JSON without BOM, then reference via file:// to avoid quote-stripping
[System.IO.File]::WriteAllText("$env:TEMP\sfn.json", '{"date":"auto","discovery_enabled":false}')
aws stepfunctions start-execution `
  --state-machine-arn "arn:aws:states:eu-west-2:<your-account-id>:stateMachine:agent-platform-data-pipeline" `
  --input file://$env:TEMP/sfn.json `
  --profile your-aws-profile --region eu-west-2
```

`"date": "auto"` resolves to today's date inside the Lambda. Pass an ISO date string (e.g. `"2026-03-20"`) to reprocess a specific day.

**Lambda Layers**: AWSSDKPandas-Python312:22 (managed: awswrangler/pandas/pyarrow) + extras layer (yfinance/pyyaml, ~11 MB)

---

## Personal Environment Setup

Use this environment for live trading with discovered formulas.

### Prerequisites

- **Python 3.12+**: `python --version`
- **Docker & Docker Compose**: `docker --version`, `docker-compose --version`
- **AWS CLI v2**: For S3 access to company buckets
- **AWS SSO Configured**: Same `your-aws-profile` profile (read-only S3)

### Step 1: Configure AWS SSO (Same as Company)

```bash
aws sso login --profile your-aws-profile
```

### Step 2: Install Dependencies

```bash
cd agent-platform

# Create virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows PowerShell

# Install packages
pip install -r requirements.txt
```

### Step 3: Configure Environment

```bash
# Copy personal config
cp config/config.personal.yaml config/config.yaml

# Copy Docker environment template
cp docker/.env.example docker/.env
```

Edit `docker/.env`:
```bash
# PostgreSQL
POSTGRES_PASSWORD=your-secure-password

# Company S3 Buckets (read-only access)
COMPANY_S3_PRODUCTION_BUCKET=formulas-production
COMPANY_S3_STAGING_BUCKET=formulas-staging
COMPANY_S3_REGION=eu-west-2
AWS_PROFILE=your-aws-profile
```

### Step 4: Start Docker Services

```bash
cd docker
docker-compose up -d
```

**Services started:**
- `postgres`: PostgreSQL 16 with pgvector extension
- `formula-sync`: Pulls formulas from S3 every 5 minutes
- `ab-tester`: Runs A/B test analysis daily
- `trading-system`: Live trading engine

### Step 5: Verify Setup

```bash
# Check all services running
docker-compose ps

# Expected output:
# postgres       running   healthy
# formula-sync   running
# ab-tester      running
# trading-system running

# Check formula sync
docker-compose logs formula-sync

# Check PostgreSQL
docker exec postgres psql -U trading -c "SELECT COUNT(*) FROM formula_models;"
```

### Step 6: Run Live Trading

```bash
cd ..
python -m src.main --environment=personal live
```

**What this does:**
1. Loads formulas from PostgreSQL (synced from S3)
2. Initializes RAT ensemble with formula models
3. Starts async trading engine
4. Monitors circuit breakers
5. Tracks outcomes back to lineage table

### Personal Environment Commands

```bash
# View live trading logs
docker-compose logs -f trading-system

# Check formula status
docker exec postgres psql -U trading -c "
    SELECT formula_id, state, allocation_weight, last_updated
    FROM formula_models
    ORDER BY allocation_weight DESC;
"

# Check A/B tests
docker exec postgres psql -U trading -c "
    SELECT test_id, status, control_sharpe, test_sharpe
    FROM ab_test_summary
    WHERE status = 'running';
"

# Check circuit breakers
docker exec postgres psql -U trading -c "
    SELECT formula_id, state, opened_at
    FROM circuit_breaker_state
    WHERE state != 'closed';
"

# View Grafana dashboards
# Navigate to: http://localhost:3000
# Default credentials: admin/admin

# Stop all services
docker-compose down

# Reset database (WARNING: deletes all data)
docker-compose down -v
docker-compose up -d
```

---

## Troubleshooting

### Company Environment

**Problem:** Terraform apply fails with "bucket already exists"

**Solution:**
```bash
# S3 bucket names must be globally unique
# Edit terraform/terraform.tfvars and change s3_bucket_name
# Or import existing bucket:
terraform import aws_s3_bucket.formulas_discovery formulas-discovery
```

**Problem:** SageMaker job fails with "insufficient capacity"

**Solution:**
```bash
# Switch to different instance type in lab config
# Or wait and retry (spot instances may be unavailable)
```

**Problem:** Athena queries timing out

**Solution:**
```bash
# Check data partitioning
# Reduce date range in query
# Verify Glue catalog has correct schema
```

### Personal Environment

**Problem:** Formula sync fails with "Access Denied" to S3

**Solution:**
```bash
# Verify AWS SSO login
aws sso login --profile your-aws-profile

# Test S3 access
aws s3 ls s3://formulas-production/ --profile your-aws-profile

# Check docker/.env has correct AWS_PROFILE
```

**Problem:** PostgreSQL won't start

**Solution:**
```bash
# Check if port 5432 already in use
docker-compose down
netstat -ano | findstr :5432  # Windows
lsof -i :5432  # Mac/Linux

# If postgres already running locally, stop it or change port in docker-compose.yml
```

**Problem:** Trading system shows "No formulas loaded"

**Solution:**
```bash
# Check formula-sync logs
docker-compose logs formula-sync

# Manually trigger sync
docker-compose restart formula-sync

# Verify S3 buckets have formulas
aws s3 ls s3://formulas-production/ --profile your-aws-profile
```

**Problem:** A/B tests never complete

**Solution:**
```bash
# Check test duration setting (default 14 days)
# Verify trading system is recording outcomes
docker exec postgres psql -U trading -c "
    SELECT COUNT(*) FROM ab_test_results;
"

# If zero results, check trading system is running
docker-compose logs trading-system
```

### Data Pipeline Issues

**Problem:** "Unable to verify/create output bucket"

**Solution:** Lambda IAM role needs `s3:GetBucketLocation` permission. Add it in `terraform/data_pipeline.tf`.

**Problem:** Athena MERGE type mismatch on features column

**Solution:** Ensure `dtype={"features": "map<string,double>"}` is passed in `src/data/writer.py` to override pandas inference.

**Problem:** `ALTER TABLE ADD COLUMNS` fails with `name already exists`

**Solution:** Athena Iceberg does not support `ADD COLUMN IF NOT EXISTS`. Issue one `ALTER TABLE` per column and catch the "already exists" failure to make migrations idempotent.

**Problem:** Need to run a local script against AWS

**Solution:** Set `$env:TRADING_CONFIG = "config\config.company.yaml"` before running. The default config loader reads `config/config.yaml` which has placeholder workgroup names.

**Problem:** Step Functions execution fails immediately with `ValueError: Invalid isoformat string: 'auto'`

**Solution:** The EventBridge schedule passes `"date": "auto"` as input. This is handled in `fetch_handler.py` — if you see this error it means an older Lambda version is deployed. Rebuild and redeploy: `Compress-Archive -Path src,config -DestinationPath $env:TEMP\dp.zip -Force` then upload to S3 and run `aws lambda update-function-code` for all five functions.

**Problem:** `scripts/build_lambda.py` fails with dependency install errors

**Solution:** The deps layer requires Linux-compatible wheels (`--platform manylinux2014_x86_64`). If pip cannot find matching wheels, the package will be skipped. Use `python scripts/build_lambda.py --skip-upload` to build and inspect the layer locally, then upload manually if needed.

**Problem:** A local script fails with `WorkGroup is not found`

**Solution:** Set `$env:ENVIRONMENT = "company"` before running — the config loader will automatically pick up `config/config.company.yaml`. Alternatively use `$env:TRADING_CONFIG = "config\config.company.yaml"` for an explicit path override.

**Problem:** `terraform apply` fails with `Athena query failed with status: FAILED` on `null_resource.create_iceberg_tables`

**Solution:** Athena Iceberg returns `FAILED` (not `SUCCEEDED`) for `CREATE TABLE IF NOT EXISTS` when the table already exists. This triggers whenever the DDL query hash changes (e.g. after adding a column to `iceberg_tables.tf`). The provisioner uses `on_failure = continue` so this should not abort apply. If it does, verify the table already exists: `aws glue get-table --database-name trading_formulas_db --name market_data --profile your-aws-profile`. Schema evolution on existing tables is handled by the daily pipeline's awswrangler writes (`schema_evolution=True`).

**Problem:** `terraform plan` fails with `filemd5: open .\lambda-packages\data-pipeline-extras-layer.zip: The system cannot find the file specified`

**Solution:** The extras layer zip is not tracked in git. Download it from S3 before running `terraform plan`:
```powershell
aws s3 cp s3://agent-platform-data-lake/lambda-packages/data-pipeline-extras-layer.zip lambda-packages/data-pipeline-extras-layer.zip --profile your-aws-profile --region eu-west-2
```

**Problem:** Pipeline returns empty data

**Solution:** Likely a weekend or market holiday — yfinance has no data for non-trading days. Retry with a valid trading date.

**Problem:** Lambda build / import errors

**Solution:** Ensure Python 3.12 runtime. Managed layer is `AWSSDKPandas-Python312:22`. The extras layer must be < 50 MB unzipped.

### Common Issues (Both Environments)

**Problem:** AWS SSO session expired

**Solution:**
```bash
# Re-authenticate (sessions last 8-12 hours)
aws sso login --profile your-aws-profile
```

**Problem:** Python import errors

**Solution:**
```bash
# Ensure virtual environment is activated
.\.venv\Scripts\Activate.ps1  # Windows
source .venv/bin/activate  # Mac/Linux

# Reinstall dependencies
pip install -r requirements.txt
```

**Problem:** Agent or script fails when editing files that contain emoji or non-ASCII characters (e.g., prompt files with section headings containing Unicode symbols)

**Solution:** Use Python for the file operation instead of PowerShell string manipulation. PowerShell's default encoding on Windows can misread Unicode, causing string matches to fail silently.
```python
with open('path/to/file.md', encoding='utf-8') as f:
    content = f.read()
content = content.replace('old text', 'new text')
with open('path/to/file.md', 'w', encoding='utf-8') as f:
    f.write(content)
```
---

## Next Steps

### For Company Environment:
1. **Load Historical Data**: Import market data into S3 for training
2. **Schedule SageMaker Jobs**: Set up recurring formula discovery
3. **Monitor Costs**: Review CloudWatch cost dashboards weekly
4. **Tune Hyperparameters**: Adjust PySR settings in config.yaml

### For Personal Environment:
1. **Connect Market Data Feed**: Replace mock data with real-time feed
2. **Configure Alerts**: Set up Slack webhooks for notifications
3. **Tune Trading Parameters**: Adjust position sizes, latency thresholds
4. **Monitor Performance**: Review Grafana dashboards daily

### Both Environments:
1. **Review [ROADMAP.md](./ROADMAP.md)**: Understand upcoming phases
2. **Check [DECISIONS.md](./DECISIONS.md)**: Provide input on open decisions
3. **Read [ARCHITECTURE.md](./ARCHITECTURE.md)**: Deep dive on trading system design (AWS pipeline, formula lifecycle, live trading)
4. **Read [ARCHITECTURE-WORKFLOW.md](./ARCHITECTURE-WORKFLOW.md)**: Development workflow, CI/CD, telemetry, executor, and LLM provider infrastructure

---

## CLI Telemetry & Session Features

GitHub Copilot CLI v1.0.12 provides built-in telemetry, session transcript export, and session resume. These features are validated and documented in [Decision 30](./DECISIONS.md).

### OTel Telemetry

Export OpenTelemetry spans to JSONL for token cost tracking:

```bash
export COPILOT_OTEL_FILE_EXPORTER_PATH=logs/.copilot-otel.jsonl
export OTEL_SERVICE_NAME=agent-platform
copilot -p "Your prompt" -s --no-ask-user
```

Each invocation appends 5 spans: `chat <model>`, `invoke_agent`, `gen_ai.client.operation.duration`, `gen_ai.client.token.usage`, `github.copilot.agent.turn.count`.

**Key cost fields** (in `attributes` of `chat` and `invoke_agent` spans):
- `github.copilot.cost` — integer (Copilot AIU units)
- `gen_ai.usage.input_tokens` / `gen_ai.usage.output_tokens` — token counts
- `github.copilot.server_duration` — server-side latency in ms

**Parse with:**
```python
import json
spans = [json.loads(l) for l in open('logs/.copilot-otel.jsonl')]
# Get cost from invoke_agent spans:
cost = sum(
    s['attributes'].get('github.copilot.cost', 0)
    for s in spans
    if s.get('type') == 'span' and s.get('name') == 'invoke_agent'
)
```

See rec-026 in `logs/.recommendations-log.jsonl` for `scripts/cost_report.py` implementation plan.

---

### Session Transcript Export

Export a full session transcript to Markdown:

```bash
# Non-interactive: auto-exports after completion
copilot -p "Your prompt" -s --no-ask-user \
  --share="logs/transcripts/session-$(git branch --show-current | sed 's|agent/||')-$(date +%s).md"

# Interactive: run /share inside the session
copilot --experimental
# In session:
/share file logs/transcripts/session-<slug>-<timestamp>.md
```

**Transcript format:** Markdown with `### 👤 User` / `### 💬 Copilot` sections, timestamps (locale format), session ID, duration.

**Note:** `--share` only auto-exports in non-interactive mode. Interactive sessions require the in-session `/share` command.

Transcript storage: `logs/transcripts/` (see [logs/transcripts/README.md](../logs/transcripts/README.md)).

---

### Session Resume

Resume a previous session with full context continuity:

```bash
# Resume most recent session
copilot --continue

# Choose from session list
copilot --resume

# Resume specific session by ID
copilot --resume=<session-uuid>
```

**Context persistence:** `--continue` restores the full conversation history from the most recent session. Context does NOT persist across independent sessions — only within a single continuous session thread.

---

### Standup Summary

Generate a standup from recent session history (reads `docs/SESSION_LOG.md` and git log):

```bash
copilot --experimental -p "/chronicle standup" -s --no-ask-user
```

**Note:** `/chronicle` is not a built-in slash command — the LLM interprets this prompt semantically. Equivalent to asking: `"Summarize recent branches and work done from docs/SESSION_LOG.md"`.

---

### Experimental Features

Enable experimental features for `/fleet`, `/delegate`, `/research`, and other advanced commands:

```bash
# Per-session flag
copilot --experimental -p "Your prompt"

# Or toggle inside an interactive session:
/experimental on
```

Available experimental slash commands (v1.0.12): `/fleet` (parallel subagents), `/delegate` (hand off to GitHub Copilot to create PR), `/lsp` (language server), `/tasks` (background tasks), `/plan` (agentic planning mode).

**Note:** `/chronicle improve` (for instruction suggestions) is NOT available in v1.0.12. Use an explicit prompt instead:
```bash
copilot --experimental -p "Review .github/copilot_instructions.md and propose improvements based on recent patterns in docs/SESSION_LOG.md and logs/.retro-lite-log.jsonl" -s --no-ask-user
```

---

## Automated Recommendation Execution

The system supports automated execution of low-risk recommendations via script-driven orchestration.

### Prerequisites

- Copilot CLI installed and authenticated
- `COPILOT_OTEL_FILE_EXPORTER_PATH` environment variable set (for OTel telemetry capture)
- Python environment configured with scripts module dependencies

### Usage

#### Classify Recommendation Risk

LLM-based risk classification (low/medium/high):

```bash
# Classify a single recommendation (requires manual classifier setup)
python scripts/classify_risk.py --classify-all
```

This command:
- Loads all recommendations from `logs/.recommendations-log.jsonl`
- Classifies each `unclassified` entry using Copilot CLI
- Persists risk levels back to the JSONL file

#### Execute a Recommendation

For recommendations marked `risk: low` and `automatable: true`, execute the full pipeline:

```bash
python scripts/execute_recommendation.py rec-NNN
```

The executor:
1. Loads the recommendation by ID
2. Checks eligibility (low risk + automatable)
3. Generates an implementation plan via Copilot CLI (max 3 critique iterations)
4. Executes implementation steps via Copilot CLI (gpt-4o-mini model)
5. Runs `validate.py` after each step, then runs the step's **acceptance command** to verify the goal was achieved
6. Creates git commit, pushes, and opens PR (no auto-merge)

#### Acceptance Commands in Plan Steps

Each plan step includes an `**Acceptance**` field — a runnable shell command that exits `0` on success. The executor runs it automatically after `validate.py` passes:

- **Non-empty acceptance field:** Parsed with `shlex.split()` and executed with a 60-second timeout. Non-zero exit code fails the step.
- **Empty acceptance field:** Falls back to `validate.py` only — no error.
- **Parse errors:** Malformed shell syntax (e.g., unmatched quotes) logs a warning and fails the step.

**Warning:** Avoid using `-k` selectors in pytest acceptance commands for test steps. LLM-generated test names are unpredictable and may change between runs, causing brittle or failing acceptance checks. Instead, use `grep` to verify the test exists, and run tests using the `python -m pytest tests/test_file.py::ClassName` format to ensure robust validation.

Examples of valid acceptance commands:
```bash
grep -q 'def test_my_feature' tests/test_file.py
python -m pytest tests/test_file.py::TestClass -q
grep -r "expected_pattern" src/
git diff --stat HEAD~1
```

Planners generating acceptance commands must provide runnable shell commands, not descriptive text. The executor trusts and executes any non-empty acceptance command.

#### Cost Budget

The executor tracks cumulative API cost across plan generation, critique, and implementation calls. Use `--max-cost` to override the default $2.00 limit:

```bash
python scripts/execute_recommendation.py rec-NNN --max-cost 5.0
```

If the budget is exceeded, execution aborts with an error. The `cost_usd` field from OTel telemetry is used; if telemetry returns `None`, the cost is treated as $0.00.

### Risk Levels

| Risk | Automatable | Eligible | Examples |
|------|-------------|----------|----------|
| Low | true | **YES** | Documentation updates, config changes, safe refactors |
| Low | false | – | Approved but requires human review |
| Medium | any | – | Moderate complexity or potential test gaps |
| High | any | – | Critical systems, eval/exec risks, major refactors |
| Unclassified | any | – | Pending risk evaluation |

### Architecture

The automation framework uses:

- **copilot_wrapper.py** — Subprocess abstraction for Copilot CLI with OTel metric capture (tokens, cost)
- **classify_risk.py** — LLM-based risk classification (prompt-based, no code execution)
- **execute_recommendation.py** — Single-recommendation executor (deterministic Python orchestration)

All scripts are:
- **Scriptable** — Run via shell, not agent tools (Decision 31)
- **CI-executable** — Work in GitHub Actions workflows with proper environment setup
- **Testable** — Full unit test coverage (`tests/test_*.py`)
- **Windows-compatible** — All subprocess calls work in Git Bash on Windows

### Future Work

- **rec-030**: Auto-merge evaluation (determines which low-risk recommendations can auto-merge directly)
- Extend executor to handle medium-risk recommendations with human-in-the-loop approval
- Parallel execution of multiple recommendations (via `--parallel` flag)

---

## Scheduled Agents Setup

Scheduled agents run autonomously via AWS Lambda on an hourly EventBridge trigger.
They review the codebase for quality issues using the GitHub Models API and write
findings to S3. This replaces the previous GitHub Actions approach, which was blocked
by a corporate SCP denying `sts:AssumeRoleWithWebIdentity`. See Decision 37 in
`docs/DECISIONS.md` for rationale.

### Architecture

```
EventBridge (hourly) → scheduled_agent_dispatcher Lambda
  → calls GitHub Models API for due agents
  → writes agents/{name}/{timestamp}.jsonl to S3

S3 ObjectCreated (agents/) → findings_processor Lambda
  → unions findings into findings/unified.jsonl
  → compares against recs via GitHub Models API
  → appends new recs to recommendations/agent-recommendations.jsonl
```

### Prerequisites

1. **GitHub PAT with GitHub Models API access**

   Create a Personal Access Token (PAT) at GitHub Settings → Developer Settings.
   The PAT needs access to the GitHub Models API (same as Copilot CLI access).

2. **Terraform infrastructure deployed**

   ```bash
   cd terraform
   terraform plan -out=tfplan
   terraform apply tfplan
   ```

   This creates:
   - `aws_lambda_function.scheduled_agent_dispatcher`
   - `aws_lambda_function.findings_processor`
   - `aws_secretsmanager_secret.github_pat` (placeholder value only)
   - EventBridge hourly rule
   - S3 bucket notification

3. **Set the GitHub PAT in Secrets Manager**

   After `terraform apply`, store the actual PAT value:

   ```bash
   aws secretsmanager put-secret-value \
     --secret-id agent-platform-github-pat \
     --secret-string "ghp_YOUR_PAT_HERE" \
     --profile your-aws-profile
   ```

### First Run

Invoke the dispatcher Lambda manually to verify the configuration:

```bash
aws lambda invoke \
  --function-name agent-platform-scheduled-agent-dispatcher \
  --payload '{}' \
  --profile your-aws-profile \
  output.json && cat output.json
```

### Local Testing

```bash
# List all agents
python -m scripts.run_scheduled_agent --list

# Dry-run a specific agent (no API calls)
python -m scripts.run_scheduled_agent --agent doc-freshness --dry-run

# Run all agents due at the current time
python -m scripts.run_scheduled_agent --due
```

Set `S3_LOG_BUCKET=agent-platform-agent-logs` in your environment to enable S3
output; omit it to fall back to local `logs/` files.

---

## Additional Resources

- **Documentation**:
  - [README.md](../README.md) - System overview
  - [ARCHITECTURE.md](./ARCHITECTURE.md) - Trading system design
  - [ARCHITECTURE-WORKFLOW.md](./ARCHITECTURE-WORKFLOW.md) - Development workflow and infrastructure
  - [ROADMAP.md](./ROADMAP.md) - Implementation plan
  - [DECISIONS.md](./DECISIONS.md) - Open decisions

- **External**:
  - [PySR Documentation](https://astroautomata.com/PySR/)
  - [pgvector Documentation](https://github.com/pgvector/pgvector)
  - [AWS Athena Documentation](https://docs.aws.amazon.com/athena/)
  - [Apache Iceberg Documentation](https://iceberg.apache.org/)
  - [Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)

## Getting Help

- **Issues**: Open a GitHub issue for bugs or feature requests
- **Questions**: Check existing documentation first, then create discussion
- **Contributing**: See branch strategy in README.md

- **Documentation**:
  - [README.md](../README.md) - System overview
  - [ARCHITECTURE.md](./ARCHITECTURE.md) - Trading system design
  - [ARCHITECTURE-WORKFLOW.md](./ARCHITECTURE-WORKFLOW.md) - Development workflow and infrastructure
  - [ROADMAP.md](./ROADMAP.md) - Implementation plan
  - [DECISIONS.md](./DECISIONS.md) - Open decisions

- **External**:
  - [PySR Documentation](https://astroautomata.com/PySR/)
  - [pgvector Documentation](https://github.com/pgvector/pgvector)
  - [AWS Athena Documentation](https://docs.aws.amazon.com/athena/)
  - [Apache Iceberg Documentation](https://iceberg.apache.org/)
  - [Terraform AWS Provider](https://registry.terraform.io/providers/hashicorp/aws/latest/docs)

## Getting Help

- **Issues**: Open a GitHub issue for bugs or feature requests
- **Questions**: Check existing documentation first, then create discussion
- **Contributing**: See branch strategy in README.md
