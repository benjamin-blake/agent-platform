"""Shared test doubles for the tests/common/test_ducklake_*.py mirror suite (rec-2709 Wave 7).

Cross-bucket shared helpers hoisted out of the former tests/test_ducklake_runtime.py monolith:
FakeCon (the DuckDB-connection double used across the writes/tables/reads/runtime mirrors) and
_SEMANTICS (the smoke-table field-semantics dict used by the writes + runtime mirrors). An
importable tests/fixtures/ module -- exempt from the no-cross-test-import guard because its name
does not start with test_ (tests/CLAUDE.md).

FakeCon references rt.SMOKE_HISTORY_TABLE / rt.SMOKE_CURRENT_TABLE, so this module imports
src.common.ducklake_runtime directly (not the tests/common/test_ducklake_runtime.py mirror).
"""

from __future__ import annotations

from src.common import ducklake_runtime as rt

_SEMANTICS = {
    "fields": {
        "ulid": {"role": "derived", "sql_type": "VARCHAR", "nullable": False},
        "rec_id": {"role": "input", "sql_type": "VARCHAR", "nullable": False},
        "created_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
        "last_updated_timestamp": {"role": "derived", "sql_type": "TIMESTAMP WITH TIME ZONE", "nullable": False},
        "payload": {"role": "input", "sql_type": "VARCHAR", "nullable": True},
    }
}


class FakeCon:
    """DuckDB-connection double: records (sql, params); simulates OCC + hard failures + reads."""

    def __init__(
        self,
        *,
        created_lookup: list | None = None,
        occ_fail_times: int = 0,
        hard_fail_substr: str | None = None,
        read_rows: list | None = None,
        rollback_raises: bool = False,
    ):
        self.executed: list[tuple[str, list | None]] = []
        self._created_lookup = created_lookup  # None/[] -> insert path; [(ts,)] -> update path
        self._occ_fail_times = occ_fail_times
        self._merge_hist_calls = 0
        self._hard_fail_substr = hard_fail_substr
        self._read_rows = read_rows or []
        self._rollback_raises = rollback_raises
        self._last = ""
        self.description = [
            ("ulid",),
            ("rec_id",),
            ("payload",),
            ("created_timestamp",),
            ("last_updated_timestamp",),
        ]
        self.closed = False

    def execute(self, sql, params=None):
        self._last = sql
        self.executed.append((sql, params))
        if self._rollback_raises and sql == "ROLLBACK":
            raise RuntimeError("no active transaction")
        if self._hard_fail_substr and self._hard_fail_substr in sql:
            raise ValueError("hard failure -- not a collision")
        if rt.SMOKE_HISTORY_TABLE in sql and sql.startswith("MERGE INTO"):
            self._merge_hist_calls += 1
            if self._merge_hist_calls <= self._occ_fail_times:
                raise RuntimeError("could not serialize access due to concurrent update")
        return self

    def fetchall(self):
        if self._last.startswith("SELECT created_timestamp"):
            return self._created_lookup or []
        if self._last.startswith("SELECT ulid"):
            return self._read_rows
        return []

    def merge_history_params(self) -> list[list]:
        """All params bound to the history MERGE, one per attempt."""
        return [p for sql, p in self.executed if rt.SMOKE_HISTORY_TABLE in sql and sql.startswith("MERGE INTO")]
