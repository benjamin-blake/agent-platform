"""Metadata-only CI-RCA bounded-evidence canary."""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import cast

from scripts.ci_rca.bounded_evidence import copy_bounded_lines


def proof(
    scenario: str, correlation_id: str, expected_sha: str, *, run_id: str = "local", event: str = "local"
) -> dict[str, object]:
    if scenario == "malformed":
        return {
            "scenario": scenario,
            "correlation_id": correlation_id,
            "expected_sha": expected_sha,
            "implementation_sha": expected_sha,
            "run_id": run_id,
            "event": event,
            "refused": True,
        }
    source = io.BytesIO(b"safe-line\n" if scenario == "complete" else b"first\nsecond\n")
    destination = io.BytesIO()
    retained_bytes, retained_lines, truncated = copy_bounded_lines(
        source, destination, max_bytes=64 if scenario == "complete" else 6, max_lines=10
    )
    return {
        "scenario": scenario,
        "correlation_id": correlation_id,
        "expected_sha": expected_sha,
        "implementation_sha": expected_sha,
        "run_id": run_id,
        "event": event,
        "retained_bytes": retained_bytes,
        "retained_lines": retained_lines,
        "truncated": truncated,
        "raw_body_emitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=("complete", "truncated", "malformed"))
    parser.add_argument("--scenarios")
    parser.add_argument("--correlation-id")
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", "local"))
    parser.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", "local"))
    args = parser.parse_args()
    if args.scenarios:
        return _control(args.scenarios.split(","), args.expected_sha)
    if not args.scenario or not args.correlation_id:
        parser.error("worker mode requires --scenario and --correlation-id")
    result = proof(args.scenario, args.correlation_id, args.expected_sha, run_id=args.run_id, event=args.event)
    encoded = json.dumps(result, sort_keys=True)
    print(encoded)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        Path(summary).write_text(f"CI_RCA_BOUNDED_PROOF `{encoded}`\n", encoding="utf-8")
    return 1 if args.scenario == "malformed" else 0


def _gh_json(command: list[str]) -> object:
    completed = subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return json.loads(completed.stdout)


def _control(scenarios: list[str], expected_sha: str) -> int:
    allowed = {"complete", "truncated", "malformed"}
    if not scenarios or set(scenarios) - allowed:
        raise ValueError("unknown canary scenario")
    workflow = "ci-rca.yml"
    for index, scenario in enumerate(scenarios):
        correlation = f"bounded-{int(time.time())}-{os.getpid()}-{index}"
        subprocess.run(
            [
                "gh",
                "workflow",
                "run",
                workflow,
                "--ref",
                expected_sha,
                "-f",
                "run_id=0",
                "-f",
                f"probe_scenario={scenario}",
                "-f",
                f"correlation_id={correlation}",
            ],
            check=True,
        )
        matched: dict[str, object] | None = None
        for _ in range(60):
            runs = _gh_json(
                [
                    "gh",
                    "run",
                    "list",
                    "--workflow",
                    workflow,
                    "--event",
                    "workflow_dispatch",
                    "--json",
                    "databaseId,displayTitle,event,headSha,status,conclusion",
                    "--limit",
                    "30",
                ]
            )
            run_documents = cast(list[dict[str, object]], runs)
            candidates = [run for run in run_documents if correlation in str(run["displayTitle"])]
            if len(candidates) > 1:
                raise RuntimeError("CI_RCA_PROBE_AMBIGUOUS_RUN")
            if candidates and candidates[0]["status"] == "completed":
                matched = candidates[0]
                break
            time.sleep(5)
        if not matched:
            raise RuntimeError("CI_RCA_PROBE_RUN_TIMEOUT")
        expected_conclusion = "failure" if scenario == "malformed" else "success"
        if (
            matched["event"] != "workflow_dispatch"
            or matched["headSha"] != expected_sha
            or matched["conclusion"] != expected_conclusion
        ):
            raise RuntimeError("CI_RCA_PROBE_CORRELATION_MISMATCH")
        print(json.dumps({"scenario": scenario, "correlation_id": correlation, "run_id": matched["databaseId"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
