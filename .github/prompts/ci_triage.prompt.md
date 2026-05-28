---
name: ci_triage
description: Dedicated CI failure investigation workflow. Fetch failing run logs, classify the failure, present a root cause analysis, and propose fixes. Use when a CI run has failed and you need to diagnose why.
agent: agent
model: GPT-5 mini
tools: ['read', 'edit/editFiles', 'search', 'execute/runInTerminal', 'execute/getTerminalOutput', 'agent']
---

## Intent

Investigate a failing GitHub Actions CI run, classify the failure type, present a root cause analysis to the human, and (after confirmation) apply the fix to both validate.py (prevention) and the failing code (cure).

---

## Step 1: Identify the Failing Run

Get the current branch:

```bash
git branch --show-current
```

**Primary path — GitHub MCP server** (if configured in `.vscode/mcp.json`):
Pass the branch name to the `list_workflow_runs` tool as the branch filter parameter. Retrieve the most recent failed run ID.

**Fallback path — `gh` CLI:**
```bash
gh run list --branch $(git branch --show-current) --limit 5
```

Identify all runs with `conclusion: failure`. If multiple runs have failed, work through them one at a time, starting with the most recent.

---

## Step 2: Fetch Logs

**Primary path — GitHub MCP server:**
Use `get_workflow_run_logs` with the failing run ID.

**Fallback path — `gh` CLI:**
```bash
gh run view <run-id> --log-failed
```

Identify:
- The exact failing job name
- The exact failing step name
- The full error message (extract the first 50 relevant lines)

---

## Step 3: Classify the Failure

Classify as exactly one of:

| Code | Meaning |
|------|---------|
| `VALIDATE_GAP` | Local `validate.py` should have caught this but didn't. Use only for code-correctness issues that a local check could detect. |
| `ENV_DIFFERENCE` | CI environment differs from local (OS, Python version, dependency pinning, missing tool). |
| `TEST_FLAKY` | Test is non-deterministic (timing, network, ordering). |
| `WORKFLOW_CONFIG` | Workflow YAML misconfiguration (wrong trigger, missing secret, bad path filter). |
| `DEPENDENCY` | Missing or incompatible package in CI environment. |

---

## Step 4: Root Cause Analysis

Present the following block to the human. Do NOT auto-apply any fix before showing this:

```
CI TRIAGE REPORT
================
Workflow:     <name>
Failing job:  <job name>
Failing step: <step name>
Error:        <truncated to relevant lines>
Classification: <VALIDATE_GAP | ENV_DIFFERENCE | TEST_FLAKY | WORKFLOW_CONFIG | DEPENDENCY>

Root cause:
  <1-2 sentences explaining why the failure occurred>

Why local validation missed this:
  <specific explanation — e.g. "validate.py does not run ruff on CI-equivalent Python 3.12.x"
   or "test uses real network call, CI has no outbound access">

Proposed remediation:
  1. Validate gap fix: <what to add/change in validate.py or tests/ to catch this class locally>
  2. CI failure fix: <specific file change to resolve the failing step>
```

Then ask:
> "Shall I proceed with these fixes? Say **'fix'** to apply both remediations, or tell me what to adjust."

---

## Step 5: Apply Fix (after confirmation)

1. Fix the validation gap in `scripts/validate.py` FIRST — so the same class of error is caught locally in future.
2. Fix the CI failure itself (code, test, workflow YAML, or requirements as appropriate).
3. Run `python scripts/validate.py` to confirm the new check passes locally.
4. Run `pytest tests/ -q` to confirm no regressions.
5. Commit with message: `fix(ci): <description> — closes validate.py gap for <classification>`
6. Push: `git push`

---

## Step 6: Verify

After the push, wait 90 seconds for CI to trigger and initialize, then poll until the run completes or 5 minutes have elapsed:

**Primary path — MCP:**
Re-run `list_workflow_runs` and check `conclusion` on the new run. If no new run appears after 90 seconds, check for workflow trigger issues (branch filter, changed files filter).

**Fallback path — `gh run watch`:**
```bash
gh run list --branch $(git branch --show-current) --limit 3
gh run watch <new-run-id>
```
`gh run watch` polls automatically — no manual sleep required.

If CI is still failing, present a new triage report for the next failure. Maximum 2 full triage cycles (fix → push → re-poll) before escalating.

---

## Step 7: Escalation

After 2 failed triage cycles without a green run:

- Stop the triage loop.
- Present a summary: what was tried, what was fixed, what is still failing.
- Instruct: "Check the workflow run logs directly at github.com — this failure requires manual investigation."
- Invoke `@retro-lite` with: the steps attempted, each triage classification made, why escalation was necessary.

---

## Constraints

- Never auto-apply a fix without the human confirmation gate in Step 4.
- Always fix the validate.py gap BEFORE fixing the CI failure itself.
- Do not skip the local `validate.py` / `pytest` run after applying fixes (Step 5 items 3-4).
- This prompt uses GPT-5 mini (free model). Reason thoroughly — this is mechanical CI debugging, not creative work.
