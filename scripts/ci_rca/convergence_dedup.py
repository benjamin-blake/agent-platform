"""Cause-aware CONVERGENCE_RED dedup for terraform-apply-sandbox refusals (CD.35 5.5d follow-on).

A CONVERGENCE_RED refusal is a downstream SYMPTOM, not its own root cause. Its cause-rec is one
of two backed keys:

  - Drift-red (record.drift_run_url present): the open source=tf_drift rec whose free-text
    context embeds that run URL (terraform-drift.yml files this rec with the run URL baked into
    context; see terraform-drift.yml's "File the drift rec" step).
  - Apply-failure-red (no drift markers): a pre-existing non-convergence_refused
    ci-rca/terraform-apply-sandbox/* commit-status SUCCESS context already posted on
    record.commit_sha -- the same anchor primitive ci-rca.yml's "Mark failure as RCA'd" step
    posts (ci-rca.yml:358-369), whose status description embeds the rec id
    ("ci-rca filed rec-NNN for this failure").

Matches ONLY these backed keys -- never a free-floating "commit_sha in rec context" field (ci_rca
recs carry no commit field; CiRcaContext, ci_rca_schema.py). Returns None when neither holds, so
the refusal files as the fallback red-surface (Decision 55 -- dedup never silently swallows an
undiagnosed failure).

CLI usage (invoked by ci-rca.yml's Dedup guard):
    bin/venv-python -m scripts.ci_rca.convergence_dedup \\
        --record /tmp/convergence-record.json \\
        --commit-statuses /tmp/commit-statuses.json
Prints already_filed=true|false, and on a hit cause_rec=rec-NNN + cause_kind=tf_drift|ci_rca.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DriftRecFinderFn = Callable[[str], Optional[str]]
CommitStatusCheckerFn = Callable[[str], Optional[str]]

# The exact description string ci-rca.yml's "Mark failure as RCA'd" step posts
# (ci-rca.yml:358-369) -- the anchor primitive that lets an apply-failure-red refusal re-link
# to the rec that already covers the underlying apply failure.
_FILED_REC_RE = re.compile(r"\bci-rca filed (rec-\d+) for this failure\b")

_CONVERGENCE_CONTEXT_PREFIX = "ci-rca/terraform-apply-sandbox/"


@dataclass
class ConvergenceCauseHit:
    cause_rec: str
    cause_kind: str  # "tf_drift" | "ci_rca"


def find_open_convergence_cause_rec(
    record: dict,
    *,
    drift_rec_finder: DriftRecFinderFn,
    commit_status_checker: CommitStatusCheckerFn,
) -> Optional[ConvergenceCauseHit]:
    """Resolve a CONVERGENCE_RED refusal's cause-rec, or None if neither backed key matches.

    Args:
        record: The parsed convergence record (s3://.../convergence/personal/sandbox.json).
        drift_rec_finder: Injected callable(drift_run_url) -> open tf_drift rec id | None.
        commit_status_checker: Injected callable(commit_sha) -> ci_rca rec id parsed from a
            matching non-convergence_refused commit-status description, or None.

    Returns:
        ConvergenceCauseHit(cause_rec, cause_kind='tf_drift') for a drift-red match,
        ConvergenceCauseHit(cause_rec, cause_kind='ci_rca') for an apply-failure-red match,
        or None when neither backed key resolves.
    """
    drift_run_url = record.get("drift_run_url")
    if drift_run_url:
        rec_id = drift_rec_finder(drift_run_url)
        if rec_id:
            return ConvergenceCauseHit(cause_rec=rec_id, cause_kind="tf_drift")
        return None

    commit_sha = record.get("commit_sha")
    if commit_sha:
        rec_id = commit_status_checker(commit_sha)
        if rec_id:
            return ConvergenceCauseHit(cause_rec=rec_id, cause_kind="ci_rca")

    return None


def _default_drift_rec_finder(drift_run_url: str, profile: Optional[str] = None) -> Optional[str]:
    """Real lookup: open source=tf_drift recs whose context embeds drift_run_url.

    Reads transit the closed DuckLake reader via a single-key structural row_filter
    (source = 'tf_drift') -- Decision 84 I-3, no caller SQL. The status=open filter and the
    URL-embed match are applied in-process on the returned rows.

    Fails OPEN (returns None + a loud log) ONLY when the reader itself is unreachable
    (connectivity failure / Neon scale-to-zero exhausting retries) -- mirrors
    find_open_ci_rca_rec_by_fingerprint's fail-open contract (ci_rca_runtime.py) so a transient
    warehouse blip degrades to "refusal files as the fallback red-surface" instead of aborting
    the whole ci-rca.yml Dedup guard step. Any other exception raises (Decision 55).
    """
    from scripts.ops_portal.ci_rca_runtime import _is_reader_unreachable_error  # noqa: PLC0415
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    try:
        rows = make_reader(profile=profile).current_state("ops_recommendations", row_filter="source = 'tf_drift'") or []
    except Exception as exc:  # noqa: BLE001
        if _is_reader_unreachable_error(exc):
            logger.warning(
                "[CI_RCA_DEDUP] DuckLake reader unreachable while searching for tf_drift cause rec "
                "(drift_run_url=%s); failing open (dedup skipped, refusal files as fallback): %s",
                drift_run_url,
                exc,
            )
            return None
        raise

    for row in rows:
        if row.get("status") != "open":
            continue
        context = row.get("context") or ""
        if drift_run_url in context:
            return row.get("id")
    return None


def _default_commit_status_checker(commit_sha: str, statuses: list[dict]) -> Optional[str]:
    """Real lookup: a non-convergence_refused ci-rca/terraform-apply-sandbox/* SUCCESS status
    already posted on commit_sha, with the rec id parsed from its description.

    `statuses` is the raw `gh api repos/OWNER/REPO/commits/{sha}/statuses` response (a list of
    status objects), fetched by the ci-rca.yml shell -- this function performs no gh/network
    call itself (thin-shell invocation-only design).
    """
    for status in statuses:
        context = status.get("context") or ""
        if not context.startswith(_CONVERGENCE_CONTEXT_PREFIX):
            continue
        category = context[len(_CONVERGENCE_CONTEXT_PREFIX) :]
        if category == "convergence_refused":
            continue
        if status.get("state") != "success":
            continue
        match = _FILED_REC_RE.search(status.get("description") or "")
        if match:
            return match.group(1)
    return None


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Cause-aware CONVERGENCE_RED dedup decision.")
    parser.add_argument(
        "--record",
        type=Path,
        default=None,
        help="Path to the convergence record JSON. Reads stdin when omitted.",
    )
    parser.add_argument(
        "--commit-statuses",
        type=Path,
        default=None,
        help="Path to the `gh api commits/{sha}/statuses` JSON array. Treated as empty when omitted.",
    )
    parser.add_argument("--profile", default=None, help="AWS profile override")
    args = parser.parse_args(argv)

    record_text = args.record.read_text(encoding="utf-8") if args.record is not None else sys.stdin.read()
    record = json.loads(record_text) if record_text.strip() else {}

    statuses: list[dict] = []
    if args.commit_statuses is not None and args.commit_statuses.exists():
        loaded = json.loads(args.commit_statuses.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            statuses = loaded

    hit = find_open_convergence_cause_rec(
        record,
        drift_rec_finder=lambda url: _default_drift_rec_finder(url, profile=args.profile),
        commit_status_checker=lambda sha: _default_commit_status_checker(sha, statuses),
    )

    if hit is None:
        print("already_filed=false")
        return 0

    print("already_filed=true")
    print(f"cause_rec={hit.cause_rec}")
    print(f"cause_kind={hit.cause_kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
