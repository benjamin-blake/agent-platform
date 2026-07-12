#!/usr/bin/env python3
"""Testable helper for .github/workflows/reconcile.yml (T2.37 -- input-free heal button).

Two responsibilities, both required before Reconcile proceeds:

  1. Read the durable convergence record (s3://agent-platform-data-lake/convergence/personal/
     sandbox.json) and resolve whether there is a red commit to reconcile. A green or absent
     record is a clean no-op -- Reconcile touches nothing (T2.37 c1). A red record without a
     commit_sha is a malformed-record error state, not silently treated as green.
  2. When an operator supplies an optional rec-id, validate it resolves to an OPEN rec via the
     ducklake_reader closed-boundary named-verb surface (rec_by_id) BEFORE the dispatch proceeds
     (T2.37 c2; Decision 84 Single Portal Invariant -- no caller SQL, never the local JSONL cache).

All external dependencies (S3 client, the ducklake reader) are injected so unit tests exercise
this module without live AWS -- mirrors the injection pattern in scripts/convergence_health.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Callable, Optional

CONVERGENCE_BUCKET = "agent-platform-data-lake"
CONVERGENCE_KEY = "convergence/personal/sandbox.json"

_REC_ID_PATTERN = re.compile(r"^rec-\d+$")


@dataclass
class ReconcileTarget:
    """Result of resolving what (if anything) Reconcile should re-apply."""

    actionable: bool
    commit_sha: Optional[str] = None
    reason: str = ""


# ---------------------------------------------------------------------------
# Convergence record read + target resolution
# ---------------------------------------------------------------------------


def read_convergence_record(
    s3_client: Any,
    bucket: str = CONVERGENCE_BUCKET,
    key: str = CONVERGENCE_KEY,
) -> Optional[dict[str, Any]]:
    """Read the convergence record from S3; return None on NoSuchKey / missing object.

    Same record and pass-on-absent semantics as scripts/convergence_health.py's
    read_convergence_record -- duplicated rather than imported so this module has no import-time
    coupling to convergence_health (each stays independently testable and deployable).
    """
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        body = response["Body"].read()
        return json.loads(body)
    except Exception as exc:  # noqa: BLE001
        exc_str = str(exc) + type(exc).__name__
        if any(marker in exc_str for marker in ("NoSuchKey", "404", "NoSuchBucket")):
            return None
        raise


def resolve_reconcile_target(record: Optional[dict[str, Any]]) -> ReconcileTarget:
    """Pure decision: given a convergence record, is there a red commit to reconcile?

    Green or absent record -> clean no-op (T2.37 c1). Red record -> the commit_sha to re-apply.
    A red record with no commit_sha is a malformed-record state: NOT actionable (nothing to
    re-apply against) and NOT treated as green (the record still needs operator attention) --
    reason distinguishes it from a genuine converged/absent no-op.
    """
    if record is None:
        return ReconcileTarget(actionable=False, reason="No convergence record (absent) -- nothing to reconcile.")

    status = record.get("status")
    if status != "red":
        return ReconcileTarget(
            actionable=False,
            reason=f"Convergence record status={status!r} (not red) -- nothing to reconcile.",
        )

    commit_sha = record.get("commit_sha")
    if not commit_sha:
        return ReconcileTarget(
            actionable=False,
            reason="Convergence record is red but carries no commit_sha -- cannot resolve a "
            "reconcile target; this is a malformed-record state requiring manual inspection, "
            "not a clean no-op.",
        )

    return ReconcileTarget(actionable=True, commit_sha=commit_sha, reason=f"Red commit {commit_sha} -- reconcilable.")


# ---------------------------------------------------------------------------
# Optional rec-id OPEN validation (T2.37 c2)
# ---------------------------------------------------------------------------


def validate_rec_id_open(rec_id: str, reader: Callable[[str], list[dict[str, Any]]]) -> bool:
    """Return True iff rec_id resolves to an OPEN rec via the injected reader's rec_by_id verb.

    reader is callable(rec_id) -> rows, matching make_reader(profile=...).named("rec_by_id",
    id=rec_id) (injected so tests never touch live AWS). A malformed rec_id (not rec-<digits>)
    returns False without calling the reader -- fail-closed on input shape, mirroring the guard
    in scripts/ops_data_portal.py's _fetch_rec_from_reader.
    """
    if not _REC_ID_PATTERN.fullmatch(rec_id):
        return False
    rows = reader(rec_id)
    if not rows:
        return False
    return rows[0].get("status") == "open"


def _default_reader(profile: Optional[str]) -> Callable[[str], list[dict[str, Any]]]:
    """Build the live ducklake_reader-bound reader callable (closed boundary, named verb only).

    Deferred import: this module must remain importable (for unit tests) without the reader's
    heavier dependency chain loaded unless the live path is actually exercised.
    """
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    def _call(rec_id: str) -> list[dict[str, Any]]:
        return make_reader(profile=profile).named("rec_by_id", id=rec_id)

    return _call


# ---------------------------------------------------------------------------
# CLI entry point (called by .github/workflows/reconcile.yml)
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint. Emits GITHUB_OUTPUT-compatible `key=value` lines to stdout.

    Usage: reconcile_target.py [--rec-id rec-NNN] [--profile PROFILE]

    Behaviour:
      - If --rec-id is supplied, validates it resolves to an OPEN rec via the ducklake_reader
        boundary FIRST. A non-open/invalid rec-id fails the dispatch (exit 1) before the
        convergence record is even read (T2.37 c2).
      - Reads the live convergence record from S3 and resolves the reconcile target. Prints
        `actionable=true|false`, `commit_sha=<sha>` (only when actionable), and `reason=...`.
      - Exit codes: 0 = resolved (actionable target OR a clean no-op -- both are success, per
        T2.37 c1's "exit cleanly" contract); 1 = rec-id validation failed or an internal error
        (S3 client init, reader unreachable) -- fails closed, the workflow must not proceed.
    """
    parser = argparse.ArgumentParser(prog="reconcile_target.py")
    parser.add_argument("--rec-id", default=None)
    parser.add_argument("--profile", default=None)
    args = parser.parse_args(argv)

    if args.rec_id:
        try:
            is_open = validate_rec_id_open(args.rec_id, _default_reader(args.profile))
        except Exception as exc:  # noqa: BLE001
            print(f"reconcile_target: rec-id validation failed: {exc}", file=sys.stderr)
            return 1
        if not is_open:
            print(
                f"reconcile_target: rec-id {args.rec_id!r} does not resolve to an OPEN rec; failing closed.",
                file=sys.stderr,
            )
            return 1
        print(f"rec_id_validated={args.rec_id}")

    try:
        import boto3  # noqa: PLC0415

        session = boto3.Session(profile_name=args.profile or None)
        s3 = session.client("s3")
        record = read_convergence_record(s3)
    except Exception as exc:  # noqa: BLE001
        print(f"reconcile_target: could not read convergence record: {exc}", file=sys.stderr)
        return 1

    target = resolve_reconcile_target(record)
    print(f"actionable={'true' if target.actionable else 'false'}")
    if target.commit_sha:
        print(f"commit_sha={target.commit_sha}")
    print(f"reason={target.reason}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
