"""Tests for scripts.llm_utils."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.llm_utils import (
    LLMResponseError,
    _compute_prompt_hash,
    build_context_path,
    check_process_killswitch,
    check_recursion_guard,
    kill_process_tree,
)


class TestBuildContextPath:
    def test_without_step(self) -> None:
        path = build_context_path("planning", "rec-042")
        assert path == "logs/debug/planning-context-rec-042.md"

    def test_with_step(self) -> None:
        path = build_context_path("implementation", "rec-123", step_n=3)
        assert path == "logs/debug/implementation-context-rec-123-step3.md"


class TestComputePromptHash:
    def test_returns_12_hex_chars(self) -> None:
        h = _compute_prompt_hash("hello world")
        assert len(h) == 12
        assert all(c in "0123456789abcdef" for c in h)

    def test_deterministic(self) -> None:
        assert _compute_prompt_hash("same") == _compute_prompt_hash("same")

    def test_different_for_different_input(self) -> None:
        assert _compute_prompt_hash("a") != _compute_prompt_hash("b")


class TestLLMResponseError:
    def test_raisable(self) -> None:
        with pytest.raises(LLMResponseError, match="test error"):
            raise LLMResponseError("test error")

    def test_is_runtime_error(self) -> None:
        err = LLMResponseError("msg")
        assert isinstance(err, RuntimeError)


class TestKillProcessTree:
    @patch("scripts.llm_utils.subprocess.run")
    def test_calls_taskkill_on_windows(self, mock_run: object) -> None:
        with patch("scripts.llm_utils.sys.platform", "win32"):
            kill_process_tree(12345)


class TestCheckProcessKillswitch:
    @patch("scripts.llm_utils.count_python_processes", return_value=10)
    def test_no_exit_under_threshold(self, mock_count: object) -> None:
        check_process_killswitch("test")

    @patch("scripts.llm_utils.count_python_processes", return_value=100)
    def test_exits_over_threshold(self, mock_count: object) -> None:
        with pytest.raises(SystemExit):
            check_process_killswitch("test")


class TestCheckRecursionGuard:
    def test_no_exit_at_depth_zero(self) -> None:
        with patch.dict("os.environ", {"_EXECUTOR_DEPTH": "0"}):
            check_recursion_guard()

    def test_exits_at_depth_one(self) -> None:
        with patch.dict("os.environ", {"_EXECUTOR_DEPTH": "1"}):
            with pytest.raises(SystemExit):
                check_recursion_guard()
