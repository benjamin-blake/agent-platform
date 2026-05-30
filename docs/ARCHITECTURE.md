# Trading System Architecture

This document describes the architecture of the Lakehouse Trading System: a dual-environment system combining AWS infrastructure (formula discovery and market data ingestion) with a personal Docker environment (live trading). For development workflow, CI/CD strategy, telemetry, and executor infrastructure, see [ARCHITECTURE-WORKFLOW.md](./ARCHITECTURE-WORKFLOW.md).

---

## Table of Contents

- [High-Level Architecture](#high-level-architecture)
- [AWS Lakehouse](#aws-lakehouse)
- [Market Data Pipeline](#market-data-pipeline)
- [Formula Lifecycle Management](#formula-lifecycle-management)
- [Lab Module](#lab-module)
- [Formula Integration](#formula-integration)
- [Live Module](#live-module-rat-ensemble)
- [Execution Module](#execution-module)
- [A/B Testing Framework](#ab-testing-framework)
- [Circuit Breakers](#circuit-breakers)
- [Meta-Learner with Auto-Weighting](#meta-learner-with-auto-weighting)
- [Feature Architecture](#feature-architecture-phase-2)
- [Sync Service](#sync-service)
- [Data Flow Examples](#data-flow-examples)
- [Deployment Options](#deployment-options)
- [Performance Characteristics](#performance-characteristics)
- [Cost Optimization](#cost-optimization)
- [Authentication & Credentials](#authentication--credentials-management)
- [Security Considerations](#security-considerations)
- [Error Handling Patterns](#error-handling-patterns)
- [Resilience Patterns](#resilience-patterns)
- [Configuration Management](#configuration-management)
- [Monitoring & Observability](#monitoring--observability)
- [Future Enhancements](#future-enhancements)
- [Related Documents](#related-documents)

---

## High-Level Architecture

The Lakehouse Trading System is a **dual-environment system** split between company AWS infrastructure (formula discovery) and personal Docker deployment (live trading).

```
┌──────────────────────────────────────────────────────────────┐
│            COMPANY ENVIRONMENT (AWS Account)                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Company VM (Development & Research)                     │ │
│  │  • Terraform → Deploy AWS infrastructure               │ │
│  │  • Lab Mode → PySR formula discovery                   │ │
│  │  • SageMaker → Orchestrate training jobs               │ │
│  │  • Athena → Query historical market data               │ │
│  │  • Lineage Tracker → Append to Iceberg                 │ │
│  └────────────────────────────────────────────────────────┘ │
│                              ↓                                │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ AWS Infrastructure                                      │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │ │
│  │  │ agent-platform-data-lake (S3 + Iceberg)             │   │ │
│  │  │  discovery/  →  staging/  →  production/            │   │ │
│  │  └──────────────────────────────────────────────────   │ │
│  │                                                         │ │
│  │  ┌─────────────────────────────────────────────┐      │ │
│  │  │ Glue + Iceberg: formula_lineage table       │      │ │
│  │  │  • SageMaker job metadata                   │      │ │
│  │  │  • Training data provenance                 │      │ │
│  │  │  • Production outcomes (appended from live) │      │ │
│  │  └─────────────────────────────────────────────┘      │ │
│  │                                                         │ │
│  │  ┌─────────────────────────────────────────────┐      │ │
│  │  │ CloudWatch Monitoring                       │      │ │
│  │  │  • Formula performance dashboards           │      │ │
│  │  │  • Cost Explorer alerts                     │      │ │
│  │  │  • Metrics from personal computer           │      │ │
│  │  └─────────────────────────────────────────────┘      │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              ↓
              Formula Discovery → S3 Upload → Versioning
                              ↓
┌──────────────────────────────────────────────────────────────┐
│          PERSONAL ENVIRONMENT (Docker Containers)             │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Personal Computer (Live Trading)                        │ │
│  │                                                         │ │
│  │  ┌─────────────────────────────────────────────┐      │ │
│  │  │ PostgreSQL + pgvector                       │      │ │
│  │  │  • Market memory (historical outcomes)      │      │ │
│  │  │  • Formula models (loaded from S3)          │      │ │
│  │  │  • A/B test results                         │      │ │
│  │  │  • Circuit breaker state                    │      │ │
│  │  └─────────────────────────────────────────────┘      │ │
│  │                          ↓                              │ │
│  │  ┌─────────────────────────────────────────────┐      │ │
│  │  │ Formula Sync Service (every 5 min)          │      │ │
│  │  │  • Pull from S3 production/staging buckets  │      │ │
│  │  │  • Validate formulas (sympy safety check)   │      │ │
│  │  │  • Load into PostgreSQL                     │      │ │
│  │  │  • Add to RAT ensemble dynamically          │      │ │
│  │  └─────────────────────────────────────────────┘      │ │
│  │                          ↓                              │ │
│  │  ┌─────────────────────────────────────────────┐      │ │
│  │  │ A/B Testing Service (daily analysis)        │      │ │
│  │  │  • 50/50 traffic split (control vs test)    │      │ │
│  │  │  • Statistical significance testing          │      │ │
│  │  │  • Auto-promotion to production bucket      │      │ │
│  │  │  • Slack notifications                      │      │ │
│  │  └─────────────────────────────────────────────┘      │ │
│  │                          ↓                              │ │
│  │  ┌─────────────────────────────────────────────┐      │ │
│  │  │ Trading Engine                              │      │ │
│  │  │  • RAT Ensemble (formulas as models)        │      │ │
│  │  │  • Meta-learner (auto-weighting)            │      │ │
│  │  │  • Execution (async + latency penalties)    │      │ │
│  │  │  • Circuit breakers (failure detection)     │      │ │
│  │  └─────────────────────────────────────────────┘      │ │
│  │                          ↓                              │ │
│  │  ┌─────────────────────────────────────────────┐      │ │
│  │  │ Grafana Dashboard (local visualization)     │      │ │
│  │  └─────────────────────────────────────────────┘      │ │
│  └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                              ↓
      Outcomes Tracked → Lineage Updated → Metrics to CloudWatch
```

---

## AWS Lakehouse

**Purpose**: Store and analyze historical market data, discover trading formulas

**Components**:
- **S3 Multi-Bucket Architecture**:
  - `agent-platform-data-lake/discovery/`: Raw SageMaker outputs with initial backtest metrics
  - `agent-platform-data-lake/staging/`: Formulas undergoing A/B testing
  - `agent-platform-data-lake/production/`: Statistically validated formulas for live trading
  - `data-lake`: Iceberg tables for market data and backtest results
  - Lifecycle policies: 90 days → Glacier, deprecated deleted after 2 years
  - Encrypted at rest with AES-256 (SSE-S3)

- **Glue Catalog**: Metadata repository
  - Schema definitions for market data
  - Iceberg table for `formula_lineage` (append-only audit trail)
  - Iceberg table for `market_data` (OHLCV + features, partitioned by `trade_date`)
  - Database name: `trading_formulas_db`
  - Partition management via Iceberg metadata (zero-maintenance, no MSCK REPAIR TABLE)

- **Athena**: SQL query engine
  - Serverless query execution via Athena engine v3
  - Separate workgroups for lab vs production (`agent-platform-lab`)
  - Direct querying of S3 data
  - MERGE INTO for upserts via awswrangler
  - OPTIMIZE (BIN_PACK) for table maintenance; snapshot expiry via Iceberg table properties
  - Prepares training datasets for PySR formula discovery

- **Iceberg Tables**: ACID transactions
  - `formula_lineage`: Complete provenance tracking
  - `market_data`: OHLCV + computed features, partitioned by `trade_date`; `interval` column discriminates grain (`1d`, `1h`, etc.)
    - Write mode: MERGE upsert matched on (symbol, timestamp, interval, source)
    - Commit mode: Copy-on-write (COW) — Athena's only supported mode
    - Maintenance: OPTIMIZE (BIN_PACK) after each write; snapshot expiry via `write.metadata.delete-after-commit.enabled` + `write.metadata.previous-versions-max=10` table properties
  - `backtest_results`: Formula backtest outcomes
  - `trading_performance`: Live trade P&L tracking
  - `ab_test_results`: A/B test outcomes
  - Schema evolution support
  - Time travel queries (within Iceberg metadata retention window)
  - Snapshot-based commits (safe for concurrent/repeated writes)

---

## Market Data Pipeline

**Purpose**: Automated daily ingestion of FTSE 100 market data with feature enrichment

**Architecture**: AWS Step Functions state machine with 5 Lambda steps:
```
EventBridge (6pm UTC, weekdays)
  ↓
┌──────────────────────┐
│ 1. FetchMarketData   │ ← yfinance batch download → staging S3 Parquet
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ 2. ComputeFeatures   │ ← technicals + sentiment + fundamentals → staging S3
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ 3. WriteToIceberg    │ ← MERGE upsert via awswrangler → market_data table
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ 4. TableMaintenance  │ ← OPTIMIZE (BIN_PACK); snapshot expiry via table properties
└──────────┬───────────┘
           ↓
┌──────────────────────┐
│ 5. TriggerDiscovery  │ ← (optional) PySR formula discovery
└──────────────────────┘
```

**Data Flow**:
1. EventBridge triggers the Step Functions state machine daily at 18:00 UTC
2. FetchMarketData Lambda downloads FTSE 100 OHLCV from yfinance → writes raw Parquet to S3 staging
3. ComputeFeatures Lambda reads raw Parquet, computes ~18 features per row → writes enriched Parquet to S3 staging
4. WriteToIceberg Lambda reads enriched Parquet, MERGE upserts to the `market_data` Iceberg table via awswrangler
   - Rows matched on (symbol, timestamp, interval, source) — existing rows updated, new rows inserted
   - Uses Athena engine v3 for atomic Iceberg commits
   - Copy-on-write (COW) mode — the only mode Athena supports, optimal for read-heavy tables
5. TableMaintenance Lambda runs OPTIMIZE (BIN_PACK)
   - OPTIMIZE compacts small Parquet files into larger ones for faster scans
   - Snapshot expiry is handled automatically via Iceberg table properties
     (`write.metadata.delete-after-commit.enabled=true`, `write.metadata.previous-versions-max=10`)
   - Athena engine v2 (`primary` workgroup) does not support the Iceberg `VACUUM` command;
     table properties are used instead and require no workgroup override
   - Non-fatal: failures skip to discovery step
6. (Optional) TriggerDiscovery Lambda runs PySR on the accumulated market data

**Lambda Stack**:
- **Runtime**: Python 3.12
- **Managed Layer**: `AWSSDKPandas-Python312:22` (awswrangler, pandas, pyarrow, boto3)
- **Extras Layer**: yfinance + pyyaml + transitive deps (~11 MB zipped)
- **Code Package**: `src/` + `config/` zipped, deployed via S3

**Current Features** (stored in `features map<string,double>`):
- **Technicals**: RSI(14), MACD(12,26,9), Bollinger Band width, ATR(14), SMA(20/50/200), EMA(12/26), volume ratio, momentum (5d/10d/20d), 20d volatility
- **Sentiment**: CNN Fear & Greed Index (market-wide)
- **Fundamentals**: P/E ratio, market cap, dividend yield (per symbol)

**Planned Schema Evolution** (see ROADMAP.md Phase 2):
The `features map<string,double>` column will be flattened into native Iceberg columns
for the ~18 stable indicators. This is critical for formula discovery performance —
PySR tests millions of formula combinations (e.g., `(feat_a / delta_b) * log(feat_c)`)
and native column access is orders of magnitude faster than map key lookups. The `features`
map will remain as a landing zone for experimental data sources (new sentiment feeds,
alternative data) before they are promoted to dedicated columns.

Additionally, pre-calculated delta columns will be added:
- **Price momentum**: 1-day, 5-day, 20-day percentage changes
- **Rolling volatility**: 10-day realised volatility (std of returns)
- **Z-scores**: 30-day normalised values for cross-stock comparison
- **Sentiment velocity**: Rate of change of sentiment scores

**Table Maintenance**:
- OPTIMIZE runs BIN_PACK after each write to compact small files
- Snapshot expiry handled automatically via Iceberg table properties (no VACUUM)
- Both are idempotent and safe to run on every pipeline invocation
- Note: `VACUUM` requires Athena engine v3 (`agent-platform-production` workgroup);
  the pipeline uses engine v2-compatible operations only to keep maintenance simple

**Data Source Extensibility**:
- `source` column in `market_data` discriminates providers (e.g., `yfinance`, `alpha_vantage`)
- New providers implement `MarketDataProvider` abstract base class
- Multiple sources union onto the same table with different source flags
- `features` map column acts as a landing zone for experimental data sources
  before they earn dedicated columns

**Scalability**:
- Schedule starts at once-daily; increase to multiple times per day by adding more EventBridge rules
- Iceberg snapshot-based commits handle concurrent writes safely
- Step Functions provides retry, error handling, and execution history out of the box
- Planned: hourly interval ingestion for intraday data
- Planned: backfill capability for 20 years of historical daily data

---

## Formula Lifecycle Management

### State Machine

```
┌─────────────┐
│ DISCOVERED  │ ← SageMaker completes job, uploads to discovery bucket
└──────┬──────┘
       │ GitHub Actions validates formula safety
       ↓
┌─────────────┐
│  TESTING    │ ← Copied to staging bucket, A/B test created
└──────┬──────┘
       │ 50/50 traffic split for 14 days
       │ Personal computer tracks outcomes
       ↓
  ┌────────┐
  │ Result?│
  └───┬────┘
      │
      ├─→ Test wins (p < 0.05) ─→ ┌────────────┐
      │                            │  STAGING   │ ← Low allocation (5-10%)
      │                            └─────┬──────┘
      │                                  │ Performance validated for 30 days
      │                                  ↓
      │                            ┌────────────┐
      │                            │ PRODUCTION │ ← Full allocation via meta-learner
      │                            └─────┬──────┘
      │                                  │ Continuous monitoring
      │                                  │ Circuit breaker detection
      │                                  │ Auto-weighting based on Sharpe
      │                                  ↓
      │                            Performance degrades?
      │                                  │
      └─→ Test loses (p >= 0.05) ──┐    │
                                    ↓    ↓
                              ┌─────────────┐
                              │ DEPRECATED  │ ← Archived in S3
                              └─────────────┘
```

### State Transitions

**DISCOVERED → TESTING**:
- Trigger: GitHub Actions detects new formula in discovery bucket
- Validation: AST parsing (no eval/exec), whitelist check on functions
- Action: Copy to staging bucket, create A/B test record in PostgreSQL

**TESTING → STAGING**:
- Trigger: A/B test completes with test formula winning
- Criteria: `test_sharpe > control_sharpe AND p_value < 0.05 AND min_trades >= 100`
- Action: Copy to production bucket with low allocation weight (5-10%)

**STAGING → PRODUCTION**:
- Trigger: 30-day validation period passes without issues
- Criteria: Circuit breaker never opened, consistent Sharpe > 0.5
- Action: Increase allocation weight via meta-learner

**PRODUCTION → DEPRECATED**:
- Trigger: Circuit breaker opens repeatedly, or weight decays to < 1%
- Criteria: Win rate < 30% over 100 trades, or Sharpe < 0.3 for 30 days
- Action: Remove from ensemble, archive to deprecated folder in S3

---

## Lab Module

**Purpose**: Use symbolic regression on SageMaker to discover profitable trading formulas

**Key Classes**:
- `FormulaFactory`: Main interface for formula discovery
- `FormulaDiscoveryPipeline`: End-to-end workflow
- `LineageTracker`: Appends metadata to Iceberg table

**Process**:
1. Query historical data from Athena (prepares training dataset)
2. Extract features and target variable
3. Run PySR symbolic regression on SageMaker
4. Backtest discovered formulas
5. Store results with lineage to S3 `agent-platform-data-lake/discovery/`
6. Append metadata to `formula_lineage` Iceberg table

**Output Format** (JSONL):
```json
{
  "formula_id": "uuid-123",
  "formula": "tanh(0.5*momentum + 0.3*volume_ratio)",
  "version": "1.0",
  "source": "sagemaker-pysr",
  "created_at": "2026-01-31T10:30:00Z",
  "state": "discovered",
  "metrics": {
    "sharpe_ratio": 1.8,
    "max_drawdown": -0.15,
    "total_return": 0.45
  },
  "lineage": {
    "sagemaker_job_id": "job-456",
    "training_data_s3": "s3://bucket/data/2025-01-01.parquet",
    "athena_execution_id": "exec-789",
    "pysr_hyperparameters": {
      "niterations": 100,
      "populations": 15
    },
    "code_commit_hash": "abc123"
  }
}
```

### Overfitting Prevention

PySR can easily discover formulas that overfit historical data. Apply these measures:

- **Walk-forward validation**: Anchored time-series splits — never random train/test
- **PySR parsimony**: High complexity penalty (0.03-0.05), maxsize cap (~20 nodes)
- **Multiple hypothesis correction**: Bonferroni/Benjamini-Hochberg on Sharpe ratios
- **Regime diversification**: Formulas must profit in at least 2 of 3 regimes (bull/bear/sideways)
- **Cross-asset validation**: Hold out ~27 symbols from the FTSE 100 training set for validation
- **Live A/B testing**: 14-day test on live data is the ultimate overfitting detector

---

## Formula Integration

**Purpose**: Load discovered formulas from S3 and integrate into RAT ensemble

### Strategy A: Formulas as RAT Models (Current Implementation)

Each discovered formula becomes an independent RAT model in the ensemble:

**Key Classes**:
- `FormulaLoader`: Downloads from S3, syncs to PostgreSQL (runs every 5 min)
- `FormulaRATModel`: Wraps formula as RAT model with memory
- `RATEnsemble`: Orchestrates multiple models including formula-based ones

**Process**:
1. FormulaLoader pulls from `agent-platform-data-lake/production/` and `agent-platform-data-lake/staging/`
2. Validates formula safety (sympy AST parsing, whitelist functions)
3. Computes embedding vector for formula characteristics
4. Stores in PostgreSQL `formula_models` table with pgvector index
5. RATEnsemble dynamically adds FormulaRATModel instance
6. Each formula has isolated memory for context retrieval

**pgvector Schema**:
```sql
CREATE TABLE formula_models (
    formula_id UUID PRIMARY KEY,
    formula_expression TEXT NOT NULL,
    embedding vector(128),
    source VARCHAR(50),
    version VARCHAR(20),
    state VARCHAR(20),
    allocation_weight FLOAT DEFAULT 0.1,
    created_at TIMESTAMP DEFAULT NOW(),
    last_updated TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ON formula_models USING ivfflat (embedding vector_cosine_ops);

CREATE TABLE formula_outcomes (
    id SERIAL PRIMARY KEY,
    formula_id UUID REFERENCES formula_models(formula_id),
    timestamp TIMESTAMP DEFAULT NOW(),
    symbol VARCHAR(20),
    market_features JSONB,
    predicted_signal FLOAT,
    actual_outcome FLOAT,
    context_similarity FLOAT,
    execution_time_ms FLOAT
);

CREATE INDEX ON formula_outcomes(formula_id, timestamp DESC);
```

**Formula Evaluation (Security)**:
```python
from sympy import sympify, lambdify

def evaluate_formula_safe(formula_str: str, features: dict) -> float:
    """Safely evaluate formula without eval()/exec()."""
    expr = sympify(formula_str)

    allowed = {'tanh', 'log', 'exp', 'sin', 'cos', 'abs', 'sign', 'sqrt'}
    used_functions = {str(f) for f in expr.atoms() if f.is_Function}

    if not used_functions.issubset(allowed):
        raise ValueError(f"Formula uses disallowed functions: {used_functions - allowed}")

    func = lambdify(list(features.keys()), expr, 'numpy')
    return float(func(**features))
```

### Strategy C: Hybrid Approach (Future Upgrade Path)

Combine formulas as both models AND feature engineers:

- Some formulas generate new features: `formula_1 = tanh(0.5*momentum + 0.3*volume)`
- Other formulas are standalone models with memory
- Meta-learner weights both feature-enhanced core models and formula models
- More complex but higher capacity

Documented in [ROADMAP.md](./ROADMAP.md) Phase 8+ (post-launch enhancements).

---

## Live Module (RAT Ensemble)

**Purpose**: Real-time trading using retrieval-augmented predictions

**Key Classes**:
- `VectorMemory`: Interface to pgvector database
- `RATModel`: Base class for RAT models
- `FormulaRATModel`: Formula-specific RAT model (Phase 3)
- `RATEnsemble`: Orchestrates all models (core + formulas)

**Process**:
1. Receive current market features
2. Compute embedding vector
3. Retrieve similar historical patterns from pgvector
4. Generate predictions using context
5. Store outcome for future retrieval

**Models**:
- **Momentum RAT**: Follows trends with memory adjustment
- **Mean Reversion RAT**: Contrarian with pattern matching

**Memory Structure**:
```sql
CREATE TABLE market_memory (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP,
    symbol VARCHAR(20),
    features JSONB,
    embedding vector(128),
    signal FLOAT,
    outcome FLOAT
);

CREATE INDEX ON market_memory
USING ivfflat (embedding vector_cosine_ops);
```

---

## Execution Module

**Purpose**: Execute trades with latency-aware position sizing

**Key Classes**:
- `ExecutionEngine`: Main trading loop
- `LatencyPenaltyCalculator`: Compute latency penalties
- `ExecutionMetrics`: Track performance

**Latency Penalty Formula**:
```python
penalty = exp(-scale * (compute_time - threshold))
adjusted_signal = raw_signal * penalty
```

**Process**:
1. Receive market data (async queue)
2. Compute signal with timing
3. Apply latency penalty if slow
4. Calculate position size
5. Execute trade if signal strong enough
6. Track metrics

**Async Design**: Non-blocking I/O, concurrent signal generation, queue-based communication, graceful shutdown.

---

## A/B Testing Framework

**Purpose**: Statistically validate new formulas before production deployment

**Key Classes**:
- `FormulaABTest`: Manages individual A/B test with 50/50 traffic split
- `ABTestOrchestrator`: Coordinates multiple concurrent tests
- `StatisticalAnalyzer`: Computes significance (t-test, p-values)

**Process**:
1. GitHub Actions detects new formula in discovery bucket
2. Validates formula safety (no banned functions)
3. Copies to staging bucket
4. Creates A/B test record in PostgreSQL
5. Personal computer routes 50% traffic to control, 50% to test
6. Records outcomes for both groups
7. After 14 days, runs statistical analysis
8. If test wins (p < 0.05), promotes to production bucket
9. Sends Slack notification with results

**Statistical Analysis**:
```python
from scipy import stats

def evaluate_ab_test(test_id: str) -> dict:
    control_outcomes = get_outcomes(test_id, 'control')
    test_outcomes = get_outcomes(test_id, 'test')
    control_sharpe = compute_sharpe(control_outcomes)
    test_sharpe = compute_sharpe(test_outcomes)
    t_stat, p_value = stats.ttest_ind(control_outcomes, test_outcomes)
    return {
        'winner': 'test' if test_sharpe > control_sharpe and p_value < 0.05 else 'control',
        'control_sharpe': control_sharpe,
        'test_sharpe': test_sharpe,
        'p_value': p_value,
        'recommendation': 'promote' if test_sharpe > control_sharpe and p_value < 0.05 else 'reject'
    }
```

---

## Circuit Breakers

**Purpose**: Automatically pause underperforming formulas to limit losses

**Logic**:
```python
class FormulaCircuitBreaker:
    def __init__(self, formula_id: str, failure_threshold: float = 0.3):
        self.formula_id = formula_id
        self.failure_threshold = failure_threshold
        self.recent_outcomes = deque(maxlen=100)
        self.state = 'closed'  # closed, open, half-open
        self.opened_at = None
        self.recovery_wait_seconds = 3600

    def record_outcome(self, outcome: float):
        self.recent_outcomes.append(outcome)
        if len(self.recent_outcomes) >= 100:
            win_rate = sum(1 for o in self.recent_outcomes if o > 0) / 100
            if win_rate < self.failure_threshold and self.state == 'closed':
                self.open_circuit()
            elif self.state == 'half-open' and win_rate < self.failure_threshold:
                self.open_circuit()
            elif self.state == 'half-open' and win_rate >= self.failure_threshold:
                self.close_circuit()

    def can_execute(self) -> bool:
        if self.state == 'closed':
            return True
        elif self.state == 'open':
            if datetime.now() - self.opened_at > timedelta(seconds=self.recovery_wait_seconds):
                self.state = 'half-open'
                return True
            return False
        elif self.state == 'half-open':
            return True
```

**Integration** in `async_engine.py`:
```python
async def execute_trade(symbol, features):
    for formula in ensemble.formulas:
        if not circuit_breaker.can_execute(formula.id):
            continue
        signal = formula.predict(features)
```

---

## Meta-Learner with Auto-Weighting

**Purpose**: Adaptively weight formulas based on rolling performance

**Key Classes**:
- `GatingNetwork`: Neural network for weight computation
- `AutoRebalancer`: Daily weight adjustment based on Sharpe ratios
- `MetaLearner`: Performance tracking and learning

**Weighting Strategy**:
```python
def compute_formula_weights(formulas: List[Formula]) -> Dict[str, float]:
    sharpes = {}
    for formula in formulas:
        outcomes = get_recent_outcomes(formula.id, days=30)
        sharpes[formula.id] = compute_sharpe(outcomes)

    total_sharpe = sum(max(s, 0) for s in sharpes.values())
    weights = {fid: max(s, 0) / total_sharpe for fid, s in sharpes.items()}

    for fid in weights:
        weights[fid] = min(weights[fid], 0.20)  # Max 20% per formula
        weights[fid] = max(weights[fid], 0.01)  # Min 1% or demote

    return weights
```

**Neural Architecture**:
```
Market Features → [Dense 64] → [ReLU] → [Dropout] →
                  [Dense 64] → [ReLU] → [Dropout] →
                  [Dense N] → [Softmax] → Model Weights
```

**Fallback**: Simple Sharpe-ratio-based weighting if neural gating disabled.

---

## Feature Architecture (Phase 2+)

This section documents the scalable three-layer feature architecture adopted in Phase 2. See [Decision 41](DECISIONS.md) for full rationale.

### Three-Layer Data Pipeline

```
RAW LAYER (Athena/Iceberg, append-only, normalized)
  Tables: market_data_raw, sentiment_raw, fundamentals_raw, alt_data_raw
  - Universal transforms applied automatically (all windows x all numeric columns)
  - Controlled by config/features.yaml (global_transforms, exclude_patterns)
  - 1,000+ columns over time -- storage is cheap
            |
            v  [transform_engine.py]
ENCODER LAYER (VAE or Transformer, trained daily/weekly)
  Table: feature_vectors (fixed schema)
  - Input: 1,000+ raw feature columns
  - Output: latent_1..latent_128 (compressed representation)
  - Plus: top 30-50 attention-selected raw columns
  - Encoder weights stored in S3, refreshed daily/weekly
            |
            v  [discovery_runner.py]
DISCOVERY LAYER (model-agnostic)
  Runners: PySR (symbolic), LightGBM, Attention NN, Future models
  - All runners consume feature_vectors table (same input)
  - All runners produce candidate models with identical metadata schema
  - No model type is privileged -- competition on performance only
            |
            v  [model_evaluator.py]
UNIFIED EVALUATION
  Metrics: Sharpe ratio, max drawdown, win rate, sample size
  - Model type is metadata, not a ranking factor
  - Output: ranked candidate models for A/B testing
```

### Key Design Principles

1. **Interpretability is not a constraint** — models are evaluated by performance metrics.
2. **Universal transforms** — `config/features.yaml` defines windows and transforms applied to ALL numeric columns automatically.
3. **Encoder absorbs feature growth** — adding 100 new raw features has zero marginal discovery cost.
4. **Model-agnostic discovery** — PySR, LightGBM, neural networks all compete on the same evaluation metrics.
5. **Automated pruning** — weekly Lambda removes features with >95% correlation or 8+ weeks of zero usage.

### Table Glossary

| Table | Written by | Purpose |
|-------|-----------|---------|
| `market_data_raw` | `writer.py` | OHLCV + fundamentals + sentiment (existing pipeline output) |
| `feature_vectors_raw` | `transform_engine.py` | 1,000+ numeric columns (all windows x all transforms) |
| `feature_vectors` | `encoder.py` inference step | `latent_1..128` + `selected_features map<string,double>` |

### Infrastructure Components

| Component | File | Rec |
|-----------|------|-----|
| Transform config | `config/features.yaml` | rec-201 |
| Transform engine | `src/data/transform_engine.py` | rec-202 |
| VAE encoder | `src/models/encoder.py` | rec-203 |
| Attention layer | `src/models/attention.py` | rec-204 |
| Feature vectors table | `terraform/iceberg_tables.tf` | rec-205 |
| Discovery runners | `src/lab/discovery_runner.py` | rec-206 |
| Model evaluator | `src/lab/model_evaluator.py` | rec-207 |
| Feature pruning | `src/data/handlers/pruning_handler.py` | rec-208 |

---

## Sync Service

**Purpose**: Transfer research results to production cache

**Process**:
1. Query Athena for recent backtest results
2. Filter by minimum Sharpe ratio
3. Compute embeddings for formulas
4. Upsert to PostgreSQL with pgvector
5. Run hourly via cron/scheduler

**Benefits**: Fast retrieval of proven formulas, no Athena query costs in production, vector similarity for formula search, automatic updates.

---

## Data Flow Examples

### Research Workflow
```
1. Historical Data → S3 → Athena Query
2. Athena Results → PySR Factory
3. PySR → Discovered Formulas + Metrics
4. Results → Iceberg Tables
5. Sync Service → pgvector Cache
```

### Live Trading Workflow
```
1. Market Data Stream → Trading Engine
2. Current Features → RAT Ensemble
3. RAT Ensemble → pgvector (similarity search)
4. Similar Patterns → Context for Prediction
5. Multiple Models → Meta-Learner
6. Meta-Learner → Weighted Signal
7. Signal → Latency Penalty → Position Size
8. Trade Executed → Store Outcome
```

---

## Deployment Options

### Local Development
```bash
docker-compose up -d
python -m src.main live
```

### Production
- **Compute**: ECS/EKS for trading system
- **Database**: RDS PostgreSQL with pgvector
- **Storage**: S3 with lifecycle policies
- **Queries**: Athena on-demand
- **Monitoring**: CloudWatch metrics
- **CI/CD**: GitHub Actions

---

## Performance Characteristics

### Latency
- Vector similarity search: < 10ms
- Signal computation: 10-50ms
- Latency penalty threshold: 100ms
- Target loop time: 100ms per symbol

### Scalability
- pgvector: Millions of vectors
- Athena: Petabytes of data
- Concurrent symbols: 100+
- Memory usage: ~2GB base

### Costs
- Athena: $5 per TB scanned
- S3: $0.023 per GB/month
- RDS: $0.09-0.27 per hour
- Compute: $0.04-0.10 per hour

---

## Authentication & Credentials Management

### AWS SSO (Single Sign-On)

This system uses a static-key assume-role chain for credential management. A near-powerless `agent_static` IAM user key assumes the `PlatformDev` role, which auto-refreshes without interactive login.

**Verify**:
```bash
aws sts get-caller-identity --profile agent_platform
# Should show an assumed-role ARN ending in .../PlatformDev/...
```

**Credential Discovery** (automatic):
1. boto3 uses `agent_platform` profile (assumes `PlatformDev` from `agent_static` key)
2. Uses IAM instance role when running on AWS compute (Lambda, OIDC CI runner)

**Profile chain** (`~/.aws/config`):
```
[profile agent_static]    # near-powerless IAM user key (long-lived)
[profile agent_platform]  # assumes PlatformDev; auto-refreshes; 10h session
[profile agent_platform_admin]  # assumes PlatformAdmin for Terraform
```

See `bin/setup-cloud-env.sh` for the canonical CC-web/Linux setup.

---

## Security Considerations

1. **Credentials**: Use `agent_platform` profile (static-key assume-role chain); never commit the `agent_static` key or any IAM secret to the repository
2. **IAM Roles**: Principle of least privilege — only required permissions per environment
3. **Encryption**: S3 at rest (AES-256 / SSE-S3), TLS in transit, pgvector data encrypted
4. **Formula Evaluation**: sympy AST parsing — never `eval()` or `exec()` on formula strings
5. **Input Validation**: Sanitize all user input; use parameterized queries with psycopg2
6. **Secrets Management**: Environment variables for credentials, never committed to Git
7. **Docker**: Run containers as non-root user, minimal base images

---

## Error Handling Patterns

All production code follows a consistent error handling pattern:

1. **Subsystem-Specific Exception Types**: Catch exceptions specific to each subsystem:
   - **AWS Operations**: `botocore.exceptions.ClientError`, `awswrangler.exceptions.ServiceApiError`
   - **Network I/O**: `ConnectionError`, `TimeoutError`, `requests.RequestException`
   - **Data Validation**: `ValueError`, `TypeError`, `sympy.SympifyError`
   - **Asyncio**: `asyncio.CancelledError` (must re-raise before other handlers)

2. **Logging for Debugging**: Log warnings/errors with context to aid investigation.
   - Use `logger = logging.getLogger(__name__)` at module level (once at module load, not per-function)
   - Log hierarchy: DEBUG (retry attempts), WARNING (transient failures), ERROR (exhausted retries), CRITICAL (circuit breaker stops)

3. **Graceful Fallback**: Provide a sensible default or skip the operation rather than crashing.

4. **Optional Dependency Import Pattern**:
   ```python
   try:
       import awswrangler as wr
       from awswrangler.exceptions import ServiceApiError as _WranglerServiceApiError
   except ImportError:
       wr = None
       class _WranglerServiceApiError(Exception):
           pass
   ```

---

## Resilience Patterns

### Circuit Breaker (Production Loops)

For long-running services (trading loop, formula sync, A/B test runner), use a consecutive-failure circuit breaker:

```python
consecutive_failures = 0
while True:
    try:
        # perform work
        consecutive_failures = 0
    except SpecificException as e:
        logger.error("Operation failed: %s", e)
        consecutive_failures += 1
        if consecutive_failures >= 5:
            logger.critical("Circuit breaker: stopping after %d consecutive failures", consecutive_failures)
            break
        time.sleep(backoff)
```

Applied to: `src/execution/async_engine.py:trading_loop()` with threshold of 5.

### Retry with Exponential Backoff (Network Operations)

For flaky network calls (external API, yfinance), use bounded exponential backoff:

```python
for attempt in range(3):
    try:
        return requests.get(url, timeout=5).json()
    except (ConnectionError, TimeoutError, ValueError) as e:
        if attempt < 2:
            time.sleep(1)
        else:
            logger.error("Failed to fetch %s after 3 retries: %s", url, e)
            return None
```

Applied to: `src/data/feature_engine.py:_fetch_fear_greed_index()`.

### Process-Local Caching with Monotonic Time

```python
_cache: dict = {}
_CACHE_TTL = 300  # seconds

if key in _cache:
    cached_value, cached_time = _cache[key]
    if time.monotonic() - cached_time < _CACHE_TTL:
        return cached_value
```

`time.monotonic()` is immune to system clock adjustments (NTP, daylight saving). Suitable for low-frequency, slow-change data (Fear & Greed Index with 5-min TTL).

---

## Configuration Management

The `Config` class in `src/common/config.py` uses a **two-phase loading and validation strategy** optimized for multi-environment deployment:

### Phase 1: Lazy Loading (Import-Time)

During import, `Config.__init__()` runs:
- Always succeeds: Loads YAML config if file exists; logs warning and returns empty dict if missing.
- No exceptions raised: Allows config module to be imported in any environment (CI, Lambda, containers).
- Defers errors: Validation errors are not raised until `validate()` is explicitly called.

### Phase 2: Explicit Validation (Setup-Time)

```python
try:
    config = Config(validate=True)
except FileNotFoundError:
    logger.error("Config file missing: %s", config.config_path)
    sys.exit(1)
```

**Environment-Specific Requirements**:
- **company**: Requires AWS Glue database, Athena workgroup, S3 data lake bucket
- **personal**: Requires PostgreSQL host and database
- **all**: Require AWS region

| Environment | Import Result | Validation Call | Outcome |
|-----------|-------------|------------------|---------|
| **Local dev** | Succeeds, loads values | Explicit via setup.py | Strict validation |
| **CI/pytest** | Succeeds, warning logged | Skipped | Tests run with empty config (fixtures provide values) |
| **Lambda** | Succeeds, warning logged | Skipped | boto3 uses IAM credentials |
| **Docker** | Depends on mount timing | Explicit via entrypoint | Validate after volume mount |

---

## Monitoring & Observability

### CloudWatch Dashboards (Company AWS Account)

**Formula Performance Dashboard**:
- Per-formula Sharpe ratio (30-day rolling)
- Win rate trends
- Circuit breaker status
- A/B test progress
- Cost metrics (SageMaker, S3, Athena)

**Cost Dashboard**:
- Daily/monthly spend by service
- S3 storage growth
- Athena query costs
- Budget alerts (80% threshold)

### Grafana (Personal Computer)

Local visualization connected to PostgreSQL, showing real-time trading activity, formula allocation, circuit breaker timelines, and outcome distribution histograms.

### Alerting

**Slack Alerts**: Circuit breaker opens/closes, A/B test completes, formula promoted to production, budget threshold exceeded (80%), personal computer offline > 1 hour.

**Expected Monthly Costs**:
- SageMaker (spot instances): $50-100
- S3 Storage: $20-30
- Athena Queries: $30-50
- Glue Catalog: $5-10
- **Total: ~$105-190/month**

---

## Future Enhancements

> These items are tracked as specific phases in [ROADMAP.md](./ROADMAP.md). See the roadmap for timelines and priorities.

1. **Risk Management** (Phase 4): Position limits, circuit breakers, kill switches
2. **A/B Testing** (Phase 5): Model comparison framework with statistical validation
3. **Monitoring** (Phase 6): CloudWatch dashboards, Grafana local visualisation
4. **Streaming**: Real-time data ingestion with Kinesis. Note: streaming integration requires inference-only mode with cached encoder weights, or mini-batch retraining triggered by data drift detection (see Decision 41). Weekly encoder retraining is not compatible with real-time streaming without these design changes.
5. **ML Ops**: Model versioning with MLflow (not yet planned)
6. **Explainability**: SHAP values for predictions (not yet planned)
7. **Strategy C Hybrid**: Document Strategy C upgrade path combining formulas as both feature engineers and RAT models

---

## Related Documents

- **[ARCHITECTURE-WORKFLOW.md](./ARCHITECTURE-WORKFLOW.md)** — Development workflow architecture: CI/CD strategy, telemetry star schema, executor package, LLM provider configuration, ops data pipeline. Start here for agent and tooling questions.
- **[INTENT-telemetry-system.md](./INTENT-telemetry-system.md)** — Full telemetry schema specification (authoritative, 7-table star schema column definitions).
- **[INTENT-recommendation-executor.md](./INTENT-recommendation-executor.md)** — Executor lifecycle intent document (authoritative spec for autonomous executor behaviour).
- **[ROADMAP.md](./ROADMAP.md)** — Phase plan and feature priorities.
- **[DECISIONS.md](./DECISIONS.md)** — Key architectural decisions with rationale.
