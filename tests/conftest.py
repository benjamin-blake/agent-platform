"""Shared pytest fixtures for the test suite."""

import os
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

# Prevent any subprocess that spawns validate.py from recursing into a full
# lint/test/coverage cycle.  The guard in validate.py main() checks this var
# and exits immediately when it is >= 1.
os.environ.setdefault("_VALIDATE_DEPTH", "1")
os.environ.setdefault("_COVERAGE_SUBPROCESS", "1")

_LLM_CLI_NAMES: frozenset[str] = frozenset({"gemini", "gemini.CMD", "claude", "copilot"})


def _get_executor_env_vars() -> frozenset[str]:
    """Import _EXECUTOR_ACC_VARS from step_runner, or fall back to a hardcoded set.

    Importing from step_runner ensures conftest stays in sync automatically as
    new executor-mode env vars are added.  The fallback prevents conftest from
    breaking if step_runner is unreachable (e.g. early CI bootstrap).
    """
    try:
        from scripts.executor.step_runner import _EXECUTOR_ACC_VARS  # noqa: PLC0415

        return _EXECUTOR_ACC_VARS | {"COPILOT_STEP_TIMEOUT_SECS"}
    except ImportError:
        return frozenset(
            {
                "SKIP_CI_WAIT",
                "SKIP_CODE_REVIEW",
                "COPILOT_MODEL_EXECUTION",
                "COPILOT_MODEL_PLANNING",
                "CI_FIX_RETRIES",
                "COPILOT_STEP_TIMEOUT_SECS",
            }
        )


@pytest.fixture(autouse=True)
def _clear_executor_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip executor-mode env vars so they never leak into test assertions.

    Derives the var list from scripts.executor.step_runner._EXECUTOR_ACC_VARS
    so new executor env vars are automatically covered without updating conftest.
    """
    for var in _get_executor_env_vars():
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _isolate_plans_jsonl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect PLANS_JSONL to a per-test temp file.

    Prevents executor-plan tests from writing to the tracked
    logs/.execution-plans.jsonl.  Tests that explicitly patch PLANS_JSONL
    themselves will simply override this fixture's value.
    """
    try:
        import scripts.executor.plan as _plan_mod  # noqa: PLC0415

        monkeypatch.setattr(_plan_mod, "PLANS_JSONL", tmp_path / "plans.jsonl")
    except ImportError:
        pass


@pytest.fixture(autouse=True)
def _patch_write_run_summary():  # type: ignore[misc]
    """Prevent executor tests from writing real logs/runs/*.json artifacts.

    Patches write_run_summary at the module level so individual tests do not
    need to remember to mock it themselves.  Yields the patcher so tests that
    need the real function can call ``.stop()`` / ``.start()``.
    """
    patcher = patch(
        "scripts.execute_recommendation.write_run_summary",
        return_value=None,
    )
    patcher.start()
    yield patcher
    patcher.stop()


@pytest.fixture(autouse=True)
def _block_llm_cli_subprocess(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard against CI/local drift where LLM CLIs exist on dev but not on Ubuntu CI runners."""
    if "integration" in [m.name for m in request.node.own_markers]:
        return

    import subprocess as _sp  # noqa: PLC0415

    _orig_run = _sp.run

    def _guarded_run(args, *a, **kw):  # type: ignore[no-untyped-def]
        cmd = args[0] if isinstance(args, (list, tuple)) else args
        name = Path(str(cmd)).name
        if name in _LLM_CLI_NAMES:
            raise RuntimeError(
                f"Unit test reached LLM CLI '{cmd}' without mocking. "
                "Patch subprocess.run or the calling function before this point, "
                "or mark the test @pytest.mark.integration."
            )
        return _orig_run(args, *a, **kw)

    monkeypatch.setattr(_sp, "run", _guarded_run)


@pytest.fixture
def ohlcv_df() -> pd.DataFrame:
    """Standard single-symbol OHLCV DataFrame (60 business days, seed=42).

    Use this fixture for tests that need a reproducible OHLCV frame without
    caring about specific price behaviour. Tests that require controlled price
    shape (e.g. MACD crossover tests) should build their own data locally.
    """
    np.random.seed(42)
    timestamps = pd.date_range("2026-01-01", periods=60, freq="B")
    price = 100.0
    rows = []
    for ts in timestamps:
        change = np.random.randn() * 1.5
        new_price = price + change
        rows.append(
            {
                "timestamp": ts,
                "symbol": "TEST.L",
                "open": round(price, 2),
                "high": round(price + abs(np.random.randn()), 2),
                "low": round(price - abs(np.random.randn()), 2),
                "close": round(new_price, 2),
                "adj_close": round(new_price, 2),
                "volume": int(np.random.uniform(1e6, 5e6)),
            }
        )
        price = new_price
    return pd.DataFrame(rows)
