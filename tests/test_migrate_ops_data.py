"""Tests for scripts/migrate_ops_data.py (Phase C one-time ops migration)."""

from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import scripts.migrate_ops_data as mod

# Athena get_query_results returns every column as a string. These mimic the SOURCE
# *_current views. rec-007 is deliberately unmigratable (empty acceptance).
_RAW_RECS = [
    {
        "id": "rec-005",
        "title": "Five",
        "source": "planning",
        "effort": "S",
        "priority": "High",
        "file": "scripts/a.py",
        "context": "ctx5",
        "acceptance": "grep -q x scripts/a.py",
        "status": "open",
        "created_timestamp": "2026-01-01T00:00:00+00:00",
        "dependencies": "[]",
        "tags": "[]",
        "execution_steps": "",
        "automatable": "true",
        "risk": "low",
        "last_updated_timestamp": "2026-04-04T00:00:00+00:00",
    },
    {
        "id": "rec-006",
        "title": "Six",
        "source": "manual",
        "effort": "M",
        "priority": "Low",
        "file": "scripts/b.py",
        "context": "ctx6",
        "acceptance": "grep -q y scripts/b.py",
        "status": "closed",
        "created_timestamp": "2026-02-02T00:00:00+00:00",
        "dependencies": "[]",
        "tags": "[]",
        "execution_steps": "",
        "automatable": "false",
        "risk": "low",
        "last_updated_timestamp": "2026-04-04T00:00:00+00:00",
    },
]
_RAW_RECS_WITH_INVALID = _RAW_RECS + [
    {
        "id": "rec-007",
        "title": "Seven",
        "source": "planning",
        "effort": "S",
        "priority": "Low",
        "file": "scripts/c.py",
        "context": "ctx7",
        "acceptance": "",  # missing required field
        "status": "open",
        "created_timestamp": "2026-03-03T00:00:00+00:00",
        "dependencies": "[]",
        "tags": "[]",
        "execution_steps": "",
        "automatable": "true",
        "risk": "low",
    },
]
_RAW_DECS = [
    {
        "id": "dec-010",
        "decision_id": "10",
        "title": "Dec ten",
        "status": "accepted",
        "created_timestamp": "2026-03-03T00:00:00+00:00",
        "last_updated_timestamp": "2026-04-04T00:00:00+00:00",
        "related_decisions": "[]",
        "problem": "",
        "decision_text": "",
        "context": "",
        "decided_date": "",
    },
]
_SAMPLE_ROWS = [
    {"id": "rec-005", "title": "Five", "source": "planning", "created_timestamp": "2026-01-01T00:00:00+00:00"},
    {"id": "rec-006", "title": "Six", "source": "manual", "created_timestamp": "2026-02-02T00:00:00+00:00"},
]


class _FakeAthena:
    """Dispatch _athena_rows by query string; count queries return 0 before writes, N after."""

    def __init__(self, raw_recs, raw_decs, expected_recs, expected_decs, dest_nonempty=False):
        self.raw_recs = raw_recs
        self.raw_decs = raw_decs
        self.expected_recs = expected_recs
        self.expected_decs = expected_decs
        self.dest_nonempty = dest_nonempty
        self.rec_count_calls = 0
        self.dec_count_calls = 0

    def __call__(self, session, query, workgroup):
        q = query.strip()
        if q.startswith("SELECT * FROM trading_formulas_db.ops_recommendations_current"):
            return [dict(r) for r in self.raw_recs]
        if q.startswith("SELECT * FROM trading_formulas_db.ops_decisions_current"):
            return [dict(r) for r in self.raw_decs]
        if "count(*) AS n" in q and "ops_recommendations_current" in q:
            self.rec_count_calls += 1
            if self.rec_count_calls == 1:
                return [{"n": str(len(self.raw_recs)) if self.dest_nonempty else "0"}]
            return [{"n": str(self.expected_recs)}]
        if "count(*) AS n" in q and "ops_decisions_current" in q:
            self.dec_count_calls += 1
            if self.dec_count_calls == 1:
                return [{"n": str(len(self.raw_decs)) if self.dest_nonempty else "0"}]
            return [{"n": str(self.expected_decs)}]
        if q.startswith("SELECT id FROM agent_platform.ops_recommendations_current"):
            return [{"id": "rec-005"}, {"id": "rec-006"}]
        if q.startswith("SELECT id FROM agent_platform.ops_decisions_current"):
            return [{"id": "dec-010"}]
        if q.startswith("SELECT id, title, source, created_timestamp"):
            return [dict(r) for r in _SAMPLE_ROWS]
        raise AssertionError(f"unexpected query: {query}")


@pytest.fixture(autouse=True)
def _restore_env():
    saved = {k: os.environ.get(k) for k in ("AWS_PROFILE", "S3_LOG_BUCKET")}
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _run(
    *,
    dry_run=False,
    force_skip_existing=False,
    source_workgroup="company-aws-workgroup",
    raw_recs=None,
    raw_decs=None,
    expected_recs=2,
    expected_decs=1,
    dest_nonempty=False,
    file_rec=None,
    file_decision=None,
    summary_path=None,
):
    """Invoke migrate() with all external I/O patched. Returns (exit_code, file_rec, file_decision, sync, ow_write)."""
    fake = _FakeAthena(
        raw_recs if raw_recs is not None else _RAW_RECS,
        raw_decs if raw_decs is not None else _RAW_DECS,
        expected_recs,
        expected_decs,
        dest_nonempty=dest_nonempty,
    )
    file_rec = file_rec or MagicMock(side_effect=lambda fields, **kw: f"rec-{kw['_migration_int_id']:03d}")
    file_decision = file_decision or MagicMock(side_effect=lambda fields, **kw: f"dec-{kw['_migration_int_id']:03d}")
    sync = MagicMock(return_value={})
    ow_write = MagicMock()

    with ExitStack() as stack:
        stack.enter_context(patch("boto3.Session", return_value=MagicMock()))
        stack.enter_context(patch("scripts.ops_writer.DATABASE", "agent_platform"))
        stack.enter_context(patch("scripts.ops_writer.ATHENA_WORKGROUP", "agent-platform-production"))
        stack.enter_context(patch("scripts.ops_writer.OpsWriter.write", ow_write))
        stack.enter_context(patch("scripts.migrate_ops_data._athena_rows", fake))
        stack.enter_context(patch("scripts.migrate_ops_data._read_counter", side_effect=lambda s, n: 99999))
        stack.enter_context(patch("scripts.ops_data_portal.file_rec", file_rec))
        stack.enter_context(patch("scripts.ops_data_portal.file_decision", file_decision))
        stack.enter_context(patch("scripts.ops_data_portal.sync", sync))
        stack.enter_context(patch("scripts.sync_recommendations.reseed_recommendations_counter"))
        stack.enter_context(patch("scripts.sync_recommendations.reseed_decisions_counter"))
        if summary_path is not None:
            stack.enter_context(patch("scripts.migrate_ops_data._SUMMARY_PATH", summary_path))
        code = mod.migrate(
            profile_source="company-aws-profile",
            profile_dest="agent_platform",
            source_workgroup=source_workgroup,
            dry_run=dry_run,
            force_skip_existing=force_skip_existing,
        )
    return code, file_rec, file_decision, sync, ow_write


def test_dry_run_zero_writes(tmp_path: Path) -> None:
    summary = tmp_path / "summary.json"
    code, file_rec, file_decision, sync, _ = _run(dry_run=True, summary_path=summary)
    assert code == 0
    file_rec.assert_not_called()
    file_decision.assert_not_called()
    sync.assert_not_called()
    import json

    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["source_recs"] == 2
    assert data["source_decisions"] == 1
    assert data["dry_run"] is True


def test_happy_path_portal_calls(tmp_path: Path) -> None:
    code, file_rec, file_decision, sync, _ = _run(summary_path=tmp_path / "s.json")
    assert code == 0
    assert file_rec.call_count == 2
    assert file_decision.call_count == 1
    sync.assert_called_once()
    for call in file_rec.call_args_list:
        assert call.kwargs["_migration_int_id"] is not None
        assert call.kwargs["_skip_sync"] is True
        assert call.kwargs["_migration_mode"] is True
    dec_call = file_decision.call_args_list[0]
    assert dec_call.kwargs["_migration_int_id"] == 10
    assert dec_call.kwargs["_skip_sync"] is True


def test_source_preserved(tmp_path: Path) -> None:
    _, file_rec, _, _, _ = _run(summary_path=tmp_path / "s.json")
    by_id = {c.kwargs["_migration_int_id"]: c.args[0] for c in file_rec.call_args_list}
    assert by_id[5]["source"] == "planning"
    assert by_id[5]["created_timestamp"] == "2026-01-01T00:00:00+00:00"
    assert by_id[6]["source"] == "manual"


def test_opswriter_write_never_called_directly(tmp_path: Path) -> None:
    _, _, _, _, ow_write = _run(summary_path=tmp_path / "s.json")
    ow_write.assert_not_called()


def test_no_logs_path_read(tmp_path: Path) -> None:
    real_open = open
    reads: list[str] = []

    def recording_open(file, mode="r", *args, **kwargs):
        if "logs" in str(file).replace("\\", "/") and (mode == "r" or mode.startswith("r")):
            reads.append(str(file))
        return real_open(file, mode, *args, **kwargs)

    with patch("builtins.open", side_effect=recording_open):
        code, *_ = _run(summary_path=tmp_path / "s.json")
    assert code == 0
    assert reads == [], f"migration read logs/ path(s) as input: {reads}"


def test_idempotency_refusal(tmp_path: Path) -> None:
    code, file_rec, file_decision, sync, _ = _run(dest_nonempty=True, summary_path=tmp_path / "s.json")
    assert code == 1
    file_rec.assert_not_called()
    file_decision.assert_not_called()
    sync.assert_not_called()


def test_outbox_sentinel_fails_loudly(tmp_path: Path) -> None:
    sentinel_rec = MagicMock(side_effect=lambda fields, **kw: "pending-deadbeef")
    code, file_rec, file_decision, sync, _ = _run(file_rec=sentinel_rec, summary_path=tmp_path / "s.json")
    assert code == 1
    sync.assert_not_called()


def test_skipped_invalid_excluded_from_count(tmp_path: Path) -> None:
    summary = tmp_path / "s.json"
    # 3 source recs, 1 invalid -> expected dest = 2.
    code, file_rec, _, _, _ = _run(raw_recs=_RAW_RECS_WITH_INVALID, expected_recs=2, summary_path=summary)
    assert code == 0
    assert file_rec.call_count == 2
    import json

    data = json.loads(summary.read_text(encoding="utf-8"))
    assert len(data["skipped_invalid"]) == 1
    assert data["skipped_invalid"][0]["id"] == "rec-007"


def test_unregistered_source_aborts(tmp_path: Path) -> None:
    stray = [dict(_RAW_RECS[0], id="rec-005", source="totally-unregistered-source")]
    summary = tmp_path / "s.json"
    code, file_rec, _, sync, _ = _run(raw_recs=stray, summary_path=summary)
    assert code == 1
    file_rec.assert_not_called()
    import json

    data = json.loads(summary.read_text(encoding="utf-8"))
    assert "totally-unregistered-source" in data["unregistered_sources"]


def test_source_workgroup_threaded(tmp_path: Path) -> None:
    """--source-workgroup reaches the SOURCE reads; dest count reads keep the dest workgroup."""
    base = _FakeAthena(_RAW_RECS, _RAW_DECS, 2, 1)
    seen: list[tuple[str, str]] = []

    def recording(session, query, workgroup):
        seen.append((query.strip(), workgroup))
        return base(session, query, workgroup)

    file_rec = MagicMock(side_effect=lambda fields, **kw: f"rec-{kw['_migration_int_id']:03d}")
    file_decision = MagicMock(side_effect=lambda fields, **kw: f"dec-{kw['_migration_int_id']:03d}")
    with ExitStack() as stack:
        stack.enter_context(patch("boto3.Session", return_value=MagicMock()))
        stack.enter_context(patch("scripts.ops_writer.DATABASE", "agent_platform"))
        stack.enter_context(patch("scripts.ops_writer.ATHENA_WORKGROUP", "agent-platform-production"))
        stack.enter_context(patch("scripts.ops_writer.OpsWriter.write", MagicMock()))
        stack.enter_context(patch("scripts.migrate_ops_data._athena_rows", recording))
        stack.enter_context(patch("scripts.migrate_ops_data._read_counter", side_effect=lambda s, n: 99999))
        stack.enter_context(patch("scripts.ops_data_portal.file_rec", file_rec))
        stack.enter_context(patch("scripts.ops_data_portal.file_decision", file_decision))
        stack.enter_context(patch("scripts.ops_data_portal.sync", MagicMock(return_value={})))
        stack.enter_context(patch("scripts.sync_recommendations.reseed_recommendations_counter"))
        stack.enter_context(patch("scripts.sync_recommendations.reseed_decisions_counter"))
        stack.enter_context(patch("scripts.migrate_ops_data._SUMMARY_PATH", tmp_path / "s.json"))
        code = mod.migrate(
            profile_source="company-aws-profile",
            profile_dest="agent_platform",
            source_workgroup="real-source-wg",
            dry_run=False,
            force_skip_existing=False,
        )
    assert code == 0
    source_wgs = [wg for q, wg in seen if q.startswith("SELECT * FROM trading_formulas_db")]
    assert source_wgs and all(wg == "real-source-wg" for wg in source_wgs)
    dest_wgs = [wg for q, wg in seen if "count(*) AS n" in q]
    assert dest_wgs and all(wg == "agent-platform-production" for wg in dest_wgs)


def test_main_threads_source_workgroup() -> None:
    """main() forwards --source-workgroup (placeholder default and explicit override) to migrate()."""
    with patch("scripts.migrate_ops_data.migrate", return_value=0) as m:
        assert mod.main(["--dry-run"]) == 0
        assert m.call_args.kwargs["source_workgroup"] == mod._DEFAULT_SOURCE_WORKGROUP
        assert mod.main(["--source-workgroup", "wg-override"]) == 0
        assert m.call_args.kwargs["source_workgroup"] == "wg-override"
