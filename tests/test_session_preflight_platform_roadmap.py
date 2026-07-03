"""Integration test: compute_state_dict against the live ROADMAP-PLATFORM.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.platform_roadmap import compute_state_dict
from scripts.session_preflight import _slim_roadmap_state

_LIVE_YAML = Path(__file__).parent.parent / "docs" / "ROADMAP-PLATFORM.yaml"
_LIVE_PRODUCT_YAML = Path(__file__).parent.parent / "docs" / "ROADMAP-PRODUCT.yaml"

# Keys present only in the full (/orient) projection, never in slim (/plan).
_FULL_ONLY_KEYS = ("in_progress", "blocked", "active_tier", "blocked_on_cd", "gate_evaluations")


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


@pytest.mark.skipif(not _LIVE_YAML.exists(), reason="live ROADMAP-PLATFORM.yaml not present")
class TestRoadmapDetailProjection:
    """T-1.20: _slim_roadmap_state slim (/plan) vs full (/orient) projection split."""

    def _full_state(self) -> dict:
        return compute_state_dict(_LIVE_YAML)

    def test_slim_omits_full_only_keys(self) -> None:
        slim = _slim_roadmap_state(self._full_state(), full=False)
        for key in _FULL_ONLY_KEYS:
            assert key not in slim, f"slim projection must not carry '{key}'"

    def test_slim_default_matches_explicit_false(self) -> None:
        state = self._full_state()
        assert _slim_roadmap_state(state) == _slim_roadmap_state(state, full=False)

    def test_slim_keeps_next_eligible_and_strategic(self) -> None:
        slim = _slim_roadmap_state(self._full_state(), full=False)
        assert set(slim.keys()) == {"next_eligible", "strategic_pending"}

    def test_full_includes_all_full_only_keys(self) -> None:
        full = _slim_roadmap_state(self._full_state(), full=True)
        for key in _FULL_ONLY_KEYS:
            assert key in full, f"full projection must carry '{key}'"

    def test_full_includes_next_eligible_and_strategic(self) -> None:
        full = _slim_roadmap_state(self._full_state(), full=True)
        assert "next_eligible" in full
        assert "strategic_pending" in full

    def test_full_gate_evaluations_carried(self) -> None:
        full = _slim_roadmap_state(self._full_state(), full=True)
        gate_ids = {g["id"] for g in full["gate_evaluations"]}
        assert {"G.1", "G.8", "G.9", "G.10"}.issubset(gate_ids)

    def test_full_blocked_on_cd_carried(self) -> None:
        # Non-empty invariant rather than a specific item id: the live roadmap always has
        # not_started eligible items gated by a pending CD, and anchoring on a concrete id
        # would be perturbed by this plan's own tier-item bookkeeping.
        full = _slim_roadmap_state(self._full_state(), full=True)
        assert isinstance(full["blocked_on_cd"], list)
        assert full["blocked_on_cd"], "full projection must carry the live blocked_on_cd entries"

    def test_next_eligible_carries_user_action_required_slim(self) -> None:
        slim = _slim_roadmap_state(self._full_state(), full=False)
        for item in slim["next_eligible"]:
            assert "user_action_required" in item, f"slim next_eligible item missing key: {item}"

    def test_next_eligible_carries_user_action_required_full(self) -> None:
        full = _slim_roadmap_state(self._full_state(), full=True)
        for item in full["next_eligible"]:
            assert "user_action_required" in item, f"full next_eligible item missing key: {item}"

    def test_full_realized_but_pending_cds_key_present(self) -> None:
        """close-audit-ulf-02: full projection carries the new realized_but_pending_cds key."""
        full = _slim_roadmap_state(self._full_state(), full=True)
        assert "realized_but_pending_cds" in full
        assert isinstance(full["realized_but_pending_cds"], list)


@pytest.mark.skipif(not _LIVE_PRODUCT_YAML.exists(), reason="live ROADMAP-PRODUCT.yaml not present")
class TestProductRoadmapProjectionUnchanged:
    """T-1.20 / Decision 93: product roadmap (no candidate_decisions/cross_tier_gates) is
    unaffected by the new projection. _slim_roadmap_state uses .get() defaults so the
    platform-only keys never crash and never appear spuriously."""

    def _product_state(self) -> dict:
        from scripts import product_roadmap as product_roadmap_module

        return product_roadmap_module.compute_state_dict(_LIVE_PRODUCT_YAML, platform_yaml_path=_LIVE_YAML)

    def test_product_slim_only_two_keys(self) -> None:
        slim = _slim_roadmap_state(self._product_state(), full=False)
        assert set(slim.keys()) == {"next_eligible", "strategic_pending"}

    def test_product_full_defaults_empty_platform_keys(self) -> None:
        # product roadmap has no blocked_on_cd / gate_evaluations -> .get() defaults to [].
        full = _slim_roadmap_state(self._product_state(), full=True)
        assert full["blocked_on_cd"] == []
        assert full["gate_evaluations"] == []

    def test_product_full_does_not_crash(self) -> None:
        # Regression guard: full projection over a state dict lacking the platform-only
        # keys must not raise (Decision 93 .get() defaults).
        full = _slim_roadmap_state(self._product_state(), full=True)
        assert "next_eligible" in full


@pytest.mark.skipif(not _LIVE_YAML.exists(), reason="live ROADMAP-PLATFORM.yaml not present")
class TestFollowonFieldsInPreflight:
    """T-1.23: in_progress entries carry open_criteria_count/all_plans_actioned/needs_followon_plan."""

    def _full_state(self) -> dict:
        from scripts.platform_roadmap import compute_state_dict

        return compute_state_dict(_LIVE_YAML)

    def test_in_progress_entries_carry_followon_fields(self) -> None:
        state = self._full_state()
        full = _slim_roadmap_state(state, full=True)
        for entry in full.get("in_progress", []):
            assert "open_criteria_count" in entry, f"missing open_criteria_count: {entry['id']}"
            assert "all_plans_actioned" in entry, f"missing all_plans_actioned: {entry['id']}"
            assert "needs_followon_plan" in entry, f"missing needs_followon_plan: {entry['id']}"

    def test_open_criteria_count_is_non_negative_int(self) -> None:
        state = self._full_state()
        full = _slim_roadmap_state(state, full=True)
        for entry in full.get("in_progress", []):
            count = entry["open_criteria_count"]
            assert isinstance(count, int) and count >= 0, f"invalid open_criteria_count for {entry['id']}: {count}"

    def test_followon_fields_are_correct_types(self) -> None:
        state = self._full_state()
        full = _slim_roadmap_state(state, full=True)
        for entry in full.get("in_progress", []):
            assert isinstance(entry["all_plans_actioned"], bool), f"all_plans_actioned not bool: {entry['id']}"
            assert isinstance(entry["needs_followon_plan"], bool), f"needs_followon_plan not bool: {entry['id']}"

    def test_needs_followon_implies_has_open_criteria(self) -> None:
        state = self._full_state()
        full = _slim_roadmap_state(state, full=True)
        for entry in full.get("in_progress", []):
            if entry["needs_followon_plan"]:
                assert entry["open_criteria_count"] > 0, (
                    f"needs_followon_plan=True but open_criteria_count=0 for {entry['id']}"
                )

    def test_next_eligible_does_not_carry_followon_fields(self) -> None:
        state = self._full_state()
        full = _slim_roadmap_state(state, full=True)
        for entry in full.get("next_eligible", []):
            assert "open_criteria_count" not in entry, f"next_eligible must not carry followon fields: {entry['id']}"


@pytest.mark.skipif(not _LIVE_YAML.exists(), reason="live ROADMAP-PLATFORM.yaml not present")
class TestCompletionBlockedOnCdProjection:
    """T-1.20:c6 -- completion_blocked_on_cd field in full (/orient) projection."""

    def _full_state(self) -> dict:
        from scripts.platform_roadmap import compute_state_dict

        return compute_state_dict(_LIVE_YAML)

    def test_full_in_progress_carries_completion_blocked_on_cd(self) -> None:
        """Full projection in_progress entries all carry completion_blocked_on_cd."""
        state = self._full_state()
        full = _slim_roadmap_state(state, full=True)
        for entry in full.get("in_progress", []):
            assert "completion_blocked_on_cd" in entry, f"in_progress entry {entry['id']} missing completion_blocked_on_cd"
            assert isinstance(entry["completion_blocked_on_cd"], list), (
                f"{entry['id']}: completion_blocked_on_cd must be a list"
            )

    def test_t112_surfaces_pending_gating_cd(self) -> None:
        """close-audit-ulf-02 (2026-07-03): T-1.20 completed once CD.1 AND CD.13 both
        ratified (Decisions 108/110), so it no longer surfaces a completion gate and is
        absent from in_progress. Re-point this test to a still-in_progress item gated by
        a real pending CD -- T1.12 is in_progress and gated by pending CD.10/CD.11/CD.25 --
        preserving the test's intent (completion_blocked_on_cd surfaces a real pending
        gate) against live post-ratification state."""
        state = self._full_state()
        full = _slim_roadmap_state(state, full=True)
        t120 = next((i for i in full.get("in_progress", []) if i["id"] == "T-1.20"), None)
        assert t120 is None, "T-1.20 expected complete (absent from in_progress) post-ratification"
        t112 = next((i for i in full.get("in_progress", []) if i["id"] == "T1.12"), None)
        assert t112 is not None, "T1.12 expected in in_progress"
        assert "CD.25" in t112["completion_blocked_on_cd"], (
            f"CD.25 expected in T1.12 completion_blocked_on_cd, got {t112['completion_blocked_on_cd']}"
        )

    def test_slim_projection_omits_in_progress(self) -> None:
        """Slim (/plan) projection does not carry in_progress (completion_blocked_on_cd never leaks)."""
        state = self._full_state()
        slim = _slim_roadmap_state(state, full=False)
        assert "in_progress" not in slim, "slim projection must not carry in_progress"
