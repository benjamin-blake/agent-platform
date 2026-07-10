# Implementation Roadmap

> **SUPERSEDED.** This document has been superseded by
> [`docs/ROADMAP-PRODUCT.yaml`](./ROADMAP-PRODUCT.yaml), a machine-parseable
> agent-first roadmap organised around the four-layer trading model
> (Alpha / Portfolio Construction / Execution / Operations-Telemetry)
> per the PIVOT TRANSCRIPT architectural reset. This legacy markdown
> is retained for one transition cycle as a recovery artefact and will
> be removed in a follow-up commit per Section 10 gate #4 of the audit.
> This conversion was driven by the product-roadmap-YAML audit prompt
> ([`docs/audit-prompts/AUDIT-PROMPT-product-roadmap-yaml.md`](./audit-prompts/AUDIT-PROMPT-product-roadmap-yaml.md)).
> Its originally-planned conversion-report and platform-gaps YAML deliverables were never committed
> under those names; historical roadmap-audit outputs are archived under [`audits/legacy/`](../audits/legacy/).

---

This document outlines the 6-phase development plan to transform the system from single-environment to production-ready dual-environment architecture with formula lifecycle management.

---

## Current State (As of March 2026)

**Working:**
- ✅ Basic RAT ensemble with PostgreSQL pgvector
- ✅ Async execution engine with latency penalties
- ✅ Meta-learner gating network
- ✅ Terraform infrastructure for AWS Lakehouse
- ✅ Lab mode with PySR formula discovery (local)
- ✅ Docker containerization
- ✅ Market data pipeline (Step Functions: Fetch → Features → Write → Maintenance → Discovery)
- ✅ FTSE 100 daily ingestion via yfinance (87 symbols verified)
- ✅ Feature engine (technicals, sentiment, fundamentals — ~18 indicators)
- ✅ awswrangler MERGE upsert writer (replaced PyIceberg)
- ✅ Copy-on-write (COW) Iceberg commits via Athena engine v3
- ✅ Table maintenance (OPTIMIZE BIN_PACK + VACUUM 7-day retention)
- ✅ EventBridge daily schedule (6pm UTC weekdays)
- ✅ Safe formula evaluation (sympy replaces eval)
- ✅ Formula discovery wired to real Iceberg market data
- ✅ AWSSDKPandas managed Lambda layer (Python 3.12)
- ✅ End-to-end pipeline tested and verified (87 rows, 87 symbols, 2026-03-20)

**Limitations:**
- Features stored in `map<string,double>` — slow for formula discovery at scale
- No pre-calculated deltas (momentum, volatility, z-scores)
- Only 1 day of data — needs backfill for meaningful formula discovery
- ~~Single environment (not split between company/personal)~~ → Planned: Phase Infra-Env
- No formula versioning or lifecycle management
- No A/B testing framework
- Manual formula deployment
- No circuit breakers or automated rollback
- Limited monitoring (basic CloudWatch log groups, no dashboards)
- No cost controls beyond budgets

---

## Phase 1: Core Infrastructure (2 weeks) ✅ COMPLETE

**Goal:** Establish dual-environment architecture with S3 multi-bucket strategy and lineage tracking

### Deliverables
- [x] Split S3 into 3 buckets: `formulas-discovery`, `formulas-staging`, `formulas-production`
- [x] Add S3 lifecycle policies (90 days → Glacier, deprecated deleted after 2 years)
- [x] Create Iceberg table for `formula_lineage` in S3
- [x] Split configs: `config.company.yaml` and `config.personal.yaml`
- [x] Update `src/main.py` with `--environment` flag
- [x] Add `config/README.md` documenting which config for which environment
- [x] Market data pipeline: `src/data/` module with provider → features → Iceberg flow
- [x] Step Functions state machine for pipeline orchestration (5 steps)
- [x] EventBridge daily schedule (6pm UTC weekdays)
- [x] Evolved `market_data` Iceberg table (OHLCV, features map, `source` column, `trade_date` partition)
- [x] awswrangler MERGE upsert writer (replaces PyIceberg)
- [x] Table maintenance: OPTIMIZE (BIN_PACK) + VACUUM (7-day retention)
- [x] AWSSDKPandas managed Lambda layer (Python 3.12)
- [x] End-to-end pipeline tested (87 symbols, verified via Athena query)

### Terraform Changes
```hcl
# terraform/main.tf - 4 S3 buckets (data-lake, discovery, staging, production)
# terraform/iceberg_tables.tf - Iceberg tables (market_data, formula_lineage, etc.)
# terraform/data_pipeline.tf - Step Functions, 5 Lambdas, IAM, EventBridge, CloudWatch
# terraform/outputs.tf - Export bucket names, layer ARNs, SFN URL
```

### Acceptance Criteria ✅
- Company VM can deploy all infrastructure with single `terraform apply`
- Personal computer can read from production bucket (but not write)
- Lineage table queryable via Athena
- `python -m src.main --environment=company lab` works on company VM
- `python -m src.main --environment=personal live` works on personal computer
- Pipeline runs end-to-end: Fetch → Features → Write → Maintenance → Discovery
- Data verified in Iceberg table (87 rows for FTSE 100 symbols)

**Completed:** March 2026

---

## Phase Platform: Automation Platform (Parallel Track)

**Goal:** Build the decision-making, observability, and autonomy infrastructure that accelerates all product phases.

**Rationale:** The automation platform is not a product feature — it is the force multiplier that makes product phases cheaper, faster, and more reliable to implement. By running it as a parallel track, waves of infrastructure improvement are continuously available without blocking product development. Product phases gate on specific waves, not on full Phase Platform completion.

No fixed timeline applies to Phase Platform waves — they are ongoing infrastructure investment that runs in parallel with product development.

**Current provider state (April 2026):** Executor uses Gemini CLI locally (Decision 53). Lambda scheduled agents use Copilot SDK with `claude-haiku-4.5` / `claude-sonnet-4.6` (Decision 54 -- reverted from Bedrock). Bedrock dormant.

### Wave 1: Priority Queue Pipeline

**Goal:** Give the system a decision-making organ so work is prioritised by impact, not filing order.

**Deliverables:**
- S3-backed priority queue replacing FIFO execution order
- `rec-curator` Lambda pipeline: clusters open recs, surfaces batches by impact/risk/effort
- Executor preflight display shows prioritised queue context
- Curator triage of 126+ non-automatable recs to reduce manual supervision burden

**References:** `docs/plans/PLAN-infra-curator-pipeline.md`, recs 455-460

**Status:** Plan complete, atomic recs ready for execution

**Dependency relationship:** Wave 1 is a soft dependency for Phase 2 (Backfill). Phase 2 is a deterministic data-loading task that does not require priority queue orchestration — it can proceed independently if Wave 1 is delayed. Wave 1 is recommended before Phase 2 because the curator will help prioritise which backfill recs to execute first.

---

### Wave 2: Telemetry System — Schema/Instrumentation Complete (Trust Gate Pending)

**Goal:** Replace fragmented JSONL telemetry with a structured 7-table star schema in Iceberg, queryable via Athena.

**Authoritative spec:** `docs/INTENT-telemetry-system.md`

**Completed phases:**
- Phase A: Foundation — OpsWriter extended, 7 telemetry table schemas, Terraform Iceberg tables, Athena views
- Phase B: Executor instrumentation — session/phase/step/model-call/process-event telemetry
- Phase C: Scheduled agent instrumentation — agent invocation telemetry in Lambda
- Phase D: Manual workflow instrumentation — `/plan` and `/implement` sessions emit to same tables

**Remaining (Phase E-F, lower priority):**
- Phase E: Cloud analysis agent (statistical anomaly detection on telemetry data)
- Phase F: Legacy cleanup (remove deprecated JSONL files and scripts)

**Gate status:** Schema and instrumentation work for Phases A-D is complete, but operational telemetry trust is **not** satisfied until `docs/INTENT-verification-system.md` causal-chain verifiers prove that records flow from PRODUCE -> TRANSPORT -> PERSIST -> QUERY -> ASSERT. Treat telemetry as structurally available but not yet safe as an autonomous decision input.

---

### Wave 3: Executor Decomposition Pass 2 ✅ COMPLETE

**Goal:** Extract remaining monolithic functions from `execute_recommendation.py` into the `scripts/executor/` package.

**Completed deliverables:**
- `scripts/executor/telemetry.py` — session telemetry write logic
- `scripts/executor/acceptance_lint.py` — acceptance command validation
- `scripts/executor/batch.py` — compound/batch execution orchestration
- `scripts/executor/model_routing.py` — dynamic model selection logic
- `scripts/executor/formatters.py` — transcript and output formatting

**Status:** Complete. All 12 submodules extracted. `execute_recommendation.py` remains at 2821 SLOC (target was lower; further reduction tracked by rec-524).

**Gate status:** Wave 3 gate (well-factored modules for Wave 4) is satisfied.

---

### Wave 4: Autonomous Executor

**Goal:** Absorb `/develop-executor` supervisor responsibilities into deterministic scripts and RCA agents, enabling unattended batch execution.

**Architecture:** RCA-first (Decision 55). When the executor hits an unrecoverable failure, it stops cleanly, emits a structured `process_event` record, and invokes an RCA agent that diagnoses the root cause and files a recommendation to fix the gap permanently. Rescue agents (Decision 46) are replaced by this model. Deterministic pattern-matched recovery (git retry, ruff fix, CLI timeout) remains unchanged.

**Deliverables:**
- RCA agent contract: diagnoses failure root cause, files recommendation (replaces rescue agent dispatcher)
- Acceptance failure RCA agent: diagnoses why acceptance fails, files rec to fix prompt or scope rules
- Failure diagnosis agent: classifies failure causes (schema, code, test, infra) and routes to RCA
- Orchestrator loop with killswitch: caps consecutive failures, forces human escalation

**References:** `docs/plans/PLAN-infra-autonomous-executor.md`, recs 468-478, Decision 55

**Gate prerequisites:** Wave 2 schema/instrumentation, Wave 3 decomposed executor modules, and Wave Control telemetry/verification trust gates.

**Gate relationship:** Phase 3 (Formula Integration) involves complex multi-file changes across Python, Terraform, and SQL — reliable autonomous execution is required before this phase runs unattended.

---

### Wave 5: Repo Consolidation

**Goal:** Align repository structure with current workflow reality; eliminate orphaned scripts, agents, and documentation.

**Deliverables:**
- `copilot-instructions.md` modularisation (extract file router, gotchas, schema into separate files)
- Directory restructure aligning `scripts/`, `src/`, `config/` with current component ownership
- Workflow orphan cleanup (agents, prompts, workflows no longer referenced)
- Agent consolidation (merge functionally overlapping agents)

**References:** recs 023, 164, 031, 016

**Gate prerequisite:** Waves 1-4 stable. Consolidation during architectural flux risks breaking live workflows.

---

### Wave Control: Autonomous Improvement Control Plane

**Goal:** Close the recursive self-improvement loop by aligning telemetry, programmatic verification, executor RCA, interactive workflows, and recommendation governance into one coherent control plane.

**Authoritative intent:** `docs/INTENT-autonomous-improvement-control-plane.md`

**Rationale:** The system already has strong planning, recommendation logging, executor orchestration, scheduled agents, and telemetry schemas, but the loop is not fully closed until real execution evidence can automatically become verified, prioritised, and executable improvement work. This wave turns the automation platform from a collection of strong components into a measured feedback loop.

**Deliverables:**
- Telemetry causal-chain verifier proves PRODUCE -> TRANSPORT -> PERSIST -> QUERY -> ASSERT for operational records
- Verifier harness integrated into V3 planning, implementation, and executor postflight gates
- Executor failures produce structured failure packets and RCA recommendations
- `/develop-executor` reduced to RCA-only supervision with no workaround or repair authority
- `.agents` becomes canonical for interactive workflows; legacy VS Code prompts become compatibility-only artefacts
- Step validation and retrospectives move to telemetry, verifier results, and state-machine events instead of LLM subagents
- Recommendation and decision writes in workflows use `scripts/ops_data_portal.py`, never direct JSONL edits
- Priority queue preserves parent/child recommendation ordering and dependency context
- Workflow and skill contract validation is added to `scripts/validate.py`

**Dependencies:**
- `docs/INTENT-verification-system.md` Waves 1-3 (verifier foundation, first verifiers, causal-chain integration)
- Working telemetry pipeline and OpsWriter outbox drain
- Recommendation portal write path and ID authority

**Gate relationship:** This is cross-cutting control-plane work, not a later optional wave. It is required before expanding Wave 4 beyond supervised execution and before scaling unattended executor batches. It makes Waves 1-4 compound safely by adding telemetry trust, verification, RCA, and governance gates.

---

## Phase 2: Schema Flattening, Deltas & Backfill (2-3 weeks)

**Goal:** Flatten the market data schema for formula discovery performance, add pre-calculated deltas, and backfill historical data

### Rationale

The current `features map<string,double>` column is a bottleneck for formula discovery:
- PySR tests millions of formula combinations (e.g., `(feat_a / delta_b) * log(feat_c)`)
- Accessing a Map index for every operation is significantly slower than native column access
- Athena can predicate-push on native columns but not on map values
- Pre-calculated deltas eliminate N×M re-computation (N rows × M formula candidates)

### Deliverables

#### 1. Schema Flattening ✅ Complete
- [x] Promote ~18 stable features from `features` map to native Iceberg columns:
  - **Technical**: `tech_rsi_14`, `tech_macd`, `tech_macd_signal`, `tech_macd_histogram`,
    `tech_bb_width`, `tech_atr_14`, `tech_sma_20`, `tech_sma_50`, `tech_sma_200`,
    `tech_ema_12`, `tech_ema_26`, `tech_volume_ratio`, `tech_momentum_5d`,
    `tech_momentum_10d`, `tech_momentum_20d`, `tech_volatility_20d`
  - **Sentiment**: `sentiment_fear_greed`
  - **Fundamentals**: `fundamental_pe`, `fundamental_market_cap`, `fundamental_div_yield`
- [x] Keep `features map<string,double>` as a **landing zone** for experimental data sources
  (e.g., new sentiment feeds, Reddit scores, alternative data) — once a source proves
  valuable, it gets promoted to a dedicated column
- [x] Update `src/data/feature_engine.py` to write features as top-level columns
- [x] Update `src/data/writer.py` to map flattened columns to Iceberg schema
- [x] Use Iceberg schema evolution (`ALTER TABLE ADD COLUMNS`) — non-breaking change
- [x] Migrate existing data: backfill new columns from the `features` map (via `scripts/migrate_schema.py`)

#### 2. Pre-Calculated Delta Columns ✅ Complete
- [x] **Price Momentum**: `delta_price_1d`, `delta_price_5d`, `delta_price_20d`
  (percentage change in close price over 1, 5, and 20 days)
- [x] **Rolling Volatility**: `delta_volatility_10d`
  (rolling standard deviation of returns over 10 days, annualised)
- [x] **Z-Scores**: `zscore_close_30d`, `zscore_volume_30d`, `zscore_rsi_30d`
  (how many standard deviations from the 30-day mean — normalises cross-stock comparison,
  e.g., a £100 move in AstraZeneca is different from a £100 move in a penny stock)
- [x] **Sentiment Velocity**: `delta_sentiment_1d`
  (rate of change of sentiment score — "Neutral → Positive" is a stronger signal
  than static "Positive")
- [x] Update `src/data/feature_engine.py` to compute deltas alongside base features
- [x] Delta computation requires multi-day history — the feature engine reads
  prior rows from the Iceberg table via `feature_handler.py` before computing rolling windows

#### 3. Backfill — Validation Phase (1 month hourly)
- [ ] Create `src/data/handlers/backfill_handler.py` — local script (not Lambda, to avoid timeouts)
- [ ] Fetch 1 month of **hourly** data for all 87 FTSE 100 symbols
  - yfinance supports hourly intervals for the last 730 days
  - ~87 symbols × ~22 trading days × ~7 hours = ~13,398 rows
- [ ] Write raw hourly OHLCV to `market_data_raw_hourly` archive table (append-only, no features)
- [ ] Aggregate hourly bars into intraday feature columns on each daily row in `market_data`:
  - `intraday_range` (high - low across all hourly bars)
  - `intraday_vwap` (volume-weighted average price)
  - `morning_momentum` (first-hour return: open to 10:00 close)
  - `closing_hour_drift` (last-hour return: 15:00 to 16:00 close)
  - Write with `interval='1d'` — all intraday aggregates belong on the daily decision row
- [ ] Validate schema correctness: query via Athena, spot-check values
- [ ] Validate delta accuracy: compare computed deltas with manual calculations
- [ ] Confirm daily pipeline still works for daily ingestion alongside hourly data

#### 4. Backfill — Historical Phase (20 years daily)
- [ ] Fetch 20 years of **daily** data for FTSE 100 symbols
  - yfinance supports daily data going back to 2000+
  - ~87 symbols × ~5,000 trading days = ~435,000 rows
- [ ] Batch the backfill: process in monthly or yearly chunks to avoid Lambda timeouts
  - Consider running as a local script rather than Lambda for the initial bulk load
  - Or use Step Functions with a Map state to parallelise by symbol
- [ ] Compute features and deltas (rolling windows will populate from day 1)
- [ ] Write to Iceberg in batches with MERGE upsert
- [ ] Validate: row counts, date ranges, null percentages for delta columns
  (early rows will have null deltas due to insufficient lookback window)
- [ ] Run OPTIMIZE after bulk load to consolidate small files

### Schema (Target State)

```sql
-- Native columns (fast for formula discovery)
CREATE TABLE market_data (
    timestamp       TIMESTAMP,
    symbol          STRING,
    source          STRING,
    open            DOUBLE,
    high            DOUBLE,
    low             DOUBLE,
    close           DOUBLE,
    adj_close       DOUBLE,
    volume          BIGINT,

    -- Promoted technical indicators
    tech_rsi_14             DOUBLE,
    tech_macd               DOUBLE,
    tech_macd_signal        DOUBLE,
    tech_macd_histogram     DOUBLE,
    tech_bb_width           DOUBLE,
    tech_atr_14             DOUBLE,
    tech_sma_20             DOUBLE,
    tech_sma_50             DOUBLE,
    tech_sma_200            DOUBLE,
    tech_ema_12             DOUBLE,
    tech_ema_26             DOUBLE,
    tech_volume_ratio       DOUBLE,
    tech_momentum_5d        DOUBLE,
    tech_momentum_10d       DOUBLE,
    tech_momentum_20d       DOUBLE,
    tech_volatility_20d     DOUBLE,

    -- Promoted fundamentals
    fundamental_pe_ratio        DOUBLE,
    fundamental_market_cap      DOUBLE,
    fundamental_dividend_yield  DOUBLE,

    -- Promoted sentiment
    sentiment_fear_greed    DOUBLE,

    -- Pre-calculated deltas
    delta_price_1d          DOUBLE,
    delta_price_5d          DOUBLE,
    delta_price_20d         DOUBLE,
    delta_volatility_10d    DOUBLE,
    zscore_close_30d        DOUBLE,
    zscore_volume_30d       DOUBLE,
    zscore_rsi_30d          DOUBLE,
    delta_sentiment_1d      DOUBLE,

    -- Landing zone for experimental data sources
    features        MAP<STRING, DOUBLE>,

    ingested_at     TIMESTAMP,
    interval        STRING,   -- '1d' | '1h' | '15m' etc.
    trade_date      DATE
)
PARTITIONED BY (trade_date)

-- Raw hourly archive (append-only, no features; used by backfill_handler)
CREATE TABLE market_data_raw_hourly (
    timestamp       TIMESTAMP,
    symbol          STRING,
    source          STRING,
    open            DOUBLE,
    high            DOUBLE,
    low             DOUBLE,
    close           DOUBLE,
    adj_close       DOUBLE,
    volume          BIGINT,
    ingested_at     TIMESTAMP,
    trade_date      DATE
)
PARTITIONED BY (trade_date)
```

### Acceptance Criteria
- All ~18 features queryable as native columns in Athena
- `SELECT tech_rsi_14 FROM market_data WHERE symbol='AZN.L'` works without map access
- Delta columns populated for rows with sufficient lookback history
- Z-scores correctly normalise cross-stock values
- 1-month hourly backfill verified (schema + delta accuracy)
- 20-year daily backfill complete (~435k rows)
- Formula discovery query performance measurably improved vs map access
- Daily pipeline continues to work with the new schema

**Dependencies:** Phase 1 complete

**Phase Platform advisory:** Phase Platform Wave 1 (Priority Queue Pipeline) is recommended before starting backfill execution — the curator helps prioritise which backfill recs to execute first. This is a soft dependency only; Phase 2 can proceed independently if Wave 1 is delayed.

**Estimated Effort:** 20-25 hours

---

## Phase 3: Formula Integration (2 weeks)

**Goal:** Implement Strategy A (formulas as RAT models) with pgvector schema and dynamic loading

> **Decision 41 (Three-Layer Data Pipeline):** This decision introduces a three-layer architecture (RAW → Encoder → Discovery) that removes interpretability as a constraint and enables model-agnostic formula discovery. Implementation recs 201-209 cover the transform engine, VAE encoder, attention layer, and unified evaluation pipeline. The encoder and attention layer work lands in Phase 3 as a prerequisite for formula discovery at scale. See [DECISIONS.md](./DECISIONS.md#decision-41).

### Deliverables
- [ ] Create `src/live/formula_rat_model.py` - FormulaRATModel class
- [ ] Update `src/live/rat_ensemble.py` - Add dynamic formula loading
- [ ] Create `src/common/formula_loader.py` - S3 → PostgreSQL sync
- [ ] Add pgvector schema: `formula_models`, `formula_outcomes` tables
- [ ] Safe formula evaluation with sympy (no eval/exec)
- [ ] Add `docker/docker-compose.yml` service: `formula-sync` (runs every 5 min)
- [ ] Document Strategy C upgrade path in ARCHITECTURE.md

### Database Schema
```sql
CREATE TABLE formula_models (
    formula_id UUID PRIMARY KEY,
    formula_expression TEXT,
    embedding vector(128),
    source VARCHAR(50),
    version VARCHAR(20),
    created_at TIMESTAMP,
    state VARCHAR(20) -- discovered, testing, staging, production, deprecated
);

CREATE TABLE formula_outcomes (
    id SERIAL PRIMARY KEY,
    formula_id UUID REFERENCES formula_models,
    timestamp TIMESTAMP,
    market_features JSONB,
    predicted_signal FLOAT,
    actual_outcome FLOAT,
    context_similarity FLOAT
);
```

### Acceptance Criteria
- Personal computer pulls formulas from S3 every 5 minutes
- New formulas automatically added to RAT ensemble
- Each formula has isolated memory in pgvector
- Meta-learner weights formulas correctly
- Formulas can be safely evaluated (security test passes)
- Formula outcomes tracked in PostgreSQL

**Dependencies:** Phase 1 complete

**Phase Platform advisory:** Phase Platform Wave 4 (Autonomous Executor) is recommended before Phase 3 — formula integration requires complex multi-file changes across Python, Terraform, and SQL that benefit from reliable autonomous execution. This is a soft dependency; Phase 3 can start while Wave 4 is in progress if the supervisor is actively monitoring.

**Estimated Effort:** 15-20 hours

---

## Phase 4: A/B Testing Framework (3 weeks)

**Goal:** Automated formula promotion from staging → production based on statistical testing

### Deliverables
- [ ] Create `src/live/ab_testing.py` - FormulaABTest class with t-test
- [ ] Add `docker/docker-compose.yml` service: `ab-tester` (runs daily analysis)
- [ ] Create GitHub Actions workflow: `.github/workflows/formula-promotion.yml`
- [ ] Add PostgreSQL tables: `ab_tests`, `ab_test_results`
- [ ] Implement 50/50 traffic split router
- [ ] Auto-promotion logic (p < 0.05, min 100 trades)
- [ ] Slack notifications for test completion
- [ ] Manual override scripts: `promote_formula.py`, `stop_ab_test.py`

### GitHub Actions Workflow
```yaml
# Detects new formula in formulas-discovery
# Validates safety (AST parsing, no banned functions)
# Copies to formulas-staging
# Creates A/B test record
# Monitors for 14 days
# Promotes or archives based on results
```

### Acceptance Criteria
- New formula triggers A/B test automatically
- 50% traffic routed to control, 50% to test
- After 14 days, statistical analysis runs
- Winning formula promoted to production bucket
- Losing formula archived to deprecated
- Slack alert sent with test results
- Manual override scripts work correctly

**Dependencies:** Phase 3 complete

**Estimated Effort:** 20-25 hours

---

## Phase 5: Circuit Breakers (1 week)

**Goal:** Per-formula failure detection with automatic pause

### Deliverables
- [ ] Create `src/live/circuit_breaker.py` - FormulaCircuitBreaker class
- [ ] Integrate into `src/execution/async_engine.py` - Check before trade
- [ ] Add PostgreSQL table: `circuit_breaker_state`
- [ ] Slack alerts when breaker opens
- [ ] Auto-recovery: test formula after 1 hour, re-enable if passing
- [ ] Dashboard showing circuit breaker status

### Circuit Breaker Logic
```python
# Track last 100 outcomes per formula
# If win_rate < 30%, open circuit (stop using formula)
# Alert team via Slack
# After 1 hour, close breaker and try again (half-open state)
# If still failing, keep open and demote to staging
```

### Acceptance Criteria
- Formula with <30% win rate stops executing within 100 trades
- Slack alert sent immediately when breaker opens
- Circuit breaker state visible in dashboard
- Formula auto-recovers if performance improves
- Persistent failures demoted from production

**Dependencies:** Phase 3 complete (can run parallel with Phase 4)

**Estimated Effort:** 8-10 hours

---

## Phase 6: Monitoring & Observability (2 weeks)

**Goal:** Comprehensive monitoring across CloudWatch and Grafana

### Deliverables
- [ ] Create `terraform/monitoring.tf` - CloudWatch dashboards
- [ ] Create `src/common/metrics.py` - Emit metrics to CloudWatch
- [ ] Create `scripts/export_metrics_to_cloudwatch.py` - Hourly export from personal computer
- [ ] Add Grafana dashboard: `docker/grafana/formula-performance.json`
- [ ] CloudWatch alarms: Sharpe < 0.3, latency > 100ms, error rate > 1%
- [ ] Create `terraform/cost_monitoring.tf` - AWS Cost Explorer budgets
- [ ] Create `scripts/cost_report.py` - Weekly email with cost breakdown

### Metrics to Track
**Performance Metrics:**
- Per-formula Sharpe ratio (rolling 30 days)
- Win rate (rolling 1000 trades)
- Max drawdown
- Average signal strength

**Operational Metrics:**
- Compute time (p50, p95, p99)
- Error rate
- Circuit breaker status
- A/B test status

**Cost Metrics:**
- SageMaker job costs
- S3 storage costs
- Athena query costs
- EC2/Docker compute costs

### Acceptance Criteria
- CloudWatch dashboard shows all formula metrics
- Grafana dashboard on personal computer visualizes PostgreSQL data
- Metrics exported from personal computer to CloudWatch hourly
- Slack alerts trigger when thresholds breached
- Weekly cost report sent via email
- AWS Cost Explorer budgets alert at 80% of monthly threshold

**Dependencies:** Phase 3 complete

**Estimated Effort:** 15-18 hours

---

## Phase 7: Automated Weighting & Decay (2 weeks)

**Goal:** Meta-learner automatically adjusts formula weights based on performance

### Deliverables
- [ ] Update `src/meta_learner/gating_network.py` - Add Sharpe-based weighting
- [ ] Create `src/live/auto_rebalancer.py` - Daily rebalancing job
- [ ] Implement decay function: Reduce weight 10%/day if Sharpe < 0.3
- [ ] Add PostgreSQL table: `formula_weights` (historical tracking)
- [ ] Auto-demotion: Move to staging if weight decays to <1%
- [ ] Dashboard showing weight distribution over time
- [ ] Manual weight override capability

### Weighting Algorithm
```python
# Compute rolling 30-day Sharpe ratio per formula
# Normalize weights: weight_i = sharpe_i / sum(all_sharpes)
# Apply decay: if sharpe < 0.3, reduce weight by 10% daily
# Minimum weight: 1% (below that, auto-demote to staging)
# Maximum weight: 20% (prevent over-concentration)
# Rebalance daily at market close
```

### Acceptance Criteria
- Formula weights adjust automatically based on Sharpe ratio
- Underperforming formulas decay weight daily
- Formulas below 1% weight auto-demote to staging bucket
- Weight history tracked in PostgreSQL
- Dashboard visualizes weight changes over time
- Manual override works for emergency adjustments

**Dependencies:** Phase 3, Phase 4 complete (needs formula models + A/B testing)

**Estimated Effort:** 12-15 hours

---

## Critical Path

Phase Platform waves have no fixed timeline -- they are ongoing infrastructure investment that runs parallel to product development. Product phases gate on specific waves, not on Phase Platform completion.

`:` denotes a soft (advisory) dependency; `|` denotes a hard gate.

```
Phase 1 (COMPLETE)
  |
  +-- Phase Platform (parallel) ----------------------------------------+
  |   Wave 1 ---> Wave 2 ---> Wave 3 ---> Wave 4 ---> Wave 5            |
  |     :                                   |                            |
  |     v (soft: curator helps prioritise)  v (hard: autonomous exec)   |
  +-- Phase 2 (Backfill) -----------> Phase 3 (Formulas) ---------------+
                                           |
                                   Phase 4 + Phase 5 (parallel)
                                           |
                                   Phase 6 --> Phase 7
```

**Parallel Work Opportunities:**
- Phase 5 (Circuit Breakers) can run parallel with Phase 4 (A/B Testing)
- Phase 6 (Monitoring) can start infrastructure setup during Phase 4
- Phase 2 backfill (20-year daily) can run in background during Phase 3

---

## Risk Mitigation

**Risk: Schema migration breaks existing queries**
- Mitigation: Iceberg schema evolution is additive (ADD COLUMNS only) — existing queries unaffected
- New columns default to NULL for historical rows until backfilled
- Keep `features` map alongside native columns during transition

**Risk: Backfill overwhelms Lambda / Athena**
- Mitigation: Batch by month or symbol, run as local script for bulk load
- Iceberg MERGE upsert is idempotent — safe to retry partial batches
- Run OPTIMIZE after bulk load to consolidate small files

**Risk: yfinance rate limits during 20-year backfill**
- Mitigation: Add exponential backoff, batch by symbol with delays
- yfinance daily data is reliable for 20+ years; hourly only last 730 days
- Consider Alpha Vantage or Polygon for hourly data beyond 2 years

**Risk: Personal computer downtime breaks system**
- Mitigation: Phase 3 includes auto-pause for A/B tests (see DECISIONS.md #3)

---

## Phase Infra-Env: Multi-Environment CI/CD (Infrastructure Track)

**Goal:** Establish staging and production environments with GitHub-native promotion workflow

> **Note:** This is an infrastructure track that can run parallel to feature phases. It does not block Phase 2-7 development but should complete before production trading begins.

### Deliverables

#### 1. Terraform Environment Configuration
- [ ] Create `terraform/envs/sandbox.tfvars` (extract current hardcoded values)
- [ ] Create `terraform/envs/staging.tfvars` (staging AWS account)
- [ ] Create `terraform/envs/production.tfvars` (production AWS account)
- [ ] Parameterize `terraform/*.tf` to use variables instead of hardcoded values
- [ ] Test: `terraform plan -var-file=envs/sandbox.tfvars` produces no changes

#### 2. GitHub Environments Setup
- [ ] Create `sandbox` environment (Settings → Environments)
  - Secrets: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_ACCOUNT_ID` for sandbox account  # pragma: allowlist secret
  - No protection rules (auto-deploy on push)
- [ ] Create `staging` environment
  - Secrets: Credentials for staging AWS account
  - Protection: 24-hour wait timer (optional, for daily promotion)
- [ ] Create `production` environment
  - Secrets: Credentials for production AWS account
  - Protection: Required reviewer (human approval gate)

#### 3. GitHub Actions Workflows
- [ ] Update `.github/workflows/ci.yml` to deploy sandbox on push to main
- [ ] Create `.github/workflows/promote-staging.yml`
  - Trigger: `schedule` (daily 6am UTC) + `workflow_dispatch`
  - Gate: Last sandbox CI passed
  - Action: `terraform apply -var-file=envs/staging.tfvars`
  - Tag: `staging-YYYY-MM-DD`
- [ ] Create `.github/workflows/promote-production.yml`
  - Trigger: `workflow_dispatch` only
  - Gate: Required reviewer approval (via environment protection)
  - Action: `terraform apply -var-file=envs/production.tfvars`
  - Tag: `prod-YYYY-MM-DD`
- [ ] Create `.github/workflows/rollback.yml`
  - Trigger: `workflow_dispatch` with inputs: environment, git tag
  - Action: Checkout tag, apply Terraform for that SHA
  - Notify: Slack alert on rollback completion

#### 4. Drift Detection & Guardrails
- [ ] Create AWS Config rule: Detect resources not managed by Terraform
- [ ] Document SCP policy for blocking console resource creation (future: apply via Organizations)
- [ ] Create `scripts/detect_drift.py` — compare Terraform state to AWS reality
- [ ] Add drift check to weekly cron (informational, not blocking)

#### 5. Documentation
- [ ] Update `copilot_instructions.md` with environment strategy (sandbox-only profile for agents)
- [ ] Create `docs/ENVIRONMENTS.md` explaining promotion workflow
- [ ] Update `GETTING_STARTED.md` with environment-specific setup instructions

### Terraform Environment Variables (Example)

```hcl
# terraform/envs/sandbox.tfvars
aws_account_id     = "123456789012"
environment        = "sandbox"
bucket_prefix      = "ml-sandbox"
lambda_memory      = 512
enable_monitoring  = false

# terraform/envs/production.tfvars
aws_account_id     = "345678901234"
environment        = "production"
bucket_prefix      = "ml-prod"
lambda_memory      = 1024
enable_monitoring  = true
```

### Acceptance Criteria
- [ ] Push to main auto-deploys to sandbox (existing behavior, now explicit)
- [ ] Manual workflow trigger promotes sandbox → staging
- [ ] Manual workflow trigger (with approval) promotes staging → production
- [ ] Git tags created on each promotion
- [ ] Rollback workflow deploys previous tag successfully
- [ ] Agent prompts reference only `company-aws-profile` profile
- [ ] Drift detection script identifies orphaned resources

### Rollback Behavior for New Resources

When rolling back to a previous tag that doesn't include a resource created later:

| Scenario | Terraform Behavior | Resolution |
|----------|-------------------|------------|
| New S3 bucket in current, rollback to previous | Bucket remains (not in state) | Manual delete OR forward-fix with `removed {}` block |
| New Lambda in current, rollback to previous | Lambda remains orphaned | `terraform state rm` + `aws lambda delete-function` |
| Modified resource, rollback to previous | Resource reverts to previous config | Automatic (desired behavior) |

**Prevention:** AWS SCPs block console creation. All resources via Terraform. Drift detection alerts on orphans.

**Dependencies:** None (can start immediately)

**Estimated Effort:** 12-15 hours

---

## Phase Infra-Platform: Executor LLM Platform Migration (Infrastructure Track, Deferred)

**Goal:** Migrate the executor's LLM interface from raw Copilot CLI subprocess calls to the GitHub Copilot SDK with AWS Bedrock as the planning backend via BYOK, enabling structured output, prompt caching, and parallel planning.

> **Note:** This is a deferred infrastructure track with no target date. Implementation is triggered by conditions defined in Decision 40. It does not block any feature phase.

> **Status:** Waiting. Re-evaluate when GitHub Copilot SDK reaches v1.0/stable, executor retry rate exceeds 40% sustained, or executor throughput becomes the North Star bottleneck.

### Rationale

The current executor uses `copilot_wrapper.py` to invoke the Copilot CLI via subprocess. This is stable but has known friction: ~2-5s startup per call, ~30% plan parsing failure rate from prose output, no prompt caching, and sequential processing only. The Copilot SDK (currently Public Preview v0.2.2) will replace subprocess management with async JSON-RPC, and its BYOK feature will enable Bedrock's structured output and prompt caching through a single interface.

### Deliverables (Three Phases)

#### P1: SDK Adoption
- [ ] Replace `copilot_wrapper.py` subprocess calls with `CopilotClient` async context managers
- [ ] Migrate to persistent CLI server mode (eliminates ~2-5s startup per call)
- [ ] Replace `_PLAN_EXCLUDED_TOOLS` workaround with SDK session hooks (`on_pre_tool_use`)
- [ ] Replace `validate_response()` question detection with SDK event handling
- [ ] Update `copilot_call()` signature to async, propagate through executor
- [ ] Maintain feature flag: `EXECUTOR_PLATFORM=cli|sdk` (env var, default `cli`)

#### P2: Bedrock Planning Backend
- [ ] Configure BYOK with Anthropic provider type for planning-phase calls
- [ ] Define JSON schema for execution plans (replaces `parse_steps_from_plan` regex parsing)
- [ ] Implement prompt caching: system prompt + repo conventions as cached prefix (5min TTL)
- [ ] Migrate plan-critique-refine loop to multi-turn Bedrock conversation (cached context)
- [ ] Add structured critique verdict schema (replaces text-based verdict parsing)
- [ ] Maintain feature flag: `EXECUTOR_PLANNER=copilot|bedrock` (env var, default `copilot`)

#### P3: Unified Multi-Rec Planning
- [ ] Bedrock planner accepts rec clusters from rec-curator agent
- [ ] Unified plan output tags each step with source rec ID for per-rec status tracking
- [ ] File conflict detection: planner sequences steps that modify the same function
- [ ] Parallel planning via `asyncio` + SDK async sessions for independent clusters
- [ ] Partial failure isolation: steps from failed recs don't block steps from passing recs

### Acceptance Criteria
- [ ] SDK mode passes all existing executor tests with `EXECUTOR_PLATFORM=sdk`
- [ ] Bedrock planning produces valid JSON plans that pass schema validation
- [ ] Plan parsing failure rate drops below 5% (from ~30%) with structured output
- [ ] Prompt cache hit rate exceeds 60% for plan-critique-refine cycles
- [ ] No regression in executor success rate when switching from CLI to SDK mode
- [ ] Feature flags allow instant rollback to CLI mode

### Monitoring Trigger Conditions
- Copilot SDK version: check `pip index versions github-copilot-sdk` quarterly
- Executor retry rate: tracked in `logs/.session-telemetry.jsonl` (field: `friction_count`)
- Executor throughput: tracked in `logs/.session-telemetry.jsonl` (field: `steps_completed`)

### Future Considerations (Non-Blocking)

**Post-merge regression detection:** Once the executor is fully autonomous, add a twice-daily scheduled CI run on main that detects regressions introduced by merged PRs and auto-reverts if main goes red. Per-merge verification is not viable due to GitHub Actions minute caps; a scheduled sweep is more cost-effective.

**Parallel execution is not a near-term priority:** The executor runs on a VM that operates 24/7 unattended. Sequential processing of 178 open recs at ~20 min each is ~59 hours of wall time -- under 3 calendar days of continuous autonomous execution, not 9 working days of human-supervised time. Parallelism (worktrees, multiple branches) becomes relevant only if throughput becomes the North Star bottleneck.

**Knowledge accumulation:** Before each executor run, query telemetry tables for historical context on the target files (past failure rates, common failure modes, optimal model selection). Inject as structured context into the planning agent's prompt so the system learns from its own history rather than starting from a blank slate each time.

**North Star metrics:** Define 3-5 executor health metrics (first-attempt success rate, cost per merged rec, mean time to merge, exception event rate, self-improvement velocity) and track trends. The cloud analysis agent should report on these; the system is "improving" only when trends move in the right direction.

**Feedback loop testing:** Periodic (monthly) meta-test: introduce a known defect into a test branch, verify a scheduled agent detects it, a rec is filed, the executor fixes it, and telemetry records the full cycle. This is the fire drill for the autonomous system.

**Dependencies:** None (infrastructure track, parallel to feature phases)

**Estimated Effort:** P1: 10-15 hours, P2: 8-12 hours, P3: 8-10 hours

**Related:** Decision 40, rec-186 (acceptance pre-flight), rec-curator agent (cluster input for P3)

---

- Future: Consider AWS failover for production

**Risk: Formula evaluation security vulnerability**
- Mitigation: Phase 3 uses sympy AST parsing, never eval/exec
- Testing: Security test validates no banned functions

**Risk: Cost overruns from unbounded formula growth**
- Mitigation: Phase 3 caps at 50 active formulas (see DECISIONS.md #2)
- Phase 6 adds cost monitoring with alerts at 80% budget

**Risk: Meta-learner overfitting with too many formulas**
- Mitigation: Phase 7 auto-demotes low-weight formulas
- Monitoring: Track meta-learner loss and validation metrics

**Risk: A/B tests take too long, slow iteration**
- Mitigation: Phase 4 starts with 14-day tests, configurable (see DECISIONS.md #1)
- Future: Adaptive test duration based on trade frequency

---

## Post-Launch (Phase 8+)

**Future Enhancements:**
- Multi-asset formula generalization (cross-market, FX, commodities)
- Formula explainability (SHAP values)
- Real-time feature drift detection
- Cross-formula correlation analysis
- Strategy C implementation (formulas as feature engineers)
- External formula marketplace integration
- Regulatory compliance reporting (MiFID II, Dodd-Frank)
- Intraday streaming data via Kinesis or WebSockets
- Additional data providers (Alpha Vantage, Polygon, Bloomberg)
- Alternative data sources (Reddit sentiment, news NLP, satellite imagery)

These are tracked in `DECISIONS.md` as "Future Decisions (Not Yet Scoped)"
