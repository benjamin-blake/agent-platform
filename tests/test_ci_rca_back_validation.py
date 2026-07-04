"""Unit tests for scripts.ci_rca_back_validation.

All tests are free of live AWS, network, and DuckLake-reader dependencies: cache_rows is
always injected (never fetched). A dedicated test asserts no reader is constructed, guarding
the Decision-88 zero-egress claim.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from scripts.ci_rca_back_validation import DEFAULT_WINDOW_DAYS, find_preventive_regressions

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _rec(
    rec_id: str,
    source: str = "ci_rca",
    status: str = "open",
    file: str = "scripts/validate.py",
    created_days_ago: float = 1,
    closed_days_ago: float | None = None,
    preventive_action: str | None = None,
) -> dict:
    created_ts = NOW - timedelta(days=created_days_ago)
    ctx = {}
    if preventive_action is not None:
        ctx["preventive_action"] = preventive_action
    row = {
        "id": rec_id,
        "source": source,
        "status": status,
        "file": file,
        "created_timestamp": created_ts.isoformat(),
        "context_v2_json": json.dumps(ctx) if ctx else "",
    }
    if closed_days_ago is not None:
        row["last_updated_timestamp"] = (NOW - timedelta(days=closed_days_ago)).isoformat()
    return row


class TestFindPreventiveRegressions:
    def test_flags_open_rec_matching_closed_prior_with_preventive_action(self) -> None:
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=10, preventive_action="Promote the check to --pre tier."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        flags = find_preventive_regressions(rows, window_days=DEFAULT_WINDOW_DAYS, now=NOW)
        assert flags == [
            {
                "new_rec_id": "rec-200",
                "prior_rec_id": "rec-100",
                "file": "scripts/validate.py",
                "preventive_action_excerpt": "Promote the check to --pre tier.",
            }
        ]

    def test_no_flag_when_prior_rec_is_open(self) -> None:
        rows = [
            _rec("rec-100", status="open", created_days_ago=10, preventive_action="Promote the check to --pre tier."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        assert find_preventive_regressions(rows, now=NOW) == []

    def test_no_flag_when_files_differ(self) -> None:
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=10, file="scripts/a.py", preventive_action="Fix a.py."),
            _rec("rec-200", status="open", created_days_ago=1, file="scripts/b.py"),
        ]
        assert find_preventive_regressions(rows, now=NOW) == []

    def test_no_flag_when_prior_rec_has_no_preventive_action(self) -> None:
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=10, preventive_action=None),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        assert find_preventive_regressions(rows, now=NOW) == []

    def test_no_flag_when_prior_rec_is_different_source(self) -> None:
        rows = [
            _rec("rec-100", source="ci_rca_probe_health", status="closed", closed_days_ago=10, preventive_action="Fix it."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        assert find_preventive_regressions(rows, now=NOW) == []

    def test_window_filtering_excludes_old_open_recs(self) -> None:
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=20, preventive_action="Fix it."),
            _rec("rec-200", status="open", created_days_ago=30),  # outside 14d window
        ]
        assert find_preventive_regressions(rows, window_days=14, now=NOW) == []

    def test_empty_on_no_matches(self) -> None:
        assert find_preventive_regressions([], now=NOW) == []

    def test_picks_most_recently_closed_prior_when_multiple_match(self) -> None:
        rows = [
            _rec("rec-100", status="closed", closed_days_ago=20, preventive_action="Older fix."),
            _rec("rec-101", status="closed", closed_days_ago=5, preventive_action="Newer fix."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        flags = find_preventive_regressions(rows, now=NOW)
        assert len(flags) == 1
        assert flags[0]["prior_rec_id"] == "rec-101"
        assert flags[0]["preventive_action_excerpt"] == "Newer fix."

    def test_no_reader_constructed_in_read_path(self) -> None:
        """Critical Decision-88 guard: find_preventive_regressions never builds a DuckLake reader.

        Patches make_reader to raise; the function must still run correctly from the
        injected cache_rows list without ever touching the reader.
        """

        def _boom(*args, **kwargs):
            raise AssertionError("find_preventive_regressions() must not construct a DuckLake reader")

        rows = [
            _rec("rec-100", status="closed", closed_days_ago=10, preventive_action="Promote the check to --pre tier."),
            _rec("rec-200", status="open", created_days_ago=1),
        ]
        with patch("src.common.iceberg_reader.make_reader", side_effect=_boom):
            flags = find_preventive_regressions(rows, now=NOW)
        assert len(flags) == 1
