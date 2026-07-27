from __future__ import annotations

import json

import pytest

from scripts.ci_rca.log_admission import SCHEMA_VERSION, canonical_admission, digest


def test_canonical_admission_aggregates_pages_and_orders_identities() -> None:
    pages = [
        {
            "jobs": [
                {
                    "id": 2,
                    "name": "b",
                    "conclusion": "failure",
                    "steps": [{"number": 2, "name": "s", "conclusion": "failure"}],
                }
            ]
        },
        {"jobs": [{"id": 1, "name": "a", "conclusion": "success", "steps": []}]},
    ]
    document = canonical_admission(pages, run_id="7", head_sha="a" * 40)
    parsed = json.loads(document)
    assert parsed["schema_version"] == SCHEMA_VERSION
    assert [job["id"] for job in parsed["jobs"]] == [1, 2]
    assert len(digest(document)) == 64


def test_duplicate_job_across_pages_fails_closed() -> None:
    job = {"id": 1, "name": "a", "conclusion": "failure", "steps": []}
    with pytest.raises(ValueError, match="duplicate"):
        canonical_admission([{"jobs": [job]}, {"jobs": [job]}], run_id="7", head_sha="a" * 40)
