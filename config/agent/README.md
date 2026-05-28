# config/agent/

Agent-consumed config. NOT bundled into any Lambda zip.

Subtrees:
- `data_quality/`   -- DQ rules consumed by `scripts/data_quality_runner.py` and `scripts/validate.py`
- `executor/`       -- Executor capability manifest and role prompts consumed by Claude Code agents
- `copilot/`        -- Copilot model registry (routing + multipliers) consumed by model_registry.py
- `validate/`       -- IAM runner manifest consumed by `scripts/validate.py`
