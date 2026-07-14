# Plan

## Intent
Close two critical open recommendations that undermine the self-improving feedback loop: the lack of automated test enforcement for new code, and the inability to verify that prompt/agent behaviour changes are actually adopted in subsequent sessions. Together these create a blind spot where both code and workflow regressions can persist undetected.

## Plan Type
IMPLEMENTATION

## Branch
agent/infra-testing-enforcement

## Phase
Phase 1: Core Infrastructure (maintenance)

## Scope
| File | Action | Purpose |
|------|--------|---------|
| `scripts/test_coverage_checker.py` | Create | AST-based checker: for each changed `.py` file, verify a corresponding test file exists and per-file coverage is 100% |
| `scripts/prompt_compliance.py` | Create | Parse `.retro-lite-log.jsonl` and `.execution-state.json` against behavioural invariants declared in prompt files |
| `scripts/validate.py` | Modify | Integrate `test_coverage_checker` and `prompt_compliance` as new validation steps; add CLI tool verification for prompt files |
| `.github/prompts/implement.prompt.md` | Modify | Add `## Behavioural Invariants` section declaring per-step retro-lite, scope-guard at midpoint, step-validator per step |
| `.github/prompts/plan.prompt.md` | Modify | Add `## Behavioural Invariants` section declaring preflight run, critique gate, branch creation |
| `tests/test_coverage_checker.py` | Create | Tests for AST function extraction, test file mapping, coverage report parsing |
| `tests/test_prompt_compliance.py` | Create | Tests for invariant parsing, retro-lite log analysis, execution state analysis, compliance report |
| `docs/RECOMMENDATIONS.md` | Modify | Mark both critical L-effort items as resolved |

## Acceptance Criteria
- [ ] `test_coverage_checker.py` extracts function/class definitions from Python files using AST
- [ ] `test_coverage_checker.py` maps source files to test files (`src/common/config.py` -> `tests/test_config.py`, `scripts/validate.py` -> `tests/test_validate.py` (if exists))
- [ ] `test_coverage_checker.py` reports missing test files for new/modified source files (blocking failure)
- [ ] `test_coverage_checker.py` checks per-file coverage is 100% for new files (blocking failure)
- [ ] `validate.py` runs CLI tool verification on prompt files: scans for `aws`, `gh`, `terraform`, `docker` commands and verifies each is in PATH (blocking failure)
- [ ] `prompt_compliance.py` parses `## Behavioural Invariants` YAML from prompt files
- [ ] `prompt_compliance.py` parses `.retro-lite-log.jsonl` to count friction entries per session
- [ ] `prompt_compliance.py` parses `.execution-state.json` to get step progress per session
- [ ] `prompt_compliance.py` validates invariants against session data (e.g., retro-lite invocations == step count from plan)
- [ ] `validate.py` runs prompt compliance check when prompt files are changed (blocking failure)
- [ ] `implement.prompt.md` has `## Behavioural Invariants` section with machine-readable YAML
- [ ] `plan.prompt.md` has `## Behavioural Invariants` section with machine-readable YAML
- [ ] Both RECOMMENDATIONS.md items marked resolved
- [ ] All tests pass: `pytest tests/`
- [ ] Validation passes: `python scripts/validate.py`

## Constraints
- Python 3.12+, type hints required
- Windows developer (bash syntax for terminal, Python scripts for automation)
- Deterministic scripting: both checkers must be standalone Python scripts callable from validate.py and CLI
- No external dependencies beyond stdlib + coverage (already in dev deps) + pyyaml (already in requirements.txt — verify before implementation)
- CLI tool verification is blocking (not informational)
- Per-file coverage for new files is 100% (not 37% project floor)
- Deterministic scripting: no manual steps — all checks run automatically through validate.py

## Context
- RECOMMENDATIONS.md items: "No automated mechanism for enforcing unit tests on new code" (Critical, L) and "No mechanism to verify prompt behaviour changes are adopted" (Critical/High, L)
- Decision 29: Friction-Free Implementation Pattern — establishes that specific, verifiable steps prevent friction
- Friction patterns show recurring issues: missing tests caught only at code review, missing imports caught only at pre-commit, prompt changes silently ignored
- `validate.py` is the single source of truth for local CI (Known Gotcha: "Validation sync")
- `.retro-lite-log.jsonl` has structured JSON with session, friction, deviation fields
- `.execution-state.json` has branch, plan_file, current_step, total_steps, status fields

## Pre-Implementation Checklist
> The implementing agent must verify all items before editing any file.
- [ ] Branch confirmed not on `main`
- [ ] copilot_instructions.md read (rules, gotchas, file router)
- [ ] DECISIONS.md read (no conflicts with prior decisions)
- [ ] All files in Scope table located and readable
- [ ] Acceptance Criteria understood and verifiable

## Ordered Execution Steps
> **Execute these in sequence. Do not substitute the Scope table as a work list.**

### Phase A: Test Coverage Enforcement

1. **Create `scripts/test_coverage_checker.py`**
   - Import `ast`, `subprocess`, `sys`, `re` from stdlib; `pathlib.Path`
   - Define `ROOT = Path(__file__).resolve().parent.parent`
   - Implement `extract_definitions(file_path: Path) -> list[str]`:
     - Parse file with `ast.parse()`
     - Walk AST and collect names of `FunctionDef`, `AsyncFunctionDef`, and `ClassDef` nodes at module level (not nested)
     - Skip private functions starting with `_` (they're tested indirectly via public API)
     - Return list of definition names
   - Implement `map_source_to_test(source_path: Path) -> Path | None`:
     - For `src/**/*.py`: strip leading `src/` path components, create `tests/test_{module}.py` (e.g., `src/common/config.py` -> `tests/test_config.py`)
     - For `scripts/*.py`: create `tests/test_{script_name}.py` (e.g., `scripts/validate.py` -> `tests/test_validate.py`)
     - Return the expected test file path (relative to ROOT), or None if source is not under `src/` or `scripts/`
   - Implement `check_test_file_exists(source_path: Path) -> tuple[bool, str]`:
     - Call `map_source_to_test()` to get expected test path
     - If None (unmapped), return `(True, "skipped: not in src/ or scripts/")`
     - If test file exists, return `(True, "test file found")`
     - If test file missing, return `(False, f"missing test file: {expected_path}")`
   - Implement `check_per_file_coverage(source_files: list[Path]) -> list[str]`:
     - Run `python -m pytest tests/ --cov={source_file_module} --cov-report=json --cov-report=term-missing -q` for each source file
     - Parse the JSON coverage report to extract per-file line coverage percentage
     - Return list of files with < 100% coverage and their actual percentage
     - If coverage.py is not available, return informational warning (not blocking)
   - Implement `get_changed_source_files() -> list[Path]`:
     - Run `git diff --name-only $(git merge-base origin/main HEAD)` to get changed files (merge-base ensures accurate feature-branch diff even if main has advanced)
     - Filter to `.py` files under `src/` or `scripts/`
     - Exclude `__init__.py`, `conftest.py`, and test files themselves
   - Implement `main()`:
     - Parse args: `--check-tests` (verify test files exist), `--check-coverage` (verify 100% per-file coverage), `--files` (optional explicit file list instead of git diff)
     - Run checks, collect errors
     - Print report, exit 0 if all pass, exit 1 if any fail
   - Add `argparse` CLI with `--check-tests`, `--check-coverage`, `--files` flags

2. **Create `tests/test_coverage_checker.py`**
   - Import the module via `importlib.util.spec_from_file_location` (same pattern as `test_plan_audit.py`)
   - Register in `sys.modules` so `patch()` works
   - Test `extract_definitions()`: create a tmp `.py` file with functions/classes, parse, verify names extracted
   - Test `extract_definitions()` skips private `_` functions
   - Test `map_source_to_test()` for `src/common/config.py` -> `tests/test_config.py`
   - Test `map_source_to_test()` for `scripts/validate.py` -> `tests/test_validate.py`
   - Test `map_source_to_test()` returns None for unmapped paths (e.g., `docs/README.md`)
   - Test `check_test_file_exists()` returns True when test file exists, False when missing
   - Test `get_changed_source_files()` with mocked git subprocess output
   - Target: at least 8 tests

3. **Add CLI tool verification to `validate.py`**
   - Add new function `validate_cli_tools_in_prompts(failed: list[str]) -> None`:
     - Scan all `.prompt.md` and `.agent.md` files in `.github/prompts/` and `.github/agents/`
     - Regex-extract shell command references: look for fenced code blocks with `bash` or no language, extract first word of each command line
     - Build a set of unique CLI tool names referenced (filter to known system tools: `aws`, `gh`, `terraform`, `docker`, `psql`, `pip-audit`)
     - For each tool, call `shutil.which(tool)` to check if it's in PATH
     - If any tool is missing, append to `failed` with message: `"CLI tool '{tool}' referenced in {file} but not found in PATH"`
   - Call this function in `run_python_checks()` and in `--quick` mode
   - This is a blocking check (appends to `failed` list)

4. **Integrate test coverage checker into `validate.py`**
   - Add new function `validate_test_coverage(failed: list[str]) -> None`:
     - Call `test_coverage_checker.get_changed_source_files()` to get changed source files
     - If no changed source files, print "No source file changes to check" and return
     - For each changed file, call `test_coverage_checker.check_test_file_exists()`
     - Collect failures; if any test files are missing, append to `failed`
     - Then run per-file 100% coverage check: call `test_coverage_checker.check_per_file_coverage()` for changed source files
     - If any file has < 100% coverage, append to `failed`
     - Print report: `"Test coverage check: {n} source files checked, {m} missing test files, {k} below 100% coverage"`
   - Call this in `run_python_checks()` (after lint, before pytest)
   - Skip in `--quick` mode (per-file coverage runs pytest which is too slow for per-step validation)
   - **No manual step:** this runs automatically as part of `python scripts/validate.py` on every `--scope python`, `--scope all`, and `--ci` invocation

### Phase B: Prompt Compliance Verification

5. **Add `## Behavioural Invariants` section to `implement.prompt.md`**
   - Add section after `## Intent` (before `## Purpose`), using YAML code block:
     ```markdown
     ## Behavioural Invariants
     ```yaml
     # Machine-readable invariants verified by scripts/prompt_compliance.py
     retro_lite_per_step: true          # @retro-lite must be invoked after every Ordered Execution Step
     scope_guard_at_midpoint: true      # @scope-guard must be invoked at ceil(N/2)
     step_validator_per_step: true      # @step-validator must be invoked after every step
     checkpoint_per_step: true          # execution_state.save_checkpoint() called after every step
     pre_commit_before_commit: true     # pre-commit run --all-files before any git commit
     ```
     ```
   - These are the behavioural guarantees that the prompt claims to enforce

6. **Add `## Behavioural Invariants` section to `plan.prompt.md`**
   - Add section after `## Intent` (before `## Purpose`), using YAML code block:
     ```markdown
     ## Behavioural Invariants
     ```yaml
     # Machine-readable invariants verified by scripts/prompt_compliance.py
     preflight_run: true                # session_preflight.py must run at Step 0
     branch_creation: true              # must create agent/{slug} branch before writing plan
     critique_gate: true                # @plan-critique must be invoked before completion
     never_on_main: true                # no file edits while on main branch
     ```
     ```

7. **Create `scripts/prompt_compliance.py`**
   - Import `json`, `re`, `sys`, `argparse` from stdlib; `pathlib.Path`; `yaml` (already a project dependency)
   - Define `ROOT = Path(__file__).resolve().parent.parent`
   - Implement `parse_invariants(prompt_path: Path) -> dict[str, bool]`:
     - Read the prompt file
     - Find `## Behavioural Invariants` section
     - Extract the YAML code block within it
     - Parse with `yaml.safe_load()` and return as dict
     - Return empty dict if section not found
   - Implement `parse_retro_lite_log(log_path: Path, session_filter: str | None = None) -> list[dict]`:
     - Read `.retro-lite-log.jsonl` line by line
     - Parse each line as JSON, skip malformed lines with warning
     - If `session_filter` provided, filter entries where `session` field contains the filter string
     - Return list of parsed entries
   - Implement `parse_execution_state(state_path: Path) -> dict | None`:
     - Read `.execution-state.json`
     - Parse as JSON, return dict or None if missing/invalid
   - Implement `check_retro_lite_compliance(invariants: dict, retro_entries: list[dict], execution_state: dict | None) -> list[str]`:
     - If `retro_lite_per_step` is True:
       - Get `total_steps` from execution_state (if available)
       - Count retro-lite entries for the current session
       - If count < total_steps: return violation `"retro_lite_per_step: expected {total_steps} entries, found {count}"`
     - If `checkpoint_per_step` is True:
       - Check execution_state `current_step` matches `total_steps` (all steps completed)
       - If not: return violation `"checkpoint_per_step: execution state shows step {current}/{total}"`
     - Return list of violations (empty = compliant)
   - Implement `check_plan_compliance(invariants: dict, session_log_path: Path) -> list[str]`:
     - For `preflight_run`, `branch_creation`, `critique_gate`: these are structural (enforced by prompt ordering), so check passes if the session completed (entry exists in SESSION_LOG.md)
     - Return list of violations
   - Implement `main()`:
     - Parse args: `--prompt` (path to prompt file), `--session` (session filter string), `--all` (check all prompt files)
     - Load invariants from specified prompt file(s)
     - Load retro-lite log and execution state
     - Run compliance checks
     - Print report, exit 0 if compliant, exit 1 if violations found

8. **Create `tests/test_prompt_compliance.py`**
   - Import the module via `importlib.util.spec_from_file_location`
   - Register in `sys.modules`
   - Test `parse_invariants()`: create tmp prompt file with `## Behavioural Invariants` YAML block, verify dict returned
   - Test `parse_invariants()` returns empty dict for prompt without invariants
   - Test `parse_retro_lite_log()`: create tmp JSONL file with entries, verify parsed correctly
   - Test `parse_retro_lite_log()` with session filter
   - Test `parse_retro_lite_log()` skips malformed JSON lines
   - Test `parse_execution_state()`: create tmp JSON file, verify parsed
   - Test `parse_execution_state()` returns None for missing file
   - Test `check_retro_lite_compliance()` passes when entry count matches step count
   - Test `check_retro_lite_compliance()` fails when entries < steps
   - Test `check_plan_compliance()` passes for completed session
   - Target: at least 10 tests

9. **Integrate prompt compliance into `validate.py`**
   - Add new function `validate_prompt_compliance(failed: list[str]) -> None`:
     - Find all `.prompt.md` files with `## Behavioural Invariants` sections
     - For each, run compliance check against the most recent session in retro-lite log
     - If any violations, append to `failed`
     - Print report
   - Call this in the prompt validation path (after `validate_prompt_files()`, gated on `has_prompt_changes or scope == "all"`)
   - This is a blocking check

### Phase C: Finalise

10. **Mark resolved items in `docs/RECOMMENDATIONS.md`**
    - Add strikethrough to: "No automated mechanism for enforcing unit tests on new code" — resolved with `test_coverage_checker.py` and `validate.py` integration
    - Add strikethrough to: "No mechanism to verify prompt behaviour changes are adopted" — resolved with `prompt_compliance.py`, invariants sections, and `validate.py` integration
    - Add resolution notes with date 2026-03-30

11. Run `pytest tests/` — all tests must pass before proceeding

12. Run `python scripts/validate.py` — must exit 0

13. Report what was implemented and any design decisions made during implementation
