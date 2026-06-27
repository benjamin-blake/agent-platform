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
    import json as _json  # noqa: PLC0415
    import os  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    if now is None:
        now = datetime.now(timezone.utc)

    token = os.environ.get("GH_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")

    def _default_caller(url: str) -> Any:
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

    caller = gh_caller or _default_caller

    stuck: list[dict[str, Any]] = []
    try:
        url = (
            f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/"
            f"terraform-apply-sandbox.yml/runs?status=waiting&per_page=10"
        )
        data = caller(url)
        if not data:
            return []
        for run in data.get("workflow_runs", []):
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
    except Exception:  # noqa: BLE001
        pass
    return stuck


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

    Returns:
        {"action": "file"|"update"|"close"|"none"|"skipped", "rec_id": str|None}
    """
    if open_recs is None:
        open_recs = _fetch_open_recs(profile=profile)

    existing = find_open_convergence_stale_rec(open_recs)
    open_rec_exists = existing is not None
    over_threshold = verdict.status == "red" and (verdict.red_age_hours >= threshold_hours or bool(verdict.stuck_approvals))

    action = escalation_action(over_threshold=over_threshold, open_rec_exists=open_rec_exists)

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
# CLI entry point (called by the GitHub Actions workflow)
# ---------------------------------------------------------------------------


def main(profile: Optional[str] = None) -> int:
    """Assess convergence health and escalate if warranted. Returns exit code."""
    import json  # noqa: PLC0415

    try:
        import boto3  # noqa: PLC0415

        session = boto3.Session(profile_name=profile)
        s3 = session.client("s3")
    except Exception as exc:  # noqa: BLE001
        print(f"[convergence_health] S3 client init failed: {exc}")
        return 1

    record = read_convergence_record(s3)
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

    result = escalate(verdict, profile=profile)
    print(f"[convergence_health] escalation result: {result}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
