"""Canonicalize and validate GitHub job metadata before CI-RCA reads logs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "ci-rca-log-admission/v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_SAFE_TEXT_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,200}$")
_CONCLUSIONS = {None, "success", "failure", "cancelled", "skipped", "timed_out", "action_required", "neutral"}


def canonical_admission(raw_pages: list[dict[str, Any]], *, run_id: str, head_sha: str) -> bytes:
    if not run_id.isdigit() or not _SHA_RE.fullmatch(head_sha):
        raise ValueError("invalid run or SHA identity")
    jobs: list[dict[str, Any]] = []
    for page in raw_pages:
        for job in page.get("jobs", []):
            steps = []
            for step in job.get("steps", []):
                name = str(step["name"])
                conclusion = step.get("conclusion")
                if not _SAFE_TEXT_RE.fullmatch(name) or conclusion not in _CONCLUSIONS:
                    raise ValueError("invalid step metadata")
                steps.append({"number": int(step["number"]), "name": name, "conclusion": conclusion})
            name = str(job["name"])
            conclusion = job.get("conclusion")
            if not _SAFE_TEXT_RE.fullmatch(name) or conclusion not in _CONCLUSIONS:
                raise ValueError("invalid job metadata")
            jobs.append(
                {
                    "id": int(job["id"]),
                    "name": name,
                    "conclusion": conclusion,
                    "steps": sorted(steps, key=lambda item: item["number"]),
                }
            )
    jobs.sort(key=lambda item: item["id"])
    if not jobs or len({job["id"] for job in jobs}) != len(jobs):
        raise ValueError("jobs metadata is empty or contains duplicate ids")
    document = {"schema_version": SCHEMA_VERSION, "run_id": run_id, "head_sha": head_sha, "jobs": jobs}
    return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode()


def load_admission(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    expected = {"schema_version", "run_id", "head_sha", "jobs"}
    if set(document) != expected or document["schema_version"] != SCHEMA_VERSION:
        raise ValueError("invalid admission schema")
    canonical = canonical_admission([{"jobs": document["jobs"]}], run_id=document["run_id"], head_sha=document["head_sha"])
    if canonical != path.read_bytes():
        raise ValueError("admission is not canonical")
    return document


def digest(document: bytes) -> str:
    return hashlib.sha256(document).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-pages", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        pages = json.loads(args.raw_pages.read_text(encoding="utf-8"))
        document = canonical_admission(pages, run_id=args.run_id, head_sha=args.head_sha)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"CI_RCA_ADMISSION_INVALID: {exc}", file=sys.stderr)
        return 1
    args.out.write_bytes(document)
    print(digest(document))
    return 0


if __name__ == "__main__":
    sys.exit(main())
