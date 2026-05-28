# Plan

## Intent
Establish the foundational data architecture for a recursively self-improving trading system by removing interpretability as a constraint, adopting encoder-based feature compression, and enabling unlimited data source growth without proportional discovery cost increases -- aligning with industry-leading automated trading system patterns. This is a key architectural inflection point that requires extensive scoping and documentation to ensure all future agents have full context.

## Plan Type
IMPLEMENTATION

## Branch
agent/1.5-scalable-feature-architecture

## Phase
Phase 1.5: Schema Flattening, Deltas & Backfill

## Scope
| File | Action | Purpose |
|------|--------|---------|
| docs/DECISIONS.md | Modify | Add Decision 41: Scalable Feature Architecture |
| docs/ARCHITECTURE.md | Modify | Add three-layer feature architecture section |
| logs/.recommendations-log.jsonl | Modify | Add researched and scoped implementation recs |
| logs/.recommendations-log.jsonl | Modify | Triage legacy recs (1-50) with status updates |
| docs/plans/briefings/ | Create | Briefing files for complex recs requiring detailed spec |

## Bundled Recommendations
None -- this plan generates new recommendations for the `/develop-executor` workflow.

## Deliverables

### Part 1: Decision 41 -- Scalable Feature Architecture (Decided)

Add the following decision to `docs/DECISIONS.md`:

---

**Decision:** Adopt a three-layer data architecture (Raw -> Encoder -> Discovery) that removes interpretability as a constraint, enables model-agnostic discovery, and ensures constant discovery cost regardless of raw feature count.

**Problem:**
The current Phase 1.5 schema design hardcodes ~35 native columns with specific deltas (delta_price_1d, zscore_rsi_30d, etc.). This approach has scaling limits:
1. Adding new data sources requires schema changes and explicit delta definitions
2. Discovery cost scales with feature count (PySR explores O(features x depth x population))
3. At 1,000+ features, discovery becomes the compute bottleneck, not storage
4. Implicit assumption that formulas must be human-interpretable limits model diversity

**Industry context:**
Top quantitative firms (Renaissance, Two Sigma, Citadel) do NOT require interpretability for trading signals. They optimize for returns, not explanation. Interpretability is a human need, not a system need. Regulatory requirements (MiFID II, SEC) apply to client-facing asset management, not proprietary trading.

**Architecture (three-layer):**

```
RAW LAYER (Athena/Iceberg, append-only, normalized)
  market_data_raw, sentiment_raw, fundamentals_raw, alt_data_raw
  - Universal transforms applied automatically (all windows x all numeric columns)
  - 1,000+ columns over time -- storage is cheap
            |
            v
ENCODER LAYER (VAE or Transformer, trained daily/weekly)
  Input: 1000+
  Output: 64-128 latent dims
            |
            v
DISCOVERY LAYER (model-agnostic)
  PySR (symbolic), LightGBM, Attention NN, Future models
            |
            v
UNIFIED EVAL (Sharpe, DD, win rate)
```

**Key design principles:**
1. **Interpretability is not a constraint** -- the system evaluates models by performance metrics (Sharpe, drawdown, win rate), not human understanding. SHAP/attention weights provide debugging capability without requiring interpretable formulas.
2. **Universal transforms** -- global config defines windows (1d, 3d, 7d, 14d, 30d) and transforms (pct_change, zscore, ema_diff, rank_percentile) applied to ALL numeric columns automatically.
3. **Encoder absorbs feature growth** -- adding 100 new raw features has zero marginal discovery cost; encoder compresses to fixed 64-128 latent dimensions.
4. **Model-agnostic discovery** -- PySR, LightGBM, neural networks, and future models all compete on the same evaluation metrics. No model type is privileged.
5. **Automated pruning** -- weekly job removes features with >95% correlation or zero usage in winning models over 8 weeks.

**Trade-offs accepted:**
- Latent dimensions are not directly interpretable (debugging via SHAP/attention instead)
- Encoder training adds compute cost (~$0.10-0.50/day on Lambda/SageMaker)
- Initial implementation requires new infrastructure (encoder training pipeline, attention layer)

**Implementation path:**
1. Add `config/features.yaml` with global transform config
2. Create `src/data/transform_engine.py` for universal transform generation
3. Create `src/models/encoder.py` for VAE/Transformer encoder
4. Create `src/models/attention.py` for supervised attention layer
5. Update `src/lab/pysr_factory.py` to consume latent + attention-selected features
6. Add parallel discovery runners (LightGBM, neural attention)
7. Unified evaluation in `src/lab/model_evaluator.py` (Sharpe, DD, win rate)

**Related:** Phase 1.5 (schema flattening), Phase 2 (formula integration), Decision 40 (Copilot SDK migration deferred)

**Decision status:** Decided -- April 2026

---

### Part 2: Recommendations for `/develop-executor`

The following recommendations should be filed to `logs/.recommendations-log.jsonl` for executor implementation:

#### rec-201: Universal transform config schema
- **file:** `config/features.yaml`
- **effort:** S
- **priority:** High
- **context:** Define global_transforms (windows, transforms), exclude_patterns, and pruning rules. This is the source of truth for feature generation -- no hardcoded delta definitions.
- **acceptance:** `python -c "import yaml; yaml.safe_load(open('config/features.yaml'))"`

#### rec-202: Transform engine implementation
- **file:** `src/data/transform_engine.py`
- **effort:** M
- **priority:** High
- **context:** Reads features.yaml, generates all window x transform combinations for all numeric columns in raw tables. Outputs to feature_vectors_raw Iceberg table (~1000+ columns).
- **acceptance:** `python -m pytest tests/test_transform_engine.py -q`
- **dependencies:** [rec-201]

#### rec-203: VAE encoder implementation
- **file:** `src/models/encoder.py`
- **effort:** L
- **priority:** High
- **context:** Variational Autoencoder that compresses 1000+ raw features to 64-128 latent dimensions. Trained daily/weekly on Lambda or SageMaker. Saves encoder weights to S3.
- **acceptance:** `python -m pytest tests/test_encoder.py -q`
- **dependencies:** [rec-202]

#### rec-204: Attention layer for feature selection
- **file:** `src/models/attention.py`
- **effort:** M
- **priority:** Medium
- **context:** Lightweight attention head that learns which raw features predict next-day return. Outputs top 30-50 attention-selected columns alongside latent dims. Provides SHAP-like debugging without interpretability constraint.
- **acceptance:** `python -m pytest tests/test_attention.py -q`
- **dependencies:** [rec-202]

#### rec-205: Feature vectors table (latent + attention)
- **file:** `terraform/iceberg_tables.tf`
- **effort:** S
- **priority:** High
- **context:** New Iceberg table `feature_vectors` with fixed schema: timestamp, symbol, latent_1..latent_128, plus 30-50 attention-selected raw columns. This is what discovery consumes.
- **acceptance:** `grep -q 'feature_vectors' terraform/iceberg_tables.tf`
- **dependencies:** [rec-203, rec-204]

#### rec-206: Model-agnostic discovery runners
- **file:** `src/lab/discovery_runner.py`
- **effort:** L
- **priority:** Medium
- **context:** Parallel discovery runners (PySR, LightGBM, attention NN) all consuming feature_vectors table. Each runner outputs candidate models with metadata (type, complexity, training metrics). Requires pysr_factory tests (rec-209) before modifying that file.
- **acceptance:** `python -m pytest tests/test_discovery_runner.py -q`
- **dependencies:** [rec-205, rec-209]

#### rec-207: Unified model evaluator
- **file:** `src/lab/model_evaluator.py`
- **effort:** M
- **priority:** Medium
- **context:** Evaluates all candidate models from any runner using identical metrics: Sharpe ratio, max drawdown, win rate, sample size. Ranks models for A/B testing. Model type is metadata, not a ranking factor.
- **acceptance:** `python -m pytest tests/test_model_evaluator.py -q`
- **dependencies:** [rec-206]

#### rec-208: Automated feature pruning job
- **file:** `src/data/handlers/pruning_handler.py`
- **effort:** S
- **priority:** Low
- **context:** Weekly Lambda that removes features with >95% correlation or 8+ weeks of zero usage in winning models. Updates features.yaml exclude_patterns.
- **acceptance:** `python -m pytest tests/test_pruning_handler.py -q`
- **dependencies:** [rec-207]

#### rec-209: Test coverage for pysr_factory.py (PREREQUISITE)
- **file:** `tests/test_pysr_factory.py`
- **effort:** M
- **priority:** Critical
- **context:** Existing src/lab/pysr_factory.py has no test coverage. Before modifying it to consume new latent features (rec-206), comprehensive tests must be in place to validate existing behavior and catch regressions.
- **acceptance:** `python -m pytest tests/test_pysr_factory.py -q --cov=src/lab/pysr_factory --cov-fail-under=80`
- **dependencies:** []

### Part 3: Recommendation Log Triage

Review legacy recommendations (rec-001 through rec-050) and apply one of:
- `declined` with resolution explaining why (e.g., "superseded by newer architecture")
- `closed` with `execution_result: "already_implemented"` if done but unmarked
- Keep `open` if still valid (update context to reflect current state)

This is a human-assisted triage -- the plan produces a triage list, the human reviews and approves, then a script applies the decisions.

#### Triage Criteria
| rec ID range | Likely disposition | Rationale |
|--------------|-------------------|-----------|
| rec-001 to rec-010 | Mostly declined | Early session orchestration ideas superseded by executor workflow |
| rec-011 to rec-030 | Mixed | Some valid, some superseded by later recs |
| rec-031 to rec-050 | Mostly valid | More recent, align with current architecture |

#### Triage Script
After human review, run:
```bash
python scripts/triage_legacy_recs.py --decisions triage-decisions.json
```
(Script to be created as part of this session or as a separate rec)

## Acceptance Criteria
- [ ] Decision 41 added to docs/DECISIONS.md with full rationale
- [ ] docs/ARCHITECTURE.md updated with three-layer feature architecture diagram
- [ ] Each proposed rec (201-209) researched for feasibility and dependencies
- [ ] Large recs broken down into smaller, executor-friendly chunks (effort <= M preferred)
- [ ] Briefing files created for any L/XL effort recs in docs/plans/briefings/
- [ ] All recs filed to logs/.recommendations-log.jsonl with complete context
- [ ] Legacy recs (1-50) triaged: each marked declined/closed/open with resolution
- [ ] validate.py passes

## Constraints
- No Docker on company VM
- All Lambda-based (encoder training may need SageMaker for larger models)
- Must work within existing Athena/Iceberg infrastructure
- Recs must be scoped for executor automation (clear acceptance commands, effort <= M where possible)
- Each rec must have sufficient context for an agent to implement without reading this plan

## Context
- Current Phase 1.5 schema has ~35 hardcoded columns; this plan enables 1000+
- PySR was chosen historically, not strategically -- now one runner among many
- Renaissance/Two Sigma pattern: optimize for returns, not interpretability
- This is a foundational architectural decision that affects all future feature and model work
- Legacy recs include early session orchestration ideas that have been superseded

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] ARCHITECTURE.md read (understand current architecture)
- [ ] logs/.recommendations-log.jsonl schema understood (see copilot-instructions.md)
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Add Decision 41 to DECISIONS.md
Add the Decision 41 text (from Deliverables Part 1 above) to `docs/DECISIONS.md`. Place it after Decision 40, following the existing format. The decision documents:
- Three-layer architecture (Raw -> Encoder -> Discovery)
- Interpretability removed as a constraint
- Industry context (Renaissance, Two Sigma patterns)
- Key design principles and trade-offs

### Step 2: Update ARCHITECTURE.md with Feature Architecture
Add a new section to `docs/ARCHITECTURE.md` titled "Feature Architecture (Phase 1.5+)" that includes:
- The three-layer diagram (Raw -> Encoder -> Discovery)
- Data flow explanation
- How this connects to existing market_data pipeline
- Reference to Decision 41 for rationale

### Step 3: Research and Scope rec-201 (Universal Transform Config)
Research the requirements for `config/features.yaml`:
- What windows should be supported? (1d, 3d, 7d, 14d, 30d)
- What transforms? (pct_change, zscore, ema_diff, rank_percentile)
- What exclude patterns are needed?
- Is this a single rec or should it be split?

File rec-201 to logs/.recommendations-log.jsonl with full context. If effort > M, create a briefing file at `docs/plans/briefings/BRIEFING-rec-201.md`.

### Step 4: Research and Scope rec-202 (Transform Engine)
Research the requirements for `src/data/transform_engine.py`:
- How does it read from features.yaml?
- How does it connect to existing feature_engine.py?
- What Iceberg tables does it write to?
- Sample SQL/Python for generating transforms
- Is this a single rec or should it be split?

File rec-202 (and any sub-recs) to logs/.recommendations-log.jsonl. Create briefing file if effort > M.

### Step 5: Research and Scope rec-203 (VAE Encoder)
Research the requirements for `src/models/encoder.py`:
- VAE architecture for tabular data (input dim variable, latent dim 64-128)
- Training infrastructure (Lambda? SageMaker? Local?)
- Model persistence (S3)
- Inference pipeline integration
- This is likely L effort -- break into sub-recs if possible

File rec-203 (and any sub-recs) to logs/.recommendations-log.jsonl. Create briefing file.

### Step 6: Research and Scope rec-204 (Attention Layer)
Research the requirements for `src/models/attention.py`:
- Attention mechanism for feature selection
- How it produces top-k selected features
- Integration with encoder output
- SHAP-like attribution output

File rec-204 (and any sub-recs) to logs/.recommendations-log.jsonl. Create briefing file if needed.

### Step 7: Research and Scope rec-205 (Feature Vectors Table)
Research the Iceberg table requirements:
- Schema for feature_vectors table (timestamp, symbol, latent_1..128, selected raw cols)
- Terraform changes to iceberg_tables.tf
- How discovery queries this table

File rec-205 to logs/.recommendations-log.jsonl.

### Step 8: Research and Scope rec-206 (Discovery Runners)
Research the model-agnostic discovery architecture:
- How to abstract PySR as one runner among many
- LightGBM runner requirements
- Attention NN runner requirements
- Unified output format for candidate models
- This is likely L effort -- break into sub-recs

File rec-206 (and any sub-recs) to logs/.recommendations-log.jsonl. Create briefing file.

### Step 9: Research and Scope rec-207 (Model Evaluator)
Research the unified evaluation requirements:
- Sharpe ratio, max drawdown, win rate calculations
- How to compare models of different types fairly
- Ranking algorithm for A/B test selection

File rec-207 to logs/.recommendations-log.jsonl.

### Step 10: Research and Scope rec-208 (Feature Pruning)
Research the automated pruning requirements:
- Correlation detection algorithm
- Usage tracking in winning models
- How to update features.yaml exclude_patterns programmatically

File rec-208 to logs/.recommendations-log.jsonl.

### Step 11: Research and Scope rec-209 (pysr_factory Tests)
Research what tests are needed for existing `src/lab/pysr_factory.py`:
- Current functionality to cover
- Mocking strategy for PySR (expensive to run)
- Coverage target (80%)

File rec-209 to logs/.recommendations-log.jsonl.

### Step 12: Triage Legacy Recs (1-50)
For each open rec from rec-001 to rec-050:
1. Read the rec's title, context, and file
2. Determine if it is:
   - `declined`: superseded by newer approach (add resolution field)
   - `closed`: already implemented but not marked (add execution_result: "already_implemented")
   - Keep `open`: still valid (update context if needed)
3. Update the rec in logs/.recommendations-log.jsonl with the decision

Focus on recs that are clearly superseded by the executor workflow or newer architectural decisions.

### Step 13: Run validate.py
Run `python scripts/validate.py` -- must exit 0.

### Step 14: Report Implementation Summary
Report:
- Decision 41 placement in DECISIONS.md
- Total recs filed (may be more than 9 if large recs were split)
- Briefing files created
- Legacy recs triaged (count of declined/closed/kept open)
- Any design decisions made during scoping
