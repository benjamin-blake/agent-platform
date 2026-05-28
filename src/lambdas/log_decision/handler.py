"""Stub handler for the log-decision Lambda. Real implementation: T0.7b."""

import json

# TODO(T0.7b): principal-binding check -- compare assumed-role ARN against PlatformAdmin role ARN
# for admin-only branches (CD.10, ROADMAP-PLATFORM.yaml T0.6 exit criterion).


def handler(event: dict, context: object) -> dict:
    return {
        "statusCode": 501,
        "body": json.dumps({"status": "stub", "lambda": "log-decision", "message": "T0.7b not yet implemented"}),
    }
