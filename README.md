# Hybrid Lakehouse Trading System

A production-ready dual-environment trading system combining AWS Lakehouse architecture with advanced machine learning for formula discovery, automated testing, and adaptive model selection.

## Overview

This system implements a complete end-to-end trading pipeline split across two environments:

### **Company Environment (AWS - Research & Development)**
- **Formula Discovery**: PySR symbolic regression on SageMaker using historical Athena data
- **Data Lake**: S3 + Glue + Iceberg for ACID-compliant market data storage
- **Lifecycle Management**: Automated progression through discovery → staging → production buckets
- **Lineage Tracking**: Iceberg table maintaining complete formula provenance

### **Personal Environment (Docker - Live Trading)**
- **RAT Ensemble**: Retrieval-Augmented Trading with pgvector memory
- **Formula Integration**: Dynamic loading from company S3 buckets
- **A/B Testing**: Automated statistical testing before production promotion
- **Execution Engine**: Async trading with latency penalties and circuit breakers
- **Meta-Learning**: Automated formula weighting based on rolling performance

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│            COMPANY ENVIRONMENT (AWS Account)                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Company VM (Development & Research)                     │ │
│  │  • Terraform (deploy infrastructure)                    │ │
│  │  • Lab Mode (PySR formula discovery)                    │ │
│  │  • SageMaker (orchestrate training jobs)                │ │
│  │  • Athena (query historical data)                       │ │
│  └────────────────────────────────────────────────────────┘ │
│                              ↓                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ AWS Infrastructure                                      │ │
│  │  • S3 Buckets: discovery / staging / production        │ │
│  │  • Glue Catalog + Iceberg Tables (lineage tracking)    │ │
│  │  • Athena Workgroups (lab + production queries)        │ │
│  │  • CloudWatch (monitoring + cost alerts)               │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              ↓
              Formula Discovery → S3 Upload → Versioning
                              ↓
┌──────────────────────────────────────────────────────────────┐
│          PERSONAL ENVIRONMENT (Docker Containers)             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Personal Computer (Live Trading)                        │ │
│  │  • PostgreSQL + pgvector (market memory)               │ │
│  │  • Formula Sync (pull from S3 every 5 min)             │ │
│  │  • A/B Testing (statistical promotion)                 │ │
│  │  • RAT Ensemble (formulas as models)                   │ │
│  │  • Execution Engine (async + circuit breakers)         │ │
│  │  • Meta-Learner (automated weighting)                  │ │
│  │  • Grafana (local dashboards)                          │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              ↓
              Outcomes Tracked → Lineage Updated → Metrics Exported
```

## Current State (March 2026)

**✅ Working Today:**
- Market data pipeline (Step Functions: Fetch → Features → Write → Maintenance → Discovery)
- FTSE 100 daily ingestion via yfinance (87 symbols, verified)
- Feature engine (~18 indicators: technicals, sentiment, fundamentals)
- awswrangler MERGE upsert to Iceberg (copy-on-write, idempotent)
- Table maintenance (OPTIMIZE BIN_PACK + VACUUM 7-day retention)
- AWSSDKPandas managed Lambda layer (Python 3.12)
- Basic RAT ensemble with PostgreSQL pgvector memory
- Async execution engine with latency penalties
- Meta-learner gating network for model weighting
- Terraform infrastructure for AWS Lakehouse (4 S3 buckets, Glue, Athena, Iceberg)
- Lab mode with PySR formula discovery
- Docker containerization for local development
- Safe formula evaluation (sympy, no eval/exec)

**🔜 Next Priority (See [ROADMAP.md](docs/ROADMAP-PRODUCT.md) Phase 1.5):**
- **Schema flattening**: Promote ~18 features from map to native columns for formula discovery performance
- **Pre-calculated deltas**: Momentum, volatility, z-scores, sentiment velocity as columns
- **Backfill**: 1-month hourly validation → 20-year daily historical data

**🚧 Future Phases (See [ROADMAP.md](docs/ROADMAP-PRODUCT.md)):**
- **Phase 2**: Formula integration as RAT models (2 weeks)
- **Phase 3**: Automated A/B testing framework (3 weeks)
- **Phase 4**: Circuit breakers with failure detection (1 week)
- **Phase 5**: CloudWatch + Grafana monitoring (2 weeks)
- **Phase 6**: Automated formula weighting & decay (2 weeks)

**Total Development Timeline:** 14-17 weeks

## Features

### 1. Formula Discovery (Company Environment)
- **Symbolic Regression**: PySR on SageMaker discovers profitable trading formulas
- **Historical Analysis**: Athena queries years of market data from S3 Iceberg tables
- **Automated Backtesting**: Performance metrics (Sharpe ratio, max drawdown, returns)
- **Version Control**: Every formula includes complete lineage (training data, hyperparameters, code commit)
- **JSONL Storage**: S3 buckets partitioned by date for efficient querying

### 2. Formula Lifecycle Management
- **Discovery Bucket**: Raw SageMaker outputs with initial backtest metrics
- **Staging Bucket**: Formulas undergoing A/B testing (14-day evaluation)
- **Production Bucket**: Statistically validated formulas for live trading
- **Deprecated**: Underperforming formulas archived with rollback capability
- **State Machine**: `discovered → testing → staging → production → deprecated`

### 3. A/B Testing Framework (Phase 3)
- **Automated Testing**: New formulas automatically enter 50/50 traffic split vs control
- **Statistical Validation**: T-test for significance (p < 0.05, minimum 100 trades)
- **Auto-Promotion**: GitHub Actions promotes winners to production bucket
- **Manual Override**: Emergency promotion/demotion scripts for critical situations
- **Slack Notifications**: Test completion alerts with performance summary

### 4. RAT Ensemble (Personal Environment)
- **Retrieval-Augmented Trading**: Uses market memory for context-aware predictions
- **pgvector Integration**: Fast similarity search (< 10ms) for historical patterns
- **Formula as Models**: Each discovered formula becomes independent RAT model
- **Dynamic Loading**: Pulls from S3 every 5 minutes, auto-adds to ensemble
- **Memory Storage**: Stores outcomes for continuous learning and adaptation

### 5. Circuit Breakers (Phase 4)
- **Per-Formula Monitoring**: Tracks last 100 outcomes per formula
- **Automatic Pause**: Opens circuit if win rate < 30%, stops execution
- **Auto-Recovery**: Tests formula after 1 hour, re-enables if performance improves
- **Demotion**: Persistent failures moved from production → staging bucket
- **Slack Alerts**: Immediate notification when breaker opens

### 6. Meta-Learner with Auto-Weighting (Phase 6)
- **Adaptive Ensemble**: Neural gating network learns optimal formula weights
- **Performance-Based**: Weights adjust based on rolling 30-day Sharpe ratio
- **Decay Function**: Reduces weight 10%/day for underperforming formulas (Sharpe < 0.3)
- **Auto-Demotion**: Formulas below 1% weight moved to staging
- **Capacity Management**: Maximum 50 active production formulas

### 7. Execution Engine
- **Asynchronous Loop**: Non-blocking execution with asyncio
- **Latency Penalties**: Automatically reduces position sizes for slow computations (> 100ms)
- **Performance Tracking**: Real-time metrics on compute times and penalties
- **Adaptive Position Sizing**: Signal strength determines position size

### 8. Monitoring & Observability (Phase 5)
- **CloudWatch Dashboards**: Formula performance, costs, operational metrics
- **Grafana Local**: Personal computer visualizes PostgreSQL data
- **Cost Monitoring**: AWS Cost Explorer alerts at 80% budget threshold
- **Metrics Exported**: Hourly export from personal computer to CloudWatch
- **Alerts**: Slack notifications for underperformance, high latency, cost overruns

## Quick Start

### Prerequisites
- **Company Environment**: Python 3.12+, Docker, AWS CLI v2, Terraform 1.0+, AWS SSO configured
- **Personal Environment**: Python 3.12+, Docker & Docker Compose

See detailed setup in [GETTING_STARTED.md](docs/GETTING_STARTED.md) for environment-specific instructions.

### Company Environment Setup (Research & Formula Discovery)

1. **Configure AWS SSO**:
```bash
aws configure sso
# SSO start URL: https://REDACTED-EMPLOYER.awsapps.com/start/#/?tab=accounts
# SSO region: eu-west-2
# Account ID: REDACTED-ACCOUNT-ID

aws sso login --profile company-aws-profile
```

2. **Deploy Infrastructure**:
```bash
cd terraform
terraform init
terraform apply -var-file="terraform.tfvars"
# Creates: S3 buckets, Glue catalog, Athena workgroups, Iceberg tables
```

3. **Run Lab Mode (Formula Discovery)**:
```bash
python -m src.main --environment=company lab
# Queries Athena → PySR discovers formulas → Uploads to S3 discovery bucket
```

### Personal Environment Setup (Live Trading)

1. **Configure Environment**:
```bash
cp config/config.personal.yaml config/config.yaml
cp docker/.env.example docker/.env
# Edit .env with company S3 bucket credentials
```

2. **Start Docker Services**:
```bash
cd docker
docker-compose up -d
# Starts: PostgreSQL, formula-sync, ab-tester, trading-system
```

3. **Run Live Trading**:
```bash
python -m src.main --environment=personal live
# Pulls formulas from S3 → Loads into RAT ensemble → Executes trades
```

### Verify Setup

**Company Environment:**
```bash
# Check infrastructure deployed
aws s3 ls | grep formulas-
# Should see: formulas-discovery, formulas-staging, formulas-production

# Verify Iceberg table
aws athena start-query-execution \
  --query-string "SELECT COUNT(*) FROM formula_lineage" \
  --work-group agent-platform-lab
```

**Personal Environment:**
```bash
# Check Docker services
docker-compose ps
# Should show: postgres (healthy), formula-sync (running), trading-system (running)

# Verify formula loading
docker exec postgres psql -U trading -c "SELECT COUNT(*) FROM formula_models;"
```

## Project Structure

```
.
├── terraform/                    # AWS infrastructure (company environment)
│   ├── main.tf                  # S3 buckets, Glue, Athena
│   ├── iceberg_tables.tf        # Formula lineage table
│   ├── monitoring.tf            # CloudWatch dashboards
│   ├── cost_monitoring.tf       # AWS Cost Explorer alerts
│   └── outputs.tf               # Export bucket names
├── src/                         # Python source code
│   ├── common/                  # Shared utilities
│   │   ├── config.py           # Configuration management
│   │   ├── database.py         # PostgreSQL + Athena clients
│   │   ├── formula_loader.py   # [Phase 2] S3 → PostgreSQL sync
│   │   └── metrics.py          # [Phase 5] CloudWatch metrics
│   ├── data/                    # Market data pipeline
│   │   ├── feature_engine.py   # ~18 indicators per symbol
│   │   ├── pipeline.py         # Pipeline orchestrator
│   │   ├── provider_base.py    # Abstract data provider interface
│   │   ├── universe.py         # FTSE 100 symbol universe
│   │   ├── writer.py           # awswrangler MERGE upsert to Iceberg
│   │   ├── yfinance_provider.py # YFinance data provider
│   │   └── handlers/           # Lambda handlers for Step Functions
│   │       ├── discovery_handler.py  # Step 5: Trigger PySR discovery
│   │       ├── feature_handler.py    # Step 2: Compute features
│   │       ├── fetch_handler.py      # Step 1: Fetch OHLCV data
│   │       ├── maintenance_handler.py # Step 4: OPTIMIZE + VACUUM
│   │       └── write_handler.py      # Step 3: MERGE upsert to Iceberg
│   ├── lab/                     # Formula discovery (company only)
│   │   ├── pysr_factory.py     # Symbolic regression
│   │   └── lineage_tracker.py  # [Phase 1] Append to Iceberg
│   ├── live/                    # Live trading (personal only)
│   │   ├── rat_ensemble.py     # RAT ensemble orchestration
│   │   ├── formula_rat_model.py # [Phase 2] Formula as RAT model
│   │   ├── ab_testing.py       # [Phase 3] A/B test framework
│   │   ├── circuit_breaker.py  # [Phase 4] Failure detection
│   │   ├── auto_rebalancer.py  # [Phase 6] Weight adjustment
│   │   └── outcome_tracker.py  # [Phase 1] Track to lineage
│   ├── execution/               # Async execution engine
│   │   └── async_engine.py     # Trading loop with latency penalties
│   ├── meta_learner/            # Gating network
│   │   └── gating_network.py   # [Phase 6] Auto-weighting
│   └── main.py                  # Entry point with --environment flag
├── scripts/                     # Utility scripts
│   ├── sync_athena_to_pgvector.py  # [Deprecated] Replaced by formula_loader
│   ├── export_metrics_to_cloudwatch.py  # [Phase 5] Hourly metrics export
│   ├── cost_report.py          # [Phase 5] Weekly cost breakdown
│   ├── promote_formula.py      # [Phase 3] Manual promotion
│   └── stop_ab_test.py         # [Phase 3] Emergency test stop
├── docker/                      # Docker configuration (personal only)
│   ├── Dockerfile              # Trading system image
│   ├── docker-compose.yml      # [Phase 1] PostgreSQL, formula-sync, ab-tester
│   ├── .env.example            # Environment variables template
│   └── grafana/                # [Phase 5] Local dashboards
├── config/                      # Configuration files
│   ├── config.company.yaml     # [Phase 1] Company environment
│   ├── config.personal.yaml    # [Phase 1] Personal environment
│   └── README.md               # [Phase 1] Config documentation
├── tests/                       # Test suite
│   ├── test_config.py
│   ├── test_execution.py
│   ├── test_meta_learner.py
│   ├── test_ab_testing.py      # [Phase 3] A/B test validation
│   └── test_formula_safety.py  # [Phase 2] Security tests
├── .github/                     # CI/CD workflows
│   └── workflows/
│       ├── ci.yml
│       ├── deploy.yml
│       └── formula-promotion.yml  # [Phase 3] Auto-promotion
├── docs/                        # Project documentation
│   ├── ROADMAP-PRODUCT.md       # 6-phase product implementation plan
│   ├── ROADMAP-PLATFORM.yaml    # Platform tier items and governance
│   ├── DECISIONS.md             # Open architectural decisions
│   ├── ARCHITECTURE.md          # Trading system design
│   ├── ARCHITECTURE-WORKFLOW.md  # Development workflow, CI/CD, telemetry, executor
│   ├── GETTING_STARTED.md       # Setup guide per environment
│   └── plans/                   # Branch-specific plan files (PLAN-{slug}.md)
├── logs/                        # Session tracking files (git-tracked; folder gitignored)
└── README.md                    # This file

Legend:
  [Phase N] - To be implemented in roadmap phase N
  [Deprecated] - Marked for removal/replacement
```

**Files by Environment:**

| File | Company VM | Personal Computer |
|------|------------|-------------------|
| `terraform/*` | ✅ Deploy | ❌ Read-only |
| `src/lab/*` | ✅ Run | ❌ Not needed |
| `src/live/*` | ❌ Not needed | ✅ Run |
| `src/common/*` | ✅ Config/Athena | ✅ Formula loader |
| `docker/*` | ❌ Not needed | ✅ Run |
| `config/config.company.yaml` | ✅ Use | ❌ Not needed |
| `config/config.personal.yaml` | ❌ Not needed | ✅ Use |

## Development

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific test suites
pytest tests/test_execution.py -v
pytest tests/test_meta_learner.py -v
```

### Linting

```bash
flake8 src/
black src/
mypy src/
```

### Pre-commit Hooks

Automatically run on every commit:
- Trailing whitespace removal
- YAML/JSON validation
- Secret detection
- Line ending fixes

## Documentation

- **[ROADMAP.md](docs/ROADMAP-PRODUCT.md)**: 6-phase implementation plan with timelines and acceptance criteria
- **[DECISIONS.md](docs/DECISIONS.md)**: Open architectural decisions requiring input
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)**: Trading system design and component documentation (AWS pipeline, formula lifecycle, live trading)
- **[ARCHITECTURE-WORKFLOW.md](docs/ARCHITECTURE-WORKFLOW.md)**: Development workflow, CI/CD strategy, telemetry, executor, and LLM provider architecture
- **[GETTING_STARTED.md](docs/GETTING_STARTED.md)**: Environment-specific setup guides
- **[CHANGELOG.md](docs/CHANGELOG.md)**: Version history and release notes

## Implementation Phases

See [ROADMAP.md](docs/ROADMAP-PRODUCT.md) for complete details.

**Phase 1 (2 weeks) ✅ COMPLETE**: Core Infrastructure
- Multi-bucket S3 architecture
- Iceberg lineage tracking
- Config split (company/personal)
- Market data pipeline (5-step Step Functions)
- awswrangler MERGE upsert writer
- Table maintenance (OPTIMIZE + VACUUM)

**Phase 1.5 (2-3 weeks) ← NEXT**: Schema Flattening, Deltas & Backfill
- Promote ~18 features from map to native columns
- Pre-calculated deltas (momentum, volatility, z-scores)
- 1-month hourly backfill (schema validation)
- 20-year daily historical backfill

**Phase 2 (2 weeks)**: Formula Integration
- Strategy A: Formulas as RAT models
- pgvector schema
- S3 → PostgreSQL loader
- Safe evaluation (sympy)

**Phase 3 (3 weeks)**: A/B Testing
- Automated 50/50 traffic split
- Statistical significance testing
- GitHub Actions promotion
- Manual override scripts

**Phase 4 (1 week)**: Circuit Breakers
- Per-formula failure detection
- Automatic pause on underperformance
- Slack alerts
- Auto-recovery logic

**Phase 5 (2 weeks)**: Monitoring
- CloudWatch dashboards
- Grafana local visualization
- Cost monitoring & alerts
- Metrics export from personal computer

**Phase 6 (2 weeks)**: Auto-Weighting
- Sharpe-based weight adjustment
- Decay function for underperformers
- Auto-demotion to staging
- Weight history tracking

**Total Timeline:** 14-17 weeks

## Key Decisions

See [DECISIONS.md](docs/DECISIONS.md) for full context on all decisions:

**Open:**
1. **A/B Test Duration**: 7, 14, or 30 days? (Recommendation: 14 days, configurable)
2. **Formula Capacity**: Fixed cap of 50 or dynamic based on resources?
3. **Disaster Recovery**: Auto-pause tests or auto-demote formulas if personal computer offline?

**Decided:**
4. **Formula Evaluation**: sympy AST parsing, never eval()/exec()
5. **Iceberg Write Strategy**: awswrangler MERGE upsert via Athena (replaced PyIceberg)
6. **Commit Mode**: Copy-on-write (COW) — Athena's only Iceberg mode
7. **Schema Flattening**: Promote features from map to native columns, keep map as landing zone
8. **Pre-Calculated Deltas**: Momentum, volatility, z-scores, sentiment velocity as columns
9. **Backfill Strategy**: 1-month hourly validation → 20-year daily production

## Security

- **Formula Evaluation**: Uses sympy AST parsing, never `eval()` or `exec()`
- **AWS Access**: SSO authentication, no static keys in repository
- **S3 Encryption**: All buckets encrypted at rest with AES-256 (SSE-S3)
- **Least Privilege**: IAM policies restrict access to minimum required permissions
- **Secrets Management**: Environment variables for credentials, never committed to Git

## Cost Optimization

**Company AWS Account (Monthly Estimates):**
- SageMaker (spot instances): $50-100
- S3 Storage: $20-30
- Athena Queries: $30-50
- Glue Catalog: $5-10
- **Total**: ~$105-190/month

**Personal Computer:**
- Docker (local): $0
- Compute: Existing hardware
- **Total**: $0/month

**Cost Controls:**
- S3 lifecycle policies (90 days → Glacier)
- Spot instances for SageMaker
- AWS Cost Explorer alerts at 80% budget
- Deprecated formulas deleted after 2 years

## CI/CD

**GitHub Actions Workflows:**

- **CI Pipeline** (`.github/workflows/ci.yml`):
  - Runs tests on every PR
  - Validates Terraform syntax
  - Builds Docker images
  - Lints code (flake8, black, mypy)

- **Deploy Pipeline** (`.github/workflows/deploy.yml`):
  - Deploys infrastructure to AWS (company environment)
  - Triggered on merge to `main`

- **Formula Promotion** (`.github/workflows/formula-promotion.yml` - Phase 3):
  - Detects new formulas in discovery bucket
  - Validates safety (no eval/exec)
  - Copies to staging bucket
  - Creates A/B test
  - Promotes winners to production

## Configuration

**Company Environment** (`config/config.company.yaml`):
```yaml
environment: company
aws:
  region: eu-west-2
  profile: company-aws-profile
  s3_discovery_bucket: formulas-discovery
  s3_staging_bucket: formulas-staging
  s3_production_bucket: formulas-production
  glue_database: trading_formulas_db
  athena_lab_workgroup: agent-platform-lab
sagemaker:
  instance_type: ml.c5.2xlarge
  use_spot_instances: true
lab:
  pysr_iterations: 100
  min_sharpe_ratio: 0.5
```

**Personal Environment** (`config/config.personal.yaml`):
```yaml
environment: personal
company:
  s3_production_bucket: formulas-production
  s3_staging_bucket: formulas-staging
  s3_region: eu-west-2
  aws_profile: company-aws-profile  # Read-only access
postgres:
  host: localhost
  port: 5432
  database: trading
  user: trading
trading:
  max_position_size: 1000.0
  latency_threshold: 0.1
ab_testing:
  enabled: true
  test_duration_days: 14
  traffic_split: 0.5
live:
  memory_retrieval_top_k: 10
  embedding_dim: 128
meta_learner:
  use_gating_network: true
  learning_rate: 0.001
```

## License

MIT License - See [LICENSE](LICENSE) file for details.

## Contributing

1. Create a feature branch from `develop`
2. Make your changes
3. Run tests and linting
4. Submit a pull request with description

**Branch Strategy:**
- `main`: Production-ready code
- `develop`: Integration branch
- `feature/*`: New features
- `bugfix/*`: Bug fixes
- `hotfix/*`: Critical production fixes

## Support

- **Issues**: Open a GitHub issue for bugs or feature requests
- **Documentation**: See [GETTING_STARTED.md](docs/GETTING_STARTED.md) for setup help
- **Roadmap**: Check [ROADMAP.md](docs/ROADMAP-PRODUCT.md) for upcoming features
- **Decisions**: Review [DECISIONS.md](docs/DECISIONS.md) for architectural choices

## Acknowledgments

- **PySR**: Symbolic regression framework
- **pgvector**: PostgreSQL vector similarity search
- **Apache Iceberg**: ACID-compliant data lake tables
- **AWS Athena**: Serverless SQL query engine (engine v3)
- **awswrangler**: AWS SDK for pandas — Iceberg integration via `athena.to_iceberg()`
- **AWSSDKPandas**: Managed Lambda layer providing awswrangler, pandas, pyarrow
