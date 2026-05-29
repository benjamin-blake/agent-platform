"""Integration tests: product_roadmap block in compute_state_dict and session_preflight."""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.product_roadmap import compute_state_dict

# Load session_preflight once; reuse the already-loaded module when the full suite runs.
if "session_preflight" not in sys.modules:
    _MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "session_preflight.py"
    _spec = importlib.util.spec_from_file_location("session_preflight", _MODULE_PATH)
    assert _spec and _spec.loader
    _preflight = importlib.util.module_from_spec(_spec)
    sys.modules["session_preflight"] = _preflight
    _spec.loader.exec_module(_preflight)  # type: ignore[union-attr]
_preflight = sys.modules["session_preflight"]

FIXTURES = Path(__file__).parent / "fixtures" / "product_roadmap"
_LIVE_PRODUCT = Path(__file__).parent.parent / "docs" / "ROADMAP-PRODUCT.yaml"
_LIVE_PLATFORM = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"


# ---------------------------------------------------------------------------
# Fixture-based state dict tests
# ---------------------------------------------------------------------------


class TestComputeStateDict:
    def test_required_keys_present(self) -> None:
        result = compute_state_dict(
            FIXTURES / "minimal_product.yaml",
            platform_yaml_path=FIXTURES / "minimal_platform.yaml",
        )
        required = (
            "next_eligible",
            "in_progress",
            "blocked",
            "strategic_pending",
            "active_layer",
            "platform_tier_item_consumers",
            "platform_gap_consumers",
            "platform_cd_consumers",
        )
        missing = [k for k in required if k not in result]
        assert not missing, f"missing keys: {missing}"

    def test_no_error_on_fixture_pair(self) -> None:
        result = compute_state_dict(
            FIXTURES / "minimal_product.yaml",
            platform_yaml_path=FIXTURES / "minimal_platform.yaml",
        )
        assert "error" not in result

    def test_three_split_consumer_namespaces(self) -> None:
        result = compute_state_dict(
            FIXTURES / "minimal_product.yaml",
            platform_yaml_path=FIXTURES / "minimal_platform.yaml",
        )
        assert isinstance(result["platform_tier_item_consumers"], dict)
        assert isinstance(result["platform_gap_consumers"], dict)
        assert isinstance(result["platform_cd_consumers"], dict)

    def test_malformed_yaml_returns_error_dict(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False, encoding="utf-8") as f:
            f.write(":: invalid yaml [[[")
            tmp = f.name
        try:
            result = compute_state_dict(tmp)
            assert "error" in result
            assert result["next_eligible"] == []
            assert result["in_progress"] == []
            assert result["platform_tier_item_consumers"] == {}
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_missing_product_yaml_returns_error_dict(self) -> None:
        result = compute_state_dict(Path("/nonexistent/ROADMAP-PRODUCT.yaml"))
        assert "error" in result
        assert result["next_eligible"] == []
        assert result["platform_gap_consumers"] == {}

    def test_missing_platform_yaml_no_crash(self) -> None:
        # PRODUCT-only walk should succeed; cross-roadmap resolution skipped
        result = compute_state_dict(
            FIXTURES / "minimal_product.yaml",
            platform_yaml_path=Path("/nonexistent/ROADMAP-PLATFORM.yaml"),
        )
        # With missing platform, cross-roadmap fails during load -> error dict
        # OR platform load silently degraded -> no error. Either is acceptable;
        # test only asserts no unhandled exception and keys are present.
        assert "next_eligible" in result

    def test_fixture_consumers_match_expected(self) -> None:
        result = compute_state_dict(
            FIXTURES / "minimal_product.yaml",
            platform_yaml_path=FIXTURES / "minimal_platform.yaml",
        )
        tier_consumers = result["platform_tier_item_consumers"]
        assert tier_consumers.get("T-1.5") == ["L0.1"]
        gap_consumers = result["platform_gap_consumers"]
        assert gap_consumers.get("GAP-fixture-gap") == ["L1.alpha.1"]
        cd_consumers = result["platform_cd_consumers"]
        assert cd_consumers.get("CD.1") == ["L1.alpha.1"]


# ---------------------------------------------------------------------------
# Live YAML integration
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _LIVE_PRODUCT.exists(), reason="live ROADMAP-PRODUCT.yaml not present")
class TestLiveComputeStateDict:
    def test_no_error_on_live_yaml(self) -> None:
        result = compute_state_dict(_LIVE_PRODUCT, platform_yaml_path=_LIVE_PLATFORM)
        assert "error" not in result, f"unexpected error: {result.get('error')}"

    def test_live_consumers_non_empty(self) -> None:
        """PLAN-cd25-platform-gap-sequencing (2026-05-24) resolved all six PLATFORM:GAP-*
        sentinels to concrete PLATFORM ids; platform_gap_consumers is empty by design
        post-resolution. tier_item and cd consumers remain populated."""
        result = compute_state_dict(_LIVE_PRODUCT, platform_yaml_path=_LIVE_PLATFORM)
        assert result["platform_tier_item_consumers"], "expected non-empty tier_item consumers on live roadmap"
        assert result["platform_cd_consumers"], "expected non-empty cd consumers on live roadmap (CD.25 etc.)"

    def test_active_layer_is_valid(self) -> None:
        result = compute_state_dict(_LIVE_PRODUCT, platform_yaml_path=_LIVE_PLATFORM)
        valid = {"L0", "L1", "L2", "L3", "L4", "D.fast", "D.lake", "E.env", "MVP", None}
        assert result["active_layer"] in valid, f"unexpected active_layer: {result['active_layer']}"

    def test_items_have_required_fields(self) -> None:
        result = compute_state_dict(_LIVE_PRODUCT, platform_yaml_path=_LIVE_PLATFORM)
        for key in ("next_eligible", "in_progress"):
            for item in result[key]:
                for field in ("id", "tier", "name", "effort", "strategic"):
                    assert field in item, f"{key} item missing '{field}': {item}"


# ---------------------------------------------------------------------------
# End-to-end: product_roadmap block lands in preflight report
# ---------------------------------------------------------------------------


class TestPreflightProductRoadmapBlock:
    """Verify that session_preflight.main() writes the product_roadmap key."""

    def test_product_roadmap_block_in_preflight_report(self, tmp_path: Path) -> None:
        preflight_report = tmp_path / ".preflight-report.json"
        _product_state = {
            "next_eligible": [],
            "in_progress": [],
            "blocked": [],
            "strategic_pending": [],
            "active_layer": "L0",
            "platform_tier_item_consumers": {"T0.13": ["L0.1"]},
            "platform_gap_consumers": {"GAP-cd25-contract-ritual": ["D.lake.1"]},
            "platform_cd_consumers": {"CD.9": ["L0.1"]},
        }

        def _athena_stub(sql: str) -> list | None:
            if "ops_priority_queue_current" in sql:
                return []
            return None

        with (
            patch("session_preflight.check_venv", return_value=True),
            patch("session_preflight.get_git_status", return_value=("agent/test", False, [])),
            patch("session_preflight.check_terraform_pending", return_value=False),
            patch("session_preflight.check_credentials", return_value="ok"),
            patch("session_preflight.parse_last_session", return_value=""),
            patch("session_preflight.count_recommendations", return_value=(0, 0, 0, [])),
            patch("session_preflight._sync_ops_pull", return_value={}),
            patch(
                "session_preflight.read_context_files",
                return_value={
                    "roadmap_phase": "",
                    "open_decisions_count": 0,
                    "recent_sessions": [],
                    "strategic_review_due": False,
                    "recommendations_count": 0,
                },
            ),
            patch(
                "session_preflight.check_telemetry_health",
                return_value={"overall": "ok", "checks": [], "friction_patterns": []},
            ),
            patch("session_preflight._check_ci_rca_liveness", return_value=None),
            patch("session_preflight._run_athena_query", side_effect=_athena_stub),
            patch("session_preflight._athena_run_query", return_value=[]),
            patch("scripts.sync_ops.sync", return_value={"drained": {}, "pulled": {}}),
            patch("session_preflight.platform_roadmap.compute_state_dict", return_value={}),
            patch("session_preflight.product_roadmap_module.compute_state_dict", return_value=_product_state),
            patch("session_preflight.PREFLIGHT_REPORT", preflight_report),
            patch("builtins.print"),
        ):
            _preflight.main()

        data = json.loads(preflight_report.read_text(encoding="utf-8"))
        assert "product_roadmap" in data
        pr = data["product_roadmap"]
        assert set(pr.keys()) == {"next_eligible", "strategic_pending"}, (
            "product_roadmap in the preflight report is intentionally slimmed via "
            "_slim_roadmap_state. The full compute_state_dict shape (in_progress, "
            "blocked, active_layer, *_consumers) is still produced by "
            "scripts.product_roadmap.compute_state_dict for direct callers, but is "
            "not stored in the report -- it cost ~4k tokens per session that no "
            "workflow consumed. If you need the full state, call compute_state_dict() directly."
        )
