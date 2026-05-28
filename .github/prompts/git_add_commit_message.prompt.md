---
name: git_add_commit_message
description: Validates the working tree, stages all files, commits with an auto-generated message, and optionally pushes with a pull request description. Refuses to commit directly to main.
model: GPT-5 mini
---

## Intent

Validate, stage, commit (with pre-commit retry), and optionally push. Refuses commits to `main`. Produces a PR description on push.

---

## Branch Guard

Before doing anything else, run:

```bash
git branch --show-current
```

If the result is `main`, **stop immediately** and tell the user:

> "Direct commits to `main` are not permitted. Create a feature branch first: `git checkout -b agent/{slug}`"

Do not proceed until the user is on a non-`main` branch.

---

# Step 0: Validate
Run `python scripts/validate.py` from the repository root.
If any check fails, stop and fix the failures before proceeding. Do not stage broken code.

# Step 1: Add and Commit (with pre-commit retry)

Pre-commit hooks (ruff-format, trailing-whitespace, etc.) may modify files during commit. This is normal -- the hooks fix issues automatically. Expect 1-2 retries on first commits after code generation.

Loop until pre-commit passes cleanly:

1. Run `git add .`
2. Run `git commit -m "<message>"` where the message:
   - Starts with a conventional prefix: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, or `ci:`
   - Summarises what changed and why in one concise line
   - Does not exceed 72 characters
3. If commit succeeds (exit 0), proceed to Step 2
4. If pre-commit modified files and aborted, return to step 1 and retry
5. Maximum 3 retries -- if still failing, report pre-commit errors to the user

**This retry behavior is expected, not a bug.**

# Step 2: Gather Context from commit
Run `git diff HEAD~1` to review what was committed. Focus on WHY each change was made, not just what changed.

# Step 3: Pause
Ask the user: "Validation passed and commit created. Do you want to push?"

# Step 4: Gather context from main
If the user confirms push, run `git diff origin/main` to understand the full scope of changes on this branch relative to main. Focus on WHY the changes were made.

# Step 5: Push

Run `git push`.

**If this fails with "no upstream branch" error:** This is normal for first push to a new branch. Run:
```bash
git push --set-upstream origin <branch-name>
```

Note: If `python setup.py` has been run with `git config push.autoSetupRemote true`, this error will not occur.

Then provide the user with a pull request description they can paste into GitHub, structured as:

```
## Summary
[2-3 sentences: what changed and why]

## Changes
[Bulleted list of key changes]

## Testing
[How the changes were validated — mention scripts/validate.py outcome]
```

Note: GitHub MCP (`create_pull_request`) is not currently available in this workspace. PR creation is manual. When MCP becomes available, update this prompt to use it — MCP commits use GitHub server-side signing, eliminating the GPG password prompt. Track this in DECISIONS.md when MCP ships.

# Step 6: Return to Main

After push and PR description, return to main and pull to stay current:
```bash
git checkout main
git pull origin main
```

This ensures the next planning session starts from the latest main, ready for a new branch.

Report: "Returned to main. Ready for next task."
