"""Unified JSONL read/write for the recommendation executor.

Centralises all access to logs/.recommendations-log.jsonl and
logs/.execution-plans.jsonl so encoding, atomic writes, and comment-line
handling are consistent across every caller.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scripts.s3_log_store import get_backend, read_jsonl

logger = logging.getLogger(__name__)


class Recommendation(BaseModel):
    """Pydantic v2 model for recommendation JSONL entries.

    Enforces canonical IDs (rec-, agent-, test-). Unknown fields (including
    Decision-56-deprecated columns that still appear in legacy Iceberg rows) are
    silently ignored so backward-compat reads do not fail.
    """

    id: str = Field(..., description="Recommendation ID matching rec-\\d+, agent-\\d+ or test-\\d+")
    title: Optional[str] = Field(None, description="Concise title")
    source: Optional[str] = Field(None, description="Origin: executor-supervision, code-review, planning, brainstorm")
    effort: Optional[str] = Field(None, description="Effort estimation (XS, S, M, L, XL)")
    priority: Optional[str] = Field(None, description="Priority level (Critical, High, Medium, Low)")
    status: Literal["open", "closed", "failed", "declined", "superseded"] = Field(
        ..., description="Lifecycle state; portal-enforced domain"
    )
    automatable: Optional[bool] = Field(None, description="Can the executor handle this?")
    risk: Optional[str] = Field(None, description="Risk level: low, medium, or high (portal-derived from file + effort)")
    file: Optional[str] = Field(None, description="Primary target file")
    context: Optional[str] = Field(None, description="Why this rec exists")
    acceptance: Optional[str] = Field(None, description="Shell command that returns 0 on success")
    verification: Optional[str] = Field(None, description="Behavioural shell command for end-to-end proof")
    verification_tier: Optional[str] = Field(None, description="V1=static, V2=unit, V3=integration")
    dependencies: Optional[list[str]] = Field(None, description="Array of blocking rec IDs")
    tags: Optional[list[str]] = Field(None, description="Categorisation tags")
    resolution: Optional[str] = Field(None, description="Why declined/superseded")
    execution_result: Optional[str] = Field(None, description="success|failure|manual|already_implemented|compound")
    execution_date: Optional[str] = Field(None, description="ISO-8601 execution date")
    execution_branch: Optional[str] = Field(None, description="Branch used for execution")
    execution_pr_url: Optional[str] = Field(None, description="URL of the created PR")
    execution_steps: Optional[int] = Field(None, description="Number of execution steps")

    # SCD2 timestamps managed by OpsWriter; row deduplication is view-only and must not appear in base table writes.
    created_timestamp: Optional[str] = Field(None, description="SCD2 creation timestamp")
    last_updated_timestamp: Optional[str] = Field(None, description="SCD2 update timestamp")

    # extra='ignore': silently drops Decision-56-deprecated fields (date, failure_step, failure_reason,
    # execution_steps_attempted, execution_steps_total, ingested_at, rn, trade_date) from legacy rows.
    model_config = ConfigDict(extra="ignore")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Ensure ID starts with rec-, agent-, or test- prefix. dec- is forbidden."""
        if not v:
            raise ValueError("ID cannot be empty")
        val = str(v).strip()
        if not (val.startswith("rec-") or val.startswith("agent-") or val.startswith("test-")):
            raise ValueError(f"Invalid ID prefix: {val}. Must be rec-, agent-, or test-.")
        return val


RECS_JSONL = Path("logs/.recommendations-log.jsonl")
PLANS_JSONL = Path("logs/.execution-plans.jsonl")
DECISIONS_JSONL = Path("logs/.decisions-index.jsonl")

# S3 key for recommendations (used when S3_LOG_BUCKET is set)
S3_RECS_KEY = "recommendations/recommendations.jsonl"

# Fields removed from a rec when it is reset to 'open'
_FAILURE_FIELDS = (
    "execution_result",
    "execution_date",
    "execution_branch",
)

# Valid status values for recommendations.
_VALID_STATUSES = {"open", "closed", "failed", "declined", "superseded"}


def load_recommendation(rec_id: str) -> Optional[dict]:
    """Load a recommendation by ID from JSONL.

    Returns the last matching entry (last-wins JSONL append semantics), or
    None if not found or on error.  When a rec is updated via append, the
    last occurrence reflects the most recent state.
    Uses S3 backend when S3_LOG_BUCKET is set, otherwise reads local file.

    Example:
        rec = load_recommendation("rec-001")
        val = rec.get("date") if rec else None
    """
    if get_backend() == "s3":
        entries = read_jsonl(S3_RECS_KEY)
        result = None
        for entry in entries:
            if entry.get("id") == rec_id:
                result = entry
        if result is not None:
            return result
        logger.warning("Recommendation %s not found in S3 JSONL", rec_id)
        return None
    try:
        lines = RECS_JSONL.read_text(encoding="utf-8").splitlines()
        result = None
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if entry.get("id") == rec_id:
                result = entry
        if result is not None:
            return result
        logger.warning("Recommendation %s not found in JSONL", rec_id)
        return None
    except FileNotFoundError:
        logger.error("JSONL file not found at %s", RECS_JSONL)
        return None
    except OSError as e:
        logger.error("Error loading recommendation: %s", e)
        return None


def load_all_recommendations() -> dict[str, dict]:
    """Load all recommendations from JSONL into a dict keyed by id.

    Skips schema comment lines and blank lines.
    Uses S3 backend when S3_LOG_BUCKET is set, otherwise reads local file.

    Returns:
        dict mapping rec ID (e.g. 'rec-009') to full entry dict.
        Returns empty dict if file is missing or unreadable.
    """
    result: dict[str, dict] = {}
    if get_backend() == "s3":
        for entry in read_jsonl(S3_RECS_KEY):
            rec_id = entry.get("id")
            if rec_id:
                result[rec_id] = entry
        return result
    try:
        lines = RECS_JSONL.read_text(encoding="utf-8").splitlines()
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
                result[rec_id] = entry
    except FileNotFoundError:
        logger.warning("JSONL file not found: %s", RECS_JSONL)
    except OSError as e:
        logger.error("Error reading JSONL: %s", e)
    return result


def update_recommendation_status(rec_id: str, updates: dict) -> bool:
    """Merge update fields into an existing recommendation via the ops data portal.

    Delegates to scripts.ops_data_portal.update_rec() which handles
    DynamoDB-allocated IDs, Pydantic validation, OpsWriter S3 staging, and
    local JSONL write-through in one atomic operation.

    Args:
        rec_id: Recommendation ID to update (e.g., 'rec-042')
        updates: Fields to merge into the existing entry

    Returns:
        True on success, False on error.

    Raises:
        ValueError: If 'status' in updates is not a valid status value.
        ValidationError: If the merged record fails schema validation.
    """
    from scripts.ops_data_portal import update_rec  # noqa: PLC0415

    return update_rec(rec_id, updates)


def _reset_rec_status(rec_id: str) -> None:
    """Reset a rec's status back to 'open', removing execution failure fields.

    Called by --restart so a previously-failed rec is eligible again.
    Delegates to scripts.ops_data_portal.update_rec() for centralised write path.
    Silently skips on error (best-effort for restart flow).
    """
    from scripts.ops_data_portal import update_rec  # noqa: PLC0415

    reset_updates: dict = {"status": "open"}
    for f in _FAILURE_FIELDS:
        reset_updates[f] = None  # OpsWriter last-wins; None fields clear them in Iceberg

    try:
        update_rec(rec_id, reset_updates)
        logger.info("[RESTART] Reset %s status to 'open' via portal", rec_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[RESTART] Could not reset status for %s: %s", rec_id, exc)


def get_next_rec_id() -> str:  # pragma: no cover
    """DEPRECATED: Use scripts.ops_data_portal.file_rec() which allocates IDs via DynamoDB.

    Local ID allocation from scanning JSONL is unsafe in multi-agent environments
    and has been replaced by DynamoDB atomic counters. This function raises a
    DeprecationWarning and falls back to the portal.

    Raises:
        DeprecationWarning: Always. Indicates a caller still using the old path.
    """
    import warnings  # noqa: PLC0415

    warnings.warn(
        "get_next_rec_id() is deprecated and disabled (Decision 84 I-2): the ducklake_writer "
        "allocates ids atomically with the insert. Use scripts.ops_data_portal.file_rec().",
        DeprecationWarning,
        stacklevel=2,
    )
    raise RuntimeError(
        "get_next_rec_id() is retired (Decision 84 I-2): client-side id allocation is forbidden -- "
        "the ducklake_writer owns the rec-NNN keyspace. File via ops_data_portal.file_rec()."
    )


def _create_postmortem_recommendation(failed_rec_id: str, branch: str, ci_attempts: int) -> None:
    """Create a postmortem recommendation for an executor failure via the ops data portal.

    Deduplicates: if an open postmortem for failed_rec_id already exists in the
    local JSONL, updates its context with an incremented attempt counter instead
    of filing a new record.

    Args:
        failed_rec_id: The rec that failed (included in the postmortem title).
        branch: The feature branch that was cleaned up after the failure.
        ci_attempts: Number of CI fix attempts that were made before giving up.
    """
    from scripts.ops_data_portal import find_open_postmortem_for  # noqa: PLC0415

    existing = find_open_postmortem_for(failed_rec_id)
    if existing:
        from scripts.ops_data_portal import update_rec  # noqa: PLC0415

        now_iso = datetime.now(timezone.utc).isoformat()
        ctx = existing.get("context", "")
        attempt_count = ctx.count("; attempt ") + 2
        try:
            update_rec(
                existing["id"],
                {
                    "context": ctx + f"; attempt {attempt_count} at {now_iso}",
                    "last_updated_timestamp": now_iso,
                },
            )
            logger.info("[POSTMORTEM] Deduped: updated existing %s for %s", existing["id"], failed_rec_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("[POSTMORTEM] Failed to update existing postmortem %s: %s", existing["id"], exc)
        return

    from scripts.ops_data_portal import file_rec  # noqa: PLC0415

    postmortem_fields: dict = {
        "title": f"Investigate executor failure for {failed_rec_id}",
        "source": "executor-postmortem",
        "effort": "S",
        "priority": "High",
        "status": "open",
        "automatable": False,
        "risk": "low",
        "file": "scripts/execute_recommendation.py",
        "context": (
            f"Executor failed to complete {failed_rec_id} after {ci_attempts} CI fix attempt(s). "
            f"Feature branch {branch} was cleaned up. "
            "Review logs/transcripts/ for detailed failure context."
        ),
        "acceptance": f"grep -q '{failed_rec_id}' logs/.recommendations-log.jsonl",
    }

    try:
        new_id = file_rec(postmortem_fields)
        logger.info("[POSTMORTEM] Created %s: investigate failure for %s", new_id, failed_rec_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("[POSTMORTEM] Failed to file postmortem rec: %s", exc)


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via a temp file.

    Uses explicit ``newline='\\n'`` to prevent \\r\\n on Windows.
    Ensures the file ends with a single newline.
    Retries up to 3 times on Windows file-in-use errors.
    """
    if not content.endswith("\n"):
        content += "\n"
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(content, encoding="utf-8", newline="\n")
        for attempt in range(3):
            try:
                tmp.replace(path)
                return
            except PermissionError as e:
                if attempt < 2:
                    time.sleep(0.05)
                else:
                    raise OSError(f"Failed to replace {path} after 3 attempts: {e}") from e
    except OSError:
        if tmp.exists():
            tmp.unlink()
        raise


_DECISION_ID_RE = re.compile(r"^dec-\d+$")


class Decision(BaseModel):
    """Pydantic v2 model for ops_decisions JSONL entries.

    Dual-write invariant: when both id and decision_id are present,
    int(id.split('-')[1]) must equal decision_id. A mismatch raises
    ValidationError -- Phase 6 column drop depends on this holding for every row.
    """

    id: str = Field(..., description="Decision ID matching dec-\\d+")
    title: str
    status: str
    created_timestamp: str
    last_updated_timestamp: str
    problem: Optional[str] = None
    decision_text: Optional[str] = None
    context: Optional[str] = None
    decided_date: Optional[str] = None
    related_decisions: Optional[list[int]] = None
    related_decisions_v2: Optional[list[str]] = None
    decision_id: Optional[int] = None
    # DAF-01 parity backstop (PLAN-daf-etl-parity-fidelity, Decision 134 cl.4) plus intent
    # (PLAN-dcg-intent-capture, Decision 151, audit finding DCG-06). Plain Optional[str] --
    # NEVER Annotated[...]/DqNotNull/any Dq* marker; hand-synced counterpart of
    # src/schemas/decision.py::DecisionPayload's same fields (see that file's comment for the
    # drift-check rationale).
    raw_block: Optional[str] = None
    reversal_conditions: Optional[str] = None
    superseded_by: Optional[str] = None
    content_hash: Optional[str] = None
    intent: Optional[str] = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        if not _DECISION_ID_RE.match(v):
            raise ValueError(f"Decision ID must match ^dec-\\d+$: {v!r}")
        return v

    @model_validator(mode="after")
    def validate_dual_write(self) -> "Decision":
        if self.id is not None and self.decision_id is not None:
            expected = int(self.id.split("-")[1])
            if expected != self.decision_id:
                raise ValueError(
                    f"Dual-write invariant violated: id={self.id!r} implies decision_id={expected}, "
                    f"but got decision_id={self.decision_id}"
                )
        return self


def load_decision(decision_id: str | int) -> Optional[dict]:
    """Load a decision by id (dec-NNN) or legacy int from DECISIONS_JSONL.

    Resolves either form to the same row. Returns the last matching entry
    (last-wins JSONL append semantics), or None if not found.
    """
    if isinstance(decision_id, int):
        target_id = f"dec-{decision_id:03d}"
    else:
        s = str(decision_id).strip()
        if _DECISION_ID_RE.match(s):
            target_id = s
        else:
            try:
                target_id = f"dec-{int(s):03d}"
            except ValueError:
                target_id = s
    result: Optional[dict] = None
    try:
        lines = DECISIONS_JSONL.read_text(encoding="utf-8").splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if entry.get("id") == target_id:
                result = entry
        return result
    except FileNotFoundError:
        logger.warning("Decisions JSONL not found at %s", DECISIONS_JSONL)
        return None
    except OSError as e:
        logger.error("Error loading decision: %s", e)
        return None


def load_all_decisions() -> dict[str, dict]:
    """Load all decisions from DECISIONS_JSONL into a dict keyed by id.

    Uses last-wins semantics: if the same id appears multiple times, the last
    occurrence (most recent SCD2 append) is kept. Returns empty dict if file
    is missing or unreadable.
    """
    result: dict[str, dict] = {}
    try:
        lines = DECISIONS_JSONL.read_text(encoding="utf-8").splitlines()
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            dec_id = entry.get("id")
            if dec_id:
                result[dec_id] = entry
    except FileNotFoundError:
        logger.warning("Decisions JSONL not found: %s", DECISIONS_JSONL)
    except OSError as e:
        logger.error("Error reading decisions JSONL: %s", e)
    return result
