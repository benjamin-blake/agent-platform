"""Integration test: compute_state_dict against the live ROADMAP-PLATFORM.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.platform_roadmap import compute_state_dict

_LIVE_YAML = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"


@pytest.mark.skipif(not _LIVE_YAML.exists(), reason="live ROADMAP-PLATFORM.yaml not present")
class TestLiveRoadmapState:
    def test_required_keys_present(self) -> None:
        result = compute_state_dict(_LIVE_YAML)
        required = ("next_eligible", "in_progress", "blocked", "strategic_pending", "active_tier")
        missing = [k for k in required if k not in result]
        assert not missing, f"missing keys: {missing}"

    def test_no_error_on_live_yaml(self) -> None:
        result = compute_state_dict(_LIVE_YAML)
        assert "error" not in result, f"unexpected error: {result.get('error')}"

    def test_next_eligible_non_empty(self) -> None:
        result = compute_state_dict(_LIVE_YAML)
        assert result["next_eligible"], "expected at least one eligible item on the live roadmap"

    def test_items_have_required_fields(self) -> None:
        result = compute_state_dict(_LIVE_YAML)
        required_fields = ("id", "tier", "name", "effort", "strategic")
        for key in ("next_eligible", "in_progress", "strategic_pending"):
            for item in result[key]:
                for field in required_fields:
                    assert field in item, f"{key} item missing field '{field}': {item}"

    def test_blocked_items_have_blocked_on(self) -> None:
        result = compute_state_dict(_LIVE_YAML)
        for item in result["blocked"]:
            assert "blocked_on" in item, f"blocked item missing 'blocked_on': {item}"
            assert isinstance(item["blocked_on"], list)

    def test_active_tier_is_valid(self) -> None:
        result = compute_state_dict(_LIVE_YAML)
        valid_tiers = {"T-1", "T0", "T1", "T2", "T3", "T4", "T5", None}
        assert result["active_tier"] in valid_tiers, f"unexpected active_tier: {result['active_tier']}"

    def test_strategic_items_absent_from_next_eligible(self) -> None:
        result = compute_state_dict(_LIVE_YAML)
        next_ids = {i["id"] for i in result["next_eligible"]}
        strategic_ids = {i["id"] for i in result["strategic_pending"]}
        overlap = next_ids & strategic_ids
        assert not overlap, f"items in both next_eligible and strategic_pending: {overlap}"
