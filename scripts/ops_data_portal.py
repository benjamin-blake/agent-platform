# complexity-waiver: decision-43
"""Unified write gateway for recommendation and decision operations.

All writes to ops_recommendations and ops_decisions MUST go through this
module. Direct appends to logs/.recommendations-log.jsonl are forbidden and
caught by validate.py.

Failure mode (Decision 84 I-4): a write that cannot complete fails LOUDLY at
the call site -- there is no offline outbox. Entity ids (rec-NNN) are allocated
by the ducklake_writer atomically with the insert (I-2); decision numbering
authority is DECISIONS.md (the caller supplies decision_id).

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
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from scripts.aws_profile import resolve_aws_profile
from scripts.executor.acceptance_lint import lint_acceptance_command
from scripts.executor.jsonl_store import _VALID_STATUSES, DECISIONS_JSONL, RECS_JSONL, Decision, Recommendation
from scripts.executor.rec_write_guidance import validate_source

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SSO_PROFILE = "agent_platform"
_FEATURE_FLAGS_YAML = _REPO_ROOT / "config" / "feature_flags.yaml"

_ci_rca_strict_mode_cache: Optional[str] = None

_AWS_REGION = "eu-west-2"

_EFFORT_SCALE: dict[str, float] = {"XS": 0.1, "S": 0.5, "M": 1.0, "L": 3.0, "XL": 5.0}
_COVERAGE_XML = _REPO_ROOT / "coverage.xml"
_CAPABILITIES_YAML = _REPO_ROOT / "config" / "agent" / "executor" / "capabilities.yaml"
_OPS_YAML_PATH = _REPO_ROOT / "config" / "agent" / "data_quality" / "ops.yaml"
_capabilities_cache: Optional[dict] = None
_write_time_validators_cache: dict[str, list] = {}

# --- DuckLake closed-boundary transport (T2.19 / Decision 81; sole backend per Decision 84 I-1) ----
# The Single-Portal caller surface (file_rec/update_rec/file_decision/update_decision/sync) is
# unchanged; the transport underneath is the closed writer/reader Function-URL boundary. The
# OPS_STORAGE_BACKEND rollback flag was retired by Decision 84 (the frozen Iceberg copy stopped
# being a coherent rollback target the day writes moved to DuckLake).
_DUCKLAKE_WRITER_URL_ENV = "DUCKLAKE_WRITER_URL"
_DUCKLAKE_WRITER_FUNCTION_NAME = "agent-platform-ducklake-writer"
_AWS_LAMBDA_SERVICE = "lambda"
# SSM path declared in src/lambdas/ducklake_writer/manifest.yaml runtime_config[] (Decision 79 SSOT).
_DUCKLAKE_WRITER_SSM_PATH = "/agent-platform/ducklake/writer_url"

# Portal table -> DuckLake ops_* table (the writer/reader select schema by this name).
_PORTAL_TABLE_NAMES = ("ops_recommendations", "ops_decisions")

# DECISIONS.md columns carried by the backfill ETL. Excludes id + decision_id (passed via
# _migration_int_id) and the timestamps (portal/runtime stamp them; the store is recreatable).
_DECISION_BACKFILL_COLS = ("title", "status", "problem", "decision_text", "context", "decided_date", "related_decisions")

# Writer 5xx statuses retried once the request is idempotent (Neon scale-to-zero cold resume --
# same rationale as the reader's transient retry, src/common/iceberg_reader.py).
_WRITER_TRANSIENT_STATUS = (502, 503, 504)
_WRITER_MAX_ATTEMPTS = 3
_WRITER_RETRY_BACKOFF_S = (2.0, 5.0)


_CI_RCA_VALID_MODES = frozenset({"warn", "strict"})
_WHY_CHAIN_SYSTEMIC_KEYWORDS = frozenset(
    {
        "gate",
        "tier",
        "policy",
        "contract",
        "gap",
        "missing",
        "absent",
        "placement",
        "scope",
        "invariant",
        "enforcement",
    }
)
_WHY_CHAIN_CITATION_RE = re.compile(r"[\w./-]+\.(py|yaml|tf|md|sh):\d+")


def get_ci_rca_strict_mode() -> str:
    """Return the CI_RCA_STRICT_MODE flag value ('warn' or 'strict').

    Module-level cached read of config/feature_flags.yaml (no hot-reload).
    Defaults to 'warn' when the key or file is absent. Raises ValueError for
    unrecognised values so misconfiguration is loud (Decision 55).
    """
    global _ci_rca_strict_mode_cache
    if _ci_rca_strict_mode_cache is not None:
        return _ci_rca_strict_mode_cache
    try:
        data = yaml.safe_load(_FEATURE_FLAGS_YAML.read_text(encoding="utf-8")) or {}
        value = data.get("CI_RCA_STRICT_MODE", "warn")
    except (FileNotFoundError, OSError, yaml.YAMLError):
        value = "warn"
    if value not in _CI_RCA_VALID_MODES:
        raise ValueError(f"CI_RCA_STRICT_MODE={value!r} is not a valid mode; accepted: {sorted(_CI_RCA_VALID_MODES)}")
    _ci_rca_strict_mode_cache = value
    return value


class _EvidenceBundleRef(BaseModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    s3_uri: str = Field(pattern=r"^s3://")
    upload_status: str


class _DetectionGap(BaseModel):
    earliest_viable_gate: str = Field(pattern=r"^(pre|presubmit|CI)$")
    actual_gate_that_caught_it: str = Field(pattern=r"^(pre|presubmit|CI)$")
    gap_explanation: str = Field(min_length=120, max_length=600)

    @field_validator("gap_explanation")
    @classmethod
    def _gap_has_file_citation(cls, v: str) -> str:
        if not _WHY_CHAIN_CITATION_RE.search(v):
            raise ValueError("gap_explanation must contain a file:line citation (e.g. scripts/validate.py:284)")
        return v


class CiRcaContext(BaseModel):
    """Structured context schema for source=ci_rca recommendations (INTENT Section 1).

    Enforced in warn mode by file_rec() when CI_RCA_STRICT_MODE=warn; raises in strict mode.
    Shape-only validation for prior_art_citation and evidence_bundle_ref (existence checks deferred
    to PLAN-ci-rca-evidence-script Phase 2).
    """

    schema_version: int = Field(default=1, ge=1, le=1)
    proximate_cause: str = Field(min_length=100, max_length=600)
    why_chain: list[str] = Field(min_length=3, max_length=7)
    why_chain_terminus_override: Optional[dict] = None
    detection_gap: _DetectionGap
    recurrence_class: str = Field(pattern=r"^(novel|instance_of_known_pattern|regression)$")
    prior_art_citation: Optional[str] = None  # shape-only; existence check deferred (Phase 2)
    corrective_action: str = Field(min_length=100, max_length=600)
    preventive_action: str = Field(min_length=100, max_length=800)
    evidence_bundle_ref: Optional[_EvidenceBundleRef] = None  # shape-only; S3 check deferred (Phase 2)

    @field_validator("why_chain")
    @classmethod
    def _validate_why_chain_entries(cls, v: list[str]) -> list[str]:
        for i, entry in enumerate(v):
            if len(entry) < 40:
                raise ValueError(f"why_chain[{i}] is too short ({len(entry)} chars; min 40)")
            if len(entry) > 250:
                raise ValueError(f"why_chain[{i}] is too long ({len(entry)} chars; max 250)")
        return v

    @model_validator(mode="after")
    def _validate_terminus(self) -> "CiRcaContext":
        if self.why_chain_terminus_override:
            return self
        final = self.why_chain[-1] if self.why_chain else ""
        lower = final.lower()
        has_systemic = any(kw in lower for kw in _WHY_CHAIN_SYSTEMIC_KEYWORDS)
        has_citation = bool(_WHY_CHAIN_CITATION_RE.search(final))
        errors: list[str] = []
        if not has_systemic:
            errors.append(f"why_chain final entry lacks a systemic keyword from {sorted(_WHY_CHAIN_SYSTEMIC_KEYWORDS)!r}")
        if not has_citation:
            errors.append("why_chain final entry lacks a file:line citation (e.g. scripts/validate.py:284)")
        if errors:
            raise ValueError("; ".join(errors))
        return self


def _validate_ci_rca_context_v2(context_v2_json: dict) -> list[str]:
    """Validate a context_v2_json dict against CiRcaContext. Returns a list of deficiency strings (empty = valid)."""
    from pydantic import ValidationError as PydanticError  # noqa: PLC0415

    try:
        CiRcaContext.model_validate(context_v2_json)
        return []
    except PydanticError as exc:
        return [str(e["msg"]) for e in exc.errors()]


def _resolve_writer_url(profile: Optional[str] = None) -> str:
    """Resolve the ducklake_writer Function URL.

    Resolution order (Decision 79 SSOT):
      1. env DUCKLAKE_WRITER_URL -- CI / explicit override
      2. SSM /agent-platform/ducklake/writer_url -- CC-web (no terraform binary)
      3. terraform output ducklake_writer_function_url -- local dev with initialized checkout
      4. lambda:GetFunctionUrlConfig -- last resort (CI runner, github_ci OIDC role)

    Loud-fail if all four are unavailable.
    """
    from src.common.iceberg_reader import (  # noqa: PLC0415
        _resolve_function_url_via_api as _api_resolver,
    )
    from src.common.iceberg_reader import (
        _resolve_function_url_via_ssm as _ssm_resolver,
    )

    url = os.environ.get(_DUCKLAKE_WRITER_URL_ENV)
    if url:
        return url.rstrip("/")
    ssm_url = _ssm_resolver(_DUCKLAKE_WRITER_SSM_PATH, profile=profile, region=_AWS_REGION)
    if ssm_url:
        return ssm_url
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
    api_url = _api_resolver(_DUCKLAKE_WRITER_FUNCTION_NAME, profile=profile, region=_AWS_REGION)
    if api_url:
        return api_url.rstrip("/")
    raise RuntimeError(
        f"{_DUCKLAKE_WRITER_URL_ENV} not set, SSM {_DUCKLAKE_WRITER_SSM_PATH!r} unavailable, "
        "terraform output 'ducklake_writer_function_url' unavailable, and "
        "lambda:GetFunctionUrlConfig fallback failed -- cannot reach the DuckLake writer "
        "(Decision 84: DuckLake is the sole ops backend)."
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


def _ducklake_write(
    table: str,
    record: dict,
    *,
    action: str,
    profile: Optional[str] = None,
    idempotency_ulid: Optional[str] = None,
) -> dict:
    """Invoke the ducklake_writer Function URL (SigV4) for a production ops write. Loud-fail on error.

    action is 'file_ops' (create; the writer allocates the entity id and returns it as `key`),
    'write_ops' (caller-keyed upsert: ETL backfill + test- probes), or 'update_ops' (update; the
    writer enforces the in-tx referential existence check). `idempotency_ulid` makes file_ops
    replay-safe, which is what licenses the transient-5xx retry below (Neon cold-resume): a retried
    request returns the originally allocated id instead of double-filing. Maps the writer's
    loud-fail status codes back to portal exceptions.
    """
    import time as _time  # noqa: PLC0415

    import boto3  # noqa: PLC0415
    import requests  # noqa: PLC0415
    from botocore.auth import SigV4Auth  # noqa: PLC0415
    from botocore.awsrequest import AWSRequest  # noqa: PLC0415

    url = _resolve_writer_url(profile=profile)
    payload = {"action": action, "table": table, "record": _project_ops_record(table, record)}
    if idempotency_ulid is not None:
        payload["idempotency_ulid"] = idempotency_ulid
    body = json.dumps(payload)
    headers = {"Content-Type": "application/json"}
    session = boto3.Session(profile_name=resolve_aws_profile(profile, default=_SSO_PROFILE))
    creds = session.get_credentials().get_frozen_credentials()

    retryable = idempotency_ulid is not None or action == "update_ops"
    last_status: Optional[int] = None
    last_text = ""
    for attempt in range(_WRITER_MAX_ATTEMPTS):
        # Re-sign per attempt: SigV4 carries a timestamp.
        aws_req = AWSRequest(method="POST", url=url, data=body, headers=dict(headers))
        SigV4Auth(creds, _AWS_LAMBDA_SERVICE, _AWS_REGION).add_auth(aws_req)
        try:
            resp = requests.post(url, data=body, headers=dict(aws_req.headers), timeout=180)
        except requests.RequestException as exc:
            # The response-lost case the idempotency key exists FOR: the write may have committed.
            # Retrying with the SAME body/ULID makes the writer replay-check return the original
            # allocation instead of double-filing.
            last_status, last_text = None, f"{type(exc).__name__}: {exc}"
            if retryable and attempt < _WRITER_MAX_ATTEMPTS - 1:
                logger.warning(
                    "ducklake_writer %s connection failure (attempt %d/%d): %s -- retrying same ULID",
                    action,
                    attempt + 1,
                    _WRITER_MAX_ATTEMPTS,
                    exc,
                )
                _time.sleep(_WRITER_RETRY_BACKOFF_S[attempt])
                continue
            raise RuntimeError(f"ducklake_writer {action} {table} failed ({last_text})") from exc
        if resp.status_code == 200:
            return resp.json()
        last_status, last_text = resp.status_code, resp.text[:400]
        if resp.status_code == 409:
            raise RuntimeError(f"ducklake_writer referential failure ({action} {table}): {last_text}")
        if resp.status_code == 422:
            raise ValueError(f"ducklake_writer schema-gate rejection ({action} {table}): {last_text}")
        if resp.status_code == 503 and '"occ_exhausted"' in last_text:
            # OCC budget exhaustion is stop-and-RCA (Decision 55), never blindly re-driven.
            raise RuntimeError(f"ducklake_writer OCC budget exhausted ({action} {table}): {last_text}")
        if retryable and resp.status_code in _WRITER_TRANSIENT_STATUS and attempt < _WRITER_MAX_ATTEMPTS - 1:
            logger.warning(
                "ducklake_writer %s HTTP %d (attempt %d/%d) -- retrying after cold-resume backoff",
                action,
                resp.status_code,
                attempt + 1,
                _WRITER_MAX_ATTEMPTS,
            )
            _time.sleep(_WRITER_RETRY_BACKOFF_S[attempt])
            continue
        break
    raise RuntimeError(f"ducklake_writer {action} {table} failed (HTTP {last_status}): {last_text}")


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

    Called from file_rec() to ensure a single shared
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
    context_v2_json: Optional[dict] = None,
) -> str:
    """File a new recommendation; the ducklake_writer allocates its ID atomically with the insert.

    On success returns the allocated ID (e.g. 'rec-2171'). On any failure the
    call raises LOUDLY (Decision 84 I-4) -- there is no offline outbox; the
    transient-5xx retry inside _ducklake_write (idempotent via the per-call
    ULID) is the only retry.

    Args:
        fields: Rec fields (MUST include at minimum: title, file, status,
                source, effort, priority, context, acceptance, risk).
        profile: Optional AWS profile override (uses AWS_PROFILE env var by default).
        _migration_int_id: PRIVATE. Backfill-only: preserves a historical integer ID
            via a caller-keyed write_ops upsert instead of writer allocation. The id
            is formed as f"rec-{n:03d}" (zero-padded under 1000) so dependency /
            priority-queue FKs to padded ids still match. Must not be used elsewhere.
        _skip_sync: PRIVATE. When True, suppress the per-row _sync_table() flush so
            a bulk import can call sync() exactly once at the end. Migration-only.
        _migration_mode: PRIVATE. When True, bypass the write-time CONTENT-quality
            validation surface (the three explicit calls _validate_file_path /
            _validate_context_length / lint_acceptance_command AND the YAML-loaded
            _load_write_time_validators loop) so historical rows that predate later
            content-rule tightening still import. validate_source and the
            Recommendation schema (model_validate) remain enforced. Migration-only.
        context_v2_json: Optional structured CiRcaContext dict for source=ci_rca recs.
            When provided: validated against CiRcaContext in warn mode (deficiencies log
            a structured warning but do NOT raise); a >=80-char human summary is written
            into the legacy context column. When absent with source=ci_rca: a deprecation
            warning is logged and the rec is filed with legacy free-text context only.

    Returns:
        Allocated ID string ('rec-NNN'). Raises on failure (no offline mode).

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

    # context_v2_json warn-mode validation for source=ci_rca (CI_RCA_STRICT_MODE; INTENT Section 1).
    # Must run before _validate_context_length so the human summary can satisfy the 80-char floor.
    if fields.get("source") == "ci_rca":
        if context_v2_json is not None:
            deficiencies = _validate_ci_rca_context_v2(context_v2_json)
            if deficiencies:
                mode = get_ci_rca_strict_mode()
                if mode == "strict":
                    raise ValueError(
                        f"[CI_RCA_STRICT_MODE=strict] context_v2_json failed validation: {'; '.join(deficiencies)}"
                    )
                logger.warning(
                    "[CI_RCA_STRICT_MODE=warn] context_v2_json deficiencies (rec filed anyway): %s",
                    "; ".join(deficiencies),
                )
            # Build a >=80-char human summary for the legacy context column from the structured schema.
            parts = []
            if context_v2_json.get("proximate_cause"):
                parts.append(f"Proximate cause: {context_v2_json['proximate_cause'][:400]}")
            if context_v2_json.get("corrective_action"):
                parts.append(f"Corrective: {context_v2_json['corrective_action'][:200]}")
            if context_v2_json.get("preventive_action"):
                parts.append(f"Preventive: {context_v2_json['preventive_action'][:200]}")
            summary = " | ".join(parts)
            if len(summary) < 80:
                summary = summary + " [ci_rca structured context -- see context_v2_json for full detail]"
            if not fields.get("context"):
                fields["context"] = summary
            elif len(fields["context"].strip()) < 80:
                fields["context"] = summary
        elif not _migration_mode:
            logger.warning(
                "[PORTAL] source=ci_rca rec filed with legacy free-text context (no context_v2_json). "
                "Migrate to context_v2_json per PLAN-ci-rca-schema-enforcement."
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

    merged = dict(fields)
    if context_v2_json is not None:
        merged["context_v2_json"] = json.dumps(context_v2_json)
    merged.pop("id", None)
    merged.setdefault("date", date.today().isoformat())

    response: dict = {}
    if _migration_int_id is not None:
        # Backfill path: the historical id is preserved via a caller-keyed write_ops upsert.
        rec_id = f"rec-{_migration_int_id:03d}"
        merged["id"] = rec_id
        Recommendation.model_validate(merged)
        response = _ducklake_write("ops_recommendations", merged, action="write_ops", profile=profile)
    else:
        # Fail fast client-side with a placeholder id; the writer's schema gate is authoritative.
        Recommendation.model_validate({**merged, "id": "rec-0"})
        # The writer allocates rec-NNN atomically with the insert (Decision 84 I-2). The
        # idempotency ULID makes a response-lost retry return the original allocation.
        from src.common.ducklake_runtime import mint_write_identity  # noqa: PLC0415

        response = _ducklake_write(
            "ops_recommendations",
            merged,
            action="file_ops",
            profile=profile,
            idempotency_ulid=mint_write_identity().ulid,
        )
        rec_id = response.get("key", "")
        if not rec_id:
            raise RuntimeError(f"ducklake_writer file_ops returned no allocated key: {response}")
        merged["id"] = str(rec_id)

    logger.info("[PORTAL] Filed %s: %s", rec_id, merged.get("title", ""))
    _refresh_cache_after_write("ops_recommendations", merged, response, RECS_JSONL, append_only=_skip_sync)
    return str(rec_id)


def _fetch_rec_from_reader(rec_id: str, profile: Optional[str] = None) -> Optional[dict]:
    """Fetch a single ops_recommendations record by id via the rec_by_id read verb.

    Closed boundary (Decision 81 cl.7 / Decision 84 I-3): the read transits the
    ducklake_reader named-verb surface; no SQL leaves the client. Decision 69:
    raises RuntimeError if the reader is unreachable. Never falls back to the
    local JSONL cache.

    Returns the record dict (coerced and sanitised) or None if not found.
    """
    if not re.fullmatch(r"rec-\d+", rec_id):
        raise ValueError(f"_fetch_rec_from_reader: invalid rec_id: {rec_id!r}")

    from scripts.sync_ops import _coerce_ops_rec_row  # noqa: PLC0415
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    rows = make_reader(profile=profile).named("rec_by_id", id=rec_id)
    if not rows:
        return None
    coerced = _coerce_ops_rec_row(dict(rows[0]))
    return _sanitize_athena_record(coerced) if coerced is not None else None


def _sync_table(table: str) -> None:
    """Full-pull refresh of the local read-cache for one ops table from the DuckLake reader.

    The atomic catalog commit means there is no compaction/view-refresh step (Decision 81 cl.4) --
    the write already landed in `current`, so a cache-pull from the reader suffices for every
    migrated table (Decision 84 I-1). Raises on infrastructure failure.

    This is the EXPLICIT full-table reconciliation primitive, retained for the bulk-backfill
    post-loop sync and the `sync()` fallback. The per-write path no longer calls it -- it uses
    _refresh_cache_after_write (incremental upsert, no reader round-trip; neon-egress-reduction D4).
    """
    from scripts.sync_ops import _pull_single_table  # noqa: PLC0415

    _pull_single_table(table)


def _refresh_cache_after_write(
    table: str,
    record: dict,
    response: dict,
    jsonl_path: Path,
    *,
    append_only: bool = False,
) -> None:
    """Refresh the local READ cache after a synchronous ducklake_writer commit -- no reader round-trip.

    Replaces the prior per-write full-table resync (_sync_table -> _pull_single_table, one reader
    invocation per file_rec/update_rec) with an incremental single-row upsert of the just-committed
    row (neon-egress-reduction D4). The write itself already transited ducklake_writer synchronously;
    this is a downstream refresh of the READ cache (Decision 84 I-4 / warehouse-as-source-of-truth):
    NEVER a write source, NEVER re-staged to S3/the writer.

    The committed `record` is enriched from the writer's authoritative `response`: the minted ULID
    (when returned) and the SCD2 timestamps. created_timestamp is set only if absent (carried
    unchanged on update, matching the runtime's SCD2 derivation); last_updated_timestamp is stamped
    now (the writer minted it at ~this instant; the next full `sync` reconciles any sub-second skew).

    append_only=True (bulk-import `_skip_sync` path) keeps the historical append-then-final-sync
    behaviour: the caller runs ONE explicit _sync_table after the loop, which dedups via full pull.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    record.setdefault("created_timestamp", now_iso)
    record["last_updated_timestamp"] = now_iso
    ulid = response.get("ulid") if isinstance(response, dict) else None
    if ulid:
        record["ulid"] = ulid

    if append_only:
        _append_to_local_jsonl(jsonl_path, record)
        return

    from scripts.sync_ops import upsert_cache_row  # noqa: PLC0415

    upsert_cache_row(table, record, path=jsonl_path)


def _sanitize_athena_record(record: dict) -> dict:
    """Replace empty strings with None for fields that Athena serialises as '' for NULL."""
    result = dict(record)
    for key, value in result.items():
        if value == "":
            result[key] = None
    return result


def update_rec(rec_id: str, updates: dict, profile: Optional[str] = None) -> bool:
    """Merge update fields into an existing recommendation and write via the DuckLake closed boundary.

    Reads the current record via DuckLake reader (ducklake backend) or DuckDBIcebergReader
    (iceberg rollback). Raises RuntimeError if the warehouse is unreachable. Merges updates,
    validates the merged record, routes the write to _ducklake_write, writes through to local
    JSONL, then triggers _sync_table to refresh the read cache.

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
    existing = _fetch_rec_from_reader(rec_id, profile=profile)
    if existing is None:
        raise RuntimeError(
            f"update_rec: {rec_id} does not exist in the current projection -- an absent rec cannot be "
            "updated (referential, CD.33 cl.8 / D-5). File it first via file_rec."
        )
    merged = {**existing, **updates}
    merged["id"] = rec_id  # always preserve the ID

    Recommendation.model_validate(merged)  # raises on failure

    # ops_recommendations always routes to DuckLake (Decision 81 cl.7 / T2.19).
    response = _ducklake_write("ops_recommendations", merged, action="update_ops", profile=profile)
    logger.info("[PORTAL] Updated %s: %s", rec_id, list(updates.keys()))
    _refresh_cache_after_write("ops_recommendations", merged, response, RECS_JSONL)
    return True


def file_decision(
    fields: dict,
    profile: Optional[str] = None,
    _migration_int_id: Optional[int] = None,
    _skip_sync: bool = False,
) -> str:
    """File a decision row for a DECISIONS.md entry (numbering authority: DECISIONS.md).

    Decision 84 I-2 exception: decision numbers are human-assigned in DECISIONS.md before
    any write, so the caller supplies the integer number via fields['decision_id'] (the
    backfill path passes _migration_int_id). The id is formed as dec-{n:03d}. The write is
    a caller-keyed write_ops upsert, so re-running the backfill refreshes the same id
    rather than duplicating it.

    Returns:
        The decision ID string (e.g. 'dec-084'). Raises LOUDLY on any failure (no outbox).
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    merged = dict(fields)

    n = _migration_int_id if _migration_int_id is not None else merged.get("decision_id")
    if not isinstance(n, int) or n <= 0:
        raise ValueError(
            "file_decision requires the DECISIONS.md-assigned integer decision number "
            "(fields['decision_id'] or _migration_int_id): decisions are authored in "
            "DECISIONS.md FIRST (Decision 84 I-2 exception)"
        )

    dec_id = f"dec-{n:03d}"
    merged["id"] = dec_id
    merged["decision_id"] = n
    merged.setdefault("created_timestamp", now_iso)
    merged["last_updated_timestamp"] = now_iso

    for _col, _validator in _load_write_time_validators("ops_decisions"):
        _validator(merged.get(_col), _col)

    Decision.model_validate(merged)

    response = _ducklake_write("ops_decisions", merged, action="write_ops", profile=profile)
    logger.info("[PORTAL] Filed decision %s: %s", dec_id, merged.get("title", ""))
    _refresh_cache_after_write("ops_decisions", merged, response, DECISIONS_JSONL, append_only=_skip_sync)
    return dec_id


def _fetch_decision_from_reader(decision_id: str, profile: Optional[str] = None) -> Optional[dict]:
    """Fetch a single ops_decisions record by id via the decision_by_id read verb.

    Closed boundary (Decision 84 I-1/I-3): decisions read from DuckLake like every migrated
    ops table; the Athena fallback retired with the estate. Decision 69: raises on reader
    failure; never returns cache. Returns the coerced record dict or None if not found.
    """
    if not re.fullmatch(r"dec-\d+", decision_id):
        raise ValueError(f"_fetch_decision_from_reader: invalid decision_id: {decision_id!r}")

    from scripts.sync_ops import _coerce_ops_decisions_row  # noqa: PLC0415
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    rows = make_reader(profile=profile).named("decision_by_id", id=decision_id)
    if not rows:
        return None
    rec = _coerce_ops_decisions_row(dict(rows[0]))
    return _sanitize_athena_record(rec) if rec is not None else None


# Back-compat alias: read-engine.yaml's single_portal_invariant names the historical symbol.
_fetch_decision_from_athena = _fetch_decision_from_reader


def update_decision(decision_id: str, updates: dict, profile: Optional[str] = None) -> bool:
    """Merge update fields into an existing decision via the DuckLake writer.

    Reads the current record through the decision_by_id verb, merges updates,
    validates, and writes via update_ops (in-transaction referential check).

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
    existing = _fetch_decision_from_reader(decision_id, profile=profile)
    if existing is None:
        raise RuntimeError(
            f"update_decision: {decision_id} does not exist in the current projection -- an absent decision "
            "cannot be updated (referential, CD.33 cl.8 / D-5). File it first via file_decision."
        )
    merged = {**existing, **updates}
    merged["id"] = decision_id

    Decision.model_validate(merged)

    response = _ducklake_write("ops_decisions", merged, action="update_ops", profile=profile)
    logger.info("[PORTAL] Updated %s: %s", decision_id, list(updates.keys()))
    _refresh_cache_after_write("ops_decisions", merged, response, DECISIONS_JSONL)
    return True


def backfill_decisions_from_md(profile: Optional[str] = None) -> dict:
    """ETL DECISIONS.md -> ops_decisions (premise P3: the markdown is the source of truth).

    Idempotent: each entry is a caller-keyed write_ops upsert on dec-{n:03d}, so re-running
    refreshes current rows (one SCD2 append per run) instead of duplicating.

    Returns:
        {"written": N, "failed": M, "skipped": K}
    """
    from scripts.decisions_md import parse_decisions_md  # noqa: PLC0415
    from scripts.sync_ops import _coerce_athena_array  # noqa: PLC0415

    written = failed = skipped = 0
    for entry in parse_decisions_md():
        try:
            n = int(str(entry.get("decision_id", "")).strip())
        except ValueError:
            n = 0
        if n <= 0:
            skipped += 1
            continue
        fields = {k: v for k, v in entry.items() if k in _DECISION_BACKFILL_COLS and v not in (None, "")}
        # Archive entries may carry no status marker; the column is non-nullable, so be honest.
        fields.setdefault("status", "unspecified")
        if "related_decisions" in fields:
            fields["related_decisions"] = _coerce_athena_array(fields["related_decisions"], elem_type=int)
        try:
            file_decision(fields, profile=profile, _migration_int_id=n, _skip_sync=True)
            written += 1
        except Exception as exc:  # noqa: BLE001 -- per-row isolation; the summary surfaces failures
            logger.warning("[PORTAL] backfill_decisions_from_md: dec-%03d failed: %s", n, exc)
            failed += 1
    if written:
        _sync_table("ops_decisions")
    return {"written": written, "failed": failed, "skipped": skipped}


def sync(tables: Optional[list] = None) -> dict:
    """Pull the local read-cache fresh from the DuckLake reader (the single flush primitive).

    Args:
        tables: Ops table names to sync. Defaults to ops_recommendations,
                ops_decisions, ops_priority_queue.

    Returns:
        {"pulled": {table: rows}}

    Raises:
        RuntimeError: If the reader boundary is unreachable.
    """
    from scripts.sync_ops import _pull_single_table  # noqa: PLC0415

    ops_tables = tables or ["ops_recommendations", "ops_decisions", "ops_priority_queue"]

    # Every migrated table is a live `current` projection behind the atomic catalog commit
    # (Decision 84 I-1): a cache pull per table is the whole job -- no drain/compact/view-refresh.
    pulled: dict[str, int] = {table: _pull_single_table(table) for table in ops_tables}
    return {"pulled": pulled}


def selftest_read(table: str = "ops_recommendations", profile: Optional[str] = None) -> dict:
    """Read a sample row from *table* via the ACTIVE backend's reader (VP14 rollback rehearsal).

    Proves the DuckLake read path serves rows (the boundary is the sole backend, Decision 84).
    Returns {"backend": ..., "table": ..., "row_count": ..., "sample_id": ...}.
    """
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    backend = "ducklake"
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

    backend = "ducklake"
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

    # ops_recommendations always routes to DuckLake (Decision 81 cl.7 / T2.19).
    _ducklake_write("ops_recommendations", record, action="write_ops", profile=profile)

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


def purge_postmortems_for(failed_rec_id: str, dry_run: bool = False, profile: Optional[str] = None) -> dict:
    """Supersede all executor postmortems for failed_rec_id and decline the rec itself.

    SCD2 deletion model (Decision 84): postmortems become status=superseded via update_rec --
    no DML DELETE, no local-JSONL rewrite. The cache refresh after each update reflects the
    new current rows; history retains the full audit trail.

    Returns:
        {"matched": [rec ids], "superseded": N}
    """
    if not re.fullmatch(r"rec-\d+", failed_rec_id):
        raise ValueError(f"Invalid rec ID for purge: {failed_rec_id!r}. Must match rec-\\d+.")

    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    title_prefix = f"Investigate executor failure for {failed_rec_id}"
    rows = make_reader(profile=profile).named("recs_by_title_prefix", title_prefix=f"{title_prefix}%")
    id_re = re.compile(rf"Investigate executor failure for {re.escape(failed_rec_id)}(?![0-9])")
    matched = [
        r["id"]
        for r in rows
        if r.get("source") == "executor-postmortem"
        and r.get("status") != "superseded"
        and id_re.match(r.get("title", ""))  # LIKE 'rec-1%' also matches rec-10/rec-1NN -- re-filter exactly
    ]
    result: dict = {"matched": matched, "superseded": 0}

    if dry_run:
        logger.info("[PURGE] Dry-run for %s: %d postmortems would be superseded.", failed_rec_id, len(matched))
        return result

    for rec_id in matched:
        update_rec(
            rec_id,
            {
                "status": "superseded",
                "resolution": f"Superseded via ops_data_portal --purge-postmortems-for {failed_rec_id}.",
            },
            profile=profile,
        )
        result["superseded"] += 1

    resolution = (
        f"SCP block prevents IAM/OIDC operations required by {failed_rec_id}. "
        "Executor postmortems superseded via ops_data_portal --purge-postmortems-for."
    )
    update_rec(failed_rec_id, {"status": "declined", "resolution": resolution}, profile=profile)

    logger.info("[PURGE] Complete for %s: %d postmortems superseded.", failed_rec_id, result["superseded"])
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
    action.add_argument(
        "--purge-postmortems-for", metavar="REC_ID", help="Supersede all executor postmortems for REC_ID (SCD2)"
    )
    action.add_argument(
        "--backfill-decisions-md",
        action="store_true",
        help="ETL DECISIONS.md -> ops_decisions on DuckLake (idempotent caller-keyed upsert)",
    )
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
        help="Refresh the local read-cache from the DuckLake reader",
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
    rec.add_argument(
        "--context-v2-json",
        dest="context_v2_json",
        default=None,
        help="JSON-encoded CiRcaContext dict to attach to a source=ci_rca rec",
    )

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
    dec.add_argument(
        "--decision-id",
        type=int,
        dest="decision_arg_id",
        help="DECISIONS.md-assigned integer number (numbering authority is DECISIONS.md, Decision 84)",
    )

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
        context_v2_parsed: dict | None = None
        if args.context_v2_json is not None:
            try:
                context_v2_parsed = json.loads(args.context_v2_json)
            except json.JSONDecodeError as exc:
                print(f"ERROR: --context-v2-json is not valid JSON: {exc}", file=sys.stderr)
                return 1
        try:
            rec_id = file_rec(fields, context_v2_json=context_v2_parsed, profile=args.profile)
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
        if not args.decision_arg_id:
            print("ERROR: --file-decision requires --decision-id (DECISIONS.md number)", file=sys.stderr)
            return 1
        dec_fields: dict = {
            "title": args.title,
            "status": args.decision_status,
            "decision_text": args.rationale,
            "decision_id": args.decision_arg_id,
        }
        try:
            decision_id = file_decision(dec_fields, profile=args.profile)
        except (ValidationError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
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

    if args.backfill_decisions_md:
        result = backfill_decisions_from_md(profile=args.profile)
        print(json.dumps(result))
        return 0 if result.get("failed", 0) == 0 else 1

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

        guidance = get_rec_write_guidance(source=args.source)
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
