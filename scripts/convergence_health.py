"""CD-convergence health sensor (CD.35 Wave 6 / T2.35).

Reads convergence/personal/sandbox.json from S3, derives red_since and
red_age_hours, counts merged terraform/personal/ commits since the record's
commit_sha, and queries GitHub Actions for stuck gated-apply approvals.

Provides an idempotent escalation path: files OR updates a single
tf_convergence_stale rec per red-episode via scripts.ops_data_portal
(file_rec / update_rec). Never writes the convergence record; never runs
terraform apply; never dispatches terraform-apply-sandbox.

All external dependencies (S3 client, git runner, GitHub API caller, portal
caller) are injected so unit tests can mock them without live AWS.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

CONVERGENCE_BUCKET = "agent-platform-data-lake"
CONVERGENCE_KEY = "convergence/personal/sandbox.json"

RED_AGE_THRESHOLD_HOURS: float = 6.0
STUCK_APPROVAL_THRESHOLD_HOURS: float = 6.0


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class HealthVerdict:
    status: str  # "green" | "red" | "unknown"
    red_age_hours: float
    unapplied_backlog: int
    stuck_approvals: list[dict[str, Any]] = field(default_factory=list)
    severity: str = "none"  # "none" | "low" | "high"


# ---------------------------------------------------------------------------
# Low-level helpers (all testable via injection)
# ---------------------------------------------------------------------------


def read_convergence_record(
    s3_client: Any,
    bucket: str = CONVERGENCE_BUCKET,
    key: str = CONVERGENCE_KEY,
) -> Optional[dict[str, Any]]:
    """Read the convergence record from S3; return None on NoSuchKey or missing object."""
    import json  # noqa: PLC0415

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        body = response["Body"].read()
        return json.loads(body)
    except Exception as exc:  # noqa: BLE001
        exc_str = str(exc) + type(exc).__name__
        if any(marker in exc_str for marker in ("NoSuchKey", "404", "NoSuchBucket")):
            return None
        raise


def derive_red_since(record: dict[str, Any]) -> datetime:
    """Return the datetime when the record entered the current red episode.

    Uses drift_detected_at when present -- a drift-flip preserves the prior
    green timestamp in the bare 'timestamp' field, so timestamp understates
    red-age on a drift-flip. Falls back to 'timestamp'.
    """
    raw = record.get("drift_detected_at") or record.get("timestamp") or ""
    return _parse_utc(raw)


def red_age_hours(record: dict[str, Any], now: Optional[datetime] = None) -> float:
    """Return how many hours the record has been red (0.0 if green or unknown)."""
    if record.get("status") != "red":
        return 0.0
    if now is None:
        now = datetime.now(timezone.utc)
    since = derive_red_since(record)
    delta = now - since
    return max(0.0, delta.total_seconds() / 3600.0)


def _parse_utc(ts: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp to a timezone-aware datetime."""
    ts = ts.rstrip("Z")
    if not ts:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)


def count_unapplied_tf_commits(
    commit_sha: str,
    git_runner: Optional[Callable[[list[str]], str]] = None,
) -> int:
    """Count merged terraform/personal/** commits since commit_sha via git log.

    Returns 0 on any error (record SHA may predate the current clone depth).
    """
    if not commit_sha:
        return 0

    def _default_runner(cmd: list[str]) -> str:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip()

    runner = git_runner or _default_runner
    try:
        output = runner(
            [
                "git",
                "log",
                f"{commit_sha}..HEAD",
                "--oneline",
                "--",
                "terraform/personal/",
            ]
        )
        if not output:
            return 0
        return len([line for line in output.splitlines() if line.strip()])
    except Exception:  # noqa: BLE001
        return 0


def filter_stuck_runs(
    runs: list[dict[str, Any]],
    threshold_hours: float,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Filter and parse run dicts whose age_hours >= threshold_hours.

    Pure: no network calls, no external dependencies. Shared by find_stuck_gated_approvals
    (status=waiting query) and diagnose_stuck_approvals (any-status diagnostic query).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    stuck: list[dict[str, Any]] = []
    for run in runs:
        created_at_str = run.get("created_at", "")
        if not created_at_str:
            continue
        created_at = _parse_utc(created_at_str)
        age_hours = (now - created_at).total_seconds() / 3600.0
        if age_hours >= threshold_hours:
            stuck.append(
                {
                    "run_id": run.get("id"),
                    "created_at": created_at_str,
                    "age_hours": round(age_hours, 1),
                    "url": run.get("html_url"),
                }
            )
    return stuck


def _make_github_caller(token: str) -> Callable[[str], Any]:
    """Return an authenticated GitHub API caller bound to token, or a no-op returning None.

    Shared by find_stuck_gated_approvals and diagnose_stuck_approvals so auth header
    construction is defined exactly once. Imports are deferred to avoid import-time side effects.
    """
    import json as _json  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    def _caller(url: str) -> Any:
        if not token:
            return None
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            return _json.loads(resp.read())

    return _caller


def find_stuck_gated_approvals(
    gh_caller: Optional[Callable[[str], Any]] = None,
    owner: str = "benjamin-blake",
    repo: str = "agent-platform",
    threshold_hours: float = STUCK_APPROVAL_THRESHOLD_HOURS,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Return terraform-apply-sandbox runs whose gated-apply job is `waiting` beyond threshold.

    gh_caller is injected for testability. When None, reads GH_TOKEN / GITHUB_TOKEN env vars;
    if neither is set, returns [] without error (graceful degradation).
    """
    import os  # noqa: PLC0415

    if now is None:
        now = datetime.now(timezone.utc)

    token = os.environ.get("GH_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    caller = gh_caller or _make_github_caller(token)

    try:
        url = (
            f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/"
            f"terraform-apply-sandbox.yml/runs?status=waiting&per_page=10"
        )
        data = caller(url)
        if not data:
            return []
        return filter_stuck_runs(data.get("workflow_runs", []), threshold_hours, now)
    except Exception:  # noqa: BLE001
        pass
    return []


def find_reconcile_runs_since(
    gh_caller: Optional[Callable[[str], Any]] = None,
    owner: str = "benjamin-blake",
    repo: str = "agent-platform",
    per_page: int = 10,
) -> list[dict[str, Any]]:
    """Query recent .github/workflows/reconcile.yml Actions runs (any status), newest first.

    T2.37 c4: this is the signal used to detect an in-flight/recent Reconcile episode so the
    stale-rec escalation below does not double-file. gh_caller is injected for testability, same
    pattern as find_stuck_gated_approvals / diagnose_stuck_approvals. Returns [] on any error, a
    None caller result, or a missing GH_TOKEN/GITHUB_TOKEN -- graceful degradation, since this
    signal only ever SUPPRESSES a file action, it never itself triggers escalation.
    """
    import os  # noqa: PLC0415

    token = os.environ.get("GH_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    caller = gh_caller or _make_github_caller(token)

    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/reconcile.yml/runs?per_page={per_page}"
        data = caller(url)
        if not data:
            return []
        return data.get("workflow_runs", []) or []
    except Exception:  # noqa: BLE001
        pass
    return []


def has_in_flight_reconcile_for_episode(
    runs: list[dict[str, Any]],
    red_since: datetime,
    now: Optional[datetime] = None,
) -> bool:
    """True iff any reconcile.yml run's created_at falls within [red_since, now].

    That window IS "in-flight/recent... within the current red episode window" (T2.37 c4): a
    Reconcile dispatch that started (or already completed) after this episode went red is
    evidence the episode is already being worked, regardless of whether that run is still
    running right now. Deliberately NOT matched by head_sha equality -- a workflow_dispatch run's
    head_sha is the branch tip at dispatch time and will not reliably equal the red commit once
    later commits merge onto main. Pure / injectable: `runs` is normally
    find_reconcile_runs_since()'s output, but tests pass a literal list directly.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    for run in runs:
        created_at_str = run.get("created_at", "")
        if not created_at_str:
            continue
        created_at = _parse_utc(created_at_str)
        if red_since <= created_at <= now:
            return True
    return False


def diagnose_stuck_approvals(
    gh_caller: Optional[Callable[[str], Any]] = None,
    owner: str = "benjamin-blake",
    repo: str = "agent-platform",
    threshold_hours: float = 0.0,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Query recent terraform-apply-sandbox runs of ANY status and parse them via filter_stuck_runs.

    Read-only diagnostic entrypoint: exercises the real-data parse path without requiring a live
    waiting run. At threshold_hours=0 every run object is parsed and returned. Returns [] on any
    error or when the caller yields None. Never escalates or writes.
    """
    import os  # noqa: PLC0415

    if now is None:
        now = datetime.now(timezone.utc)

    token = os.environ.get("GH_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")
    caller = gh_caller or _make_github_caller(token)

    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/terraform-apply-sandbox.yml/runs?per_page=20"
        data = caller(url)
        if not data:
            return []
        return filter_stuck_runs(data.get("workflow_runs", []), threshold_hours, now)
    except Exception:  # noqa: BLE001
        pass
    return []


# ---------------------------------------------------------------------------
# Escalation decision (pure; injectable in tests)
# ---------------------------------------------------------------------------


def escalation_action(over_threshold: bool, open_rec_exists: bool) -> str:
    """Return the action to take given red-age and existing-rec state.

    Returns:
        "file"   -- new rec should be filed (over threshold, no open rec yet)
        "update" -- existing open rec should be updated (still over threshold)
        "close"  -- existing open rec should be closed (under threshold / green)
        "none"   -- nothing to do (under threshold, no open rec)
    """
    if over_threshold and not open_rec_exists:
        return "file"
    if over_threshold and open_rec_exists:
        return "update"
    if not over_threshold and open_rec_exists:
        return "close"
    return "none"


# ---------------------------------------------------------------------------
# Health assessment
# ---------------------------------------------------------------------------


def assess_health(
    record: Optional[dict[str, Any]],
    stuck_approvals: Optional[list[dict[str, Any]]] = None,
    git_runner: Optional[Callable[[list[str]], str]] = None,
    now: Optional[datetime] = None,
) -> HealthVerdict:
    """Derive a HealthVerdict from the convergence record and supplementary signals."""
    if record is None:
        return HealthVerdict(
            status="unknown",
            red_age_hours=0.0,
            unapplied_backlog=0,
            stuck_approvals=[],
            severity="none",
        )

    status = record.get("status", "unknown")
    age = red_age_hours(record, now=now)
    backlog = count_unapplied_tf_commits(
        record.get("commit_sha", ""),
        git_runner=git_runner,
    )
    approvals = stuck_approvals or []

    if status != "red":
        severity = "none"
    elif age >= RED_AGE_THRESHOLD_HOURS or approvals:
        severity = "high"
    else:
        severity = "low"

    return HealthVerdict(
        status=status,
        red_age_hours=round(age, 2),
        unapplied_backlog=backlog,
        stuck_approvals=approvals,
        severity=severity,
    )


# ---------------------------------------------------------------------------
# Idempotent escalation
# ---------------------------------------------------------------------------


def find_open_convergence_stale_rec(
    open_recs: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Return the first open tf_convergence_stale rec from a list of open recs, or None."""
    for rec in open_recs:
        if rec.get("source") == "tf_convergence_stale" and rec.get("status") == "open":
            return rec
    return None


def _fetch_open_recs(profile: Optional[str] = None) -> list[dict[str, Any]]:
    """Fetch all open recs from the DuckLake reader (live, never the local JSONL cache)."""
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    return make_reader(profile=profile).named("open_recs") or []


def _build_context(verdict: HealthVerdict) -> str:
    parts = [
        f"The sandbox convergence record has been red for {verdict.red_age_hours:.1f} hours.",
    ]
    if verdict.unapplied_backlog:
        parts.append(
            f"{verdict.unapplied_backlog} merged terraform/personal/ commit(s) are pending "
            "application since the last green convergence commit."
        )
    if verdict.stuck_approvals:
        parts.append(
            f"{len(verdict.stuck_approvals)} terraform-apply-sandbox run(s) are waiting on "
            "the tf-gated-apply Environment approval (stuck > threshold). Check GitHub "
            "Actions -> Review pending deployments to approve or cancel."
        )
    parts.append(
        "Resolve via: (a) approve the pending gated-apply run in GitHub Actions, or "
        "(b) run terraform-apply-sandbox workflow_dispatch with acknowledge_red_commit "
        "naming the red commit SHA. This rec closes automatically on the next sensor "
        "tick once the convergence record returns to green."
    )
    return " ".join(parts)


def _build_rec_fields(verdict: HealthVerdict) -> dict[str, Any]:
    return {
        "title": "Sandbox convergence record persistently red -- staleness escalation",
        "file": ".github/workflows/convergence-health.yml",
        "status": "open",
        "source": "tf_convergence_stale",
        "priority": "High",
        "effort": "S",
        "risk": "medium",
        "verification_tier": "V2",
        "context": _build_context(verdict),
        "acceptance": (
            "terraform-apply-sandbox workflow_dispatch converges successfully (writes a green "
            "convergence record) and this rec is closed via the standard portal path "
            "(update_rec --status closed, or a Resolves: trailer when a fix PR lands)."
        ),
    }


def escalate(
    verdict: HealthVerdict,
    portal_caller: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    open_recs: Optional[list[dict[str, Any]]] = None,
    threshold_hours: float = RED_AGE_THRESHOLD_HOURS,
    profile: Optional[str] = None,
    reconcile_in_flight: bool = False,
) -> dict[str, Any]:
    """Idempotent escalation: file/update/close exactly one tf_convergence_stale rec per episode.

    Args:
        verdict:       HealthVerdict from assess_health.
        portal_caller: Injected callable(action, fields) for testability. When None,
                       uses scripts.ops_data_portal.file_rec / update_rec directly.
        open_recs:     Pre-fetched open rec list (for testing). When None, fetches live
                       via the DuckLake reader open_recs named verb (not the JSONL cache).
        threshold_hours: Red-age threshold triggering escalation.
        profile:       AWS profile for the reader / portal.
        reconcile_in_flight: T2.37 c4 -- True when a reconcile.yml Actions run has already
                       started (or completed) during the current red episode (see
                       has_in_flight_reconcile_for_episode). Suppresses ONLY a fresh "file"
                       action -- an already-open rec still updates/closes normally, since
                       refreshing an existing rec's context is not a double-file.

    Returns:
        {"action": "file"|"update"|"close"|"none"|"skipped"|"skipped_reconcile_in_flight", "rec_id": str|None}
    """
    if open_recs is None:
        open_recs = _fetch_open_recs(profile=profile)

    existing = find_open_convergence_stale_rec(open_recs)
    open_rec_exists = existing is not None
    over_threshold = verdict.status == "red" and (verdict.red_age_hours >= threshold_hours or bool(verdict.stuck_approvals))

    action = escalation_action(over_threshold=over_threshold, open_rec_exists=open_rec_exists)

    if action == "file" and reconcile_in_flight:
        # T2.37 c4: a Reconcile dispatch already started (or completed) during this red episode --
        # do not double-file a NEW tf_convergence_stale rec for the episode Reconcile is already
        # clearing. The episode either resolves (record returns green, no rec ever needed) or the
        # reconcile run itself fails, and the next sensor tick re-evaluates from a clean slate.
        return {"action": "skipped_reconcile_in_flight", "rec_id": None}

    if action == "none":
        return {"action": "none", "rec_id": None}

    if action == "file":
        fields = _build_rec_fields(verdict)
        if portal_caller is not None:
            rec_id = portal_caller("file", fields)
        else:
            from scripts.ops_data_portal import file_rec  # noqa: PLC0415

            rec_id = file_rec(fields, profile=profile)
        return {"action": "file", "rec_id": rec_id}

    if action == "update" and existing is not None:
        updates = {"context": _build_context(verdict)}
        if portal_caller is not None:
            portal_caller("update", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "update", "rec_id": existing["id"]}

    if action == "close" and existing is not None:
        updates = {
            "status": "closed",
            "resolution": ("Convergence record returned to green; staleness episode resolved."),
        }
        if portal_caller is not None:
            portal_caller("close", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "close", "rec_id": existing["id"]}

    return {"action": "skipped", "rec_id": None}


# ---------------------------------------------------------------------------
# DuckLake code-drift alarm (T2.38 / Decision 125/126)
#
# Reads each of the four DuckLake functions' deploy records (scripts.build_lambda_deploy.
# read_deploy_record), resolves the latest main commit touching ducklake source paths via
# git_runner, and compares recorded source_git_sha against it. Mirrors escalate()'s idempotent
# file/update/close pattern, but ANY stale function triggers exactly ONE deduped
# ducklake_code_drift rec (never one per function). Never writes a deploy record; never
# redeploys; never runs build_lambda. Alarm-not-gate (priority High, never source=ci_rca).
# ---------------------------------------------------------------------------

DUCKLAKE_SOURCE_PATHSPECS: tuple[str, ...] = (
    "src/lambdas/ducklake_writer",
    "src/lambdas/ducklake_reader",
    "src/lambdas/ducklake_maintenance",
    "src/lambdas/ducklake_catalog_dr",
    "src/common/ducklake_*.py",
    "config/lambda/ducklake",
)


def find_open_ducklake_drift_rec(
    open_recs: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Return the first open ducklake_code_drift rec from a list of open recs, or None."""
    for rec in open_recs:
        if rec.get("source") == "ducklake_code_drift" and rec.get("status") == "open":
            return rec
    return None


def _build_ducklake_drift_context(stale_functions: list[str], latest_sha: str) -> str:
    fn_list = ", ".join(sorted(stale_functions))
    return (
        f"The following DuckLake Lambda function(s) have a deployed CodeSha256 whose recorded "
        f"source_git_sha does not match (or has no deploy record for) the latest main commit "
        f"touching ducklake source ({latest_sha[:12] if latest_sha else 'unknown'}): {fn_list}. "
        "Redeploy via the governed channel (.github/workflows/deploy-ducklake-lambdas.yml -- push "
        "to main touching ducklake source, or workflow_dispatch) to bring the deployed code "
        "current. This rec closes automatically on the next sensor tick once every function's "
        "deploy record matches the latest ducklake-source commit."
    )


def _build_ducklake_drift_rec_fields(stale_functions: list[str], latest_sha: str) -> dict[str, Any]:
    return {
        "title": "DuckLake Lambda code drift -- deployed code stale vs latest main",
        "file": ".github/workflows/deploy-ducklake-lambdas.yml",
        "status": "open",
        "source": "ducklake_code_drift",
        "priority": "High",
        "effort": "S",
        "risk": "medium",
        "verification_tier": "V2",
        "context": _build_ducklake_drift_context(stale_functions, latest_sha),
        "acceptance": (
            "the governed deploy-ducklake-lambdas workflow runs successfully against the stale "
            "function(s) and this rec is closed via the standard portal path (update_rec "
            "--status closed, or a Resolves: trailer when a fix PR lands)."
        ),
    }


def detect_ducklake_code_drift(
    git_runner: Optional[Callable[[list[str]], str]] = None,
    s3_client: Any = None,
    portal_caller: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    open_recs: Optional[list[dict[str, Any]]] = None,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotent ducklake code-drift alarm: file/update/close exactly one rec per episode.

    Args:
        git_runner:    Injected callable(argv) -> stdout, mirroring count_unapplied_tf_commits.
                       When None, shells out to the real git binary.
        s3_client:     Injected boto3-like S3 client passed through to read_deploy_record for
                       each of the four ducklake functions. When None, a real client is created
                       (never at import time).
        portal_caller: Injected callable(action, fields) for testability, mirroring escalate().
                       When None, uses scripts.ops_data_portal.file_rec / update_rec directly.
        open_recs:     Pre-fetched open rec list (for testing). When None, fetches live via the
                       DuckLake reader open_recs named verb (not the JSONL cache) -- mirrors
                       escalate()'s default.
        profile:       AWS profile for the reader / portal / S3 client.

    Returns:
        {"action": "file"|"update"|"close"|"none"|"skipped", "rec_id": str|None}
    """
    from scripts.build_lambda_config import _build_ducklake_function_zip_keys  # noqa: PLC0415
    from scripts.build_lambda_deploy import read_deploy_record  # noqa: PLC0415

    if s3_client is None:
        import boto3  # noqa: PLC0415

        s3_client = boto3.Session(profile_name=profile).client("s3")

    def _default_runner(cmd: list[str]) -> str:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip()

    runner = git_runner or _default_runner
    latest_sha = runner(["git", "log", "-1", "--format=%H", "--", *DUCKLAKE_SOURCE_PATHSPECS]).strip()

    stale_functions: list[str] = []
    for function in _build_ducklake_function_zip_keys():
        record = read_deploy_record(function, s3_client=s3_client)
        if record is None or record.get("source_git_sha") != latest_sha:
            stale_functions.append(function)

    if open_recs is None:
        open_recs = _fetch_open_recs(profile=profile)

    existing = find_open_ducklake_drift_rec(open_recs)
    open_rec_exists = existing is not None
    over_threshold = bool(stale_functions)

    action = escalation_action(over_threshold=over_threshold, open_rec_exists=open_rec_exists)

    if action == "none":
        return {"action": "none", "rec_id": None}

    if action == "file":
        fields = _build_ducklake_drift_rec_fields(stale_functions, latest_sha)
        if portal_caller is not None:
            rec_id = portal_caller("file", fields)
        else:
            from scripts.ops_data_portal import file_rec  # noqa: PLC0415

            rec_id = file_rec(fields, profile=profile)
        return {"action": "file", "rec_id": rec_id}

    if action == "update" and existing is not None:
        updates = {"context": _build_ducklake_drift_context(stale_functions, latest_sha)}
        if portal_caller is not None:
            portal_caller("update", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "update", "rec_id": existing["id"]}

    if action == "close" and existing is not None:
        updates = {
            "status": "closed",
            "resolution": (
                "All DuckLake deploy records match the latest main commit touching ducklake source; drift resolved."
            ),
        }
        if portal_caller is not None:
            portal_caller("close", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "close", "rec_id": existing["id"]}

    return {"action": "skipped", "rec_id": None}


# ---------------------------------------------------------------------------
# Prod-class code-drift alarm (T2.43 / Decision 125/126)
#
# Mirrors detect_ducklake_code_drift exactly, scoped to the three prod-class functions
# (scheduled-agent-dispatcher, findings-processor, ops-compaction) and their
# deploy-records/prod/<function>.json records (read_deploy_record channel="prod"). ANY stale
# function triggers exactly ONE deduped prod_code_drift rec (never one per function). Never
# writes a deploy record; never redeploys; never runs build_lambda. Alarm-not-gate (priority
# High, never source=ci_rca).
# ---------------------------------------------------------------------------

# Kept in sync with .github/workflows/deploy-prod-lambdas.yml's `on.push.paths` filter (single
# conceptual source per rec-2686 -- a path added to one must be added to the other) so the drift
# sensor's notion of "source changed" never diverges from what actually triggers a deploy.
PROD_SOURCE_PATHSPECS: tuple[str, ...] = (
    "src/data/handlers",
    "scripts/aws_profile.py",
    "scripts/github_models_client.py",
    "scripts/llm_client.py",
    "scripts/llm_utils.py",
    "scripts/ops_writer.py",
    "scripts/run_scheduled_agent.py",
    "scripts/s3_log_store.py",
    "scripts/telemetry_schemas.py",
    "scripts/tool_runtime.py",
    "config/lambda/data-pipeline",
    "config/lambda/ops-compaction",
)

_PROD_FUNCTION_NAMES: tuple[str, ...] = (
    "agent-platform-scheduled-agent-dispatcher",
    "agent-platform-findings-processor",
    "agent-platform-ops-compaction",
)


def find_open_prod_drift_rec(
    open_recs: list[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Return the first open prod_code_drift rec from a list of open recs, or None."""
    for rec in open_recs:
        if rec.get("source") == "prod_code_drift" and rec.get("status") == "open":
            return rec
    return None


def _build_prod_drift_context(stale_functions: list[str], latest_sha: str) -> str:
    fn_list = ", ".join(sorted(stale_functions))
    return (
        f"The following prod-class Lambda function(s) have a deployed CodeSha256 whose recorded "
        f"source_git_sha does not match (or has no deploy record for) the latest main commit "
        f"touching prod source ({latest_sha[:12] if latest_sha else 'unknown'}): {fn_list}. "
        "Redeploy via the governed channel (.github/workflows/deploy-prod-lambdas.yml -- push to "
        "main touching prod source, or workflow_dispatch) to bring the deployed code current. "
        "This rec closes automatically on the next sensor tick once every function's deploy "
        "record matches the latest prod-source commit."
    )


def _build_prod_drift_rec_fields(stale_functions: list[str], latest_sha: str) -> dict[str, Any]:
    return {
        "title": "Prod-class Lambda code drift -- deployed code stale vs latest main",
        "file": ".github/workflows/deploy-prod-lambdas.yml",
        "status": "open",
        "source": "prod_code_drift",
        "priority": "High",
        "effort": "S",
        "risk": "medium",
        "verification_tier": "V2",
        "context": _build_prod_drift_context(stale_functions, latest_sha),
        "acceptance": (
            "the governed deploy-prod-lambdas workflow runs successfully against the stale "
            "function(s) and this rec is closed via the standard portal path (update_rec "
            "--status closed, or a Resolves: trailer when a fix PR lands)."
        ),
    }


def detect_prod_code_drift(
    git_runner: Optional[Callable[[list[str]], str]] = None,
    s3_client: Any = None,
    portal_caller: Optional[Callable[[str, dict[str, Any]], Any]] = None,
    open_recs: Optional[list[dict[str, Any]]] = None,
    profile: Optional[str] = None,
) -> dict[str, Any]:
    """Idempotent prod-class code-drift alarm: file/update/close exactly one rec per episode.

    Mirrors detect_ducklake_code_drift; see that function's docstring for the argument contract.
    The only differences: the three prod-class function names (vs the four ducklake functions),
    PROD_SOURCE_PATHSPECS (vs DUCKLAKE_SOURCE_PATHSPECS), source="prod_code_drift" (vs
    "ducklake_code_drift"), and read_deploy_record(..., channel="prod") (vs the ducklake default).

    Returns:
        {"action": "file"|"update"|"close"|"none"|"skipped", "rec_id": str|None}
    """
    from scripts.build_lambda_deploy import read_deploy_record  # noqa: PLC0415

    if s3_client is None:
        import boto3  # noqa: PLC0415

        s3_client = boto3.Session(profile_name=profile).client("s3")

    def _default_runner(cmd: list[str]) -> str:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip()

    runner = git_runner or _default_runner
    latest_sha = runner(["git", "log", "-1", "--format=%H", "--", *PROD_SOURCE_PATHSPECS]).strip()

    stale_functions: list[str] = []
    for function in _PROD_FUNCTION_NAMES:
        record = read_deploy_record(function, s3_client=s3_client, channel="prod")
        if record is None or record.get("source_git_sha") != latest_sha:
            stale_functions.append(function)

    if open_recs is None:
        open_recs = _fetch_open_recs(profile=profile)

    existing = find_open_prod_drift_rec(open_recs)
    open_rec_exists = existing is not None
    over_threshold = bool(stale_functions)

    action = escalation_action(over_threshold=over_threshold, open_rec_exists=open_rec_exists)

    if action == "none":
        return {"action": "none", "rec_id": None}

    if action == "file":
        fields = _build_prod_drift_rec_fields(stale_functions, latest_sha)
        if portal_caller is not None:
            rec_id = portal_caller("file", fields)
        else:
            from scripts.ops_data_portal import file_rec  # noqa: PLC0415

            rec_id = file_rec(fields, profile=profile)
        return {"action": "file", "rec_id": rec_id}

    if action == "update" and existing is not None:
        updates = {"context": _build_prod_drift_context(stale_functions, latest_sha)}
        if portal_caller is not None:
            portal_caller("update", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "update", "rec_id": existing["id"]}

    if action == "close" and existing is not None:
        updates = {
            "status": "closed",
            "resolution": ("All prod-class deploy records match the latest main commit touching prod source; drift resolved."),
        }
        if portal_caller is not None:
            portal_caller("close", {"id": existing["id"], **updates})
        else:
            from scripts.ops_data_portal import update_rec  # noqa: PLC0415

            update_rec(existing["id"], updates, profile=profile)
        return {"action": "close", "rec_id": existing["id"]}

    return {"action": "skipped", "rec_id": None}


# ---------------------------------------------------------------------------
# CLI entry point (called by the GitHub Actions workflow)
# ---------------------------------------------------------------------------


def main(profile: Optional[str] = None) -> int:
    """Assess convergence health and escalate if warranted. Returns exit code."""
    import json  # noqa: PLC0415
    import os  # noqa: PLC0415

    try:
        import boto3  # noqa: PLC0415

        session = boto3.Session(profile_name=profile)
        s3 = session.client("s3")
    except Exception as exc:  # noqa: BLE001
        print(f"[convergence_health] S3 client init failed: {exc}")
        return 1

    record = read_convergence_record(s3)
    diagnose_mode = bool(os.environ.get("CONVERGENCE_HEALTH_DIAGNOSE"))

    if diagnose_mode:
        diagnose_out = diagnose_stuck_approvals()
        verdict = assess_health(record, stuck_approvals=diagnose_out)
    else:
        stuck = find_stuck_gated_approvals()
        verdict = assess_health(record, stuck_approvals=stuck)

    print(
        f"[convergence_health] HealthVerdict: {
            json.dumps(
                {
                    'status': verdict.status,
                    'red_age_hours': verdict.red_age_hours,
                    'unapplied_backlog': verdict.unapplied_backlog,
                    'stuck_approvals': len(verdict.stuck_approvals),
                    'severity': verdict.severity,
                }
            )
        }"
    )

    if diagnose_mode:
        print(f"[convergence_health] diagnose_stuck_approvals: {diagnose_out}")
        return 0  # read-only; do not escalate

    reconcile_in_flight = False
    if record is not None and record.get("status") == "red":
        # T2.37 c4: only worth the extra API call when there is a red episode to potentially
        # double-file against.
        reconcile_runs = find_reconcile_runs_since()
        reconcile_in_flight = has_in_flight_reconcile_for_episode(reconcile_runs, red_since=derive_red_since(record))

    result = escalate(verdict, profile=profile, reconcile_in_flight=reconcile_in_flight)
    print(f"[convergence_health] escalation result: {result}")
    return 0


def main_ducklake_drift(profile: Optional[str] = None) -> int:
    """Run the DuckLake code-drift sensor (T2.38) and escalate if warranted. Returns exit code."""
    try:
        result = detect_ducklake_code_drift(profile=profile)
    except Exception as exc:  # noqa: BLE001
        print(f"[convergence_health] ducklake_code_drift failed: {exc}")
        return 1
    print(f"[convergence_health] ducklake_code_drift result: {result}")
    return 0


def main_prod_drift(profile: Optional[str] = None) -> int:
    """Run the prod-class code-drift sensor (T2.43) and escalate if warranted. Returns exit code."""
    try:
        result = detect_prod_code_drift(profile=profile)
    except Exception as exc:  # noqa: BLE001
        print(f"[convergence_health] prod_code_drift failed: {exc}")
        return 1
    print(f"[convergence_health] prod_code_drift result: {result}")
    return 0


if __name__ == "__main__":
    import sys

    if "--ducklake-drift" in sys.argv[1:]:
        sys.exit(main_ducklake_drift())
    elif "--prod-drift" in sys.argv[1:]:
        sys.exit(main_prod_drift())
    else:
        sys.exit(main())
