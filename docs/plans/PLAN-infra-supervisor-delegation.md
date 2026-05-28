# Plan

## Intent
Close the critical gap in the autonomous self-improvement loop where supervisor architectural insights (hotfix routing, tool restriction, structured delegation) exist only in conversation history rather than as actionable recommendations. Formalizing these as recs with explicit dependency chains and phase tags enables the executor to autonomously evolve the supervisor from direct operator to orchestrator -- the prerequisite for the system to improve its own improvement process.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-supervisor-delegation

## Phase
Infrastructure -- Executor Stabilization (ongoing, post-Phase 1 completion)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| logs/.recommendations-log.jsonl | Modify | Append rec-412 through rec-418 with full schema, dependency chains, and phase tags |

## Bundled Recommendations
None -- this plan CREATES new recommendations rather than bundling existing ones.

## Acceptance Criteria
- [ ] rec-412 through rec-418 all present in logs/.recommendations-log.jsonl
- [ ] All 7 entries parse as valid JSON with required schema fields (id, date, title, source, effort, priority, status, automatable, risk, file, context, acceptance, tags)
- [ ] Dependency chains are correct: rec-414 depends on rec-413; rec-415 depends on rec-413 and rec-414; rec-417 depends on rec-413 and rec-414; rec-390 is referenced but not duplicated
- [ ] No existing rec is duplicated (checked against rec-368, rec-386, rec-390, rec-272, rec-367, rec-369, rec-372)
- [ ] `python -m scripts.validate --quick` passes
- [ ] All 7 recs have `"source": "brainstorm"` and `"date": "2026-04-16"`

## Constraints
- Must not duplicate work already captured by existing open recs (rec-368, rec-386, rec-390, rec-272)
- Must follow the recommendations log schema from copilot-instructions.md
- Acceptance commands must not use `python -c` (banned pattern per validate.py)
- Each rec must be independently actionable -- no implicit knowledge required from the conversation transcript
- Recs that modify .prompt.md files are `automatable: false` (human review required for process changes)

## Context
- Decision 42 (Three-Tier Architecture) established the /plan -> /implement -> /develop-executor workflow. The supervisor delegation recs strengthen Tier 3 by evolving /develop-executor from operator to orchestrator.
- rec-367 (failure budget, closed) and rec-369 (hotfix test requirement, closed) are Phase A prerequisites -- already done.
- rec-368 (infra-stabilize mode, open) covers the session-type separation but not the delegation mechanism.
- rec-386 (log_writer CLI, open) covers friction capture automation but not the broader delegation pattern.
- rec-390 (supervision cost tracking, open) is the Phase D telemetry enabler.
- The phased migration (A -> B -> C -> D) is deliberately gated on executor reliability -- each phase has prerequisites that must be closed before the next phase's recs become actionable.

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot-instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps

### Step 1: Append rec-412 through rec-418 to recommendations log

Append exactly 7 new JSONL entries to `logs/.recommendations-log.jsonl`. Each entry must be a single line of valid JSON. Use the schema from copilot-instructions.md. The entries are:

**rec-412: `execute_recommendation --next-batch` automated rec selection**
- effort: S, priority: High, automatable: true, risk: low
- file: scripts/execute_recommendation.py
- context: The supervisor currently reads the full JSONL, manually filters by status/automatable/risk/dependencies/effort, and selects recs. This is procedural work that a script should do. Add `--next-batch` flag to execute_recommendation.py that outputs a JSON array of recommended rec IDs based on: (a) status=open AND automatable=true AND risk=low, (b) dependencies all closed, (c) sorted by priority then effort (XS first), (d) limited to N recs (default 3, configurable). The supervisor calls this instead of manually parsing JSONL. Output format: `{"recommended": ["rec-XXX", "rec-YYY"], "skipped": [{"id": "rec-ZZZ", "reason": "dependency rec-AAA not closed"}]}`. This replaces the manual Phase 2 workflow in develop-executor.prompt.md with a single command. Independent of other recs in this batch.
- tags: executor, delegation, automation, batch-selection
- acceptance: `grep -q 'next.batch\|next_batch' scripts/execute_recommendation.py && python -m pytest tests/test_execute_recommendation.py -x -q`

**rec-413: `execute_recommendation --fast` mode for supervisor-filed XS hotfix recs**
- effort: M, priority: Critical, automatable: true, risk: medium
- file: scripts/execute_recommendation.py
- context: Phase B enabler for supervisor delegation. When the supervisor diagnoses a machinery failure, the current workflow is: (1) supervisor edits code directly via replace_string_in_file, (2) supervisor writes a regression test, (3) supervisor commits hotfix to main. This bypasses all quality gates (planning, critique, code review, validation). The --fast flag creates a lightweight executor path: (a) accepts a pre-built 1-step plan as JSON via stdin or --plan-json arg, (b) skips planning LLM call and critique cycle entirely, (c) runs implementation via normal copilot_call with the provided plan, (d) runs validation (validate.py), (e) runs acceptance check, (f) skips code review (supervisor already reviewed the diagnosis), (g) creates PR and merges. This means every hotfix goes through the executor's validation and testing pipeline even when the supervisor knows exactly what needs to change. The supervisor's diagnose-and-file workflow becomes: diagnose failure, file XS rec via log_writer (rec-386), run `python -m scripts.execute_recommendation <rec-id> --fast --plan-json '{"steps": [{"description": "...", "file": "...", "acceptance": "..."}]}'`. Cost: ~1 premium request per hotfix (1 implementation call) vs 0 for direct edit but with full quality gates. Depends on nothing -- can be implemented standalone. Phase B of the supervisor delegation migration.
- tags: executor, fast-mode, hotfix, delegation, phase-B
- dependencies: []
- acceptance: `grep -q 'fast\|fast_mode' scripts/execute_recommendation.py && python -m pytest tests/test_execute_recommendation.py -x -q`

**rec-414: Route hotfixes through executor pipeline in develop-executor.prompt.md**
- effort: S, priority: High, automatable: false, risk: low
- file: .github/prompts/develop-executor.prompt.md
- context: Phase B process change. After rec-413 (--fast mode) is implemented, update the Escalation and Hotfix Protocol in develop-executor.prompt.md (currently in executor-supervisor-workflow.instructions.md) to establish the delegation path as the primary hotfix mechanism. New protocol: (1) Supervisor diagnoses the failure (reasoning -- supervisor's job), (2) Supervisor files a new XS rec with automatable: true using log_writer CLI (rec-386) or inline JSONL append, (3) Supervisor runs `python -m scripts.execute_recommendation <rec-id> --fast --plan-json '...'`, (4) If --fast fails, supervisor may use direct edit as emergency fallback with explicit justification logged, (5) Emergency fallback requires regression test before merge (existing rec-369 requirement). The prompt should state: "Prefer --fast over direct edit. Direct edit is an emergency escape hatch, not the default workflow." This ensures hotfixes flow through the executor's validation pipeline (validate.py, acceptance check) and generate telemetry. Depends on rec-413.
- tags: develop-executor, hotfix, delegation, process, phase-B
- dependencies: [rec-413]
- acceptance: `grep -qi 'fast\|delegate.*hotfix\|hotfix.*executor\|prefer.*fast' .github/prompts/develop-executor.prompt.md`

**rec-415: Phase C tool access restriction -- remove replace_string_in_file from supervisor tools**
- effort: S, priority: High, automatable: false, risk: medium
- file: .github/prompts/develop-executor.prompt.md
- context: Phase C of supervisor delegation migration. After --fast mode (rec-413) is proven reliable and hotfix routing (rec-414) is established, restrict the supervisor's tool access via prompt frontmatter `tools:` field. Remove replace_string_in_file and multi_replace_string_in_file from the allowed tools list. The supervisor can only: read files (read_file, grep_search, semantic_search), run terminal commands (run_in_terminal for scripts), invoke subagents (runSubagent), and manage memory. If the supervisor encounters a situation it cannot resolve via delegation, it files a rec and stops -- escalating to human. This is the structural enforcement that makes delegation non-optional. The instructions file Rule 2 (Allowed Files) should evolve from a permissive list of editable files to a statement that source code edits are only performed via executor invocation. Gated on: rec-413 closed AND rec-414 closed AND executor XS success rate > 80% (measured from telemetry). The success rate gate means this rec should not be executed until sufficient telemetry data exists from --fast mode usage.
- tags: develop-executor, tool-restriction, delegation, structural-enforcement, phase-C
- dependencies: [rec-413, rec-414]
- acceptance: `grep -q '^tools:' .github/prompts/develop-executor.prompt.md && ! grep -A20 '^tools:' .github/prompts/develop-executor.prompt.md | grep -qi replace_string_in_file`

**rec-416: Structured executor failure output for @rca-analyst consumption**
- effort: S, priority: High, automatable: true, risk: low
- file: scripts/execute_recommendation.py
- context: The supervisor currently reads raw terminal output and transcript files to diagnose failures -- a high-cognitive-load task that produces inconsistent results. The @rca-analyst subagent exists but is underused (rec-272 notes this). Fix: when the executor fails, emit a structured JSON failure summary to stdout (or a file path) containing: (a) rec_id and attempt number, (b) failure_phase (planning, critique, implementation, validation, postflight, acceptance), (c) failure_class (cli_timeout, parse_error, test_failure, scope_creep, ghost_step, acceptance_mismatch), (d) last_transcript_path, (e) git_diff_stat from the failed attempt, (f) validation_output (if postflight failed), (g) acceptance_output (if acceptance failed). The supervisor passes this JSON directly to @rca-analyst instead of manually assembling context. This shifts failure diagnosis from "supervisor reads logs and reasons" to "supervisor reads structured summary and routes to specialist." Independent of other recs.
- tags: executor, failure-output, rca-analyst, structured-data, delegation
- dependencies: []
- acceptance: `grep -q 'failure_summary\|FailureSummary\|structured.*failure' scripts/execute_recommendation.py && python -m pytest tests/test_execute_recommendation.py -x -q`

**rec-417: Restructure develop-executor.prompt.md around Observe-Decide-Delegate-Verify loop**
- effort: M, priority: High, automatable: false, risk: medium
- file: .github/prompts/develop-executor.prompt.md
- context: The current develop-executor workflow is a linear 6-phase checklist (env check, select, run, handle outcome, cross-run analysis, write review). The supervisor implicitly follows an observe-decide-delegate-verify pattern but the prompt does not make this explicit. As delegation mechanisms are added (--next-batch for selection, --fast for hotfixes, structured failure output for diagnosis, log_writer for friction capture, session_postflight --auto for session close), the prompt should be restructured around the decision loop: OBSERVE (read structured output from the previous action), DECIDE (what to do next -- the supervisor's core value), DELEGATE (invoke the appropriate script/subagent), VERIFY (check the result). Each current workflow phase maps to this pattern. The restructure should also make explicit which jobs are reasoning (supervisor does) vs procedural (scripts do): reasoning = rec selection strategy, failure diagnosis, cross-run pattern recognition; procedural = environment setup, executor invocation, friction logging, session close. This is a prompt rewrite that should happen after Phase B mechanisms exist (rec-413 and rec-414 closed) so the delegation targets are concrete. Depends on rec-413 and rec-414.
- tags: develop-executor, architecture, delegation, observe-decide-delegate-verify, phase-C
- dependencies: [rec-413, rec-414]
- acceptance: `grep -qi 'observe.*decide.*delegate\\|ODDV\\|decision.loop' .github/prompts/develop-executor.prompt.md`

**rec-418: session_postflight --auto: add retro-lite invocation between metrics and commit**
- effort: XS, priority: Medium, automatable: true, risk: low
- file: scripts/session_postflight.py
- context: session_postflight.py already has --close (branch verification + SESSION_LOG entry) and --auto (validate -> close -> metrics -> commit -> push -> log-housekeeping). The develop-executor.prompt.md Session Close Checklist step 4 requires running retro-lite, but --auto does not invoke run_retro_lite.run_append(). This is the only gap between the --auto flag and a fully automated session close. Fix: in run_auto(), after the metrics phase and before the commit phase, call run_retro_lite.run_append() with a clean entry using the session summary string from --auto's message argument. If run_append fails (e.g. duplicate detection), log a warning and continue -- session close should not fail because of retro-lite. After this, the supervisor's session close reduces from 6 manual steps to one command: `python -m scripts.session_postflight --auto "Session summary"`. Independent of other recs.
- tags: session-postflight, automation, delegation, retro-lite
- dependencies: []
- acceptance: `grep -q 'run_retro_lite\|retro_lite' scripts/session_postflight.py && python -m pytest tests/test_session_postflight.py -x -q`

### Step 2: Validate JSONL integrity

Run: `python -c "import json; lines = [json.loads(l) for l in open('logs/.recommendations-log.jsonl', encoding='utf-8') if l.strip()]; print(f'{len(lines)} entries, all valid JSON')"` -- must print count with no errors.

### Step 3: Validate recommendation schema

Run: `python -m scripts.validate --quick` -- must exit 0.

### Step 4: Verify no duplicates

Confirm rec-412 through rec-418 do not duplicate existing open recs:
- rec-412 (--next-batch) is distinct from rec-033 (superseded batch orchestrator) -- rec-033 was a full sequential loop, rec-412 is a selection-only command
- rec-413 (--fast) is new -- no existing rec covers a lightweight executor path
- rec-414 (hotfix routing) is distinct from rec-368 (infra-stabilize mode) -- rec-368 is a session type, rec-414 is a hotfix mechanism
- rec-415 (tool restriction) is new -- no existing rec covers prompt frontmatter tool restrictions
- rec-416 (structured failure output) is distinct from rec-272 (pre-assembled RCA context) -- rec-272 is about the supervisor assembling context, rec-416 is about the executor emitting it
- rec-417 (ODDV loop) is new -- no existing rec covers the prompt restructure pattern
- rec-418 (retro-lite in --auto) is distinct from existing --close and --auto flags -- they already exist but --auto is missing the retro-lite invocation step that the Session Close Checklist requires

### Step 5: Run pytest

Run: `python -m pytest tests/ -x -q --timeout=60` -- must pass (no test changes in this plan).

### Step 6: Run validate.py

Run: `python -m scripts.validate --quick` -- must exit 0.

### Step 7: Report implementation summary

Report what was implemented: 7 new recommendations filed (rec-412 through rec-418) covering the 4-phase supervisor delegation migration, with explicit dependency chains ensuring the executor processes them in the correct order.
