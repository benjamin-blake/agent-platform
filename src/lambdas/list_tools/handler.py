"""Stub handler for the list-tools Lambda. Real implementation: T1.3."""

import json

# TODO(T1.3): principal-binding check -- compare assumed-role ARN against PlatformAdmin role ARN
# for admin-only branches (CD.10, ROADMAP-PLATFORM.yaml T0.6 exit criterion).


def handler(event: dict, context: object) -> dict:
    return {
        "statusCode": 501,
        "body": json.dumps({"status": "stub", "lambda": "list-tools", "message": "T1.3 not yet implemented"}),
    }
