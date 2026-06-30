"""Wrapper to invoke Copilot CLI /delegate, capture PR URL, poll for completion.

Boundary contract: docs/contracts/delegate-cli.md

/delegate runs the agent remotely so there is no local transcript or OTel
capture. Mitigation: capture the PR URL from CLI output, poll via gh CLI for
merge status, and write commit/diff stats to logs/.delegate-telemetry.jsonl.

Windows subprocess: uses subprocess.Popen + proc.communicate(timeout=N) +
kill_process_tree(pid) as required by AGENTS.md/PROJECT_CONTEXT.md Known Gotchas.
subprocess.run(timeout=N) does NOT cascade termination on Windows.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.llm_utils import kill_process_tree

ROOT = Path(__file__).parent.parent
TELEMETRY_LOG = ROOT / "logs" / ".delegate-telemetry.jsonl"

# Regex to extract a GitHub PR URL from /delegate output
_PR_URL_RE = re.compile(r"https://github\.com/[^\s]+/pull/\d+")


def delegate_task(prompt: str, rec_id: str) -> dict:
    """Invoke Copilot CLI /delegate and capture the PR URL.

    Args:
        prompt: Task description including rec ID, acceptance criteria, and
            validation requirements.
        rec_id: Recommendation ID (e.g. 'rec-042') for telemetry linkage.

    Returns:
        {"pr_url": str, "status": "delegated", "rec_id": str} on success.
        {"error": str, "status": "failed", "rec_id": str} on failure.

    Input semantics: see docs/contracts/delegate-cli.md.
    Why this delivery mechanism: /delegate creates a branch+PR remotely;
    the PR URL is the only audit hook available without a local transcript.
    What goes wrong if semantics differ: if the task description omits
    acceptance criteria, the remote agent has no pass/fail signal and may
    merge broken code silently.
    """
    import shutil

    copilot_path = shutil.which("copilot")
    if not copilot_path:
        return {
            "error": "copilot CLI not found in PATH",
            "status": "failed",
            "rec_id": rec_id,
        }

    # /delegate is an interactive-mode slash command; pass via -i with the
    # slash command inline.  The task prompt is safely embedded in the
    # /delegate argument string -- no @file needed here because the task
    # description is intentionally short (rec ID + acceptance criteria).
    cmd = [copilot_path, "-i", f"/delegate {prompt}"]

    try:
        with subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=120)
            except subprocess.TimeoutExpired:
                kill_process_tree(proc.pid)
                proc.wait()
                return {
                    "error": "delegate timed out after 120s",
                    "status": "failed",
                    "rec_id": rec_id,
                }
    except OSError as exc:
        return {"error": str(exc), "status": "failed", "rec_id": rec_id}

    combined = stdout + stderr
    match = _PR_URL_RE.search(combined)
    if match:
        return {"pr_url": match.group(), "status": "delegated", "rec_id": rec_id}

    return {
        "error": f"No PR URL found in output: {combined[:500]}",
        "status": "failed",
        "rec_id": rec_id,
    }


def poll_delegate_pr(pr_url: str, timeout_secs: int = 600) -> dict:
    """Poll a PR URL via gh CLI until it is merged, closed, or timeout.

    Args:
        pr_url: GitHub PR URL returned by delegate_task().
        timeout_secs: Maximum seconds to wait before returning status=failed.

    Returns:
        {"status": "merged" | "open" | "closed" | "failed",
         "commits": int, "ci_status": str}

    Why gh CLI: the gh CLI provides structured JSON output for PR state and
    checks -- it is the correct boundary for this use case. The GitHub API
    directly would require PAT injection into this script.
    What goes wrong if semantics differ: if gh CLI is not authenticated, this
    will fail with an exit-code error; the caller should surface that as
    status=failed without crashing.
    """
    import time

    deadline = time.monotonic() + timeout_secs
    interval = 30  # seconds between polls

    while time.monotonic() < deadline:
        result = subprocess.run(
            ["gh", "pr", "view", pr_url, "--json", "state,commits,statusCheckRollup"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            return {
                "status": "failed",
                "commits": 0,
                "ci_status": f"gh error: {result.stderr[:200]}",
            }

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "status": "failed",
                "commits": 0,
                "ci_status": f"json parse error: {result.stdout[:200]}",
            }

        state = data.get("state", "").lower()
        commits = len(data.get("commits", []))
        checks = data.get("statusCheckRollup", [])
        ci_state = checks[0].get("conclusion", "pending") if checks else "unknown"

        if state == "merged":
            return {"status": "merged", "commits": commits, "ci_status": ci_state}
        if state == "closed":
            return {"status": "closed", "commits": commits, "ci_status": ci_state}

        time.sleep(interval)

    return {"status": "failed", "commits": 0, "ci_status": "timeout"}


def capture_delegate_telemetry(pr_url: str, rec_id: str) -> None:
    """Extract commit messages and diff stats from a merged PR and write to JSONL.

    Args:
        pr_url: GitHub PR URL of the merged delegate PR.
        rec_id: Recommendation ID for audit linkage.

    Writes one JSON line to logs/.delegate-telemetry.jsonl with:
        timestamp, rec_id, pr_url, commits (list of messages), diff_additions,
        diff_deletions, ci_status.
    """
    commits_result = subprocess.run(
        ["gh", "pr", "view", pr_url, "--json", "commits,statusCheckRollup,additions,deletions"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    entry: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rec_id": rec_id,
        "pr_url": pr_url,
        "commits": [],
        "diff_additions": 0,
        "diff_deletions": 0,
        "ci_status": "unknown",
    }

    if commits_result.returncode == 0:
        try:
            data = json.loads(commits_result.stdout)
            entry["commits"] = [c.get("messageHeadline", "") for c in data.get("commits", [])]
            entry["diff_additions"] = data.get("additions", 0)
            entry["diff_deletions"] = data.get("deletions", 0)
            checks = data.get("statusCheckRollup", [])
            entry["ci_status"] = checks[0].get("conclusion", "unknown") if checks else "unknown"
        except (json.JSONDecodeError, KeyError):
            pass

    TELEMETRY_LOG.parent.mkdir(parents=True, exist_ok=True)
    with TELEMETRY_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")

    print(f"[delegate_runner] telemetry written: {TELEMETRY_LOG.name} ({rec_id})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Delegate a recommendation to Copilot CLI /delegate")
    parser.add_argument("--rec-id", required=True, help="Recommendation ID (e.g. rec-042)")
    parser.add_argument("--prompt", required=True, help="Task description for /delegate")
    parser.add_argument("--poll", action="store_true", help="Poll the PR until merged or closed")
    args = parser.parse_args()

    result = delegate_task(args.prompt, args.rec_id)
    print(json.dumps(result, indent=2))

    if result.get("status") == "delegated" and args.poll:
        pr_url = result["pr_url"]
        print(f"Polling PR: {pr_url}")
        poll_result = poll_delegate_pr(pr_url)
        print(json.dumps(poll_result, indent=2))

        if poll_result.get("status") == "merged":
            capture_delegate_telemetry(pr_url, args.rec_id)


if __name__ == "__main__":
    main()
