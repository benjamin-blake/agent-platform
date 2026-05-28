"""Smoke tests for the six platform Lambda stub handlers.

Asserts each handler returns 501, uses the correct hyphenated lambda name in the
response body, and references a T0.7/T1.x tier_item id in the message field.
A copy-paste error (e.g. log_decision handler claiming lambda: "log-rec") fails loudly.
"""

import importlib
import json
import re

import pytest

STUBS = [
    ("src.lambdas.log_rec.handler", "log-rec", "T0.7"),
    ("src.lambdas.log_decision.handler", "log-decision", "T0.7"),
    ("src.lambdas.query.handler", "query", "T0.7"),
    ("src.lambdas.update_rec.handler", "update-rec", "T1."),
    ("src.lambdas.list_tools.handler", "list-tools", "T1."),
    ("src.lambdas.maintenance.handler", "maintenance", "T1."),
]

TIER_PATTERN = re.compile(r"T[01]\.[0-9]")


@pytest.mark.parametrize("module_path,expected_name,tier_prefix", STUBS)
def test_stub_returns_501(module_path: str, expected_name: str, tier_prefix: str) -> None:
    mod = importlib.import_module(module_path)
    response = mod.handler({}, None)

    assert response["statusCode"] == 501, f"{module_path}: expected 501, got {response['statusCode']}"

    body = json.loads(response["body"])
    assert body["lambda"] == expected_name, (
        f"{module_path}: expected lambda name '{expected_name}', got '{body.get('lambda')}'"
    )
    assert tier_prefix in body["message"], (
        f"{module_path}: expected tier prefix '{tier_prefix}' in message '{body.get('message')}'"
    )
    assert TIER_PATTERN.search(body["message"]), f"{module_path}: message must contain a tier_item id like T0.7a or T1.1"
