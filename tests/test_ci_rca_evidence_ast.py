"""Golden-fixture contract test for the AST walker in scripts/ci_rca/tier_map.py.

Pins the walker output against a frozen expected tier_membership for a fixture mirror
of validate.py structure (all four control-flow cases). Fixture changes require
Decision-Record-class review (the fixture encodes the contract's understanding of validate.py).

Also asserts against the LIVE scripts/validate.py:
  validate_sloc_limits -> ["pre", "presubmit"] (duplicate registration case).
"""

import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from scripts.ci_rca.tier_map import build_tier_membership  # noqa: E402

FIXTURE_VALIDATE_SOURCE = textwrap.dedent("""
    import sys

    def validate_direct_pre(failed):
        pass

    def validate_duplicate(failed):
        pass

    def validate_via_aggregator(failed):
        pass

    def validate_after_exit(failed):
        pass

    def run_python_checks(failed):
        validate_via_aggregator(failed)
        validate_duplicate(failed)
        validate_after_exit(failed)

    def main():
        import argparse
        args = argparse.Namespace(pre=True)

        if args.pre:
            validate_direct_pre(failed=[])
            validate_duplicate(failed=[])
            sys.exit(0)

        run_python_checks(failed=[])
""")

EXPECTED_FIXTURE_MEMBERSHIP: dict[str, list[str]] = {
    "validate_direct_pre": ["pre"],
    "validate_duplicate": ["pre", "presubmit"],
    "validate_via_aggregator": ["presubmit"],
    "validate_after_exit": ["presubmit"],
}


class TestFixtureMirror:
    """Pinned golden fixture -- changes here require Decision-Record-class review."""

    def test_direct_pre_call(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text(FIXTURE_VALIDATE_SOURCE)
        result = build_tier_membership(vpath)
        assert result is not None, "Walker returned None (parse failure)"
        assert result.get("validate_direct_pre") == EXPECTED_FIXTURE_MEMBERSHIP["validate_direct_pre"], (
            "validate_direct_pre should be in --pre only"
        )

    def test_aggregator_indirection(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text(FIXTURE_VALIDATE_SOURCE)
        result = build_tier_membership(vpath)
        assert result is not None
        assert result.get("validate_via_aggregator") == EXPECTED_FIXTURE_MEMBERSHIP["validate_via_aggregator"], (
            "validate_via_aggregator should be presubmit only (via aggregator)"
        )

    def test_sys_exit_short_circuit(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text(FIXTURE_VALIDATE_SOURCE)
        result = build_tier_membership(vpath)
        assert result is not None
        tiers = result.get("validate_after_exit", [])
        assert "pre" not in tiers, (
            "validate_after_exit appears after sys.exit(0) in --pre block; must not be attributed to --pre"
        )

    def test_duplicate_registration(self, tmp_path):
        vpath = tmp_path / "validate.py"
        vpath.write_text(FIXTURE_VALIDATE_SOURCE)
        result = build_tier_membership(vpath)
        assert result is not None
        assert result.get("validate_duplicate") == EXPECTED_FIXTURE_MEMBERSHIP["validate_duplicate"], (
            "validate_duplicate is registered in both --pre and aggregator; should be ['pre', 'presubmit']"
        )


class TestLiveValidatePy:
    """Assertions against the live scripts/validate.py -- regression guard."""

    def test_validate_sloc_limits_duplicate_registration(self):
        result = build_tier_membership()
        assert result is not None, "AST walk of live validate.py failed"
        tiers = result.get("validate_sloc_limits", [])
        assert "pre" in tiers, "validate_sloc_limits should be in --pre (called directly at validate.py:2941)"
        assert "presubmit" in tiers, "validate_sloc_limits should be in presubmit (via run_python_checks at validate.py:2491)"
        assert tiers == ["pre", "presubmit"], f"Expected ['pre', 'presubmit'], got {tiers}"
