"""DuckLake + prod-class code-drift alarms (T2.38/T2.43, Decision 125/126).

Reads each governed function's deploy record (scripts.build_lambda_deploy.
read_deploy_record), resolves the latest main commit touching its source
paths via git_runner, and compares recorded source_git_sha against it.
Mirrors escalate()'s idempotent file/update/close pattern, but ANY stale
function triggers exactly ONE deduped rec (never one per function). Never
writes a deploy record; never redeploys; never runs build_lambda.
Alarm-not-gate (priority High, never source=ci_rca). Part of the
scripts.convergence_health package -- see scripts/convergence_health/__init__.py
for the full public surface.
"""

from __future__ import annotations

import subprocess
from typing import Any, Callable, Optional

from scripts.convergence_health.assess import escalation_action
from scripts.convergence_health.escalate import _fetch_open_recs

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
    "scripts/llm/github_models_client.py",
    "scripts/llm/client.py",
    "scripts/llm/utils.py",
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
