"""Recommendation sync utilities: ID allocation and local cache management.

next_id(counter_name): Atomically allocate the next sequential ID from DynamoDB.
seed_counters(profile): Seed DynamoDB counters from local JSONL + DECISIONS.md.

ROLLBACK TOOLING ONLY (Decision 84 I-2): the ducklake_writer owns rec-NNN allocation;
nothing on the live path calls next_id. These CLIs survive solely so a portal revert can
reseed the DynamoDB counter FROM THE DUCKLAKE MAX first (stale ids silently overwrite
writer-allocated recs otherwise). Retires with the counters table at demolition.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

try:
    import boto3

    _BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None
    _BOTO3_AVAILABLE = False

from scripts.aws_profile import resolve_aws_profile

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCAL_RECS_FILE = _REPO_ROOT / "logs" / ".recommendations-log.jsonl"
_DYNAMODB_TABLE = "agent-platform-counters"
_AWS_REGION = "eu-west-2"
_SSO_PROFILE = "agent_platform"


def _read_local_recs() -> list[dict]:
    """Read local .recommendations-log.jsonl."""
    if not _LOCAL_RECS_FILE.exists():
        return []
    entries: list[dict] = []
    for lineno, line in enumerate(_LOCAL_RECS_FILE.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            entries.append(json.loads(stripped))
        except json.JSONDecodeError as exc:
            logger.warning("Skipping malformed JSON on line %d of local recs: %s", lineno, exc)
    return entries


def next_id(counter_name: str, profile: str | None = None) -> str | int:
    """Atomically allocate the next sequential ID from DynamoDB.

    Uses UpdateItem ADD 1 (strongly consistent, concurrent-safe).
    Returns:
        - 'rec-NNN' (zero-padded) when counter_name == 'recommendations'
        - int when counter_name == 'decisions'
        - int for any other counter_name
    Raises RuntimeError if boto3 unavailable or DynamoDB unreachable.
    """
    if not _BOTO3_AVAILABLE:
        raise RuntimeError("boto3 not available; cannot allocate ID from DynamoDB")
    _profile = resolve_aws_profile(profile, default=_SSO_PROFILE)
    session = boto3.Session(profile_name=_profile, region_name=_AWS_REGION)
    ddb = session.client("dynamodb", region_name=_AWS_REGION)
    response = ddb.update_item(
        TableName=_DYNAMODB_TABLE,
        Key={"counter_name": {"S": counter_name}},
        UpdateExpression="ADD current_value :inc",
        ExpressionAttributeValues={":inc": {"N": "1"}},
        ReturnValues="UPDATED_NEW",
    )
    value = int(response["Attributes"]["current_value"]["N"])
    if counter_name == "recommendations":
        return f"rec-{value:03d}"
    return value


def reseed_decisions_counter(max_id: int, profile: str | None = None) -> None:
    """Monotonically advance the DynamoDB decisions counter to max_id.

    Uses a ConditionExpression so the counter never decreases (calling with a
    lower max_id is a no-op via ConditionalCheckFailedException). Safe to call
    multiple times with the same max_id (idempotent).

    Distinct from seed_counters (bootstrap only, unconditional put_item):
    this function is for re-seeding an existing counter, not creating it.

    Raises:
        RuntimeError: if boto3 is unavailable or DynamoDB is unreachable.
    """
    if not _BOTO3_AVAILABLE:
        raise RuntimeError("boto3 not available; cannot reseed DynamoDB counter")
    _profile = resolve_aws_profile(profile, default=_SSO_PROFILE)
    session = boto3.Session(profile_name=_profile, region_name=_AWS_REGION)
    ddb = session.client("dynamodb", region_name=_AWS_REGION)
    try:
        ddb.update_item(
            TableName=_DYNAMODB_TABLE,
            Key={"counter_name": {"S": "decisions"}},
            UpdateExpression="SET current_value = :max",
            ConditionExpression="attribute_not_exists(current_value) OR current_value < :max",
            ExpressionAttributeValues={":max": {"N": str(max_id)}},
        )
        logger.info("reseed_decisions_counter: advanced counter to %d", max_id)
    except ddb.exceptions.ConditionalCheckFailedException:
        logger.info("reseed_decisions_counter: counter already >= %d (no-op)", max_id)


def reseed_recommendations_counter(max_id: int, profile: str | None = None) -> None:
    """Monotonically advance the DynamoDB recommendations counter to max_id.

    Uses a ConditionExpression so the counter never decreases (calling with a
    lower max_id is a no-op via ConditionalCheckFailedException). Safe to call
    multiple times with the same max_id (idempotent).

    Symmetric with reseed_decisions_counter. Required by the Phase C migration
    (Step 13c HARD gate, Decision 50): after preserving historical rec-NNN ids
    via _migration_int_id, the counter MUST be raised above the migrated max so a
    future _next_id cannot re-issue a migrated id and SCD2-merge two distinct recs.
    seed_counters' unconditional put_item could LOWER the counter -- never use it
    to re-seed.

    Raises:
        RuntimeError: if boto3 is unavailable or DynamoDB is unreachable.
    """
    if not _BOTO3_AVAILABLE:
        raise RuntimeError("boto3 not available; cannot reseed DynamoDB counter")
    _profile = resolve_aws_profile(profile, default=_SSO_PROFILE)
    session = boto3.Session(profile_name=_profile, region_name=_AWS_REGION)
    ddb = session.client("dynamodb", region_name=_AWS_REGION)
    try:
        ddb.update_item(
            TableName=_DYNAMODB_TABLE,
            Key={"counter_name": {"S": "recommendations"}},
            UpdateExpression="SET current_value = :max",
            ConditionExpression="attribute_not_exists(current_value) OR current_value < :max",
            ExpressionAttributeValues={":max": {"N": str(max_id)}},
        )
        logger.info("reseed_recommendations_counter: advanced counter to %d", max_id)
    except ddb.exceptions.ConditionalCheckFailedException:
        logger.info("reseed_recommendations_counter: counter already >= %d (no-op)", max_id)


def seed_counters(profile: str | None = None) -> dict:
    """Seed DynamoDB counters from local sources.

    Bootstrap only -- uses unconditional put_item. NOT suitable for re-seeding
    an existing counter (put_item overwrites the current value, which can lower
    it). Use reseed_decisions_counter() to safely advance the decisions counter
    to a higher value without risking a decrease.

    Reads max rec ID from .recommendations-log.jsonl and max decision ID from
    DECISIONS.md (via parse_decisions_md), then writes both counters via
    DynamoDB put_item. Safe to call multiple times (idempotent; you must manually
    bump the seed value if the local log is ahead of what was previously seeded).

    Returns: {"recommendations": N, "decisions": N} for the seeded values.
    Raises RuntimeError if boto3 unavailable or DynamoDB unreachable.
    """
    if not _BOTO3_AVAILABLE:
        raise RuntimeError("boto3 not available; cannot seed DynamoDB counters")
    from scripts.decisions_md import parse_decisions_md  # noqa: PLC0415

    # Determine max rec ID from local JSONL
    max_rec_id = 0
    for entry in _read_local_recs():
        rec_id_str = entry.get("id", "")
        if isinstance(rec_id_str, str) and rec_id_str.startswith("rec-"):
            try:
                n = int(rec_id_str[4:])
                if n > max_rec_id:
                    max_rec_id = n
            except ValueError:
                pass

    # Determine max decision ID from DECISIONS.md
    max_decision_id = 0
    try:
        decisions = parse_decisions_md()
        for d in decisions:
            did = d.get("decision_id", 0)
            if isinstance(did, int) and did > max_decision_id:
                max_decision_id = did
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not parse DECISIONS.md for seed: %s", exc)

    _profile = resolve_aws_profile(profile, default=_SSO_PROFILE)
    session = boto3.Session(profile_name=_profile, region_name=_AWS_REGION)
    ddb = session.client("dynamodb", region_name=_AWS_REGION)

    ddb.put_item(
        TableName=_DYNAMODB_TABLE,
        Item={
            "counter_name": {"S": "recommendations"},
            "current_value": {"N": str(max_rec_id)},
        },
    )
    ddb.put_item(
        TableName=_DYNAMODB_TABLE,
        Item={
            "counter_name": {"S": "decisions"},
            "current_value": {"N": str(max_decision_id)},
        },
    )
    print(f"Seeded: recommendations={max_rec_id}, decisions={max_decision_id}")
    return {"recommendations": max_rec_id, "decisions": max_decision_id}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Recommendation ID allocation and counter seeding.")
    parser.add_argument(
        "--next-id",
        metavar="COUNTER_NAME",
        dest="next_id",
        help="Allocate next sequential ID via DynamoDB atomic counter (e.g. recommendations, decisions)",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Seed DynamoDB counters from local JSONL and DECISIONS.md",
    )
    parser.add_argument(
        "--profile",
        metavar="AWS_PROFILE",
        default=None,
        help="AWS profile for DynamoDB access (overrides AWS_PROFILE env var)",
    )
    args = parser.parse_args(argv)

    if not any([args.next_id, args.seed]):
        parser.print_help()
        return 0

    if args.next_id:
        try:
            result_id = next_id(args.next_id, profile=args.profile)
            print(result_id)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    if args.seed:
        try:
            seed_counters(profile=args.profile)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
