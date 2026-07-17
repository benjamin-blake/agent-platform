"""Unit tests for scripts.ops_portal.ci_rca_lifecycle (ci-rca-identity-lifecycle, Decision 136).

Status-aware chain dedup, regression-vs-drop ancestry classification (mocked git ancestry)
INCLUDING the legacy closed-head-with-no-fixed_by_sha fail-closed-to-regression case,
regression-record fields, flake escalation, the timestamp-based inactivity-close predicate,
stamp_fixed_by_sha, and escape-attribution.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from scripts.ops_portal.ci_rca_lifecycle import (
    ChainRecord,
    check_flake_escalation,
    classify_closed_head,
    closed_head_of_chain,
    compute_escape_class,
    current_commit_sha,
    file_regression_record,
    is_inactive,
    list_open_ci_rca_recs,
    newest_open_in_chain,
    resolve_chain,
    stamp_fixed_by_sha,
)

_FINGERPRINT = "a" * 64


def _row(rec_id: str, status: str, fingerprint: str = _FINGERPRINT, last_updated: str = "", created: str = "", **ctx_extra):
    ctx = {"fingerprint": fingerprint, **ctx_extra}
    return {
        "id": rec_id,
        "status": status,
        "last_updated_timestamp": last_updated,
        "created_timestamp": created,
        "context_v2_json": json.dumps(ctx),
    }


class TestResolveChain:
    """VP6 target (`-k "chain_newest_open"`)."""

    def test_chain_newest_open_orders_newest_first(self):
        rows = [
            _row("rec-1", "closed", last_updated="2026-01-01T00:00:00Z"),
            _row("rec-2", "open", last_updated="2026-06-01T00:00:00Z"),
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            chain = resolve_chain(_FINGERPRINT)
        assert [r.rec_id for r in chain] == ["rec-2", "rec-1"]

    def test_falls_back_to_created_timestamp_when_no_last_updated(self):
        rows = [
            _row("rec-1", "open", last_updated="", created="2026-01-01T00:00:00Z"),
            _row("rec-2", "open", last_updated="", created="2026-06-01T00:00:00Z"),
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            chain = resolve_chain(_FINGERPRINT)
        assert chain[0].rec_id == "rec-2"

    def test_non_matching_fingerprint_excluded(self):
        rows = [_row("rec-1", "open", fingerprint="b" * 64)]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert resolve_chain(_FINGERPRINT) == []

    def test_no_context_v2_json_excluded(self):
        rows = [{"id": "rec-1", "status": "open", "context_v2_json": None}]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert resolve_chain(_FINGERPRINT) == []

    def test_malformed_context_v2_json_excluded_not_raised(self):
        rows = [{"id": "rec-1", "status": "open", "context_v2_json": "not-json"}]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert resolve_chain(_FINGERPRINT) == []

    def test_fixed_by_sha_carried_into_chain_record(self):
        rows = [_row("rec-1", "closed", fixed_by_sha="deadbeef")]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            chain = resolve_chain(_FINGERPRINT)
        assert chain[0].fixed_by_sha == "deadbeef"


class TestNewestOpenInChain:
    """VP6 target: only bump if the NEWEST record is open."""

    def test_newest_open_returns_id(self):
        rows = [
            _row("rec-old", "closed", last_updated="2026-01-01T00:00:00Z"),
            _row("rec-new", "open", last_updated="2026-06-01T00:00:00Z"),
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert newest_open_in_chain(_FINGERPRINT) == "rec-new"

    def test_closed_head_not_bumped_returns_none(self):
        """VP6 target (`-k "closed_head_not_bumped"`): a closed newest record is never bumped --
        newest_open_in_chain returns None even though an OLDER open record exists in the chain."""
        rows = [
            _row("rec-old-open", "open", last_updated="2026-01-01T00:00:00Z"),
            _row("rec-new-closed", "closed", last_updated="2026-06-01T00:00:00Z"),
        ]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert newest_open_in_chain(_FINGERPRINT) is None

    def test_empty_chain_returns_none(self):
        reader = MagicMock()
        reader.current_state.return_value = []
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert newest_open_in_chain(_FINGERPRINT) is None


class TestClosedHeadOfChain:
    def test_closed_newest_returned(self):
        rows = [_row("rec-1", "closed")]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            head = closed_head_of_chain(_FINGERPRINT)
        assert head is not None
        assert head.rec_id == "rec-1"

    def test_open_newest_returns_none(self):
        rows = [_row("rec-1", "open")]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert closed_head_of_chain(_FINGERPRINT) is None


class TestClassifyClosedHead:
    """VP7 target (`-k "regression or stale_rerun_drop or legacy_closed_no_sha"`)."""

    def test_stale_rerun_drop_when_ancestor(self):
        head = ChainRecord(rec_id="rec-1", status="closed", fixed_by_sha="fixed_sha", last_touched="")
        with patch("scripts.ops_portal.ci_rca_lifecycle._is_ancestor", return_value=True) as mock_ancestor:
            verdict = classify_closed_head("failing_sha", head)
        assert verdict == "drop"
        mock_ancestor.assert_called_once_with("failing_sha", "fixed_sha", cwd=None)

    def test_regression_when_not_ancestor(self):
        head = ChainRecord(rec_id="rec-1", status="closed", fixed_by_sha="fixed_sha", last_touched="")
        with patch("scripts.ops_portal.ci_rca_lifecycle._is_ancestor", return_value=False):
            verdict = classify_closed_head("failing_sha", head)
        assert verdict == "regression"

    def test_legacy_closed_no_sha_fails_closed_to_regression(self):
        """A closed head with NO fixed_by_sha (every rec closed before this change; a manual
        closure) cannot run the ancestry check -- fails CLOSED to regression, never a silent drop."""
        head = ChainRecord(rec_id="rec-1", status="closed", fixed_by_sha=None, last_touched="")
        with patch("scripts.ops_portal.ci_rca_lifecycle._is_ancestor") as mock_ancestor:
            verdict = classify_closed_head("failing_sha", head)
        assert verdict == "regression"
        mock_ancestor.assert_not_called()

    def test_no_failing_sha_fails_closed_to_regression(self):
        """current_commit_sha() returning empty (git call failed) must not silently drop either."""
        head = ChainRecord(rec_id="rec-1", status="closed", fixed_by_sha="fixed_sha", last_touched="")
        with patch("scripts.ops_portal.ci_rca_lifecycle._is_ancestor") as mock_ancestor:
            verdict = classify_closed_head("", head)
        assert verdict == "regression"
        mock_ancestor.assert_not_called()

    def test_no_status_flip_in_any_case(self):
        """Neither classify_closed_head verdict path ever returns anything resembling a status
        transition -- only the two named string verdicts exist."""
        head_with_sha = ChainRecord(rec_id="rec-1", status="closed", fixed_by_sha="x", last_touched="")
        head_without_sha = ChainRecord(rec_id="rec-2", status="closed", fixed_by_sha=None, last_touched="")
        with patch("scripts.ops_portal.ci_rca_lifecycle._is_ancestor", return_value=True):
            assert classify_closed_head("s", head_with_sha) in ("drop", "regression")
        assert classify_closed_head("s", head_without_sha) in ("drop", "regression")


class TestFileRegressionRecord:
    def test_sets_regression_of_and_critical_priority(self):
        fields = {"title": "Something broke", "priority": "Medium"}
        ctx = {"fingerprint": _FINGERPRINT}
        new_fields, new_ctx = file_regression_record(fields, ctx, "rec-999")
        assert new_fields["title"] == "REGRESSION: Something broke"
        assert new_fields["priority"] == "Critical"
        assert new_ctx["regression_of"] == "rec-999"

    def test_does_not_mutate_caller_dicts(self):
        fields = {"title": "X", "priority": "low"}
        ctx = {"a": 1}
        file_regression_record(fields, ctx, "rec-1")
        assert fields == {"title": "X", "priority": "low"}
        assert ctx == {"a": 1}

    def test_idempotent_double_prefix_not_added(self):
        fields = {"title": "REGRESSION: already prefixed"}
        new_fields, _ = file_regression_record(fields, {}, "rec-1")
        assert new_fields["title"] == "REGRESSION: already prefixed"

    def test_empty_title_becomes_bare_regression(self):
        new_fields, _ = file_regression_record({}, {}, "rec-1")
        assert new_fields["title"] == "REGRESSION"


class TestStampFixedBySha:
    """VP13 target (`-k "fixed_by_sha_recorded or stamp_fixed_by_sha"`)."""

    def test_stamp_fixed_by_sha_recorded_via_portal(self):
        existing_ctx = json.dumps({"fingerprint": _FINGERPRINT})
        fake_sha = "deadbeef1234"  # pragma: allowlist secret -- synthetic test git sha, not a real secret
        with (
            patch(
                "scripts.ops_data_portal._fetch_rec_from_reader", return_value={"id": "rec-1", "context_v2_json": existing_ctx}
            ),
            patch("scripts.ops_data_portal.update_rec") as mock_update,
        ):
            stamp_fixed_by_sha("rec-1", fake_sha)

        mock_update.assert_called_once()
        call_args, call_kwargs = mock_update.call_args
        assert call_args[0] == "rec-1"
        updated_ctx = json.loads(call_args[1]["context_v2_json"])
        assert updated_ctx["fixed_by_sha"] == fake_sha
        assert updated_ctx["fingerprint"] == _FINGERPRINT

    def test_stamp_fixed_by_sha_raises_on_missing_rec(self):
        with patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value=None):
            with pytest.raises(RuntimeError, match="does not exist"):
                stamp_fixed_by_sha("rec-nope", "deadbeef")

    def test_stamp_fixed_by_sha_malformed_context_recovers(self):
        with (
            patch(
                "scripts.ops_data_portal._fetch_rec_from_reader",
                return_value={"id": "rec-1", "context_v2_json": "not-json"},
            ),
            patch("scripts.ops_data_portal.update_rec") as mock_update,
        ):
            stamp_fixed_by_sha("rec-1", "deadbeef")

        updated_ctx = json.loads(mock_update.call_args[0][1]["context_v2_json"])
        assert updated_ctx["fixed_by_sha"] == "deadbeef"

    def test_stamp_fixed_by_sha_no_existing_context(self):
        with (
            patch("scripts.ops_data_portal._fetch_rec_from_reader", return_value={"id": "rec-1", "context_v2_json": None}),
            patch("scripts.ops_data_portal.update_rec") as mock_update,
        ):
            stamp_fixed_by_sha("rec-1", "cafefeed")

        updated_ctx = json.loads(mock_update.call_args[0][1]["context_v2_json"])
        assert updated_ctx["fixed_by_sha"] == "cafefeed"


class TestFlakeEscalation:
    """VP9 target (`-k "flaky_escalation"`)."""

    def test_flaky_escalation_chain_reaching_three_is_flaky(self):
        rows = [_row(f"rec-{i}", "closed") for i in range(3)]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert check_flake_escalation(_FINGERPRINT) is True

    def test_flaky_escalation_chain_of_two_not_flaky(self):
        rows = [_row(f"rec-{i}", "closed") for i in range(2)]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert check_flake_escalation(_FINGERPRINT) is False

    def test_flaky_escalation_chain_exceeding_three_is_flaky(self):
        rows = [_row(f"rec-{i}", "closed") for i in range(5)]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert check_flake_escalation(_FINGERPRINT) is True


class TestInactivityClose:
    """VP9 target (`-k "inactivity_close"`)."""

    def test_inactivity_close_old_and_old_enough_is_inactive(self):
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=45)).isoformat()
        assert is_inactive({"last_seen": old}, old, now=now) is True

    def test_inactivity_close_recently_seen_stays_open(self):
        now = datetime.now(timezone.utc)
        recent = (now - timedelta(days=2)).isoformat()
        old_created = (now - timedelta(days=60)).isoformat()
        assert is_inactive({"last_seen": recent}, old_created, now=now) is False

    def test_inactivity_close_young_rec_stays_open_even_if_last_seen_old(self):
        """The created-age floor: a rec created only 5 days ago never auto-closes, even if
        last_seen looks stale (it never had a chance to recur yet)."""
        now = datetime.now(timezone.utc)
        old_last_seen = (now - timedelta(days=45)).isoformat()
        young_created = (now - timedelta(days=5)).isoformat()
        assert is_inactive({"last_seen": old_last_seen}, young_created, now=now) is False

    def test_inactivity_close_falls_back_to_created_timestamp_when_no_last_seen(self):
        now = datetime.now(timezone.utc)
        old_created = (now - timedelta(days=45)).isoformat()
        assert is_inactive({}, old_created, now=now) is True

    def test_inactivity_close_unparseable_timestamp_never_closes(self):
        assert is_inactive({"last_seen": "not-a-date"}, "not-a-date") is False

    def test_inactivity_close_missing_all_timestamps_never_closes(self):
        assert is_inactive({}, "") is False

    def test_inactivity_close_exactly_at_min_age_boundary_is_inclusive(self):
        now = datetime.now(timezone.utc)
        created = (now - timedelta(days=14)).isoformat()
        old_last_seen = (now - timedelta(days=45)).isoformat()
        assert is_inactive({"last_seen": old_last_seen}, created, now=now) is True


class TestListOpenCiRcaRecs:
    def test_returns_only_open_rows(self):
        rows = [_row("rec-1", "open"), _row("rec-2", "closed")]
        reader = MagicMock()
        reader.current_state.return_value = rows
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            open_recs = list_open_ci_rca_recs()
        assert [r["id"] for r in open_recs] == ["rec-1"]

    def test_empty_when_no_rows(self):
        reader = MagicMock()
        reader.current_state.return_value = []
        with patch("src.common.iceberg_reader.make_reader", return_value=reader):
            assert list_open_ci_rca_recs() == []


class TestEscapeClass:
    """VP10 target (`-k "escape_class"`)."""

    def test_escape_class_capped_when_deferred(self):
        manifest = {"selected": [], "deferred": ["tests/test_foo.py"]}
        assert compute_escape_class("tests/test_foo.py::test_bar", manifest) == "capped"

    def test_escape_class_no_edge_when_absent_from_selected(self):
        manifest = {"selected": ["tests/test_other.py"], "deferred": []}
        assert compute_escape_class("tests/test_foo.py::test_bar", manifest) == "no-edge"

    def test_escape_class_unknown_data_edge_when_selected_but_still_failed(self):
        manifest = {"selected": ["tests/test_foo.py"], "deferred": []}
        assert compute_escape_class("tests/test_foo.py::test_bar", manifest) == "unknown-data-edge"

    def test_escape_class_deferred_takes_priority_over_selected(self):
        """A file cannot be both selected AND deferred in a real manifest, but the priority order
        (deferred checked first) is a deliberate defensive choice, verified directly."""
        manifest = {"selected": ["tests/test_foo.py"], "deferred": ["tests/test_foo.py"]}
        assert compute_escape_class("tests/test_foo.py::test_bar", manifest) == "capped"

    def test_escape_class_nodeid_without_double_colon_uses_whole_string_as_file(self):
        manifest = {"selected": ["tests/test_foo.py"], "deferred": []}
        assert compute_escape_class("tests/test_foo.py", manifest) == "unknown-data-edge"


class TestCurrentCommitSha:
    def test_returns_stdout_on_success(self):
        result = MagicMock(returncode=0, stdout="abc123\n")
        with patch("subprocess.run", return_value=result):
            assert current_commit_sha() == "abc123"

    def test_returns_empty_string_on_failure(self):
        result = MagicMock(returncode=1, stdout="")
        with patch("subprocess.run", return_value=result):
            assert current_commit_sha() == ""


class TestIsAncestorRealGit:
    """Real (non-mocked) git merge-base --is-ancestor call -- classify_closed_head's tests mock
    _is_ancestor directly, so this exercises its own subprocess body against this repo's HEAD."""

    def test_head_is_ancestor_of_itself(self):
        from scripts.ops_portal.ci_rca_lifecycle import _is_ancestor

        head = current_commit_sha()
        assert head, "expected a real HEAD sha in this repo checkout"
        assert _is_ancestor(head, head) is True

    def test_bogus_sha_is_not_an_ancestor(self):
        from scripts.ops_portal.ci_rca_lifecycle import _is_ancestor

        head = current_commit_sha()
        assert _is_ancestor("0000000000000000000000000000000000000000", head) is False


class TestParseTsNaiveDatetime:
    def test_naive_timestamp_treated_as_utc(self):
        """No explicit test currently exercises the naive-datetime (no tzinfo) branch of
        _parse_ts via is_inactive -- a last_seen value with no offset must still be usable."""
        now = datetime.now(timezone.utc)
        naive_old = (now - timedelta(days=45)).replace(tzinfo=None).isoformat()
        naive_created = (now - timedelta(days=60)).replace(tzinfo=None).isoformat()
        assert is_inactive({"last_seen": naive_old}, naive_created, now=now) is True
