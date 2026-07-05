# Boundary Contract: Copilot CLI /delegate

## Tool
GitHub Copilot CLI `/delegate` slash command (interactive mode via `copilot -i`)

## Input Semantics

| Argument | Semantics | Correct Use |
|----------|-----------|-------------|
| `/delegate "<task description>"` | Delegates the task to a remote Copilot agent that creates a branch, implements the changes, and opens a PR | Pass a clear task description including rec ID, acceptance criteria, and validation requirements |

## What We Send
A task description string that includes:
- The recommendation ID (e.g., `rec-042`)
- A concise description of the change required
- Acceptance criteria (what must pass for the task to be complete)
- Validation requirements (e.g., `python scripts/validate.py` must exit 0)

Example:
```
/delegate "Implement rec-042: add timeout parameter to fetch_data(). Acceptance: python -m pytest tests/test_data_pipeline.py -q passes. See docs/plans/PLAN-rec-042.md for full spec."
```

## What We Get Back
A PR URL pointing to the branch and PR created by the remote agent. Example output:
```
Delegated task. PR: https://github.com/owner/repo/pull/42
```
Or an error message if delegation fails.

## Why This Delivery Mechanism Is Correct
`/delegate` is the correct mechanism when:
1. The task is well-specified (rec with acceptance criteria, plan file)
2. Remote parallel execution is acceptable (task does not require local state)
3. The telemetry gap is acceptable and mitigated (PR URL captured for audit trail)

`/delegate` is NOT correct when the task requires access to local secrets, local file state not in the repo, or real-time human interaction during implementation.

## What Would Go Wrong If Semantics Differ
- If the task description is ambiguous, the remote agent may implement the wrong thing -- always include acceptance criteria
- If the acceptance command references local paths that don't exist in a fresh checkout, CI will fail -- use repo-relative paths only
- If rec-IDs are omitted, telemetry capture cannot link the PR back to the recommendation

## Telemetry Gap
`/delegate` runs the agent remotely. Local transcript/OTel capture is NOT available. Mitigation:
1. `delegate_runner.py` captures the PR URL from `/delegate` output
2. `poll_delegate_pr()` polls `gh pr view` to track status (merged/open/closed)
3. `capture_delegate_telemetry()` extracts commit messages and diff stats from the merged PR and writes to `logs/.delegate-telemetry.jsonl`

This provides an audit trail even without a local transcript.

## Doc Page
https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference#slash-commands-in-the-interactive-interface

## Date Last Verified
2026-04-08

## Related Files
- `scripts/delegate_runner.py` -- wrapper that calls `/delegate` and captures telemetry
- `logs/.delegate-telemetry.jsonl` -- per-PR audit trail written by `capture_delegate_telemetry()`
