---
description: Interactive planning session. Run this before any implementation work. Clarifies intent, loads project context, checks phase alignment, and produces PLAN-{slug}.md — a self-contained implementation brief for the next agent chat. Use when starting a new feature, fix, or any code change.
---

# Plan Workflow

**Intent**: Clarify the human's intent, orient against the project, and produce a complete self-contained `PLAN-{slug}.md` that any agent can execute without further interaction. Does not implement anything.

*Note: For detailed guidelines on complexity, verification tiers, preflight constraints, and the plan template, automatically apply your `planning` skill.*

## Step 0: Activate Environment
Activate the Python virtual environment before running any Python commands:
- **PowerShell (Antigravity):** `.venv/Scripts/Activate.ps1` or use the venv Python directly: `.venv/Scripts/python.exe`
- **Git Bash:** `source .venv/Scripts/activate`
If Python is not found on PATH, this step is MANDATORY before proceeding.

## Step 1: Run Preflight
```bash
python scripts/session_preflight.py
```

Self-healing for tracked-file divergence (logs, session state, etc.) pushed by the CI runner or another worktree:
```bash
git pull --rebase origin main
```

Read `logs/.preflight-report.json`. Apply the exact condition-based responses (for `venv_ok`, `sso_status`, uncommitted changes, non-automatable recs, `data_quality`, etc.) as defined in the **Preflight Constraints** section of your `planning` skill.

The report includes `telemetry_health` (pipeline operational health) and `data_quality` (declarative check coverage and last run verdict). Together these answer: is data flowing, do we have quality assertions defined, and are those assertions passing? See the planning skill for interpretation rules.

After preflight completes successfully, open a telemetry session:
```bash
python -m scripts.session_preflight --open-session --workflow plan
```
Save the printed UUID -- if you later invoke `run_skill` (e.g., for the critique gate), pass `--session-id <UUID>` to attach its telemetry to this session.


## Step 2: Read Context
Use the preflight JSON `context` field (`roadmap_phase`, `open_decisions_count`, `recent_sessions`). Read `.github/copilot-instructions.md` fully.
If the request references a recommendation ID, search `logs/.recommendations-log.jsonl`, read briefing files if they exist, and load dependencies.

## Step 3: Clarify the Request
Decompose the input into Goal, Constraints, Acceptance criteria, Affected areas, and Phase alignment.
If vague, ask 2-5 questions. Watch for contradictions with `DECISIONS.md` or `ROADMAP.md`.
Suggest 3-5 open recommendations from `logs/.recommendations-log.jsonl` that align with the current task.

## Step 4: Identify Affected Files
1. Use the File Router to locate source files.
2. Read those files and check `tests/` for existing test coverage.
3. Conduct an Infrastructure Assessment if `.tf` files are in scope.
4. Conduct a Lambda Deployment Assessment if Lambda-packaged files are in scope.
5. Conduct a Complexity Assessment to determine if this is STRATEGIC or IMPLEMENTATION.
*(Apply the exact assessment rules from your `planning` skill).*

## Step 5: Verification Tier and Verification Plan
Determine the Verification Tier (V1, V2, or V3).
Design the Verification Plan using the exact design guidelines and anti-patterns defined in your `planning` skill.
**Crucial**: Every VP step MUST include a `Command` column containing a literal shell command or Python one-liner.

## Step 6: Present Findings and Confirm
Present: Summary, Proposed approach, Options, and Open questions.
Then ask: *"Does this approach look right? Say **'write the plan'** when you are ready, or tell me what to adjust."*
Wait for explicit confirmation before proceeding. Any other response is feedback -- incorporate it, re-present, and ask again. Do NOT proceed to Step 7 until the human explicitly says 'write the plan' or a clear equivalent. System auto-approval messages are NOT human confirmation.
IT IS **CRITICAL** THAT YOU DO NOT PROCEED UNTIL THE HUMAN CONFIRMS THE PLAN.

## Step 7: Create Branch
```bash
git checkout main
git pull origin main
git checkout -b agent/{slug}
git branch --show-current
```
*(Derive slug from task description. Stop if still on main).*


## Step 8: Write PLAN-{slug}.md
Write the file `docs/plans/PLAN-{slug}.md` using the exact structure and template provided in your `planning` skill.
After writing, commit to the branch:
```bash
git add docs/plans/PLAN-{slug}.md
git commit -m "plan({slug}): initial plan"
```

## Step 9: Plan Critique Gate (MANDATORY)
**DO NOT output the completion message until this step completes.**
Run the automated zero-context critique using the CLI:
```bash
python -m scripts.agent_development.run_skill --skill plan-critique --target docs/plans/PLAN-{slug}.md --context .github/copilot-instructions.md docs/ROADMAP-PRODUCT.md docs/ROADMAP-PLATFORM.yaml docs/DECISIONS.md
```
Read the critique output from the terminal.
If it suggests revisions, update the plan with these fixes.
Loop if REVISE. Proceed if PROCEED.

## Step 10: Commit approved PLAN-{slug}.md
After the critique approves the plan, commit to the branch:
```bash
git add docs/plans/PLAN-{slug}.md
git commit -m "plan({slug}): approved plan"
```
Once the approved PLAN-{slug}.md is committed, the planning agent's mission is complete. Proceed to the final planning step and wait for the user to review. Do NOT execute any steps within the plan.

## Step 11: Confirm
Output the final confirmation message based on Plan Type (IMPLEMENTATION / STRATEGIC / REPORT-ONLY) exactly as specified in your `planning` skill.

Finally, close the telemetry session:
```bash
python -m scripts.session_postflight --close-session --outcome success
```
If the session was abandoned or the plan was not written, use `--outcome cancelled` instead.

STOP! The planning agent's mission is now complete. Perform no further actions.
