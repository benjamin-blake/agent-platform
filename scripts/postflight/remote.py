# complexity-waiver: decision-43
"""Remote push/PR/CI concern: push, create PR, poll CI, squash-merge.

Moved verbatim from scripts/session_postflight.py (SLOC decomposition, PLAN-sloc-session-postflight).
This is the executor-era gh-CLI automation surface, distinct from the CC-web MCP merge flow used by
the /implement Git-ops procedure; the legacy poll loop moves as-is, not redesigned.
"""

from __future__ import annotations

import json
import re
import time

from scripts.postflight import _common


def run_push() -> int:
    """Push branch, create PR, poll CI, auto-merge on green."""
    branch = _common._current_branch()

    # Push (set upstream if needed)
    push_result = _common._run(["git", "push", "--set-upstream", "origin", branch])
    if push_result.returncode != 0:
        output = {"status": "push_failed", "error": push_result.stderr.strip()}
        print(json.dumps(output, indent=2))
        return 1

    # Get PR intent from plan file
    pr_title = branch
    pr_body = f"Automated PR for branch `{branch}`."
    plan_file = _common.find_plan_file()
    if plan_file and plan_file.exists():
        content = plan_file.read_text(encoding="utf-8")
        intent_match = re.search(r"## Intent\s*\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
        if intent_match:
            intent = intent_match.group(1).strip()
            slug = branch[len("agent/") :] if branch.startswith("agent/") else branch
            pr_title = f"feat: {slug}"
            pr_body = intent[:300]

    # Create PR
    pr_result = _common._run(["gh", "pr", "create", "--title", pr_title, "--body", pr_body, "--base", "main"])
    if pr_result.returncode != 0:
        # PR may already exist
        if "already exists" not in pr_result.stderr.lower():
            output = {"status": "pr_failed", "error": pr_result.stderr.strip()}
            print(json.dumps(output, indent=2))
            return 1

    # Get PR URL
    pr_view = _common._run(["gh", "pr", "view", "--json", "url,number"])
    pr_url = ""
    pr_number = ""
    if pr_view.returncode == 0:
        try:
            pr_data = json.loads(pr_view.stdout)
            pr_url = pr_data.get("url", "")
            pr_number = str(pr_data.get("number", ""))
        except (json.JSONDecodeError, KeyError):
            pass

    # Poll CI — wait for ALL required PR checks to complete before merging.
    # Uses gh pr view --json statusCheckRollup: gives per-check status (COMPLETED/IN_PROGRESS)
    # and conclusion (SUCCESS/FAILURE/NEUTRAL/etc.) — works reliably on this repo's gh version.
    # This prevents merging when only the fastest check (e.g. Pre-commit, 47s) passes while
    # slower checks (e.g. CI validate-python, ~4min) are still running.
    deadline = time.time() + _common.CI_POLL_TIMEOUT_SECONDS
    run_id = ""
    _OK_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
    while time.time() < deadline:
        sr_result = _common._run(["gh", "pr", "view", pr_number, "--json", "statusCheckRollup"])
        if sr_result.returncode == 0 and sr_result.stdout.strip():
            try:
                sr_data = json.loads(sr_result.stdout)
                checks = sr_data.get("statusCheckRollup", [])
                if checks:
                    # Best-effort run ID for the failure report
                    runs_result = _common._run(
                        ["gh", "run", "list", "--branch", branch, "--json", "databaseId", "--limit", "5"]
                    )
                    if runs_result.returncode == 0 and runs_result.stdout.strip():
                        runs = json.loads(runs_result.stdout)
                        if runs:
                            run_id = str(runs[0].get("databaseId", ""))

                    pending = [c for c in checks if c.get("status", "") != "COMPLETED"]
                    failures = [
                        c for c in checks if c.get("status") == "COMPLETED" and c.get("conclusion", "") not in _OK_CONCLUSIONS
                    ]

                    if pending:
                        pass  # Some checks still running — keep polling
                    elif failures:
                        failed_names = [c.get("workflowName", c.get("name", "?")) for c in failures]
                        _common.clear_checkpoint()
                        output = {
                            "status": "ci_failed",
                            "run_id": run_id,
                            "error_summary": f"Failed checks: {', '.join(failed_names)}",
                            "pr_url": pr_url,
                        }
                        print(json.dumps(output, indent=2))
                        return 1
                    else:
                        # All checks completed with passing conclusions — safe to merge
                        merge_result = _common._run(["gh", "pr", "merge", pr_number, "--squash", "--auto", "--delete-branch"])
                        _common.clear_checkpoint()
                        if merge_result.returncode == 0:
                            output = {"status": "merged", "pr_url": pr_url, "run_id": run_id}
                        else:
                            output = {"status": "merge_failed", "pr_url": pr_url, "error": merge_result.stderr.strip()}
                        print(json.dumps(output, indent=2))
                        return 0 if merge_result.returncode == 0 else 1
            except (json.JSONDecodeError, KeyError, IndexError):
                pass
        time.sleep(_common.CI_POLL_INTERVAL_SECONDS)

    # Timeout — clear checkpoint so the next session isn't blocked
    _common.clear_checkpoint()
    output = {
        "status": "ci_timeout",
        "run_id": run_id,
        "pr_url": pr_url,
        "error_summary": f"CI did not complete within {_common.CI_POLL_TIMEOUT_SECONDS}s",
    }
    print(json.dumps(output, indent=2))
    return 1
