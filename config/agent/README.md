# config/agent/

Agent-consumed config. NOT bundled into any Lambda zip.

Subtrees:
- `data_quality/`          -- DQ rules consumed by `scripts/data_quality_runner.py` and `scripts/validate.py`
- `executor/`              -- Executor capability manifest and role prompts consumed by Claude Code agents
- `validate/`              -- IAM runner manifest consumed by `scripts/validate.py`
- `verification_registry/` -- Graduated VP-step check registry (differentially admitted) consumed by `scripts/validate.py`

Files:
- `cost_reconciliation.yaml` -- Cost reconciliation monitor baselines + thresholds, consumed by `scripts/cost_reconciliation.py`
