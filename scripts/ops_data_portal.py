# complexity-waiver: decision-43
"""Unified write gateway for recommendation and decision operations.

All writes to ops_recommendations and ops_decisions MUST go through this
module. Direct appends to logs/.recommendations-log.jsonl are forbidden and
caught by validate.py.

Offline mode (DynamoDB unreachable): recommendations are queued to
logs/.ops-outbox/ops_recommendations_pending/ and drained by drain_pending()
on the next session-close postflight run.

Usage:
    from scripts.ops_data_portal import file_rec, update_rec
    rec_id = file_rec({"title": "...", "file": "...", "status": "open", ...})
    update_rec("rec-522", {"status": "closed", "execution_result": "success"})

CLI:
    python -m scripts.ops_data_portal --file-rec --title "..." --file "..." ...
    python -m scripts.ops_data_portal --update-rec rec-522 --status closed
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import yaml
from pydantic import ValidationError

from scripts.aws_profile import resolve_aws_profile
from scripts.executor.acceptance_lint import lint_acceptance_command
from scripts.executor.jsonl_store import _VALID_STATUSES, DECISIONS_JSONL, RECS_JSONL, Decision, Recommendation
from scripts.executor.rec_write_guidance import validate_source
from scripts.ops_writer import OpsWriter
from scripts.sync_recommendations import next_id as _next_id

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PENDING_OUTBOX = _REPO_ROOT / "logs" / ".ops-outbox" / "ops_recommendations_pending"
_DECISIONS_PENDING_OUTBOX = _REPO_ROOT / "logs" / ".ops-outbox" / "ops_decisions_pending"
_SSO_PROFILE = "agent_platform"

_ATHENA_DATABASE = "agent_platform"
_ATHENA_WORKGROUP = "agent-platform-production"
_AWS_REGION = "eu-west-2"

_EFFORT_SCALE: dict[str, float] = {"XS": 0.1, "S": 0.5, "M": 1.0, "L": 3.0, "XL": 5.0}
_COVERAGE_XML = _REPO_ROOT / "coverage.xml"
_CAPABILITIES_YAML = _REPO_ROOT / "config" / "agent" / "executor" / "capabilities.yaml"
_OPS_YAML_PATH = _REPO_ROOT / "config" / "agent" / "data_quality" / "ops.yaml"
_capabilities_cache: Optional[dict] = None
_write_time_validators_cache: dict[str, list] = {}

# --- Storage-backend transport flag (T2.19 / Decision 81) -----------------------------------------
# The Single-Portal caller surface (file_rec/update_rec/file_decision/update_decision/sync) is
# unchanged; ONLY the transport underneath swaps. `iceberg` = OpsWriter()/Athena (legacy, rollback
# target); `ducklake` = the closed writer/reader Function-URL boundary.
# Default is `ducklake` (T2.19 cutover signed off 2026-06-09); set OPS_STORAGE_BACKEND=iceberg to roll back.
_OPS_STORAGE_BACKEND_ENV = "OPS_STORAGE_BACKEND"
_DEFAULT_OPS_STORAGE_BACKEND = "ducklake"
_DUCKLAKE_WRITER_URL_ENV = "DUCKLAKE_WRITER_URL"
_DUCKLAKE_WRITER_FUNCTION_NAME = "agent-platform-ducklake-writer"
_AWS_LAMBDA_SERVICE = "lambda"

# Portal table -> DuckLake ops_* table (the writer/reader select schema by this name).
_PORTAL_TABLE_NAMES = ("ops_recommendations", "ops_decisions")


def _ops_backend() -> str:
    """Return the active storage backend ('iceberg' | 'ducklake'); default iceberg until cutover."""
    return (os.environ.get(_OPS_STORAGE_BACKEND_ENV) or _DEFAULT_OPS_STORAGE_BACKEND).strip().lower()


def _resolve_function_url_via_api(function_name: str, profile: Optional[str] = None) -> Optional[str]:
    """Resolve a Lambda Function URL via lambda:GetFunctionUrlConfig. None on any failure.

    Last-resort fallback for environments with neither the DUCKLAKE_*_URL env nor a terraform-init'd
    checkout -- principally the CI runner (T2.19 cutover), where the github_ci OIDC role carries the
    GetFunctionUrlConfig grant.
    """
    try:
        import boto3  # noqa: PLC0415

        client = boto3.Session(profile_name=profile).client("lambda", region_name="eu-west-2")
        return client.get_function_url_config(FunctionName=function_name).get("FunctionUrl")
    except Exception as exc:  # noqa: BLE001 -- best-effort fallback; caller raises if this returns None
        logger.warning("[PORTAL] GetFunctionUrlConfig fallback failed for %s: %s", function_name, exc)
        return None


def _resolve_writer_url(profile: Optional[str] = None) -> str:
    """Resolve the ducklake_writer Function URL: env, then terraform output, then the AWS API.

    The AWS-API fallback (lambda:GetFunctionUrlConfig) covers the CI runner case (no env, no
    terraform-init'd checkout); the github_ci OIDC role carries the grant. Loud-fail if all fail.
    """
    url = os.environ.get(_DUCKLAKE_WRITER_URL_ENV)
    if url:
        return url.rstrip("/")
    try:
        proc = subprocess.run(
            ["terraform", "-chdir=terraform/personal", "output", "-raw", "ducklake_writer_function_url"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip().rstrip("/")
    except FileNotFoundError:
        pass
    api_url = _resolve_function_url_via_api(_DUCKLAKE_WRITER_FUNCTION_NAME, profile=profile)
    if api_url:
        return api_url.rstrip("/")
    raise RuntimeError(
        f"{_DUCKLAKE_WRITER_URL_ENV} not set, terraform output 'ducklake_writer_function_url' unavailable, and "
        "lambda:GetFunctionUrlConfig fallback failed -- cannot reach the DuckLake writer (OPS_STORAGE_BACKEND=ducklake)."
    )


def _project_ops_record(table: str, record: dict) -> dict:
    """Project a validated record onto the table's INPUT columns for the writer schema gate.

    Drops derived fields (ulid/created_timestamp/last_updated_timestamp -- the runtime mints them)
    and any non-schema keys (e.g. the Decision-56-deprecated `date`). Keeps the merge key + business
    inputs. Mirrors the writer's schema gate so the request is accepted on the first try.
    """
    from src.common.ducklake_runtime import resolve_table_spec  # noqa: PLC0415

    spec = resolve_table_spec(table)
    inputs = {name for name, fspec in spec.fields.items() if fspec.get("role") == "input"}
    return {k: v for k, v in record.items() if k in inputs}


def _ducklake_write(table: str, record: dict, *, action: str, profile: Optional[str] = None) -> dict:
    """Invoke the ducklake_writer Function URL (SigV4) for a production ops write. Loud-fail on error.

    action is 'write_ops' (file) or 'update_ops' (update; the writer enforces the in-tx referential
    existence check). Maps the writer's loud-fail status codes back to portal exceptions.
    """
    import boto3  # noqa: PLC0415
    import requests  # noqa: PLC0415
    from botocore.auth import SigV4Auth  # noqa: PLC0415
    from botocore.awsrequest import AWSRequest  # noqa: PLC0415

    url = _resolve_writer_url(profile=profile)
    payload = {"action": action, "table": table, "record": _project_ops_record(table, record)}
    body = json.dumps(payload)
    headers = {"Content-Type": "application/json"}
    session = boto3.Session(profile_name=resolve_aws_profile(profile, default=_SSO_PROFILE))
    creds = session.get_credentials().get_frozen_credentials()
    aws_req = AWSRequest(method="POST", url=url, data=body, headers=dict(headers))
    SigV4Auth(creds, _AWS_LAMBDA_SERVICE, _AWS_REGION).add_auth(aws_req)
    resp = requests.post(url, data=body, headers=dict(aws_req.headers), timeout=180)
    if resp.status_code == 200:
        return resp.json()
    detail = resp.text[:400]
    if resp.status_code == 409:
        raise RuntimeError(f"ducklake_writer referential failure ({action} {table}): {detail}")
    if resp.status_code == 422:
        raise ValueError(f"ducklake_writer schema-gate rejection ({action} {table}): {detail}")
    raise RuntimeError(f"ducklake_writer {action} {table} failed (HTTP {resp.status_code}): {detail}")


def _compute_risk_score(file_path: str, effort: str) -> float:
    """Return raw R = (C * S) / M for the given file and effort label.

    C = max cyclomatic complexity (1.0 fallback), S = effort scale, M = coverage + 0.1 baseline.
    """
    c = 1.0
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "radon", "cc", "-s", file_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            nums = [int(m) for m in re.findall(r"\((\d+)\)", proc.stdout)]
            if nums:
                c = float(max(nums))
    except Exception:  # noqa: BLE001
        pass

    s = _EFFORT_SCALE.get(effort, 1.0)

    m = 0.1
    try:
        tree = ET.parse(str(_COVERAGE_XML))
        norm_target = file_path.replace("\\", "/")
        for cls in tree.getroot().iter("class"):
            name = (cls.get("filename") or "").replace("\\", "/")
            if name.endswith(norm_target) or norm_target.endswith(name):
                m = float(cls.get("line-rate", 0.0)) + 0.1
                break
    except Exception:  # noqa: BLE001
        pass

    return (c * s) / m


def compute_risk(file_path: str, effort: str) -> str:
    """Derive risk tier from cyclomatic complexity, effort scale, and test coverage.

    R = (C * S) / M where:
      C = max cyclomatic complexity of target file (1.0 if file missing or radon returns empty)
      S = effort scale factor from _EFFORT_SCALE (1.0 fallback for unknown labels)
      M = line-rate from coverage.xml for the file + 0.1 baseline (0.1 if absent)
    Thresholds: R <= 5 -> "low", R <= 15 -> "medium", R > 15 -> "high"
    """
    r = _compute_risk_score(file_path, effort)
    if r <= 5:
        return "low"
    if r <= 15:
        return "medium"
    return "high"


def load_capabilities() -> dict:
    """Load and cache executor_capabilities.yaml. Returns empty dict on read failure."""
    global _capabilities_cache
    if _capabilities_cache is None:
        try:
            _capabilities_cache = yaml.safe_load(_CAPABILITIES_YAML.read_text(encoding="utf-8")) or {}
        except (FileNotFoundError, OSError, yaml.YAMLError):
            _capabilities_cache = {}
    return _capabilities_cache


def compute_automatable(file_path: str, effort: str) -> bool:
    """Return True iff this recommendation is within the executor's current capability boundary.

    Formula: NOT in boundary AND R <= maturity_ceiling.
    Offline fallback: returns True when file_path is empty (boundary unknown).
    """
    if not file_path:
        return True
    caps = load_capabilities()
    boundary_patterns: list[str] = caps.get("boundary_patterns", [])
    ceiling: float = float(caps.get("maturity_ceiling", 1.0))
    if any(pat in file_path for pat in boundary_patterns):
        return False
    r = _compute_risk_score(file_path, effort)
    return r <= ceiling


def _validate_file_path(path: str) -> None:
    """Raise ValueError if path is absolute or uses backslash separators."""
    if not path:
        return
    if path.startswith("/"):
        raise ValueError(f"file must be a repo-relative path with forward slashes (got absolute Unix path): {path!r}")
    if re.match(r"[A-Za-z]:[/\\]", path):
        raise ValueError(f"file must be a repo-relative path with forward slashes (got absolute Windows path): {path!r}")
    if "\\" in path:
        raise ValueError(f"file must use forward slashes as path separators (got backslash): {path!r}")


def _validate_context_length(text: str) -> None:
    """Raise ValueError if stripped context is shorter than 80 characters."""
    if not text:
        return
    stripped_len = len(text.strip())
    if stripped_len < 80:
        raise ValueError(
            f"context must be at least 80 stripped characters (got {stripped_len}). "
            "Answer 'what problem does this solve and why now?'"
        )


def _check_not_null(v: object, col: str) -> None:
    if v is None or not str(v).strip():
        raise ValueError(f"required field '{col}' must be non-empty")


def _derive_computed_fields(fields: dict) -> None:
    """Derive and set risk, automatable, and created_timestamp in-place.

    Called from both file_rec() and drain_pending() to ensure a single shared
    derivation path -- prevents the dual-maintenance drift that produced rec-001
    (automatable=NULL) and rec-742 (created_timestamp midnight fallback).
    """
    if fields.get("file") and fields.get("effort"):
        derived_risk = compute_risk(fields["file"], fields["effort"])
        if fields.get("risk") and fields["risk"] != derived_risk:
            logger.warning(
                "[PORTAL] caller risk %s overridden by formula %s for %s",
                fields["risk"],
                derived_risk,
                fields.get("title", ""),
            )
        fields["risk"] = derived_risk

        derived_automatable = compute_automatable(fields["file"], fields["effort"])
        if "automatable" in fields and fields["automatable"] != derived_automatable:
            logger.warning(
                "[PORTAL] caller automatable %s overridden by formula %s for %s",
                fields["automatable"],
                derived_automatable,
                fields.get("title", ""),
            )
        fields["automatable"] = derived_automatable

    fields.setdefault("created_timestamp", datetime.now(timezone.utc).isoformat())


def _load_write_time_validators(table: str) -> list[tuple[str, Callable]]:
    """Load write-time validators from ops.yaml for the given table.

    Returns a list of (column_name, validator_fn) tuples for every test entry
    with write_time: true. Result is cached to avoid repeated YAML reads.
    """
    if table in _write_time_validators_cache:
        return _write_time_validators_cache[table]

    try:
        data = yaml.safe_load(_OPS_YAML_PATH.read_text(encoding="utf-8")) or {}
    except (FileNotFoundError, OSError, yaml.YAMLError):
        _write_time_validators_cache[table] = []
        return []

    columns = data.get("tables", {}).get(table, {}).get("columns", {})
    validators: list[tuple[str, Callable]] = []

    for col_name, col_def in columns.items():
        if not isinstance(col_def, dict):
            continue
        for test_entry in col_def.get("tests", []):
            if not isinstance(test_entry, dict):
                continue
            for test_name, params in test_entry.items():
                if not isinstance(params, dict) or not params.get("write_time"):
                    continue
                if test_name == "not_null":
                    validators.append((col_name, _check_not_null))
                elif test_name == "accepted_values":
                    allowed = list(params.get("values", []))

                    def _make_accepted(values: list, column: str) -> Callable:
                        def _check(v: object, col: str) -> None:
                            if v is not None and str(v).strip() and str(v) not in values:
                                raise ValueError(f"{col} must be one of {values!r}, got {str(v)!r}")

                        return _check

                    validators.append((col_name, _make_accepted(allowed, col_name)))
                elif test_name == "path_syntax":
                    validators.append((col_name, lambda v, col: _validate_file_path(str(v) if v else "")))
                elif test_name == "acceptance_lint":

                    def _check_acceptance(v: object, col: str) -> None:
                        ok, msg = lint_acceptance_command(str(v) if v else "")
                        if not ok:
                            raise ValueError(msg)

                    validators.append((col_name, _check_acceptance))
                elif test_name == "expression" and isinstance(params.get("python"), str):
                    validators.append((col_name, lambda v, col: _validate_context_length(str(v) if v else "")))

    _write_time_validators_cache[table] = validators
    return validators


def file_rec(
    fields: dict,
    profile: Optional[str] = None,
    _migration_int_id: Optional[int] = None,
    _skip_sync: bool = False,
    _migration_mode: bool = False,
) -> str:
    """Allocate a new recommendation ID and stage the record to OpsWriter.

    On success returns the allocated ID (e.g. 'rec-522').
    If DynamoDB is unreachable (RuntimeError), the record is queued to the
    pending outbox and 'pending-<uuid>' is returned. Validation is deferred
    until drain_pending() allocates a real ID.

    Args:
        fields: Rec fields (MUST include at minimum: title, file, status,
                source, effort, priority, context, acceptance, risk).
        profile: Optional AWS profile override (uses AWS_PROFILE env var by default).
        _migration_int_id: PRIVATE. Used only by the Phase C migration script to
            bypass the DynamoDB allocator and preserve historical integer IDs.
            When set, the id is formed as f"rec-{n:03d}" (same zero-padding as
            next_id) so dependency / priority-queue FKs to padded ids still match.
            Threaded through the offline outbox + drain_pending so a DynamoDB blip
            cannot silently renumber a migrated rec. Must not be used elsewhere.
        _skip_sync: PRIVATE. When True, suppress the per-row _sync_table() flush so
            a bulk import can call sync() exactly once at the end. Migration-only.
        _migration_mode: PRIVATE. When True, bypass the write-time CONTENT-quality
            validation surface (the three explicit calls _validate_file_path /
            _validate_context_length / lint_acceptance_command AND the YAML-loaded
            _load_write_time_validators loop) so historical rows that predate later
            content-rule tightening still import. validate_source and the
            Recommendation schema (model_validate) remain enforced. Migration-only.

    Returns:
        Allocated ID string ('rec-NNN') or 'pending-<uuid>' when offline.

    Raises:
        ValueError: If any required non-empty field is absent or blank.
        ValidationError: If fields fail Recommendation schema validation (online only).
    """
    fields = dict(fields)  # defensive copy -- do not mutate caller's dict

    if fields.get("source") == "ci_rca" and not (fields.get("file") or "").strip():
        raise ValueError(
            "source='ci_rca' requires non-empty source_file (the file implicated by the failure diagnosis); "
            "see .claude/agents/scheduled/ci-rca.md"
        )

    _derive_computed_fields(fields)

    if not _migration_mode:
        for _col, _validator in _load_write_time_validators("ops_recommendations"):
            _validator(fields.get(_col), _col)

    validate_source(fields["source"])

    if not _migration_mode:
        _validate_file_path(fields["file"])
        _validate_context_length(fields["context"])
        lint_ok, lint_msg = lint_acceptance_command(fields["acceptance"])
        if not lint_ok:
            raise ValueError(lint_msg)

    try:
        if _migration_int_id is not None:
            rec_id = f"rec-{_migration_int_id:03d}"
        else:
            rec_id = _next_id("recommendations", profile=profile)
    except Exception as exc:
        # Reached only when _next_id raises -- i.e. NON-migration writes (migration rows set
        # _migration_int_id, which bypasses _next_id, so they never reach here). Migration id
        # preservation under S3 flakiness is handled by OpsWriter's own outbox, which stages the
        # record with its already-resolved id. drain_pending still honours a migration marker if
        # one is present in a payload, but file_rec does not produce such a payload.
        logger.warning("[PORTAL] DynamoDB unreachable or credentials missing, queuing rec to pending outbox: %s", exc)
        pending_id = str(uuid.uuid4())
        _PENDING_OUTBOX.mkdir(parents=True, exist_ok=True)
        pending_file = _PENDING_OUTBOX / f"{pending_id}.json"
        pending_fields = dict(fields)
        pending_fields.pop("id", None)  # no ID yet
        pending_file.write_text(json.dumps(pending_fields), encoding="utf-8")
        return f"pending-{pending_id}"

    merged = dict(fields)
    merged["id"] = str(rec_id)
    merged.setdefault("date", date.today().isoformat())

    Recommendation.model_validate(merged)  # raises ValidationError on schema failure

    if _ops_backend() == "ducklake":
        _ducklake_write("ops_recommendations", merged, action="write_ops", profile=profile)
    else:
        OpsWriter().write("ops_recommendations", merged)
    _append_to_local_jsonl(RECS_JSONL, merged)
    logger.info("[PORTAL] Filed %s: %s", rec_id, merged.get("title", ""))
    if not _skip_sync:
        _sync_table("ops_recommendations")
    return str(rec_id)


def _fetch_rec_from_athena(rec_id: str, profile: Optional[str] = None) -> Optional[dict]:
    """Fetch a single ops_recommendations record by id from the warehouse.

    Reads the current-state snapshot via DuckDBIcebergReader with predicate
    pushdown (row_filter="id = '<rec_id>'"), falling back to Athena on reader
    failure.

    Decision 69: raises RuntimeError if the warehouse is unreachable. Never
    falls back to the local JSONL cache.

    Returns the record dict (coerced and sanitised) or None if not found.
    """
    if not re.fullmatch(r"rec-\d+", rec_id):
        raise ValueError(f"_fetch_rec_from_athena: invalid rec_id: {rec_id!r}")

    from scripts.sync_ops import _coerce_ops_rec_row  # noqa: PLC0415

    # -- DuckLake closed-boundary path (no Athena fallback -- OQ.7) --
    if _ops_backend() == "ducklake":
        from src.common.iceberg_reader import make_reader  # noqa: PLC0415

        rows = make_reader().current_state("ops_recommendations", row_filter=f"id = '{rec_id}'")
        if not rows:
            return None
        coerced = _coerce_ops_rec_row(dict(rows[0]))
        return _sanitize_athena_record(coerced) if coerced is not None else None

    # -- DuckDB-on-Iceberg reader path (rollback backend; Athena fallback retained until cutover) --
    try:
        from src.common.iceberg_reader import DuckDBIcebergReader  # noqa: PLC0415

        reader = DuckDBIcebergReader()
        rows = reader.current_state(
            "ops_recommendations",
            row_filter=f"id = '{rec_id}'",
        )
        if rows:
            coerced = _coerce_ops_rec_row(dict(rows[0]))
            if coerced is None:
                return None
            return _sanitize_athena_record(coerced)
        return None
    except Exception as reader_exc:  # noqa: BLE001
        logger.warning(
            "ops_data_portal._fetch_rec_from_athena: reader failed for %s, using Athena fallback: %s",
            rec_id,
            reader_exc,
        )

    # -- Athena fallback (Decision 69: must raise on unreachable; never return cache) --
    import time  # noqa: PLC0415

    import boto3 as _boto3  # noqa: PLC0415

    effective_profile = resolve_aws_profile(profile, default=_SSO_PROFILE)
    try:
        session = _boto3.Session(profile_name=effective_profile)
        athena = session.client("athena", region_name=_AWS_REGION)
        eid = athena.start_query_execution(
            QueryString=f"SELECT * FROM {_ATHENA_DATABASE}.ops_recommendations_current WHERE id = '{rec_id}' LIMIT 1",
            WorkGroup=_ATHENA_WORKGROUP,
        )["QueryExecutionId"]
    except Exception as exc:
        raise RuntimeError(f"ops_data_portal._fetch_rec_from_athena: warehouse unreachable: {exc}") from exc

    deadline = time.time() + 60
    state = "RUNNING"
    status: dict = {}
    while time.time() < deadline:
        resp = athena.get_query_execution(QueryExecutionId=eid)
        status = resp["QueryExecution"]["Status"]
        state = status["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(2)
    else:
        raise RuntimeError(f"ops_data_portal._fetch_rec_from_athena: query timed out for {rec_id}")

    if state != "SUCCEEDED":
        raise RuntimeError(
            f"ops_data_portal._fetch_rec_from_athena: query {state} for {rec_id}: {status.get('StateChangeReason', 'unknown')}"
        )

    paginator = athena.get_paginator("get_query_results")
    header: list[str] = []
    for page in paginator.paginate(QueryExecutionId=eid):
        for i, row in enumerate(page.get("ResultSet", {}).get("Rows", [])):
            data = [col.get("VarCharValue", "") for col in row.get("Data", [])]
            if i == 0 and not header:
                header = data
                continue
            if not header:
                continue
            rec = dict(zip(header, data))
            rec.pop("row_num", None)
            rec.pop("_rn", None)
            coerced = _coerce_ops_rec_row(rec)
            if coerced is None:
                return None
            return _sanitize_athena_record(coerced)
    return None


def _sync_table(table: str) -> None:
    """Refresh the local read-cache for one ops table from the active backend.

    DuckLake: the atomic catalog commit means there is no compaction/view-refresh step (Decision 81
    cl.4) -- the write already landed in `current`, so a cache-pull from the DuckLake reader suffices.
    Iceberg (rollback): compact + refresh the view + pull (legacy). Raises on infrastructure failure.
    """
    from scripts.sync_ops import _pull_single_table  # noqa: PLC0415

    # Only ops_recommendations follows the DuckLake backend this slice; decisions + other tables are
    # DEFERRED and always rebuild from Iceberg/Athena (compact + refresh + pull).
    if table == "ops_recommendations" and _ops_backend() == "ducklake":
        _pull_single_table(table)
        return

    OpsWriter().compact(table)
    OpsWriter()._refresh_view(table)
    _pull_single_table(table)


def _sanitize_athena_record(record: dict) -> dict:
    """Replace empty strings with None for fields that Athena serialises as '' for NULL."""
    result = dict(record)
    for key, value in result.items():
        if value == "":
            result[key] = None
    return result


def update_rec(rec_id: str, updates: dict, profile: Optional[str] = None) -> bool:
    """Merge update fields into an existing recommendation and stage via OpsWriter.

    Reads the current record from Athena ops_recommendations_current (requires SSO
    connectivity). Raises RuntimeError if Athena is unreachable. Merges updates,
    validates the merged record, stages to OpsWriter (S3), writes through to local
    JSONL, then triggers _sync_table to compact and refresh the view.

    Args:
        rec_id: Recommendation ID to update (e.g. 'rec-042').
        updates: Fields to merge into the existing record.
        profile: Optional AWS profile override.

    Returns:
        True on success.

    Raises:
        ValueError: If 'status' in updates is not a valid status value.
        ValidationError: If the merged record fails schema validation.
        RuntimeError: If Athena is unreachable for the read step or compaction fails.
    """
    if "status" in updates and updates["status"] not in _VALID_STATUSES:
        raise ValueError(f"Invalid status '{updates['status']}'. Must be one of: {', '.join(sorted(_VALID_STATUSES))}")

    # Referential existence (CD.33 cl.8 / D-5): an absent rec loud-fails. This replaces the prior
    # permissive `existing or {}` upsert-on-absent, which silently created a partial record.
    existing = _fetch_rec_from_athena(rec_id, profile=profile)
    if existing is None:
        raise RuntimeError(
            f"update_rec: {rec_id} does not exist in the current projection -- an absent rec cannot be "
            "updated (referential, CD.33 cl.8 / D-5). File it first via file_rec."
        )
    merged = {**existing, **updates}
    merged["id"] = rec_id  # always preserve the ID

    Recommendation.model_validate(merged)  # raises on failure

    if _ops_backend() == "ducklake":
        _ducklake_write("ops_recommendations", merged, action="update_ops", profile=profile)
    else:
        OpsWriter().write("ops_recommendations", merged)
    _append_to_local_jsonl(RECS_JSONL, merged)
    logger.info("[PORTAL] Updated %s: %s", rec_id, list(updates.keys()))
    _sync_table("ops_recommendations")
    return True


def file_decision(
    fields: dict,
    profile: Optional[str] = None,
    _migration_int_id: Optional[int] = None,
    _skip_sync: bool = False,
) -> str:
    """Allocate a new decision ID and stage the record to OpsWriter.

    Args:
        fields: Decision fields (title, status at minimum).
        profile: Optional AWS profile override.
        _migration_int_id: PRIVATE. Used only by the Phase C migration script to
            bypass the DynamoDB allocator and preserve historical integer IDs.
            Must not be used by any other caller.
        _skip_sync: PRIVATE. When True, suppress the per-row _sync_table() flush so
            a bulk import can call sync() exactly once at the end. Migration-only.

    Returns:
        Allocated decision ID string (e.g. 'dec-073'), or 'pending-<uuid>' when
        DynamoDB is unreachable and the record is queued to the outbox.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    merged = dict(fields)

    try:
        if _migration_int_id is not None:
            n = _migration_int_id
        else:
            n = int(_next_id("decisions", profile=profile))  # type: ignore[arg-type]

        dec_id = f"dec-{n:03d}"
        merged["id"] = dec_id
        merged["decision_id"] = n
        merged.setdefault("created_timestamp", now_iso)
        merged["last_updated_timestamp"] = now_iso

        for _col, _validator in _load_write_time_validators("ops_decisions"):
            _validator(merged.get(_col), _col)

        Decision.model_validate(merged)

        # Decisions are DEFERRED from the recs-first DuckLake cutover (their source of truth is
        # DECISIONS.md, so they rebuild rather than migrate). They STAY on the Iceberg/OpsWriter path
        # regardless of OPS_STORAGE_BACKEND until their own migration.
        OpsWriter().write("ops_decisions", merged)
        _append_to_local_jsonl(DECISIONS_JSONL, merged)
        logger.info("[PORTAL] Filed decision %s: %s", dec_id, merged.get("title", ""))
        if not _skip_sync:
            _sync_table("ops_decisions")
        return dec_id

    except RuntimeError as exc:
        logger.warning("[PORTAL] DynamoDB unreachable for decision, queuing to outbox: %s", exc)
        pending_id = str(uuid.uuid4())
        _DECISIONS_PENDING_OUTBOX.mkdir(parents=True, exist_ok=True)
        payload = dict(fields)
        if _migration_int_id is not None:
            payload["_migration_int_id"] = _migration_int_id
        (_DECISIONS_PENDING_OUTBOX / f"{pending_id}.json").write_text(json.dumps(payload), encoding="utf-8")
        return f"pending-{pending_id}"


def _fetch_decision_from_athena(decision_id: str, profile: Optional[str] = None) -> Optional[dict]:
    """Fetch a single ops_decisions record by id from the warehouse.

    Reads the current-state snapshot via DuckDBIcebergReader with predicate
    pushdown (row_filter="id = '<decision_id>'"), falling back to Athena on
    reader failure.

    Decision 69: raises RuntimeError if the warehouse is unreachable. Never
    falls back to the local JSONL cache.

    Returns the record dict or None if not found.
    """
    from scripts.sync_ops import _coerce_ops_decisions_row  # noqa: PLC0415

    if not re.fullmatch(r"dec-\d+", decision_id):
        raise ValueError(f"_fetch_decision_from_athena: invalid decision_id: {decision_id!r}")

    # Decisions are DEFERRED from the DuckLake cutover -- they read from Iceberg/Athena regardless of
    # OPS_STORAGE_BACKEND (no DuckLake closed-boundary path for decisions this slice).
    # -- DuckDB-on-Iceberg reader path (Athena fallback retained) --
    try:
        from src.common.iceberg_reader import DuckDBIcebergReader  # noqa: PLC0415

        reader = DuckDBIcebergReader()
        rows = reader.current_state(
            "ops_decisions",
            row_filter=f"id = '{decision_id}'",
        )
        if rows:
            rec = dict(rows[0])
            rec.pop("row_num", None)
            return _sanitize_athena_record(_coerce_ops_decisions_row(rec))
        return None
    except Exception as reader_exc:  # noqa: BLE001
        logger.warning(
            "ops_data_portal._fetch_decision_from_athena: reader failed for %s, using Athena fallback: %s",
            decision_id,
            reader_exc,
        )

    # -- Athena fallback (Decision 69: must raise on unreachable; never return cache) --
    import time  # noqa: PLC0415

    import boto3 as _boto3  # noqa: PLC0415

    effective_profile = resolve_aws_profile(profile, default=_SSO_PROFILE)
    try:
        session = _boto3.Session(profile_name=effective_profile)
        athena = session.client("athena", region_name=_AWS_REGION)
        eid = athena.start_query_execution(
            QueryString=(f"SELECT * FROM {_ATHENA_DATABASE}.ops_decisions_current WHERE id = '{decision_id}' LIMIT 1"),
            WorkGroup=_ATHENA_WORKGROUP,
        )["QueryExecutionId"]
    except Exception as exc:
        raise RuntimeError(f"ops_data_portal._fetch_decision_from_athena: warehouse unreachable: {exc}") from exc

    deadline = time.time() + 60
    state = "RUNNING"
    status: dict = {}
    while time.time() < deadline:
        resp = athena.get_query_execution(QueryExecutionId=eid)
        status = resp["QueryExecution"]["Status"]
        state = status["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(2)
    else:
        raise RuntimeError(f"ops_data_portal._fetch_decision_from_athena: query timed out for {decision_id}")

    if state != "SUCCEEDED":
        raise RuntimeError(
            f"ops_data_portal._fetch_decision_from_athena: query {state} for {decision_id}: "
            f"{status.get('StateChangeReason', 'unknown')}"
        )

    paginator = athena.get_paginator("get_query_results")
    header: list[str] = []
    for page in paginator.paginate(QueryExecutionId=eid):
        for i, row in enumerate(page.get("ResultSet", {}).get("Rows", [])):
            data = [col.get("VarCharValue", "") for col in row.get("Data", [])]
            if i == 0 and not header:
                header = data
                continue
            if not header:
                continue
            rec = dict(zip(header, data))
            rec.pop("row_num", None)
            return _sanitize_athena_record(_coerce_ops_decisions_row(rec))
    return None


def update_decision(decision_id: str, updates: dict, profile: Optional[str] = None) -> bool:
    """Merge update fields into an existing decision and stage via OpsWriter.

    Reads the current record from Athena ops_decisions_current (requires SSO
    connectivity). Merges updates, validates, and stages via OpsWriter.

    Args:
        decision_id: Decision ID string to update (e.g. 'dec-072').
        updates: Fields to merge into the existing record.
        profile: Optional AWS profile override.

    Returns:
        True on success.

    Raises:
        RuntimeError: If Athena is unreachable.
        ValidationError: If the merged record fails schema validation.
    """
    existing = _fetch_decision_from_athena(decision_id, profile=profile)
    if existing is None:
        raise RuntimeError(
            f"update_decision: {decision_id} does not exist in the current projection -- an absent decision "
            "cannot be updated (referential, CD.33 cl.8 / D-5). File it first via file_decision."
        )
    merged = {**existing, **updates}
    merged["id"] = decision_id

    Decision.model_validate(merged)

    # Decisions are DEFERRED from the DuckLake cutover -- they STAY on Iceberg/OpsWriter regardless of
    # OPS_STORAGE_BACKEND until their own migration.
    OpsWriter().write("ops_decisions", merged)
    _append_to_local_jsonl(DECISIONS_JSONL, merged)
    logger.info("[PORTAL] Updated %s: %s", decision_id, list(updates.keys()))
    _sync_table("ops_decisions")
    return True


def drain_pending_decisions(profile: Optional[str] = None) -> dict:
    """Drain queued pending decisions by allocating IDs and staging to OpsWriter.

    Scans logs/.ops-outbox/ops_decisions_pending/ for *.json files. For each file:
    allocates a real ID from DynamoDB (or uses preserved _migration_int_id),
    validates, writes to OpsWriter, appends to local JSONL, and deletes the file.

    Returns:
        {"drained": N, "skipped": M}
    """
    drained = 0
    skipped = 0

    if not _DECISIONS_PENDING_OUTBOX.exists():
        return {"drained": 0, "skipped": 0}

    for pending_file in sorted(_DECISIONS_PENDING_OUTBOX.glob("*.json")):
        try:
            fields = json.loads(pending_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[PORTAL] Cannot read pending decision file %s: %s", pending_file, exc)
            skipped += 1
            continue

        migration_int_id = fields.pop("_migration_int_id", None)

        try:
            result = file_decision(fields, profile=profile, _migration_int_id=migration_int_id)
            if result.startswith("pending-"):
                logger.warning("[PORTAL] DynamoDB still unreachable; leaving %s in outbox", pending_file.name)
                skipped += 1
                continue
            pending_file.unlink(missing_ok=True)
            drained += 1
            logger.info("[PORTAL] Drained pending decision -> %s", result)
        except (ValidationError, ValueError, OSError) as exc:
            logger.warning("[PORTAL] Cannot drain decision %s: %s", pending_file.name, exc)
            skipped += 1

    return {"drained": drained, "skipped": skipped}


def drain_pending(profile: str | None = None) -> dict:
    """Drain queued pending recommendations by allocating IDs and staging to OpsWriter.

    Scans logs/.ops-outbox/ops_recommendations_pending/ for *.json files.
    For each file: allocates a real ID from DynamoDB, validates, writes to
    OpsWriter, appends to local JSONL, and deletes the pending file.

    Postmortem deduplication: if a pending file has source == "executor-postmortem"
    and an open postmortem for the same failed rec already exists in the local JSONL,
    the existing record's context is updated with an attempt counter and the
    pending file is deleted without allocating a new ID.

    If DynamoDB is still unreachable during drain, the file is left for the next
    drain attempt.

    Returns:
        {"drained": N, "skipped": M, "deduped": P}
    """
    drained = 0
    skipped = 0
    deduped = 0

    if not _PENDING_OUTBOX.exists():
        return {"drained": 0, "skipped": 0, "deduped": 0}

    for pending_file in sorted(_PENDING_OUTBOX.glob("*.json")):
        try:
            fields = json.loads(pending_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[PORTAL] Cannot read pending file %s: %s", pending_file, exc)
            skipped += 1
            continue

        # Migration markers (preserved through the outbox so a DynamoDB blip cannot
        # renumber a migrated rec or re-impose content validation on a historical row).
        migration_int_id = fields.pop("_migration_int_id", None)
        migration_mode = bool(fields.pop("_migration_mode", False))

        try:
            validate_source(fields.get("source", ""))
        except ValueError as exc:
            logger.warning("[PORTAL] drain_pending: skipping entry with invalid source -- %s", exc)
            skipped += 1
            continue

        if fields.get("source") == "executor-postmortem":
            m = re.search(r"rec-\d+", fields.get("title", ""))
            if m:
                parent_id = m.group(0)
                existing = find_open_postmortem_for(parent_id)
                if existing:
                    try:
                        now_iso = datetime.now(timezone.utc).isoformat()
                        ctx = existing.get("context", "")
                        attempt_count = ctx.count("; attempt ") + 2
                        update_rec(
                            existing["id"],
                            {
                                "context": ctx + f"; attempt {attempt_count} at {now_iso}",
                                "last_updated_timestamp": now_iso,
                            },
                        )
                        pending_file.unlink(missing_ok=True)
                        deduped += 1
                        logger.info("[PORTAL] Deduped pending postmortem for %s -> updated %s", parent_id, existing["id"])
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("[PORTAL] Deduplication failed for %s: %s", pending_file.name, exc)
                        skipped += 1
                    continue

        if migration_int_id is not None:
            rec_id = f"rec-{int(migration_int_id):03d}"
        else:
            try:
                rec_id = _next_id("recommendations", profile=profile or _SSO_PROFILE)
            except RuntimeError as exc:
                logger.warning("[PORTAL] DynamoDB still unreachable during drain, skipping %s: %s", pending_file.name, exc)
                skipped += 1
                continue

        try:
            merged = dict(fields)
            merged["id"] = str(rec_id)
            merged.setdefault("date", date.today().isoformat())
            _derive_computed_fields(merged)
            if not migration_mode:
                for _col, _validator in _load_write_time_validators("ops_recommendations"):
                    _validator(merged.get(_col), _col)
            Recommendation.model_validate(merged)
            if _ops_backend() == "ducklake":
                _ducklake_write("ops_recommendations", merged, action="write_ops", profile=profile)
            else:
                OpsWriter().write("ops_recommendations", merged)
            _append_to_local_jsonl(RECS_JSONL, merged)
            pending_file.unlink(missing_ok=True)
            drained += 1
            logger.info("[PORTAL] Drained pending rec -> %s", rec_id)
        except (ValidationError, ValueError, OSError) as exc:
            logger.warning("[PORTAL] Cannot drain %s: %s", pending_file.name, exc)
            skipped += 1

    return {"drained": drained, "skipped": skipped, "deduped": deduped}


def sync(tables: Optional[list] = None) -> dict:
    """Compact Iceberg tables, refresh views, and pull local cache.

    This is the single flush primitive for the ops pipeline. Agents should call
    this instead of managing drain/compact/refresh/pull steps manually.

    Args:
        tables: Ops table names to sync. Defaults to ops_recommendations,
                ops_decisions, ops_priority_queue.

    Returns:
        {"compacted": {table: rows}, "pulled": {table: rows}, "views_refreshed": [...]}

    Raises:
        RuntimeError: If the backend infrastructure is unreachable.
    """
    from scripts.sync_ops import _pull_single_table  # noqa: PLC0415
    from scripts.sync_ops import drain as _drain_outbox  # noqa: PLC0415

    ops_tables = tables or ["ops_recommendations", "ops_decisions", "ops_priority_queue"]
    backend = _ops_backend()

    # Drain the Iceberg outbox first: it buffers offline decisions writes (always Iceberg) and any
    # pre-cutover recs (the VP10 "drain to Iceberg before backfill" step). Idempotent when empty.
    _drain_outbox()

    compacted: dict[str, int] = {}
    pulled: dict[str, int] = {}
    views_refreshed: list[str] = []

    for table in ops_tables:
        # ops_recommendations on DuckLake: the atomic catalog commit eliminates compact/view-refresh
        # (Decision 81 cl.4) -- `current` is already live, so a cache-pull from the reader suffices.
        if table == "ops_recommendations" and backend == "ducklake":
            pulled[table] = _pull_single_table(table)
            continue
        # Deferred tables (decisions/queue) + recs-on-Iceberg rollback: compact + refresh + pull.
        compacted[table] = OpsWriter().compact(table)
        OpsWriter()._refresh_view(table)
        views_refreshed.append(table)
        pulled[table] = _pull_single_table(table)

    return {"compacted": compacted, "pulled": pulled, "views_refreshed": views_refreshed}


def selftest_read(table: str = "ops_recommendations", profile: Optional[str] = None) -> dict:
    """Read a sample row from *table* via the ACTIVE backend's reader (VP14 rollback rehearsal).

    Proves the flag-selected read path serves rows on whichever backend OPS_STORAGE_BACKEND names.
    Returns {"backend": ..., "table": ..., "row_count": ..., "sample_id": ...}.
    """
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    backend = _ops_backend()
    rows = make_reader(profile=profile).current_state(table) or []
    sample_id = (rows[0].get("id") if rows else None) if rows else None
    return {"backend": backend, "table": table, "row_count": len(rows), "sample_id": sample_id}


def selftest_roundtrip(profile: Optional[str] = None) -> dict:
    """Write a file_rec-shaped throwaway rec via the active backend, then read it back (VP15 sign-off).

    Uses a `test-roundtrip-<uuid>` id (valid `test-` prefix; not a DynamoDB-allocated rec-NNN, so the
    live counter is untouched) so the proof does not consume a production ID. On DuckLake the write
    transits the writer Function URL and the read transits the reader -- the closed-boundary proof.
    """
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    backend = _ops_backend()
    probe_id = f"test-roundtrip-{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "id": probe_id,
        "title": "ducklake cutover selftest-roundtrip",
        "source": "manual",
        "status": "open",
        "effort": "XS",
        "priority": "Low",
        "risk": "low",
        "file": "scripts/ops_data_portal.py",
        "context": (
            "Selftest roundtrip probe written by --selftest-roundtrip to prove the active backend's "
            "write+read path end-to-end at cutover sign-off (VP15). Safe to ignore/purge."
        ),
        "acceptance": "grep -q selftest-roundtrip logs/.recommendations-log.jsonl",
        "created_timestamp": now_iso,
        "last_updated_timestamp": now_iso,
    }
    Recommendation.model_validate(record)

    if backend == "ducklake":
        _ducklake_write("ops_recommendations", record, action="write_ops", profile=profile)
    else:
        OpsWriter().write("ops_recommendations", record)

    rows = make_reader(profile=profile).current_state("ops_recommendations", row_filter=f"id = '{probe_id}'") or []
    read_back = bool(rows) and rows[0].get("id") == probe_id
    if not read_back:
        raise RuntimeError(f"selftest_roundtrip FAIL ({backend}): wrote {probe_id} but read-back returned {len(rows)} rows")
    return {"backend": backend, "probe_id": probe_id, "read_back": True}


def enqueue_findings(path: Path, profile: Optional[str] = None) -> dict:
    """Bulk-enqueue findings from a JSONL file into the ops_recommendations portal.

    Reads one finding per line. Blank lines and lines starting with '#' are skipped.
    Schema-invalid entries are counted as invalid, not raised. Per-line JSON parse
    errors are counted as skipped. Missing or empty input file returns zeros without raising.

    Args:
        path: Path to a JSONL file; each line is a dict of Recommendation fields.
        profile: Optional AWS profile override (passed through to file_rec).

    Returns:
        dict with keys: enqueued (int), invalid (int), skipped (int).
    """
    enqueued = 0
    invalid = 0
    skipped = 0

    if not path.exists() or path.stat().st_size == 0:
        return {"enqueued": 0, "invalid": 0, "skipped": 0}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        # Pre-validate schema so invalid entries are caught even on the offline path
        # (file_rec skips Pydantic validation when DynamoDB is unreachable)
        try:
            probe = dict(entry)
            probe.setdefault("id", "test-0")  # satisfies rec-/agent-/test- prefix rule
            probe.setdefault("date", date.today().isoformat())
            Recommendation.model_validate(probe)
        except ValidationError:
            invalid += 1
            continue
        try:
            file_rec(entry, profile=profile)
            enqueued += 1
        except ValidationError:
            invalid += 1
        except OSError:
            skipped += 1

    return {"enqueued": enqueued, "invalid": invalid, "skipped": skipped}


def _append_to_local_jsonl(path: Path, record: dict) -> None:
    """Append a JSON record to the local JSONL file (write-through cache update).

    Creates the file if it does not exist. Uses explicit newline='\n' to
    prevent CRLF on Windows.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError as exc:
        logger.warning("[PORTAL] Write-through to %s failed: %s", path, exc)


def find_open_postmortem_for(failed_rec_id: str) -> Optional[dict]:
    """Return the first open executor-postmortem for failed_rec_id from local JSONL, or None.

    Uses last-wins JSONL semantics (builds a dict keyed by rec ID) then filters
    for source == "executor-postmortem", status == "open", and title containing
    failed_rec_id. Pure function; no side effects.
    """
    try:
        lines = RECS_JSONL.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return None
    by_id: dict = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        rec_id = entry.get("id")
        if rec_id:
            by_id[rec_id] = entry
    for rec in by_id.values():
        if (
            rec.get("source") == "executor-postmortem"
            and rec.get("status") == "open"
            and failed_rec_id in rec.get("title", "")
        ):
            return rec
    return None


def _delete_postmortems_from_iceberg(failed_rec_id: str, profile: Optional[str] = None) -> int:
    """Delete executor postmortem rows for failed_rec_id from the Iceberg ops_recommendations table.

    Runs an Athena DML DELETE and polls until the query completes.
    Returns 0 on failure or when boto3 is unavailable; returns -1 on success
    (Athena DML does not report affected-row counts).

    Raises:
        ValueError: If failed_rec_id does not match the rec-\\d+ pattern.
    """
    if not re.fullmatch(r"rec-\d+", failed_rec_id):
        raise ValueError(f"Invalid rec ID for purge: {failed_rec_id!r}. Must match rec-\\d+.")

    try:
        import boto3  # noqa: PLC0415
    except ImportError:
        logger.warning("[PURGE] boto3 not available; skipping Iceberg delete for %s", failed_rec_id)
        return 0

    _profile = resolve_aws_profile(profile, default=_SSO_PROFILE)
    session = boto3.Session(profile_name=_profile, region_name=_AWS_REGION)
    athena = session.client("athena", region_name=_AWS_REGION)

    title_prefix = f"Investigate executor failure for {failed_rec_id}"
    query = (
        f"DELETE FROM {_ATHENA_DATABASE}.ops_recommendations "
        f"WHERE source = 'executor-postmortem' "
        f"AND title LIKE '{title_prefix}%'"
    )
    bucket = os.environ.get("S3_LOG_BUCKET", "agent-platform-data-lake")

    try:
        response = athena.start_query_execution(
            QueryString=query,
            WorkGroup=_ATHENA_WORKGROUP,
            ResultConfiguration={"OutputLocation": f"s3://{bucket}/athena-results/"},
        )
        exec_id = response["QueryExecutionId"]

        import time  # noqa: PLC0415

        state = "RUNNING"
        status_resp: dict = {}
        for _ in range(60):
            time.sleep(2)
            status_resp = athena.get_query_execution(QueryExecutionId=exec_id)
            state = status_resp["QueryExecution"]["Status"]["State"]
            if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
                break

        if state != "SUCCEEDED":
            reason = status_resp.get("QueryExecution", {}).get("Status", {}).get("StateChangeReason", "unknown")
            logger.warning("[PURGE] Iceberg DELETE ended with state %s: %s", state, reason)
            return 0

        logger.info("[PURGE] Iceberg DELETE completed for %s", failed_rec_id)
        return -1  # Athena DML does not return affected-row counts
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PURGE] Iceberg delete failed for %s: %s", failed_rec_id, exc)
        return 0


def _rewrite_jsonl_excluding_postmortems(postmortem_ids: set) -> None:
    """Rewrite local JSONL removing all lines belonging to postmortem_ids.

    Uses the rename-create-delete pattern to prevent partial-write corruption on
    Windows: write to .jsonl.new, rename canonical to .jsonl.old, rename .new to
    canonical, delete .old.
    """
    try:
        lines = RECS_JSONL.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return

    kept: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            kept.append(line)
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        if entry.get("id") in postmortem_ids:
            continue
        kept.append(line)

    content = "\n".join(kept)
    if not content.endswith("\n"):
        content += "\n"

    path_new = Path(str(RECS_JSONL) + ".new")
    path_old = Path(str(RECS_JSONL) + ".old")
    path_new.write_text(content, encoding="utf-8", newline="\n")
    RECS_JSONL.rename(path_old)
    path_new.rename(RECS_JSONL)
    path_old.unlink(missing_ok=True)


def purge_postmortems_for(failed_rec_id: str, dry_run: bool = False, profile: Optional[str] = None) -> dict:
    """Discover and optionally hard-delete all executor postmortems for failed_rec_id.

    Steps (when dry_run=False):
      1. Delete pending outbox files whose title references failed_rec_id.
      2. Run Athena DML DELETE to remove matching rows from the Iceberg table.
      3. Rewrite local JSONL excluding the postmortem entries (rename-create-delete).
      4. Update failed_rec_id itself to status=declined.

    Returns:
        {"pending_files": N, "jsonl_entries": M, "iceberg_delete_attempted": bool}
    """
    # Discover pending files
    pending_matches: list[Path] = []
    if _PENDING_OUTBOX.exists():
        for f in sorted(_PENDING_OUTBOX.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if failed_rec_id in data.get("title", ""):
                    pending_matches.append(f)
            except (json.JSONDecodeError, OSError):
                pass

    # Discover JSONL postmortem entries (last-wins per ID)
    try:
        lines = RECS_JSONL.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        lines = []

    by_id: dict = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        rec_id = entry.get("id")
        if rec_id:
            by_id[rec_id] = entry

    postmortem_ids: set = {
        rec["id"]
        for rec in by_id.values()
        if rec.get("source") == "executor-postmortem" and failed_rec_id in rec.get("title", "")
    }

    result = {
        "pending_files": len(pending_matches),
        "jsonl_entries": len(postmortem_ids),
        "iceberg_delete_attempted": False,
    }

    if dry_run:
        logger.info(
            "[PURGE] Dry-run for %s: %d pending files, %d JSONL entries would be removed.",
            failed_rec_id,
            len(pending_matches),
            len(postmortem_ids),
        )
        return result

    for f in pending_matches:
        f.unlink(missing_ok=True)
        logger.info("[PURGE] Deleted pending file %s", f.name)

    iceberg_result = _delete_postmortems_from_iceberg(failed_rec_id, profile=profile)
    result["iceberg_delete_attempted"] = iceberg_result != 0

    if postmortem_ids:
        _rewrite_jsonl_excluding_postmortems(postmortem_ids)

    resolution = (
        f"SCP block prevents IAM/OIDC operations required by {failed_rec_id}. "
        "Executor postmortems purged via ops_data_portal --purge-postmortems-for."
    )
    update_rec(failed_rec_id, {"status": "declined", "resolution": resolution}, profile=profile)

    logger.info(
        "[PURGE] Complete for %s: %d pending deleted, %d JSONL entries removed.",
        failed_rec_id,
        len(pending_matches),
        len(postmortem_ids),
    )
    return result


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for the ops data portal."""
    parser = argparse.ArgumentParser(
        description="Unified gateway for filing and updating recommendations and decisions.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--profile", metavar="AWS_PROFILE", default=None, help="AWS profile override")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview purge without writing (use with --purge-postmortems-for)"
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--file-rec", action="store_true", help="File a new recommendation")
    action.add_argument("--update-rec", metavar="REC_ID", help="Update an existing recommendation")
    action.add_argument("--file-decision", action="store_true", help="File a new decision")
    action.add_argument(
        "--update-decision", metavar="DECISION_ID", type=str, help="Update an existing decision (e.g. dec-072)"
    )
    action.add_argument("--purge-postmortems-for", metavar="REC_ID", help="Hard-delete all executor postmortems for REC_ID")
    action.add_argument(
        "--enqueue-findings",
        metavar="PATH",
        help="Bulk-enqueue findings from a JSONL file into ops_recommendations",
    )
    action.add_argument(
        "--guidance",
        action="store_true",
        help="Print field semantics and registered source values as YAML, then exit",
    )
    action.add_argument(
        "--sync",
        action="store_true",
        help="Drain + refresh the local read-cache from the active backend (OPS_STORAGE_BACKEND)",
    )
    action.add_argument(
        "--selftest-read",
        action="store_true",
        help="Read a sample row via the active backend's reader (rollback rehearsal, VP14)",
    )
    action.add_argument(
        "--selftest-roundtrip",
        action="store_true",
        help="Write+read a throwaway test- rec via the active backend (cutover sign-off, VP15)",
    )

    # file-rec fields
    rec = parser.add_argument_group("--file-rec fields")
    rec.add_argument("--title")
    rec.add_argument("--file", dest="target_file")
    rec.add_argument("--context", dest="rec_context")
    rec.add_argument("--acceptance")
    rec.add_argument("--effort", choices=["XS", "S", "M", "L", "XL"])
    rec.add_argument("--priority", choices=["Critical", "High", "Medium", "Low"])
    rec.add_argument("--source")
    rec.add_argument("--risk", choices=["low", "medium", "high"])
    rec.add_argument("--tags", nargs="*", default=None)
    rec.add_argument("--dependencies", nargs="*", default=None)
    rec.add_argument("--verification")
    rec.add_argument("--verification-tier", choices=["V1", "V2", "V3"], dest="verification_tier")

    # update-rec fields
    upd = parser.add_argument_group("--update-rec fields")
    upd.add_argument("--status", choices=["open", "closed", "failed", "declined", "superseded"])
    upd.add_argument("--execution_result", choices=["success", "failure", "manual", "already_implemented"])
    upd.add_argument("--execution_date")
    upd.add_argument("--execution_branch")
    upd.add_argument("--execution_pr_url")
    upd.add_argument("--resolution")

    # file-decision fields
    dec = parser.add_argument_group("--file-decision fields")
    dec.add_argument("--rationale")
    dec.add_argument("--decision-status", choices=["open", "closed", "superseded"], dest="decision_status")

    args = parser.parse_args(argv)

    if args.file_rec:
        required = ["title", "target_file", "rec_context", "acceptance", "effort", "priority", "source", "risk"]
        missing = [r for r in required if not getattr(args, r, None)]
        if missing:
            print(f"ERROR: --file-rec requires: {', '.join(missing)}", file=sys.stderr)
            return 1
        fields: dict = {
            "title": args.title,
            "file": args.target_file,
            "context": args.rec_context,
            "acceptance": args.acceptance,
            "effort": args.effort,
            "priority": args.priority,
            "source": args.source,
            "risk": args.risk,
            "status": "open",
        }
        if args.tags is not None:
            fields["tags"] = args.tags
        if args.dependencies is not None:
            fields["dependencies"] = args.dependencies
        if args.verification:
            fields["verification"] = args.verification
        if args.verification_tier:
            fields["verification_tier"] = args.verification_tier
        try:
            rec_id = file_rec(fields, profile=args.profile)
            print(rec_id)
            return 0
        except (ValidationError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.update_rec:
        updates: dict = {}
        for field in ["status", "execution_result", "execution_date", "execution_branch", "execution_pr_url", "resolution"]:
            val = getattr(args, field, None)
            if val is not None:
                updates[field] = val
        if not updates:
            print("ERROR: --update-rec requires at least one update field (e.g. --status)", file=sys.stderr)
            return 1
        try:
            update_rec(args.update_rec, updates, profile=args.profile)
            print(f"Updated {args.update_rec}")
            return 0
        except (ValidationError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.file_decision:
        required_dec = ["title", "decision_status", "rationale"]
        missing_dec = [r for r in required_dec if not getattr(args, r.replace("-", "_"), None)]
        if missing_dec:
            # Check mapped names
            actually_missing = []
            if not args.title:
                actually_missing.append("--title")
            if not args.decision_status:
                actually_missing.append("--decision-status")
            if not args.rationale:
                actually_missing.append("--rationale")
            if actually_missing:
                print(f"ERROR: --file-decision requires: {', '.join(actually_missing)}", file=sys.stderr)
                return 1
        dec_fields: dict = {
            "title": args.title,
            "status": args.decision_status,
            "rationale": args.rationale,
        }
        decision_id = file_decision(dec_fields, profile=args.profile)
        if decision_id == -1:
            print("queued-pending", file=sys.stderr)
            return 1
        print(decision_id)
        return 0

    if args.update_decision is not None:
        dec_updates: dict = {}
        if args.status:
            dec_updates["status"] = args.status
        if args.resolution:
            dec_updates["resolution"] = args.resolution
        if not dec_updates:
            print("ERROR: --update-decision requires at least one update field", file=sys.stderr)
            return 1
        update_decision(args.update_decision, dec_updates, profile=args.profile)
        print(f"Updated decision {args.update_decision}")
        return 0

    if args.purge_postmortems_for:
        result = purge_postmortems_for(args.purge_postmortems_for, dry_run=args.dry_run, profile=args.profile)
        print(json.dumps(result, indent=2))
        return 0

    if args.enqueue_findings:
        result = enqueue_findings(Path(args.enqueue_findings), profile=args.profile)
        print(f"enqueued: {result['enqueued']}, invalid: {result['invalid']}, skipped: {result['skipped']}")
        return 0

    if args.guidance:
        from scripts.executor.rec_write_guidance import get_rec_write_guidance

        guidance = get_rec_write_guidance()
        print(yaml.dump(guidance, default_flow_style=False, sort_keys=True, allow_unicode=True))
        return 0

    if args.sync:
        result = sync()
        print(json.dumps(result, indent=2))
        return 0

    if args.selftest_read:
        result = selftest_read(profile=args.profile)
        print(json.dumps(result, indent=2))
        return 0

    if args.selftest_roundtrip:
        try:
            result = selftest_roundtrip(profile=args.profile)
        except (RuntimeError, ValueError, ValidationError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
