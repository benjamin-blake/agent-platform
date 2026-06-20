"""Tests for scripts/ci_rca_tier_map.py (100% coverage)."""

import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ci_rca_tier_map import (  # noqa: E402
    AST_WALKER_VERSION,
    build_tier_membership,
    compute_earliest_viable_gate,
    probe_runtime,
)

MINI_VALIDATE = textwrap.dedent("""
    import sys

    def validate_pre_only(failed):
        pass

    def validate_presubmit_only(failed):
        pass

    def validate_both(failed):
        pass

    def validate_after_exit(failed):
        pass

    def run_python_checks(failed):
        validate_presubmit_only(failed)
        validate_both(failed)
        validate_after_exit(failed)

    def main():
        import argparse
        args = argparse.Namespace(pre=True)

        if args.pre:
            validate_pre_only(failed=[])
            validate_both(failed=[])
            sys.exit(0)

        run_python_checks(failed=[])
""")


class TestBuildTierMembership:
    def test_pre_only_check(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text(MINI_VALIDATE)
        result = build_tier_membership(vpath)
        assert result is not None
        assert "pre" in result.get("validate_pre_only", [])
        assert "presubmit" not in result.get("validate_pre_only", [])

    def test_presubmit_only_check(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text(MINI_VALIDATE)
        result = build_tier_membership(vpath)
        assert result is not None
        tiers = result.get("validate_presubmit_only", [])
        assert "presubmit" in tiers
        assert "pre" not in tiers

    def test_duplicate_registration(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text(MINI_VALIDATE)
        result = build_tier_membership(vpath)
        assert result is not None
        tiers = result.get("validate_both", [])
        assert "pre" in tiers
        assert "presubmit" in tiers

    def test_after_exit_not_pre(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text(MINI_VALIDATE)
        result = build_tier_membership(vpath)
        assert result is not None
        tiers = result.get("validate_after_exit", [])
        assert "pre" not in tiers

    def test_ast_parse_failure_returns_none(self, tmp_path):
        vpath = tmp_path / "broken.py"
        vpath.write_text("def foo(: pass")
        result = build_tier_membership(vpath)
        assert result is None

    def test_missing_file_returns_none(self, tmp_path):
        result = build_tier_membership(tmp_path / "nonexistent.py")
        assert result is None

    def test_no_main_returns_none(self, tmp_path):
        vpath = tmp_path / "no_main.py"
        vpath.write_text("def foo(): pass\n")
        result = build_tier_membership(vpath)
        assert result is None

    def test_live_validate_sloc_limits(self):
        result = build_tier_membership()
        assert result is not None
        tiers = result.get("validate_sloc_limits", [])
        assert "pre" in tiers
        assert "presubmit" in tiers


class TestProbeRuntime:
    def test_probe_success_returns_median(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text("def validate_fast(failed):\n    pass\n")
        fake_samples = [0.05, 0.06, 0.05, 0.06, 0.05]
        with patch("scripts.ci_rca_tier_map.subprocess.run") as mock_run:
            responses = []
            for s in fake_samples:
                m = MagicMock()
                m.returncode = 0
                m.stdout = f"{s:.6f}\n"
                responses.append(m)
            mock_run.side_effect = responses
            conf, median = probe_runtime("validate_fast", vpath)
        assert median is not None
        assert "median=" in conf

    def test_probe_missing_function_fails(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text("def validate_fast(failed):\n    pass\n")
        conf, median = probe_runtime("validate_nonexistent", vpath)
        assert median is None
        assert "probe_failed" in conf

    def test_dispersion_too_high(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text("def validate_fast(failed):\n    pass\n")
        fake_samples = [0.001, 0.001, 0.5, 1.0, 2.0]
        with patch("scripts.ci_rca_tier_map.subprocess.run") as mock_run:
            responses = []
            for s in fake_samples:
                m = MagicMock()
                m.returncode = 0
                m.stdout = f"{s:.6f}\n"
                responses.append(m)
            mock_run.side_effect = responses
            conf, median = probe_runtime("validate_fast", vpath)
        assert median is None
        assert "dispersion_too_high" in conf

    def test_probe_exception_returns_error(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text("def validate_fast(failed):\n    pass\n")
        with patch("scripts.ci_rca_tier_map.subprocess.run", side_effect=Exception("network error")):
            conf, median = probe_runtime("validate_fast", vpath)
        assert median is None
        assert "probe_failed" in conf


class TestComputeEarliestViableGate:
    def test_external_dep_returns_presubmit(self):
        gate, rationale = compute_earliest_viable_gate("validate_iam_runner_policy", {}, "ok", 0.01)
        assert gate == "presubmit"
        assert "Decision 60" in rationale

    def test_ast_failure_returns_none(self):
        gate, _ = compute_earliest_viable_gate("validate_x", None, "ok", 0.01)
        assert gate is None

    def test_already_in_pre(self):
        tm = {"validate_x": ["pre", "presubmit"]}
        gate, rationale = compute_earliest_viable_gate("validate_x", tm, "ok", 0.01)
        assert gate == "pre"

    def test_not_in_any_tier_defaults_presubmit(self):
        gate, _ = compute_earliest_viable_gate("validate_unknown", {}, "ok", 0.01)
        assert gate == "presubmit"

    def test_fits_headroom_recommends_pre(self):
        tm = {"validate_x": ["presubmit"]}
        gate, rationale = compute_earliest_viable_gate("validate_x", tm, "median=50ms", 0.05, current_pre_runtime=10.0)
        assert gate == "pre"
        assert "promotion" in rationale

    def test_exceeds_headroom_stays_presubmit(self):
        tm = {"validate_x": ["presubmit"]}
        gate, _ = compute_earliest_viable_gate("validate_x", tm, "median=400000ms", 400.0, current_pre_runtime=0.0)
        assert gate == "presubmit"

    def test_probe_failed_returns_none(self):
        tm = {"validate_x": ["presubmit"]}
        gate, _ = compute_earliest_viable_gate("validate_x", tm, "probe_failed: timeout", None)
        assert gate is None

    def test_dispersion_too_high_returns_none(self):
        tm = {"validate_x": ["presubmit"]}
        gate, _ = compute_earliest_viable_gate("validate_x", tm, "dispersion_too_high: ...", None)
        assert gate is None

    def test_version_constant(self):
        assert isinstance(AST_WALKER_VERSION, int)
        assert AST_WALKER_VERSION >= 1
