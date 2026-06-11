---
name: implement
description: Deep methodology for executing implementation plans, including live verification protocols, strategic scoping gates, code review integration, and commit flows.
---

# Implement Methodology & Rules

You are using this skill to augment the `/implement` workflow. Apply these deep instructions when executing the workflow steps. The workflow defines WHAT to do and in WHAT ORDER. This skill defines HOW to do each step.
You must treat every Turn as a cold-start. Disregard all system-generated conversation summaries and 'persistent memory' unless they are explicitly referenced by the USER in the current turn. If a file or task is not listed in the current IMPLEMENTATION plan's scope, you are forbidden from touching it, even if you believe it is a 'logical next step' or a cleanup from a previous session.

**Plan format (T1.11 / CD.22):** plans are `docs/plans/PLAN-{slug}.yaml`, schema-validated by `scripts/plan_document.py` (resolve via `scripts/find_plan.py`). If handed a legacy `PLAN-{slug}.md` path, emit a deprecation warning in the session output and proceed -- the .md path survives one release cycle, then is removed. Never author new .md plans. (This legacy mirror is updated as voluntary hygiene -- `.claude/skills/implement/SKILL.md` is canonical per Decision 76; no sync obligation exists.)

## Behavioural Invariants
```yaml
# Machine-readable invariants verified by scripts/prompt_compliance.py
preflight_run: true              # session_preflight.py must run at Step 1
never_on_main: true              # no file edits while on main branch
no_code_changes: false           # IMPLEMENTATION plans execute steps directly
review_as_scope: true            # Critical/High findings from code-review MUST be implemented immediately
auto_review_and_commit: true     # Proactively trigger review and commit once VP passes -- do not wait for human
```

## Preflight Constraints (Workflow Step 1)
When reading `logs/.preflight-report.json`, apply these conditionals:
- **`venv_ok: false`** -- Auto-activate venv and rerun preflight. If still false, STOP.
- **`creds_status: "unavailable"`** -- **Static-key recovery (non-fatal, Decision 60):** the static-key assume-role chain has no interactive login. Verify it with `aws sts get-caller-identity --profile agent_platform`; if the `agent_static` key was rotated, refresh `~/.aws/credentials`. Do NOT block -- continue in degraded mode (credential-dependent verifiers are skipped, emitting SKIPPED). Autonomous executors never attempt recovery.
- **`outbox_synced: false`** -- Run `python -m scripts.sync_ops pull` to drain outbox and sync ops data (Decision 51). If fails, STOP.
- **`uncommitted_changes` non-empty** -- Ask human: "Resume, stash, or discard?". Wait. Continue on all other conditions.

## Documentation Artefact Design

This repository is agent-first. When implementing documentation changes, apply these rules:

- Prefer extending an existing machine-readable source over creating a new document.
- A new file is warranted only when it has a distinct machine-parseable role (e.g., a
  decision manifest YAML, a registry YAML). Never create a human-readable companion
  alongside a machine-readable source -- that produces drift by design.
- Canonical field documentation pattern: ops.yaml extended contract. Add `description`
  and `semantics` metadata fields directly to the column entry in ops.yaml or
  telemetry.yaml. These fields are ignored by the DQ runner and consumed by agents.
  Do not create a separate briefing doc for the same information.
- When a plan step proposes a new document, ask: "Could this information be a metadata
  field in an existing YAML?" If yes, prefer that over a new file.

## Live Verification Protocol (Workflow Step 4 -- MANDATORY)
After all code changes are complete and unit tests pass, the implementing agent MUST execute the Verification Plan from the PLAN-{slug}.yaml file before proceeding to code review.

### Why This Exists (Rationale)
Acceptance commands prove the code landed (e.g. `grep` or `pytest`). Verification commands prove the feature works end-to-end. Examples of bugs that only verification catches:
- Athena view created successfully but returns 0 rows due to a bad filter
- Lambda deployed successfully but times out on invocation
- CLI script passes unit tests with mocks but crashes with real input

### Protocol
1. **For each step:**
   a. Execute the action exactly as described.
   b. Compare actual outcome to expected outcome.
   c. If **PASS**: record the actual output and proceed.
   d. If **FAIL**: diagnose root cause, fix the code, re-run `pytest` to confirm no regressions, re-attempt. Maximum 3 fix attempts per step. If still failing, STOP and report to the human.
2. **All verification steps must pass** before proceeding.

### Tier-Specific Guidance
- **V1:** Parse configs, check doc links, confirm formatting. Quick but mandatory.
- **V2:** Run the changed code path with real (non-mocked) input. Confirm the feature works outside the test harness.
- **V3:** All V2 requirements PLUS deploy and invoke the live system. Do not merge until invocation produces correct output.
- **Anti-Patterns:** Do NOT accept "Tests pass", "File exists", "No errors on import", or "Grep found expected string" as verified. Substituting an easier command for a VP step is a protocol violation.


### VP Failure Is Not Negotiable
If a VP step fails for ANY reason (including credential/environment issues), the status is FAIL.
There is no "graceful" failure, no "local pass", no "env blocked" — only PASS or FAIL.
If the failure is due to missing credentials or infrastructure, the agent MUST:
1. Attempt the documented recovery (verify the static-key chain: `aws sts get-caller-identity --profile agent_platform`; refresh `~/.aws/credentials` if the `agent_static` key was rotated)
2. Re-run the VP step
3. If still failing, mark FAIL and STOP — do not proceed, do not merge

### VP Compliance Gate
Before proceeding to code review (Step 5), produce a VP compliance table in the chat output:
```
| VP# | Command Executed | Actual Output (truncated) | PASS/FAIL |
```
- The "Command Executed" must be the actual shell command run.
- If ANY row is FAIL, do NOT proceed.
- If a VP step was skipped or is awaiting a human-gated action (e.g., terraform apply), mark it BLOCKED and wait.
- Lack of AWS credentials is NOT automatically a block. Verify the static-key chain with `aws sts get-caller-identity --profile agent_platform`; there is no interactive login to run (refresh `~/.aws/credentials` if `agent_static` was rotated).

### V3 Merge Gate
If the Verification Plan contains V3 post-deploy steps, execute the full sequence:
0. Confirm credentials are active with `aws sts get-caller-identity --profile agent_platform`. There is no interactive login in the static-key model; if the chain fails, refresh `~/.aws/credentials` (rotated `agent_static`) and re-verify.
1. Complete all pre-deploy VP steps.
2. Present the deploy output.
3. WAIT for human confirmation of deployment success.
4. Execute post-deploy VP steps.
Only when ALL steps pass can you proceed to code review.


## Code Review Protocol (Workflow Step 5 -- MANDATORY)
**You MUST trigger the code-review skill immediately after the Verification Plan passes. Do not wait for the human to prompt you.**

### Trigger
```bash
python -m scripts.agent_development.run_skill --skill code-review
```

### Handling Findings
- **Critical and High**: You MUST implement fixes for these findings before proceeding. They are mandatory extensions of the original plan. After fixing, re-run `python -m scripts.validate --pre` to confirm no regressions.
- **Medium and Low**: File these as new recommendations using `python scripts/ops_data_portal.py`. Do not fix them inline -- they will be addressed in future sessions.

### Rationale
This ensures that even "perfect" implementations are audited for repository-wide patterns (e.g., mock exhaustion, safety rules, scope creep) that the planner might have missed. The review also catches regression risks before they reach `main`.


## Strategic Scoping Rules (Workflow Step 3 -- STRATEGIC Plans only)

### JIT Context Injection
When breaking a STRATEGIC plan into atomic recommendations, explicitly review `.github/copilot-instructions.md`. Copy any relevant "Known Gotchas" or constraints directly into the recommendation's `context` field. Autonomous executors no longer read `copilot-instructions.md` by default, so they rely entirely on the JIT context you provide.

### Quality Gate Validation
Before filing each recommendation using `python scripts/ops_data_portal.py`, apply this gate. FAIL if any check fails:
1. **Acceptance Command:** Must be a single inline command in backticks. FAIL if: contains `python -c`, contains `--pre` flag, has trailing prose, or uses line numbers. Must be behavioural.
2. **Target File:** Verify `"file"` field exists relative to repo root.
3. **Effort Threshold:** If `L` or `XL`, REQUIRE human confirmation before filing.
4. **Context Quality:** FAIL if context is vague or < 50 characters.

### Dedup Gate
Before filing, search for open recs targeting the same file with at least 3 keyword matches. If duplicates found:
- Surface: "Found potential duplicate(s). Options: (1) supersede existing, (2) file both, (3) skip this one?" Wait for human.

## Commit Flows (Workflow Step 7 -- MANDATORY)
**Once validation passes (Step 6), you MUST execute the appropriate commit flow autonomously. Do not stop to ask for permission -- the plan was already approved during /plan.**

### STRATEGIC Commit Flow
```bash
git add docs/plans/briefings/
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
