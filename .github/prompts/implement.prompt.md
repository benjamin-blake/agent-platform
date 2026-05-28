---
name: implement
description: "Implements IMPLEMENTATION plans directly or scopes STRATEGIC plans into atomic recommendations for the executor. Run after /plan."
model: Claude Sonnet 4.6 (copilot)
agent: agent
tools: ['read', 'edit', 'vscode', 'search', 'execute/runInTerminal', 'execute/getTerminalOutput', 'agent', 'todo']
---

## Intent

For IMPLEMENTATION plans: execute the Ordered Execution Steps directly. For STRATEGIC plans: research Work Areas and produce atomic, automatable recommendations for the executor.

---

## Behavioural Invariants

```yaml
# Machine-readable invariants verified by scripts/prompt_compliance.py
preflight_run: true      # session_preflight.py must run at Step 0
never_on_main: true      # no file edits while on main branch
no_code_changes: false   # IMPLEMENTATION plans execute steps directly
```

---

## Step 0: Run Preflight

```bash
python scripts/session_preflight.py
```

Read `logs/.preflight-report.json` and handle: if `venv_ok: false`, activate venv and retry once (STOP on second failure). If `sso_status: "expired"`, run `aws sso login --profile company-aws-profile` (STOP on failure). If `uncommitted_changes` non-empty, surface and ask human. Continue on all other conditions.

After preflight completes, open a telemetry session:
```bash
python -m scripts.session_preflight --open-session --workflow implement
```
Save the printed UUID for `--session-id` in any `run_skill` invocations.

---

## Step 1: Load PLAN File

```bash
git branch --show-current
```

If the result is `main`, STOP:

> "Branch gate failed: currently on `main`. Check out the correct branch or re-run `/plan`."

Find the plan file: `docs/plans/PLAN-${SLUG}.md`. Read the entire file. Extract:

- Intent (verify alignment with North Star)
- Plan Type
- Verification Tier
- Work Areas table (for STRATEGIC) or Ordered Execution Steps (for IMPLEMENTATION)
- Verification Plan table
- Constraints and Context

**If no plan file exists, STOP:**

> "No plan found for branch `{branch}`. Expected `docs/plans/PLAN-{slug}.md`. Run `/plan` first."

Also read `.github/copilot-instructions.md` and `docs/DECISIONS.md` before proceeding.

---

### IMPLEMENTATION Plans

If `Plan Type` is `IMPLEMENTATION`:

1. Read the plan's Ordered Execution Steps section
2. Count Scope files and estimated steps
3. Present to the human:
   - A summary of the plan scope (files, steps, effort)
   - A statement: "This is an IMPLEMENTATION plan. I'm going to autonomously execute the steps as written, without breaking them down into recs."
   - A fun titbit of information to confirm that you have read, understood and are following the instructions.
4. Execute each Ordered Execution Step sequentially. Make the edits described in each step using `replace_string_in_file` or `create_file`. Run unit tests and acceptance criteria verification commands as you go.
5. **Execute the Verification Plan** (MANDATORY -- see Step 5 below). After all code changes pass tests, run each step from the plan's `## Verification Plan` table. If any step fails, diagnose the bug, fix the code, re-run tests, and re-attempt verification. Loop until all verification steps pass. Do NOT proceed to merge with failing verification.
6. SKIP Steps 2-4 below (those are for STRATEGIC scoping).
7. Proceed directly to Step 6 (Validate, Commit, and Merge) using the **IMPLEMENTATION commit flow**.

### STRATEGIC Plans

If `Plan Type` is `STRATEGIC`, proceed to Step 2.

---

## Step 2: For Each Work Area (STRATEGIC only)

For each row in the Work Areas table:

1. **Research the scope** -- Read the files/modules listed. Understand the current state.
2. **Identify dependencies** -- What must be done first? What can be parallelised?
3. **Break into atomic recs** -- Each rec should have effort `<= M`. Prefer `S` or `XS`.
4. **Write full context** -- Each rec must have enough context for the executor to work alone without reading this plan.
5. **Define acceptance command** -- Must be a single inline command (no prose after the backtick) that returns 0 on success. The command must be **behavioural** (exercise the feature), not **structural** (grep for text). If the rec creates a queryable resource, the acceptance command must query it. If it creates a callable endpoint, the acceptance command must call it.
6. **Define verification steps** -- For each rec, include in the `context` field a description of how the executor should verify the feature works beyond unit tests. Example: "After implementing, run `python -m scripts.sync_ops --dry-run` with the test config and confirm output contains 3 synced records."

---

## Step 3: Create Briefing Files (STRATEGIC only)

For any rec with estimated effort `> M` that cannot be broken down further:

- Create `docs/plans/briefings/BRIEFING-rec-NNN.md`
- Include: detailed problem statement, solution approach, files to modify table, test strategy
- Reference the briefing path in the rec's `context` field

---

## Step 4: File Recs to Log (STRATEGIC only)

Append all recs to `logs/.recommendations-log.jsonl` following the schema in `copilot-instructions.md`.

Verify each rec has:
- `automatable: true` (if not, explain why in `context` and flag explicitly)
- `acceptance` command: single inline backtick command, no trailing prose
- `dependencies` array (may be empty `[]`)
- Complete `context` (executor should not need to read this plan)
- `status: "open"`

Use sequential IDs: read the last `"id"` in the JSONL file and increment.

### Dedup Gate

Before appending each rec, search for open recs targeting the same file with at least 3 keyword matches in title + context. If duplicates found:
- Surface: "Found potential duplicate(s): rec-XXX. Options: (1) supersede existing, (2) file both, (3) skip this one?"
- Wait for human response before proceeding.
- If option (1): update the existing rec's `status` to `"superseded"` and add `"resolution": "superseded by rec-NNN"`, then file the new rec.
- If option (2): file both recs as-is.
- If option (3): skip filing this rec and continue to the next Work Area.

### Quality Gate Validation

Before appending each rec, apply this gate. If ANY check fails, report the issue and ask the human to fix it:

1. **Acceptance Command:** Must be a single inline command in backticks. FAIL if: contains `python -c`, contains `--pre` flag, has trailing prose, or uses line numbers.
2. **Target File:** Verify `"file"` field exists relative to repo root. FAIL if: file does not exist or path is absolute.
3. **Effort Threshold:** If `L` or `XL`, REQUIRE human confirmation before filing.
4. **Context Quality:** FAIL if context contains vague references ("the plan", "as discussed", "see above") or is < 50 characters.

---

## Step 5: Live Verification Protocol (ALL Plans -- MANDATORY)

After all code changes are complete and unit tests pass, the implementing agent MUST execute the Verification Plan from the plan file before proceeding to merge. This applies to ALL verification tiers. (For STRATEGIC plans with no code changes: verify recs are correctly filed and readable, then skip to Step 6.)

### Why This Exists

Unit tests with mocked dependencies hide real bugs. The only way to confirm a feature works is to exercise it. Examples:
- Athena view created but query returns 0 rows (wrong table reference)
- Rec logging portal built but submission fails (schema validation error)
- Lambda deployed but invocation times out (missing IAM permission)
- CLI command added but crashes with real input (edge case not covered by mocks)

### Protocol

1. **Read** the `## Verification Plan` table from PLAN-{slug}.md
2. **For each step:**
   a. Execute the action exactly as described
   b. Compare actual outcome to expected outcome
   c. If **PASS**: record the actual output and proceed
   d. If **FAIL**: diagnose root cause, fix the code, re-run `pytest` to confirm no regressions, re-attempt. Maximum 3 fix attempts per step. If still failing, STOP and report to the human with: what was attempted, error output, root cause hypothesis, suggested next steps.
3. **All verification steps must pass** before proceeding to Step 6.

### Tier-Specific Guidance

- **V1:** Parse configs, check doc links, confirm formatting. Quick but still mandatory.
- **V2:** Run the changed code path with real (non-mocked) input. Call new functions with sample data. Run new CLI commands with representative args. Confirm the feature works outside the test harness.
- **V3:** All V2 requirements PLUS deploy and invoke the live system. Follow iterative deploy-test-fix loop. Do not merge until invocation produces correct output. Acceptance commands must be behavioural, not structural.

### Anti-Patterns (Do NOT Accept These as "Verified")

- "Tests pass" -- proves the mock works, not the feature
- "File exists" -- existence is not correctness
- "No errors on import" -- loading is not verification
- "Grep found the expected string" -- structural, not behavioural
- "Terraform applied successfully" -- infrastructure existing is not enough
- Substituting a different, easier command for the one specified in the VP step -- protocol violation

### VP Compliance Gate (MANDATORY before Step 6)

Before proceeding to Step 6 (Validate, Commit, and Merge), produce a VP compliance table. This table must appear in the chat output and in the Step 8 report:

```
| VP# | Command Executed | Actual Output (truncated) | PASS/FAIL |
|-----|-----------------|---------------------------|----------|
| 1   | python -m scripts.verify_schema --table sessions | 30 columns, types OK...  | PASS     |
| 2   | python -m scripts.ops_writer --smoke-test | record written, compacted 1 row... | PASS     |
```

**Rules:**
- Every VP row from the plan must have a corresponding row in this table
- The "Command Executed" column must show the actual command that was run (not a description)
- The "Actual Output" column must show real terminal output (truncated to key lines if long)
- If ANY row is FAIL, do NOT proceed to Step 6
- If a VP step was skipped or is awaiting a human-gated action (e.g., terraform apply), mark it BLOCKED and explain. Do NOT merge until all BLOCKED steps are resolved.
- **Substituting a different, easier command for a VP step is a protocol violation.** The command must match what the plan specified, or the agent must explain why a substitution is needed and get human approval.

### V3 Merge Gate

If the Verification Plan contains any V3 post-deploy steps (Terraform apply, Lambda deploy, Athena queries against live tables), the agent MUST NOT proceed to Step 6 until those steps are confirmed. The sequence is:

1. Complete all code changes and pre-deploy VP steps
2. Present the Terraform plan or Lambda deploy output to the human for approval
3. **WAIT** for human confirmation that the deploy succeeded
4. Execute ALL post-deploy verification steps (Athena queries, Lambda invocations, etc.)
5. Only then proceed to Step 6 (commit and merge)

Do NOT commit, push, or create a PR while V3 post-deploy verification steps are pending. The merge gate is: **all VP steps PASS, including post-deploy.**

---

## Step 6: Validate, Commit, and Merge

```bash
python -m scripts.validate --pre
```

Must exit 0 before continuing.

### STRATEGIC Commit Flow

```bash
git add logs/.recommendations-log.jsonl docs/plans/briefings/
git commit -m "scope({slug}): add recs for {work-area-summary}"
git push origin HEAD
gh pr create --title "scope({slug}): add recs for {work-area-summary}" --body "Recs filed by /implement scoping agent." --base main
gh pr merge --squash --delete-branch
git checkout main
git pull origin main
```

### IMPLEMENTATION Commit Flow

```bash
git add -A
git commit -m "feat({slug}): implement {brief-description}"
git push origin HEAD
gh pr create --title "feat({slug}): {brief-description}" --body "Implemented by /implement agent. Verification plan passed." --base main
gh pr merge --squash --delete-branch
git checkout main
git pull origin main
```

---

## Step 7: Capture Friction

Record friction as a structured process event:
```bash
python -c "
from scripts.executor.telemetry import emit_process_event
emit_process_event(tier='rework', category='<CATEGORY>', severity='warning', description='<DESCRIPTION>', detected_by='manual')
"
```
Use a category from the canonical enum in `docs/INTENT-telemetry-system.md`. If no friction, this step is a no-op.

---

## Step 8: Report

Output:

- **STRATEGIC:** Total recs filed, recs by effort level, any `automatable: false` recs (explain why), briefing files created, next step: "Run `/develop-executor` or `python -m scripts.execute_recommendation rec-NNN`"
- **IMPLEMENTATION:** Files changed, verification results (actual outcomes per step), bugs found and fixed during verification loop, any design decisions made

Finally, close the telemetry session:
```bash
python -m scripts.session_postflight --close-session --outcome success
```
Use `--outcome failure` if the session ended with unresolved errors. Use `--outcome cancelled` if abandoned.
