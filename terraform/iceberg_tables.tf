# Iceberg Tables for Formula Lineage Tracking
# Append-only tables for audit trail and provenance

locals {
  glue_tables = {
    formula_lineage = {
      location = "s3://${aws_s3_bucket.formulas_discovery.bucket}/lineage/"
      columns = [
        {
          name    = "formula_id"
          type    = "string"
          comment = "Unique UUID for formula"
        },
        {
          name    = "version"
          type    = "int"
          comment = "Formula version number (starts at 1)"
        },
        {
          name    = "formula_expression"
          type    = "string"
          comment = "Symbolic expression (e.g., tanh(x0 * 0.5 + x1))"
        },
        {
          name    = "feature_names"
          type    = "array<string>"
          comment = "List of feature variable names (e.g., [momentum, volatility])"
        },
        {
          name    = "discovery_timestamp"
          type    = "timestamp"
          comment = "When formula was discovered by PySR"
        },
        {
          name    = "discovery_job_id"
          type    = "string"
          comment = "SageMaker job ID that produced formula"
        },
        {
          name    = "discovery_metrics"
          type    = "struct<sharpe_ratio:double,complexity:int,mse:double>"
          comment = "Metrics from PySR training"
        },
        {
          name    = "state"
          type    = "string"
          comment = "Current state: discovered|testing|staging|production|deprecated|circuit_broken"
        },
        {
          name    = "state_changed_at"
          type    = "timestamp"
          comment = "When state last changed"
        },
        {
          name    = "state_changed_by"
          type    = "string"
          comment = "Process that changed state (e.g., ab_tester, circuit_breaker)"
        },
        {
          name    = "ab_test_id"
          type    = "string"
          comment = "A/B test ID if in testing/staging"
        },
        {
          name    = "ab_test_metrics"
          type    = "struct<win_rate:double,sharpe_ratio:double,max_drawdown:double,sample_size:int>"
          comment = "A/B test results"
        },
        {
          name    = "production_metrics"
          type    = "struct<win_rate:double,sharpe_ratio:double,max_drawdown:double,total_trades:int>"
          comment = "Live trading performance"
        },
        {
          name    = "circuit_breaker_triggered"
          type    = "boolean"
          comment = "Whether circuit breaker activated"
        },
        {
          name    = "circuit_breaker_reason"
          type    = "string"
          comment = "Why circuit breaker triggered (e.g., win_rate < 30%)"
        },
        {
          name    = "s3_bucket"
          type    = "string"
          comment = "Current S3 bucket (discovery|staging|production)"
        },
        {
          name    = "s3_key"
          type    = "string"
          comment = "S3 object key (e.g., formulas/2024-01-15/formula_abc123.jsonl)"
        },
        {
          name    = "metadata"
          type    = "map<string,string>"
          comment = "Additional metadata (tags, notes, etc.)"
        }
      ]
    }
    trading_performance = {
      location = "s3://${aws_s3_bucket.formulas_discovery.bucket}/performance/"
      columns = [
        {
          name    = "trade_id"
          type    = "string"
          comment = "Unique trade identifier"
        },
        {
          name    = "formula_id"
          type    = "string"
          comment = "Formula that generated signal"
        },
        {
          name    = "formula_version"
          type    = "int"
          comment = "Formula version at trade time"
        },
        {
          name    = "timestamp"
          type    = "timestamp"
          comment = "Trade execution timestamp"
        },
        {
          name    = "symbol"
          type    = "string"
          comment = "Trading symbol"
        },
        {
          name    = "signal"
          type    = "double"
          comment = "Formula output signal [-1.0, 1.0]"
        },
        {
          name    = "position_size"
          type    = "double"
          comment = "Position size in USD"
        },
        {
          name    = "entry_price"
          type    = "double"
          comment = "Entry price"
        },
        {
          name    = "exit_price"
          type    = "double"
          comment = "Exit price"
        },
        {
          name    = "pnl"
          type    = "double"
          comment = "Profit/Loss in USD"
        },
        {
          name    = "holding_period"
          type    = "int"
          comment = "Holding period in seconds"
        },
        {
          name    = "features"
          type    = "map<string,double>"
          comment = "Input features at signal time"
        },
        {
          name    = "market_regime"
          type    = "string"
          comment = "Market regime (bull|bear|sideways)"
        },
        {
          name    = "ab_test_id"
          type    = "string"
          comment = "A/B test ID if applicable"
        },
        {
          name    = "environment"
          type    = "string"
          comment = "trading|paper|backtest"
        }
      ]
    }
    ab_test_results = {
      location = "s3://${aws_s3_bucket.formulas_discovery.bucket}/ab_tests/"
      columns = [
        {
          name    = "ab_test_id"
          type    = "string"
          comment = "Unique test identifier"
        },
        {
          name    = "formula_id"
          type    = "string"
          comment = "Formula being tested"
        },
        {
          name    = "start_date"
          type    = "timestamp"
          comment = "Test start date"
        },
        {
          name    = "end_date"
          type    = "timestamp"
          comment = "Test end date"
        },
        {
          name    = "duration_days"
          type    = "int"
          comment = "Test duration (7|14|30 days)"
        },
        {
          name    = "control_sharpe"
          type    = "double"
          comment = "Control group Sharpe ratio"
        },
        {
          name    = "treatment_sharpe"
          type    = "double"
          comment = "Treatment group Sharpe ratio"
        },
        {
          name    = "p_value"
          type    = "double"
          comment = "Statistical significance (p < 0.05)"
        },
        {
          name    = "sample_size"
          type    = "int"
          comment = "Number of trades"
        },
        {
          name    = "decision"
          type    = "string"
          comment = "promote|reject|extend"
        },
        {
          name    = "decision_reason"
          type    = "string"
          comment = "Why decision was made"
        },
        {
          name    = "promoted_to_production"
          type    = "boolean"
          comment = "Whether formula was promoted"
        }
      ]
    }
    market_data = {
      location = "s3://${aws_s3_bucket.data_lake.bucket}/iceberg/market_data/"
      columns = [
        {
          name    = "timestamp"
          type    = "timestamp"
          comment = "Market data timestamp"
        },
        {
          name    = "symbol"
          type    = "string"
          comment = "Trading symbol (e.g., HSBA.L, BP.L)"
        },
        {
          name    = "source"
          type    = "string"
          comment = "Data provider (e.g., yfinance, alpha_vantage, manual)"
        },
        {
          name    = "open"
          type    = "double"
          comment = "Opening price"
        },
        {
          name    = "high"
          type    = "double"
          comment = "High price"
        },
        {
          name    = "low"
          type    = "double"
          comment = "Low price"
        },
        {
          name    = "close"
          type    = "double"
          comment = "Closing price"
        },
        {
          name    = "adj_close"
          type    = "double"
          comment = "Adjusted closing price"
        },
        {
          name    = "volume"
          type    = "bigint"
          comment = "Trading volume"
        },
        # Promoted technical indicators (Phase 1.5 schema flattening)
        {
          name    = "tech_rsi_14"
          type    = "double"
          comment = "RSI (14-period)"
        },
        {
          name    = "tech_macd"
          type    = "double"
          comment = "MACD line (12/26 EMA)"
        },
        {
          name    = "tech_macd_signal"
          type    = "double"
          comment = "MACD signal line (9-period EMA of MACD)"
        },
        {
          name    = "tech_macd_histogram"
          type    = "double"
          comment = "MACD histogram (MACD - signal)"
        },
        {
          name    = "tech_bb_width"
          type    = "double"
          comment = "Bollinger Band width (2σ / SMA20)"
        },
        {
          name    = "tech_atr_14"
          type    = "double"
          comment = "Average True Range (14-period)"
        },
        {
          name    = "tech_sma_20"
          type    = "double"
          comment = "Simple Moving Average (20-day)"
        },
        {
          name    = "tech_sma_50"
          type    = "double"
          comment = "Simple Moving Average (50-day)"
        },
        {
          name    = "tech_sma_200"
          type    = "double"
          comment = "Simple Moving Average (200-day)"
        },
        {
          name    = "tech_ema_12"
          type    = "double"
          comment = "Exponential Moving Average (12-period)"
        },
        {
          name    = "tech_ema_26"
          type    = "double"
          comment = "Exponential Moving Average (26-period)"
        },
        {
          name    = "tech_volume_ratio"
          type    = "double"
          comment = "Volume relative to 20-day average"
        },
        {
          name    = "tech_momentum_5d"
          type    = "double"
          comment = "5-day price momentum (% change)"
        },
        {
          name    = "tech_momentum_10d"
          type    = "double"
          comment = "10-day price momentum (% change)"
        },
        {
          name    = "tech_momentum_20d"
          type    = "double"
          comment = "20-day price momentum (% change)"
        },
        {
          name    = "tech_volatility_20d"
          type    = "double"
          comment = "20-day historical volatility (annualised)"
        },
        # Promoted fundamentals
        {
          name    = "fundamental_pe"
          type    = "double"
          comment = "Trailing or forward P/E ratio"
        },
        {
          name    = "fundamental_market_cap"
          type    = "double"
          comment = "Market capitalisation"
        },
        {
          name    = "fundamental_div_yield"
          type    = "double"
          comment = "Dividend yield"
        },
        # Promoted sentiment
        {
          name    = "sentiment_fear_greed"
          type    = "double"
          comment = "CNN Fear & Greed Index (0-100)"
        },
        # Pre-calculated deltas (Phase 1.5)
        {
          name    = "delta_price_1d"
          type    = "double"
          comment = "1-day close price % change"
        },
        {
          name    = "delta_price_5d"
          type    = "double"
          comment = "5-day close price % change"
        },
        {
          name    = "delta_price_20d"
          type    = "double"
          comment = "20-day close price % change"
        },
        {
          name    = "delta_volatility_10d"
          type    = "double"
          comment = "10-day rolling volatility (annualised std of returns)"
        },
        {
          name    = "zscore_close_30d"
          type    = "double"
          comment = "30-day z-score of close price"
        },
        {
          name    = "zscore_volume_30d"
          type    = "double"
          comment = "30-day z-score of volume"
        },
        {
          name    = "zscore_rsi_30d"
          type    = "double"
          comment = "30-day z-score of RSI(14)"
        },
        {
          name    = "delta_sentiment_1d"
          type    = "double"
          comment = "1-day change in Fear & Greed Index (sentiment velocity)"
        },
        # Landing zone for experimental / not-yet-promoted features
        {
          name    = "features"
          type    = "map<string,double>"
          comment = "Experimental features not yet promoted to native columns"
        },
        {
          name    = "ingested_at"
          type    = "timestamp"
          comment = "Pipeline ingestion timestamp"
        },
        {
          name    = "interval"
          type    = "string"
          comment = "Data granularity: 1d (daily), 1h (hourly), 15m (15-minute), etc."
        }
      ]
      # Partitioned by trade_date (date) — Iceberg handles partition metadata automatically
      partition_columns = ["trade_date"]
    }
    backtest_results = {
      location = "s3://${aws_s3_bucket.data_lake.bucket}/iceberg/backtest_results/"
      columns = [
        {
          name    = "formula_id"
          type    = "string"
          comment = "Formula identifier"
        },
        {
          name    = "formula"
          type    = "string"
          comment = "Formula expression"
        },
        {
          name    = "sharpe_ratio"
          type    = "double"
          comment = "Sharpe ratio from backtest"
        },
        {
          name    = "total_return"
          type    = "double"
          comment = "Total return"
        },
        {
          name    = "max_drawdown"
          type    = "double"
          comment = "Maximum drawdown"
        },
        {
          name    = "created_at"
          type    = "timestamp"
          comment = "Backtest creation timestamp"
        }
      ]
    }
    market_data_raw_hourly = {
      location = "s3://${aws_s3_bucket.data_lake.bucket}/iceberg/market_data_raw_hourly/"
      columns = [
        {
          name    = "timestamp"
          type    = "timestamp"
          comment = "Bar open timestamp (hourly precision)"
        },
        {
          name    = "symbol"
          type    = "string"
          comment = "Trading symbol (e.g., HSBA.L)"
        },
        {
          name    = "source"
          type    = "string"
          comment = "Data provider (e.g., yfinance)"
        },
        {
          name    = "open"
          type    = "double"
          comment = "Opening price"
        },
        {
          name    = "high"
          type    = "double"
          comment = "High price"
        },
        {
          name    = "low"
          type    = "double"
          comment = "Low price"
        },
        {
          name    = "close"
          type    = "double"
          comment = "Closing price"
        },
        {
          name    = "adj_close"
          type    = "double"
          comment = "Adjusted closing price"
        },
        {
          name    = "volume"
          type    = "bigint"
          comment = "Trading volume"
        },
        {
          name    = "ingested_at"
          type    = "timestamp"
          comment = "Pipeline ingestion timestamp"
        }
      ]
      partition_columns = ["trade_date"]
    }
    # Operational data store tables (Decision 50) -- append-only Iceberg for audit trail
    ops_recommendations = {
      location = "s3://${aws_s3_bucket.agent_logs.bucket}/iceberg/ops_recommendations/"
      columns = [
        { name = "id", type = "string", comment = "Recommendation ID (e.g., rec-001)" },
        { name = "title", type = "string", comment = "Concise description" },
        { name = "source", type = "string", comment = "Origin: executor-supervision, code-review, planning, brainstorm" },
        { name = "effort", type = "string", comment = "XS, S, M, L, or XL" },
        { name = "priority", type = "string", comment = "Critical, High, Medium, or Low" },
        { name = "status", type = "string", comment = "open, closed, failed, declined, or superseded" },
        { name = "automatable", type = "boolean", comment = "Whether the executor can handle this" },
        { name = "risk", type = "string", comment = "low, medium, or high" },
        { name = "file", type = "string", comment = "Primary target file path" },
        { name = "context", type = "string", comment = "Why this rec exists (self-contained for executor)" },
        { name = "acceptance", type = "string", comment = "Shell command returning 0 on success" },
        { name = "dependencies", type = "array<string>", comment = "Blocking rec IDs" },
        { name = "tags", type = "array<string>", comment = "Categorisation tags" },
        { name = "resolution", type = "string", comment = "Why declined or superseded" },
        { name = "execution_result", type = "string", comment = "success, failure, manual, or already_implemented" },
        { name = "execution_date", type = "string", comment = "ISO-8601 timestamp set by executor" },
        { name = "execution_branch", type = "string", comment = "Branch name set by executor" },
        { name = "execution_pr_url", type = "string", comment = "PR URL set by executor" },
        { name = "execution_steps", type = "int", comment = "Step count set by executor" },
        { name = "created_timestamp", type = "timestamp", comment = "When this record was first created (SCD2)" },
        { name = "last_updated_timestamp", type = "timestamp", comment = "When this version was written (SCD2 ordering key)" }
      ]
      partition_columns = []
    }
    ops_execution_plans = {
      location = "s3://${aws_s3_bucket.agent_logs.bucket}/iceberg/ops_execution_plans/"
      columns = [
        { name = "plan_id", type = "string", comment = "Unique plan ID (UUID)" },
        { name = "rec_id", type = "string", comment = "Recommendation ID this plan targets" },
        { name = "branch", type = "string", comment = "Git branch for this execution" },
        { name = "plan_type", type = "string", comment = "IMPLEMENTATION or STRATEGIC" },
        { name = "verification_tier", type = "string", comment = "V1, V2, or V3" },
        { name = "steps_json", type = "string", comment = "JSON-encoded ordered execution steps array" },
        { name = "scope_json", type = "string", comment = "JSON-encoded scope table" },
        { name = "model_used", type = "string", comment = "Model ID used for planning" },
        { name = "critique_result", type = "string", comment = "APPROVED, NEEDS_REVISION, or EXHAUSTED" },
        { name = "created_timestamp", type = "timestamp", comment = "When this record was first created (SCD2)" },
        { name = "last_updated_timestamp", type = "timestamp", comment = "When this version was written (SCD2 ordering key)" }
      ]
      partition_columns = []
    }
    ops_session_log = {
      location = "s3://${aws_s3_bucket.agent_logs.bucket}/iceberg/ops_session_log/"
      columns = [
        { name = "session_id", type = "string", comment = "Unique session ID (UUID)" },
        { name = "branch", type = "string", comment = "Git branch active during session" },
        { name = "session_type", type = "string", comment = "executor-supervision, planning, implementation, strategic-review" },
        { name = "recs_attempted", type = "array<string>", comment = "Rec IDs attempted this session" },
        { name = "recs_closed", type = "array<string>", comment = "Rec IDs successfully closed this session" },
        { name = "summary", type = "string", comment = "Human-readable session summary" },
        { name = "duration_minutes", type = "int", comment = "Session wall-clock duration" },
        { name = "created_timestamp", type = "timestamp", comment = "When this record was first created (SCD2)" },
        { name = "last_updated_timestamp", type = "timestamp", comment = "When this version was written (SCD2 ordering key)" }
      ]
      partition_columns = []
    }
    ops_decisions = {
      location = "s3://${aws_s3_bucket.agent_logs.bucket}/iceberg/ops_decisions/"
      columns = [
        { name = "id", type = "string", comment = "Canonical string key (dec-NNN). Introduced Phase 0+1." },
        { name = "decision_id", type = "int", comment = "Sequential decision number (e.g., 50)" },
        { name = "title", type = "string", comment = "Decision title" },
        { name = "status", type = "string", comment = "Decided, Superseded, or Open" },
        { name = "problem", type = "string", comment = "Problem statement" },
        { name = "decision_text", type = "string", comment = "The decision made" },
        { name = "context", type = "string", comment = "Why this decision was made" },
        { name = "decided_date", type = "string", comment = "ISO date decided" },
        { name = "related_decisions", type = "array<int>", comment = "Related decision IDs (legacy; deprecated in Phase 6)" },
        { name = "related_decisions_v2", type = "array<string>", comment = "Related decision IDs in dec-NNN format (introduced Phase 0+1)" },
        { name = "created_timestamp", type = "timestamp", comment = "When this record was first created (SCD2)" },
        { name = "last_updated_timestamp", type = "timestamp", comment = "When this version was written (SCD2 ordering key)" }
      ]
      partition_columns = []
    }
    ops_priority_queue = {
      location = "s3://${aws_s3_bucket.agent_logs.bucket}/iceberg/ops_priority_queue/"
      columns = [
        { name = "queue_run_id", type = "string", comment = "UUID shared by all entries in one curator run" },
        { name = "rank", type = "int", comment = "Priority rank within the run (1 = highest)" },
        { name = "rec_id", type = "string", comment = "Recommendation ID" },
        { name = "mode", type = "string", comment = "solo or compound" },
        { name = "compound_with", type = "array<string>", comment = "Other rec IDs in compound run" },
        { name = "rationale", type = "string", comment = "Why this rec is ranked here" },
        { name = "gates", type = "array<string>", comment = "Blocking gate conditions" },
        { name = "north_star_impact", type = "string", comment = "How this serves the North Star" },
        { name = "decay_date", type = "string", comment = "Date after which this entry is stale" },
        { name = "status", type = "string", comment = "queued, executing, or done" },
        { name = "created_timestamp", type = "timestamp", comment = "When this record was first created (SCD2)" },
        { name = "last_updated_timestamp", type = "timestamp", comment = "When this version was written (SCD2 ordering key)" }
      ]
      partition_columns = []
    }
  }
}

# Create Iceberg tables via Athena (required for proper metadata location)
# Using null_resource with local-exec to run Athena CREATE TABLE queries

locals {
  create_table_queries = {
    formula_lineage = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.formula_lineage (
        formula_id string COMMENT 'Unique UUID for formula',
        version int COMMENT 'Formula version number (starts at 1)',
        formula_expression string COMMENT 'Symbolic expression (e.g., tanh(x0 * 0.5 + x1))',
        feature_names array<string> COMMENT 'List of feature variable names',
        discovery_timestamp timestamp COMMENT 'When formula was discovered by PySR',
        discovery_job_id string COMMENT 'SageMaker job ID that produced formula',
        discovery_metrics struct<sharpe_ratio:double,complexity:int,mse:double> COMMENT 'Metrics from PySR training',
        state string COMMENT 'Current state: discovered|testing|staging|production|deprecated|circuit_broken',
        state_changed_at timestamp COMMENT 'When state last changed',
        state_changed_by string COMMENT 'Process that changed state',
        ab_test_id string COMMENT 'A/B test ID if in testing/staging',
        ab_test_metrics struct<win_rate:double,sharpe_ratio:double,max_drawdown:double,sample_size:int> COMMENT 'A/B test results',
        production_metrics struct<win_rate:double,sharpe_ratio:double,max_drawdown:double,total_trades:int> COMMENT 'Live trading performance',
        circuit_breaker_triggered boolean COMMENT 'Whether circuit breaker activated',
        circuit_breaker_reason string COMMENT 'Why circuit breaker triggered',
        s3_bucket string COMMENT 'Current S3 bucket',
        s3_key string COMMENT 'S3 object key',
        metadata map<string,string> COMMENT 'Additional metadata'
      )
      LOCATION '${local.glue_tables["formula_lineage"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    trading_performance = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.trading_performance (
        trade_id string COMMENT 'Unique trade identifier',
        formula_id string COMMENT 'Formula that generated signal',
        formula_version int COMMENT 'Formula version at trade time',
        timestamp timestamp COMMENT 'Trade execution timestamp',
        symbol string COMMENT 'Trading symbol',
        signal double COMMENT 'Formula output signal [-1.0, 1.0]',
        position_size double COMMENT 'Position size in USD',
        entry_price double COMMENT 'Entry price',
        exit_price double COMMENT 'Exit price',
        pnl double COMMENT 'Profit/Loss in USD',
        holding_period int COMMENT 'Holding period in seconds',
        features map<string,double> COMMENT 'Input features at signal time',
        market_regime string COMMENT 'Market regime (bull|bear|sideways)',
        ab_test_id string COMMENT 'A/B test ID if applicable',
        environment string COMMENT 'trading|paper|backtest'
      )
      LOCATION '${local.glue_tables["trading_performance"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    ab_test_results = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.ab_test_results (
        ab_test_id string COMMENT 'Unique test identifier',
        formula_id string COMMENT 'Formula being tested',
        start_date timestamp COMMENT 'Test start date',
        end_date timestamp COMMENT 'Test end date',
        duration_days int COMMENT 'Test duration (7|14|30 days)',
        control_sharpe double COMMENT 'Control group Sharpe ratio',
        treatment_sharpe double COMMENT 'Treatment group Sharpe ratio',
        p_value double COMMENT 'Statistical significance (p < 0.05)',
        sample_size int COMMENT 'Number of trades',
        decision string COMMENT 'promote|reject|extend',
        decision_reason string COMMENT 'Why decision was made',
        promoted_to_production boolean COMMENT 'Whether formula was promoted'
      )
      LOCATION '${local.glue_tables["ab_test_results"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet'
      )
    EOT

    market_data = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.market_data (
        timestamp timestamp COMMENT 'Market data timestamp',
        symbol string COMMENT 'Trading symbol (e.g., HSBA.L, BP.L)',
        source string COMMENT 'Data provider (e.g., yfinance, alpha_vantage, manual)',
        open double COMMENT 'Opening price',
        high double COMMENT 'High price',
        low double COMMENT 'Low price',
        close double COMMENT 'Closing price',
        adj_close double COMMENT 'Adjusted closing price',
        volume bigint COMMENT 'Trading volume',
        tech_rsi_14 double COMMENT 'RSI (14-period)',
        tech_macd double COMMENT 'MACD line (12/26 EMA)',
        tech_macd_signal double COMMENT 'MACD signal line',
        tech_macd_histogram double COMMENT 'MACD histogram',
        tech_bb_width double COMMENT 'Bollinger Band width (2σ / SMA20)',
        tech_atr_14 double COMMENT 'Average True Range (14-period)',
        tech_sma_20 double COMMENT 'Simple Moving Average (20-day)',
        tech_sma_50 double COMMENT 'Simple Moving Average (50-day)',
        tech_sma_200 double COMMENT 'Simple Moving Average (200-day)',
        tech_ema_12 double COMMENT 'Exponential Moving Average (12-period)',
        tech_ema_26 double COMMENT 'Exponential Moving Average (26-period)',
        tech_volume_ratio double COMMENT 'Volume relative to 20-day average',
        tech_momentum_5d double COMMENT '5-day price momentum',
        tech_momentum_10d double COMMENT '10-day price momentum',
        tech_momentum_20d double COMMENT '20-day price momentum',
        tech_volatility_20d double COMMENT '20-day historical volatility (annualised)',
        fundamental_pe double COMMENT 'Trailing or forward P/E ratio',
        fundamental_market_cap double COMMENT 'Market capitalisation',
        fundamental_div_yield double COMMENT 'Dividend yield',
        sentiment_fear_greed double COMMENT 'CNN Fear & Greed Index (0-100)',
        delta_price_1d double COMMENT '1-day close price % change',
        delta_price_5d double COMMENT '5-day close price % change',
        delta_price_20d double COMMENT '20-day close price % change',
        delta_volatility_10d double COMMENT '10-day rolling volatility (annualised)',
        zscore_close_30d double COMMENT '30-day z-score of close price',
        zscore_volume_30d double COMMENT '30-day z-score of volume',
        zscore_rsi_30d double COMMENT '30-day z-score of RSI(14)',
        delta_sentiment_1d double COMMENT '1-day change in Fear & Greed Index',
        features map<string,double> COMMENT 'Experimental features landing zone',
        ingested_at timestamp COMMENT 'Pipeline ingestion timestamp',
        interval string COMMENT 'Data granularity: 1d (daily), 1h (hourly), 15m (15-minute), etc.',
        trade_date date COMMENT 'Trading date (partition key)'
      )
      PARTITIONED BY (trade_date)
      LOCATION '${local.glue_tables["market_data"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip',
        'write.metadata.delete-after-commit.enabled'='true',
        'write.metadata.previous-versions-max'='10'
      )
    EOT

    backtest_results = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.backtest_results (
        formula_id string COMMENT 'Formula identifier',
        formula string COMMENT 'Formula expression',
        sharpe_ratio double COMMENT 'Sharpe ratio from backtest',
        total_return double COMMENT 'Total return',
        max_drawdown double COMMENT 'Maximum drawdown',
        created_at timestamp COMMENT 'Backtest creation timestamp'
      )
      LOCATION '${local.glue_tables["backtest_results"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    market_data_raw_hourly = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.market_data_raw_hourly (
        timestamp timestamp COMMENT 'Bar open timestamp (hourly precision)',
        symbol string COMMENT 'Trading symbol (e.g., HSBA.L)',
        source string COMMENT 'Data provider (e.g., yfinance)',
        open double COMMENT 'Opening price',
        high double COMMENT 'High price',
        low double COMMENT 'Low price',
        close double COMMENT 'Closing price',
        adj_close double COMMENT 'Adjusted closing price',
        volume bigint COMMENT 'Trading volume',
        ingested_at timestamp COMMENT 'Pipeline ingestion timestamp',
        trade_date date COMMENT 'Trading date (partition key)'
      )
      PARTITIONED BY (trade_date)
      LOCATION '${local.glue_tables["market_data_raw_hourly"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip',
        'write.metadata.delete-after-commit.enabled'='true',
        'write.metadata.previous-versions-max'='10'
      )
    EOT

    # Operational data store tables (Decision 50, schema Decision 56)
    ops_recommendations = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.ops_recommendations (
        id string COMMENT 'Recommendation ID (e.g., rec-001)',
        title string COMMENT 'Concise description',
        source string COMMENT 'Origin: executor-supervision, code-review, planning, brainstorm',
        effort string COMMENT 'XS, S, M, L, or XL',
        priority string COMMENT 'Critical, High, Medium, or Low',
        status string COMMENT 'open, closed, failed, declined, or superseded',
        automatable boolean COMMENT 'Whether the executor can handle this',
        risk string COMMENT 'low, medium, or high',
        file string COMMENT 'Primary target file path',
        context string COMMENT 'Why this rec exists',
        acceptance string COMMENT 'Shell command returning 0 on success',
        dependencies array<string> COMMENT 'Blocking rec IDs',
        tags array<string> COMMENT 'Categorisation tags',
        resolution string COMMENT 'Why declined or superseded',
        execution_result string COMMENT 'success, failure, manual, or already_implemented',
        execution_date string COMMENT 'ISO-8601 timestamp set by executor',
        execution_branch string COMMENT 'Branch name set by executor',
        execution_pr_url string COMMENT 'PR URL set by executor',
        execution_steps int COMMENT 'Step count set by executor',
        created_timestamp timestamp COMMENT 'When this record was first created (SCD2)',
        last_updated_timestamp timestamp COMMENT 'When this version was written (SCD2 ordering key)'
      )
      PARTITIONED BY (day(last_updated_timestamp))
      LOCATION '${local.glue_tables["ops_recommendations"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    ops_execution_plans = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.ops_execution_plans (
        plan_id string COMMENT 'Unique plan ID (UUID)',
        rec_id string COMMENT 'Recommendation ID this plan targets',
        branch string COMMENT 'Git branch for this execution',
        plan_type string COMMENT 'IMPLEMENTATION or STRATEGIC',
        verification_tier string COMMENT 'V1, V2, or V3',
        steps_json string COMMENT 'JSON-encoded ordered execution steps array',
        scope_json string COMMENT 'JSON-encoded scope table',
        model_used string COMMENT 'Model ID used for planning',
        critique_result string COMMENT 'APPROVED, NEEDS_REVISION, or EXHAUSTED',
        created_timestamp timestamp COMMENT 'When this record was first created (SCD2)',
        last_updated_timestamp timestamp COMMENT 'When this version was written (SCD2 ordering key)'
      )
      PARTITIONED BY (day(last_updated_timestamp))
      LOCATION '${local.glue_tables["ops_execution_plans"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    ops_session_log = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.ops_session_log (
        session_id string COMMENT 'Unique session ID (UUID)',
        branch string COMMENT 'Git branch active during session',
        session_type string COMMENT 'executor-supervision, planning, implementation, strategic-review',
        recs_attempted array<string> COMMENT 'Rec IDs attempted this session',
        recs_closed array<string> COMMENT 'Rec IDs successfully closed this session',
        summary string COMMENT 'Human-readable session summary',
        duration_minutes int COMMENT 'Session wall-clock duration',
        created_timestamp timestamp COMMENT 'When this record was first created (SCD2)',
        last_updated_timestamp timestamp COMMENT 'When this version was written (SCD2 ordering key)'
      )
      PARTITIONED BY (day(last_updated_timestamp))
      LOCATION '${local.glue_tables["ops_session_log"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    ops_decisions = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.ops_decisions (
        id string COMMENT 'Canonical string key (dec-NNN). Introduced Phase 0+1.',
        decision_id int COMMENT 'Sequential decision number (e.g., 50)',
        title string COMMENT 'Decision title',
        status string COMMENT 'Decided, Superseded, or Open',
        problem string COMMENT 'Problem statement',
        decision_text string COMMENT 'The decision made',
        context string COMMENT 'Why this decision was made',
        decided_date string COMMENT 'ISO date decided',
        related_decisions array<int> COMMENT 'Related decision IDs (legacy; deprecated in Phase 6)',
        related_decisions_v2 array<string> COMMENT 'Related decision IDs in dec-NNN format (introduced Phase 0+1)',
        created_timestamp timestamp COMMENT 'When this record was first created (SCD2)',
        last_updated_timestamp timestamp COMMENT 'When this version was written (SCD2 ordering key)'
      )
      PARTITIONED BY (day(last_updated_timestamp))
      LOCATION '${local.glue_tables["ops_decisions"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    ops_priority_queue = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.ops_priority_queue (
        queue_run_id string COMMENT 'UUID shared by all entries in one curator run',
        rank int COMMENT 'Priority rank within the run (1 = highest)',
        rec_id string COMMENT 'Recommendation ID',
        mode string COMMENT 'solo or compound',
        compound_with array<string> COMMENT 'Other rec IDs in compound run',
        rationale string COMMENT 'Why this rec is ranked here',
        gates array<string> COMMENT 'Blocking gate conditions',
        north_star_impact string COMMENT 'How this serves the North Star',
        decay_date string COMMENT 'Date after which this entry is stale',
        status string COMMENT 'queued, executing, or done',
        created_timestamp timestamp COMMENT 'When this record was first created (SCD2)',
        last_updated_timestamp timestamp COMMENT 'When this version was written (SCD2 ordering key)'
      )
      PARTITIONED BY (day(last_updated_timestamp))
      LOCATION '${local.glue_tables["ops_priority_queue"].location}'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT
  }
}

resource "null_resource" "create_iceberg_tables" {
  for_each = local.create_table_queries

  triggers = {
    query_hash = md5(each.value)
  }

  provisioner "local-exec" {
    command     = <<-EOT
      $QueryFile = [System.IO.Path]::GetTempFileName()
      $Query = @'
${each.value}
'@
      $Query | Out-File -FilePath $QueryFile -Encoding utf8

      $QueryId = aws athena start-query-execution `
        --query-string (Get-Content $QueryFile -Raw) `
        --query-execution-context Database=${aws_glue_catalog_database.trading_db.name} `
        --result-configuration OutputLocation=s3://${aws_s3_bucket.formulas_discovery.bucket}/athena-results/ `
        --work-group agent-platform-production `
        --region ${var.aws_region} `
        --profile ${var.aws_profile} `
        --query 'QueryExecutionId' `
        --output text

      if ($LASTEXITCODE -ne 0) {
        Remove-Item $QueryFile
        exit 1
      }

      # Wait for query to complete
      do {
        Start-Sleep -Seconds 2
        $Status = aws athena get-query-execution `
          --query-execution-id $QueryId `
          --region ${var.aws_region} `
          --profile ${var.aws_profile} `
          --query 'QueryExecution.Status.State' `
          --output text
      } while ($Status -eq 'RUNNING' -or $Status -eq 'QUEUED')

      Remove-Item $QueryFile

      if ($Status -ne 'SUCCEEDED') {
        Write-Error "Athena query failed with status: $Status"
        exit 1
      }
    EOT
    interpreter = ["PowerShell", "-Command"]
    # INTENTIONAL: on_failure = continue is required here because Athena returns
    # FAILED (not SUCCEEDED) for CREATE TABLE IF NOT EXISTS when the table already
    # exists. This is expected idempotent behaviour on re-plan after DDL hash changes
    # or on first-time apply over a pre-existing database. It does NOT mask real
    # table-creation failures — recheck Athena query history if tables are missing.
    # Schema evolution on existing tables is handled by the daily pipeline's
    # awswrangler writes (schema_evolution=True).
    on_failure = continue
  }

  depends_on = [
    aws_glue_catalog_database.trading_db,
    aws_s3_bucket.formulas_discovery,
    aws_s3_bucket.agent_logs
  ]
}

# Operational current-state views (Decision 50)
# ROW_NUMBER() deduplication -- INSERT-only tables, views expose latest snapshot per entity
locals {
  create_ops_view_queries = {
    ops_recommendations_current = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.trading_db.name}.ops_recommendations_current AS
      SELECT *
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY id ORDER BY last_updated_timestamp DESC) AS row_num
        FROM ${aws_glue_catalog_database.trading_db.name}.ops_recommendations
      )
      WHERE row_num = 1
    EOT

    ops_decisions_current = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.trading_db.name}.ops_decisions_current AS
      SELECT *
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY id ORDER BY last_updated_timestamp DESC) AS row_num
        FROM ${aws_glue_catalog_database.trading_db.name}.ops_decisions
      )
      WHERE row_num = 1
    EOT

    ops_priority_queue_current = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.trading_db.name}.ops_priority_queue_current AS
      SELECT * FROM ${aws_glue_catalog_database.trading_db.name}.ops_priority_queue
      WHERE queue_run_id = (
        SELECT queue_run_id
        FROM ${aws_glue_catalog_database.trading_db.name}.ops_priority_queue
        ORDER BY last_updated_timestamp DESC
        LIMIT 1
      )
    EOT
  }
}

resource "null_resource" "create_ops_views" {
  for_each = local.create_ops_view_queries

  triggers = {
    query_hash = md5(each.value)
  }

  provisioner "local-exec" {
    command     = <<-EOT
      $QueryFile = [System.IO.Path]::GetTempFileName()
      $Query = @'
${each.value}
'@
      $Query | Out-File -FilePath $QueryFile -Encoding utf8

      $QueryId = aws athena start-query-execution `
        --query-string (Get-Content $QueryFile -Raw) `
        --query-execution-context Database=${aws_glue_catalog_database.trading_db.name} `
        --result-configuration OutputLocation=s3://${aws_s3_bucket.formulas_discovery.bucket}/athena-results/ `
        --work-group agent-platform-production `
        --region ${var.aws_region} `
        --profile ${var.aws_profile} `
        --query 'QueryExecutionId' `
        --output text

      if ($LASTEXITCODE -ne 0) {
        Remove-Item $QueryFile
        exit 1
      }

      do {
        Start-Sleep -Seconds 2
        $Status = aws athena get-query-execution `
          --query-execution-id $QueryId `
          --region ${var.aws_region} `
          --profile ${var.aws_profile} `
          --query 'QueryExecution.Status.State' `
          --output text
      } while ($Status -eq 'RUNNING' -or $Status -eq 'QUEUED')

      Remove-Item $QueryFile

      if ($Status -ne 'SUCCEEDED') {
        Write-Error "Athena view creation failed with status: $Status"
        exit 1
      }
    EOT
    interpreter = ["PowerShell", "-Command"]
    on_failure  = continue
  }

  depends_on = [null_resource.create_iceberg_tables]
}

# Data source to retrieve table information after creation
data "aws_glue_catalog_table" "iceberg_tables" {
  for_each = local.glue_tables

  name          = each.key
  database_name = aws_glue_catalog_database.trading_db.name

  depends_on = [null_resource.create_iceberg_tables]
}

# IAM Role for Glue Crawler (to update Iceberg metadata)
resource "aws_iam_role" "glue_crawler" {
  name = "${var.environment}-formula-glue-crawler"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "glue.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "glue_service" {
  role       = aws_iam_role.glue_crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy" "glue_s3_access" {
  name = "glue-s3-access"
  role = aws_iam_role.glue_crawler.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          "${aws_s3_bucket.formulas_discovery.arn}/*",
          "${aws_s3_bucket.formulas_discovery.arn}"
        ]
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# Telemetry tables (7-table star schema -- Phase A of INTENT-telemetry-system.md)
# All tables use the agent_logs S3 bucket with telemetry_ prefix.
# All integer columns use bigint to avoid Iceberg integer-promotion issues.
# ---------------------------------------------------------------------------

locals {
  create_telemetry_table_queries = {
    telemetry_sessions = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.telemetry_sessions (
        session_id string COMMENT 'PK. UUID generated at session start.',
        workflow string COMMENT 'Enum: plan, implement, executor, scheduled_agent, strategic_review.',
        branch string COMMENT 'Git branch. Null for scheduled agents.',
        rec_ids array<string> COMMENT 'Recommendation IDs addressed. Null for non-rec work.',
        plan_slug string COMMENT 'Plan file slug. Null if no plan.',
        started_at timestamp COMMENT 'Session start (ISO-8601).',
        ended_at timestamp COMMENT 'Session end. Null if crashed/abandoned.',
        duration_seconds bigint COMMENT 'Wall-clock duration.',
        outcome string COMMENT 'Enum: success, failed, abandoned, partial, timeout, already_implemented.',
        failure_reason string COMMENT 'Structured failure class.',
        failure_phase string COMMENT 'Which phase failed.',
        files_changed bigint COMMENT 'Total files modified.',
        lines_added bigint COMMENT 'Lines added.',
        lines_removed bigint COMMENT 'Lines removed.',
        steps_total bigint COMMENT 'Planned steps.',
        steps_completed bigint COMMENT 'Actually completed steps.',
        process_event_count bigint COMMENT 'Total process events in this session.',
        rework_count bigint COMMENT 'Count of tier=rework events.',
        exception_count bigint COMMENT 'Count of tier=exception events.',
        scope_drift_files array<string> COMMENT 'Files changed not in plan scope.',
        pr_url string COMMENT 'GitHub PR URL.',
        ci_outcome string COMMENT 'Enum: passed, failed, timeout, skipped.',
        model_primary string COMMENT 'Primary model used.',
        execution_attempt bigint COMMENT 'Retry number. 1 = first attempt.',
        parent_session_id string COMMENT 'For retries, links to the original session.',
        coverage_before double COMMENT 'Test coverage % at session start.',
        coverage_after double COMMENT 'Test coverage % at session end.',
        ingested_at timestamp COMMENT 'Write timestamp.',
        trade_date date COMMENT 'Partition key.'
      )
      PARTITIONED BY (trade_date)
      LOCATION 's3://${aws_s3_bucket.agent_logs.bucket}/iceberg/telemetry_sessions/'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    telemetry_phases = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.telemetry_phases (
        phase_id string COMMENT 'PK. UUID.',
        session_id string COMMENT 'FK to telemetry_sessions.',
        phase string COMMENT 'Enum: preflight, plan_generation, critique, refinement, implementation, validation, acceptance, code_review, code_review_fix, ci_wait, ci_fix, merge, merge_recovery, cleanup, postflight.',
        phase_order bigint COMMENT 'Sequence within session (1, 2, 3...).',
        started_at timestamp COMMENT 'Phase start.',
        ended_at timestamp COMMENT 'Phase end. Null if ongoing/crashed.',
        duration_seconds bigint COMMENT 'Duration in seconds.',
        outcome string COMMENT 'Enum: success, failed, skipped, retried, escalated.',
        attempt_number bigint COMMENT 'Which attempt of this phase (1 = first).',
        max_attempts bigint COMMENT 'Configured max attempts for this phase.',
        model_used string COMMENT 'Model for this phase.',
        tokens_input bigint COMMENT 'Total input tokens consumed in this phase.',
        tokens_output bigint COMMENT 'Total output tokens generated in this phase.',
        revision_count bigint COMMENT 'For critique/refinement: number of revisions.',
        blocking_findings_count bigint COMMENT 'For code_review: number of blocking findings.',
        plan_steps_json string COMMENT 'For plan_generation: JSON array of structured plan steps.',
        metadata_json string COMMENT 'JSON blob for phase-specific data not in named columns.',
        ingested_at timestamp COMMENT 'Write timestamp.',
        trade_date date COMMENT 'Partition key.'
      )
      PARTITIONED BY (trade_date)
      LOCATION 's3://${aws_s3_bucket.agent_logs.bucket}/iceberg/telemetry_phases/'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    telemetry_steps = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.telemetry_steps (
        step_id string COMMENT 'PK. UUID.',
        session_id string COMMENT 'FK to telemetry_sessions.',
        phase_id string COMMENT 'FK to telemetry_phases (the implementation phase).',
        step_number bigint COMMENT '1-indexed step within plan.',
        total_steps bigint COMMENT 'Total planned steps.',
        title string COMMENT 'Step title from plan.',
        target_file string COMMENT 'Primary file being modified.',
        action string COMMENT 'Enum: create, modify, delete.',
        started_at timestamp COMMENT 'Step start.',
        ended_at timestamp COMMENT 'Step end.',
        duration_seconds bigint COMMENT 'Duration in seconds.',
        outcome string COMMENT 'Enum: success, failed, retried, skipped, ghost_step.',
        model_used string COMMENT 'Model used for this step.',
        tokens_input bigint COMMENT 'Input tokens.',
        tokens_output bigint COMMENT 'Output tokens.',
        acceptance_command string COMMENT 'The acceptance check that was run.',
        acceptance_passed boolean COMMENT 'Whether acceptance passed.',
        acceptance_duration_seconds bigint COMMENT 'How long acceptance took.',
        diff_stat string COMMENT 'Git diff summary.',
        lines_added bigint COMMENT 'Lines added.',
        lines_removed bigint COMMENT 'Lines removed.',
        retry_count bigint COMMENT 'Times this step was retried (0 = first attempt succeeded).',
        model_escalated_from string COMMENT 'Previous model if escalation occurred.',
        prompt_hash string COMMENT 'Hash for prompt reproducibility.',
        transcript_path string COMMENT 'Path to transcript file.',
        ingested_at timestamp COMMENT 'Write timestamp.',
        trade_date date COMMENT 'Partition key.'
      )
      PARTITIONED BY (trade_date)
      LOCATION 's3://${aws_s3_bucket.agent_logs.bucket}/iceberg/telemetry_steps/'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    telemetry_process_events = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.telemetry_process_events (
        event_id string COMMENT 'PK. UUID.',
        session_id string COMMENT 'FK to telemetry_sessions. Null for standalone anomaly detections.',
        phase_id string COMMENT 'FK to telemetry_phases.',
        step_id string COMMENT 'FK to telemetry_steps.',
        rec_id string COMMENT 'Recommendation being worked on.',
        timestamp timestamp COMMENT 'When the event was observed.',
        tier string COMMENT 'Enum: decision, rework, exception, anomaly.',
        category string COMMENT 'Process event category (see canonical enum in INTENT).',
        severity string COMMENT 'Enum: info, warning, error, critical.',
        description string COMMENT 'Human-readable event description.',
        root_cause string COMMENT 'Structured root cause.',
        resolution string COMMENT 'How the event was resolved.',
        time_lost_seconds bigint COMMENT 'Estimated time consumed by this event.',
        rec_filed string COMMENT 'Recommendation ID filed to address this event.',
        detected_by string COMMENT 'Enum: executor_script, recovery_agent, cloud_analysis_agent, manual.',
        ingested_at timestamp COMMENT 'Write timestamp.',
        trade_date date COMMENT 'Partition key.'
      )
      PARTITIONED BY (trade_date)
      LOCATION 's3://${aws_s3_bucket.agent_logs.bucket}/iceberg/telemetry_process_events/'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    telemetry_model_calls = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.telemetry_model_calls (
        call_id string COMMENT 'PK. UUID.',
        session_id string COMMENT 'FK to telemetry_sessions. Null for scheduled agent calls.',
        phase_id string COMMENT 'FK to telemetry_phases.',
        step_id string COMMENT 'FK to telemetry_steps.',
        invocation_id string COMMENT 'FK to telemetry_agent_invocations.',
        timestamp timestamp COMMENT 'Call start.',
        duration_seconds bigint COMMENT 'Latency in seconds.',
        provider string COMMENT 'Enum: copilot_cli, copilot_sdk, github_models.',
        model string COMMENT 'Model identifier (e.g., claude-haiku-4.5, gpt-5-mini).',
        purpose string COMMENT 'Enum: planning, critique, refinement, implementation, code_review, code_review_fix, ci_fix, merge_recovery, risk_classification, findings, comparison, escalation_diagnosis, acceptance_rewrite, self_repair.',
        tokens_input bigint COMMENT 'Input tokens consumed.',
        tokens_output bigint COMMENT 'Output tokens generated.',
        exit_code bigint COMMENT 'LLM call exit code.',
        copilot_session_id string COMMENT 'Copilot CLI session ID for reuse tracking.',
        prompt_hash string COMMENT 'Hash for prompt version tracking.',
        error string COMMENT 'Error message if failed.',
        ingested_at timestamp COMMENT 'Write timestamp.',
        trade_date date COMMENT 'Partition key.'
      )
      PARTITIONED BY (trade_date)
      LOCATION 's3://${aws_s3_bucket.agent_logs.bucket}/iceberg/telemetry_model_calls/'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    telemetry_transcripts = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.telemetry_transcripts (
        transcript_id string COMMENT 'PK. UUID.',
        session_id string COMMENT 'FK to telemetry_sessions.',
        phase_id string COMMENT 'FK to telemetry_phases.',
        step_id string COMMENT 'FK to telemetry_steps.',
        invocation_id string COMMENT 'FK to telemetry_agent_invocations.',
        timestamp timestamp COMMENT 'When transcript was produced.',
        purpose string COMMENT 'Enum: same as telemetry_model_calls.purpose.',
        local_path string COMMENT 'Local filesystem path.',
        s3_key string COMMENT 'S3 key once uploaded.',
        size_bytes bigint COMMENT 'Transcript file size in bytes.',
        token_count bigint COMMENT 'Estimated token count of transcript content.',
        model_used string COMMENT 'Model that produced this transcript.',
        rec_id string COMMENT 'Recommendation ID if applicable.',
        ingested_at timestamp COMMENT 'Write timestamp.',
        trade_date date COMMENT 'Partition key.'
      )
      PARTITIONED BY (trade_date)
      LOCATION 's3://${aws_s3_bucket.agent_logs.bucket}/iceberg/telemetry_transcripts/'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT

    telemetry_agent_invocations = <<-EOT
      CREATE TABLE IF NOT EXISTS ${aws_glue_catalog_database.trading_db.name}.telemetry_agent_invocations (
        invocation_id string COMMENT 'PK. UUID.',
        agent_name string COMMENT 'Agent identifier (e.g., doc-freshness, rec-curator).',
        trigger string COMMENT 'Enum: eventbridge, manual, smoke_test, cron_workflow.',
        started_at timestamp COMMENT 'Lambda invocation start.',
        ended_at timestamp COMMENT 'Lambda invocation end.',
        duration_seconds bigint COMMENT 'Duration in seconds.',
        outcome string COMMENT 'Enum: success, failed, timeout, throttled.',
        model_used string COMMENT 'Model used.',
        provider string COMMENT 'Enum: copilot_sdk, github_models, anthropic_max.',
        tokens_input bigint COMMENT 'Input tokens.',
        tokens_output bigint COMMENT 'Output tokens.',
        findings_count bigint COMMENT 'Number of findings produced.',
        recs_created bigint COMMENT 'Recs auto-filed by findings processor.',
        queue_entries_written bigint COMMENT 'Priority queue entries (rec-curator).',
        error string COMMENT 'Error message if failed.',
        lambda_request_id string COMMENT 'AWS Lambda request ID; set for eventbridge trigger, null for cron_workflow.',
        workflow_run_id string COMMENT 'GitHub Actions GITHUB_RUN_ID; set for cron_workflow trigger, null for eventbridge/manual.',
        ingested_at timestamp COMMENT 'Write timestamp.',
        trade_date date COMMENT 'Partition key.'
      )
      PARTITIONED BY (trade_date)
      LOCATION 's3://${aws_s3_bucket.agent_logs.bucket}/iceberg/telemetry_agent_invocations/'
      TBLPROPERTIES (
        'table_type'='ICEBERG',
        'format'='parquet',
        'write_compression'='gzip'
      )
    EOT
  }
}

resource "null_resource" "create_telemetry_tables" {
  for_each = local.create_telemetry_table_queries

  triggers = {
    query_hash = md5(each.value)
  }

  provisioner "local-exec" {
    command     = <<-EOT
      $QueryFile = [System.IO.Path]::GetTempFileName()
      $Query = @'
${each.value}
'@
      $Query | Out-File -FilePath $QueryFile -Encoding utf8

      $QueryId = aws athena start-query-execution `
        --query-string (Get-Content $QueryFile -Raw) `
        --query-execution-context Database=${aws_glue_catalog_database.trading_db.name} `
        --result-configuration OutputLocation=s3://${aws_s3_bucket.formulas_discovery.bucket}/athena-results/ `
        --work-group agent-platform-production `
        --region ${var.aws_region} `
        --profile ${var.aws_profile} `
        --query 'QueryExecutionId' `
        --output text

      if ($LASTEXITCODE -ne 0) {
        Remove-Item $QueryFile
        exit 1
      }

      do {
        Start-Sleep -Seconds 2
        $Status = aws athena get-query-execution `
          --query-execution-id $QueryId `
          --region ${var.aws_region} `
          --profile ${var.aws_profile} `
          --query 'QueryExecution.Status.State' `
          --output text
      } while ($Status -eq 'RUNNING' -or $Status -eq 'QUEUED')

      Remove-Item $QueryFile

      if ($Status -ne 'SUCCEEDED') {
        Write-Error "Athena query failed with status: $Status"
        exit 1
      }
    EOT
    interpreter = ["PowerShell", "-Command"]
    # on_failure = continue: Athena returns FAILED for CREATE TABLE IF NOT EXISTS
    # when the table already exists (idempotent behaviour on re-plan).
    on_failure = continue
  }

  depends_on = [
    aws_glue_catalog_database.trading_db,
    aws_s3_bucket.agent_logs
  ]
}

# ---------------------------------------------------------------------------
# Telemetry Athena views
# ---------------------------------------------------------------------------

locals {
  create_telemetry_view_queries = {
    # Current-state views: ROW_NUMBER() deduplication for tables with mutable entity state
    telemetry_sessions_current = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.trading_db.name}.telemetry_sessions_current AS
      SELECT session_id, workflow, branch, rec_ids, plan_slug, started_at, ended_at,
             duration_seconds, outcome, failure_reason, failure_phase,
             files_changed, lines_added, lines_removed,
             steps_total, steps_completed, process_event_count, rework_count,
             exception_count, scope_drift_files, pr_url, ci_outcome, model_primary,
             execution_attempt, parent_session_id, coverage_before, coverage_after,
             ingested_at, trade_date
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY ingested_at DESC) AS row_num
        FROM ${aws_glue_catalog_database.trading_db.name}.telemetry_sessions
      )
      WHERE row_num = 1
    EOT

    telemetry_phases_current = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.trading_db.name}.telemetry_phases_current AS
      SELECT phase_id, session_id, phase, phase_order, started_at, ended_at,
             duration_seconds, outcome, attempt_number, max_attempts, model_used,
             tokens_input, tokens_output, revision_count,
             blocking_findings_count, plan_steps_json, metadata_json,
             ingested_at, trade_date
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY phase_id ORDER BY ingested_at DESC) AS row_num
        FROM ${aws_glue_catalog_database.trading_db.name}.telemetry_phases
      )
      WHERE row_num = 1
    EOT

    telemetry_steps_current = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.trading_db.name}.telemetry_steps_current AS
      SELECT step_id, session_id, phase_id, step_number, total_steps, title,
             target_file, action, started_at, ended_at, duration_seconds, outcome,
             model_used, tokens_input, tokens_output,
             acceptance_command, acceptance_passed, acceptance_duration_seconds,
             diff_stat, lines_added, lines_removed, retry_count, model_escalated_from,
             prompt_hash, transcript_path, ingested_at, trade_date
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY step_id ORDER BY ingested_at DESC) AS row_num
        FROM ${aws_glue_catalog_database.trading_db.name}.telemetry_steps
      )
      WHERE row_num = 1
    EOT

    telemetry_agent_invocations_current = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.trading_db.name}.telemetry_agent_invocations_current AS
      SELECT invocation_id, agent_name, trigger, started_at, ended_at,
             duration_seconds, outcome, model_used, provider,
             tokens_input, tokens_output, findings_count, recs_created,
             queue_entries_written, error, lambda_request_id, ingested_at, trade_date
      FROM (
        SELECT *,
          ROW_NUMBER() OVER (PARTITION BY invocation_id ORDER BY ingested_at DESC) AS row_num
        FROM ${aws_glue_catalog_database.trading_db.name}.telemetry_agent_invocations
      )
      WHERE row_num = 1
    EOT

    # Analytical views (30-day rolling window)
    telemetry_session_summary_30d = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.trading_db.name}.telemetry_session_summary_30d AS
      SELECT
        workflow,
        COUNT(*) AS session_count,
        SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) AS success_count,
        ROUND(100.0 * SUM(CASE WHEN outcome = 'success' THEN 1 ELSE 0 END) / COUNT(*), 2) AS success_rate_pct,
        ROUND(AVG(CAST(duration_seconds AS double)), 1) AS avg_duration_seconds,
        SUM(rework_count) AS total_rework,
        SUM(exception_count) AS total_exceptions
      FROM ${aws_glue_catalog_database.trading_db.name}.telemetry_sessions
      WHERE trade_date >= CURRENT_DATE - INTERVAL '30' DAY
      GROUP BY workflow
    EOT

    telemetry_phase_time_distribution = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.trading_db.name}.telemetry_phase_time_distribution AS
      SELECT
        phase,
        COUNT(*) AS phase_count,
        ROUND(AVG(CAST(duration_seconds AS double)), 1) AS avg_duration_seconds,
        ROUND(
          APPROX_PERCENTILE(CAST(duration_seconds AS double), 0.9), 1
        ) AS p90_duration_seconds,
      FROM ${aws_glue_catalog_database.trading_db.name}.telemetry_phases
      WHERE trade_date >= CURRENT_DATE - INTERVAL '30' DAY
        AND duration_seconds IS NOT NULL
      GROUP BY phase
    EOT

    telemetry_event_frequency_30d = <<-EOT
      CREATE OR REPLACE VIEW ${aws_glue_catalog_database.trading_db.name}.telemetry_event_frequency_30d AS
      SELECT
        tier,
        category,
        COUNT(*) AS event_count,
        COUNT(DISTINCT session_id) AS affected_sessions
      FROM ${aws_glue_catalog_database.trading_db.name}.telemetry_process_events
      WHERE trade_date >= CURRENT_DATE - INTERVAL '30' DAY
      GROUP BY tier, category
      ORDER BY event_count DESC
    EOT
  }
}

resource "null_resource" "create_telemetry_views" {
  for_each = local.create_telemetry_view_queries

  triggers = {
    query_hash = md5(each.value)
  }

  provisioner "local-exec" {
    command     = <<-EOT
      $QueryFile = [System.IO.Path]::GetTempFileName()
      $Query = @'
${each.value}
'@
      $Query | Out-File -FilePath $QueryFile -Encoding utf8

      $QueryId = aws athena start-query-execution `
        --query-string (Get-Content $QueryFile -Raw) `
        --query-execution-context Database=${aws_glue_catalog_database.trading_db.name} `
        --result-configuration OutputLocation=s3://${aws_s3_bucket.formulas_discovery.bucket}/athena-results/ `
        --work-group agent-platform-production `
        --region ${var.aws_region} `
        --profile ${var.aws_profile} `
        --query 'QueryExecutionId' `
        --output text

      if ($LASTEXITCODE -ne 0) {
        Remove-Item $QueryFile
        exit 1
      }

      do {
        Start-Sleep -Seconds 2
        $Status = aws athena get-query-execution `
          --query-execution-id $QueryId `
          --region ${var.aws_region} `
          --profile ${var.aws_profile} `
          --query 'QueryExecution.Status.State' `
          --output text
      } while ($Status -eq 'RUNNING' -or $Status -eq 'QUEUED')

      Remove-Item $QueryFile

      if ($Status -ne 'SUCCEEDED') {
        Write-Error "Athena view creation failed with status: $Status"
        exit 1
      }
    EOT
    interpreter = ["PowerShell", "-Command"]
    on_failure  = continue
  }

  depends_on = [null_resource.create_telemetry_tables]
}
