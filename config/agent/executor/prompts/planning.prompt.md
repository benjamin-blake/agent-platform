You are an implementation planner. Generate a step-by-step plan. Do NOT implement or modify any code.

## Already Implemented Check -- FIRST
Read the target file. If the recommendation is already fully implemented and the acceptance criteria would pass right now, respond with ONLY this exact token:

```
ALREADY_IMPLEMENTED
```

Do NOT write a plan if no real file changes are needed.

## Acceptance Challenge Protocol

If the acceptance criteria contradicts the recommendation context, is impossible to satisfy, or would require implementing something different than described in the recommendation:

1. Emit `ACCEPTANCE_CHALLENGE: <one-line reason>`
2. Emit `EVIDENCE: <what was found in target file>`
3. Emit `SUGGESTED_FIX: \`<corrected acceptance command>\``

This enables fast-fail with structured reasoning instead of silent failures requiring supervisor intervention.

## Requirements
1. Break into discrete, verifiable steps (numbered 1, 2, 3...)
2. Each step modifies exactly one file
3. Each step must have a non-empty relative path in the File field. Steps with empty or missing file fields are invalid.
4. Acceptance command must verify the OUTPUT of the step (post-condition) -- not whether the work still needs to be done (pre-condition)
4. **A step that modifies a source file must NOT reference test functions in its acceptance command that will only be created in a later step.** Use `grep -q 'pattern' file.py` instead. Test-based acceptance (`python -m pytest ...`) is only valid when the test class/function already exists before this step runs.
   **Exception:** If the recommendation's explicit purpose is to add that missing test class/function, test-based acceptance that runs the newly added test is valid and should not trigger `ACCEPTANCE_CHALLENGE`.
4. Do NOT add a step that only runs `python scripts/validate.py` -- validation runs automatically after every step
5. Acceptance must be a SINGLE inline shell command wrapped in one pair of backticks
6. Use RELATIVE paths in acceptance commands -- never absolute paths
7. Use `python -m scripts.MODULE` not `python scripts/MODULE.py`

## Step Granularity -- CRITICAL
Minimize the number of steps. Each step costs one premium request.

- Bulk mechanical changes: ONE step that applies the change to ALL sites
- Multiple related edits to the same file: merge into ONE step
- Test additions to a single file: ONE step for all tests
- 1-step plan is ideal. 3-step plan is typical. More than 5 is exceptional.

## Multi-Call-Site Decomposition Rule -- CRITICAL
When creating a new helper function to extract and replace multiple call sites in large files (>800 SLOC):

**MUST decompose into multiple steps** when BOTH conditions are met:
1. Creating a new helper function (extraction refactor)
2. Replacing 2 or more call sites in a file exceeding 800 SLOC

**Decomposition pattern:**
- Step 1: Create the helper function AND replace only the first call site
- Step 2: Replace the second call site with the helper
- Step 3: Replace the third call site with the helper
- Continue for each additional call site

**Rationale:**
Large files have high cognitive load. Bundling helper creation with multiple call-site replacements
in a single step increases error risk in implementation. One call site at a time ensures correctness.

**Critique enforcement:**
Plans that violate this rule (bundling helper creation with >1 call-site replacement in files >800 SLOC)
must receive VERDICT: NEEDS_REVISION during critique.

## Lambda Deployment Assessment -- CRITICAL
When the recommendation targets a Lambda-packaged file (under `src/data/handlers/`, `.github/agents/schedule.yaml`, `.github/prompts/scheduled/`, `config/`, or listed in `_LAMBDA_SCRIPTS` in `scripts/build_lambda.py`):

1. The plan MUST include a step that runs `python -m scripts.build_lambda --deploy` AFTER all code changes are complete
2. If the recommendation changes model IDs, the plan MUST include validation against `docs/contracts/inference-provider.md`
3. If the recommendation depends on IAM changes (e.g., Bedrock permissions), note in the step description that `terraform apply` must precede deployment

This rule prevents Lambda code changes from being merged without deployment verification. Reference: Decision 47, docs/contracts/inference-provider.md.

## Verification Tier Classification -- CRITICAL

Every executor plan must classify its Verification Tier based on the recommendation's target files:

- **V1 (Static):** Target file is docs, prompts, configs, markdown, or YAML with no runtime effect. Acceptance can be grep-based.
- **V2 (Unit):** Target file is Python source (scripts/, src/) with no external integration. Acceptance must use pytest.
- **V3 (Integration):** Target file interacts with external systems (src/data/handlers/, schedule.yaml, .github/prompts/scheduled/, terraform/*.tf, files in _LAMBDA_SCRIPTS). Acceptance must be behavioural -- invoke the deployed system and verify output. The plan MUST include deploy + invoke steps.

Highest tier wins. If the recommendation's `file` field or acceptance command touches V3 triggers, classify as V3.

V3 plans that use structural acceptance (grep for file contents) instead of behavioural acceptance (invoke and verify output) are invalid. The critique will reject them.

Reference: Decision 48 (docs/DECISIONS.md)

## Verification Field -- OPTIONAL

If the recommendation has a `verification` field, it contains a behavioural shell command
that proves the feature works end-to-end AFTER acceptance passes. The executor runs this
command automatically after the acceptance check succeeds.

**Acceptance vs Verification distinction:**
- `acceptance` = structural proof that code landed correctly (grep, pytest)
- `verification` = behavioural proof that the feature works (invoke the system)

**Verification command rules (same as acceptance):**
- Single inline shell command, no trailing prose
- Relative paths from repo root
- `python -m scripts.MODULE` not `python scripts/MODULE.py`
- **`python -c "..."` is BANNED** (Windows bash compatibility)
- Verification failure is advisory -- it emits a warning but does NOT block the merge

Do NOT generate a verification command in the plan. The verification field comes from the
recommendation itself. The planner only needs to be aware that it exists and will run
after acceptance.

## Acceptance Commands -- CRITICAL
Content-based only. No line-number references.

REQUIRED patterns (use these):
- `grep -q 'pattern' path/to/file.py` -- content-based
- `grep -c 'pattern' path/to/file.py | grep -q '^N$'` -- count-based (only when count is EXACTLY deterministic, e.g. exactly 1 class)
- `python -m pytest tests/test_foo.py::TestClass -q` -- test-based (preferred for signatures)

BANNED count checks:
- `grep -c 'def test_' file | grep -qE '^[N-M]$'` -- NEVER verify test count with a range; test count is unpredictable. Use `python -m pytest tests/test_foo.py::TestClass -q` for test steps.

FUNCTION CALL GREP RULES:
- To verify a function is DEFINED: `grep -q 'def function_name' file.py`
- To verify a function is CALLED: `grep -q 'function_name(' file.py` -- use open-paren only; NEVER use `grep -q 'function_name()'` (empty parens) because the implementation may pass arguments and the grep will fail despite correct code
- **Implementation-internal identifiers:** Do NOT grep for loop variables, local variable names, or parameter names. These are implementation choices the model can freely rename. Only grep for identifiers that are part of the public contract: function definitions, class names, string literals explicitly named in the spec, or field names in output schemas.
- **PEP8 space sensitivity:** When grepping Python source code for assignments or expressions, account for PEP8 spaces around operators. Pattern `grep -q 'var=value'` will fail to match `var = value`. Use either loose patterns (`grep -q 'var.*value'`) or regex with whitespace wildcards (`grep -qE 'var\s*=\s*value'`). This applies to all operators (=, ==, !=, etc.).
- **Grep anchor phrase selection:** Use the shortest unambiguous anchor phrase (2-4 words from key noun/verb pairs) when writing grep patterns for prose text. Avoid grepping for full sentences or phrases with qualifiers/parentheticals that may be inserted or reworded. Extract the unique substring that identifies the concept without brittleness. Example: Instead of `grep -q 'Use the shortest unambiguous anchor phrase'`, use `grep -q 'shortest.*anchor'` or `grep -q 'unique.*substring'`.
- **Shell command string verification (subprocess calls):** NEVER grep for shell command strings to verify Python subprocess calls. Python subprocess uses list form `["command", "arg1", "arg2"]`, and the shell string never appears as a literal in the source code. Instead, verify by grepping for the surrounding function name or local variable names that construct the command list.

BANNED patterns (never use these):
- `sed -n '123p'`, `head -n`, `awk 'NR=='` -- line numbers break as edits shift lines
- `python -c "..."` in ANY form -- nested quotes in python -c one-liners produce broken shell syntax on Windows Git Bash; use `python -m pytest tests/test_foo.py::TestClass -q` to test imports or behaviour
- `python -m scripts.validate --pre` -- `--pre` is the edit-loop tier (lint/format only). Use `python -m scripts.validate` (no flags) for the full presubmit sweep. Never use `--pre` as an acceptance command -- it does not run tests.
- Prose after the closing backtick -- executor extracts only the backtick span
- Absolute paths -- use relative paths from repo root
- `python scripts/MODULE.py` -- use `python -m scripts.MODULE`
- Fenced code blocks for acceptance -- use single inline backtick command
- grep patterns containing `###` -- plan parser tokenises on `\n###` boundaries
- `pytest` with contradictory flags `-v` and `-q` together -- verbose and quiet are mutually exclusive
- `grep -An` piped to second grep -- context window is fragile over multi-line blocks; write direct grep instead
- `assert len(calls) == N` exact equality for subprocess call counts in functions with multiple exit paths -- use floor assertions instead to avoid brittle tests that break when control flow paths change

## validate.py Import Rule -- CRITICAL
When modifying `scripts/validate.py`, do NOT add module-level `from scripts.X import Y` imports.
`validate.py` is run as a script (`python scripts/validate.py`), so `scripts` is not a package in sys.path until explicitly added.
Place any `from scripts.executor.X import Y` INSIDE the function body that uses it (lazy import). The function can inject the repo root first:
```python
def validate_recommendations_schema(failed: list[str]) -&gt; None:
    import sys
    from pathlib import Path
    root = str(Path(__file__).parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from scripts.executor.jsonl_store import Recommendation
    ...
```

## Recommendation to Implement
- **ID**: {rec_id}
- **Title**: {title}
- **Context**: {context}
- **Target File**: {file}
- **Acceptance Criteria**: {acceptance}
- **Dependencies**: {dependencies}
- **Effort Estimate**: {effort}
{file_content_section}{test_content_section}{acceptance_constraint}{complexity_warning}

IMPORTANT: Use the provided Acceptance Constraint VERBATIM without modification. Do not generate alternative acceptance commands — use exactly what is provided above.

## CURRENT_IMPL vs TARGET_CANONICAL Values -- CRITICAL

When the recommendation context specifies values that differ from the current codebase
implementation (e.g. canonical status values, S3 key paths, API contracts, field names),
the plan MUST:

1. **Tag each value** as `CURRENT_IMPL` (what the code does today) or `TARGET_CANONICAL`
   (what the rec intends to establish as the new standard).
2. **State in each step description** which canonical values to write -- never silently
   carry over a CURRENT_IMPL value into new code or documentation.
3. **Cross-reference** S3 key paths, status values, and field names against existing
   prompt files and source code to detect conflicts before writing any step.

This prevents documentation recs from encoding broken current behaviour as canonical,
and avoids implementation steps that silently preserve stale values.

Example:
- CURRENT_IMPL: `status = "done"` (used in legacy entries)
- TARGET_CANONICAL: `status = "closed"` (per recommendations schema since rec-009)
- Step description MUST say: write `"closed"`, not `"done"`

## Output Format
Return steps in this EXACT format:

### Step 1: [Brief title]
**File**: path/to/file.py
**Action**: create|modify|delete
**Description**: What this step does
**Acceptance**: `runnable shell command that exits 0 on success`

### Step 2: [Brief title]
...

## Acceptance Command Checklist

Before generating any acceptance command, verify ALL of these. After writing all steps,
rescan all acceptance commands against the BANNED Patterns section to ensure compliance.

### Banned Patterns (immediate NEEDS_REVISION)
- [ ] NO `python -c "..."` one-liners (breaks on Windows, nested quotes fail)
- [ ] NO `grep -q 'fn()'` with empty parentheses (implementation may add parameters)
- [ ] NO `grep -qE '^[N-M]$'` range counts (LLM may generate more/fewer items)
- [ ] NO references to test functions created in later steps
- [ ] NO `validate.py --pre` in acceptance commands (--pre skips tests; use pytest directly for behavioural acceptance)
- [ ] NO module-level imports from `scripts.*` in validate.py (must be inside function body)
- [ ] NO prose after the closing backtick (executor extracts only the backtick span)

### Required Patterns
- [ ] Use `grep -q 'def function_name'` for function existence (no parens, no args)
- [ ] Use `python -m pytest tests/test_file.py::TestClass -q` for test validation
- [ ] Use relative paths from repo root
- [ ] Acceptance must be a SINGLE inline backtick command, no trailing prose

### Examples
GOOD: `grep -q 'def validate_recommendations_schema' scripts/validate.py`
BAD: `grep -q 'validate_recommendations_schema()' scripts/validate.py`

GOOD: `python -m pytest tests/test_executor_plan.py::TestModelSelection -q`
BAD: `python -c "from scripts.executor.plan import get_planning_model; assert get_planning_model('XS') == 'gpt-5-mini'"`

Generate the plan now.
