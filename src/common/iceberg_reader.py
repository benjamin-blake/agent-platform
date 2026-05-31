"""Engine-agnostic reader protocol and DuckDB-on-Iceberg implementation.

The Reader protocol defines the minimal verb surface so an Athena-backed
sibling can satisfy it without changing call sites (CD.8 engine-interchangeability).
DuckDBIcebergReader is the default implementation: pyiceberg GlueCatalog -> Arrow
-> DuckDB in-process, with predicate/projection pushdown into pyiceberg .scan()
and SCD2 dedup applied in DuckDB SQL.

Current state qualification:
- ops_recommendations, ops_decisions: ROW_NUMBER() OVER (PARTITION BY id
  ORDER BY last_updated_timestamp DESC) = 1  (Decision 56)
- ops_priority_queue: correlated subquery returning all entries from the
  latest curator run identified by queue_run_id  (Decision 70)

Credential resolution: resolve_aws_profile() returns the named agent_platform
profile when present (local / Claude-Code-on-the-web) and None when running
under CI OIDC (AWS_ACCESS_KEY_ID in environment), letting boto3 fall through
to ambient credentials.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_DEFAULT_DATABASE = "agent_platform"
_DEFAULT_REGION = "eu-west-2"
_DEFAULT_CATALOG_NAME = "agent_platform"

# pk used for ROW_NUMBER() dedup (Decision 56)
_TABLE_PARTITION_KEYS: dict[str, str] = {
    "ops_recommendations": "id",
    "ops_decisions": "id",
}

# tables using correlated-subquery current-state pattern (Decision 70)
_CORRELATED_SUBQUERY_TABLES: frozenset[str] = frozenset({"ops_priority_queue"})

_ORDER_BY_DEFAULT = "last_updated_timestamp"

# Valid SQL identifier pattern -- used to guard column-name interpolation
_COL_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")


class Reader(Protocol):
    """Minimal engine-agnostic read interface.

    Both DuckDBIcebergReader and any future Athena-backed implementation must
    satisfy this protocol without changing call sites (CD.8).
    """

    def current_state(
        self,
        table: str,
        *,
        partition_by: str = "id",
        order_by: str = _ORDER_BY_DEFAULT,
        row_filter: str | None = None,
        selected_fields: tuple[str, ...] | None = None,
        snapshot_id: int | None = None,
    ) -> list[dict]: ...

    def latest_snapshot(self, table: str) -> int | None: ...


class DuckDBIcebergReader:
    """DuckDB-on-Iceberg read layer.

    pyiceberg GlueCatalog resolves the table location; .scan() applies predicate
    and projection pushdown before Arrow materialization; DuckDB executes the
    current-state SQL (SCD2 ROW_NUMBER or priority-queue correlated subquery).

    Engine is exposed directly here as a pre-Lambda bridge (CD.8 note: hiding
    behind T0.7c/T0.8 verbs is deferred until those verbs land).
    """

    def __init__(
        self,
        profile: str | None = None,
        catalog_name: str = _DEFAULT_CATALOG_NAME,
        database: str = _DEFAULT_DATABASE,
        region: str = _DEFAULT_REGION,
    ) -> None:
        self._profile = profile
        self._catalog_name = catalog_name
        self._database = database
        self._region = region
        self._catalog_instance: Any = None

    def _catalog(self) -> Any:
        if self._catalog_instance is None:
            from pyiceberg.catalog.glue import GlueCatalog  # noqa: PLC0415

            from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

            resolved = resolve_aws_profile(self._profile)
            props: dict[str, str] = {
                "client.region": self._region,
                "s3.region": self._region,
            }
            if resolved is not None:
                props["client.profile-name"] = resolved
                props["s3.profile-name"] = resolved
            self._catalog_instance = GlueCatalog(self._catalog_name, **props)
        return self._catalog_instance

    def _load_arrow(
        self,
        table: str,
        *,
        row_filter: str | None = None,
        selected_fields: tuple[str, ...] | None = None,
        snapshot_id: int | None = None,
    ) -> Any:
        """Scan Iceberg table to a PyArrow Table with optional pushdown.

        row_filter and selected_fields are passed into pyiceberg .scan() so that
        partition pruning and column projection happen before materialisation --
        not as a post-filter on a full Arrow table.
        """
        catalog = self._catalog()
        iceberg_table = catalog.load_table(f"{self._database}.{table}")

        scan_kwargs: dict[str, Any] = {}
        if row_filter is not None:
            scan_kwargs["row_filter"] = row_filter
        if selected_fields is not None:
            scan_kwargs["selected_fields"] = selected_fields
        if snapshot_id is not None:
            scan_kwargs["snapshot_id"] = snapshot_id

        scan = iceberg_table.scan(**scan_kwargs)
        return scan.to_arrow()

    def latest_snapshot(self, table: str) -> int | None:
        """Return the id of the current snapshot for *table*, or None if the table is empty."""
        try:
            catalog = self._catalog()
            iceberg_table = catalog.load_table(f"{self._database}.{table}")
            snap = iceberg_table.current_snapshot()
            return snap.snapshot_id if snap is not None else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckDBIcebergReader.latest_snapshot: %s: %s", table, exc)
            return None

    def current_state(
        self,
        table: str,
        *,
        partition_by: str = "id",
        order_by: str = _ORDER_BY_DEFAULT,
        row_filter: str | None = None,
        selected_fields: tuple[str, ...] | None = None,
        snapshot_id: int | None = None,
    ) -> list[dict]:
        """Return current-state rows for *table* with SCD2 dedup applied in DuckDB.

        For ops_priority_queue: correlated subquery selecting all entries from
        the latest curator run (Decision 70).
        For all other tables: ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY
        last_updated_timestamp DESC) = 1 (Decision 56).

        Pushdown: row_filter and selected_fields are forwarded into pyiceberg
        .scan() before Arrow materialisation.

        Returns [] when the table is empty or unreachable (signals the caller
        to degrade gracefully when used from session_preflight).  Call sites
        that must raise on unreachable (Decision 69: ops_data_portal) should
        catch the exception themselves -- this method re-raises from _load_arrow.
        """
        import duckdb  # noqa: PLC0415

        for col, label in ((partition_by, "partition_by"), (order_by, "order_by")):
            if not _COL_NAME_RE.match(col):
                raise ValueError(f"DuckDBIcebergReader.current_state: invalid {label} column name: {col!r}")

        pk = _TABLE_PARTITION_KEYS.get(table, partition_by)

        arrow_table = self._load_arrow(
            table,
            row_filter=row_filter,
            selected_fields=selected_fields,
            snapshot_id=snapshot_id,
        )

        if arrow_table.num_rows == 0:
            return []

        with duckdb.connect() as con:
            con.register("_tbl", arrow_table)

            if table in _CORRELATED_SUBQUERY_TABLES:
                dedup_sql = (
                    "SELECT * FROM _tbl "
                    "WHERE queue_run_id = ("
                    "  SELECT queue_run_id FROM _tbl "
                    "  ORDER BY last_updated_timestamp DESC LIMIT 1"
                    ")"
                )
            else:
                dedup_sql = (
                    "SELECT * EXCLUDE(row_num) FROM ("
                    f"  SELECT *, ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY {order_by} DESC) AS row_num"
                    "  FROM _tbl"
                    ") WHERE row_num = 1"
                )

            cursor = con.execute(dedup_sql)
            col_names = [desc[0] for desc in cursor.description]
            return [dict(zip(col_names, row)) for row in cursor.fetchall()]

    def query(
        self,
        table: str,
        sql: str,
        *,
        params: tuple[Any, ...] = (),
        snapshot_id: int | None = None,
    ) -> list[dict] | None:
        """Execute *sql* against the current-state Arrow table for *table*.

        Builds the current-state view internally (same SCD2/correlated-subquery
        logic as current_state) then runs *sql* on top of it. Use ``{tbl}`` in
        *sql* as the table reference and ``?`` for bound params.

        Returns None on any exception so callers can degrade gracefully.

        This method exposes the engine directly as a pre-Lambda bridge.
        Engine-hiding is restored when T0.7c/T0.8 verbs land (CD.8).
        """
        import duckdb  # noqa: PLC0415

        try:
            arrow_table = self._load_arrow(table, snapshot_id=snapshot_id)

            if arrow_table.num_rows == 0:
                return []

            with duckdb.connect() as con:
                con.register("_tbl", arrow_table)

                if table in _CORRELATED_SUBQUERY_TABLES:
                    current_sql = (
                        "SELECT * FROM _tbl "
                        "WHERE queue_run_id = ("
                        "  SELECT queue_run_id FROM _tbl "
                        "  ORDER BY last_updated_timestamp DESC LIMIT 1"
                        ")"
                    )
                else:
                    pk = _TABLE_PARTITION_KEYS.get(table, "id")
                    current_sql = (
                        "SELECT * EXCLUDE(row_num) FROM ("
                        f"  SELECT *, ROW_NUMBER() OVER (PARTITION BY {pk} ORDER BY last_updated_timestamp DESC) AS row_num"
                        "  FROM _tbl"
                        ") WHERE row_num = 1"
                    )

                con.execute(f"CREATE TEMP VIEW _current AS {current_sql}")
                final_sql = sql.replace("{tbl}", "_current")
                cursor = con.execute(final_sql, list(params))
                col_names = [desc[0] for desc in cursor.description]
                return [dict(zip(col_names, row)) for row in cursor.fetchall()]

        except Exception as exc:  # noqa: BLE001
            logger.warning("DuckDBIcebergReader.query: %s: %s", table, exc)
            return None
