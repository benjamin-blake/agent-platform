# AUDIT PROMPT - Convert docs/ROADMAP-PRODUCT.md to docs/ROADMAP-PRODUCT.yaml

> Stand-alone prompt for a fresh agent session. Hand this entire file to the
> auditor as their starting context. The auditor has no view of any prior chat.

---

## 1. Mission

Convert `docs/ROADMAP-PRODUCT.md` (843 lines, prose markdown) into
`docs/ROADMAP-PRODUCT.yaml` - a machine-parseable, agent-first artefact that:

1. **Mirrors the structural quality of `docs/ROADMAP-PLATFORM.yaml`** (2,205 lines)
   - `document`, `north_star`, `current_state`, `tier_items[]`,
   `candidate_decisions[]`, `cross_tier_gates[]`, `gate_helpers`,
   `open_questions[]`, `known_gaps[]`.
2. **Incorporates the trading-architecture pivot** embedded as the
   PIVOT TRANSCRIPT in Section 11 below. That transcript SUPERSEDES the
   current product roadmap's organising principles. Treat it as design
   north-star.
3. **Encodes cross-roadmap dependencies** (PRODUCT depends on PLATFORM
   contracts, capabilities, and tier_items). This is the dimension the
   PLATFORM YAML did not have to solve and is the principal additional
   complexity.
4. **Respects the pre-codegen contract-ratification ritual** (CD.25 /
   `docs/INTENT-pre-codegen-contract-ratification.md`). Every product
   schema that becomes Iceberg DDL or a Lambda contract is gated on
   ratification under `docs/contracts/`.

You are NOT implementing the trading system. You are producing
**(a) the YAML roadmap** and **(b) a REPORT-ONLY audit report**
describing the conversion.

---

## 2. Operating context (hard rules - do not violate)

Read `CLAUDE.md` / `AGENTS.md` at repo root first - everything below is a summary.

- **Branching**: never edit on `main`. Check `git branch --show-current`. If
  on `main`, create `agent/product-roadmap-yaml-conversion` from a freshly
  pulled `main` before any edit.
- **No emojis** in code, scripts, or documentation. Plain ASCII hyphens (`-`).
  No em dashes.
- **Python wrapper**: invoke `bin/venv-python` instead of `python` / `python3`.
- **Single Portal Invariant**: do NOT directly edit
  `logs/.recommendations-log.jsonl` or `logs/.decisions-index.jsonl`. All
  recommendation/decision writes go through `scripts/ops_data_portal.py`.
- **STRATEGIC plans are suspended** (CD.17 / Decision 67). Your deliverables
  are IMPLEMENTATION or REPORT-ONLY type. The YAML itself is a documentation
  artefact (neither plan type). The audit report is REPORT-ONLY.
- **Lambda deploys deferred** (CD.16 / Decision 67). If the roadmap
  proposes product-domain Lambdas (e.g., paper-trading scheduler),
  populate the corresponding `tier_item`'s `deferred_note` with the
  **AGENTS.md canonical string verbatim**: `"DEFERRED: build_lambda.py
  --deploy + run_scheduled_agent.py --smoke-test (pending Decision 67
  reversal)"`. Do not paraphrase, do not substitute "CD.16/CD.17" or
  any other phrasing - AGENTS.md is the authority and CI checks for
  this exact string.
- **Warehouse-as-source-of-truth**: any product schema landing in Iceberg
  is Class A (per CD.25 ritual). The YAML must surface a contract-gate
  for it under `docs/contracts/{name}.yaml` (proposed path; do not author
  the contract in this pass).
- **Do NOT modify `docs/ROADMAP-PLATFORM.yaml`**. If you discover
  platform gaps that the product depends on (e.g., transaction-cost
  analysis aggregation, broker adapter Protocol contract), accumulate
  them in `docs/audit-reports/PRODUCT-ROADMAP-PLATFORM-GAPS.yaml`
  (schema in Section 5.3). Do NOT file recs via `ops_data_portal
  file_rec` for these; the user reviews the gap YAML with a follow-up
  agent before any rec is filed. Do not in-line patch PLATFORM.
- **Do NOT delete `docs/ROADMAP-PRODUCT.md`** in this pass. Leave a
  banner at its top: "Superseded by `docs/ROADMAP-PRODUCT.yaml`. Will be
  removed in a follow-up commit." The legacy markdown stays as a
  recovery artefact for one transition cycle.

---

## 3. Mandatory preflight reads (read FULL, do not skim)

These three reads are required BEFORE any subagent fan-out. Read them
yourself, in order, with the `Read` tool. Do not delegate these reads to
subagents - you need the full mental model to brief subagents correctly.

### 3.1 `docs/ROADMAP-PLATFORM.yaml` (2,205 lines)

This is the structural inspiration. Internalise:
- The top-level shape: `document`, `north_star`, `cost_projection`,
  `rebuild_vs_refactor`, `foundation_already_shipped`, `candidate_decisions`,
  `tier_items`, `cross_tier_gates`, `open_questions`, `known_gaps`,
  `gate_helpers`.
- Tier numbering convention (`T-1`, `T0`, `T1`, ..., `T5`) and
  sub-numbering (`T0.7a`, `T0.7b`, `T0.7c`).
- `candidate_decisions[]` shape: `id`, `title`, `detail`, `gates` (list of
  tier_item ids whose COMPLETION it gates), `decision_required_before`
  (optional - state-transition gate), `state` (pending / ratified),
  `filed_via`.
- `tier_items[]` shape: `id`, `tier`, `name`, `intent`, `depends_on`,
  `files_in_scope`, `exit_criteria`, `related_candidate_decisions`,
  `effort` (XS/S/M/L/XL), `strategic`, `status`, optional `completed_at`,
  optional `user_action_required`.
- `gate_helpers` mini-language: `tier_complete(tier_name)`,
  `all_in_tier_with_status(tier_name, status)`, `grace_period_elapsed(...)`,
  etc. The grammar is enforced by `scripts/platform_roadmap.py`
  `RoadmapDocument.model_validate()`.
- The bootstrap clauses (START eligibility and COMPLETION exemption) and
  why they exist.
- `agent_instructions` block: prose rules for agents reading the file.
- CD.1's role as "this document is canonical" - the same pattern will be
  needed for PRODUCT.

### 3.2 `docs/INTENT-pre-codegen-contract-ratification.md` (1,472 lines)

Internalise:
- Class A / Class B / Class C contract definitions and examples.
- The semantic-evolution problem Iceberg does NOT solve, and the
  `_contract_version` column + `semantic_break` flag remedy.
- CD.25's role and current `pending` state.
- The ratification ritual (separate PR for semantics vs codegen).
- `docs/contracts/{name}.yaml` as canonical home for field semantics.
- The CD.16 vs CD.17 split (Lambda-deploy freeze vs STRATEGIC-plan
  freeze) and how each affects product-tier work.
- Which product artefacts WILL be Class A (anything persisted to Iceberg:
  fill records, strategy run records, telemetry tables, cost curves).
- Which product artefacts WILL be Class B (any Lambda Function URL the
  product introduces: paper-trading scheduler, end-of-day reconciliation).
- Which artefacts are Class C (in-process Protocols, Pydantic-only
  configs: `EnvironmentConfig`, broker adapter `Protocol`, `Signal`
  payload pre-persistence).

### 3.3 The PIVOT TRANSCRIPT (Section 11 of this file)

This is a verbatim conversation with a prior agent. It describes the
trading-system architecture the new product roadmap must encode. The
existing `docs/ROADMAP-PRODUCT.md` is PIVOT-SUPERSEDED on its organising
principle - the new YAML organises around the four-layer trading model
(Alpha / Portfolio Construction / Execution / Operations-Telemetry) and environment-
as-config-bundle, NOT around the legacy "Phase 1..7" sequence.

Key shifts to internalise from Section 11. These are organised by
which conversation Part introduces them.

**From Part A (data architecture - OLTP/OLAP framing flip):**

- **Broker is the OLTP source of truth** for orders, positions, cash,
  fills. NOT Postgres, NOT Aurora, NOT RDS. Your system is a client of
  the broker's OLTP, not its source of truth.
- **Three-tier data architecture**: broker (OLTP) -> DynamoDB (fast tier,
  sub-ms mutable cache) -> Iceberg/DuckDB (append-only lakehouse for
  audit/research/market-data history). All three are first-class.
- **DynamoDB, not Postgres**, for the fast tier. Rationale: single-writer
  eliminates MVCC wins; AWS-serverless-native; already in stack via ops
  portal ID allocation; trivially key-value; cost; conditional writes
  give the OLTP primitive (`attribute_not_exists`, `condition: current_status = X`).
- **DynamoDB tables to add**: `orders` (PK = client_order_id), `positions_cache`
  (PK = symbol), `features_serving` (PK = symbol, write-from-batch-only -
  one-way projection from Iceberg, like a feature store).
- **Iceberg tables to add**: `ops_trade_events`, `ops_reconciliations`,
  `strategies_versions`, `alpha_versions`, `pc_versions`, `exec_versions`,
  `strategy_runs`, `signals`, `target_portfolios`, `fills`,
  `pnl_attribution`, `tca_events`, `promotion_events`.
- **The decision loop write-path is a 7-step sequence**: compute decision -
  pre-trade risk gate (read position cache) - generate client_order_id
  (PutItem with conditional) - submit to broker (pass id) - on ack
  (UpdateItem with conditional) - on fill (UpdateItem + cross-item
  transaction with position cache) - reconciliation loop every N minutes.
  Every state change appends to Iceberg.
- **Order lifecycle DAG**: `submitted -> acked -> (filled | partial |
  cancelled | rejected)`. Enforced in three places: broker (authoritative),
  DynamoDB conditional writes (local races), application code.
- **Reconciliation is non-negotiable**. Pull positions from broker every
  N minutes, diff against DynamoDB cache, append reconciliation event,
  file critical rec on drift.
- **Feature precomputation is the legitimate "OLAP feeds OLTP"**: nightly
  DuckDB job over Iceberg -> features written to DynamoDB keyed by symbol.
  One-way; live loop never writes to feature store.
- **Don't write to Iceberg synchronously from hot path** (commits are
  seconds-scale). Buffered writer or SQS -> Lambda batch-append. Reuse
  the existing outbox mental model.
- **Don't put live market data in Iceberg in real-time**. WebSocket ->
  in-memory ring buffer for decisions; batch-write to Iceberg every minute.
- **Don't introduce Kafka / Kinesis prematurely**. SQS + Lambda is
  sufficient until you have multiple consumers of the same stream.

**From Part C (four-layer trading model):**

- **Four-layer trading model**: Alpha (signal generation) -> Portfolio
  Construction (sizing + constraints + hedging) -> Execution (broker-
  facing) -> Operations/Telemetry (feedback). Each layer has its own
  contract.
- **Layer 2 is the high-leverage middle layer that retail-quant content
  ignores.** At small-to-medium size, execution quality and risk
  discipline matter more than signal quality.
- **Layer 2 sub-problems**: (a) position sizing - equal-weight top-N /
  signal-weighted / Kelly (never full) / fractional Kelly / risk parity
  / MVO / Black-Litterman; (b) risk model - ignore / full covariance
  with Ledoit-Wolf shrinkage / factor-based; (c) constraints - max
  position, sector caps, gross/net exposure, liquidity, borrow, cash
  buffer, concentration; (d) turnover control - periodic / threshold /
  turnover budget / cost-aware optimisation; (e) drawdown - never override
  / vol scaling / **hard circuit breaker (non-negotiable for sole-dev)**.
- **Layer 3 execution at retail scale is boring-correct**: marketable
  limit orders 5bps through spread, avoid first/last 15 min, daily once
  ~10:00 ET, no slicing, single retry then file rec.
- **The trade-on-open-vs-close decision**: backtests assume close, live
  trades open or mid-morning. The gap is where backtest-to-live degradation
  lives. Mirror in backtest what you do live.
- **Three parameter populations**: alpha (tuned in research loop),
  strategy (backtested end-to-end on out-of-sample data), operational
  (tuned live from telemetry).
- **Critical insight**: strategy parameters cannot be tuned by alpha-only
  backtests. The whole pipeline (alpha + PC + cost + risk) is the unit
  of optimisation.
- **The frontier per layer**: L1 = 100+ orthogonal alphas via meta-model;
  L2 = convex opt with cost + factor + turnover penalty; L3 = ML execution
  agents minimising shortfall; L4 = full Brinson attribution.
- **For sole-dev**: frontier L1 + L4, mid-tier L2, boring-correct L3.
- **Minimum viable v1 prescription (verbatim from transcript)**:
  - Alpha: formulas -> score per symbol per day, top-N=20.
  - PC: equal-weight or risk-parity over top-N, max position 7%, gross <=
    100% long-only, threshold rebalance epsilon=2%, drawdown -10%/20d ->
    cash 10 trading days, cash buffer 5%.
  - Execution: marketable limit 5bps, 10:00 ET daily, single retry then
    file rec.
  - Operations: broker SOT, DynamoDB fast tier, Iceberg journal,
    reconciliation every 30 min during session.
- **Reading list**: Chan "Algorithmic Trading", Grinold & Kahn "Active
  Portfolio Management" (esp. ch 14-17), Lopez de Prado "Advances in
  Financial Machine Learning".

**From Part E (identifiability, execution, funnel, repo):**

- **Layer 2 is NOT formula-discovery.** Statistical power collapses 2000x
  from L1 (per-symbol-per-day) to L2 (portfolio-rebalance). PySR or any
  symbolic regressor at L2 finds noise. Use **Bayesian optimisation with
  strong priors (Optuna, BoTorch)** over a small structured search space
  of 5-10 hyperparameters.
- **The identifiability problem**: alpha quality and sizing quality are
  jointly unidentifiable from portfolio returns. Aggressive sizing on
  weak signal looks identical to conservative sizing on strong signal in
  backtest. The aggressive-on-weak case is the classic blowup pattern.
- **Layer-isolated attribution fix**: evaluate L1 with sizing-agnostic
  metrics: **IC (Information Coefficient)** = per-day rank correlation
  prediction vs realised; **IR** = IC mean / IC std; **quantile spreads**
  = top-decile minus bottom-decile realised return; **hit rate with
  magnitude weighting**. Evaluate L2 by holding L1 fixed.
- **Brinson attribution**: decompose portfolio P&L into selection (L1)
  vs sizing (L2) vs execution (L3) contributions. Industry standard.
- **What CAN be recursively optimised at L2**: hyperparameters (shrinkage,
  lookback, threshold epsilon, drawdown trigger, vol target); regime
  selection rules; meta-allocation across alpha versions; constraint
  tuning.
- **Walk-forward CV ALWAYS**, never i.i.d. splits in time series.
- **Execution mechanics vs execution policy**: mechanics (API calls,
  order types, retries, state machine) stay boring. Policy (when to
  trade, conditional on what) has real edge but tuned from **live
  telemetry, not backtests** (market impact and microstructure not in
  historical data).
- **TCA (Transaction Cost Analysis) loop**: live execution -> fill
  telemetry -> TCA aggregation -> cost-curve estimates -> Layer 2 cost
  model + Layer 3 policy thresholds. **Cost-aware portfolio construction
  is the bridge** that closes the loop.
- **Execution policy tunables**: liquidity gating (X% of ADV),
  spread gating (Y bps cap), vol-conditional timing (news avoidance),
  time-of-day buckets, order type selection. **Rule-based with tuned
  thresholds, NOT learned formulas.** No neural networks executing trades.
- **Implementation shortfall metric**: `(fill_price - decision_price) *
  sign(side)` in bps, aggregated by (time-of-day, spread quintile, ADV
  quintile, vol regime, side) buckets.
- **Two killer biases**: (1) **selection bias on multiple testing** -
  remedy via **deflated Sharpe ratio (Lopez de Prado)** and **probability
  of backtest overfitting**; (2) **survivorship bias** - every pipeline
  that ever existed must be in evaluation statistics, dead or alive.
- **Four-stage promotion funnel**: research backtest (cheap, 100s,
  walk-forward CV + deflated-Sharpe filter) -> out-of-sample paper (5-10,
  minimum 3 months, simulated fills, same code path as live) -> small
  live (3-5, real money fixed small allocation, minimum 3 months, true
  cost discovery) -> production ensemble (3-5, capital-weighted).
- **Skipping stages is the #1 retail-quant failure mode**. Each stage
  discovers a different class of bug.
- **Pre-registered promotion criteria** (ratified decisions in your CD
  pattern): min duration 3 months, deflated Sharpe > 1.0, max DD < 15%,
  no more than 3 consecutive losing weeks, win-rate / profit-factor
  thresholds. **You cannot override your own past self when recent data
  feels good.**
- **Production ensemble = vol-scaled equal-weight**, rebalanced monthly.
  Each pipeline gets `1/N * (target_vol / realised_vol_of_pipeline)`.
  Resist dynamic/performance-weighted ensembles initially.
- **Concurrent paper trading alongside live** (champion-challenger):
  challengers, sanity checks (paper-vs-live drift = execution-quality
  bug), warmed-up replacement candidates.
- **Five-property optimisability test for every component**:
  parameterised + versioned + composable + observable + evaluable.
  Hardcoded magic numbers fail #1; anonymous functions fail #2; tight
  coupling fails #3; hidden state fails #4; "I'll know it when I see it"
  fails #5.
- **Component-as-versioned-artifact Pydantic schemas** (all Annotated
  with CD.12 DQ markers, all Iceberg tables under the portal):
  `AlphaModelVersion`, `PortfolioConstructionVersion`,
  `ExecutionPolicyVersion`, `StrategyVersion`. A strategy is a
  composition of versioned components, not a monolith.
- **Same-code-path commitment**: backtest and live use identical code;
  only the `BrokerAdapter` Protocol implementation differs
  (`HistoricalSimulationBroker`, `PaperBroker`, `AlpacaBroker`).
  Backtest engine is part of the trading system, not a separate tool.
- **Pure-function discipline at every layer**: `alpha(market_state, params)
  -> Signal`, `construct_portfolio(signal, current_portfolio, params)
  -> TargetPortfolio`, `plan_trades(target, current, params) -> [Order]`.
  No hidden state. Reproducible from logged inputs.
- **Telemetry-as-contract**: `LayerInvocation` schema captures every
  layer invocation with run_id, strategy_version_id, layer name,
  component_version_id, invocation_time, inputs_hash, outputs_hash,
  metrics, duration_ms. Feeds the recursive optimisation loop.
- **Promotion as a typed verb**: `promote_strategy(strategy_id, from_stage,
  to_stage, evaluation_window, capital_allocation) -> PromotionEventId`.
  Criteria checked inline; failures return typed rejection; overrides
  require amending ratified criteria first.
- **Proposed repo layout**: `src/trading/{types,brokers,alpha,
  portfolio_construction,execution,risk,strategy,tca,evaluation}`,
  `scripts/{trade,backtest,tca_report,promote}.py`.
- **What NOT to build in v1**: don't build the recursive optimiser first
  (build one working strategy through the funnel first); don't pre-build
  "every component must be optimisable" before any component works; don't
  optimise the architecture for hypothetical strategies.

**From Part G (hedging, options, environments, contract-driven separation):**

- **Hedging is a Layer-2 constraint**, NOT a new layer. Beta/dollar/
  sector/factor/currency/pairs hedges are linear constraints in the
  optimiser (cvxpy handles natively). Tail hedging is a separate
  "insurance sleeve" outside Layer 2.
- **Hedge vs size-down** is an explicit Layer-2 decision: hedging costs
  money, sizing-down is free. For sole-quant scale and Sharpe profile,
  **default is size-down**. Revisit when factor model is trustworthy
  and Sharpe survives halving from hedging costs.
- **Tail-hedge sleeve** (1-3% of capital in long OTM puts) has BEHAVIORAL
  value (lets you size alpha larger) but expected return is negative; not
  a profit centre.
- **Options is a separate discipline** - 5 Greeks per position (delta,
  gamma, vega, theta, rho) changes Layer 2 from "aggregate weights" to
  "aggregate Greek exposures" and Risk Gates from "max % per name" to
  "max gamma/vega per term, max theta/day, pin risk, assignment risk".
  Defer to post-launch; do NOT extend stock system to options inline.
- **Options architectural extensions** (when added): instrument schema
  with full OCC identifier; pricing model (Black-Scholes / binomial /
  broker mid); per-position Greeks at decision time; portfolio-level
  Greek aggregation; multi-leg execution (verticals, calendars, condors)
  as single orders to avoid leg-risk; expiry state machine
  (close/exercise/assign/expire) with post-expiry reconciliation sweeps.
- **Five environments**: research / backtest-canonical / paper /
  live-small / live-full. Same code path, different broker adapter and
  capital allocation. Environment is a CONFIG BUNDLE, not a deployment.
- **Six environment invariants**: same code path across all envs;
  one-way data flow (prod telemetry -> research; research never writes to
  prod); capital allocation is the production gate; backtest data is
  frozen and survivor-bias-corrected; paper trading uses production
  infrastructure; promotion is a typed action with audit trail.
- **Single AWS account, Pattern C isolation** (IAM + table-prefix).
  Iceberg tables prefixed: `research_strategy_runs`,
  `paper_strategy_runs`, `live_strategy_runs`. Asymmetric IAM (research
  role can READ live but not WRITE). Broker creds in per-env Secrets
  Manager entries.
- **`EnvironmentConfig` Pydantic block (verbatim from transcript)**:
  fields environment, broker_adapter, data_source, capital_allocation,
  table_prefix, iam_role_arn, risk_gate_overrides, promotion_criteria.
- **Deploy-once, configure-per-environment** is the industrial pattern.
- **Telemetry environment-tagged** in one logical table for cross-env
  comparison (paper-vs-live Sharpe / fill drift).
- **What runs continuously vs on-demand**: research = on-demand;
  backtest-canonical = on-demand (triggered by strategy versions / CI);
  paper = continuous, mirrors live trading hours; live-small/full =
  continuous, market hours only.
- **Platform/product separation is contract-driven**. The unit of
  separation is the contract, not the code. PRODUCT consumes PLATFORM
  contracts (Iceberg schemas, typed portal verbs, Lambda Function URLs,
  four-layer trading interfaces, broker adapter Protocol). PLATFORM
  improvements that preserve contracts are transparent.
- **Two-phase pattern**: Phase 1 PLATFORM ships capability under new/
  extended contract (validated by structural correctness, latency,
  observability - NOT P&L); Phase 2 PRODUCT consumes contract in
  separate plan (validated by P&L, Sharpe, drawdown).
- **The diagnostic question** the separation must answer:
  "Strategy v17 underperforms v12 in live. Is the alpha worse? Did PC
  change? Did execution get more expensive? Did a platform component
  change behind a stable contract?" Without layer-versioning and
  contract boundaries this is unanswerable.
- **Cadence differs**: PLATFORM slow + low-risk-tolerance + ratified-
  decision-gated; PRODUCT iterative + higher-risk + promotion-criteria-
  gated. Same person, different mindset, different validation lens.
- **The boundary blurs case**: platform engineering treats product
  engineers as customers. Requirements inform platform design;
  implementation is independent.

**Cross-cutting (synthesise these into YAML `agent_instructions` and `north_star`):**

- The trading system is an EXTENSION of the existing recursive-
  improvement substrate to a new domain, not a new architecture. Every
  pattern the platform has ratified (SCD2 versioning, Single Portal
  writes, Annotated-Pydantic schema, DQ-as-alarm, append-only journaling)
  applies here.
- **Discipline first, optimisation second.** The frontier is reached by
  rigorous structure that admits clever algorithms when statistical
  power justifies them, NOT by clever algorithms applied to broken
  structure.

---

## 4. Subagent fan-out plan

### Step 0 (mandatory, BEFORE any other action)

Run these checks in order. If ANY fails, fix it before proceeding to
preflight reads, subagent fan-out, or edits. Some of these are enforced
at the harness level (`.claude/hooks/never_on_main.py` is a PreToolUse
hook that will block Edit/Write/MultiEdit/NotebookEdit + git
commit/push while on `main`); the rest are auditor responsibility.

1. **Branch check**: `git branch --show-current`. If output is `main`,
   create the working branch:
   `git checkout main && git pull && git checkout -b agent/product-roadmap-yaml-conversion`.
   Confirm with `git branch --show-current` that the working branch is
   active. Do NOT proceed while on `main` - the never-on-main hook
   will block all edits mid-flow and waste Opus subagent tokens.
2. **Validate gate awareness**: confirm you will run
   `bin/venv-python -m scripts.validate` (no flag) for the schema
   check, not `--pre`. Per AGENTS.md, `--pre` is advisory (lint /
   format / prompts only) and does NOT exercise the RoadmapDocument
   validator that gates the PRODUCT YAML.
3. **Lambda-deploy posture**: any tier_item that proposes a Lambda
   carries the `deferred_note: "DEFERRED: build_lambda.py --deploy +
   run_scheduled_agent.py --smoke-test (pending Decision 67 reversal)"`
   field with the AGENTS.md canonical string.
4. **No rec filing**: this audit does NOT call
   `ops_data_portal file_rec`. PLATFORM gaps accumulate in the gap
   YAML (Section 5.3) for user review.
5. **Pre-Wave-1 ask-user gates** (Section 10) - resolve BEFORE
   dispatching Wave 1, not after synthesis. Ask-the-user costs nothing
   compared to a wrong-shape Wave 1 fan-out.

Deploy subagents IN PARALLEL where they have no dependencies. Use
`Agent` tool calls in a single message for parallel wave dispatch.

**Model override**: pass `model: "opus"` on every Agent call. The user
has explicitly authorised liberal Opus subagent use; depth matters more
than cost here.

**Subagent type**: use `general-purpose` for synthesis tasks (A, B, D, F),
and `Explore` for pure read-and-catalogue tasks (C, E) if appropriate.
`general-purpose` is the safe default if you are unsure.

**Self-containment**: each subagent has NO view of this prompt or any
prior context. Brief them like a smart colleague who just walked in -
state the goal, name the files, list the deliverables, give the output
format. Include the PIVOT TRANSCRIPT verbatim in any subagent brief that
needs it (D and F). Do NOT include this entire prompt; only the parts the
subagent needs.

**Trust but verify**: when a subagent returns, spot-check at least one
non-trivial claim against the source file before accepting it into
synthesis. For PLATFORM ID references specifically, do not stop at
one - run a programmatic resolution check (see Section 7's
"definition of done") that greps every `PLATFORM:` token in the draft
YAML against `docs/ROADMAP-PLATFORM.yaml`.

### Section 4A. What the auditor decides vs what the prompt decides

Three categories of content. Knowing which is which is the difference
between an audit that produces a faithful YAML and one that imports
prompt errors as design choices.

**Category 1 - DESIGN COMMITMENTS the prompt encodes; the auditor must
carry them through faithfully, not re-decide.** The user has already
ratified these via the pivot transcript and this prompt. The auditor's
job is to encode them correctly, not to choose differently. Examples:

- The four-layer model is Alpha / PC / Execution / Operations-Telemetry
  (per PIVOT Part C diagram). L4 is NOT Risk Gates. Risk gates live as
  L2 constraints + L3 pre-trade hooks.
- The three-tier data architecture is Broker (OLTP) / DynamoDB (fast
  tier) / Iceberg lakehouse (append-only).
- The five environments are research / backtest-canonical / paper /
  live-small / live-full, with the same code path and only the broker
  adapter differing.
- Contract-driven platform/product separation, with cross-roadmap
  deps as typed edges.
- The pre-codegen contract-ratification ritual (CD.25) gates product
  schemas; product Iceberg tables are Class A; broker / Protocol
  interfaces are Class C; product Lambdas are Class B.
- Gap-YAML for PLATFORM additions, not direct rec filings.
- The MVP v1 composition surface (alpha = formula-score top-N; PC =
  equal-weight or risk-parity over top-N with constraints + threshold
  rebalance + hard drawdown circuit breaker; execution = marketable-
  limit + daily mid-morning + single retry; ops = broker SOT +
  DynamoDB fast tier + Iceberg journal + 30-min reconciliation). The
  auditor populates `composition_ref` + `contract_refs` to the
  versioned artefact, but does NOT change the composition's
  structural shape - the user already ratified the v1 prescription
  via PIVOT Part C.
- The four-stage funnel (research_backtest -> out_of_sample_paper ->
  live_small -> live_full -> production_ensemble) with stage-gated
  promotion. Skipping stages is forbidden.

The auditor must NOT silently demote, rename, or restructure these.
If the prompt's encoding is found to be wrong (Subagent G surfaces a
schema fit issue, or a critique finds an internal contradiction), the
auditor surfaces the conflict to the user via `AskUserQuestion` and
waits for resolution; the auditor does NOT improvise a fix.

**Category 2 - MECHANISM RULES the prompt declares; non-negotiable
implementation discipline.** Examples:

- `bin/venv-python` invocation, not `python` / `python3`.
- Branch is `agent/product-roadmap-yaml-conversion`, never edit on `main`.
- Full presubmit (`validate.py`, no flags) is the authoritative gate;
  `--pre` is advisory.
- Single Portal Invariant for ops writes.
- No emojis, no em dashes; plain ASCII hyphens.
- No STRATEGIC plans (CD.17 freeze); only IMPLEMENTATION or REPORT-ONLY.
- Lambda-touching items carry the canonical `deferred_note` string per
  AGENTS.md (verbatim "(pending Decision 67 reversal)" ending).
- Contract gates carry `{path, class, contract_version}` triples, not
  bare paths.
- `D.fast.*` and `D.lake.*` items carry `owning_layer` to preserve
  strategy_version_id lineage to the layer that owns writes.
- Five-property optimisability test (parameterised / versioned /
  composable / observable / evaluable) is REQUIRED on every L1-L4
  tier_item. Each property attestation cites a `path:line` or a
  tier_item id - bare prose fails verification.
- Promotion criteria thresholds live in
  `docs/contracts/promotion-criteria.yaml` (Class A), NEVER as YAML
  scalars in this roadmap.
- Every product-domain Iceberg row carries `strategy_version_id`
  lineage.
- Per-row `_contract_version` stamping where the contract is Class A.

Same posture as Category 1: surface conflicts, do not improvise.

**Category 3 - CONTENT DECISIONS the auditor makes, drawing on subagent
outputs and the pivot transcript.** This is where judgment lives.
Examples:

- Which candidate CDPs (Section 5.1's commented list) become ratified
  CDPs vs roll into `open_design_questions[]` vs become `known_gaps[]`.
- The exact `intent`, `exit_criteria`, `effort`, `status` for each
  tier_item.
- The IDs the auditor uses for tier_items (the sketch suggests
  groupings: L1.alpha.*, L2.pc.*, L3.exec.*, L4.ops.*, D.fast.*,
  D.lake.*, E.env.*, MVP.* - but specific item IDs and their counts
  come from the audit).
- Which Subagent C catalogued items become tier_items vs
  `retired_items[]` vs `known_gaps[]`.
- Which gates in the candidate slot list (Section 5.1's
  `cross_tier_gates` comment) become actual gates, and their rule
  strings (constrained by Subagent G's gate_helpers extension).
- Cross-roadmap dependency edges per item.
- Contract-gate paths and classes per item.
- The audit report's open_questions for the user.
- The gap YAML's entries.

For Category 3, the auditor uses judgment freely - that is the audit's
purpose. The prompt provides STRUCTURE; the auditor provides CONTENT.

**Anti-pattern**: treating a Category 3 surface as if it were a
Category 1 commitment ("the prompt's sketch had CDP.13 about
reconciliation, so I'll keep CDP.13 verbatim") - the sketch's CDP
titles are CANDIDATE titles to ratify, not pre-decided CDPs.
**Inverse anti-pattern**: treating a Category 1 commitment as if it
were a Category 3 choice ("L4 = Risk Gates seems reasonable so I'll
keep it") - the user already decided L4 = Operations/Telemetry, and
the auditor is not authorised to relitigate.

### Wave 1 (parallel - dispatch all six in a single message)

#### Subagent A: PLATFORM-SUMMARISER

**Brief**:
> Read `/home/user/agent-platform/docs/ROADMAP-PLATFORM.yaml`
> (2,205 lines) in full, plus
> `/home/user/agent-platform/scripts/platform_roadmap.py`
> (391 lines, the RoadmapDocument Pydantic validator).
>
> Produce a structured summary with:
> 1. Top-level YAML key list with one-line semantics for each
>    (`document`, `north_star`, `cost_projection`, ...).
> 2. Verbatim shapes (field names + types + required/optional) of:
>    `DocumentMeta`, `TierItem`, `CandidateDecision`, `CrossTierGate`,
>    `OpenQuestion`, `KnownGap`, `NorthStarPrinciple`, `NorthStar`,
>    `FoundationItem`, `RoadmapDocument`. Cite the Pydantic source.
> 3. The `model_config = ConfigDict(extra="ignore")` posture on every
>    model and what it implies for adding new fields.
> 4. Full inventory of `candidate_decisions[]`: `(id, title, gates, state)`
>    tuples. The PRODUCT YAML may need to reference these by id.
> 5. Full inventory of `tier_items[]`: `(id, tier, name, status, effort,
>    one-sentence intent)` tuples. The PRODUCT YAML will reference
>    individual tier items as cross-roadmap dependencies.
> 6. The `gate_helpers` mini-language grammar verbatim, including every
>    helper's name, arity, params, returns, semantics.
> 7. Examples of `cross_tier_gates[]` entries verbatim - so the PRODUCT
>    YAML can reuse the rule-grammar.
> 8. The `agent_instructions` block verbatim - the PRODUCT YAML needs
>    its own analogous block.
> 9. The bootstrap-clause language verbatim.
> 10. Specifically: which PLATFORM tier_items already mention or are
>    structurally about (a) Iceberg table schemas, (b) telemetry, (c)
>    Lambda dispatchers, (d) IAM / Terraform substrate, (e) the
>    log-decision Lambda, (f) Pydantic schemas, (g) the executor pipeline,
>    (h) broker / trading interfaces. List them as `(id, one-line-why)`
>    so they can be candidate cross-roadmap dependency targets.
>
> Output: **YAML, not markdown** - Wave 1.5 Step 1 must mechanically
> resolve PLATFORM ids from A's output, which requires structured form.
> Required schema:
>
> ```yaml
> top_level_keys:
>   - name: document
>     semantics: "..."
>   # ... one per top-level key
>
> pydantic_shapes:
>   DocumentMeta:
>     fields: [...]
>     required: [...]
>     optional: [...]
>     extra_posture: ignore
>     source_lines: "scripts/platform_roadmap.py:91-114"
>   # ... TierItem, CandidateDecision, CrossTierGate, OpenQuestion,
>   # KnownGap, NorthStarPrinciple, NorthStar, FoundationItem,
>   # RoadmapDocument
>
> candidate_decisions_inventory:
>   - id: CD.1
>     title: "..."
>     gates: [...]
>     state: pending | ratified
>   # ... one per CD
>
> tier_items_inventory:
>   - id: T0.1
>     tier: T0
>     name: "..."
>     status: not_started | in_progress | complete | reserved
>     effort: XS | S | M | L | XL
>     intent: "..."
>   # ... one per tier_item
>
> gate_helpers_grammar:
>   - name: tier_complete
>     arity: 1
>     params: [{name: tier_name, type: str}]
>     returns: bool
>     semantics: "..."
>   # ... all PLATFORM helpers verbatim
>
> cross_tier_gate_examples:
>   - rule: "..."
>     description: "..."
>   # 2-3 examples
>
> agent_instructions_block: |
>   <verbatim copy of PLATFORM's document.agent_instructions>
>
> bootstrap_clause: |
>   <verbatim>
>
> cross_roadmap_candidate_targets:
>   - id: T0.12
>     why: "Pydantic schema substrate"
>     category: pydantic_schemas
>   # ... one per item the PRODUCT YAML might depend on
> ```
>
> Estimated output size: ~600-1000 lines of YAML. Committed at
> `docs/audit-reports/wave-1-outputs/A.yaml`.

#### Subagent B: CONTRACT-RATIFICATION-EXTRACTOR

**Brief**:
> Read `/home/user/agent-platform/docs/INTENT-pre-codegen-contract-ratification.md`
> (1,472 lines) in full. Also read the existing example contracts:
> `/home/user/agent-platform/docs/contracts/inference-provider.md`,
> `.../ops-data-store.md`,
> `.../instruction-architecture.md`.
>
> Produce a structured summary with:
> 1. Verbatim definitions of Class A, Class B, Class C contracts with
>    their examples and non-examples.
> 2. The list of canonical projections of a contract: Pydantic model,
>    Athena DDL, DQ YAML, prose docs - and which is the source of truth
>    (the contract YAML itself).
> 3. The semantic-evolution problem and the
>    `_contract_version` + `semantic_break` remedy verbatim.
> 4. CD.25's full description, gates, and current state.
> 5. The CD.16 vs CD.17 split and how each affects PRODUCT-tier work.
> 6. The shape of an existing `docs/contracts/{name}.{md|yaml}` file -
>    quote ~50 lines of `inference-provider.md` so the PRODUCT YAML
>    can propose new contract files with realistic structure.
> 7. **Mapping table**: for each product artefact below, classify as
>    Class A / B / C, propose a `docs/contracts/{slug}.yaml` path, AND
>    propose a starting `contract_version` integer (typically `1` for
>    a fresh contract; cite if a different version is implied by an
>    existing schema). Output rows MUST be `{path, class,
>    contract_version, rationale}` quadruples - do NOT emit
>    `{path, class, rationale}` triples; downstream consumers (Subagent F
>    and the auditor's tier_items) require the version to populate
>    `contract_gates: [{path, class, contract_version}]` per INTENT-pre-
>    codegen-contract-ratification.md Invariants 1+2. Use the broader
>    pivot's surface:
>    - **L1 Alpha**: Signal payload; AlphaModelVersion; alpha() interface.
>    - **L2 Portfolio Construction**: TargetPortfolio payload;
>      PortfolioConstructionVersion; construct_portfolio() interface;
>      Constraint set; CostCurve (consumed from PLATFORM TCA).
>    - **L3 Execution**: BrokerAdapter Protocol (typing.Protocol);
>      Order; Fill; ExecutionPolicyVersion; plan_trades() interface;
>      implementation-shortfall payload.
>    - **L4 Operations/Telemetry**: LayerInvocation event payload;
>      Brinson attribution record; deflated-Sharpe / PBO computation
>      schemas; promotion-events record. NOTE: per PIVOT Part C, L4 is
>      Operations/Telemetry; risk gates do NOT live at L4. Risk gate
>      surfaces (GateDecision, risk-gate parameters, circuit-breaker
>      state) belong as L2 constraint-set entries and L3 pre-trade
>      hooks - classify them under L2/L3 not L4.
>    - **DynamoDB tier**: orders table, positions_cache table,
>      features_serving table. Each has a write-side contract and a
>      conditional-write state machine.
>    - **Iceberg tier** (all Class A, all need contract YAMLs):
>      ops_trade_events, ops_reconciliations, strategies_versions,
>      alpha_versions, pc_versions, exec_versions, strategy_runs,
>      signals, target_portfolios, fills, pnl_attribution (view; may
>      not need DDL contract), tca_events, promotion_events.
>    - **Telemetry**: LayerInvocation event schema.
>    - **Env infra**: EnvironmentConfig (Class C, local); PromotionCriteria
>      (Class C, ratified as decisions).
>    - **Deferred (options)**: instrument schema with OCC identifier,
>      Greek aggregation payload, multi-leg order payload, expiry-state
>      payload. Flag all as PIVOT-DEFERRED.
> 8. The pre-codegen ratification ritual steps (the new
>    tier_items it adds to PLATFORM - T-1.12 and others).
> 9. Any explicit guidance in the INTENT about how PRODUCT-tier
>    contracts should be authored.
>
> Output: **YAML**. The contract-classification mapping table (task 7
> above) MUST be machine-loadable. Required schema:
>
> ```yaml
> class_definitions:
>   class_a: "[verbatim from INTENT]"
>   class_b: "[verbatim]"
>   class_c: "[verbatim]"
> projections:
>   pydantic_model: "..."
>   athena_ddl: "..."
>   dq_yaml: "..."
>   prose_docs: "..."
>   source_of_truth: "docs/contracts/{slug}.yaml"
> semantic_evolution:
>   contract_version_column: "[verbatim]"
>   semantic_break_flag: "[verbatim]"
>   forward_compat_default: "[verbatim]"
> cd_25_summary: "..."
> cd_16_vs_cd_17_split: "..."
> contract_yaml_example: |
>   [~50 lines from inference-provider.md]
> contract_mapping:
>   # Required quadruples, NOT triples - downstream consumers populate
>   # `contract_gates: [{path, class, contract_version}]` per INTENT
>   # Invariants 1+2.
>   - artefact: Signal payload (L1 alpha output)
>     class: A  # if persisted to signals Iceberg
>     proposed_path: docs/contracts/signal-payload.yaml
>     proposed_contract_version: 1
>     rationale: "Persisted to signals Iceberg table; Class A per CD.25."
>   - artefact: AlphaModelVersion
>     class: A
>     proposed_path: docs/contracts/alpha-versions.yaml
>     proposed_contract_version: 1
>     rationale: "SCD2 Iceberg catalogue of alpha versions."
>   # ... one row per artefact in the per-layer surface
> ratification_ritual_steps: [...]
> intent_guidance_on_product_authoring: |
>   [verbatim quotes from INTENT relevant to product-tier contracts]
> ```
>
> Estimated output size: ~800-1200 lines of YAML.

#### Subagent C: PRODUCT-ROADMAP-CATALOGUER

**Brief**:
> Read `/home/user/agent-platform/docs/ROADMAP-PRODUCT.md`
> (843 lines) in full.
>
> Produce a complete inventory with NO information loss. For every
> Phase / Wave / Phase-Infra / Post-Launch section, list:
> 1. Phase name + status marker (COMPLETE / in progress / planned).
> 2. Every deliverable bullet, verbatim, with `[x]` / `[ ]` state.
> 3. Every acceptance criterion verbatim.
> 4. Every limitation listed under "Current State".
> 5. Every Terraform change called out.
> 6. Every schema (target state) table verbatim.
> 7. Every workflow YAML / pseudocode block (just identify and
>    summarise their purpose - do not copy huge blocks).
> 8. Critical Path block verbatim.
> 9. Risk Mitigation block verbatim.
> 10. Post-Launch (Phase 8+) bullets verbatim.
>
> For EACH deliverable / phase, classify as one of:
> - **PIVOT-ALIGNED-LAYER**: maps to a layer in the four-layer model
>   (Alpha / Portfolio Construction / Execution / Operations-Telemetry).
>   NOTE: L4 is Operations/Telemetry per PIVOT Part C, NOT Risk Gates.
>   Risk-gate code (pre-trade gates, circuit breakers, drawdown logic)
>   classifies under L2 or L3, not L4. Name
>   the layer.
> - **PIVOT-ALIGNED-INFRA**: pre-pivot infrastructure that the pivot
>   still requires (market-data pipeline, formula discovery, A/B
>   testing framework, environment infra, monitoring).
> - **PIVOT-ORTHOGONAL**: tooling not covered by the four-layer model
>   but not superseded either.
> - **PIVOT-SUPERSEDED**: contradicts the pivot's guidance or is replaced
>   by a different mechanism (e.g., "manual formula deployment" is
>   superseded by the contract-ratification ritual + promotion config).
> - **PIVOT-DEFERRED**: belongs in post-launch or a later phase under
>   the pivot's deferral logic (e.g., options trading).
>
> Output: **YAML, not markdown**. Per AGENTS.md agent-first principle,
> the auditor consumes this output mechanically to populate
> tier_items / retired_items / known_gaps. Required schema:
>
> ```yaml
> catalogue:
>   - source_section: "Phase 1 / Core Infrastructure"   # markdown heading
>     status_marker: COMPLETE | IN_PROGRESS | PLANNED   # from the heading or context
>     deliverables:
>       - text: "Split S3 into 3 buckets: formulas-discovery, formulas-staging, formulas-production"
>         state: done | open                            # from [x] / [ ]
>         classification: PIVOT_ALIGNED_LAYER | PIVOT_ALIGNED_INFRA | PIVOT_ORTHOGONAL | PIVOT_SUPERSEDED | PIVOT_DEFERRED
>         layer: alpha | portfolio_construction | execution | operations_telemetry | platform_infra | lab_offline | env_infra  # if classification == PIVOT_ALIGNED_LAYER
>         rationale: "[one-sentence why this classification]"
>     acceptance_criteria:
>       - "criterion verbatim"
>     terraform_changes: [...]
>     schemas: [...]
>     # ... other section content
>   # ... more sections
> critical_path: "[verbatim]"
> risk_mitigation: "[verbatim]"
> post_launch_bullets: [...]
> ```
>
> Sub-clause granularity: if a deliverable bullet contains multiple
> distinct concerns separated by commas, "and"/"plus", semicolons,
> or other conjunctions (e.g. "monitoring, alerting, and KPI
> dashboards"), enumerate each phrase as a separate row so the
> Checkpoint-3 completeness check operates at phrase level. Each
> sub-clause row carries a `source_bullet_id: int` so Checkpoint 3
> can verify that bullets containing conjunctions were correctly
> expanded (N rows per source bullet, N matching the number of
> distinct concerns the auditor would count by hand).
>
> Worked example - the source bullet "Add monitoring, alerting,
> and KPI dashboards [x]" expands to three rows:
>
> ```yaml
> deliverables:
>   - text: "Add monitoring"
>     source_bullet_id: 47
>     state: done
>     classification: PIVOT_ALIGNED_INFRA
>     layer: null
>     rationale: "monitoring is platform-infra observability"
>   - text: "Add alerting"
>     source_bullet_id: 47
>     state: done
>     classification: PIVOT_ALIGNED_INFRA
>     layer: null
>     rationale: "alerting is platform-infra"
>   - text: "Add KPI dashboards"
>     source_bullet_id: 47
>     state: done
>     classification: PIVOT_ALIGNED_LAYER
>     layer: operations_telemetry
>     rationale: "KPI dashboards are an L4 observability surface"
> ```
>
> Estimated output size: 5000-7000 lines of YAML (large but
> mechanically loadable; the auditor selects keys via Read
> offset/limit during synthesis - do NOT Read the full file into
> context).
>
> The PIVOT TRANSCRIPT is required reading for this subagent. Do NOT
> inline-paste it into this brief (transcription-error / silent-truncation
> risk). The auditor MUST derive offset/limit dynamically (hardcoded
> values are fragile - they drift every time the prompt is edited):
>
> ```bash
> SECTION_START=$(rg -n '^## 11\. PIVOT TRANSCRIPT' \
>   /home/user/agent-platform/docs/AUDIT-PROMPT-product-roadmap-yaml.md \
>   | cut -d: -f1)
> SECTION_END=$(rg -n '^## 12\. End of prompt' \
>   /home/user/agent-platform/docs/AUDIT-PROMPT-product-roadmap-yaml.md \
>   | cut -d: -f1)
> LIMIT=$((SECTION_END - SECTION_START - 1))
> ```
>
> Then dispatch the subagent with a Read invocation bound to those
> exact values (substitute $SECTION_START for offset and $LIMIT for
> limit when composing the subagent's brief). Reject any subagent
> output that suggests it read fewer than 90% of $LIMIT lines.
> Section 11 spans Parts A through G; all are load-bearing.

#### Subagent D: TRADING-PIVOT-DELTA-ANALYSER

**Brief**:
> You are given a verbatim conversation about trading-system architecture
> (the PIVOT TRANSCRIPT - all seven Parts A-G). Distil it into a
> structured rule-set the YAML can embed. Be thorough; the transcript
> is dense and load-bearing for the new product roadmap.
>
> Produce a structured report with sections corresponding to Parts A-G:
>
> **From Part A (data architecture):**
> 1. **Three-tier data architecture** verbatim: broker (OLTP source of
>    truth) - DynamoDB (fast tier) - Iceberg/DuckDB (lakehouse). Reproduce
>    the ASCII diagram.
> 2. **DynamoDB-vs-Postgres rationale** - the six bullets verbatim.
> 3. **DynamoDB tables proposed**: `orders` (PK, write pattern),
>    `positions_cache`, `features_serving` (one-way projection rule).
> 4. **The decision loop write-path** - the 7-step ordered sequence
>    verbatim.
> 5. **Order state machine** DAG and where enforcement lives (broker /
>    DynamoDB conditional / app code).
> 6. **"What to not do" rules** - six bullets verbatim (no synchronous
>    Iceberg writes from hot path; no lakehouse-as-position-store; no
>    hand-rolled concurrency; reconciliation non-negotiable; no live
>    market data in Iceberg real-time; no premature Kafka/Kinesis).
> 7. **Tables/components table** verbatim (orders, positions_cache,
>    features_serving, ops_trade_events, ops_reconciliations,
>    ops_recommendations).
> 8. **When to revisit DynamoDB-vs-Postgres** - 3 trigger conditions.
>
> **From Part C (four-layer mental model):**
> 9. **Four-layer model**: for each layer (Alpha, Portfolio Construction,
>    Execution, Operations/Telemetry):
>    - Name and one-sentence responsibility
>    - Inputs / outputs
>    - Function-level interface verbatim (`alpha(market_state, params)
>      -> Signal`, etc.)
>    - "Variables that don't go into formulas" mapping per layer.
> 10. **Layer 2 sub-problems (a-e) verbatim**:
>     - (a) Position sizing - seven choices from equal-weight to
>       Black-Litterman with the v1 recommendation.
>     - (b) Risk model - three options with the recommendation.
>     - (c) Constraints - seven types.
>     - (d) Turnover control - four approaches with v1 recommendation.
>     - (e) Drawdown - three philosophies with the recommendation
>       ("Hard circuit breaker. Non-negotiable.").
> 11. **Layer 3 execution boring-correct** prescription verbatim:
>     order type, timing, frequency, slicing, retries.
> 12. **The trade-on-open-vs-close decision** verbatim.
> 13. **Three populations of parameters** table verbatim (alpha /
>     strategy / operational) and how each is tuned.
> 14. **Frontier per layer** verbatim - 4 bullets.
> 15. **Realistic sole-dev target** verbatim - L1 frontier, L2 mid-
>     tier, L3 boring, L4 frontier.
> 16. **Minimum viable v1 prescription verbatim** - alpha, PC,
>     execution, operations bullets. Include all numbers.
> 17. **Reading list** - 3 books in order.
>
> **From Part E (identifiability + execution + funnel + repo):**
> 18. **Identifiability problem** verbatim and the layer-isolated
>     attribution fix (IC, IR, quantile spreads, hit rate, Brinson
>     attribution).
> 19. **What CAN be recursively optimised at Layer 2** - hyperparameters,
>     regime selection, meta-allocation, constraint tuning. Note the
>     **walk-forward-CV-only** rule.
> 20. **Execution mechanics vs execution policy** distinction verbatim.
> 21. **TCA loop diagram**: live execution -> fill telemetry -> TCA
>     aggregation -> cost curves -> L2 cost model + L3 thresholds.
> 22. **Implementation shortfall metric** formula and bucketing
>     (time-of-day, spread quintile, ADV quintile, vol regime, side).
> 23. **Execution policy tunables** - liquidity gating, spread gating,
>     vol-conditional timing, time-of-day buckets, order type
>     selection. **Rule-based with tuned thresholds, NOT learned
>     formulas** (no NN executing trades).
> 24. **Two killer biases** - selection bias on multiple testing
>     (deflated Sharpe + PBO remedy); survivorship bias (every
>     pipeline dead-or-alive in stats).
> 25. **Four-stage funnel** ASCII diagram verbatim with population
>     sizes per stage.
> 26. **Pre-registered promotion criteria** verbatim - min duration,
>     deflated Sharpe, max DD, consecutive losing weeks, win rate /
>     profit factor.
> 27. **Production ensemble**: vol-scaled equal-weight,
>     `1/N * (target_vol/realised_vol)` formula, monthly rebalance,
>     reasons-to-resist-dynamic-weighting.
> 28. **Concurrent paper trading** (champion-challenger framework).
> 29. **Five-property optimisability test** - the five properties
>     and what fails each.
> 30. **Component-as-versioned-artifact Pydantic blocks**: quote the
>     four BaseModel classes verbatim (AlphaModelVersion,
>     PortfolioConstructionVersion, ExecutionPolicyVersion,
>     StrategyVersion).
> 31. **Tables-to-add table** verbatim from Part E.
> 32. **Same-code-path commitment**: BrokerAdapter Protocol verbatim
>     with simulation / paper / Alpaca subclasses.
> 33. **Pure-function discipline**: the three function signatures
>     verbatim.
> 34. **LayerInvocation telemetry-as-contract** Pydantic block verbatim.
> 35. **promote_strategy() typed verb** signature verbatim.
> 36. **Proposed repo layout** verbatim from Part E.
> 37. **What NOT to do in v1** - three rules verbatim.
> 38. **How this composes with existing system** - 5 bullets verbatim.
>
> **From Part G (hedging, options, environments, separation):**
> 39. **Hedging decision matrix** verbatim (seven hedge types table).
> 40. **Hedge-vs-size-down** rules verbatim. For sole-quant scale,
>     default size-down. Tail-hedge sleeve is behavioural.
> 41. **Options architectural extensions** verbatim - 7 bullets.
> 42. **Environment taxonomy** table verbatim.
> 43. **Six environment invariants** verbatim.
> 44. **Three isolation patterns** (A/B/C) and selection of Pattern C
>     with the rationale.
> 45. **`EnvironmentConfig` Pydantic** verbatim.
> 46. **Telemetry-environment-tagged SQL** example verbatim.
> 47. **Platform/product separation** rules:
>     - Contracts are the unit of separation.
>     - Transparent vs breaking platform changes (the table verbatim).
>     - Two-phase pattern.
>     - Cadence / validation-lens differences (the table verbatim).
> 48. **Cost-aware portfolio construction walkthrough** verbatim - this
>     is the concrete two-phase pattern example.
> 49. **The diagnostic question** (strategy v17 vs v12) verbatim.
> 50. **Direct quotes suitable for `agent_instructions` and
>     `north_star.principles[].statement`** - 10-15 of the most load-
>     bearing sentences from the full transcript.
>
> Output: **YAML, not markdown**. 50 keyed entries (one per task above),
> consumed mechanically by the auditor during synthesis. Required
> schema:
>
> ```yaml
> trading_pivot_extraction:
>   - task_id: 1
>     pivot_part: A  # one of A, B, C, D, E, F, G
>     title: "Three-tier data architecture verbatim"
>     content: |
>       [verbatim extract from PIVOT Section 11 - preserve transcript
>       phrasing; if a quote, mark with quote markers]
>     intended_yaml_target: three_tier_data_architecture  # name the
>                                                          # PRODUCT YAML
>                                                          # block this
>                                                          # populates
>     load_bearing: true | false
>     notes: "[any caveats]"
>   - task_id: 2
>     pivot_part: A
>     title: "DynamoDB-vs-Postgres rationale - the six bullets verbatim"
>     content: |
>       1. [...]
>       2. [...]
>       ...
>     intended_yaml_target: candidate_decisions (DynamoDB-not-RDS detail)
>     load_bearing: true
>   # ... 48 more
> ```
>
> Estimated output size: ~3000-5000 lines of YAML.
>
> PIVOT TRANSCRIPT - do NOT inline-paste (transcription-error risk).
> The auditor MUST derive offset/limit dynamically per the same grep
> recipe used for Subagent C (see Subagent C brief above):
>
> ```bash
> SECTION_START=$(rg -n '^## 11\. PIVOT TRANSCRIPT' .../AUDIT-PROMPT-product-roadmap-yaml.md | cut -d: -f1)
> SECTION_END=$(rg -n '^## 12\. End of prompt' .../AUDIT-PROMPT-product-roadmap-yaml.md | cut -d: -f1)
> LIMIT=$((SECTION_END - SECTION_START - 1))
> ```
>
> Dispatch with offset=$SECTION_START, limit=$LIMIT. Parts A through G
> are all load-bearing; reject any subagent output that suggests
> truncation at < 90% of $LIMIT.

#### Subagent E: CODE-SURFACE-AUDITOR

**Brief**:
> Audit the `/home/user/agent-platform/src/` tree to produce
> a code-grounded current-state baseline for the product YAML's
> `current_state` block.
>
> Scope (read these files in full):
> - `src/main.py`
> - `src/live/rat_ensemble.py`
> - `src/execution/async_engine.py`
> - `src/meta_learner/gating_network.py`
> - `src/data/pipeline.py`
> - `src/data/feature_engine.py`
> - `src/data/writer.py`
> - `src/data/universe.py`
> - `src/data/yfinance_provider.py`
> - `src/data/provider_base.py`
> - `src/data/handlers/fetch_handler.py`
> - `src/data/handlers/feature_handler.py`
> - `src/data/handlers/write_handler.py`
> - `src/data/handlers/maintenance_handler.py`
> - `src/data/handlers/scheduled_agent_handler.py`
> - `src/lab/pysr_factory.py`
> - `src/schemas/decision.py`
> - `src/schemas/rec.py`
> - `src/schemas/annotations.py`
> - `src/common/config.py`
> - `src/common/database.py`
>
> For each file, produce:
> 1. Public classes and top-level functions with their signatures
>    (no internals).
> 2. Cite as `path:line` for every signature.
> 3. Classify the file under one of:
>    - LAYER 1 (Alpha)
>    - LAYER 2 (Portfolio Construction)
>    - LAYER 3 (Execution)
>    - LAYER 4 (Operations/Telemetry - per PIVOT Part C; code that
>      emits LayerInvocation events, computes Brinson attribution,
>      deflated Sharpe, PBO, or feeds the recursive improvement loop)
>    - RISK SUBLAYER (NOT a fourth layer per pivot - code that
>      implements pre-trade gates, circuit breakers, hedging
>      constraints, drawdown logic. Classifies under L2 if it lives
>      in portfolio-construction as a constraint, or under L3 if it
>      lives in execution as a pre-submit gate. Cite which.)
>    - PLATFORM-INFRA (data pipeline, schemas, config)
>    - LAB / OFFLINE (formula discovery)
>    - UNCLEAR (flag)
> 4. Whether the file is production code, partial stub, or scaffold.
>    Cite `TODO`, `NotImplementedError`, `pass`, or sparse logic as
>    evidence.
>
> Also determine, for each surface below, whether code exists. Treat
> each as an OPEN QUESTION until evidence is gathered; do not assume
> the answer either way. Cite the grep command, the files inspected,
> and any matched signatures (with `path:line`) in the report.
> Surfaces to check:
> - `EnvironmentConfig` Pydantic (or any analogous per-env config schema)
> - Broker adapter `Protocol` (or any analogous typing.Protocol for brokers)
> - Portfolio-construction optimisation code (any solver / cvxpy /
>   Optuna usage, any sizing-method registry)
> - Pre-trade gate / kill-switch / circuit-breaker code
> - TCA / cost-curve aggregation
> - Per-env table-prefix logic (research_*, paper_*, live_*)
> - Position cache / DynamoDB orders-table client code
> - Reconciliation loop code
> - Backtest engine separate from live engine (a violation per the
>   same-code-path commitment)
> - Three-place state machine (broker / DynamoDB-conditional / app code)
>
> Required grep coverage (use ripgrep `rg` or `grep -nr`):
> ```
> rg -n "class \w*Environment|class \w*Broker|class \w*Adapter" src/ scripts/
> rg -n "Protocol" src/ scripts/
> rg -n "cost_curve|CostCurve|tca|TCA|implementation_shortfall" src/ scripts/
> rg -n "circuit_breaker|drawdown|kill_switch" src/ scripts/
> rg -n "portfolio_construction|risk_parity|equal_weight|black_litterman" src/ scripts/
> rg -n "reconcil" src/ scripts/
> rg -n "dynamo|DynamoDB|boto3.resource\('dynamodb'\)" src/ scripts/
> rg -n "table_prefix|research_|paper_|live_" src/ scripts/
> rg -n "client_order_id|ClientOrderId" src/ scripts/
> ```
> Report any missed surface explicitly as "no matches found" with the
> command run. Do NOT report a surface as "missing" without showing the
> grep evidence.
>
> Output as a single structured markdown report, ~2000-3000 words,
> with a code-surface table at the top and a "missing" enumeration at
> the bottom. Reference every claim by `path:line`.

#### Subagent G: SCHEMA-FIT-AUDITOR (yes, G is in Wave 1; F is in Wave 2)

**Brief**:
> Determine the minimal schema delta the PRODUCT YAML needs versus
> the existing `RoadmapDocument` Pydantic schema, given the new
> requirement that PRODUCT items can depend on PLATFORM items
> (cross-roadmap dependencies).
>
> Scope (read in full):
> - `/home/user/agent-platform/scripts/platform_roadmap.py`
>   (391 lines)
> - The `document` block and one example each of `tier_items[]`,
>   `candidate_decisions[]`, `cross_tier_gates[]` in
>   `docs/ROADMAP-PLATFORM.yaml`
>
> Produce:
> 1. The exact `RoadmapDocument` Pydantic shape today (all field types,
>    `extra="ignore"` posture confirmed).
> 2. A proposal for cross-roadmap dependency encoding. Compare options:
>    - **Option 1**: per-item field `cross_roadmap_depends_on:
>      [PLATFORM:T0.12, PLATFORM:CD.25]`. Pros: localised; cons: parser
>      change.
>    - **Option 2**: top-level `cross_roadmap_dependencies:` block with
>      `(product_id, platform_id, kind, rationale)` tuples. Pros: aggregable;
>      cons: redundant with `depends_on`.
>    - **Option 3**: extend `depends_on` to accept prefixed ids
>      (`PLATFORM:T0.12` vs bare `L2.pc.3`). Pros: minimal schema change;
>      cons: dependency graph parser needs prefix awareness.
>    Recommend one (with rationale).
> 3. Other proposed PRODUCT-specific fields per `tier_items[]`:
>    - `layer: alpha | portfolio_construction | execution |
>      operations_telemetry | platform_infra | lab_offline | env_infra` -
>      the four-layer classification surface. NOTE: L4 is
>      OPERATIONS/TELEMETRY per PIVOT Part C, NOT "risk gates". Risk
>      gates live as L2 constraints (in `contains_risk_constraints`)
>      and L3 pre-trade hooks (in `contains_pretrade_gates`).
>    - `owning_layer: alpha | portfolio_construction | execution |
>      operations_telemetry` - REQUIRED on `D.fast.*` and `D.lake.*`
>      items (physical-storage items). Recovers strategy_version_id
>      lineage to the layer that owns writes (orders -> L3, signals ->
>      L1, target_portfolios -> L2, fills -> L3, etc.).
>    - `environment_scope: [research, backtest, paper, live_small,
>      live_full]`.
>    - `contract_gates: [{path, class, contract_version}]` - NOT a
>      plain path list. INTENT-pre-codegen-contract-ratification.md
>      Invariants 1+2 mandate versioned references. A plain
>      `[docs/contracts/foo.yaml]` form silently loses the version,
>      defeating the semantic-evolution mechanism.
>    - `validation_lens: structural | pnl | both`.
>    - `five_property_test:` block (parameterised / versioned /
>      composable / observable / evaluable - each a short prose
>      attestation) on L1-L4 items per the optimisability CDP.
>    - `deferred: bool` + `deferred_note: str` (the canonical
>      AGENTS.md string when Lambda-deploy is gated by Decision 67).
>    Justify each.
> 4. Top-level fields the PRODUCT YAML needs that PLATFORM does not:
>    - `four_layer_model:` block (canonical layer definitions, NOT
>      item-side).
>    - `three_tier_data_architecture:` block (broker / DynamoDB / lakehouse).
>    - `environments:` block defining the five envs.
>    - `evaluation_metrics:` block with per-layer sizing-agnostic
>      metrics.
>    - `minimum_viable_v1:` block referencing a versioned
>      `docs/contracts/minimum-viable-v1.yaml` artefact (NOT inline
>      scalars).
>    - `promotion_funnel:` block referencing per-stage criteria contracts.
>    - `retired_items[]:` block.
> 5. **Gate-helper grammar extension** - REQUIRED additional output.
>    PLATFORM's `scripts/platform_roadmap.py` defines `_GATE_HELPERS`
>    (the table of helper names + arities) and `GateRuleParser` will
>    reject any `cross_tier_gates[].rule` that invokes an undeclared
>    helper. PRODUCT YAML's gate rules will need helpers PLATFORM does
>    NOT have (e.g. `deflated_sharpe(strategy_id, env, window)`,
>    `max_drawdown(...)`, `consecutive_losing_weeks(...)`,
>    `implementation_shortfall_within_budget(...)`,
>    `ic_oos(alpha_version_id)`, `ir_oos(...)`,
>    `code_path_hash(env, strategy_version_id)`,
>    `live_full_uptime_days(...)`,
>    `consecutive_quarters_positive_sharpe(...)`,
>    `all_contract_gates_ratified(item)`, etc.). For EACH new helper
>    the PRODUCT YAML's gates will use:
>    - Name and arity
>    - Parameter types
>    - Return type
>    - Semantics (one sentence)
>    - Athena query template or in-Python evaluator (since some helpers
>      require warehouse queries, not in-YAML reasoning)
>    - Whether it belongs in `document.gate_helpers` of PRODUCT.yaml
>      (PRODUCT-local) or proposed as a PLATFORM extension (added to
>      PLATFORM's `_GATE_HELPERS` via a gap-YAML entry).
>    - If `code_path_hash` cannot be defined concretely, propose
>      demoting the same-code-path gate to
>      `code_path_verification_present_for(strategy_version_id)` and
>      file a separate tier_item to author the runtime-recording
>      mechanism.
>    Output a concrete `gate_helpers:` block ready to copy into PRODUCT
>    YAML.
> 6. Schema-class decision:
>    - (a) the SAME `RoadmapDocument` schema with optional fields added
>      to `TierItem`. CONCERN: `extra="ignore"` silently drops new
>      fields - validates green but the data is invisible to any
>      downstream Python loader. Recommend ONLY if Subagent G can show
>      that no automated reader of PRODUCT YAML exists / is planned.
>    - (b) a NEW `ProductRoadmapDocument` Pydantic schema in
>      `scripts/product_roadmap.py` with required fields explicit.
>    - (c) a unified `RoadmapDocument` with a `kind:
>      platform | product` discriminator and conditionally-required
>      fields.
>    Recommend one. Default recommendation: (b), to avoid the
>    silent-drop risk.
> 7. Concrete schema delta: write out the proposed Pydantic class
>    additions as code (no need to commit them - just propose).
>
> Output: **YAML, not markdown** - Wave 1.5 Step 3 must mechanically
> grep helper names from G's output, which requires structured form.
> Required schema:
>
> ```yaml
> roadmap_document_current_shape:
>   document_meta: "<verbatim Pydantic source>"
>   tier_item: "<verbatim>"
>   candidate_decision: "<verbatim>"
>   cross_tier_gate: "<verbatim>"
>   roadmap_document: "<verbatim>"
>   extra_posture: ignore | forbid | allow
>   silent_drop_risk_notes: "..."
>
> cross_roadmap_dep_encoding_options:
>   - option: 1
>     name: per_item_cross_roadmap_depends_on
>     pros: [...]
>     cons: [...]
>   # ... options 2, 3
>   recommended: 1 | 2 | 3
>   recommended_rationale: "..."
>
> tier_item_field_additions:
>   - field: layer
>     type: "Literal['alpha', 'portfolio_construction', 'execution', 'operations_telemetry', 'platform_infra', 'lab_offline', 'env_infra']"
>     required: true
>     rationale: "..."
>   # ... other fields (owning_layer, environment_scope, contract_gates,
>   # validation_lens, five_property_test, deferred, deferred_note)
>
> top_level_field_additions:
>   - field: four_layer_model
>     rationale: "..."
>   # ... three_tier_data_architecture, environments, evaluation_metrics,
>   # minimum_viable_v1, promotion_funnel, retired_items,
>   # candidate_decisions_research_pool
>
> gate_helpers_extension:
>   - name: deflated_sharpe
>     arity: 3
>     params:
>       - {name: strategy_id, type: str}
>       - {name: env, type: str}
>       - {name: window_days, type: int}
>     returns: float
>     semantics: "Lopez de Prado deflated Sharpe over window for strategy in env."
>     athena_query_template: "SELECT deflated_sharpe(...) FROM strategy_runs WHERE ..."
>     scope: product_local | platform_extension
>   # ... one entry per helper PRODUCT YAML's cross_tier_gates will use
>   # (max_drawdown, consecutive_losing_weeks, implementation_shortfall_within_budget,
>   # ic_oos, ir_oos, code_path_hash OR code_path_verification_present_for,
>   # live_full_uptime_days, consecutive_quarters_positive_sharpe,
>   # all_contract_gates_ratified)
>
> schema_class_decision:
>   recommended: a | b | c
>   recommended_rationale: "..."
>   schema_delta_code: |
>     # Pydantic class additions, ready to commit
>     class ProductRoadmapDocument(BaseModel):
>         ...
> ```
>
> Estimated output size: ~500-800 lines of YAML. Committed at
> `docs/audit-reports/wave-1-outputs/G.yaml`.

### Wave 1.5 (auditor solo - blocking gate between Wave 1 and Wave 2)

After Wave 1 returns and BEFORE briefing Subagent F (Wave 2), the
auditor runs three blocking validation steps. These are NOT critique
subagents - they are mechanical checks the auditor performs against
Wave 1 outputs to catch hallucinations before they propagate into F's
input (and through F into the YAML).

**Step 1: Programmatic PLATFORM-id resolution**

Subagent A returned an inventory of PLATFORM tier_item and CD ids.
Verify every id Subagent A claims exists actually exists in
`docs/ROADMAP-PLATFORM.yaml`:

```bash
# extract claimed ids from A's YAML output via Python (more robust
# than grep against potentially-multi-format content)
bin/venv-python -c "
import yaml, sys
data = yaml.safe_load(open('docs/audit-reports/wave-1-outputs/A.yaml'))
ids = set()
for ti in data.get('tier_items_inventory', []):
    ids.add(ti['id'])
for cd in data.get('candidate_decisions_inventory', []):
    ids.add(cd['id'])
for line in sys.stdin:
    print(line.rstrip())
" < /dev/null > /tmp/a-ids.txt
# Then grep PLATFORM YAML for each
for id in $(cat /tmp/a-ids.txt); do
  rg -q "id: $id\$" docs/ROADMAP-PLATFORM.yaml \
    || echo "HALLUCINATED PLATFORM ID in A's output: $id"
done
```

Any `HALLUCINATED PLATFORM ID` output means Subagent A invented an id.
The auditor either re-runs A with corrective context OR flags the
hallucinated id and proceeds (rare; usually re-running is cheaper).

**Step 2: Draft the tier_item id list**

Subagent F's brief requires "a draft list of ~20-40 tier_item ids
with names and intents." The auditor authors this list HERE,
synthesising from Subagent A (PLATFORM dependency targets), Subagent
C (existing PRODUCT.md deliverables to carry forward), Subagent D
(four-layer / three-tier surfaces), and Subagent E (existing code
surfaces).

Output: a YAML file at
`docs/audit-reports/wave-1.5-tier-items-draft.yaml`:

```yaml
draft_tier_items:
  - id: L1.alpha.1
    name: "[short imperative]"
    intent: "[one-paragraph rationale drawing on Subagent D + E]"
  # ... 20-40 rows
```

Commit this file BEFORE briefing Subagent F. F will consume it.

**Step 3: Helper-grammar pre-check**

Subagent G returned a `gate_helpers:` extension block. The auditor
greps PLATFORM's `_GATE_HELPERS` table to confirm none of G's proposed
helpers collide with existing names:

```bash
rg "^    - name: " docs/ROADMAP-PLATFORM.yaml | sort -u
# compare against G's gate_helpers block; flag any name collision
```

Name collisions force G to either rename or scope the helper as
PRODUCT-local.

### Wave 2 (sequenced after Wave 1 + Wave 1.5; dispatch alone)

#### Subagent F: CROSS-ROADMAP-DEPENDENCY-MAPPER

**Brief**:
> You consume the following committed Wave-1 outputs (the auditor's
> brief includes their paths so you can Read them; do NOT inline-paste).
> Extensions per Section 5.6 directory layout: structured YAML content
> uses `.yaml`; prose narrative uses `.md`.
>
> - `docs/audit-reports/wave-1-outputs/A.yaml` (PLATFORM inventory:
>   tier_item ids, CD ids, gate_helpers grammar - YAML)
> - `docs/audit-reports/wave-1-outputs/B.yaml` (contract classification
>   quadruples: `{path, class, contract_version, rationale}` - YAML)
> - `docs/audit-reports/wave-1-outputs/C.yaml` (PRODUCT.md catalogue
>   with per-deliverable classification - YAML; REQUIRED - the legacy
>   PRODUCT.md surface is the substrate for `retired_items[]` and any
>   cross-roadmap edges on legacy items)
> - `docs/audit-reports/wave-1-outputs/D.yaml` (50 keyed pivot
>   extractions - YAML)
> - `docs/audit-reports/wave-1-outputs/E.md` (code-surface audit - prose
>   with `path:line` citations; markdown)
> - `docs/audit-reports/wave-1-outputs/G.yaml` (schema-fit + gate_helpers
>   extension + pydantic delta - YAML)
> - `docs/audit-reports/wave-1.5-tier-items-draft.yaml` (the auditor's
>   draft tier_item id list: ~20-40 entries with name + intent)
>
> Produce the cross-roadmap dependency map by joining the draft
> tier_items list against PLATFORM ids and contract paths.
>
> Output format: YAML, NOT markdown table (per agent-first repo
> commitment - downstream consumers read this mechanically). Each row
> is a YAML mapping:
>
> ```yaml
> - product_id: L1.alpha.1
>   name: Wire RAT ensemble to four-layer interface
>   platform_depends_on: [PLATFORM:T0.12, PLATFORM:CD.12]
>   contract_gates:
>     - path: docs/contracts/signal-payload.yaml
>       class: C
>       contract_version: 1
>   rationale: Alpha layer emits Signal; Signal payload must be ratified before persistence.
> - product_id: L3.exec.1
>   name: Broker adapter Protocol
>   platform_depends_on: [PLATFORM:CD.25]
>   contract_gates:
>     - path: docs/contracts/broker-adapter.yaml
>       class: C
>       contract_version: 1
>   rationale: Protocol interface ratified pre-codegen per CD.25. Class may become A if Protocol payloads later persisted.
> - product_id: E.env.1
>   name: EnvironmentConfig Pydantic
>   platform_depends_on: [PLATFORM:T0.12]
>   contract_gates: []
>   rationale: Local Pydantic, Class C, in-process only; no DDL.
> - product_id: L2.pc.5
>   name: Cost-aware portfolio construction
>   platform_depends_on: [PLATFORM:GAP-TCA-aggregation]
>   contract_gates:
>     - path: docs/contracts/cost-curve.yaml
>       class: A
>       contract_version: 1
>   rationale: Requires TCA aggregation in PLATFORM; flag GAP.
> ```
>
> For each row:
> - **platform_depends_on**: list PLATFORM tier_item ids and CD ids by
>   id (never by name). Use Subagent A's inventory as the source. If
>   the dependency does NOT exist in PLATFORM today, flag as
>   `PLATFORM:GAP-{slug}` and explain what PLATFORM needs to add.
> - **contract_gates**: list of `{path, class, contract_version}`
>   mappings per Subagent B's quadruple output (NEVER as a
>   "path (Class X)" string - downstream `tier_items[].contract_gates`
>   needs the structured form per INTENT-pre-codegen-contract-
>   ratification.md Invariants 1+2).
> - **rationale**: one sentence why this dependency exists.
>
> Also produce a "PLATFORM additions needed" section enumerating every
> `PLATFORM:GAP-*` flagged in the table, with proposed PLATFORM-side
> tier_items. These flow into
> `docs/audit-reports/PRODUCT-ROADMAP-PLATFORM-GAPS.yaml` (Section 5.3
> of the audit prompt), NOT into ops_data_portal `file_rec`. The user
> reviews the gap YAML with a follow-up agent before any rec is filed.
>
> Output: YAML (see schema above; NOT markdown). Estimated size:
> ~1500-2500 lines. Committed at
> `docs/audit-reports/wave-2-output-F.yaml`.

### Wave 3 (you, alone - the synthesis step)

After Wave 1 + Wave 2 return, you (the auditor) do the synthesis. Do
not delegate this. Specifically:

1. **Spot-check** at least one claim from each subagent against the
   actual source file. Subagent summaries describe what the subagent
   intended to do, not necessarily what they verified.
2. **Draft `docs/ROADMAP-PRODUCT.yaml`** per Section 5 of this prompt.
3. **Draft `docs/audit-reports/AUDIT-product-roadmap-yaml-conversion.yaml`**
   per Section 5.2 of this prompt (YAML, NOT markdown - canonical
   storage form per AGENTS.md agent-first principle). Create the
   `docs/audit-reports/` directory if needed.
4. **Validate** with `bin/venv-python -m scripts.validate`. If
   the existing `RoadmapDocument` schema rejects PRODUCT YAML (likely,
   because `extra="ignore"` silently drops unknowns but graph-validation
   may fail on PRODUCT ids), document the schema-extension work needed
   as a follow-up `tier_item` rather than patching the validator inline.
5. **Add banner to legacy markdown**: edit `docs/ROADMAP-PRODUCT.md` to
   prepend a banner pointing at the YAML.
6. **Commit on branch** with message:
   `roadmap-product: convert to YAML, organise around four-layer model`.
   Push to remote per AGENTS.md (`git push -u origin <branch>` with
   exponential backoff retry on network failure).

---

## 5. Output deliverables

### 5.1 `docs/ROADMAP-PRODUCT.yaml`

Top-level shape (extend the PLATFORM YAML structure with PRODUCT-specific
fields per Subagent G's schema delta):

```yaml
document:
  id: ROADMAP-PRODUCT
  version: 1
  status: draft
  filed_via: pending_log_decision_lambda
  description: |
    Canonical product roadmap for the recursively-self-improving trading
    system. Sibling to docs/ROADMAP-PLATFORM.yaml. Organised around the
    four-layer trading model (Alpha / Portfolio Construction / Execution
    / Operations-Telemetry) and environment-as-config (research / backtest /
    paper / live-small / live-full). Supersedes docs/ROADMAP-PRODUCT.md.
  agent_instructions: |
    [analogous to PLATFORM's block, with rules covering: four-layer
    organisation, cross-roadmap depends_on syntax (PLATFORM:T0.12),
    layer field, environment_scope, contract_gates, validation lens
    (P&L not structural), promotion-via-config rule, contract
    ratification gate per CD.25, options as PIVOT-DEFERRED.]

four_layer_model:
  # TAXONOMY NOTE: per PIVOT TRANSCRIPT Part C (Section 11), the four
  # layers are Alpha -> Portfolio Construction -> Execution ->
  # Operations/Telemetry. Risk gates are NOT a fourth layer; they are
  # (a) constraints inside L2 (hedging-as-constraint, max position,
  # sector caps, gross/net exposure - encoded in construct_portfolio's
  # `constraints` argument) and (b) pre-trade hooks inside L3 (margin
  # check, position-cache check, circuit-breaker query - encoded in
  # plan_trades' early-exit path). Sketch shape only - auditor
  # populates from Subagent D.
  - layer: alpha
    name: Alpha
    responsibility: "[populated from PIVOT Part C verbatim]"
    interface: "alpha(market_state, params) -> Signal"
    inputs: "[populated from Subagent D]"
    outputs: "[populated from Subagent D]"
    contract_refs: "[populated from Subagent B contract mapping]"
  - layer: portfolio_construction
    name: Portfolio Construction
    responsibility: "[populated from PIVOT Part C verbatim]"
    interface: "construct(signals, current_portfolio, constraints) -> TargetPortfolio"
    inputs: "[populated from Subagent D]"
    outputs: "[populated from Subagent D]"
    contract_refs: "[populated from Subagent B]"
    contains_risk_constraints: true  # hedging, sizing, exposure caps live here
    notes: "[populated from PIVOT Part G hedging-as-constraint quote]"
  - layer: execution
    name: Execution
    responsibility: "[populated from PIVOT Part C verbatim]"
    interface: "plan_trades(target, current, params) -> [Order]"
    inputs: "[populated from Subagent D]"
    outputs: "[populated from Subagent D]"
    contract_refs: "[populated from Subagent B]"
    contains_pretrade_gates: true  # margin/position/circuit-breaker checks live here
  - layer: operations_telemetry
    name: Operations / Telemetry / Feedback
    responsibility: "[populated from PIVOT Part C verbatim - the layer that captures every invocation and feeds the recursive improvement loop]"
    interface: "LayerInvocation event emission per layer invocation"
    inputs: "[populated from Subagent D]"
    outputs: "[populated from Subagent D - LayerInvocation, TCA, Brinson attribution]"
    contract_refs: "[populated from Subagent B - includes layer-invocation.yaml, tca-events.yaml, promotion-events.yaml]"
    notes: |
      Per PIVOT Part C diagram, L4 = OPERATIONS / TELEMETRY / FEEDBACK,
      NOT Risk Gates. The diagnostic question framing (PIVOT Part G:
      "Did the alpha-version change? Did the PC-version change? Did
      the exec-version change?") assumes L4 = telemetry that observes
      L1-L3 versioned components.

environments:
  - env: research
    code: pre_merge
    data: production_historical_readonly
    broker_adapter: none
    capital: none
    telemetry_destination: research_sandbox
  - env: backtest_canonical
    code: merged_versioned
    data: frozen_canonical
    broker_adapter: simulation
    capital: notional
    telemetry_destination: backtest_results_table
  - env: paper
    code: merged_versioned
    data: realtime_market
    broker_adapter: paper_broker
    capital: notional
    telemetry_destination: production_telemetry_tagged
  - env: live_small
    code: merged_versioned
    data: realtime_market
    broker_adapter: live_broker
    capital: small_allocation
    telemetry_destination: production_telemetry
  - env: live_full
    code: merged_versioned
    data: realtime_market
    broker_adapter: live_broker
    capital: full_allocation
    telemetry_destination: production_telemetry

three_tier_data_architecture:
  - tier: broker_oltp
    name: Broker (OLTP source of truth)
    description: |
      The broker (IBKR / Alpaca / etc.) is the authoritative system of
      record for orders, positions, cash, fills. Our system is a client,
      not the source of truth. ACID is the broker's problem.
    examples: [interactive_brokers, alpaca]
    write_authority: external
    contract_refs: [docs/contracts/broker-adapter.yaml]
  - tier: fast_tier
    name: DynamoDB fast tier (sub-ms mutable cache)
    description: |
      Small mutable state outside the Single Portal Invariant because it
      is a derivative projection of the warehouse, not a write source.
      Conditional writes provide the OLTP primitives we actually need.
    tables:
      - name: orders
        pk: client_order_id
        write_pattern: PutItem with attribute_not_exists; UpdateItem with conditional state-machine guards
        contract_ref: docs/contracts/dynamodb-orders.yaml
      - name: positions_cache
        pk: symbol
        write_pattern: refresh from broker on schedule + after fills via cross-item transactions
        contract_ref: docs/contracts/dynamodb-positions-cache.yaml
      - name: features_serving
        pk: symbol
        write_pattern: ONE-WAY projection from Iceberg via nightly batch job; live loop is read-only
        contract_ref: docs/contracts/dynamodb-features-serving.yaml
    rationale_for_dynamodb_not_postgres: |
      Single-writer; AWS-serverless-native; already in stack; key-value
      query patterns; <$1/mo on-demand; conditional writes cover 95% of
      Postgres' transactional semantics for this workload.
  - tier: lakehouse
    name: Lakehouse (S3 + Iceberg + DuckDB, append-only)
    description: |
      Append-only journal for audit, research, market-data history.
      Single Portal Invariant applies. Hot path writes via buffered
      writer or SQS -> Lambda batch-append; never synchronous from
      decision loop.
    tables:
      - ops_trade_events
      - ops_reconciliations
      - strategies_versions
      - alpha_versions
      - pc_versions
      - exec_versions
      - strategy_runs
      - signals
      - target_portfolios
      - fills
      - pnl_attribution
      - tca_events
      - promotion_events
      - ops_recommendations  # EXTENDED, not new - drift events from
                             # the reconciliation loop route here via
                             # the existing portal flow (PIVOT Part A
                             # tables/components table)
    write_hot_path_rule: NEVER synchronous; use buffered writer or SQS+Lambda batching
    write_market_data_rule: WebSocket -> in-memory ring buffer for decisions; batch-write every ~1 minute for history

evaluation_metrics:
  layer_1_alpha:
    - name: ic
      description: Information Coefficient - per-day rank correlation between predicted and realized returns
      sizing_dependent: false
    - name: ir
      description: Information Ratio of the signal - IC mean / IC std (signal stability over time)
      sizing_dependent: false
    - name: quantile_spread
      description: Top-decile minus bottom-decile realized return
      sizing_dependent: false
    - name: hit_rate_magnitude_weighted
      description: Fraction of correct direction predictions weighted by realized magnitude
      sizing_dependent: false
    - name: signal_decay_half_life
      description: Time horizon over which the alpha's IC decays to half its initial value; captures the "how fast does the alpha go stale" dimension that IC averages obscure
      sizing_dependent: false
    - name: alpha_pairwise_ic_correlation
      description: Pairwise IC correlation between alpha versions; per PIVOT Part C frontier framing, the L1 orthogonality target ("100+ orthogonal alpha signals") is sizing-agnostic and a load-bearing L1 metric
      sizing_dependent: false
  layer_2_portfolio_construction:
    - name: brinson_attribution_sizing
      description: P&L attributed to sizing decisions holding alpha fixed
      sizing_dependent: true
    - name: turnover_adjusted_sharpe
      description: Sharpe net of explicit transaction costs
      sizing_dependent: true
  layer_3_execution:
    - name: implementation_shortfall
      description: (fill_price - decision_price) * sign(side), in bps; bucketed by time-of-day, spread quintile, ADV quintile, vol regime, side
      sizing_dependent: true
    - name: slippage_vs_expected
      description: realized minus modeled slippage per bucket
      sizing_dependent: true
  layer_4_operations_telemetry:
    # `role:` distinguishes attribution-surface metrics (decompose P&L
    # to debug "what changed") from observability-surface metrics
    # (process coverage of the recursive improvement loop) from
    # drift-detector metrics (cross-env or broker-vs-cache divergence).
    # Future agents query by role mechanically.
    - name: layer_invocation_coverage
      description: Fraction of L1/L2/L3 invocations that successfully emit a LayerInvocation event; gates the recursive improvement loop
      sizing_dependent: false
      role: observability
      pivot_provenance: auditor_synthesis_from_layer_invocation_schema  # PIVOT Part E names LayerInvocation; coverage is auditor-derived
    - name: brinson_full_attribution
      description: Per-strategy-version P&L decomposed across selection (L1) / sizing (L2) / execution (L3) / residual; the diagnostic surface for "did the alpha change vs PC change vs exec change"
      sizing_dependent: true
      role: attribution
      pivot_provenance: verbatim_part_c_and_part_e
    - name: paper_vs_live_divergence
      description: For the same strategy_version_id running in both paper and live, the gap in fill prices / Sharpe / drawdown - the execution-quality drift detector
      sizing_dependent: true
      role: drift_detector
      pivot_provenance: verbatim_part_g
    - name: reconciliation_drift_rate
      description: Frequency and magnitude of broker-vs-DynamoDB position-cache divergence events
      sizing_dependent: false
      role: drift_detector
      pivot_provenance: verbatim_part_a
  portfolio:
    - name: deflated_sharpe
      description: Lopez de Prado deflated Sharpe correcting for selection bias on multiple testing
    - name: probability_of_backtest_overfitting
      description: PBO check
    - name: max_drawdown
    - name: profit_factor
    - name: consecutive_losing_weeks

minimum_viable_v1:
  # CRITICAL: per the five-property optimisability test (a candidate CDP
  # the auditor will ratify from PIVOT Part E), every component is
  # parameterised + versioned. Hardcoded magic numbers fail #1
  # ("Parameterised - explicit, typed inputs"). The MVP v1 prescription
  # MUST therefore be expressed as a REFERENCE to a versioned artefact,
  # not as YAML scalars in this file. Inline numbers in this file are
  # the anti-pattern.
  description: |
    Name the v1 composition. The actual numeric parameters
    (top_n, max_position_weight, rebalance_threshold_epsilon,
    drawdown_circuit_breaker.{lookback_days, drawdown_threshold,
    cash_days}, cash_buffer_min, spread_aggression_bps, submit_time,
    retry_policy, reconciliation_cadence_minutes) live inside the
    versioned PortfolioConstructionVersion / ExecutionPolicyVersion
    artefacts named below, NEVER as YAML scalars in this roadmap.
  composition_ref:
    strategy_version_id: "[auditor populates - e.g. mvp_v1@<hash>]"
    alpha_version_ref: "[auditor populates - e.g. formula_score_top_n@<hash>]"
    pc_version_ref: "[auditor populates - e.g. equal_weight_top_n_v1@<hash> OR risk_parity_top_n_v1@<hash>]"
    exec_version_ref: "[auditor populates - e.g. marketable_limit_v1@<hash>]"
    risk_constraints_ref: "[populated from L2 constraint set (including drawdown circuit breaker per PIVOT Part C - constraint, NOT L4 surface) + L3 pre-trade gate hooks. L4 is Operations/Telemetry; circuit breakers are L2 constraints.]"
    environment_config_ref: "[per-stage EnvironmentConfig instance reference]"
  contract_refs:
    - path: docs/contracts/minimum-viable-v1.yaml
      class: A  # ratified composition, persisted to strategies_versions Iceberg table
      contract_version: 1
      contains: |
        - alpha.top_n (PIVOT Part C: "Top-N ranking, N=20" as DEFAULT, tunable)
        - portfolio_construction.method (PIVOT Part C: equal_weight_top_n OR risk_parity_top_n)
        - portfolio_construction.max_position_weight
        - portfolio_construction.gross_exposure_max
        - portfolio_construction.rebalance.{policy, epsilon}
        - portfolio_construction.drawdown_circuit_breaker.{lookback_days, drawdown_threshold, cash_days}
        - portfolio_construction.cash_buffer_min
        - execution.order_type
        - execution.spread_aggression_bps
        - execution.submit_time
        - execution.retry_policy
        - operations.reconciliation_cadence_minutes
        # Default numbers from PIVOT Part C "Minimum viable trading
        # system, opinionated" block live INSIDE this contract file
        # (auditored in the contract-ratification ritual, NOT inline
        # here). They become tunable hyperparameters under
        # Bayesian-opt (a candidate CDP) once L1 alpha is validated
        # live.
  pivot_quote_reference: "PIVOT Section 11 Part C - 'Minimum viable trading system, opinionated' block. Auditor cites verbatim in docs/contracts/minimum-viable-v1.yaml when authoring that contract in a follow-up plan."

promotion_funnel:
  # CRITICAL: same discipline as `minimum_viable_v1`. Promotion criteria
  # NUMBERS (deflated_sharpe thresholds, max_drawdown ceilings,
  # min_duration_days, consecutive_losing_weeks caps) live inside a
  # ratified Class A contract at docs/contracts/promotion-criteria.yaml,
  # NEVER as YAML scalars in this roadmap. Inline scalars would let a
  # future PR change "deflated_sharpe >= 1.0" to "deflated_sharpe >= 0.5"
  # without ratification - defeating the pre-registration discipline that
  # is the entire point of the funnel.
  description: |
    Four-stage funnel with pre-registered promotion criteria. Skipping
    stages is the #1 retail-quant failure mode; each stage discovers a
    different class of bug. Stage criteria themselves are versioned
    Class A contracts (per CD.25), not inline scalars.
  criteria_ref:
    path: docs/contracts/promotion-criteria.yaml
    class: A  # ratified criteria, persisted to ops_decisions + promotion_events
    contract_version: 1
    contains: |
      Per-stage promotion criteria (numeric thresholds), drawn verbatim
      from PIVOT Part E "Promotion criteria, pre-registered" block:
        - research_backtest -> out_of_sample_paper:
            walk_forward_cv_passed; deflated_sharpe filter threshold;
            probability_of_backtest_overfitting check.
        - out_of_sample_paper -> live_small:
            min_duration_days; deflated_sharpe_threshold;
            max_drawdown_threshold; consecutive_losing_weeks_cap;
            same_code_path_verified; survivorship_inclusive_stats_required.
        - live_small -> live_full:
            min_duration_days; deflated_sharpe_threshold;
            max_drawdown_threshold;
            implementation_shortfall_within_budget;
            survivorship_inclusive_stats_required.
        - production_ensemble:
            ensemble_weighting (vol_scaled_equal_weight);
            rebalance_cadence; weight formula.
      Threshold numbers (e.g. "deflated_sharpe >= 1.0", "max_drawdown
      <= 0.15", "consecutive_losing_weeks <= 3", "min_duration_days =
      90") authored verbatim inside the contract YAML, NOT here.
  pivot_quote_reference: "PIVOT Section 11 Part E - 'Promotion criteria, pre-registered' block. Auditor cites verbatim in docs/contracts/promotion-criteria.yaml in a follow-up plan."
  stages:
    # Structural shape only - thresholds in the contract, not here.
    - stage: research_backtest
      population_size: hundreds
      data: frozen_canonical
      broker_adapter: simulation
      criteria_contract: docs/contracts/promotion-criteria.yaml#research_backtest_to_paper
    - stage: out_of_sample_paper
      population_size: 5_to_10
      data: realtime_market
      broker_adapter: paper_broker
      criteria_contract: docs/contracts/promotion-criteria.yaml#paper_to_live_small
    - stage: live_small
      population_size: 3_to_5
      data: realtime_market
      broker_adapter: live_broker
      capital: small_allocation
      purpose: true_cost_discovery
      criteria_contract: docs/contracts/promotion-criteria.yaml#live_small_to_live_full
    - stage: production_ensemble
      population_size: 3_to_5
      criteria_contract: docs/contracts/promotion-criteria.yaml#ensemble_weighting
  concurrent_paper_alongside_live: true
  champion_challenger: true

north_star:
  [analogous to PLATFORM's north_star, but stating: a live
  trading system whose layer-versioned strategies are observed,
  promoted-by-config, and improved-by-evidence, with each layer
  testable in isolation and across environments. Principles drawn
  from Subagent D quotes.]

current_state:
  [grounded in Subagent E's code-surface audit. Reference code by
  path:line. Distinguish "working" from "limitations" honestly.]

candidate_decisions:
  # SKETCH NOTE: only CDP.1 and CDP.2 are mandatory (CDP.1 = "adopt this
  # roadmap as canonical"; CDP.2 = "four-layer model is the organising
  # principle"). All others below are CANDIDATE TITLES the auditor MAY
  # ratify after reading Subagent D's extraction. Subagent D produces a
  # ranked list of candidate CDPs from PIVOT transcript Parts A-G; the
  # auditor decides which become CDPs, which roll into open_design_questions,
  # and which become known_gaps. Do NOT carry the suggested IDs below
  # forward without re-ratification - they exist only to show what
  # surface area is plausibly CDP-worthy.
  - id: CDP.1
    title: Adopt this product roadmap as canonical
    detail: "[populated by auditor - structure: succinct rule + supersession claim]"
    gates: [L0]
    state: pending
  - id: CDP.2
    title: Four-layer trading model is the organising principle
    detail: "[populated by auditor from PIVOT Part C diagram, naming L1/L2/L3/L4 = Alpha/PC/Exec/Operations-Telemetry; risk lives inside L2 constraints + L3 pre-trade gate]"
    gates: [L1, L2, L3, L4]
    state: pending

  # ---- Candidate CDPs the auditor may ratify (titles only; no detail). ----
  # The auditor MUST read PIVOT Section 11 Parts A-G via Subagent D and
  # decide which of these to lift into CDPs. Author the `detail` block as
  # a verbatim quote or tight paraphrase from the transcript, NOT from
  # this sketch's text. If a candidate below is NOT supported by the
  # transcript, drop it. If the transcript surfaces a load-bearing
  # commitment NOT below, add it.
  #
  # NOTE: the list below is in YAML COMMENTS, which are stripped on
  # `yaml.safe_load()`. Downstream agents that load PRODUCT.yaml will
  # NOT see this list. The list survives ONLY as audit substrate for
  # the auditor's reading of the prompt. Additionally, the auditor
  # MUST author a parallel `candidate_decisions_research_pool:`
  # top-level block (see schema below) so the candidates survive YAML
  # round-trips and are mechanically iterable. Without that block, an
  # agent loading PRODUCT.yaml has no view of "what was considered and
  # left for follow-up vs what was ratified."
  #
  # candidate titles (auditor extends/prunes):
  #   - Layer 2 and Layer 3 quality dominate Layer 1 quality at retail
  #     scale (Renaissance Medallion framing - PIVOT Part C: "execution
  #     quality and risk discipline matter more than signal quality")
  #   - Lakehouse is never a position store; DynamoDB fast tier carries
  #     "current state", Iceberg is append-only history (one of PIVOT
  #     Part A's six "what to not do" bullets)
  #   - ops_recommendations is extended (not replaced) for trading
  #     drift events; reconciliation drift -> critical rec via the
  #     existing portal (PIVOT Part A tables/components table)
  #   - Hedging is a Layer-2 constraint; default to size-down
  #   - Tail-hedge sleeve is a behavioural instrument (not edge)
  #   - Options trading deferred to post-MVP
  #   - Environments are config bundles, not deployments
  #   - Single-account AWS, Pattern C isolation
  #   - Promotion is a config change (capital allocation gate)
  #   - Platform/product separation is contract-driven
  #   - Broker is the OLTP source of truth (not Postgres/Aurora)
  #   - DynamoDB is the fast tier (not RDS)
  #   - Iceberg/DuckDB stays append-only for audit/research
  #   - DynamoDB cross-item transactions for order+position-cache
  #     (do not hand-roll concurrency)
  #   - Three-place state machine: broker -> DynamoDB conditional -> app
  #   - No synchronous Iceberg writes from hot path; buffered or SQS+Lambda
  #   - No premature Kafka/Kinesis at single-agent volume
  #   - Reconciliation every N minutes is non-negotiable
  #   - L1 evaluation is sizing-agnostic (IC, IR, quantile spread,
  #     hit-rate, signal-decay, alpha-pairwise-correlation)
  #   - L2 is Bayesian-opt hyperparameter tuning, NOT formula discovery
  #   - Full Kelly sizing is forbidden; only fractional Kelly
  #   - Vanilla MVO is unstable; use only cost-aware MVO or Black-Litterman
  #   - Pipeline is the unit of optimisation; alpha-only optimisation is
  #     not promotable
  #   - Same code path for backtest/paper/live; only broker adapter differs
  #   - Trade-on-open-vs-close decision: backtest mirrors live
  #   - All layers are pure functions over versioned inputs
  #   - Every component passes the five-property optimisability test
  #   - Marketable-limit orders only at L3; pure market orders forbidden
  #     on illiquid names
  #   - L3 execution policies are rule-based with tuned thresholds;
  #     neural-network execution is forbidden at retail scale
  #   - All product-domain Iceberg rows carry strategy_version_id lineage
  #   - Production ensemble is vol-scaled equal-weight, monthly rebalance
  #   - Four-stage promotion funnel with pre-registered criteria
  #   - Statistical hygiene: deflated Sharpe + PBO + survivorship-inclusive stats
  #   - Promotion is a typed verb with criteria-check baked in
  #   - Promotion criteria are themselves a ratified contract
  #     (docs/contracts/promotion-criteria.yaml Class A)
  #   - TCA loop closes L2 cost model + L3 policy thresholds
  #   - Hard drawdown circuit breaker (non-negotiable)
  #   - Multi-leg options orders submitted as single broker tickets
  #     (no legging in)
  #   - Backtest canonical dataset is immutable, versioned,
  #     survivor-bias-corrected
  #   - Asymmetric research<-prod IAM (research reads prod telemetry;
  #     never writes prod tables)
  #   - "What the auditor decides vs what the prompt decides" - see
  #     Section 4A. The auditor MUST NOT lift any candidate above into a
  #     CDP without finding the load-bearing quote in the transcript and
  #     citing it inline.

tier_items:
  # SKETCH NOTE: structural shape only. The auditor does NOT carry these
  # IDs/names forward verbatim. Subagents A/B/C/D/E produce the inputs
  # to populate this block; the auditor synthesises. Every tier_item the
  # auditor authors MUST carry the field shape below; CONTENT comes from
  # the audit, not from this sketch.

  # Required item shape (every tier_item passes):
  #   id:                          # e.g. L1.alpha.3 ; auditor chooses IDs
  #   tier:                        # required by PLATFORM RoadmapDocument; e.g. L1, D, E, V, MVP
  #   layer:                       # one of: alpha, portfolio_construction, execution, operations_telemetry, env_infra, platform_infra
  #   owning_layer:                # only on physical-storage items (D.fast.*, D.lake.*); the layer that owns writes (e.g. L3.exec for orders/fills)
  #   name:                        # short imperative; auditor populates
  #   intent:                      # one-paragraph rationale; auditor populates from Subagent C/D outputs
  #   files_in_scope:              # list of paths; auditor populates from Subagent E
  #   environment_scope:           # list of envs from environments block
  #   cross_roadmap_depends_on:    # list of PLATFORM:<id> or PLATFORM:GAP-<slug>; resolves against Subagent A inventory
  #   contract_gates:              # list of {path: docs/contracts/{slug}.yaml, class: A|B|C, contract_version: int}
  #   effort: XS|S|M|L|XL
  #   strategic: false             # STRATEGIC plans suspended per CD.17; always false in this audit
  #   status: not_started|in_progress|complete|reserved
  #   validation_lens: structural|pnl|both
  #   five_property_test:          # required for L1-L4 items; explicit list of how this item satisfies parameterised/versioned/composable/observable/evaluable
  #   deferred: false              # true if PIVOT-DEFERRED (e.g. options items)
  #   deferred_note: ""            # canonical string per AGENTS.md when applicable

  # Tier groupings the auditor will populate (NOT verbatim - these are
  # the surfaces Subagent C/D/E will reveal; auditor chooses which become
  # tier_items vs which roll into retired_items / known_gaps):
  #
  #   L0.*       Foundation items already shipped or in progress (Subagent C catalogue + Subagent E code-surface audit)
  #   L1.alpha.* Alpha layer items: alpha() Protocol, AlphaModelVersion, RAT-ensemble wiring, IC/IR/decay/orthogonality metrics, walk-forward CV harness, PySR registry, multi-alpha orthogonality
  #   L2.pc.*    Portfolio Construction items: construct_portfolio() Protocol, PortfolioConstructionVersion, sizing methods (equal-weight/risk-parity/cost-aware-MVO/Black-Litterman), constraint set, turnover control, Bayesian tuner, hedging-as-constraint surface, regime-aware selector
  #   L3.exec.*  Execution items: BrokerAdapter Protocol, simulation/paper/Alpaca/IBKR adapters, plan_trades() Protocol, ExecutionPolicyVersion, marketable-limit v1 policy, liquidity/spread/vol gating, TCA aggregation, implementation-shortfall metric, get_cost_curve typed verb, pre-trade gate hook (margin/position/circuit-breaker)
  #   L4.ops.*   Operations/Telemetry items (the actual L4 per PIVOT Part C): LayerInvocation schema, Brinson attribution, deflated Sharpe computation, PBO check, RAG-fed recursive improvement loop extension. NOTE: this slot was previously labelled "Risk Gates" in earlier sketch drafts - corrected per architectural-rigor critique. Risk gates live as L2 constraints and L3 pre-trade hooks, not as their own layer.
  #   D.fast.*   DynamoDB fast-tier physical items: orders, positions_cache, features_serving, conditional-write state machine, cross-item transactions. Each carries `owning_layer` to recover L1/L2/L3 lineage.
  #   D.lake.*   Iceberg lakehouse physical items: ops_trade_events, ops_reconciliations, strategies_versions, alpha_versions, pc_versions, exec_versions, strategy_runs, signals, target_portfolios, fills, pnl_attribution view, tca_events, promotion_events, buffered/SQS Iceberg writer. Each carries `owning_layer`.
  #   E.env.*    Environment infrastructure items: EnvironmentConfig Pydantic, Pattern-C IAM + table-prefix isolation, per-env Secrets Manager broker credentials, promote_strategy() typed verb, pre-registered promotion criteria (gated on docs/contracts/promotion-criteria.yaml), paper-trading orchestration, production ensemble runner, reconciliation Lambda, feature precomputation batch job, backtest engine (same code path as live).
  #   MVP.*      Minimum-viable-pipeline end-to-end items composing a single strategy through the four-stage funnel. References a versioned PortfolioConstructionVersion + ExecutionPolicyVersion in docs/contracts/minimum-viable-v1.yaml (Class A), NEVER as inline YAML scalars (per CDP "five-property optimisability test").

  # Concrete example shape (one item, fully populated, illustrative only):
  - id: L3.exec.1
    tier: L3
    layer: execution
    name: BrokerAdapter typing.Protocol
    intent: "[auditor populates from Subagent D's BrokerAdapter quote in PIVOT Part E]"
    files_in_scope: ["[auditor populates from Subagent E; likely src/trading/brokers/adapter.py]"]
    environment_scope: [research, backtest_canonical, paper, live_small, live_full]
    cross_roadmap_depends_on: ["[auditor populates - likely PLATFORM:CD.25 contract-ratification + PLATFORM:T0.12 Pydantic substrate]"]
    contract_gates:
      - path: docs/contracts/broker-adapter.yaml
        class: C   # in-process Protocol; promoted to A if persisted
        contract_version: 1
    effort: M
    strategic: false
    status: not_started
    validation_lens: structural
    five_property_test:
      # Each attestation MUST carry a `cites:` field per DoD enforcement.
      # `cites:` is path:line in current code OR a forward-pointing
      # tier_item id OR an evaluation_metrics key that establishes the
      # property. Bare prose attestations FAIL Checkpoint 3 completeness.
      parameterised:
        attestation: "BrokerAdapter Protocol exposes typed method signatures; no hidden module-level constants"
        cites: "tier_item:L3.exec.1 (this item authors the Protocol); src/trading/brokers/adapter.py:1 (file to be created by this tier_item)"
      versioned:
        attestation: "Each BrokerAdapter implementation carries version_hash; selection via EnvironmentConfig.broker_adapter literal"
        cites: "tier_item:E.env.1 (EnvironmentConfig schema); tier_item:L3.exec.4 (Alpaca/IBKR implementations)"
      composable:
        attestation: "Protocol consumed by plan_trades() and strategy runner; no other coupling"
        cites: "tier_item:L3.exec.5 (plan_trades Protocol consumer); tier_item:E.env.6 (paper-trading orchestration); tier_item:E.env.10 (backtest engine)"
      observable:
        attestation: "Every BrokerAdapter method emits a LayerInvocation event"
        cites: "tier_item:V.eval.4 (LayerInvocation telemetry schema); evaluation_metrics.layer_4_operations_telemetry.layer_invocation_coverage"
      evaluable:
        attestation: "Implementation parity assessed via paper-vs-live divergence telemetry on environment-tagged strategy_runs"
        cites: "evaluation_metrics.layer_4_operations_telemetry.paper_vs_live_divergence; tier_item:D.lake.11 (strategy_runs Iceberg)"
    deferred: false

  # All other items: auditor authors per the shape above, drawing from
  # subagent outputs. The sketch deliberately does NOT pre-populate them.

cross_tier_gates:
  # SKETCH NOTE: structural shape only. Rules below are CANDIDATE
  # surfaces from PIVOT Parts E (funnel + statistical hygiene) and G
  # (separation discipline). The auditor populates the actual rule
  # strings AFTER Subagent G's schema-fit work confirms which
  # `gate_helpers` are available in PLATFORM's grammar (per
  # scripts/platform_roadmap.py) and AFTER Subagent G proposes any
  # required helper extensions. Authoring a rule string that references
  # an undeclared helper will cause GateRuleParser to reject the YAML
  # at load time - this is the "gate-helper grammar gap" the
  # repo-discipline critique flagged.
  #
  # Each entry must:
  #   id:           # G.<slug>
  #   rule: ""      # parseable by PLATFORM's gate_helpers grammar OR by
  #                 # a new helper Subagent G proposed (in which case the
  #                 # helper appears in document.gate_helpers extension)
  #   description: ""
  #   helpers_required: []  # list of helper names this rule uses; the
  #                         # auditor cross-checks each name against
  #                         # document.gate_helpers
  #
  # Candidate gate slots the auditor will populate (rule strings to be
  # authored AFTER helper grammar is settled):
  #   G.research_backtest_before_paper
  #   G.paper_before_live_small
  #   G.live_small_before_live_full
  #   G.alpha_validation_before_layer2_consumption
  #   G.same_code_path_verified_before_paper
  #     # If `code_path_hash` is not in PLATFORM's gate_helpers AND
  #     # Subagent G does not propose adding it with a concrete grammar
  #     # AND query template, demote this gate to
  #     # `same_code_path_verification_present(strategy_version_id)`
  #     # backed by a runtime-recording mechanism (separate tier_item).
  #   G.no_options_until_stock_system_live_and_stable
  #   G.no_recursive_optimiser_before_mvp_complete
  #   G.reconciliation_active_before_any_live_trading
  #   G.contract_ratification_before_any_iceberg_write
  #   G.survivorship_inclusive_stats_required_for_promotion
  #   G.no_synchronous_iceberg_write_from_decision_loop
  #   G.backtest_execution_timing_mirrors_live
  #   G.dynamodb_cross_item_transaction_for_order_position_pair
  #   G.no_neural_network_at_l3
  #   G.asymmetric_research_to_prod_iam
  #
  # The auditor MUST NOT carry candidate slots above forward as gates
  # without (a) a transcript quote justifying the rule and (b) a
  # rule-string the gate_helpers grammar will accept.

candidate_decisions_research_pool:
  # Top-level mechanically-iterable list of CDP candidates the auditor
  # surfaced from PIVOT Section 11 but did NOT lift to ratified CDPs in
  # `candidate_decisions:`. Survives YAML round-trips (unlike the
  # commented list under `candidate_decisions:`). Each entry includes
  # the pivot quote that justifies it so a follow-up plan can ratify
  # without re-reading the transcript.
  - id: CDPR.1
    title: "[short imperative]"
    pivot_reference: "Section 11 Part X, paragraph Y"
    pivot_quote: |
      [verbatim quote]
    why_not_ratified_now: |
      [auditor populates: e.g. "needs user input on threshold value"
      or "depends on a Subagent G schema decision not yet made"]
    proposed_resolution: ratify_in_followup | demote_to_known_gap | drop
    affected_tier_items: [...]
  # ... one row per candidate not ratified

retired_items:
  - source_section: "Phase 7: Automated Weighting & Decay"
    reason: "Superseded by per-layer strategy versioning + ensemble-as-Layer-1-construct under the four-layer model. Weighting is now a Layer-1 ensemble concern, not a separate phase."
  - source_section: "[every Phase 1-7 / Wave 1-5 / Phase Infra-* deliverable Subagent C marked PIVOT-SUPERSEDED]"
    reason: "[Subagent C's one-line rationale]"

open_questions:
  [3-5 questions Subagent F surfaced + auditor-surfaced]

known_gaps:
  [items intentionally out of scope]
```

**CRITICAL - this is a SKETCH, NOT the answer.**

The block above shows the **structural template** the YAML should
follow: which top-level keys, which item-level fields, the ID
convention (L0, L1.alpha.\*, L2.pc.\*, L3.exec.\*, L4.ops.\*, D.fast.\*,
D.lake.\*, E.env.\*, V.eval.\*, MVP.\*), and the relationship between
them. It is NOT the content the auditor should produce.

The right output:
- **Looks STRUCTURALLY isomorphic to the sketch** - same top-level
  blocks, same field names, same ID conventions, same cross-roadmap
  encoding.
- **Looks MEANINGFULLY DIFFERENT in content** - every `intent`,
  `exit_criteria`, `status`, `cross_roadmap_depends_on`,
  `contract_gates`, `effort` value comes from the subagent outputs and
  the actual code/roadmap audit, not from the sketch's placeholders.

Anti-pattern - "copy the sketch": if the auditor's draft YAML mostly
reproduces the sketch's strings (e.g., shipping with intents like
"[drawn from existing Phase 1 deliverables]" or item names lifted
verbatim from the sketch), the synthesis step failed. Checkpoint 3's
sketch-vs-answer critique subagent catches this. Redo if flagged.

The sketch is also INCOMPLETE on purpose. The auditor will discover
items the sketch doesn't list (Subagent C catalogues legacy phases
the sketch doesn't enumerate; Subagent F surfaces gap-driven items;
Subagent E grounds current_state in actual code). Add them. Likewise,
some sketched items may turn out to be wrong-shaped after Subagent G's
schema-fit work - revise them.

### 5.2 `docs/audit-reports/AUDIT-product-roadmap-yaml-conversion.yaml`

REPORT-ONLY artefact, **YAML not markdown**. Per AGENTS.md "Agent-First
Repository" rule: "narrative summaries are query results, not stored
artefacts" - the audit report's stored form is structured/queryable;
human-readable narratives are produced from it on demand.

Schema:

```yaml
document:
  id: AUDIT-product-roadmap-yaml-conversion
  version: 1
  status: complete  # or in_progress at intermediate checkpoints
  produced_by: docs/AUDIT-PROMPT-product-roadmap-yaml.md
  branch: agent/product-roadmap-yaml-conversion
  artefact_class: REPORT_ONLY

executive_summary: |
  [auditor populates: one paragraph, 100-150 words]

methodology:
  preflight_reads_completed: [docs/ROADMAP-PLATFORM.yaml, docs/INTENT-pre-codegen-contract-ratification.md, Section 11 PIVOT TRANSCRIPT]
  wave_1_subagents_dispatched: [A, B, C, D, E, G]
  wave_2_subagents_dispatched: [F]
  checkpoints_run: [1, 2, 3, 4]
  synthesis_approach: |
    [auditor populates: brief paragraph naming how Wave-1 outputs were
    consumed into the YAML, the synthesis order, any improvisations
    surfaced to user via AskUserQuestion]

subagent_reports:
  - id: A
    name: PLATFORM-SUMMARISER
    role: Structural summary of ROADMAP-PLATFORM.yaml + RoadmapDocument schema
    output_path: docs/audit-reports/wave-1-outputs/A.yaml
    findings_summary: |
      [auditor populates: 1-2 sentences]
    spot_check:
      claim_verified: |
        [auditor populates: which claim was checked]
      verification_result: pass | fail | partial
      verification_evidence: |
        # REQUIRED form: must be ONE of (a) `path:line` pointing at code
        # or a YAML key, (b) a grep command + first 5 lines of output,
        # (c) a Read tool call signature with file_path + offset + first
        # matching line. Prose-only evidence like "I checked it" or
        # "looks correct" is a FAIL.
        [auditor populates per above]
  - id: B
    name: CONTRACT-RATIFICATION-EXTRACTOR
    [... same shape ...]
  - id: C
    name: PRODUCT-ROADMAP-CATALOGUER
    [... same shape ...]
  - id: D
    name: TRADING-PIVOT-DELTA-ANALYSER
    [... same shape ...]
  - id: E
    name: CODE-SURFACE-AUDITOR
    [... same shape ...]
  - id: F
    name: CROSS-ROADMAP-DEPENDENCY-MAPPER
    [... same shape ...]
  - id: G
    name: SCHEMA-FIT-AUDITOR
    [... same shape ...]

pivot_summary:
  # The "pivot in narrative form" is the query result; the source of
  # truth is Section 11 + Subagent D's structured extraction. This
  # block summarises by topic.
  four_layer_model: |
    [auditor populates from Subagent D verbatim]
  three_tier_data_architecture: |
    [auditor populates]
  environments: |
    [auditor populates]
  contract_driven_separation: |
    [auditor populates]
  statistical_hygiene: |
    [auditor populates]

cross_roadmap_dependency_map:
  # Reproduces Subagent F's table verbatim (same YAML shape Subagent F emits)
  - product_id: ...
    name: ...
    platform_depends_on: [...]
    contract_gates: [...]
    rationale: ...
  # ... one row per PRODUCT tier_item that has a cross-roadmap dep

contract_ratification_gates:
  # Aggregated from PRODUCT.yaml's contract_gates fields
  - path: docs/contracts/broker-adapter.yaml
    class: C
    contract_version: 1
    consumed_by: [L3.exec.1]
    status: proposed  # or ratified, if PLATFORM follow-up already done
  # ... one row per unique contract path

platform_gaps_summary:
  # References the gap YAML; do NOT duplicate full gap content.
  - gap_id: GAP.1
    title: TCA aggregation + cost-curve typed verb
    surfaced_by: [L2.pc.5, L3.exec.11, L3.exec.12, L3.exec.13]
    resolution: pending_user_review
    gap_yaml_ref: docs/audit-reports/PRODUCT-ROADMAP-PLATFORM-GAPS.yaml#GAP.1
  # ... one row per gap

open_questions_for_user:
  # MINIMUM 3, IDEALLY 5. Each carries the AskUserQuestion default and
  # the consequences of resolving differently.
  - id: OQ.1
    question: |
      [auditor populates]
    default_recommendation: |
      [auditor populates]
    consequences_if_resolved_differently: |
      [auditor populates]

validation_log:
  full_presubmit_command: "bin/venv-python -m scripts.validate"
  full_presubmit_exit_code: 0  # or non-zero
  full_presubmit_failures: |
    [auditor populates if non-zero - cite specific errors and schema-
    extension follow-up tier_item ids]
  programmatic_id_resolution_check_run: true
  programmatic_id_resolution_missing: []  # empty = pass
  helper_grammar_resolution_check_run: true
  helper_grammar_resolution_missing: []  # empty = pass
  lambda_deferred_note_check_run: true
  lambda_deferred_note_missing: []  # empty = pass

follow_up_work:
  schema_extension_plan_needed: bool  # if Subagent G's Option G(b) chosen
  legacy_markdown_deletion_plan_needed: bool
  promotion_criteria_contract_authoring_plan_needed: true  # always true under Path C parameterisation
  minimum_viable_v1_contract_authoring_plan_needed: true   # always true
  contract_yaml_authoring_plans: [...]  # one per docs/contracts/{slug}.yaml proposed
  platform_gap_resolution_session_needed: true  # always true if gap YAML has entries
```

**Do NOT also produce a `.md` rendering**. The YAML is the only
storage form. A narrative `.md` companion creates drift-by-design
(the "two surfaces for one subject" anti-pattern AGENTS.md explicitly
forbids). If the user wants a human-readable summary, they query the
audit report via an agent at consumption time.

### 5.3 `docs/audit-reports/PRODUCT-ROADMAP-PLATFORM-GAPS.yaml` (gap file)

**Do NOT file recommendations via `ops_data_portal file_rec` for
PLATFORM gaps surfaced during this audit.** Instead, accumulate all
discovered gaps in a single YAML artefact at
`docs/audit-reports/PRODUCT-ROADMAP-PLATFORM-GAPS.yaml`. The user will
review this file with another agent in a follow-up session to confirm
how PLATFORM and PRODUCT fit together before any rec is filed. This
keeps the user in the loop on architectural understanding rather than
having gaps drop into the rec queue uncurated.

Schema:

```yaml
document:
  id: PRODUCT-ROADMAP-PLATFORM-GAPS
  version: 1
  status: draft
  description: |
    Catalogue of PLATFORM additions surfaced during the PRODUCT
    roadmap YAML conversion (docs/AUDIT-PROMPT-product-roadmap-yaml.md).
    Each entry names a PLATFORM tier_item or capability that does NOT
    exist in docs/ROADMAP-PLATFORM.yaml today but is required by a
    PRODUCT tier_item. This file is the input to a separate
    user-in-the-loop session that decides whether each gap becomes a
    PLATFORM tier_item, a recommendation, a deferred-with-rationale
    note, or a re-scope of the PRODUCT item.
  produced_by: docs/AUDIT-PROMPT-product-roadmap-yaml.md
  agent_instructions: |
    - This file is REPORT-ONLY. Agents append; humans curate; nothing
      here flows to ops_data_portal until the human confirms.
    - Every entry MUST cite the PRODUCT tier_item that surfaced the
      gap (the `surfaced_by` field).
    - Every entry MUST propose a PLATFORM tier_item id (the
      `proposed_platform_item.id` field). Use the next-available id
      within the tier that makes structural sense (e.g., a TCA
      aggregation gap might propose T1.12 or T2.4 depending on
      where the existing telemetry tier sits in PLATFORM).
    - Every entry SHOULD enumerate the contract surface required
      (`required_contracts` list) using the docs/contracts/{slug}.yaml
      convention.
    - When the human reviews and decides on disposition, set
      `resolution` to one of: filed_as_rec | adopted_as_platform_item |
      deferred_with_rationale | re_scoped_product_item | not_a_gap.

gaps:
  - id: GAP.1
    surfaced_by: PRODUCT:L2.pc.5  # Cost-aware portfolio construction
    title: TCA aggregation job + cost-curve typed verb
    context: |
      PRODUCT L2.pc.5 (cost-aware portfolio construction) depends on a
      PLATFORM-side TCA aggregation job that computes cost curves from
      fill telemetry and exposes them via a typed verb
      get_cost_curve(symbol_bucket, time_bucket) -> CostCurve. No
      PLATFORM tier_item describes this today.
    pivot_reference: |
      Transcript Part E, "Concrete example walk-through" - the
      Phase 1 (PLATFORM) capability that Phase 2 (PRODUCT) consumes
      for cost-aware portfolio construction.
    proposed_platform_item:
      id: T?.?  # auditor names the structural slot; e.g., T1.12 if
                # telemetry tables are at T1
      tier: T?
      name: TCA aggregation + cost-curve typed verb
      exit_criteria:
        - tca_events Iceberg table contract ratified
        - aggregation job produces cost curves at <100ms latency
        - get_cost_curve typed verb deployed and reachable from
          product Layer 2 code
      effort: M
    required_contracts:
      - docs/contracts/tca-events.yaml  # Class A
      - docs/contracts/cost-curve.yaml  # Class A (return shape)
    blocks_product_items: [L2.pc.5, L3.exec.11, L3.exec.12, L3.exec.13]
    workaround_if_not_resolved: |
      L2.pc.5 stays not_started indefinitely; product ships with
      L2.pc.3 (equal-weight) or L2.pc.4 (risk-parity) only.
    resolution: pending_user_review

  - id: GAP.2
    surfaced_by: PRODUCT:E.env.8  # Reconciliation Lambda
    title: Per-env reconciliation Lambda deployment
    context: |
      PRODUCT E.env.8 (reconciliation Lambda) is gated on PLATFORM
      CD.16 (Lambda-deploy freeze). The audit needs to confirm that
      reconciliation is a new Class B Lambda contract under the
      ratification ritual, not a re-use of an existing dispatcher.
    proposed_platform_item:
      id: T?.?
      [...]
    resolution: pending_user_review

  # ... more gaps surfaced by Subagent F

open_design_questions:
  # Cross-cutting design questions that don't map to a single gap.
  # Auditor surfaces these for the user-in-the-loop session.
  # SCHEMA: every ODQ MUST include `resolution_branches:` enumerating
  # the alternative resolutions with their downstream consequences,
  # so the user can decide without scrolling back to context. The
  # auditor's default is one branch; the alternatives are siblings.
  - id: ODQ.1
    question: |
      Should the DynamoDB fast tier be a PRODUCT-tier responsibility
      (auditor's current default) or a PLATFORM-tier capability? The
      pivot describes it as part of the trading system's data
      architecture, but the existing PLATFORM YAML already owns the
      ops portal's DynamoDB ID allocation.
    affected_items: [D.fast.*]
    auditor_default_recommendation: PRODUCT-owned with cross-roadmap edges to PLATFORM IAM/Terraform substrate.
    resolution_branches:
      - choice: PRODUCT-owned (default)
        affected_items: [D.fast.1, D.fast.2, D.fast.3, D.fast.4, D.fast.5]
        cascading_changes:
          - D.fast.* tier_items remain in PRODUCT YAML with cross_roadmap_depends_on PLATFORM IAM tier_items
          - Contracts (docs/contracts/dynamodb-orders.yaml etc.) owned by PRODUCT
          - Future agents querying "who owns orders table" -> PRODUCT
      - choice: PLATFORM-owned
        affected_items: [D.fast.*]
        cascading_changes:
          - D.fast.* tier_items move to PLATFORM YAML as a new PLATFORM:GAP-DynamoDB-trading-fast-tier
          - PRODUCT depends_on the PLATFORM substrate via cross_roadmap edges only
          - Contracts owned by PLATFORM (and gated on PLATFORM ratification cadence)
          - Audit cycle blocks on PLATFORM-side authoring before PRODUCT MVP completes

  - id: ODQ.2
    question: |
      Is `validate.py` the right validator for PRODUCT.yaml, or does
      it need a sibling `product_roadmap.py` per Subagent G's
      recommendation? If sibling, who owns the schema delta - PRODUCT
      audit or PLATFORM team in a follow-up plan?
    affected_items: [all tier_items, document.gate_helpers]
    auditor_default_recommendation: Sibling `scripts/product_roadmap.py` with a `ProductRoadmapDocument` Pydantic schema; PRODUCT audit authors the schema in a follow-up IMPLEMENTATION plan (not this one).
    resolution_branches:
      - choice: Sibling product_roadmap.py (default)
        cascading_changes:
          - New file scripts/product_roadmap.py authored in follow-up plan
          - PRODUCT YAML cannot validate against validate.py until follow-up plan completes; audit deliverable status = "validation deferred"
          - No risk of extra="ignore" silent drop
      - choice: Extend platform_roadmap.py with kind discriminator
        cascading_changes:
          - scripts/platform_roadmap.py edited; PLATFORM team owns merge
          - PRODUCT YAML can validate immediately
          - Cross-cutting risk: PLATFORM team must agree to schema extension
      - choice: Reuse RoadmapDocument with extra="ignore"
        cascading_changes:
          - PRODUCT YAML validates green but PRODUCT-specific fields silently dropped on load
          - Forbidden by Section 8 anti-patterns unless Subagent G demonstrates no automated reader exists or is planned

  - id: ODQ.3
    question: |
      Does the auditor's candidate CDP "Layer 2 is Bayesian-opt, not
      formula discovery" supersede or coexist with the existing PySR
      formula-discovery infrastructure? PySR remains the L1
      formula-generator, but the v1 product roadmap currently shows
      no L2-level optimisation. If/when L2 hyperparameter tuning
      lands, what's the relationship to PySR?
    affected_items: [L1.alpha.6, L2.pc.9]
    auditor_default_recommendation: Coexist - PySR stays at L1 (formula generation), Bayesian-opt at L2 (hyperparameter tuning), separate optimisation surfaces with separate metrics.
    resolution_branches:
      - choice: Coexist (default)
        cascading_changes:
          - L1.alpha.6 retains PySR as alpha generator
          - L2.pc.9 added as Bayesian-opt tuner; consumes alpha versions but does not generate them
          - Two separate recursive-improvement loops with separate metrics
      - choice: Unify under one optimiser
        cascading_changes:
          - Bigger architectural change; would need a separate INTENT doc
          - Out of scope for this audit; punt to follow-up
```

The auditor MUST write this file with at least one entry per
`PLATFORM:GAP-*` flagged in Subagent F's cross-roadmap dependency map,
plus at least three cross-cutting `open_design_questions` entries.

Anti-pattern: filing recs directly from the audit. The Single Portal
Invariant still applies - this gap file is a draft input to a
user-curated rec-filing session, not a parallel write path.

### 5.4 (NO recommendation filings in this audit)

Unlike a typical audit, this one does **NOT** file recommendations via
`ops_data_portal file_rec`. All discoveries that would otherwise be recs
are accumulated in the gap YAML (Section 5.3) for user review. The
user explicitly requested this to stay in the architectural-
understanding loop rather than dispatching gaps directly to the
executor queue. After user review, individual gap entries may become
recs (with the user's explicit approval) in a follow-up session.

---

## 5.5 Routine zero-context prompt reviews (workflow rule)

The auditor MUST schedule **zero-context prompt critique subagents** at
the following workflow checkpoints. Each critique subagent is briefed
ONLY with this prompt file (`docs/AUDIT-PROMPT-product-roadmap-yaml.md`)
and a single critique angle - they see no other context, no prior
subagent output, no in-progress YAML draft. Their job is to catch
errors in the prompt that an in-context agent would miss because of
familiarity blindness.

**Checkpoint 1 - immediately after the auditor reads the prompt, before
any Wave 1 dispatch.** Fan out 3 critique subagents in parallel:
- **Adversarial / risk lens**: what could a misreading of this prompt
  cause? Where might subagent briefs be ambiguous, contradictory, or
  silently truncated? What pivot content is at risk of being dropped?
- **Coverage lens**: does the prompt encode the full pivot transcript's
  architectural commitments? Cross-check Section 3.3 bullets against
  Section 11 Parts A-G - is anything load-bearing missing from the
  briefs?
- **Repo-discipline lens**: does the prompt respect AGENTS.md, the
  never-on-main hook, the Single Portal Invariant, the contract-
  ratification ritual (CD.25), the CD.16/CD.17 freezes, the
  warehouse-as-SOT invariant, the no-emoji rule, the bin/venv-python
  invocation rule?

The auditor reads the three reports, surfaces material concerns to the
user via `AskUserQuestion` before Wave 1, then proceeds.

**Checkpoint 2 - after Wave 1 subagent outputs land, before Wave 2
dispatch.** Fan out 1 critique subagent:
- **Brief-fit lens**: re-read this prompt and the actual Subagent A-E
  outputs. Did the briefs produce the outputs the synthesis step needs?
  Are there asks the briefs failed to elicit? Is Subagent F's brief
  going to be tractable given what A/B/D/E actually returned?

If the critique surfaces material gaps, the auditor decides between:
(a) re-running specific Wave 1 subagents with sharpened briefs;
(b) augmenting Subagent F's brief with a recovery instruction;
(c) surfacing the gap to the user via `AskUserQuestion`.

**Checkpoint 3 - after the YAML draft is written, before commit.**
Fan out 2 critique subagents in parallel:
- **Sketch-vs-answer lens**: does the YAML the auditor produced look
  like the SKETCH in Section 5.1, or does it look meaningfully
  different? If too similar, the auditor copied rather than
  synthesised - flag for redo. If meaningfully different in ways
  that contradict the pivot, flag for redo. The right answer is
  meaningfully different from the sketch in CONTENT but isomorphic
  in STRUCTURE.
- **Completeness lens**: does every Subagent C catalogued PRODUCT.md
  deliverable appear in the YAML as one of: tier_item, retired_items
  entry, known_gaps entry? Any silent drop is a bug.

The auditor reads both reports, addresses any material findings, then
commits.

**Checkpoint 4 (MANDATORY per agent-first repo commitment) - after commit, before
reporting back to the user.** Fan out 1 critique subagent:
- **External-reader lens**: this subagent is given ONLY
  `docs/ROADMAP-PRODUCT.yaml` (the produced artefact), with no view
  of the prompt or pivot transcript. Can it reconstruct the
  organising principles (four-layer model, three-tier data
  architecture, environments, contract-driven separation) from the
  YAML alone? If not, the YAML's `agent_instructions` and `north_star`
  blocks are under-stated.

**Rule for all critique subagents**: brief is < 250 words. The
critique subagent is read-only and produces **YAML output (not
narrative markdown)** so the auditor can mechanically extract
actionable findings. Required output schema:

```yaml
critique:
  checkpoint: 1 | 2 | 3 | 4
  angle: adversarial | coverage | repo-discipline | architectural | brief-fit | sketch-vs-answer | completeness | external-reader
  findings:
    - id: F.1
      severity: HIGH | MEDIUM | LOW
      location: line_number_or_section_reference
      issue: |
        [one-paragraph description]
      suggested_fix: |
        [one-paragraph remediation]
      auditor_action_required: true | false
      rationale_for_action_required: |
        [if true, why the auditor cannot defer this]
    # ... more findings
  ranked_top_3: [F.id, F.id, F.id]  # most-impactful first
  net_verdict: PASS | PASS_WITH_CONCERNS | FAIL
  verdict_rationale: |
    [one-paragraph summary]
```

The auditor MUST mechanically extract all `auditor_action_required:
true` findings before Wave 1 dispatch (Checkpoint 1), Wave 2 dispatch
(Checkpoint 2), commit (Checkpoint 3), or report-back (Checkpoint 4).
Findings with `severity: HIGH` and `auditor_action_required: false`
are surfaced to the user in the audit report's `open_questions`
section but do not block the workflow.

The auditor is responsible for synthesising critique reports back
into the workflow - the critique subagents do not edit anything.

**Critique-YAML parse-fail handling**: if `yaml.safe_load(critique_output)`
raises, re-dispatch the same critique subagent with its prior output
appended and the instruction "Your prior output was not valid YAML;
produce a strictly valid YAML response matching the schema in
Section 5.5 of the audit prompt." If the second attempt also fails,
log the malformed output to
`docs/audit-reports/critique-reports/checkpoint-N-{angle}-malformed.txt`,
treat the critique as `findings: []` with `net_verdict: PARSE_FAIL`,
and surface to the user via `AskUserQuestion` before proceeding.

The same parse-fail policy applies to Subagent C/D/F/G YAML outputs:
two attempts, then surface to user. Do NOT attempt to hand-edit a
malformed subagent YAML - the auditor's job is to consume subagent
output, not author it.

**Cost note**: these reviews are deliberately cheap (small briefs,
small outputs) but high-leverage. The cost of missing a load-bearing
constraint is far higher than 4 extra Opus invocations at the
checkpoints.

---

## 5.6 Audit artefact directory layout (extension policy + DoD invariant)

The audit produces 19 deliverable artefacts across 4 directories. To
prevent extension drift and missing-file regressions, the canonical
layout is:

```
docs/
  ROADMAP-PRODUCT.yaml                        # primary deliverable
  ROADMAP-PRODUCT.md                          # legacy, with banner
  audit-reports/
    AUDIT-product-roadmap-yaml-conversion.yaml  # audit report (Section 5.2)
    PRODUCT-ROADMAP-PLATFORM-GAPS.yaml          # gap file (Section 5.3)
    ask-user-gates-resolved.yaml                # resume runbook step 2
    wave-1-outputs/
      A.yaml                                  # PLATFORM-SUMMARISER
      B.yaml                                  # CONTRACT-RATIFICATION-EXTRACTOR
      C.yaml                                  # PRODUCT-ROADMAP-CATALOGUER
      D.yaml                                  # TRADING-PIVOT-DELTA-ANALYSER
      E.md                                    # CODE-SURFACE-AUDITOR (prose)
      G.yaml                                  # SCHEMA-FIT-AUDITOR
    wave-1.5-tier-items-draft.yaml            # Wave 1.5 Step 2
    wave-2-output-F.yaml                      # CROSS-ROADMAP-DEPENDENCY-MAPPER
    critique-reports/
      checkpoint-1-adversarial.yaml
      checkpoint-1-coverage.yaml
      checkpoint-1-repo-discipline.yaml
      checkpoint-2-brief-fit.yaml
      checkpoint-3-sketch-vs-answer.yaml
      checkpoint-3-completeness.yaml
      checkpoint-4-external-reader.yaml
```

**Extension policy**: structured-content artefacts use `.yaml`;
prose-narrative artefacts use `.md`. The two are NOT interchangeable
by extension change - YAML content in a `.md` file requires markdown-
wrapper parsing before YAML load, which downstream consumers do not
implement. Mismatched extensions ARE a FAIL.

**DoD directory invariant**: as the final pre-commit check (before
Checkpoint 4), the auditor runs:

```bash
expected_files=(
  "docs/ROADMAP-PRODUCT.yaml"
  "docs/audit-reports/AUDIT-product-roadmap-yaml-conversion.yaml"
  "docs/audit-reports/PRODUCT-ROADMAP-PLATFORM-GAPS.yaml"
  "docs/audit-reports/ask-user-gates-resolved.yaml"
  "docs/audit-reports/wave-1-outputs/A.yaml"
  "docs/audit-reports/wave-1-outputs/B.yaml"
  "docs/audit-reports/wave-1-outputs/C.yaml"
  "docs/audit-reports/wave-1-outputs/D.yaml"
  "docs/audit-reports/wave-1-outputs/E.md"
  "docs/audit-reports/wave-1-outputs/G.yaml"
  "docs/audit-reports/wave-1.5-tier-items-draft.yaml"
  "docs/audit-reports/wave-2-output-F.yaml"
  "docs/audit-reports/critique-reports/checkpoint-1-adversarial.yaml"
  "docs/audit-reports/critique-reports/checkpoint-1-coverage.yaml"
  "docs/audit-reports/critique-reports/checkpoint-1-repo-discipline.yaml"
  "docs/audit-reports/critique-reports/checkpoint-2-brief-fit.yaml"
  "docs/audit-reports/critique-reports/checkpoint-3-sketch-vs-answer.yaml"
  "docs/audit-reports/critique-reports/checkpoint-3-completeness.yaml"
)
for f in "${expected_files[@]}"; do
  [[ -f "$f" ]] || echo "MISSING: $f"
done
# Checkpoint 4 report committed post-pre-commit-check, so excluded
```

Any `MISSING:` output is a FAIL. The auditor MAY have additional
artefacts (e.g. Wave-1 re-run versions per Checkpoint 2) but the 18
canonical files above are mandatory.

**No-emoji / no-em-dash sweep**: also as a final pre-commit check,
confirm no non-ASCII content snuck in:

```bash
for f in "${expected_files[@]}"; do
  bin/venv-python -c "
import sys
with open('$f') as h:
    for n, line in enumerate(h, 1):
        for ch in line:
            if ord(ch) > 127:
                print(f'{sys.argv[1]}:{n}: non-ASCII U+{ord(ch):04X}: {ch!r}')
" "$f"
done
```

---

## 6. Cross-reference precision rules

- **Code references**: always `path:line` (e.g.,
  `src/execution/async_engine.py:42`). Never paraphrase a function name.
- **Roadmap references**: always by id (e.g., `T0.12`, `CD.25`,
  `PLATFORM:T0.12`). Never by title.
- **Contract references**: always by path (e.g.,
  `docs/contracts/inference-provider.md`). Propose new contracts by
  `docs/contracts/{slug}.{md|yaml}` path.
- **Cross-roadmap edges**: always prefix with `PLATFORM:` or `PRODUCT:`.
- **PLATFORM gaps**: always tag as `PLATFORM:GAP-{slug}` with a
  proposed `tier_item.id` PLATFORM would add. Surface in the gap YAML
  (Section 5.3), NOT as a rec - the user reviews the gap YAML in a
  follow-up session before any rec is filed.
- **Pivot quotes**: when embedding text from the PIVOT TRANSCRIPT into
  YAML `agent_instructions` / `candidate_decisions[].detail`, quote
  verbatim and clearly attribute (`# verbatim from pivot transcript Part X`).

---

## 7. Definition of done

The audit is complete when ALL of the following hold:

- [ ] Working branch `agent/product-roadmap-yaml-conversion` exists and
  is the current branch.
- [ ] `docs/ROADMAP-PRODUCT.yaml` exists, with `document.id == ROADMAP-PRODUCT`,
  populated `tier_items[]` covering all four layers + environments,
  populated `candidate_decisions[]` (CDP.1, CDP.2 ratified; the
  remainder drawn from the candidate-titles list under
  `candidate_decisions:` in Section 5.1 and ratified per Subagent D's
  transcript-quote justification), populated `cross_tier_gates[]` with
  **at least one gate per category**: (a) promotion-stage gate
  (research_backtest -> paper, paper -> live_small, live_small ->
  live_full), (b) reconciliation gate, (c) contract-ratification gate
  (no Iceberg write before contract ratified), (d) statistical-hygiene
  gate (survivorship-inclusive stats required for promotion). An empty
  `cross_tier_gates: []` ships as zero enforcement and is a FAIL.
  Populated `open_questions[]`, populated `known_gaps[]`, populated
  `retired_items[]` for every Subagent-C-flagged PIVOT-SUPERSEDED entry.
- [ ] Every `tier_items[]` entry has at minimum: `id`, `tier`, `layer`,
  `name`, `intent`, `depends_on`, `exit_criteria`, `status`,
  `environment_scope`, `effort`, `strategic` (always `false` per CD.17),
  `validation_lens`, `cross_roadmap_depends_on`, `contract_gates`.
- [ ] Every `D.fast.*` and `D.lake.*` tier_item carries `owning_layer:
  alpha | portfolio_construction | execution | operations_telemetry`
  (the layer that owns writes). Items missing this are a FAIL because
  layer-versioning lineage is irrecoverable from a missing field.
- [ ] Every `cross_roadmap_depends_on` value resolves to an actually-
  existing PLATFORM id (Subagent A's inventory is the resolution table),
  or is tagged `PLATFORM:GAP-*` with a corresponding entry in the gap
  YAML (Section 5.3).
- [ ] Every `contract_gates` entry is a **`{path, class, contract_version}`
  triple**: `path` is an existing `docs/contracts/` file or a proposed
  `docs/contracts/{slug}.yaml`; `class` is one of A/B/C; `contract_version`
  is a positive integer. Bare-path lists or `path + class` pairs FAIL
  per INTENT-pre-codegen-contract-ratification.md Invariants 1+2 - the
  semantic-evolution mechanism requires the version.
- [ ] Every L1.alpha.*, L2.pc.*, L3.exec.*, L4.ops.* tier_item carries
  a `five_property_test:` block with five short attestations
  (parameterised / versioned / composable / observable / evaluable).
  Each attestation MUST reference either (a) a `path:line` in current
  code where the property holds OR (b) a forward-pointing tier_item id
  that establishes the property. Bare prose attestations FAIL (they
  are unverifiable by Checkpoint-3 critique).
- [ ] `docs/ROADMAP-PRODUCT.md` has the legacy banner prepended.
- [ ] `docs/audit-reports/AUDIT-product-roadmap-yaml-conversion.yaml`
  exists and validates as YAML (yaml.safe_load returns without error),
  with all 11 top-level keys populated per the Section 5.2 schema
  (document, executive_summary, methodology, subagent_reports,
  pivot_summary, cross_roadmap_dependency_map,
  contract_ratification_gates, platform_gaps_summary,
  open_questions_for_user, validation_log, follow_up_work).
- [ ] `docs/audit-reports/PRODUCT-ROADMAP-PLATFORM-GAPS.yaml` exists,
  contains one entry per `PLATFORM:GAP-*` flagged in the audit, and
  contains at least three `open_design_questions` entries for the
  user-in-the-loop session (Section 5.3).
- [ ] **Zero recs filed**: `logs/.recommendations-log.jsonl` is
  unchanged. No `ops_data_portal file_rec` calls were made during the
  audit. The user reviews the gap YAML before any rec is filed (a
  follow-up session).
- [ ] Checkpoint 1 critique subagent reports (3) read and material
  findings addressed before Wave 1.
- [ ] Checkpoint 2 critique subagent report read before Wave 2.
- [ ] Checkpoint 3 critique subagent reports (2) read before commit;
  sketch-vs-answer report did NOT flag "copy the sketch."
- [ ] Checkpoint 4 critique subagent report read before reporting back.
- [ ] `bin/venv-python -m scripts.validate` exits 0, OR
  the audit report documents exactly why it fails and what schema
  extension is needed.
- [ ] No edits to `docs/ROADMAP-PLATFORM.yaml`.
- [ ] No edits to `logs/.recommendations-log.jsonl` or
  `logs/.decisions-index.jsonl`.
- [ ] No STRATEGIC-plan artefacts produced.
- [ ] At least 3 open questions surfaced for the user.
- [ ] All subagent claims spot-checked at least once each.
- [ ] **Programmatic ID resolution check** has been run: for every
  `PLATFORM:` reference in the draft YAML, grep the platform roadmap
  to confirm the id exists, with the exception of `PLATFORM:GAP-*`
  references which must resolve to entries in the gap YAML:
  ```
  rg -no 'PLATFORM:[A-Z0-9._-]+' docs/ROADMAP-PRODUCT.yaml | sort -u | \
    while read ref; do
      id="${ref#PLATFORM:}"
      if [[ "$id" == GAP-* ]]; then
        rg -q "id: $id" docs/audit-reports/PRODUCT-ROADMAP-PLATFORM-GAPS.yaml \
          || echo "MISSING GAP: $ref"
      else
        rg -q "id: $id\$" docs/ROADMAP-PLATFORM.yaml \
          || echo "MISSING PLATFORM: $ref"
      fi
    done
  ```
  Any `MISSING` output is a failure - resolve before commit.
- [ ] **Helper grammar resolution check** has been run: every helper
  invoked in `cross_tier_gates[].rule` strings appears in PRODUCT
  YAML's `document.gate_helpers[]` block OR in PLATFORM's helper table
  (`scripts/platform_roadmap.py::_GATE_HELPERS`). Otherwise the
  `GateRuleParser` will reject the YAML at load time.
- [ ] **Lambda deferred-note check**: every tier_item whose intent
  implies a Lambda (TCA aggregation, cost_curve typed verb,
  reconciliation, paper-trading scheduler, EOD reconciliation,
  feature-precomputation batch) carries `deferred: true` and the
  canonical `deferred_note` string per AGENTS.md.
- [ ] **validation_log evidence-paired**: every `validation_log._run:
  true` field in the audit report YAML (Section 5.2) is paired with
  a populated `_missing: [...]` field (empty list for pass; non-empty
  list with resolution notes for partial). Self-reported flags with
  missing or unspecified results FAIL the DoD; the auditor's spot-
  check re-runs the corresponding bash command from the DoD bullet
  (e.g. the PLATFORM-id grep) and confirms the YAML's `_missing`
  field matches the live result.
- [ ] **Directory-invariant check**: per Section 5.6, the 18 canonical
  audit artefacts (or 19 including Checkpoint-4-external-reader)
  exist at their named paths with their named extensions. Any
  `MISSING:` from the for-loop FAILS.
- [ ] **Non-ASCII sweep**: per Section 5.6, every artefact passes
  the non-ASCII grep (no emojis, no em dashes); any U+0080+ output
  FAILS.
- [ ] Commit pushed to remote (`git push -u origin
  agent/product-roadmap-yaml-conversion`) with exponential backoff
  retry on network failure.

---

## 8. Anti-patterns to avoid

- **Re-reading the same large file from multiple subagents in parallel**.
  Subagent A reads PLATFORM YAML; Subagents F and G consume A's summary
  rather than re-reading.
- **Letting subagents synthesise across each other's outputs**. F is the
  ONLY subagent that consumes other subagent outputs - and even F
  receives them via your brief, not directly. Cross-subagent synthesis
  is YOUR job.
- **Trusting subagent summaries blindly**. Spot-check at least one
  non-trivial claim per subagent (e.g., open the cited file at the
  cited line and verify the signature matches).
- **Defaulting to `extra="ignore"` silent-drop**. Section 10 ask-user
  gate 2 and Subagent G's brief both default to **Option G(b)**: a
  sibling `ProductRoadmapDocument` Pydantic schema with PRODUCT-specific
  fields REQUIRED, not optional. Falling back to Option G(a) (reuse
  PLATFORM's `RoadmapDocument` with `extra="ignore"` swallowing the new
  fields) is the anti-pattern - it validates green while the
  PRODUCT-specific data is invisible to any downstream Python loader.
  Option G(a) is permitted ONLY if Subagent G demonstrates no automated
  reader of PRODUCT YAML exists or is planned (and surfaces that
  determination explicitly in the audit report). If unsure, take
  Option G(b).
- **Dropping content from PRODUCT.md silently**. Every section either
  becomes a tier_item, ends up in `retired_items[]`, or appears in
  `known_gaps[]`. Subagent C's classification is the audit trail.
- **Authoring contract YAMLs inline**. The audit PROPOSES contract
  paths and classes. The contracts themselves are authored in
  follow-up plans gated on CD.25 ratification.
- **Patching ROADMAP-PLATFORM.yaml inline** to add missing items.
  Append to the gap YAML (Section 5.3) instead. Do NOT file recs
  directly - the user reviews the gap YAML first.
- **Filing recommendations directly** from the audit (`ops_data_portal
  file_rec`). The user requested explicit-loop-in via the gap YAML.

---

## 9. Estimated cost and runtime

Realistic estimates (revised - the earlier "~1 hour" was wrong; that
figure ignored synthesis depth, critique checkpoints, and validation
iteration):

- **Checkpoint 1 (pre-Wave-1 prompt critique)**: 3 critique subagents
  in parallel, ~5-10 min wall-clock, ~15K tokens output. Surface
  material concerns via `AskUserQuestion` before Wave 1.
- **Pre-Wave-1 ask-user gates** (Section 10): resolve before Wave 1
  dispatch. ~5-30 min depending on user availability; defaults defined
  per gate.
- **Wave 1**: 6 Opus subagents in parallel (A, B, C, D, E, G).
  Wall-clock: ~15-25 minutes for the slowest. Token cost: revised
  per Path C YAML output specs - Subagent C emits 5000-7000 lines of
  YAML (~30-40K tokens), D emits 3000-5000 lines (~20-30K tokens),
  A/B/G ~600-1000 lines each (~5-7K tokens each), E ~2000-3000 lines
  of markdown (~10-15K tokens). Aggregate: **~80-100K tokens of
  Wave-1 output**.
- **Wave 1.5**: auditor solo (~10-15 min) for PLATFORM-id resolution,
  tier_items draft authoring, helper-grammar pre-check.
- **Checkpoint 2 (post-Wave-1 brief-fit critique)**: 1 subagent,
  ~5 min. May trigger re-runs of specific Wave-1 subagents with
  sharpened briefs.
- **Wave 2**: 1 Opus subagent (F), ~10-15 min, ~10-15K tokens output
  (revised from ~5-10K - F now emits YAML quadruples + structured
  PLATFORM-gap summary).
- **Synthesis (Wave 3)**: the auditor drafts the YAML, the audit
  report YAML, and the gap YAML. This is ~2-4 hours of auditor work
  (revised from ~1-3h because Wave-1 output to absorb is now
  **~80-100K tokens, not 50K**). Synthesis-budget guidance: use
  targeted Read offset/limit for Subagent C/D output - do NOT Read
  the full 5000-line files into context unless absolutely needed.
  Iteration with `validate.py` (likely several rounds: gate_helpers
  grammar extension, contract_gates shape, ProductRoadmapDocument
  schema delta), audit report YAML, gap YAML.
- **Checkpoint 3 (pre-commit critique)**: 2 subagents in parallel
  (sketch-vs-answer, completeness), ~10 min.
- **Checkpoint 4 (post-commit external-reader critique)**: 1
  subagent, ~5-10 min. MANDATORY per agent-first repo commitment -
  this is the only check that validates the YAML from the perspective
  of an agent consuming it without prior context.

**Realistic total**: 4-6 hours wall-clock end-to-end. ~15-25 Opus
subagent invocations total (6 + 1 + 3 + 1 + 2 + 1 = 14 mandatory, plus
any Wave-1 re-runs from Checkpoint 2). Do NOT under-fan-out to save
cost; the prompt's critique findings (multiple HIGHs) were caught only
because critique subagents were dispatched - skipping them re-imports
the bugs they catch.

---

## 10. Ask-the-user gates

These resolve BEFORE Wave 1 fan-out, not at the end. Asking the user
before subagents dispatch costs nothing; asking at the end risks
having to redo Wave 1 + Wave 2 + synthesis if the user disagrees with
a structural default. Run via `AskUserQuestion` immediately after
preflight reads and Checkpoint 1 critiques resolve.

If the user does not respond within ~30 minutes, log the question in
the audit report under `open_questions[]` with the auditor's
recommended default, and proceed using the default. Re-surface at
Checkpoint 3 if the choice materially affects what got built.

1. **Tier numbering**: PRODUCT YAML uses `L0..L4`, `D`, `E`, `MVP`
   layer-aligned prefixes? Or borrow PLATFORM's `T-1..T5` numbering
   with `layer:` as the orthogonal classifier? Recommend layer-aligned.
2. **Cross-roadmap encoding**: which of Subagent G's three options
   does the user prefer? Recommend per-item `cross_roadmap_depends_on`
   with `PLATFORM:` prefix (Option 1) **paired with a new
   `ProductRoadmapDocument` Pydantic schema** to avoid the
   `extra="ignore"` silent-drop risk (Option 5b).
3. **Options posture**: PIVOT-DEFERRED in `known_gaps`, or surfaced as
   a future-tier `L?.options.*` block in `retired_items` for visibility?
   Recommend `known_gaps[]` with a forward-pointer note + a gap-YAML
   `open_design_questions` entry naming the options hypothesis trigger.
4. **Legacy markdown deletion**: delete `docs/ROADMAP-PRODUCT.md` in
   this PR or follow-up? Recommend follow-up (keep one transition
   cycle with the banner).
5. **Schema location**: if Option 5b (new `ProductRoadmapDocument`),
   author it in `scripts/product_roadmap.py` (sibling to
   `platform_roadmap.py`) or extend `scripts/platform_roadmap.py` with
   a discriminator? Recommend sibling file.
6. **Gate-helper scope**: PLATFORM extension (helpers added to
   `_GATE_HELPERS`) vs PRODUCT-local helpers (added to PRODUCT YAML's
   `document.gate_helpers` block)? Recommend PRODUCT-local for any
   helper that queries PRODUCT-only Iceberg tables, PLATFORM extension
   only for genuinely cross-cutting helpers - and either way, route
   helper additions through the gap YAML for user review before edits.

---

## 10A. Resume-from-checkpoint runbook

If the audit is interrupted (context window pressure, environment
restart, network failure mid-Wave), the auditor resumes from the most
recent committed state. The branch (`agent/product-roadmap-yaml-conversion`)
is the resume substrate. Intermediate progress is committed at the
following points so resume is tractable:

Extension policy (per Section 5.6): structured YAML content uses
`.yaml`; prose narrative uses `.md`. Critique reports + Subagent
A/B/C/D/F/G outputs are YAML; only Subagent E's code-surface audit
is markdown.

1. **After Checkpoint 1 critiques**: commit the three critique reports
   at `docs/audit-reports/critique-reports/checkpoint-1-{adversarial,
   coverage,repo-discipline}.yaml` (or whichever 3 critique angles
   were chosen) and any auditor decisions.
2. **After ask-user gates resolve**: commit the resolved-defaults file
   `docs/audit-reports/ask-user-gates-resolved.yaml` so resumes do not
   re-ask.
3. **After Wave 1 completes**: commit raw subagent outputs:
   `docs/audit-reports/wave-1-outputs/A.yaml`,
   `wave-1-outputs/B.yaml`, `wave-1-outputs/C.yaml`,
   `wave-1-outputs/D.yaml`, `wave-1-outputs/E.md`,
   `wave-1-outputs/G.yaml`. The auditor does not synthesise yet.
4. **After Checkpoint 2 brief-fit critique**: commit
   `docs/audit-reports/critique-reports/checkpoint-2-brief-fit.yaml`
   + any Wave-1 re-run outputs (same paths, version-suffixed).
5. **After Wave 2 (F) completes**: commit Subagent F output to
   `docs/audit-reports/wave-2-output-F.yaml`.
6. **After draft YAML written but before Checkpoint 3 critiques**:
   commit `docs/ROADMAP-PRODUCT.yaml` (status `draft`) +
   `docs/audit-reports/AUDIT-product-roadmap-yaml-conversion.yaml` (in
   progress) + `docs/audit-reports/PRODUCT-ROADMAP-PLATFORM-GAPS.yaml`
   (in progress).
7. **After Checkpoint 3 critiques**: commit
   `docs/audit-reports/critique-reports/checkpoint-3-{sketch-vs-answer,
   completeness}.yaml`.
8. **Final commit before Checkpoint 4**: tidy-up commit of all
   artefacts.
9. **Checkpoint 4 external-reader critique**: commit report at
   `docs/audit-reports/critique-reports/checkpoint-4-external-reader.yaml`.

To resume: `git log --oneline agent/product-roadmap-yaml-conversion`
shows the last completed checkpoint. The auditor reads the most recent
critique-report + the relevant artefact and continues from the next
step. The prompt itself is unchanged; resume context is in the
committed audit-reports directory.

**Commit-vs-push cadence (important)**: commit locally at each of the
9 checkpoints, but push to remote ONLY at audit completion (after
Checkpoint 4). Reason: each push triggers the self-hosted runner's
`validate.py` CI run (Decision 68); 9 pushes = 9 CI runs at 5-10 min
wall-clock each, plus risk of intermediate ci-rca runs filing
critical recs against incomplete artefacts. The single push at end
is sufficient for the merge gate. Exception: push the
`ask-user-gates-resolved.yaml` checkpoint (step 2) if the auditor
wants the user to see progress; the YAML is non-functional and
unlikely to fail CI.

**Checkpoint 4 vs never-amend rule**: Checkpoint 4 fires AFTER the
final-tidy-up commit (step 8). If Checkpoint 4 surfaces a material
finding (e.g., `agent_instructions` block too thin for an external
reader to reconstruct the four-layer model), the auditor authors a
NEW follow-up commit on the same branch addressing the finding -
never `git commit --amend` per AGENTS.md. The branch history will
include both the original Checkpoint-4-trigger commit AND the
remediation; this is the audit trail. If the finding requires changes
to many earlier commits, file the rework as a follow-up plan rather
than rewriting history.

**Wave-1 interrupted mid-flight**: if the auditor crashes after
dispatching Wave 1 but before all 6 subagents commit their outputs,
re-dispatch the entire wave from scratch. Do NOT assume partial
outputs are valid - subagent IDs and tool-call IDs are lost across
context restart, and re-dispatching is cheaper than reconstructing
ambiguous partial state.

**Harness-specific failure modes the auditor must handle**:
- **AWS SSO expiry**: `validate.py` may invoke backend tools requiring
  fresh SSO credentials. If `aws sso login --profile
  company-aws-profile` fails or the audit started >8h ago, refresh
  before running `validate.py`. The audit prompt does not require any
  Athena queries directly, so SSO is only needed for the final
  validate step.
- **Context window compaction during synthesis**: Wave-1 outputs
  (~40-60K) + prompt (~80K) + accumulated state risk compaction. After
  committing Wave-1 outputs (step 3 above) and Wave-2 output (step 5),
  the auditor SHOULD drop Wave-1/2 outputs from working context and
  re-Read them by file as needed during synthesis. The audit prompt
  itself is the only document that must stay resident.
- **Bash tool 2-minute default timeout**: `git push` to remote may
  exceed this on a slow network. Use `timeout=300000` (5 min) on the
  push command; retry up to 4 times with exponential backoff per
  AGENTS.md.
- **Self-hosted runner stopped**: if the EC2 runner is stopped (per
  AGENTS.md operational runbook), the final `validate.py` push-gate
  CI run won't fire. The auditor should run `bin/venv-python -m
  scripts.validate` LOCALLY before push; if it passes, push; if CI
  doesn't run within ~15 min of push, surface to user (do not wake the
  runner without authorisation per AGENTS.md).

Anti-pattern: trying to keep all intermediate state in working memory
without intermediate commits. Wave 1 outputs alone are ~40-60K tokens;
losing them to a context restart wastes Opus subagent budget.

Anti-pattern (NEW): pushing every checkpoint to trigger CI runs as
"progress signals." Each push burns 5-10 min CI wall-clock and risks
ci-rca filings against incomplete artefacts. Push only at completion.

---

## 11. PIVOT TRANSCRIPT (verbatim)

> Embedded verbatim. Treat as the design north-star.
> When dispatching Subagents C, D, F, include this entire section in
> their brief.

```
## A. Agent reply - the OLTP/OLAP framing flip (data architecture)

### The framing flip

"OLAP feeds OLTP for live trading" is half-right but mislocates the OLTP problem. You won't actually own the OLTP layer for the most critical state - your broker does. The broker (IBKR / Alpaca / whoever) is the authoritative system of record for orders, positions, cash, and fills. They've already solved the ACID problem for the parts that matter most (your money). Your system is a client of that OLTP system, not its source of truth.

That reshapes the question from "do I need Postgres?" into "what mutable state do I actually own, and how fast does it need to be?"

### What lives in each tier

```
+--------------------------------------------------------------+
|  Broker (IBKR / Alpaca / etc.)                                |  <- actual OLTP source of truth
|  - canonical positions, cash, order state machine             |     for orders, positions, cash
|  - native client_order_id idempotency                         |
|  - their problem to keep ACID, not yours                      |
+----------------+---------------------------------------------+
                 | API + WebSocket
                 v
+--------------------------------------------------------------+
|  Fast tier (DynamoDB)                                         |  <- small, mutable,
|  - idempotency keys for in-flight submissions                 |     sub-ms access
|  - in-flight orders cache (submitted, not yet acked)          |
|  - position cache (refreshed from broker, drift-monitored)    |
|  - precomputed features keyed by symbol                       |
|  - risk-limit current exposures                               |
+----------------+---------------------------------------------+
                 | append events
                 v
+--------------------------------------------------------------+
|  Lakehouse (S3 + Iceberg + DuckDB) - your current pattern     |  <- append-only,
|  - immutable event journal: decisions, submissions, acks,     |     research +
|    fills, reconciliations                                     |     analytics +
|  - market data history (batch-appended ticks)                 |     audit
|  - backtest features, model artefacts                         |
|  - reconciliation snapshots (drift evidence)                  |
+--------------------------------------------------------------+
```

### Why DynamoDB, not Postgres

For your specific case - single trading agent, single AWS account, single region, sole user - Postgres is the wrong answer despite being the safe-sounding one:

- **Single writer eliminates most OLTP wins.** You don't have concurrent writers racing for the same row. The reason Postgres exists (MVCC for concurrent transactions) is wasted on you.
- **You're AWS-serverless-native.** Adding RDS means an instance to patch, backup, monitor, snapshot, VPC, security-group, secret-rotate. That's operational debt for a one-person system that runs ~24 hours/day.
- **DynamoDB is already in your stack.** The ops portal allocates IDs via DynamoDB atomic counters. You know the operational model.
- **The query patterns are trivially key-value.** "Get order by client_order_id." "Get current position for AAPL." "Get features for symbol X." None of this needs joins or relational predicates.
- **Cost.** DynamoDB on-demand at your write rate is <$1/month. RDS micro is ~$15/month idle.
- **Conditional writes give you the OLTP primitive you actually need.** `PutItem` with `attribute_not_exists(client_order_id)` is the idempotency guarantee. `UpdateItem` with `condition: current_status = 'submitted'` is the state-machine guard. That covers 95% of what you'd want from Postgres' transactional semantics.

Where Postgres would start to make sense: multi-leg orders with FK integrity across child orders, complex pre-trade filters expressed as SQL predicates over a relational position model, or a team-of-engineers who reach for SQL by reflex. None of those apply.

### Where "OLAP feeds OLTP" is the right pattern

**Feature precomputation.** This is the legitimate version of your intuition:

- Nightly DuckDB job over Iceberg market data -> compute per-symbol features (rolling vol, momentum scores, formula outputs from PySR) -> write to DynamoDB keyed by symbol.
- During trading hours, the decision loop reads features sub-ms from DynamoDB.
- The DynamoDB feature table is a projection of an Iceberg snapshot - read-only from the trading loop's perspective, written only by the batch job.

This is a **feature store** pattern (Feast, Tecton are the named-products in this space, but you don't need them - DuckDB -> DynamoDB is the same shape). Crucially, the feature store is a one-way projection: writes always come from the batch lakehouse, never from the live loop. That keeps your append-only invariant intact for the data side while exposing a fast read surface for the decision side.

### Concrete write-paths in the live system

Decision loop, in order:

1. **Compute decision** - DuckDB query against feature table or in-memory. Append `decision` event to Iceberg (your existing ops pattern extended).
2. **Pre-trade risk gate** - read current exposure from DynamoDB position cache + proposed trade size + limits. Reject locally if breached. Append `risk_check` event to Iceberg.
3. **Generate client_order_id** - UUID. `PutItem` into DynamoDB orders table with `condition: attribute_not_exists(client_order_id)`. This is your idempotency anchor.
4. **Submit to broker** - pass `client_order_id` so the broker enforces idempotency too. Two-layer defence.
5. **On ack** - `UpdateItem` order status from `submitted` to `acked` with conditional check. Append `order_ack` event to Iceberg.
6. **On fill** - `UpdateItem` order status, update position cache in DynamoDB transactionally with the order update (DynamoDB supports cross-item transactions for this). Append `fill` event to Iceberg.
7. **Reconciliation loop (every N minutes)** - pull positions from broker, diff against DynamoDB cache, append `reconciliation` event. If drift > tolerance, file a critical recommendation via your existing portal. Drift is a bug; your existing rec workflow handles it.

Every state change produces an append to Iceberg. The DynamoDB tier is a materialised view of "current state" computed from the event stream, just realised in a fast store instead of recomputed each time.

### The state machine question

Order lifecycle is a DAG: `submitted -> acked -> (filled | partial | cancelled | rejected)`. You enforce it three places, in order of authority:

1. In the broker (they own the canonical lifecycle).
2. In DynamoDB conditional updates (`UpdateItem` with `condition: current_status IN ('submitted')`). This catches local races.
3. In application code (the trading loop checks state before transitioning).

This is exactly CD.12's discipline applied to a new table: stateful invariants live in handler code (and DynamoDB conditional writes), not in schema annotations.

### What to not do

- **Don't write to Iceberg from the hot path synchronously.** Iceberg commits are seconds-scale. Append via a buffered writer that batches every 5-30s, OR write the event to an SQS queue and let a Lambda batch-append. Your existing outbox pattern (`logs/.ops-outbox/`) is already the right mental model.
- **Don't try to make the lakehouse the live position store.** Snapshot isolation at second-scale freshness is wrong for trading decisions. The DynamoDB cache exists precisely because "current state" needs ms-fresh.
- **Don't hand-roll concurrency primitives.** DynamoDB transactions exist; use them for the order-update + position-update pair. Don't write a two-phase commit yourself.
- **Don't skip reconciliation.** Even with two-layer idempotency, network partitions can leave your local view divergent from the broker. A reconciliation loop is non-negotiable and the drift events are signal, not noise - file them as recs and analyse why.
- **Don't put live market data in Iceberg in real-time.** Stream WebSocket -> in-memory ring buffer for live decisions, batch-write to Iceberg every minute or so for history.
- **Don't introduce Kafka / Kinesis prematurely.** At single-agent volume you can do everything with SQS + Lambda. Kinesis costs more than it saves until you have multiple consumers of the same stream.

### What this looks like in your existing pattern language

You'd add roughly three new tables/components, all extending what you already have:

| New surface | Type | Pattern | Lives in |
|---|---|---|---|
| `orders` | mutable | DynamoDB, PK = client_order_id, conditional writes for state transitions | DynamoDB |
| `positions_cache` | mutable | DynamoDB, PK = symbol, refreshed from broker on schedule + after fills | DynamoDB |
| `features_serving` | mutable but write-from-batch-only | DynamoDB, PK = symbol, projection from Iceberg | DynamoDB |
| `ops_trade_events` | append-only SCD2 | Iceberg + your portal pattern, day-partitioned | Iceberg |
| `ops_reconciliations` | append-only SCD2 | Iceberg + portal, every reconciliation snapshot | Iceberg |
| (extend) `ops_recommendations` | already exists | Drift -> critical rec -> your existing /plan flow | Iceberg |

Notice what's not in that list: no Postgres, no extra OLTP infrastructure, no new write portal - DynamoDB writes go through a thin client, Iceberg writes go through your existing portal. The Single Portal Invariant stays intact for the lakehouse side; DynamoDB is the small mutable cache outside the portal because it's a derivative projection, not a write source. That distinction is the same one CLAUDE.md already makes about read caches vs the warehouse.

### When you'd revisit this

Replace DynamoDB with Postgres or Yugabyte if:

- You add multiple concurrent decision agents writing to the same positions (multi-strategy with shared book) -> still might be DynamoDB transactions, but Postgres becomes reasonable.
- Pre-trade filters require complex relational predicates ("reject any order that would create position correlated >0.7 with existing top-3 holdings by notional") -> SQL becomes nicer.
- You go multi-region for resilience -> Yugabyte or Aurora Global enters the conversation, but you'd be the only retail trader in the world with that requirement, so don't.

For ~years to come, the answer is DynamoDB + Iceberg + broker-as-OLTP. The discipline you've built around the lakehouse extends naturally; you're adding a small fast tier, not introducing a parallel architecture.

### TL;DR

- Broker is your OLTP source of truth for orders/positions/cash - let them solve ACID for the money.
- Add DynamoDB (not Postgres) as a thin fast tier for idempotency keys, in-flight order tracking, position cache, and feature serving.
- Lakehouse stays append-only for audit / research / market-data history - exactly your current pattern, extended with `ops_trade_events` and `ops_reconciliations`.
- The legitimate "OLAP feeds fast tier" pattern is feature precomputation: DuckDB batch -> DynamoDB projection, one-way.
- Reconciliation is non-negotiable; drift events surface through your existing recommendation pipeline.
- The Postgres reflex is a "team-of-engineers reflex." You're not a team; you're an AWS-serverless-native sole dev with an agent harness. Match the architecture to that reality.

---

## B. User question - "still confused on the trading layer"

> i think I'm still confused as to what the structure should be in order to reach the frontier. I've thought a lot about how the platform, obviously, and the RAG system will work - recursive self improvement fed from telemetry. the formulas, the market predictions, are firmly in my comfort zone - optimising combinations, grouping them, optimising those groups recursively, rigourous A/B testing, windowed and forward facing testing and all of that. but the actual TRADING I have not thought about much. what to do with the signal, how to scale the variables that don't go into the formulas etc. your explanations didn't make it much clearer unfortunately. all I know and agree with is that the iceberg and DuckDB route is for analytics and not live trading.

---

## C. Agent reply - the four-layer mental model

OK, useful diagnostic - you've conflated two different layers of the system and I was answering the wrong one. Let me reset.

You have rich mental models for Layer 1 (Alpha) and Layer 4 (Platform/RAG/telemetry). The gap is the two middle layers that translate a signal into actual trades: **Portfolio Construction** and **Execution**. These aren't data architecture problems - they're trading-system-design problems, and the industry has a standard mental model for them. Let me give you that model first, then we can talk architecture.

### The four-layer mental model

Every systematic trading system, from a hedge fund's $10B book to a retail Robinhood bot, decomposes into the same four layers. Most people new to systematic trading don't see the boundaries:

```
+----------------------------------------------------------------------+
|  Layer 1: ALPHA / SIGNAL GENERATION                                   |
|  Produces: a score per asset (expected return, direction+confidence,  |
|            ranking, or some scalar that says "I think this is hot")  |
|  Your domain. Formulas, models, PySR, ML, factor combinations.        |
+----------------------------------------------------------------------+
                              |
                              v  (score per symbol)
+----------------------------------------------------------------------+
|  Layer 2: PORTFOLIO CONSTRUCTION                                      |
|  Translates: signals + constraints + risk model -> target positions   |
|  Asks: "Given these scores, how much of each should I hold?"          |
|  Outputs: target portfolio (vector of weights or share counts)        |
+----------------------------------------------------------------------+
                              |
                              v  (target portfolio)
+----------------------------------------------------------------------+
|  Layer 3: EXECUTION                                                   |
|  Translates: target portfolio - current portfolio -> trades           |
|  Asks: "How do I get from where I am to where I want to be, given     |
|         transaction costs, slippage, and market microstructure?"      |
|  Outputs: orders sent to broker                                       |
+----------------------------------------------------------------------+
                              |
                              v  (fills, state changes)
+----------------------------------------------------------------------+
|  Layer 4: OPERATIONS / TELEMETRY / FEEDBACK                           |
|  Your other domain. Captures everything, feeds back into Layer 1.     |
+----------------------------------------------------------------------+
```

The "variables that don't go into formulas" you mentioned are **Layer 2 and Layer 3 parameters**. They're not less important than the alpha - at small to medium size, execution quality and risk discipline matter more than signal quality. Renaissance Medallion's edge is famously as much in execution and capacity management as in signal.

### Layer 2: Portfolio Construction - the layer you're missing

This is the part nobody talks about in retail-quant content and it's where most systematic strategies live or die. The job is: given a vector of alpha scores, produce a vector of target weights.

The canonical sub-problems:

**a) Position sizing - how much to bet on each signal.**

Choices, from simplest to most sophisticated:

- **Equal-weight top-N**: rank by signal, take top N, equal weight. Robust, almost embarrassingly hard to beat in practice.
- **Signal-weighted**: weight proportional to signal strength. Tempting but fragile - you'll overweight extreme signals that are often noise.
- **Kelly criterion**: mathematically optimal for log-wealth growth, but pathologically sensitive to estimation error in expected return. Don't use full Kelly. Ever.
- **Fractional Kelly (e.g., 1/4 Kelly)**: the practical version. Trades growth-optimality for robustness to bad estimates.
- **Risk parity**: weight inversely to volatility so each position contributes equal risk. Strong baseline; well-suited to systems with many bets of similar conviction.
- **Mean-variance optimization (Markowitz)**: maximize return for given risk. Mathematically clean, terrible in practice - extreme weight concentration on whichever asset's expected return you estimated highest, and your estimates are noisy.
- **Black-Litterman**: shrink your views toward a market-equilibrium prior. The grown-up version of mean-variance.

For v1, start with **equal-weight top-N** or **risk parity over top-N**. You will get embarrassingly close to whatever sophisticated thing you eventually build, and you'll learn what actually matters.

**b) Risk model - what's the covariance structure.**

Two extremes:

- Ignore it, equal-weight (works surprisingly well at small N).
- Estimate a full covariance matrix from rolling returns and use it for risk parity / MVO (gets noisy fast; needs shrinkage).
- Middle path: **factor-based risk model** (Fama-French style - exposures to market, size, value, momentum factors). Bloomberg PORT, Barra, Axioma all sell this. For your scale, Ledoit-Wolf shrinkage on a covariance estimate is sufficient.

**c) Constraints - the hard stuff that overrides alpha.**

- Max position weight (e.g., no single name > 5% of book).
- Max sector / industry exposure.
- Max gross exposure (sum of |weights|) and max net exposure (sum of signed weights).
- Liquidity constraints (can't hold > X days of average daily volume).
- Borrow constraints (for shorts - can the broker source the stock).
- Cash buffer (always hold >= Y% cash for opportunism and margin safety).
- Concentration constraints (e.g., max correlation of any pair).

These are pre-trade gates. Violating them is a bug - file a rec.

**d) Turnover control - how aggressively to rebalance.**

This is one of the highest-leverage decisions in retail-scale systematic trading and the literature underweights it. Rebalancing daily to your "optimal" portfolio churns capital and eats edge to transaction costs. Approaches:

- **Periodic rebalance**: monthly / weekly. Simple, low turnover.
- **Threshold rebalance**: only trade when target weight differs from current by > epsilon.
- **Turnover budget**: cap total turnover per period.
- **Cost-aware optimization**: penalize the trade-list size inside the portfolio construction step (Garleanu-Pedersen dynamic optimization is the academic version).

For v1, **threshold rebalancing with a generous epsilon** is a good default. You'll discover empirically that lowering epsilon past a point destroys returns - that's the transaction cost crossover.

**e) Drawdown / circuit-breaker logic.**

When the strategy is bleeding, do you keep trading? Three philosophies:

- **Never override the model** (Renaissance philosophy - the model has seen this before).
- **Volatility scaling** - scale down position size when realized vol spikes.
- **Hard circuit breaker** - if drawdown > X%, go to cash for Y days. Hated by purists, valuable for sole-dev sanity.

You're a sole developer with real money at risk. **Hard circuit breaker. Non-negotiable.** Tune it generously so it rarely triggers, but it must exist.

### Layer 3: Execution - the layer you can mostly ignore (for now)

At retail scale (sub-$1M, trading liquid US equities), execution is genuinely easy. You don't have market impact. You don't need VWAP/TWAP slicing. The right answer is boring and that's good news:

- **Order type**: marketable limit orders (limit price slightly through the spread). Avoids slippage on jumpy stocks; still fills near-instantly on liquid names. Never pure market orders for anything illiquid.
- **Timing**: avoid first and last 15 minutes of session unless your strategy specifically targets them. The volatility/spread cost outweighs the price discovery.
- **Frequency**: once per day, at a consistent time. Mid-morning is conventional. Reduces variance from intraday noise.
- **Slicing**: not needed at your size. A single marketable limit on most US equities fills in milliseconds.
- **Retries**: if rejected (margin, day-trade, halted), one retry after re-fetching state, then file a rec and stop.

Execution becomes its own discipline above ~$10M AUM trading single-name equities, or any size in less liquid markets (small caps, options, crypto altcoins). Until then: keep it boring, keep a slippage budget per trade, monitor realized vs expected slippage in your telemetry.

**The one execution decision that matters at any size**: do you trade on close or on open? Most academic backtests assume execution at close. Live, you typically execute at open the next day (or mid-morning). That gap is where backtest-to-live degradation lives. **Mirror in your backtest framework whatever you do live.**

### "Variables that don't go into formulas" - what they are and how to tune them

You named the right gap. There are three populations of parameters in the full system:

| Population | Examples | How they're tuned |
|---|---|---|
| **Alpha parameters** | lookback windows, formula coefficients, feature engineering choices | Your research loop - formula discovery, cross-validation, walk-forward |
| **Strategy parameters** | top-N count, rebalance threshold, target volatility, max position, drawdown trigger, holding period | Backtested as part of the full pipeline - alpha + portfolio construction together, on out-of-sample data |
| **Operational parameters** | order type, retry policy, reconciliation interval, latency budgets, slippage budgets | Tuned live with observation - you can't backtest these, you watch them in production telemetry and adjust |

**Critical insight: strategy parameters cannot be tuned by alpha-only backtests.** If you optimize your formula on raw returns, then bolt on portfolio construction, you've left edge on the table. The whole pipeline must be the unit of optimization - alpha + construction + transaction-cost model + risk gates - backtested together, parameters jointly tuned.

This is where "rigorous A/B testing, windowed and forward facing testing" you already do extends. You're testing the pipeline, not the formula. The formula is one knob among many.

### What "the frontier" looks like

Since you asked for industry-leading-architect framing, here's what the top tier looks like at each layer so you can see the staircase:

- **Layer 1 (alpha)**: 100+ orthogonal alpha signals combined via a meta-model. Not one formula - a portfolio of formulas with negative or low correlation. Your PySR loop should aim at the orthogonality, not just predictive power. Two signals that both work but are uncorrelated are worth more than one stronger signal.
- **Layer 2 (portfolio construction)**: convex optimization with explicit cost model, factor-risk constraints, turnover penalty, position-decay terms. Solved per rebalance with cvxpy or similar. Industry standard since ~2010.
- **Layer 3 (execution)**: ML-driven execution agents that schedule trades to minimize implementation shortfall, accounting for predicted intraday volume curves. JP Morgan's LOXM, Optiver's execution models, etc.
- **Layer 4 (telemetry)**: full attribution - what fraction of P&L came from alpha selection, sizing, execution, market beta, factor exposures. Brinson attribution or similar. Lets you know why the system made money this month, not just whether.

For a sole dev with appropriate humility, the realistic target is **Layer 1 frontier (your strength), Layer 2 mid-tier (risk parity + threshold rebalance + drawdown gate is fine), Layer 3 boring-correct, Layer 4 frontier (your other strength)**. Don't waste a year reinventing execution - it doesn't matter at your size.

### Minimum viable trading system, opinionated

If I were you and I wanted to go live in 6 months with something that's correct rather than clever:

- **Alpha**: your formulas produce a score per symbol per day. Top-N ranking, N=20.
- **Portfolio construction**:
  - Equal-weight or risk-parity over the top-N.
  - Hard constraint: no position > 7%, gross exposure <= 100% (long-only initially).
  - Threshold rebalance: trade only when target weight differs from current by > 2% absolute.
  - Drawdown circuit breaker: if 20-day return < -10%, go to cash for 10 trading days.
  - Cash buffer: 5% minimum.
- **Execution**:
  - Marketable limit orders, 5bps through the spread.
  - Submit at 10:00 ET daily.
  - Single retry on rejection; file rec on second failure.
- **Operations**:
  - Broker = source of truth (IBKR or Alpaca; Alpaca is friendlier for paper-trading first).
  - DynamoDB for in-flight orders, position cache, idempotency keys.
  - Iceberg/DuckDB for everything else, append-only.
  - Reconciliation every 30 min during session; drift -> critical rec.

This system is unfashionable, unoptimized, and **will make money if your alpha is real**. Build it, run it on paper for 3 months, then go live with small capital. The temptation will be to optimize Layer 2 before Layer 1 has proven itself live. Resist. Live performance vs paper-trading performance is the only honest evaluation; everything before that is research, not validation.

### What to read

You want this internalized, not just summarized. Three books, in order:

1. **Ernie Chan, "Algorithmic Trading: Winning Strategies and Their Rationale"** - pragmatic, builds the mental model layer by layer. Start here.
2. **Grinold & Kahn, "Active Portfolio Management"** - the canonical reference for Layer 2. Dense. Skim chapters 14-17 (portfolio construction, transaction costs).
3. **Marcos Lopez de Prado, "Advances in Financial Machine Learning"** - modern ML + finance; chapters on labeling, sample weighting, backtest overfitting are essential and most retail-quant content gets these wrong.

Skip anything by trading "influencers." Skip 90% of QuantPedia. The above three + reading hedge fund letters (Renaissance is opaque but AQR and Two Sigma publish openly) is sufficient.

### TL;DR

You're missing two layers, not data architecture. The signal-to-trade pipeline is **Alpha -> Portfolio Construction -> Execution**, and Portfolio Construction is the high-leverage middle layer that turns "this stock looks good" into "buy N shares." Your "non-formula variables" are strategy parameters (tuned by backtesting the whole pipeline jointly) and operational parameters (tuned by live observation). Start with embarrassingly simple choices at every layer; the frontier is reached by getting Layer 1 (your strength) right and not breaking the system with overengineered middle layers. The boring v1 above is closer to "frontier for your size" than you'd think.

---

## D. User question - follow-ups on Layer 2, execution, pipeline, repo

> that's fascinating and highly appreciated, thank you.
>
> I have some further questions:
>
> 1. you suggest to not overengineer layer 2, but wouldn't the ideal be to replicate a similar formula discovery to layer 1? where the ideal portfolio size is calculated using recursive optimisation given the layer 1 alphas? ah, thinking about it, I suppose the problem is that you can't distinguish alpha performance from portfolio distribution performance. could you go into that more to help my understanding?
> 2. the execution seems overly simplistic. surely it's better to have dynamic triggers for execution? filters and conditions that are, again, determined by recursive improvement? they would be formulas in themselves would they not? or do you mean the actual execution mechanics, calling an API etc., should be kept boring? if so, I'd agree with that
> 3. the end-to-end pipeline optimisation - yes this is important, I agree. what's the best way to design that? having multiple paper-trading pipelines and only escalating the best performer to live money? or having multiple live pipelines AND paper pipelines and weighting them on score?
> 4. I think I broadly agree with keeping it simple and then building up, but I want to ensure that every aspect can, eventually, be recursively optimised. as an industry leading architect, how do you propose i set the repo up for that?

---

## E. Agent reply - identifiability, execution policy, funnel, repo

Excellent questions - all four hit real structural decisions. Going deep on each.

### 1. Why Layer 2 isn't a formula-discovery problem (the identifiability question you half-caught)

You diagnosed the headline issue: you can't distinguish alpha from sizing performance. Let me unpack why that's structural, not just an annoyance.

**The signal-to-noise collapse at higher layers**

At Layer 1, your evaluation signal is rich: per-symbol-per-day prediction quality. If you're trading 500 names over 5 years, that's ~600,000 evaluation observations. Symbolic regression has a chance of finding real structure because the sample-to-parameter ratio is high.

At Layer 2, your evaluation signal is portfolio-level: returns of a rebalanced portfolio over time. If you rebalance weekly over 5 years, that's ~260 observations. You're trying to fit parameters with 2000x less statistical power. PySR or any symbolic regressor will eagerly find "formulas" - they'll be noise.

This is Lopez de Prado's "probability of backtest overfitting" in a nutshell. The number of independent hypotheses you can responsibly test against a backtest grows much slower than the number of parameters you'd like to tune. At Layer 2, you've already burned most of your statistical budget on Layer 1.

**The identifiability problem you spotted**

Concretely: you have alpha signal `s` and sizing function `f(s, theta)` producing weight `w`. Portfolio return is `w . r` where `r` is realized returns. If you optimize jointly over alpha-generation parameters and theta, the optimizer cannot decompose the gradient. A weak signal with aggressive `f` can produce identical historical returns to a strong signal with conservative `f`. The optimizer has no preference - but they have radically different out-of-sample behavior.

The aggressive-sizing-on-weak-signal version is the classic blowup pattern. It survives backtest because the noise happened to align. It dies live.

**Layer 2 has structural priors you should use, not discover**

Risk parity isn't a hypothesis. It's an identity: given a covariance estimate Sigma, the risk-parity weights are the solution to a specific convex optimization. Mean-variance optimization is the Markowitz solution to a known problem. Kelly is the analytic optimum under specific assumptions. These aren't formulas to discover; they're theorems to choose between.

The role of optimization at Layer 2 is **regime selection and hyperparameter tuning**, not formula discovery:

- Pick the regime: equal-weight / risk-parity / cost-aware MVO / Black-Litterman.
- Tune the regime's hyperparameters: shrinkage factor, lookback for covariance estimation, turnover penalty weight.
- Possibly: switch regime based on observed conditions (vol-regime-aware allocator).

The right tool here is **Bayesian optimization with strong priors** (Optuna, BoTorch), not symbolic regression. The search space is small, structured, and you have theoretical lower bounds on what each method achieves.

**The identifiability fix: layer-isolated attribution**

You evaluate Layer 1 with signal-quality metrics that don't depend on Layer 2:

- **IC (Information Coefficient)**: rank correlation between predicted and realized returns. Per-day, then averaged. Independent of sizing.
- **IR (Information Ratio of the signal)**: IC mean / IC std. Signal stability over time.
- **Quantile spreads**: top-decile minus bottom-decile realized return. Sizing-agnostic.
- **Hit rate with magnitude weighting.**

These metrics tell you "the signal is real, of strength X" without committing to a sizing rule. Now Layer 2 is a separate problem: given a signal of strength X, what's the best portfolio construction?

You can also flip it: run a fixed Layer 2 (e.g., risk-parity over top-20, no turnover penalty) and use full-portfolio metrics to compare alpha versions. As long as Layer 2 is held constant, differences are attributable to Layer 1.

This is **Brinson attribution** in spirit - decompose portfolio P&L into selection (Layer 1) vs sizing (Layer 2) vs execution (Layer 3) contributions.

**What you CAN optimize recursively at Layer 2**

Once you've conceded that Layer 2 isn't formula-discovery, there's still a real optimization surface:

- **Hyperparameters**: shrinkage, lookback, threshold epsilon, drawdown trigger, vol target. Optimized via Bayesian opt with walk-forward cross-validation (never i.i.d. splits in time series - always forward-walking).
- **Regime selection rules**: simple thresholds ("if 60-day realized vol > X, switch from risk-parity to equal-weight") - these are small parameterized rules, tuned the same way.
- **Meta-allocation across alpha versions**: if you have N alpha models, weighting them inside Layer 1 IS a Layer 1 problem; choosing which subset is consumed by Layer 2 IS a Layer 2 problem. The line blurs.
- **Constraint tuning**: max position weight, sector caps, turnover budget. These are tuned against backtests with explicit cost models.

Treat Layer 2 as a small, structured optimization problem with explicit theoretical baselines and 5-10 hyperparameters, not as 100s of free parameters. Anything more and you'll find spurious structure.

### 2. Execution - what's "boring" and what's optimizable

You read me right. Two separate things:

- **Execution mechanics** (API calls, order types, retries, state machine): boring. Don't optimize. The variance in outcomes is dominated by correctness, not cleverness.
- **Execution policy** (when to trade, conditional on what, with what size adjustments): there's real edge here, but it's tuned from live telemetry, not backtested.

**Why execution policy can't be backtested rigorously**

The fundamental problem: market impact and microstructure aren't in your historical data. The bid-ask spread you see in historical NBBO is what someone else paid. If you'd been there, the spread might have widened. Slippage is a function of liquidity at the moment of execution, and that's path-dependent and partly caused by your own action.

Backtest-derived execution rules systematically underestimate live execution costs. The right loop is:

1. Implement a simple execution policy (your boring v1).
2. **Log everything**: decision price, decision time, submission time, fill price, fill time, NBBO at each stage, spread, ADV, intraday vol.
3. Compute **implementation shortfall** per trade: `(fill_price - decision_price) * sign(side)` in bps.
4. Aggregate by buckets: time-of-day, spread quintile, ADV quintile, vol regime, side.
5. Surface anomalies as recommendations. Tune execution policy against the live cost curves you observe.

This is **Transaction Cost Analysis (TCA)**, an entire subfield. At your scale, the simple version is sufficient: keep a rolling slippage estimate per bucket, route around the costly buckets.

**Execution policy CAN have recursive components - but small ones**

Things that legitimately benefit from optimization, in roughly this priority:

- **Liquidity gating**: don't submit > X% of expected daily volume. X is tunable but starts at 1% and rarely needs to change.
- **Spread gating**: skip the trade if observed spread > Y bps. Y is tuned per symbol bucket from telemetry.
- **Volatility-conditional timing**: avoid the 5 minutes after major scheduled news events. Earnings calendars, FOMC, NFP.
- **Time-of-day buckets**: empirically, post-9:45 ET and pre-15:30 ET fills are cheapest for liquid US equities. Worth measuring on your own flow.
- **Order type selection**: marketable limit vs aggressive limit vs market - choice tuned by post-trade shortfall by type.

Notice these are rule-based with tuned thresholds, not learned formulas. **A neural network executing trades is exactly the wrong place to put ML for a retail-scale system.** The complexity-to-edge ratio is awful.

**The optimization signal IS available, post-hoc**

Per-trade implementation shortfall is a clean per-observation metric. Over a year you'll have hundreds-to-thousands of fills. That's enough to estimate cost curves per bucket and tune thresholds. It's NOT enough to train a deep model end-to-end. Match the model complexity to the data volume.

**Where execution policy belongs in the recursive loop**

Conceptually:

```
Live execution -> fill telemetry -> TCA aggregation -> cost-curve estimates ->
  Layer 2 cost model (used in next portfolio construction) +
  Layer 3 policy thresholds (used in next execution)
```

The TCA outputs feed back into Layer 2's cost-aware optimization, not just Layer 3. **Cost-aware portfolio construction is the bridge** - it makes Layer 2 turnover decisions sensitive to current execution conditions, not just an a priori cost model. This is where the recursive loop earns its keep: live execution telemetry -> calibrated cost model -> smarter rebalance decisions -> less turnover in costly regimes -> better realized returns.

### 3. Pipeline-level optimization design - staged promotion vs ensemble vs both

The honest answer: **both**, in a specific architecture. Let me name the failure modes first, because they kill more retail-quant systems than bad alphas do.

**The two killer biases**

**Selection bias on multiple testing.** If you run 100 paper pipelines and promote the best, you've selected for noise as much as signal. The expected Sharpe of the best of 100 i.i.d. zero-Sharpe pipelines over a year is ~2.5 - looks like an amazing system. Lopez de Prado's **deflated Sharpe ratio** corrects for this; for your sanity, also use **probability of backtest overfitting** as a check.

**Survivorship bias.** If you kill pipelines that perform poorly and don't include them in your statistics, your aggregate performance looks better than reality. Every pipeline that ever existed must be in your evaluation, dead or alive.

Both of these are statistical hygiene problems. They're solved by discipline, not architecture. But the architecture must make discipline easy and shortcuts hard.

**The recommended structure: multi-stage funnel + production ensemble**

```
                +-------------------------------------+
                |  Research backtest (cheap, 100s)    |
                |  - all candidate pipelines          |
                |  - walk-forward CV                  |
                |  - deflated Sharpe filter           |
                +-------------+-----------------------+
                              | promotion criteria (pre-registered)
                              v
                +-------------------------------------+
                |  Out-of-sample paper (5-10)         |
                |  - real-time data, simulated fills  |
                |  - minimum 3 months                 |
                |  - same code path as live           |
                +-------------+-----------------------+
                              | promotion criteria
                              v
                +-------------------------------------+
                |  Small live (3-5)                   |
                |  - real money, fixed small allocation|
                |  - minimum 3 months                 |
                |  - true cost discovery              |
                +-------------+-----------------------+
                              | ensemble weighting
                              v
                +-------------------------------------+
                |  Production ensemble (3-5 live)     |
                |  - capital weighted by performance  |
                |  - simple weighting rule (vol-scaled|
                |     equal-weight is a good default) |
                +-------------------------------------+
```

**Why all four stages**

Each stage corrects a specific bias:

- **Backtest**: Cheap exploration. Filters obviously broken pipelines. Cannot validate anything.
- **Paper**: Reveals data-pipeline bugs, real-time edge cases, look-ahead bias in your features. Cannot reveal market impact or execution friction.
- **Small live**: Reveals slippage, broker behavior, real fills. Cannot reveal full-scale market impact.
- **Full live**: The real deal.

**Skipping stages is the most common retail-quant failure mode.** Each stage discovers a different class of bug.

**Promotion criteria, pre-registered**

This is your Single Portal Invariant applied to strategy promotion. Define before the data exists:

- Minimum out-of-sample duration per stage (3 months minimum).
- Deflated Sharpe > 1.0 over the stage.
- Maximum drawdown < 15%.
- No more than 3 consecutive losing weeks.
- Win rate, profit factor thresholds.

Commit these criteria as ratified decisions (your CD pattern works perfectly here). Promotions become typed verbs: `promote_to_paper(strategy_id)`, `promote_to_live(strategy_id)`. The criteria check is built-in; the promotion fails if criteria aren't met. **You cannot override your own past self when the recent data feels good.**

**Production ensemble weighting**

The temptation is to be sophisticated: dynamic weighting by recent performance, regime-detection. Resist. Three reasons:

- Recent performance is mean-reverting noise at the timescales you can measure. Weighting by it adds drawdown.
- Dynamic weighting introduces correlation between your strategies (they all tilt the same way when one wins recently), defeating the diversification benefit.
- Simple ensembles are robust under regime change; clever ones fail badly when their detection rules break.

The boring-correct answer: **vol-scaled equal-weighted ensemble.** Each live pipeline gets `1/N * (target_vol / realized_vol_of_pipeline)` weight. Rebalanced monthly. Done.

You can graduate to performance-weighted later, but require a very high statistical bar for evidence that it helps.

**Concurrent paper trading alongside live**

Your second instinct - running paper pipelines simultaneously with live - is exactly right. They serve as:

- **Challengers** to live pipelines (champion-challenger framework).
- **Sanity checks**: if a paper pipeline using the same alpha as a live pipeline diverges materially in performance, you have an execution-quality problem to investigate.
- **Replacement candidates**: when a live pipeline degrades, you have warmed-up challengers ready, with statistical history.

The architectural cost is low: paper and live use the same code path with different broker adapters. The discipline cost is real: you must track and evaluate paper pipelines with the same rigor as live ones.

### 4. Repo structure for universal recursive optimizability

This is the architectural question and it ties everything together. You already have most of the machinery (versioned artefacts, append-only journal, Single Portal, agent-first design). The trading system extends it. Here's the pattern.

**The five-property test for "optimizable"**

For any component to participate in your recursive improvement loop, it needs to be:

1. **Parameterized** - explicit, typed inputs.
2. **Versioned** - every instantiation has a stable identifier.
3. **Composable** - clean input/output contracts at boundaries.
4. **Observable** - emits structured telemetry per invocation.
5. **Evaluable** - has a defined success metric, computable from telemetry.

Every layer of your system should pass all five. Hardcoded magic numbers fail #1. Anonymous functions fail #2. Tight coupling between layers fails #3. Hidden state fails #4. "I'll know it when I see it" fails #5.

**Component-as-versioned-artifact pattern**

Every layer's implementation is a named, versioned, Pydantic-typed artifact:

```python
class AlphaModelVersion(BaseModel):
    alpha_id: str          # human-readable: "momentum_12_1_v3"
    version_hash: str       # content hash of the model artifact
    inputs_schema: dict     # what market data it consumes
    outputs_schema: dict    # what shape signal it produces
    params: dict            # hyperparameters
    created_at: datetime
    source_commit_sha: str

class PortfolioConstructionVersion(BaseModel):
    pc_id: str             # "risk_parity_top20_v2"
    version_hash: str
    method: Literal["equal_weight", "risk_parity", "cost_aware_mvo", ...]
    params: dict           # shrinkage, lookback, threshold, etc.
    constraints: dict       # max position, sector caps, etc.

class ExecutionPolicyVersion(BaseModel):
    exec_id: str
    version_hash: str
    order_type: Literal["marketable_limit", "limit", "market"]
    thresholds: dict       # spread cap, ADV cap, etc.

class StrategyVersion(BaseModel):
    strategy_id: str
    alpha_ref: str         # alpha_id @ version_hash
    pc_ref: str
    exec_ref: str
    capital_allocation: Decimal
    stage: Literal["backtest", "paper", "live_small", "live_full"]
```

All four are `Annotated`-Pydantic with your CD.12 DQ markers. All four are Iceberg tables under your portal. A strategy is a composition of versioned components, not a monolith.

**Tables you'd add**

Extension of your existing ops/telemetry schema:

| Table | Purpose | Pattern |
|---|---|---|
| `strategies_versions` | Catalog of strategy compositions | SCD2, day-partitioned |
| `alpha_versions`, `pc_versions`, `exec_versions` | Component catalogs | SCD2, day-partitioned |
| `strategy_runs` | Each (strategy_id, date_range, environment) - backtest or live | Append-only |
| `signals` | Layer 1 outputs per (run_id, symbol, date) | Append-only, day-partitioned |
| `target_portfolios` | Layer 2 outputs per (run_id, date) | Append-only, day-partitioned |
| `orders` | Layer 3 submissions per (run_id, symbol, date) | DynamoDB cache + Iceberg journal |
| `fills` | Broker fills | Append-only, day-partitioned |
| `pnl_attribution` | Daily attribution by (run_id, layer) | Computed view |
| `tca_events` | Per-fill implementation shortfall | Append-only |
| `promotion_events` | Stage transitions, with criteria-check results | Append-only (your ratification pattern) |

Every row in every table has `strategy_version_id` lineage. You can trace any fill back to the exact alpha/pc/exec versions that produced it.

**The "same code path" architectural commitment**

This is the most important structural commitment and the one most retail systems violate:

**Backtest and live MUST use the same code path. The ONLY difference is the broker adapter.**

```python
class BrokerAdapter(Protocol):
    async def get_positions(self) -> dict[str, Decimal]: ...
    async def submit_order(self, order: Order) -> OrderId: ...
    async def get_fills(self, order_id: OrderId) -> list[Fill]: ...

class HistoricalSimulationBroker(BrokerAdapter): ...   # for backtest
class PaperBroker(BrokerAdapter): ...                  # for paper (real prices, fake fills)
class AlpacaBroker(BrokerAdapter): ...                 # for live
```

Everything above the broker adapter - alpha, portfolio construction, execution policy, telemetry, risk gates - is identical across backtest/paper/live. **Diverging code paths is the #1 source of backtest-to-live performance degradation.** Don't let it happen.

This implies: your backtest engine is part of the trading system, not a separate tool. It's the same engine running with a different broker.

**The pure-function discipline**

Every layer is a pure function over its versioned inputs:

```python
def alpha(market_state: MarketState, params: AlphaParams) -> Signal: ...
def construct_portfolio(signal: Signal, current_portfolio: Portfolio, params: PCParams) -> TargetPortfolio: ...
def plan_trades(target: TargetPortfolio, current: Portfolio, params: ExecParams) -> list[Order]: ...
```

No hidden state. Everything the function needs is in its arguments. State (current portfolio, in-flight orders) is read from the database at the start of each invocation and passed in.

This makes every invocation reproducible - given the same inputs, the same outputs. Critical for debugging live anomalies (replay the inputs from telemetry, get the same outputs).

**Telemetry-as-contract**

Every invocation of every layer emits a structured event with the same shape:

```python
class LayerInvocation(BaseModel):
    run_id: str
    strategy_version_id: str
    layer: Literal["alpha", "portfolio_construction", "execution"]
    component_version_id: str   # which alpha/pc/exec version
    invocation_time: datetime
    inputs_hash: str             # content-hash of inputs for reproducibility
    outputs_hash: str
    metrics: dict                 # layer-specific
    duration_ms: int
```

This is the agent surface for the recursive optimization loop. Your recommendation system reads from this table, identifies underperforming components, and files recommendations for improved versions.

**Promotion as a typed verb**

Mirroring `file_rec` / `update_rec`:

```python
def promote_strategy(
    strategy_id: str,
    from_stage: Literal["backtest", "paper", "live_small"],
    to_stage: Literal["paper", "live_small", "live_full"],
    evaluation_window: tuple[date, date],
    capital_allocation: Decimal,
) -> PromotionEventId
```

The function checks promotion criteria (which are themselves ratified decisions, your CD pattern) and either succeeds or returns a typed rejection with the failing criterion. You cannot manually override your own promotion criteria. If you decide to override, you must amend the criteria first - which means filing a decision via your portal, with rationale, that becomes part of the audit trail.

**Repo layout**

```
src/
  trading/
    types.py                  # Pydantic schemas for everything
    brokers/
      adapter.py              # Protocol definition
      simulation.py
      paper.py
      alpaca.py
    alpha/
      registry.py             # alpha_versions catalog
      models/
        momentum_12_1.py
        formula_pysr_v1.py
        ...
    portfolio_construction/
      registry.py
      methods/
        equal_weight.py
        risk_parity.py
        cost_aware_mvo.py
    execution/
      registry.py
      policies/
        boring_v1.py
        spread_gated.py
    risk/
      gates.py                # pre-trade hard checks
      circuit_breaker.py
    strategy/
      composition.py          # compose alpha + pc + exec -> strategy
      runner.py               # the main loop, broker-agnostic
    tca/
      shortfall.py
      aggregation.py
    evaluation/
      metrics.py              # IC, IR, Sharpe, deflated Sharpe, etc.
      attribution.py          # Brinson-style P&L decomposition
      promotion.py            # promotion criteria checks
scripts/
  trade.py                    # entry point: --strategy-id --env (paper|live)
  backtest.py                 # entry point: same engine, simulation broker
  tca_report.py
  promote.py
```

Symmetry with your existing repo's discipline: one file per component, components self-register, schema-as-code via Pydantic, every action goes through a typed verb in the portal.

**What you DON'T do in v1**

Important - to keep this advice realistic:

- **Don't build the recursive optimizer first.** Build one strategy, one composition of (alpha, pc, exec), get it through backtest -> paper -> live. Then add a second strategy alongside. Then add the optimizer that proposes new versions.
- **Don't pre-build "every component must be optimizable" before you have any component working.** The architecture should admit recursive optimization without forcing you to use it from day one.
- **Don't optimize the architecture for hypothetical strategies.** Build the strategies you actually want, and let the architecture emerge. Your existing repo demonstrates exactly this discipline already.

**How this composes with your existing system**

Everything plugs into what you already have:

- Decisions about strategy promotion go through `file_decision`.
- Failed promotion criteria, drift events, TCA anomalies all file recommendations via `file_rec`.
- Your `/plan` workflow handles "improve momentum alpha v3" the same way it handles "fix CI failure."
- Your executor (when reinstated) processes trading-system improvements the same way it processes platform improvements.
- The RAG-fed recursive improvement loop you've designed for the platform extends to the trading components - same telemetry table, same evaluation pattern, same promotion mechanism.

**The trading system isn't a new architecture. It's an extension of your existing recursive-improvement substrate to a new domain.** Every pattern you've ratified for the platform applies here: SCD2 versioning, Single Portal writes, Annotated-Pydantic schema, DQ-as-alarm, append-only journaling. The discipline you've built for managing platform recommendations is the discipline you'll need for managing strategy candidates.

### TL;DR

- **Layer 2 isn't formula discovery** - it's structured hyperparameter optimization with strong priors over well-known regimes. Use Bayesian opt, not PySR. The identifiability problem is solved by attribution: evaluate layers with metrics specific to that layer (IC for alpha, attributed P&L for portfolio construction), not by joint optimization.
- **Execution mechanics stay boring; execution policy gets tuned from live telemetry, not backtests.** TCA is the discipline, implementation shortfall is the metric, simple rule-thresholds are the implementation. Cost-curve estimates feed back into Layer 2's cost-aware optimization.
- **Pipeline optimization is a four-stage funnel**: backtest -> paper -> small live -> full live, with pre-registered promotion criteria you can't override on a whim. Production runs a small ensemble (3-5 strategies, vol-scaled equal-weight). Paper pipelines run continuously as challengers. Selection bias and survivorship bias are killed by statistical discipline, not architecture.
- **For universal recursive optimizability**, every component is a versioned, parameterized, observable, evaluable artifact (your CD.12 pattern extended). Same code path for backtest/paper/live with only the broker adapter swapped. Pure functions composed at the strategy level. Promotion as a typed verb with criteria-check baked in. This is your existing recursive-improvement substrate extended to a new domain - not a new architecture.

The thread underneath all four answers: **discipline first, optimization second.** The frontier isn't reached by clever algorithms applied to broken structure. It's reached by rigorous structure that admits clever algorithms when statistical power justifies them.

---

## F. User question - hedging, options, environments, platform/product separation

> I like those answers, they make sense to me and I'm going to pin this conversation for future reference. I have a few follow up questions that increase the scope:
>
> 1. where would hedging come into this? and broader - option trading in general?
> 2. given my desired, end-state platform architecture you have in your context from the roadmap, where do different environments come into this? as an industry leading architect, your insight into what industry leading practice is would be beneficial. each environment would have the full pipeline, except for the live trading. but how would that actually work? how is platform infrastructure improvement separated from product improvement when the platform improves the product?

---

## G. Agent reply - hedging, options, environments, contract-driven separation

Both questions hit deep architectural choices. Going in order.

## 1. Hedging and options - where they fit in the four-layer model

### Hedging

Hedging is not a new layer - it's a **Layer 2 (Portfolio Construction) concern with a specific constraint**. The thing being hedged is some unwanted *exposure* (market beta, sector exposure, currency, factor loading), and the hedge is a position that cancels that exposure while preserving the desired bet.

Concretely, hedging slots into Layer 2 as constraints or additional terms in the optimization:

| Hedge type | What it neutralizes | Layer 2 mechanism |
|---|---|---|
| Beta-neutral | Market beta of long book | Constraint: portfolio beta = 0 (short SPY/futures to balance) |
| Dollar-neutral | Net market exposure | Constraint: sum(weights) = 0 (long-short balanced) |
| Sector-neutral | Sector concentration | Constraint: net sector exposures = 0 |
| Factor-neutral | Exposure to Fama-French / Barra factors | Constraint: net factor loadings = 0 |
| Currency-hedged | FX exposure on foreign assets | Add inverse FX position sized to portfolio's FX exposure |
| Pairs / relative-value | Symbol-specific noise; isolates spread | Long A / short B with size ratio chosen to cancel common factor |
| Tail hedge | Catastrophic drawdowns | Separate "insurance sleeve" - usually long OTM puts or VIX calls |

The first six belong inside Layer 2's optimization - they're just additional linear constraints on the weight vector, and any convex solver (cvxpy) handles them natively. **You don't bolt them on; you add them to the constraint set.**

The seventh - tail hedging - is structurally different and lives outside Layer 2. It's an *insurance overlay*, expected to lose money in normal times, sized as a fraction of capital, evaluated by drawdown reduction not return contribution.

### The "hedge vs size down" decision

This is a high-leverage question most retail-quant content skips. You always have a choice:

- **Hedge**: keep gross exposure constant, neutralize an unwanted risk via offsetting position.
- **Size down**: reduce gross exposure until total risk is acceptable.

Hedging *costs*: bid-ask on hedge instruments, financing costs (especially shorts), basis risk (hedge correlates imperfectly with what you're hedging), operational complexity. **Sizing down is free.**

You hedge when:
- You have *very high conviction* on alpha but want to isolate it from a specific factor (classic equity long/short fund argument).
- The instrument-specific edge you're trying to capture is small relative to overall market noise, so sizing down would shrink alpha below execution costs.
- You face leverage constraints - you want to hold $1M of stocks, but only have $100k of capital and can't use margin economically for the *whole* position.

You size down when:
- Your alpha is moderate and noisy.
- You're at retail scale where execution costs and operational overhead of hedging eat the benefit.
- You don't have a factor model rigorous enough to know what factor you're actually hedging.

**For your scale and your stage: size down. Hedging adds operational surface area without commensurate edge.** Revisit when you have a factor model you trust and an alpha whose Sharpe survives a halving from hedging costs.

The exception worth considering early: **a small tail hedge sleeve** (1-3% of capital in long OTM puts) if it lets you psychologically tolerate larger alpha-book sizing. The expected return of the hedge is negative; the value is in changing your own behavior under drawdown. Treat it as a behavioral instrument, not an edge instrument.

### Options trading more broadly

Options are *not* an extension to your stock system. They're a different discipline. Architecturally, they reuse some infrastructure (brokers, telemetry, ops journal) but introduce concepts the stock system doesn't have.

The fundamental difference: an options position has **non-linear, multi-dimensional risk exposure** - the Greeks:

- **Delta**: directional exposure (changes with underlying price *and* time *and* implied vol).
- **Gamma**: how delta changes (curvature; the killer in short-gamma positions).
- **Vega**: exposure to implied volatility changes.
- **Theta**: time decay (positive for short option, negative for long option).
- **Rho**: interest rate sensitivity (mostly negligible at retail scale).
- (Higher-order: vanna, vomma, charm - only matter at scale.)

A stock book has one risk per position: shares x delta(=1). An options book has five risks per position, all non-linear, all interacting, all time-varying. Portfolio construction at Layer 2 changes from "aggregate weights" to "aggregate Greek exposures across positions." Risk gates change from "max % per name" to "max gamma per name, max vega per term, max theta cost per day."

The four common use cases for options, with architectural notes:

| Use case | What it is | Where retail edge exists | Where it doesn't |
|---|---|---|---|
| **Tail hedging** | Long OTM puts as catastrophe insurance | Behavioral / sizing benefit | Not a profit center |
| **Covered calls / cash-secured puts** | Sell premium on stocks you'd hold anyway | Mild yield enhancement, simple to operate | Caps upside; not a strategy in itself |
| **Directional speculation with leverage** | Buy calls/puts on a stock view | Sometimes, when stock vol is mispriced | Mostly retail loses to bid-ask + theta + IV crush |
| **Volatility trading** | Bet on IV-vs-realized-vol divergence, vol surfaces | Specific event-driven trades (earnings, mergers) | Generic vol trading is dominated by professional vol desks |

**Honest assessment for a sole quant**: covered calls and cash-secured puts are operationally simple yield enhancers on a stock book. Tail hedging is a sizing tool. Directional/vol speculation through options is genuinely hard to make money in at retail - you're trading against professional market makers with co-located systems, real-time IV surfaces, and orders of magnitude better risk infrastructure. The edge gradient toward institutions is *steeper* in options than in equities.

### Architectural extensions for options

If/when you add options, the additions are:

1. **Instrument schema**: extend your instrument types to include options with their full identifier (underlying, expiry, strike, type, multiplier, OCC symbol).
2. **Pricing model**: Black-Scholes for European, binomial / Bjerksund-Stensland for American, or just trust broker mid-quotes. Don't build your own surface unless you're trading vol.
3. **Greeks calculation**: per-position Greeks computed at decision time. Aggregated at portfolio level for risk gates.
4. **Portfolio construction extension**: Layer 2's target portfolio becomes a vector of (instrument, quantity) where instruments include options. Constraints expand to Greek limits.
5. **Risk gates** (additional, mandatory):
   - Max portfolio gamma (sudden delta changes can blow up sizing).
   - Max portfolio vega per expiry bucket.
   - Max theta cost per day (limits insurance bleed).
   - Pin risk monitor (positions near strike at expiry).
   - Assignment risk monitor (short ITM American options).
6. **Multi-leg execution**: spreads (verticals, calendars, condors) submitted as single multi-leg orders to avoid leg-risk. Your execution policy gets more complex.
7. **Expiry handling**: positions either close, exercise, get assigned, or expire worthless. State machine has new terminal states. Reconciliation includes post-expiry sweeps.

**Defer options until your stock system is live, stable, and you have a specific options strategy with a tested hypothesis.** Adding options before then is scope creep that delays the harder thing (proving the stock system makes money live). Options on the roadmap as Phase 2 is the right place.

## 2. Environments - industry-leading practice

You said "each environment has the full pipeline except for live trading." I'd refine that: **each environment has the full pipeline *including* execution**, but execution targets a different broker adapter (simulation / paper / live-small / live-full). Live trading isn't *absent* from non-live environments - it's *simulated*. This matters because if execution code only runs in live, you discover execution bugs in live, which is the worst possible discovery point.

### The environment taxonomy industry actually uses

Hedge funds and serious quant systems differentiate environments along multiple axes, not just "is this real money":

| Environment | Code | Data | Broker | Capital | Telemetry destination |
|---|---|---|---|---|---|
| **Research** | Pre-merge, exploratory | Production historical, read-only | None | None | Research sandbox |
| **Backtest-canonical** | Merged, versioned | Frozen canonical dataset | Simulation broker | Notional | Backtest results table |
| **Paper** | Merged, versioned | Real-time market data | Paper broker (real prices, fake fills) | Notional | Production telemetry (tagged paper) |
| **Live-small** | Merged, versioned | Real-time market data | Live broker | Small allocation | Production telemetry |
| **Live-full** | Merged, versioned | Real-time market data | Live broker | Full allocation | Production telemetry |

Key invariants industry-leading firms enforce:

1. **Same code path across all environments.** Only the broker adapter and config differ. This is the single most important commitment; everything else follows from it.
2. **One-way data flow.** Production telemetry flows *into* research (for evaluation). Research never writes to production tables. This isolates exploration from operations.
3. **Capital allocation is the production gate.** What makes "live-full" different from "live-small" isn't a code change - it's a capital allocation parameter. Promotion is a config change, not a deploy.
4. **Backtest data is frozen.** Canonical backtest dataset is immutable, versioned, and survivor-bias-corrected. "I re-ran the backtest and got different numbers" is a bug, not a feature.
5. **Paper trading uses production infrastructure.** Same broker adapter abstraction, same telemetry pipeline, same monitoring. Paper failures must be debuggable with the same tools as live failures.
6. **Promotion is a typed action with an audit trail.** Strategy promotions are logged events with criteria-check evidence, not implicit consequences of someone running a command.

### How environments map to infrastructure

Industry's three architectural patterns, in increasing isolation:

**Pattern A: Multi-account isolation** (hedge fund standard).
Each environment is a separate AWS account. Research, backtest-canonical, paper, live each have dedicated accounts with cross-account roles for the controlled data flows. Maximum blast-radius containment; high operational overhead.

**Pattern B: Multi-VPC / multi-namespace within one account**.
Single AWS account with strict VPC separation, IAM role separation, S3 prefix separation, separate IAM principals per environment. Medium isolation, medium overhead.

**Pattern C: Prefix-and-IAM isolation within one account**.
Single account with naming conventions (`research-`, `paper-`, `live-`) and IAM policies enforcing access boundaries. Easiest operationally; weakest isolation.

**For a sole developer in a personal AWS account: Pattern C is correct.** Your CD.6 already commits to single-account. The cost of pattern A is multiple AWS bills, multiple SSO logins, multiple sets of credentials. Not worth it for one person.

But Pattern C only works if you enforce the *logical* isolation rigorously:

- Iceberg tables prefixed: `research_strategy_runs`, `paper_strategy_runs`, `live_strategy_runs`. Or partitioned with `environment` as a first-class partition key.
- DynamoDB tables prefixed similarly.
- Separate IAM roles for research / paper / live processes, with policies that only allow writes to their environment's prefix.
- Broker credentials in separate Secrets Manager entries, accessed only by the matching environment's IAM role.
- The "research" role can READ live telemetry but cannot WRITE to live tables. Asymmetric permission, enforced at IAM.

This gives you the *invariants* of multi-account isolation (one-way data flow, write-isolation) without the *overhead* (multiple accounts).

### The environment-as-config pattern

The right architectural commitment is: **an environment is a config bundle, not a deployment**. Same binary, different config.

```python
class EnvironmentConfig(BaseModel):
    environment: Literal["research", "backtest", "paper", "live_small", "live_full"]
    broker_adapter: Literal["simulation", "paper_alpaca", "live_alpaca", "live_ibkr"]
    data_source: Literal["historical_iceberg", "real_time_polygon", "real_time_broker"]
    capital_allocation: Decimal
    table_prefix: str
    iam_role_arn: str
    risk_gate_overrides: dict       # tighter limits in early stages
    promotion_criteria: PromotionCriteria
```

The same `python -m trading.run --strategy-id X --env paper` and `--env live_small` invoke identical code paths. The config is loaded from a versioned, ratified config file (your existing CD pattern). Promotion is "change the env, run again" - there's no separate live-vs-paper code to deploy.

Industry firms call this **deploy-once, configure-per-environment** and it's load-bearing for trustworthy operations.

### Telemetry across environments

Production telemetry is environment-tagged but in a single logical table (or partition):

```sql
SELECT strategy_id, environment, AVG(sharpe), MAX(drawdown)
FROM strategy_runs_telemetry
WHERE date >= current_date - INTERVAL 90 DAYS
GROUP BY strategy_id, environment;
```

This lets you compare paper-vs-live for the same strategy, detect drift between simulated and real fills, and feed all environments into the same evaluation pipeline. The environment column is the natural partition for promotion logic ("if paper Sharpe >= 1.2 over 90d -> eligible for live_small").

### What runs continuously vs on-demand

- **Research**: on-demand, interactive (you running queries, exploring).
- **Backtest-canonical**: on-demand, triggered by new strategy versions or CI checks.
- **Paper**: continuous, mirrors live trading hours. Same scheduler as live.
- **Live-small / live-full**: continuous, market hours only.

All four "continuous" components share the same orchestration code. Paper-vs-live differs only in broker adapter and capital allocation parameter.

## 3. Platform/product separation when platform improves product

This is genuinely the hardest architectural question you've asked, and the answer is the same answer enterprise platform engineering has converged on over the last decade. Let me build it up.

### The naive view that fails

Naive framing: "platform changes are infrastructure; product changes are strategies." But platform improvements *enable* product improvements - a better executor means better strategies can be deployed, a faster query layer means feature pipelines can be richer, a stronger DQ system means strategies trust their inputs more. So platform changes *do* change product behavior, transitively.

How can the two be separated if one changes the other?

### The right framing: **contract-driven separation**

The platform exposes a **set of contracts** to the product. The contracts are typed, versioned, documented. The product consumes contracts. The platform's freedom is bounded by its contracts; the product's behavior is bounded by what contracts it consumes.

A platform change is **transparent** if it preserves contracts. A platform change is **breaking** if it changes contracts.

| Platform change type | Effect on product | Coordination required |
|---|---|---|
| Performance improvement that preserves contract | Product sees same outputs, faster | None - pure platform tier work |
| New capability added (additive contract) | Product can opt in if it wants the capability | None for platform ship; product change is separate plan |
| Bug fix that changes outputs | Product sees different outputs from same inputs | Coordination required; treat as breaking change |
| Contract change (schema, semantics) | Product must adapt | Two-phase: platform ships compat layer; product migrates; old contract retired |

This is exactly Stripe's API versioning model, AWS API stability commitments, the Linux kernel's syscall stability - all of which are platform/product separation at industrial scale. **The unit of separation is the contract, not the code.**

### What this means in your repo

You already have the substrate. Let me name where contracts live:

- **Iceberg table schemas** (Pydantic-defined per CD.12) - contracts between platform writers and product readers, AND between product writers and platform analytics.
- **Typed portal verbs** (`file_rec`, `log_decision`, etc.) - contracts between agents and the ops layer.
- **Lambda Function URLs with AWS_IAM** (CD.10) - contracts at the network surface.
- **The four-layer trading interface** (`alpha(market_state, params) -> Signal`, etc.) - contracts between strategy layers.
- **Broker adapter Protocol** - contract between trading system and execution destination.

Each of these is a place where the *platform* offers a guarantee and the *product* consumes it. Platform engineering = improving the implementation behind the guarantee. Product engineering = building things that consume the guarantee in new ways.

### When platform improvements unlock product improvements

The two-phase pattern:

**Phase 1 (Platform tier): Ship the capability under a new or extended contract.**
- Existing contracts unchanged.
- New contract documented, schema-typed, validated, observable.
- Backward-compatible by default.
- Platform tier item; lives in ROADMAP-PLATFORM.yaml.
- Validated by *platform-tier metrics*: schema validates, latency budget met, monitoring in place. Strategy P&L is NOT a platform validation metric.

**Phase 2 (Product tier): Consume the new contract to do something the product previously couldn't.**
- Separate plan, separate validation.
- Validated by *product-tier metrics*: improved Sharpe, reduced drawdown, faster signal-to-trade.
- Product tier item; lives in ROADMAP-PRODUCT.md.
- Depends on Phase 1 having shipped (the existing `depends_on` machinery handles this).

The roadmap document already says ROADMAP-PLATFORM and ROADMAP-PRODUCT are *siblings, not parent/child*. That's the right model. They are two roadmaps over two domains, with cross-references where one depends on the other.

### Concrete example walk-through

Suppose you want to enable cost-aware portfolio construction (Layer 2 with explicit transaction cost model).

**Phase 1 - Platform**:
- Extend telemetry schema to capture per-fill implementation shortfall (new optional fields, backward-compatible).
- Add a TCA aggregation job that computes cost curves from fill telemetry.
- Expose typed verb: `get_cost_curve(symbol_bucket, time_bucket) -> CostCurve`.
- Ship behind a flag if cautious; otherwise just add it.
- Validation: schema validates, cost curves produce sane outputs, latency under 100ms.
- *No change to existing strategy behavior.* Strategies haven't started consuming the curve yet.

**Phase 2 - Product**:
- Define a new Portfolio Construction version that consumes `get_cost_curve` and uses it as a turnover penalty in optimization.
- Backtest it. Paper trade it. Promote it through stages.
- Validation: improved Sharpe net of costs vs the existing cost-unaware version.
- *Old strategies unchanged.* The new strategy is a *new version*, not a replacement; ensemble may run both during evaluation.

The platform ratifies "we now have cost curves." The product ratifies "we use them in strategy v17." Two independently-validatable changes, two independent cadences, two independent roadmaps.

### Why this separation actually matters operationally

Without separation, you can't answer the diagnostic question that comes up six months in:

> "Strategy v17 underperforms v12 in live. Is the alpha worse? Did portfolio construction change? Did execution get more expensive? Did a platform change subtly alter the inputs?"

Without contract boundaries and version tracking at each layer, this question is unanswerable. You'll spend weeks bisecting. With them, you can ask:

- Did the alpha-version change? (Layer 1 contract).
- Did the PC-version change? (Layer 2 contract).
- Did the exec-version change? (Layer 3 contract).
- Did any platform component used by these layers change implementation behind a stable contract? (Platform changelog).

This is the same logic as your existing ratified-decisions discipline: **the system must explain why it behaves the way it does**. The platform/product contract boundary is the place where the explanation chain terminates cleanly.

### The cadence difference

Industry pattern: platform and product engineering operate at different cadences and risk tolerances:

| Dimension | Platform | Product |
|---|---|---|
| Cadence | Deliberate, slower | Iterative, faster |
| Risk tolerance | Low (breaking the platform breaks everything) | Higher (one strategy underperforming is local) |
| Validation | Structural correctness, latency, observability | P&L, drawdown, Sharpe |
| Reversibility | Often hard (schema migrations) | Usually easy (deprecate strategy version) |
| Decision mechanism | Ratified decisions (your CD pattern) | Promotion criteria + post-hoc evaluation |
| Ownership at scale | Platform team | Strategy/research team |
| For a sole dev | Same person, different mindset | Same person, different mindset |

You'll need to context-switch deliberately between these modes. Tell yourself "I'm in platform mode this week" or "I'm in product mode this sprint." The discipline of the right validation lens is what keeps the two streams from contaminating each other.

### When the boundary blurs

The honest case: sometimes a platform improvement *requires* knowing how the product uses it. "How fast should the query layer be?" depends on what strategies need it. "What's the right schema for feature serving?" depends on what features strategies want.

The industry pattern: **platform engineering treats product engineers as customers**. You design the platform for the demands the product has, but you don't co-build them. Product requirements inform platform design; platform implementation is independent.

In your sole-dev context: when you're sketching a platform change, put on the product-customer hat and ask "as a strategy author, what would I want from this contract?" That's the requirements-gathering phase. Then take off that hat and put on the platform-engineer hat to design the implementation. The hats are mental, not organizational, but the discipline of separating them is what produces a clean contract.

### The roadmap implication

Your roadmap structure already supports this cleanly. The fact that ROADMAP-PLATFORM and ROADMAP-PRODUCT are siblings means:

- A tier item's "tier" tells you which roadmap it's on (platform vs product).
- A tier item's `depends_on` can cross roadmaps (e.g., product tier item depends on platform tier item).
- Ratified decisions categorize as platform-domain or product-domain (you can add a `domain` field to CD schema if useful).
- Plans declared at intake time are either platform-tier or product-tier - affects validation criteria, affects which roadmap consumes the plan's output.

The infrastructure you have is sufficient. The discipline is: when authoring a plan, *explicitly tag it* as platform or product, and apply the right validation lens.

## TL;DR

1. **Hedging is Layer 2 constraints, not a new layer.** For your scale, prefer sizing down over hedging until you have a factor model worth trusting. A small tail-hedge sleeve has behavioral value (lets you size alpha larger) but isn't a profit center. **Options trading is a separate discipline**, not an extension. Each options position has 5 risk exposures (Greeks); portfolio construction and risk gates change shape. Defer until the stock system is live and stable, and only if you have a specific options hypothesis.

2. **Environments are a config bundle, not a deployment.** Same code, different broker adapter and capital allocation. Five-stage taxonomy (research / backtest / paper / live-small / live-full) with same-code-path and one-way-data-flow invariants. Single AWS account with IAM + prefix isolation is correct for sole-dev; multi-account is industrial overkill.

3. **Platform/product separation is contract-driven, not code-driven.** Platform owns the contracts (schemas, typed verbs, broker Protocol). Product consumes them. Platform improvements that preserve contracts are transparent; new capabilities ship as additive contracts in Phase 1; product consumes them in a separate Phase 2 plan. Your existing roadmap structure (PLATFORM and PRODUCT as siblings, with `depends_on` cross-references) already supports this. The discipline is *which validation lens you apply* - platform validates structural correctness, product validates P&L. Same person, different mindset, different tier.
```

---

## 12. End of prompt

If you (the auditor) have questions about ANY of the above, raise them
via `AskUserQuestion` BEFORE starting the fan-out. Subagent fan-out is
expensive; do not start it with ambiguity in the brief.
