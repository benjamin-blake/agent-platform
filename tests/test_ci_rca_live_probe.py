from scripts.ci_rca.live_probe import proof


def test_live_probe_scenarios_are_metadata_only() -> None:
    complete = proof("complete", "c", "a" * 40)
    truncated = proof("truncated", "c", "a" * 40)
    malformed = proof("malformed", "c", "a" * 40)
    assert complete["truncated"] is False
    assert truncated["truncated"] is True
    assert malformed["refused"] is True
    assert "body" not in complete
