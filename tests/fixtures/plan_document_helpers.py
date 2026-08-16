"""Shared fixtures for the tests/roadmap/plan_document/ concern-split package.

REPO_ROOT, FIXTURES, and the four helpers (_base, _base_v2, _mutate, _mutate_v2) are copied
verbatim (module-body logic unchanged) from the former tests/test_plan_document.py monolith
(PLAN-decompose-test-plan-document). tests/fixtures/ is an importable package exempt from the
no-cross-test-import guard (names never start with test_) -- consumers alias on import (e.g.
`from tests.fixtures.plan_document_helpers import _base, _base_v2, _mutate, _mutate_v2`) so every
call site stays byte-identical to the monolith. Direct precedent: tests/fixtures/ops_writer_helpers.py
(rec-2709 Wave 9).
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "plan_documents"


def _base() -> dict:
    with (FIXTURES / "valid.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _base_v2() -> dict:
    with (FIXTURES / "valid_v2.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _mutate(**overrides) -> dict:
    d = copy.deepcopy(_base())
    d.update(overrides)
    return d


def _mutate_v2(**overrides) -> dict:
    d = copy.deepcopy(_base_v2())
    d.update(overrides)
    return d
