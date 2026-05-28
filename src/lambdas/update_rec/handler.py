"""Stub handler for the update-rec Lambda. Real implementation: T1.1."""

import json

# TODO(T1.1): principal-binding check -- compare assumed-role ARN against PlatformAdmin role ARN
# for admin-only branches (CD.10, ROADMAP-PLATFORM.yaml T0.6 exit criterion).


def handler(event: dict, context: object) -> dict:
    return {
        "statusCode": 501,
        "body": json.dumps({"status": "stub", "lambda": "update-rec", "message": "T1.1 not yet implemented"}),
    }
