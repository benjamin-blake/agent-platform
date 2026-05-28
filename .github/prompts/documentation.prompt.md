---
name: documentation
description: "Entry point for all documentation tasks. Automatically routes to the correct workflow: documentation_update for feature branches and PRs, or documentation_full_audit for whole-repository health checks. Use this instead of calling either sub-prompt directly."
agent: agent
model: GPT-5 mini
tools: ['execute/getTerminalOutput', 'execute/runInTerminal', 'read', 'edit/editFiles', 'search', 'agent']
---

## Intent

Entry point for all documentation tasks. Routes to `documentation_update` or `documentation_full_audit` based on context. Does not execute documentation work directly.

---

## YOUR TASK: Determine the Correct Documentation Workflow

Before doing anything else, determine which workflow applies using the decision tree below. Once you have determined the correct workflow, load and execute it in full — do not summarise or paraphrase it.

---

## Decision Tree

### Signal 1 — Check for an active feature branch

Run:
```bash
git diff origin/main --name-only
```

- **If the output lists changed files** → the user is on a feature branch with uncommitted or un-documented changes. Use **`documentation_update`**.
- **If the output is empty** → there are no undocumented branch changes. Proceed to Signal 2.

### Signal 2 — Check for an explicit audit request

If the user's message contains any of the following signals, use **`documentation_full_audit`**:
- "audit", "health check", "drift", "out of date", "stale docs", "review all", "full review", "everything", "whole repo", "all READMEs"

If the user's message contains any of the following signals, use **`documentation_update`**:
- "PR", "pull request", "branch", "just merged", "just added", "feature", "just changed", specific file names

### Signal 3 — If still ambiguous, ask exactly one question

Ask:
> "Do you want to document a specific set of recent code changes (feature branch / PR), or run a full health-check of all repository documentation?"

Map the answer:
- "Recent changes / branch / PR" → **`documentation_update`**
- "Full health-check / audit / all docs" → **`documentation_full_audit`**

---

## Routing

Once the correct workflow is determined, load and follow it completely:

- **`documentation_update`** → follow all instructions in [documentation_update.prompt.md](./documentation_update.prompt.md)
- **`documentation_full_audit`** → follow all instructions in [documentation_full_audit.prompt.md](./documentation_full_audit.prompt.md)

Do not stop after routing. Execute the selected workflow end-to-end, including its Phase 5 cleaning and commit.
