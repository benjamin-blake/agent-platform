"""SCD2 schema layer -- pure, I/O-free SQL-generation and validation (T2.19 / CD.33, Decision 81).

The seam between this module and ducklake_runtime is the pure/impure boundary:
  - ducklake_scd2_schema: WHAT the schema IS and how to render its SQL (I/O-free, DB-free).
  - ducklake_runtime: WHAT the schema DOES (connection, transaction, OCC, reads, metrics).

Dependency is strictly one-directional: runtime imports schema, never the reverse.
Pure functions here are DB-free and unit-testable by asserting on SQL strings alone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CATALOG_ALIAS = "ops_catalog"

# Representative SCD2 smoke-table pair (real ops_* business schema is T2.19).
SMOKE_HISTORY_TABLE = "ducklake_smoke_history"
SMOKE_CURRENT_TABLE = "ducklake_smoke_current"

_FIELD_SEMANTICS_ENV = "DUCKLAKE_FIELD_SEMANTICS_PATH"
_DEFAULT_FIELD_SEMANTICS_PATH = Path(__file__).resolve().parents[2] / "config" / "lambda" / "ducklake" / "field_semantics.yaml"

# SQL-type -> Python type for the schema gate's input-field validation. Extended for the real ops_*
# column types (T2.19): arrays (tags/dependencies/related_decisions -> list), integers
# (decision_id/execution_steps/rank -> int), booleans (automatable -> bool). DuckDB array types are
# spelled `<base>[]` (e.g. VARCHAR[], BIGINT[]); they map to a Python list at the gate.
_PY_TYPE_FOR_SQL: dict[str, type] = {
    "VARCHAR": str,
    "TIMESTAMP WITH TIME ZONE": datetime,
    "BIGINT": int,
    "INTEGER": int,
    "BOOLEAN": bool,
    "VARCHAR[]": list,
    "BIGINT[]": list,
    "INTEGER[]": list,
}


# ---------------------------------------------------------------------------
# Exceptions -- all loud-fail (Decision 55)
# ---------------------------------------------------------------------------


class DuckLakeRuntimeError(RuntimeError):
    """Base for all DuckLake runtime loud-fail conditions."""


class SchemaGateError(DuckLakeRuntimeError):
    """Raised when a write record fails the schema gate (unknown/derived/missing/mis-typed field)."""


class ReferentialError(DuckLakeRuntimeError):
    """Raised when an update targets a merge-key absent from the current projection (CD.33 cl.8 / D-5).

    The in-transaction existence check replaces the prior permissive upsert-on-absent: an update of a
    non-existent record loud-fails instead of silently creating a partial row.
    """


class AppendOnlyUpdateError(DuckLakeRuntimeError):
    """Raised when require_exists=True is passed for an append_only table (Decision 70 / write-once lifecycle).

    Append-only tables are write-once; the update path is illegal. Record state changes as new events
    with a distinct merge_key.
    """


class StatusTransitionError(DuckLakeRuntimeError):
    """Raised when an update would silently REACTIVATE a resolved rec (closed/declined/superseded -> open).

    Distinct from scripts/contracts_enforcement.check_status_transition (the contract-lifecycle check)
    to avoid a same-name collision (Decision 103: the DAG is a resolved-reactivation guard, not a
    forward-only/terminal whitelist -- every live transition, incl. failed->open executor restart and
    *->superseded / open|failed->declined postmortem purge, passes; only a resolved->open reactivation
    is rejected).
    """


# ---------------------------------------------------------------------------
# Write identity and result dataclasses (minted by runtime, schema contract)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WriteIdentity:
    """The deterministic identity minted ONCE per write op, reused on every OCC retry.

    ulid: monotonic ULID, the history logical PK + idempotency dedup key.
    timestamp: high-precision write timestamp, stable across retries (SCD2 ordering).
    """

    ulid: str
    timestamp: datetime


@dataclass(frozen=True)
class WriteResult:
    """Outcome of a write_scd2 call. occ_retries + commit_ms drive the CloudWatch metrics."""

    ulid: str
    rec_id: str
    occ_retries: int
    commit_ms: float
    created_timestamp: datetime
    last_updated_timestamp: datetime


# ---------------------------------------------------------------------------
# Field-semantics contract -- the single source the gate + derivations + tests read
# ---------------------------------------------------------------------------


def _field_semantics_path() -> Path:
    """Resolve the field-semantics YAML path (env override for Lambda-bundle relocation)."""
    override = os.environ.get(_FIELD_SEMANTICS_ENV)
    return Path(override) if override else _DEFAULT_FIELD_SEMANTICS_PATH


@lru_cache(maxsize=4)
def _load_field_semantics_cached(path_str: str) -> dict[str, Any]:
    return yaml.safe_load(Path(path_str).read_text(encoding="utf-8"))


def load_field_semantics(path: str | Path | None = None) -> dict[str, Any]:
    """Load + cache the field-semantics contract. Pass `path` to override (tests)."""
    resolved = Path(path) if path is not None else _field_semantics_path()
    return _load_field_semantics_cached(str(resolved))


# ---------------------------------------------------------------------------
# Table spec -- the single resolved shape that drives the gate, DDL, MERGE, and reads.
# table=None selects the smoke pair (T2.17 back-compat); a name selects an ops_tables entry (T2.19).
# ---------------------------------------------------------------------------

# Derived SCD2-envelope columns minted by the runtime (never caller-supplied). Physical column order
# is: ulid first, then the input columns (merge_key first), then created/last_updated last.
_DERIVED_LEAD = "ulid"
_DERIVED_TAIL = ("created_timestamp", "last_updated_timestamp")


@dataclass(frozen=True)
class ScdTableSpec:
    """Resolved SCD2 table shape. Drives create/gate/write/read uniformly for smoke + ops_* tables."""

    table: str | None  # None = smoke
    history_table: str
    current_table: str | None  # None for append_only tables (no write-through projection)
    merge_key: str
    fields: dict[str, Any]  # column name -> {role, sql_type, nullable}; the schema-gate contract
    ordered_columns: tuple[tuple[str, str], ...]  # (name, sql_type) in physical (DDL/INSERT) order
    partition_history: str
    partition_current: str
    entity_id_prefix: str | None = None  # canonical id shape <prefix>NNN (None = no canonical keyspace)
    id_keyspace: str = "caller"  # "writer" => file_ops allocates + write_ops advances the counter (Decision 84 I-2)
    write_mode: str = "scd2"  # "scd2" | "append_only"; append_only skips the current write-through projection


def _order_columns(fields: dict[str, Any], merge_key: str) -> tuple[tuple[str, str], ...]:
    """Return ((name, sql_type), ...) in physical order: ulid, merge_key, other inputs, created, updated.

    A stable, deterministic order so the DDL, the MERGE source SELECT, the INSERT VALUES list, and the
    read projection all agree without a separate ordering source.
    """
    inputs = [c for c, s in fields.items() if s.get("role") == "input"]
    other_inputs = [c for c in inputs if c != merge_key]
    ordered = [_DERIVED_LEAD, merge_key, *other_inputs, *_DERIVED_TAIL]
    return tuple((c, fields[c]["sql_type"]) for c in ordered)


def resolve_table_spec(table: str | None = None, semantics: dict[str, Any] | None = None) -> ScdTableSpec:
    """Resolve the SCD2 spec for *table* (None = smoke). Loud-fail on an unknown ops table name."""
    semantics = semantics if semantics is not None else load_field_semantics()
    if table is None:
        partitions = semantics.get("partition_transforms", {})
        return ScdTableSpec(
            table=None,
            history_table=SMOKE_HISTORY_TABLE,
            current_table=SMOKE_CURRENT_TABLE,
            merge_key="rec_id",
            fields=semantics["fields"],
            ordered_columns=_order_columns(semantics["fields"], "rec_id"),
            partition_history=partitions.get("history", "day(created_timestamp)"),
            partition_current=partitions.get("current", "bucket(8, rec_id)"),
        )
    ops_tables = semantics.get("ops_tables", {})
    spec = ops_tables.get(table)
    if spec is None:
        raise SchemaGateError(f"unknown ops table {table!r}: not in field_semantics ops_tables (have {sorted(ops_tables)})")
    merge_key = spec["merge_key"]
    fields = spec["columns"]
    part = spec.get("partition", {})
    write_mode = spec.get("write_mode", "scd2")
    return ScdTableSpec(
        table=table,
        history_table=spec["history_table"],
        current_table=spec.get("current_table") if write_mode == "scd2" else None,
        merge_key=merge_key,
        fields=fields,
        ordered_columns=_order_columns(fields, merge_key),
        partition_history=part.get("history", "day(created_timestamp)"),
        partition_current=part.get("current", f"bucket(8, {merge_key})"),
        entity_id_prefix=spec.get("entity_id_prefix"),
        id_keyspace=spec.get("id_keyspace", "caller"),
        write_mode=write_mode,
    )


def check_append_only_guard(spec: ScdTableSpec, require_exists: bool) -> None:
    """Loud-fail when an update (require_exists=True) targets an append_only table (Decision 70).

    Append-only tables are write-once; require_exists=True implies an intent to update an existing
    record, which is illegal. Record state changes as new events with a distinct merge_key.
    """
    if spec.write_mode == "append_only" and require_exists:
        raise AppendOnlyUpdateError(
            f"table {spec.table!r} is append_only: require_exists=True is illegal "
            "(Decision 70 / write-once lifecycle). Record state changes as new events with a new merge_key."
        )


def ops_table_names(semantics: dict[str, Any] | None = None) -> tuple[str, ...]:
    """Return the configured ops_* table names (live + dormant)."""
    semantics = semantics if semantics is not None else load_field_semantics()
    return tuple(semantics.get("ops_tables", {}).keys())


def _column_ddl(spec: ScdTableSpec) -> str:
    """Compose the CREATE-TABLE column list from the spec (NOT NULL on non-nullable columns)."""
    parts: list[str] = []
    for name, sql_type in spec.ordered_columns:
        nullable = bool(spec.fields[name].get("nullable", True))
        parts.append(f"{name} {sql_type}" + ("" if nullable else " NOT NULL"))
    return ", ".join(parts)


def _build_merge_history_sql(spec: ScdTableSpec) -> str:
    cols = [c for c, _ in spec.ordered_columns]
    select = ", ".join(f"? AS {c}" for c in cols)
    col_list = ", ".join(cols)
    values = ", ".join(f"s.{c}" for c in cols)
    # Explicit INSERT (col_list) so the mapping is by name, not by physical position.
    # This makes MERGE safe across schema migrations that add columns via ALTER TABLE ADD COLUMN
    # (which appends at the physical end regardless of the spec's logical order).
    return (
        f"MERGE INTO {CATALOG_ALIAS}.{spec.history_table} AS t "
        f"USING (SELECT {select}) AS s "
        "ON t.ulid = s.ulid "
        f"WHEN NOT MATCHED THEN INSERT ({col_list}) VALUES ({values})"
    )


def _build_merge_current_sql(spec: ScdTableSpec) -> str:
    cols = [c for c, _ in spec.ordered_columns]
    select = ", ".join(f"? AS {c}" for c in cols)
    col_list = ", ".join(cols)
    values = ", ".join(f"s.{c}" for c in cols)
    # created_timestamp is carried (never re-stamped on update); the merge key is the ON predicate.
    update_cols = [c for c in cols if c not in (spec.merge_key, "created_timestamp")]
    set_clause = ", ".join(f"{c} = s.{c}" for c in update_cols)
    return (
        f"MERGE INTO {CATALOG_ALIAS}.{spec.current_table} AS t "
        f"USING (SELECT {select}) AS s "
        f"ON t.{spec.merge_key} = s.{spec.merge_key} "
        f"WHEN MATCHED THEN UPDATE SET {set_clause} "
        f"WHEN NOT MATCHED THEN INSERT ({col_list}) VALUES ({values})"
    )


def _build_select_existing_created_sql(spec: ScdTableSpec, *, include_status: bool = False) -> str:
    """SELECT the existing row's created_timestamp (+ status, when *include_status*) by merge key.

    `include_status` reuses this SAME existing-row fetch to read the current status for the DAG
    check (write_scd2's require_exists path) -- no second Neon round-trip (Decision 88).
    """
    cols = "created_timestamp, status" if include_status else "created_timestamp"
    return f"SELECT {cols} FROM {CATALOG_ALIAS}.{spec.current_table} WHERE {spec.merge_key} = ?"


def _write_params(spec: ScdTableSpec, record: dict[str, Any], identity: WriteIdentity, created_ts: datetime) -> list[Any]:
    """Bind the ordered-column values for the MERGE source row (derived minted, inputs from record)."""
    params: list[Any] = []
    for name, _ in spec.ordered_columns:
        if name == "ulid":
            params.append(identity.ulid)
        elif name == "created_timestamp":
            params.append(created_ts)
        elif name == "last_updated_timestamp":
            params.append(identity.timestamp)
        else:
            params.append(record.get(name))
    return params


# ---------------------------------------------------------------------------
# Named-read registry -- the pre-established read verbs the reader Lambda serves (Decision 84 I-3).
# Verb SQL is server-side trusted content: callers name a verb and bind params; no caller SQL
# crosses the boundary on this path. `{tbl}` = current projection, `{hist}` = history table.
# ---------------------------------------------------------------------------

NAMED_READS_VERSION = 3


@dataclass(frozen=True)
class NamedRead:
    """One pre-established read verb: fixed SQL over a fixed table with named bind params."""

    verb: str
    table: str
    sql: str
    params: tuple[str, ...] = ()
    description: str = ""
    paginable: bool = False  # True => the caller-supplied `limit` (named_read) may bound this verb's rows


NAMED_READS: dict[str, NamedRead] = {
    nr.verb: nr
    for nr in (
        NamedRead(
            verb="open_recs",
            table="ops_recommendations",
            sql=("SELECT id, title, context, created_timestamp, automatable FROM {tbl} WHERE status = 'open' ORDER BY id"),
            description="Open recommendations with the fields the preflight tally consumes.",
            paginable=True,
        ),
        NamedRead(
            verb="rec_by_id",
            table="ops_recommendations",
            sql="SELECT * FROM {tbl} WHERE id = ?",
            params=("id",),
            description="Single recommendation by id (portal fetch-before-update).",
        ),
        NamedRead(
            verb="recs_by_title_prefix",
            table="ops_recommendations",
            sql="SELECT id, title, status, source FROM {tbl} WHERE title LIKE ? ORDER BY id",
            params=("title_prefix",),
            description="Recommendations whose title starts with the bound prefix (postmortem supersede sweep).",
            paginable=True,
        ),
        NamedRead(
            verb="ci_rca_open",
            table="ops_recommendations",
            sql=(
                "SELECT id, title, priority, created_timestamp, file FROM {tbl} "
                "WHERE source = 'ci_rca' AND status IN ('open', 'in_progress') "
                "ORDER BY created_timestamp DESC, id LIMIT 5"
            ),
            description="Most recent open/in-progress CI-RCA recommendations (preflight hard-block surface).",
        ),
        NamedRead(
            verb="ci_rca_since",
            table="ops_recommendations",
            sql=("SELECT id FROM {tbl} WHERE source = 'ci_rca' AND created_timestamp > CAST(? AS TIMESTAMPTZ)"),
            params=("since_ts",),
            description="CI-RCA recommendations created after the bound timestamp (liveness alert).",
        ),
        NamedRead(
            verb="forward_fix_recursion",
            table="ops_recommendations",
            sql=(
                "SELECT file, COUNT(*) AS cnt FROM {tbl} "
                "WHERE source = 'ci_rca' AND created_timestamp > CAST(? AS TIMESTAMPTZ) "
                "GROUP BY file HAVING COUNT(*) >= 3"
            ),
            params=("since_ts",),
            description="Files targeted by >=3 CI-RCA recommendations since the bound timestamp.",
        ),
        NamedRead(
            verb="budget_bypass_recent",
            table="ops_recommendations",
            sql=(
                "SELECT id, context, created_timestamp FROM {tbl} "
                "WHERE source = 'budget_bypass' "
                "AND created_timestamp > (current_timestamp - INTERVAL 7 DAY) "
                "ORDER BY created_timestamp DESC, id LIMIT 10"
            ),
            description="budget_bypass recommendations filed in the last 7 days (fast-tier drift alert).",
        ),
        NamedRead(
            verb="rec_history",
            table="ops_recommendations",
            sql="SELECT * FROM {hist} WHERE id = ? ORDER BY last_updated_timestamp DESC, ulid DESC",
            params=("id",),
            description="Prior SCD2 history versions of a rec, newest-first (agent-facing history read).",
        ),
        NamedRead(
            verb="count_by_status",
            table="ops_recommendations",
            sql="SELECT status, COUNT(*) AS n FROM {tbl} GROUP BY status ORDER BY status",
            description="Recommendation count per lifecycle status.",
        ),
        NamedRead(
            verb="decision_by_id",
            table="ops_decisions",
            sql="SELECT * FROM {tbl} WHERE id = ?",
            params=("id",),
            description="Single decision by dec-NNN id (portal fetch-before-update).",
        ),
        NamedRead(
            verb="decisions_max_updated",
            table="ops_decisions",
            sql="SELECT max(last_updated_timestamp) AS ts FROM {tbl}",
            description="Latest decision update timestamp (roadmap freshness input).",
        ),
        NamedRead(
            verb="priority_queue_current",
            table="ops_priority_queue",
            sql=(
                "SELECT * FROM {tbl} WHERE queue_run_id = ("
                "SELECT queue_run_id FROM {tbl} ORDER BY last_updated_timestamp DESC LIMIT 1) "
                "ORDER BY rank"
            ),
            description="All entries of the latest curator run (Decision 70 correlated-subquery pattern).",
        ),
    )
}


def _params_schema(params: tuple[str, ...]) -> dict[str, Any]:
    """A minimal JSON-schema-shaped object over *params* (all bind values are strings at this boundary)."""
    return {
        "type": "object",
        "properties": {p: {"type": "string"} for p in params},
        "required": list(params),
    }


def describe_named_reads() -> dict[str, dict[str, Any]]:
    """Per-verb parameter schema for every NAMED_READS entry (agent-facing `describe`, CD.10 / CD.15)."""
    return {
        verb: {
            "table": nr.table,
            "description": nr.description,
            "params": list(nr.params),
            "paginable": nr.paginable,
            "params_schema": _params_schema(nr.params),
        }
        for verb, nr in NAMED_READS.items()
    }


# ---------------------------------------------------------------------------
# Rec status DAG -- resolved-reactivation guard (Decision 103 / Decision 55).
#
# NOT a forward-only/terminal-status whitelist: every LIVE transition passes (failed->open executor
# restart; *->superseded and open/failed->declined postmortem purge; open->{closed,failed,declined,
# superseded}; same-status writes). The ONE thing rejected is a RESOLVED rec (closed/declined/
# superseded) being silently REACTIVATED (-> open). Unrecognised status vocabulary is skipped
# narrowly (Decision 55) -- never silently treated as an illegal transition.
# ---------------------------------------------------------------------------

_ENFORCED_REC_STATUSES = frozenset({"open", "closed", "failed", "declined", "superseded"})
_RESOLVED_REC_STATUSES = frozenset({"closed", "declined", "superseded"})
_ACTIVE_REC_STATUSES = frozenset({"open"})

# table -> {enforced, resolved, active} status vocabulary the DAG is defined over. A table absent
# from this registry has no declared DAG -- check_rec_status_transition is then a permissive no-op.
STATUS_TRANSITIONS: dict[str, dict[str, frozenset[str]]] = {
    "ops_recommendations": {
        "enforced": _ENFORCED_REC_STATUSES,
        "resolved": _RESOLVED_REC_STATUSES,
        "active": _ACTIVE_REC_STATUSES,
    },
}


def check_rec_status_transition(table: str, existing_status: Any, new_status: Any) -> None:
    """Raise StatusTransitionError iff *table* declares a DAG and this is a resolved->active reactivation.

    Permissive-skip (never raises) when: *table* has no declared DAG, either status is outside the
    declared enforced vocabulary, or the transition is not resolved->active (this also covers
    same-status writes, since resolved and active are disjoint).
    """
    dag = STATUS_TRANSITIONS.get(table)
    if dag is None:
        return
    if existing_status not in dag["enforced"] or new_status not in dag["enforced"]:
        return
    if existing_status in dag["resolved"] and new_status in dag["active"]:
        raise StatusTransitionError(
            f"{table}: illegal status transition {existing_status!r} -> {new_status!r} -- a resolved rec "
            "must not be silently reactivated (Decision 103). Record the reopen as a new event/rec instead."
        )


# ---------------------------------------------------------------------------
# Write-verb registry -- the pre-established write verbs the writer Lambda serves (CD.10 / CD.15
# describe surface). Mirrors NAMED_READS' shape for the write side; params_schema is descriptive
# metadata only -- schema_gate (per-table field_semantics) remains the enforced write contract.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WriteVerb:
    """One pre-established write verb: a description + a descriptive params_schema."""

    verb: str
    description: str
    params_schema: dict[str, Any]


VERB_REGISTRY: dict[str, WriteVerb] = {
    wv.verb: wv
    for wv in (
        WriteVerb(
            verb="write_ops",
            description=(
                "Raw SCD2 upsert into an ops_* table (history MERGE-on-ULID append + current "
                "write-through, schema-gated, bounded-OCC-retried). No id allocation, no require_exists."
            ),
            params_schema={
                "type": "object",
                "properties": {"table": {"type": "string"}, "record": {"type": "object"}},
                "required": ["table", "record"],
            },
        ),
        WriteVerb(
            verb="update_ops",
            description=(
                "Update an existing ops_* record (record is the FULL merged row). Loud-fails "
                "(ReferentialError) if the merge key is absent, or (StatusTransitionError) if the "
                "update would silently reactivate a resolved rec."
            ),
            params_schema={
                "type": "object",
                "properties": {"table": {"type": "string"}, "record": {"type": "object"}},
                "required": ["table", "record"],
            },
        ),
        WriteVerb(
            verb="file_ops",
            description=(
                "Create one ops_* record, allocating its merge key inside the write transaction "
                "(writer-owned keyspace, Decision 84 I-2). idempotency_ulid replays to the "
                "originally-allocated id on a response-lost retry."
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "record": {"type": "object"},
                    "idempotency_ulid": {"type": "string"},
                },
                "required": ["table", "record"],
            },
        ),
        WriteVerb(
            verb="create_ops_tables",
            description=(
                "Admin provisioning verb: create (optionally force-recreate) an ops_* table pair with "
                "partition transforms; bootstraps/repairs the writer-owned entity-id counter."
            ),
            params_schema={
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "force_recreate_tables": {"type": "boolean"},
                    "confirm_force_recreate": {"type": "string"},
                },
                "required": ["table"],
            },
        ),
    )
}


def describe_write_verbs() -> dict[str, dict[str, Any]]:
    """Per-verb description + params_schema for every VERB_REGISTRY entry (agent-facing `describe`)."""
    return {verb: {"description": wv.description, "params_schema": wv.params_schema} for verb, wv in VERB_REGISTRY.items()}


# ---------------------------------------------------------------------------
# Schema gate -- loud-fail on unknown / derived / missing / mis-typed input fields
# ---------------------------------------------------------------------------


def schema_gate(record: dict[str, Any], semantics: dict[str, Any] | None = None, *, table: str | None = None) -> None:
    """Validate a caller-supplied write record against the contract. Loud-fail (Decision 55).

    `table=None` validates against the smoke `fields` map (T2.17 back-compat); a table name validates
    against that ops_tables entry's `columns` map (T2.19).

    Rejects (raises SchemaGateError):
      - any key not present in the contract (unknown field),
      - any key whose role is `derived` (the caller must not supply derived values),
      - any required (`nullable: false`) input field that is missing, null, or empty,
      - any input field whose value is not the contract's declared SQL type.
    """
    semantics = semantics if semantics is not None else load_field_semantics()
    fields: dict[str, Any] = semantics["fields"] if table is None else resolve_table_spec(table, semantics).fields

    for key in record:
        spec = fields.get(key)
        if spec is None:
            raise SchemaGateError(f"unknown field {key!r}: not in the field-semantics contract")
        if spec["role"] == "derived":
            raise SchemaGateError(f"field {key!r} is derived: the runtime mints it; the caller must not supply it")

    for name, spec in fields.items():
        if spec["role"] != "input":
            continue
        nullable = bool(spec.get("nullable", True))
        present = name in record
        value = record.get(name)
        if not nullable and (not present or value is None):
            raise SchemaGateError(f"required input field {name!r} is missing or null")
        if present and value is not None:
            expected = _PY_TYPE_FOR_SQL.get(spec["sql_type"])
            if expected is not None and not isinstance(value, expected):
                raise SchemaGateError(f"field {name!r} expected {expected.__name__}, got {type(value).__name__}")
            if expected is str and not nullable and value == "":
                raise SchemaGateError(f"required input field {name!r} is empty")
