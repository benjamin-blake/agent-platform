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

This package is a behaviour-preserving decomposition of the former single-file
convergence_health monolith (Decision 128 / PLAN-convergence-health-sloc-decompose-guardrails):
every submodule stays under the 500-SLOC budget.
This __init__.py is the facade -- it re-exports the full prior public surface
(plus test-patched private symbols) so `from scripts.convergence_health import
X` and existing call/patch sites keep resolving unchanged.

  record.py     -- convergence-record read + time/backlog helpers.
  approvals.py  -- GitHub-Actions stuck-approval / Reconcile signal helpers.
  assess.py     -- HealthVerdict + assess_health.
  escalate.py   -- idempotent tf_convergence_stale file/update/close.
  code_drift.py -- DuckLake + prod-class code-drift alarms.
  __main__.py   -- CLI dispatch (python -m scripts.convergence_health).
"""

from __future__ import annotations

from scripts.convergence_health.__main__ import main, main_ducklake_drift, main_prod_drift
from scripts.convergence_health.approvals import (
    STUCK_APPROVAL_THRESHOLD_HOURS,
    _make_github_caller,
    diagnose_stuck_approvals,
    filter_stuck_runs,
    find_reconcile_runs_since,
    find_stuck_gated_approvals,
    has_in_flight_reconcile_for_episode,
)
from scripts.convergence_health.assess import (
    RED_AGE_THRESHOLD_HOURS,
    STALE_GREEN_BACKLOG_THRESHOLD_HOURS,
    HealthVerdict,
    assess_health,
    escalation_action,
)
from scripts.convergence_health.code_drift import (
    _PROD_FUNCTION_NAMES,
    DUCKLAKE_SOURCE_PATHSPECS,
    PROD_SOURCE_PATHSPECS,
    detect_ducklake_code_drift,
    detect_prod_code_drift,
    find_open_ducklake_drift_rec,
    find_open_prod_drift_rec,
)
from scripts.convergence_health.escalate import (
    _RESOLUTION_PERSISTENTLY_RED,
    _RESOLUTION_STALE_GREEN_BACKLOG,
    _RESOLUTION_STUCK_APPROVAL,
    _TITLE_PERSISTENTLY_RED,
    _TITLE_STALE_GREEN_BACKLOG,
    _TITLE_STUCK_APPROVAL,
    _fetch_open_recs,
    escalate,
    find_open_convergence_stale_rec,
)
from scripts.convergence_health.record import (
    CONVERGENCE_BUCKET,
    CONVERGENCE_KEY,
    _parse_utc,
    count_unapplied_tf_commits,
    derive_red_since,
    read_convergence_record,
    record_age_hours,
    red_age_hours,
)

__all__ = [
    "CONVERGENCE_BUCKET",
    "CONVERGENCE_KEY",
    "RED_AGE_THRESHOLD_HOURS",
    "STALE_GREEN_BACKLOG_THRESHOLD_HOURS",
    "STUCK_APPROVAL_THRESHOLD_HOURS",
    "DUCKLAKE_SOURCE_PATHSPECS",
    "PROD_SOURCE_PATHSPECS",
    "HealthVerdict",
    "_PROD_FUNCTION_NAMES",
    "_RESOLUTION_PERSISTENTLY_RED",
    "_RESOLUTION_STALE_GREEN_BACKLOG",
    "_RESOLUTION_STUCK_APPROVAL",
    "_TITLE_PERSISTENTLY_RED",
    "_TITLE_STALE_GREEN_BACKLOG",
    "_TITLE_STUCK_APPROVAL",
    "_fetch_open_recs",
    "_make_github_caller",
    "_parse_utc",
    "assess_health",
    "count_unapplied_tf_commits",
    "derive_red_since",
    "detect_ducklake_code_drift",
    "detect_prod_code_drift",
    "diagnose_stuck_approvals",
    "escalate",
    "escalation_action",
    "filter_stuck_runs",
    "find_open_convergence_stale_rec",
    "find_open_ducklake_drift_rec",
    "find_open_prod_drift_rec",
    "find_reconcile_runs_since",
    "find_stuck_gated_approvals",
    "has_in_flight_reconcile_for_episode",
    "main",
    "main_ducklake_drift",
    "main_prod_drift",
    "read_convergence_record",
    "record_age_hours",
    "red_age_hours",
]
