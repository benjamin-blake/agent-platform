---
name: implement
description: Implements IMPLEMENTATION plans directly or scopes STRATEGIC plans into atomic recommendations for the executor. Run after /plan.
---

# Implement Workflow

**Intent**: For IMPLEMENTATION plans: execute the Ordered Execution Steps directly. For STRATEGIC plans: research Work Areas and produce atomic, automatable recommendations for the executor.

*Note: For detailed guidelines on how to execute each step below, automatically apply your `implement` skill.*

## Step 0: Activate Environment
Activate the Python virtual environment before running any Python commands:
- **PowerShell (Antigravity):** `.venv/Scripts/Activate.ps1` or use the venv Python directly: `.venv/Scripts/python.exe`
- **Git Bash:** `source .venv/Scripts/activate`
If Python is not found on PATH, this step is MANDATORY before proceeding.

## Step 1: Run Preflight
```bash
python scripts/session_preflight.py
```
Read `logs/.preflight-report.json` and handle constraints as defined in the **Preflight Constraints** section of your `implement` skill.

After preflight completes successfully, open a telemetry session:
```bash
python -m scripts.session_preflight --open-session --workflow implement
```
Save the printed UUID for use with `--session-id` in any `run_skill` invocations during this session.

## Step 2: Load PLAN File
```bash
git branch --show-current
```
If the result is `main`, STOP.
Find the plan file: `docs/plans/PLAN-${SLUG}.md`. Read the entire file. Extract Intent, Plan Type, Verification Tier, Work Areas (STRATEGIC) or Execution Steps (IMPLEMENTATION), Verification Plan, and Constraints.
**If no plan file exists, STOP.**
Also read `.github/copilot-instructions.md` (using the venv Python path for any script commands) and `docs/DECISIONS.md` before proceeding.

## Step 3: Dispatch by Plan Type

### For IMPLEMENTATION Plans
1. Count Scope files and estimated steps.
2. Present summary of scope to the human, and explicitly state you are executing autonomously without breaking into recs. Include a fun titbit to confirm understanding.
3. Execute each Ordered Execution Step sequentially.
4. Proceed to Step 4.

### For STRATEGIC Plans
1. Research each Work Area by reading files/modules.
2. Identify dependencies.
3. Break into atomic recs (effort `<= M`).
4. Write full context (executor should not need to read the plan).
5. Define acceptance command and verification steps.
6. Apply the **Quality Gate Validation**, **Dedup Gate**, and **JIT Context Injection** from your `implement` skill.
7. File approved recs using `python scripts/ops_data_portal.py`. For recs `> M` effort, create `docs/plans/briefings/BRIEFING-rec-NNN.md`.
8. Skip Steps 4-5 and proceed directly to Step 6.

## Step 4: Verification Plan (IMPLEMENTATION only -- MANDATORY)
**You MUST execute this step. Do not skip it.**
Execute the Verification Plan from the PLAN-{slug}.md file. Apply the strict **Live Verification Protocol** from your `implement` skill.
Produce the VP Compliance Table. If ANY row is FAIL, fix and re-verify. If BLOCKED, wait for human.

## Step 5: Code Review (IMPLEMENTATION only -- MANDATORY)
**You MUST trigger the code-review skill immediately after verification passes. Do not wait for the human to ask.**
```bash
python -m scripts.agent_development.run_skill --skill code-review
```
Read the findings output. You MUST implement fixes for all **Critical** and **High** priority findings before proceeding.
Medium and Low findings should be filed as recommendations using `python scripts/ops_data_portal.py`.

## Step 6: Final Validation
**You MUST run validation. Do not skip this step.**
```bash
python -m scripts.validate --pre
```
Must exit 0 before continuing. If it fails, fix the issues and re-run.

## Step 7: Commit, PR, and Merge
**You MUST execute the commit flow autonomously once Step 6 passes. Do not stop to ask for permission.**
Apply the appropriate **Commit Flow** (STRATEGIC or IMPLEMENTATION) defined in your `implement` skill.

## Step 8: Capture Friction
Record friction (parsing errors, ambiguous areas, bugs found) as a process event emitted to `telemetry_process_events` via the executor telemetry API. If no friction, this step is a no-op.

**RCA-First Protocol (Decision 55):**
If the friction was a recurring gap or unrecoverable failure, you MUST invoke the RCA skill via `python -m scripts.agent_development.run_skill --skill executor-rca` to diagnose the root cause and file a permanent fix. Do NOT silently workaround structural issues.

Friction logs will be committed to the current branch and pushed automatically via the `session_postflight.py` flow during Step 7, or you can flush them manually:
```bash
python scripts/session_postflight.py --log-housekeeping
```

## Step 9: Report and Close Session
Output the final report:
- **STRATEGIC**: Total recs filed, breakdowns, briefing files created, and next step instructions.
- **IMPLEMENTATION**: Files changed, verification results (actual outcomes per step), code review findings fixed, bugs fixed, design decisions.

Finally, close the telemetry session:
```bash
python -m scripts.session_postflight --close-session --outcome success
```
Use `--outcome failure` if the session ended with unresolved errors. Use `--outcome cancelled` if abandoned.
