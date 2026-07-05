Review this implementation plan and determine if it is ready for execution.

## Scope Files
Before evaluating rules, read each file in this scope list. Your verdict MUST include a FILES READ section.
{scope_files}

## Deep Analysis Required
You MUST read every file listed above before outputting your verdict. Your FILES READ section must:
1. List every scope file with its line count (e.g., `scripts/executor/plan.py (423 lines)`)
2. Cite line numbers for modified functions (e.g., `get_planning_model at L145`)
3. Cite line numbers for affected mocks in test files (e.g., `mock patching plan.copilot_call at L89`)
4. If you cannot cite line numbers, you have not read the files — go back and read them.

## Plan to Review
{plan_text}

Evaluate against the hard-fail rules in your instructions. Read the actual target files before judging factual accuracy (Rule 11).

## Hard-Fail Rules
Steps that call external tools (Copilot CLI, gh CLI, AWS SDK, Lambda invocation, subprocess) without citing a boundary contract in `docs/contracts/` or doc reference are NEEDS_REVISION.

Steps that modify Lambda-packaged files (`src/data/handlers/`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`, `config/`, `scripts/_LAMBDA_SCRIPTS`) without a `build_lambda.py --deploy` step in the plan are NEEDS_REVISION. Reference: Decision 47, docs/contracts/inference-provider.yaml.

Plans classified as V3 (integration verification) that use structural acceptance commands (grep, test -f, file-existence checks) instead of behavioural acceptance commands (invoke the deployed system and verify output) are NEEDS_REVISION. V3 plans must include: (a) a deploy step, (b) an invoke step that triggers the real system, (c) a verify step that checks the output. Structural acceptance for V3 features hides integration bugs that only surface on first live invocation. Reference: Decision 48.

## VERDICT GATE
Any hard-fail rule violation (rules 1-12 from your instructions) MUST result in a NEEDS_REVISION verdict. Do not approve plans with known violations. List each violation by rule number with specific details.

Output your verdict as plain text — do NOT use tool calls to emit it.

VERDICT must appear on its own line:
```
VERDICT: APPROVED
```
or
```
VERDICT: NEEDS_REVISION
```

If NEEDS_REVISION, list each violation by rule number.
