# complexity-waiver: decision-43
#!/usr/bin/env python3
"""Local CI validation script. Run before every commit.

Runs validation checks that mirror the GitHub Actions CI pipeline.
Default (no flags) runs the full check suite. Use --pre for fast lint/format
checks only during implementation.
"""

import argparse
import ast
import importlib.util
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
PYTHON = sys.executable  # Use same interpreter that's running this script
KNOWN_MODELS = {
    "Claude Haiku 4.5 (copilot)",
    "Claude Sonnet 4.5 (copilot)",
    "Claude Sonnet 4.6 (copilot)",
    "Claude Opus 4.5 (copilot)",
    "Claude Opus 4.6 (copilot)",
    "GPT-4.1",
    "GPT-5 mini",
    "GPT-5.4",
    "Gemini 2.5 Pro",
}

# CLI tools that may appear in prompt/agent files and must be in PATH
_KNOWN_CLI_TOOLS = {"aws", "gh", "terraform", "docker", "psql", "pip-audit"}


# File patterns that mark executor boundary files (Decision 44).
# Canonical source: config/agent/executor/capabilities.yaml -- do not edit this list directly.
def _load_boundary_patterns() -> tuple[str, ...]:
    import yaml  # noqa: PLC0415

    capabilities_path = ROOT / "config" / "agent" / "executor" / "capabilities.yaml"
    data = yaml.safe_load(capabilities_path.read_text(encoding="utf-8"))
    return tuple(data["boundary_patterns"])


_EXECUTOR_BOUNDARY_PATTERNS = _load_boundary_patterns()

_FAST_TIER_BUDGET_SECONDS = 300


def _load_coverage_checker():
    """Lazy-load test_coverage_checker to avoid import-time subprocess calls."""
    checker_path = ROOT / "scripts" / "test_coverage_checker.py"
    if not checker_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("test_coverage_checker", checker_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]

    # Ensure repo root is in sys.path so intra-package imports resolve
    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
    return mod


def _load_prompt_compliance():
    """Lazy-load prompt_compliance to avoid import-time subprocess calls."""
    compliance_path = ROOT / "scripts" / "prompt_compliance.py"
    if not compliance_path.exists():
        return None
    spec = importlib.util.spec_from_file_location("prompt_compliance", compliance_path)
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]

    # Ensure repo root is in sys.path so intra-package imports resolve
    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
    return mod


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, **kwargs)


def invoke_step(name: str, cmd: list[str], failed: list[str], cwd: Path | None = None) -> None:
    print(f"\n=== {name} ===")
    result = run(cmd, cwd=cwd or ROOT)
    if result.returncode != 0:
        failed.append(name)


def get_changed_files() -> list[str]:
    """Get files changed vs origin/main, falling back to HEAD. Excludes deleted paths."""
    result = run(["git", "diff", "--name-only", "origin/main"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if result.returncode == 0:
        files = result.stdout.strip().splitlines()
    else:
        result = run(["git", "diff", "--name-only", "HEAD"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        files = result.stdout.strip().splitlines()
    return [f for f in files if f and (ROOT / f).exists()]


def run_precommit_checks(failed: list[str], *, all_files: bool, files: list[str] | None = None) -> None:
    """Run the pre-commit hook suite (detect-secrets, shape denylist, file hygiene).

    pre-commit is the single home for detect-secrets and the shape-based
    never-commit identifier denylist. Routing it through validate.py keeps
    validate.py the single source of truth: the same hooks run in the --pre edit
    loop, the pr-validate CI gate, and the main-validate full tier -- so a failing
    detect-secrets result can no longer merge unseen (it reddens the authoritative
    gate the way every other check does, instead of only the advisory pre_commit
    workflow that push-to-main never blocked on).

    no-commit-to-branch is skipped via SKIP: it is a commit-time guard already
    covered by .claude/hooks/never_on_main.py, and it would always fail on the
    push-to-main main-validate run (which legitimately runs on the main branch).
    """
    name = "pre-commit hooks"
    if importlib.util.find_spec("pre_commit") is None:
        print(f"\n=== {name} ===\nWARNING: pre-commit not installed; skipping (install requirements-dev.txt).")
        return
    cmd = [PYTHON, "-m", "pre_commit", "run", "--show-diff-on-failure", "--color", "never"]
    if all_files:
        cmd.append("--all-files")
    else:
        target = files if files is not None else get_changed_files()
        if not target:
            print(f"\n=== {name} ===\nNo changed files vs origin/main; skipping.")
            return
        cmd += ["--files", *target]
    print(f"\n=== {name} ===")
    env = {**os.environ, "SKIP": "no-commit-to-branch"}
    result = run(cmd, cwd=ROOT, env=env)
    if result.returncode != 0:
        failed.append(name)


def validate_requirements(failed: list[str]) -> None:
    print("\n=== Requirements validation ===")
    req_file = ROOT / "requirements.txt"
    if not req_file.exists():
        print(f"requirements.txt not found at {req_file}")
        failed.append("Requirements validation")
        return

    lines = req_file.read_text(encoding="utf-8").splitlines()
    packages: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Skip git+, http(s)://, -e, and -r directives — not PyPI packages
        if re.match(r"^(git\+|https?://|-e\s|-r\s)", stripped):
            continue
        # Extract package name — stop at version specifier, extras, comment, or whitespace
        match = re.match(r"^([A-Za-z0-9_-]+)", stripped)
        if match:
            packages.append(match.group(1))

    if not packages:
        print("requirements.txt has no packages to validate.")
        return

    errors: list[str] = []
    for pkg in packages:
        # Validate package name is safe before issuing subprocess (defence-in-depth)
        if not re.match(r"^[A-Za-z0-9_-]+$", pkg):
            errors.append(f"{pkg} — skipped (non-standard name, verify manually)")
            continue
        try:
            result = run(
                [PYTHON, "-m", "pip", "index", "versions", pkg],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        except FileNotFoundError:
            errors.append(f"{pkg} — pip not found (check venv activation)")
            continue
        if result.returncode != 0:
            stderr = result.stderr.lower()
            if any(word in stderr for word in ("connection", "timeout", "network", "unreachable")):
                errors.append(f"{pkg} — network error checking PyPI (retry or check connectivity)")
            else:
                errors.append(f"{pkg} — not found on PyPI (pip index versions returned non-zero)")

    if errors:
        print("Requirements validation errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Requirements validation")
    else:
        print(f"All {len(packages)} packages in requirements.txt found on PyPI.")


# CLI tools intentionally absent on the Claude Code web harness (GitHub ops use the
# GitHub MCP tools, Decision 76). Legacy .github/prompts/.github/agents files that still
# reference these are deep-frozen; a missing optional tool is a skip, not a failure.
_OPTIONAL_CLI_TOOLS = {"gh"}


def validate_cli_tools_in_prompts(failed: list[str]) -> None:
    """Scan prompt and agent files for CLI tool references and verify each is in PATH."""
    print("\n=== CLI tool verification (prompt/agent files) ===")
    search_dirs = [
        ROOT / ".github" / "prompts",
        ROOT / ".github" / "agents",
    ]
    errors: list[str] = []
    referenced: dict[str, str] = {}  # tool -> first file that references it

    for directory in search_dirs:
        if not directory.exists():
            continue
        for md_file in directory.glob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            # Extract fenced code blocks (bash or unspecified language)
            code_blocks = re.findall(r"```(?:bash|sh)?\n(.*?)```", content, re.DOTALL)
            for block in code_blocks:
                for line in block.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    first_word = line.split()[0]
                    if first_word in _KNOWN_CLI_TOOLS and first_word not in referenced:
                        referenced[first_word] = md_file.name

    for tool, source_file in referenced.items():
        if shutil.which(tool) is None:
            if tool in _OPTIONAL_CLI_TOOLS:
                print(f"  note: optional CLI tool '{tool}' not in PATH (referenced in {source_file}); skipped (Decision 76)")
                continue
            errors.append(f"CLI tool '{tool}' referenced in {source_file} but not found in PATH")

    if errors:
        print("CLI tool verification errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("CLI tool verification")
    else:
        checked = list(referenced.keys())
        print(f"All {len(checked)} CLI tool(s) found in PATH: {', '.join(sorted(checked)) or 'none referenced'}.")


def validate_imports(failed: list[str]) -> None:
    """Validate that new executor modules can be imported successfully."""
    print("\n=== Import validation (executor modules) ===")
    import importlib.util
    import sys

    modules = [
        ("copilot_wrapper", ROOT / "scripts" / "copilot_wrapper.py"),
        ("execute_recommendation", ROOT / "scripts" / "execute_recommendation.py"),
        ("classify_risk", ROOT / "scripts" / "classify_risk.py"),
    ]
    errors: list[str] = []
    # Ensure repo root is in sys.path so intra-package imports (e.g. from scripts.x) resolve
    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        for module_name, module_path in modules:
            if not module_path.exists():
                errors.append(f"{module_name}: file not found at {module_path}")
                print(f"  X {module_name}: file not found")
                continue
            try:
                spec = importlib.util.spec_from_file_location(module_name, module_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                print(f"  OK {module_name}")
            except Exception as e:
                errors.append(f"{module_name}: {e}")
                print(f"  ERROR {module_name}: {e}")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)
    if errors:
        failed.append("Import validation")
    else:
        print(f"All {len(modules)} executor modules import successfully.")


def validate_recommendations_schema(failed: list[str]) -> None:
    """Validate that all entries in logs/.recommendations-log.jsonl conform to schema.

    Uses Pydantic v2 Recommendation model from scripts.executor.jsonl_store.
    Validates line-by-line, skips comments and blank lines, collects errors.
    """
    print("\n=== Recommendations schema validation ===")
    import json
    import sys

    recs_jsonl = ROOT / "logs" / ".recommendations-log.jsonl"

    if not recs_jsonl.exists():
        print("logs/.recommendations-log.jsonl not found — skipping.")
        return

    # Lazy import with sys.path injection
    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)

    try:
        from pydantic import ValidationError

        from scripts.executor.jsonl_store import Recommendation
    except ImportError as e:
        logger_error = f"Could not import Recommendation model: {e}"
        print(f"ERROR: {logger_error}")
        failed.append("Recommendations schema validation")
        return
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)

    errors: list[str] = []
    try:
        lines = recs_jsonl.read_text(encoding="utf-8").splitlines()
        for line_num, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError as e:
                errors.append(f"Line {line_num}: JSON parse error: {e}")
                continue

            try:
                Recommendation.model_validate(entry)
            except ValidationError as e:
                field_errors = "; ".join(f"{err['loc'][0]}: {err['msg']}" for err in e.errors())
                errors.append(f"Line {line_num}: {field_errors}")
                continue

            # Catch banned acceptance patterns at commit time.
            # 'python -c' with nested quotes breaks shell escaping in executor pre-flight.
            # Exclude cases where 'python -c' appears as a grep search string (inside quotes).
            acceptance = entry.get("acceptance") or ""
            if "python -c" in acceptance and "'python -c'" not in acceptance:
                errors.append(
                    f"Line {line_num}: acceptance contains banned pattern 'python -c'"
                    f" (use a shell command or pytest invocation instead)"
                )
    except OSError as e:
        errors.append(f"Could not read JSONL file: {e}")

    if errors:
        print("Recommendations schema validation errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Recommendations schema validation")
    else:
        print("Recommendations schema validation passed.")


def validate_outbox_staleness(failed: list[str]) -> None:
    """Warn if ops outbox has files older than 24 hours."""
    print("\n=== Ops outbox staleness check ===")
    outbox_dir = ROOT / "logs" / ".ops-outbox"
    if not outbox_dir.exists():
        print("  No outbox directory -- OK")
        return
    import time

    now = time.time()
    stale_count = 0
    for table_dir in outbox_dir.iterdir():
        if not table_dir.is_dir():
            continue
        for f in table_dir.glob("*.jsonl"):
            age_hours = (now - f.stat().st_mtime) / 3600
            if age_hours > 24:
                stale_count += 1
    if stale_count > 0:
        msg = f"  WARNING: {stale_count} outbox entries older than 24h -- run: python -m scripts.sync_ops drain"
        print(msg)
        # Warning only, not a hard failure (SSO may be legitimately unavailable).
    else:
        total = sum(1 for _ in outbox_dir.rglob("*.jsonl"))
        print(f"  {total} outbox entries, none stale -- OK")


def validate_executor_boundary(failed: list[str]) -> None:
    """Validate that no open rec with automatable:true targets an executor boundary file.

    Decision 44: executor machinery files (prompts, scripts, tests) must only be
    modified via /plan -> /implement, never by the autonomous executor.
    Uses _EXECUTOR_BOUNDARY_PATTERNS to classify boundary files.

    Matches only the rec's `file` field -- the executor's edit target. Acceptance-command
    text is intentionally not matched: a verification command that merely references a
    boundary filename (e.g. `grep 'DECISIONS.md' ...`) does not modify it, so matching it
    produced false positives.
    """
    print("\n=== Executor boundary validation ===")
    import json

    recs_jsonl = ROOT / "logs" / ".recommendations-log.jsonl"

    if not recs_jsonl.exists():
        print("logs/.recommendations-log.jsonl not found — skipping.")
        return

    violations: list[tuple[str, str, str]] = []
    try:
        lines = recs_jsonl.read_text(encoding="utf-8").splitlines()
        by_id: dict = {}
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            rec_id = entry.get("id")
            if rec_id:
                by_id[rec_id] = entry
        for entry in by_id.values():
            if entry.get("status") != "open" or entry.get("automatable") is not True:
                continue
            file_field = entry.get("file", "")
            for pat in _EXECUTOR_BOUNDARY_PATTERNS:
                if pat in file_field:
                    violations.append((entry.get("id", "?"), file_field, pat))
                    break
    except OSError as e:
        print(f"ERROR: Could not read JSONL file: {e}")
        failed.append("Executor boundary validation")
        return

    if violations:
        print("Executor boundary violations (open rec with automatable:true targets boundary file):")
        for rec_id, file_field, matched_pat in violations:
            print(f"  - {rec_id}: file='{file_field}' matches pattern '{matched_pat}'")
        failed.append("Executor boundary validation")
    else:
        print("Executor boundary validation passed.")


def validate_test_coverage(failed: list[str]) -> None:
    """Check that changed source files have test files and 100% per-file coverage."""
    print("\n=== Test coverage check ===")

    # Break recursion: if we're already inside a coverage subprocess
    # (test_coverage_checker.py -> pytest -> test -> validate.py), skip
    # the coverage check to prevent infinite fork explosion.
    import os

    if os.environ.get("_COVERAGE_SUBPROCESS") == "1":
        print("Inside coverage subprocess — skipping to prevent recursion.")
        return

    checker = _load_coverage_checker()
    if checker is None:
        print("test_coverage_checker.py not found — skipping.")
        return

    source_files = checker.get_changed_source_files()
    if not source_files:
        print("No source file changes to check.")
        return

    missing_tests: list[str] = []
    for src in source_files:
        ok, msg = checker.check_test_file_exists(src)
        if not ok:
            try:
                rel = src.relative_to(ROOT)
            except ValueError:
                rel = src
            missing_tests.append(f"{rel}: {msg}")

    coverage_errors: list[str] = []
    if not missing_tests:
        coverage_errors = checker.check_per_file_coverage(source_files)

    n = len(source_files)
    m = len(missing_tests)
    k = len(coverage_errors)
    print(f"Test coverage check: {n} source files checked, {m} missing test files, {k} below 100% coverage")

    if missing_tests:
        for e in missing_tests:
            print(f"  - {e}")
        failed.append("Test coverage check")

    if coverage_errors:
        for e in coverage_errors:
            print(f"  - {e}")
        failed.append("Coverage below 100%")


def validate_prompt_compliance(failed: list[str]) -> None:
    """Run prompt compliance checks against declared behavioural invariants."""
    print("\n=== Prompt compliance check ===")
    compliance = _load_prompt_compliance()
    if compliance is None:
        print("prompt_compliance.py not found — skipping.")
        return

    prompts_dir = ROOT / ".github" / "prompts"
    prompt_files = list(prompts_dir.glob("*.prompt.md"))
    violations: list[str] = []

    retro_log = ROOT / "logs" / ".retro-lite-log.jsonl"
    state_path = ROOT / "logs" / ".execution-state.json"

    # Lazy import of s3_log_store to avoid import-time sys.path dependency
    # (validate.py may be invoked as a standalone script without sys.path injection)
    try:
        from scripts.s3_log_store import get_backend, read_jsonl  # noqa: F401

        _s3_available = True
    except ImportError:
        _s3_available = False

    for prompt_file in prompt_files:
        invariants = compliance.parse_invariants(prompt_file)
        if not invariants:
            continue

        retro_entries = compliance.parse_retro_lite_log(retro_log)
        execution_state = compliance.parse_execution_state(state_path)

        step_violations = compliance.check_retro_lite_compliance(invariants, retro_entries, execution_state)
        violations.extend(f"{prompt_file.name}: {v}" for v in step_violations)

    if violations:
        print("Prompt compliance violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("Prompt compliance check")
    else:
        print(f"Prompt compliance: {len(prompt_files)} prompt file(s) checked, no violations.")


def validate_copilot_multipliers(failed: list[str]) -> None:
    """Validate copilot_model_multipliers.yaml integrity and structure."""
    print("\n=== Copilot multipliers validation ===")

    import yaml

    config_path = ROOT / "config" / "agent" / "copilot" / "model_multipliers.yaml"

    if not config_path.exists():
        print(f"ERROR: {config_path} not found")
        failed.append("Copilot multipliers validation")
        return

    try:
        content = config_path.read_text(encoding="utf-8")
        config = yaml.safe_load(content)
    except yaml.YAMLError as e:
        print(f"ERROR: Invalid YAML in {config_path}: {e}")
        failed.append("Copilot multipliers validation")
        return
    except Exception as e:
        print(f"ERROR: Failed to read {config_path}: {e}")
        failed.append("Copilot multipliers validation")
        return

    errors: list[str] = []

    if not isinstance(config, dict):
        errors.append("Config is not a YAML dict")
    else:
        metadata = config.get("metadata", {})
        if not isinstance(metadata, dict):
            errors.append("metadata field is not a dict")
        else:
            for required_field in ("source_url", "last_verified", "next_review"):
                if required_field not in metadata:
                    errors.append(f"Missing metadata field: {required_field}")

        default_mult = config.get("default_multiplier")
        if default_mult is None:
            errors.append("Missing default_multiplier field")
        elif not isinstance(default_mult, (int, float)) or (isinstance(default_mult, bool)):
            errors.append(f"default_multiplier must be numeric, got {default_mult}")

        multipliers = config.get("multipliers", {})
        if not isinstance(multipliers, dict):
            errors.append("multipliers field is not a dict")
        else:
            for model_name, multiplier_value in multipliers.items():
                if not isinstance(multiplier_value, (int, float)) or isinstance(multiplier_value, bool):
                    errors.append((f"Model {model_name}: multiplier must be numeric, got {multiplier_value}"))
                elif not (0.0 <= multiplier_value <= 30.0):
                    errors.append((f"Model {model_name}: multiplier {multiplier_value} out of range (0.0 - 30.0)"))

    if errors:
        print("Copilot multipliers validation errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Copilot multipliers validation")
    else:
        print(
            f"Copilot multipliers config valid: "
            f"{len(config.get('multipliers', {}))} models, "
            f"default multiplier={config.get('default_multiplier')}"
        )


def _is_inside_try(content: str, pos: int) -> bool:
    """Return True if position pos is nested inside any try() call (at any depth).

    Algorithm: walk backwards from pos tracking parenthesis depth. Every time a
    '(' is found while depth is 0, it is an enclosing call boundary. Check
    whether its identifier is exactly 'try' (word boundary enforced). If yes,
    return True. If not, keep depth at 0 and continue walking to find higher
    ancestors.

    Examples::

        try(filemd5("x"))              -> True  (direct parent)
        try(md5(file("x")))            -> True  (ancestor, not direct parent)
        filemd5("x")                   -> False (no enclosing try)
        retry(filemd5("x"))            -> False ('retry' is not 'try')
    """
    depth = 0
    i = pos - 1
    while i >= 0:
        ch = content[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth > 0:
                depth -= 1
            else:
                # depth == 0: this ( is an enclosing call boundary
                preceding = content[max(0, i - 10) : i]
                if re.search(r"(?<![\w])try$", preceding):
                    return True
                # depth stays 0: continue looking for outer ancestors
        i -= 1
    return False


def validate_decisions_local_writes(failed: list[str]) -> None:
    """Enforce that no .py file directly writes to .decisions-index.jsonl.

    The local decisions cache is a read-only downstream projection of Athena.
    All writes must go through scripts.ops_data_portal (file_decision, update_decision)
    which handles write-through. Cache rebuild happens via sync_ops pull only.

    Whitelisted files (permitted to write directly):
      - scripts/ops_data_portal.py  (write-through cache update)
      - scripts/sync_ops.py         (cache rebuild from Athena)
    """
    print("\n=== Decisions JSONL write-path enforcement ===")
    scripts_dir = ROOT / "scripts"
    personal_dir = ROOT / "personal_scripts"
    _WHITELIST = {
        scripts_dir / "ops_data_portal.py",
        scripts_dir / "sync_ops.py",
    }
    _PATTERNS = [
        re.compile(r'\.decisions-index\.jsonl.*open\(.*["\'][aw]["\']', re.DOTALL),
        re.compile(r'DECISIONS_JSONL\.open\(["\'][aw]["\']'),
        re.compile(r'decisions.index\.jsonl.*["\'][aw]["\']'),
    ]
    errors: list[str] = []

    search_dirs = [scripts_dir]
    if personal_dir.exists():
        search_dirs.append(personal_dir)

    for search_dir in search_dirs:
        for py_file in sorted(search_dir.glob("**/*.py")):
            if py_file in _WHITELIST:
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in _PATTERNS:
                if pattern.search(content):
                    rel = py_file.relative_to(ROOT)
                    errors.append(
                        f"{rel}: writes to .decisions-index.jsonl but not on decisions write-path whitelist. "
                        f"See validate_decisions_local_writes docstring."
                    )
                    break

    if errors:
        print("Decisions JSONL write-path violations:")
        for e in errors:
            print(f"  - {e}")
        for e in errors:
            failed.append(e)
    else:
        print("All .decisions-index.jsonl writes originate from whitelisted files.")


def validate_rec_write_paths(failed: list[str]) -> None:
    """Enforce that no .py file directly writes to the recommendations JSONL.

    All writes must go through scripts.ops_data_portal (file_rec, update_rec).
    Direct JSONL appends bypass DynamoDB ID allocation, Pydantic validation,
    and OpsWriter S3 staging.

    Whitelisted files (permitted to write directly):
      - scripts/ops_data_portal.py  (the portal itself)
      - scripts/sync_recommendations.py  (cache overwrite by design)
    """
    print("\n=== Rec JSONL write-path enforcement ===")
    scripts_dir = ROOT / "scripts"
    personal_dir = ROOT / "personal_scripts"
    _WHITELIST = {
        scripts_dir / "ops_data_portal.py",
        scripts_dir / "sync_recommendations.py",
        scripts_dir / "sync_ops.py",
        scripts_dir / "s3_log_store.py",
        scripts_dir / "session_postflight.py",
    }
    # Patterns that indicate a direct JSONL write or routing bypass
    _PATTERNS = [
        re.compile(r'RECS_JSONL\.open\(["\']a["\']'),
        re.compile(r'RECS_JSONL\.open\(["\']w["\']'),
        re.compile(r'recommendations-log\.jsonl.*open\(.*["\'][aw]["\']', re.DOTALL),
        re.compile(r"append_jsonl\s*\(\s*_RECS_KEY"),
        re.compile(r'append_jsonl\s*\(\s*["\']\.recommendations-log\.jsonl["\']'),
    ]
    errors: list[str] = []

    search_dirs = [scripts_dir]
    if personal_dir.exists():
        search_dirs.append(personal_dir)

    for search_dir in search_dirs:
        for py_file in sorted(search_dir.glob("**/*.py")):
            if py_file in _WHITELIST:
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in _PATTERNS:
                for m in pattern.finditer(content):
                    lineno = content[: m.start()].count("\n") + 1
                    rel = py_file.relative_to(ROOT)
                    errors.append(f"{rel}:{lineno}: direct rec JSONL write detected (use ops_data_portal)")
                    break  # one report per file per pattern is enough

    if errors:
        print("Rec write-path violations found:")
        for e in errors:
            print(f"  - {e}")
        for e in errors:
            failed.append(e)
    else:
        print("No direct rec JSONL writes outside whitelist.")


def validate_warehouse_write_sources(failed: list[str]) -> None:
    """Enforce the warehouse-as-source-of-truth invariant.

    Every call to OpsWriter().write("ops_*", ...) must originate from a
    whitelisted file. The whitelist captures the four legitimate write paths:
    1. Portal calls (file_rec/update_rec/file_decision/update_decision)
    2. Canonical ETL from a non-warehouse source of truth (DECISIONS.md -> ops_decisions)
    3. Outbox drain (write-once transient buffer, never replayable)
    4. Fresh in-memory writes (e.g. priority queue enrichment, execution plan save)

    Any new file that writes to an ops_* table must be reviewed against the
    warehouse-as-source invariant in CLAUDE.md before being added to the
    whitelist. Replaying a read cache (e.g. logs/.recommendations-log.jsonl) into
    the warehouse is the resurrection anti-pattern that creates infinite
    re-injection loops -- Iceberg DELETE removes the snapshot, the next replay
    re-injects, SCD2 dedupe surfaces the resurrection as the current row.
    """
    print("\n=== Warehouse write-source whitelist ===")
    scripts_dir = ROOT / "scripts"
    src_dir = ROOT / "src"

    _WHITELIST = {
        scripts_dir / "ops_data_portal.py",
        scripts_dir / "session_postflight.py",
        scripts_dir / "sync_ops.py",
        scripts_dir / "ops_writer.py",
        scripts_dir / "s3_log_store.py",
        scripts_dir / "executor" / "plan.py",
        scripts_dir / "validate.py",  # contains regex patterns that match the rule
    }

    _PATTERNS = [
        re.compile(r'OpsWriter\(\)\.write\(\s*["\']ops_'),
        re.compile(r'\b(?:writer|ops|_writer)\.write\(\s*["\']ops_'),
    ]

    # Table-specific block: ops_recommendations must NEVER route to OpsWriter/Iceberg after T2.19.
    # This catches any site (including whitelisted files) that re-introduces the split-brain.
    # Self-excluded: validate.py itself contains the pattern strings and would otherwise self-flag.
    _RECS_BLOCK_PATTERNS = [
        re.compile(r'OpsWriter\(\)\.write\(\s*["\']ops_recommendations'),
        re.compile(r'OpsWriter\(\)\.compact\(\s*["\']ops_recommendations'),
        re.compile(r'\b(?:writer|ops|_writer)\.write\(\s*["\']ops_recommendations'),
        re.compile(r'\b(?:writer|ops|_writer)\.compact\(\s*["\']ops_recommendations'),
    ]

    errors: list[str] = []
    for search_dir in [scripts_dir, src_dir]:
        if not search_dir.exists():
            continue
        for py_file in sorted(search_dir.glob("**/*.py")):
            try:
                content = py_file.read_text(encoding="utf-8")
            except OSError:
                continue

            # Table-specific ops_recommendations block (applies to ALL files, including whitelist).
            if py_file != scripts_dir / "validate.py":
                for recs_pat in _RECS_BLOCK_PATTERNS:
                    if recs_pat.search(content):
                        rel = py_file.relative_to(ROOT)
                        errors.append(
                            f"{rel}: writes/compacts ops_recommendations via OpsWriter -- "
                            "recs transit the DuckLake closed boundary (Decision 81 cl.7 / T2.19). "
                            "Use ops_data_portal.file_rec / update_rec."
                        )
                        break

            if py_file in _WHITELIST:
                continue
            for pattern in _PATTERNS:
                if pattern.search(content):
                    rel = py_file.relative_to(ROOT)
                    errors.append(
                        f"{rel}: writes to ops_* table but not on warehouse-write whitelist. "
                        f"See validate_warehouse_write_sources docstring."
                    )
                    break

    if errors:
        print("Warehouse write-source violations:")
        for e in errors:
            print(f"  - {e}")
        for e in errors:
            failed.append(e)
    else:
        print("All ops_* writes originate from whitelisted files.")


def validate_subprocess_encoding(failed: list[str]) -> None:
    """Check that subprocess.run/Popen with text=True also specifies encoding=."""
    print("\n=== Subprocess encoding lint ===")
    scripts_dir = ROOT / "scripts"
    errors: list[str] = []

    for py_file in sorted(scripts_dir.glob("**/*.py")):
        content = py_file.read_text(encoding="utf-8")
        for match in re.finditer(r"\bsubprocess\.(run|Popen)\(", content):
            start = match.end()
            depth = 1
            pos = start
            while pos < len(content) and depth > 0:
                if content[pos] == "(":
                    depth += 1
                elif content[pos] == ")":
                    depth -= 1
                pos += 1
            call_body = content[start : pos - 1]
            if re.search(r"\btext\s*=\s*True", call_body) and not re.search(r"\bencoding\s*=", call_body):
                line_num = content[: match.start()].count("\n") + 1
                rel = py_file.relative_to(ROOT)
                errors.append(f"{rel}:{line_num}: subprocess.{match.group(1)} with text=True must specify encoding='utf-8'")

    if errors:
        print("Subprocess encoding lint errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Subprocess encoding lint")
    else:
        print("All subprocess calls with text=True specify encoding.")


def validate_sys_executable(failed: list[str]) -> None:
    """Check scripts use sys.executable instead of bare 'python'/'pip' in subprocess calls."""
    print("\n=== sys.executable lint ===")
    scripts_dir = ROOT / "scripts"
    errors: list[str] = []

    pattern = re.compile(r"""\bsubprocess\.(run|Popen)\s*\(\s*\[\s*['\"](python|pip)['\"]""")

    for py_file in sorted(scripts_dir.glob("**/*.py")):
        content = py_file.read_text(encoding="utf-8")
        for m in pattern.finditer(content):
            line_num = content[: m.start()].count("\n") + 1
            rel = py_file.relative_to(ROOT)
            errors.append(f"{rel}:{line_num}: Use sys.executable instead of '{m.group(2)}' in subprocess calls")

    if errors:
        print("sys.executable lint errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("sys.executable lint")
    else:
        print("All subprocess calls use sys.executable (no bare 'python'/'pip').")


def validate_terraform_try(failed: list[str]) -> None:
    """Check that filemd5() and file() in .tf files are wrapped with try()."""
    print("\n=== Terraform try() lint ===")
    tf_dir = ROOT / "terraform"
    errors: list[str] = []

    for tf_file in sorted(tf_dir.glob("*.tf")):
        content = tf_file.read_text(encoding="utf-8")
        for m in re.finditer(r"\bfilemd5\s*\(|(?<![\w])file\s*\(", content):
            if not _is_inside_try(content, m.start()):
                fn_name = "filemd5()" if "filemd5" in m.group() else "file()"
                line_num = content[: m.start()].count("\n") + 1
                errors.append(f"{tf_file.name}:{line_num}: {fn_name} must be wrapped in try() for CI compatibility")

    if errors:
        print("Terraform try() lint errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Terraform try() lint")
    else:
        print("All filemd5() and file() calls in terraform files are wrapped with try().")


def validate_no_underscore_instructions(failed: list[str]) -> None:
    """Fail if .github/copilot_instructions.md (underscore) exists.

    VS Code loads .github/copilot-instructions.md (hyphen).  The underscore
    variant is a ghost file that consumes context budget and diverges silently.
    Decision 38 deleted it; this check prevents accidental re-creation.
    """
    print("\n=== Underscore instruction file check ===")
    underscore_path = ROOT / ".github" / "copilot_instructions.md"
    if underscore_path.exists():
        print(f"  [FAIL] {underscore_path.relative_to(ROOT)} exists -- delete it (Decision 38).")
        failed.append("Underscore instruction file check")
    else:
        print("No underscore instruction file found. OK.")


def validate_invariants(failed: list[str]) -> None:
    """Check codebase-level invariants that guard known failure modes.

    Check 1 (@file gotcha): Scan scripts/ (excluding copilot_wrapper.py) for
    direct copilot subprocess invocations that use '-p @file' without an inline
    instruction string -- this causes agentic models to implement specs rather
    than plan against them (see 'Copilot CLI @file vs user message' gotcha).

    Check 2 (mock count): Verify that the subprocess.run calls added to
    cleanup_after_merge() in scripts/executor/postflight.py are covered by the
    mock side_effect lists in TestCleanupAfterMerge. A mismatch causes silent
    StopIteration failures in CI (see 'cleanup_after_merge mock exhaustion' gotcha).
    """
    print("\n=== Invariant checks ===")
    errors: list[str] = []
    scripts_dir = ROOT / "scripts"

    # -----------------------------------------------------------------------
    # Check 1: @file without instruction in copilot subprocess calls
    # Scan all scripts EXCEPT copilot_wrapper.py (the canonical implementation).
    # If any other script constructs a copilot command with '-p @file' (without
    # a preceding instruction string), flag it.
    # -----------------------------------------------------------------------
    wrapper_path = scripts_dir / "copilot_wrapper.py"
    at_file_pattern = re.compile(r'"-p"\s*,\s*f?"@')
    for py_file in sorted(scripts_dir.glob("**/*.py")):
        if py_file.resolve() == wrapper_path.resolve():
            continue
        content = py_file.read_text(encoding="utf-8")
        for m in at_file_pattern.finditer(content):
            line_num = content[: m.start()].count("\n") + 1
            rel = py_file.relative_to(ROOT)
            errors.append(
                f"{rel}:{line_num}: Copilot CLI @file used without instruction string -- "
                "see 'Copilot CLI @file vs user message' gotcha and docs/contracts/copilot-cli.md"
            )

    # -----------------------------------------------------------------------
    # Check 2: cleanup_after_merge mock side_effect count
    # Count subprocess.run calls in cleanup_after_merge() and compare against
    # the maximum side_effect list length in TestCleanupAfterMerge tests.
    # Formula: subprocess_count > max_side_effect * 2 + 2 -> mismatch
    # (The factor of 2+2 accounts for conditional branches that not all tests
    # exercise; adding a new subprocess.run call shifts the balance.)
    # -----------------------------------------------------------------------
    postflight_path = ROOT / "scripts" / "executor" / "postflight.py"
    test_path = ROOT / "tests" / "test_execute_recommendation.py"
    if postflight_path.exists() and test_path.exists():
        postflight_src = postflight_path.read_text(encoding="utf-8")
        # Extract cleanup_after_merge function body
        fn_match = re.search(
            r"def cleanup_after_merge\(.*?\).*?(?=\ndef |\Z)",
            postflight_src,
            re.DOTALL,
        )
        if fn_match:
            fn_body = fn_match.group()
            subprocess_count = len(re.findall(r"\bsubprocess\.run\(", fn_body))

            test_src = test_path.read_text(encoding="utf-8")
            # Find TestCleanupAfterMerge class body
            class_match = re.search(
                r"class TestCleanupAfterMerge\b.*?(?=\nclass |\Z)",
                test_src,
                re.DOTALL,
            )
            if class_match:
                class_body = class_match.group()
                # Find all list literals containing MagicMock items (covers both
                # inline side_effect=[...] and pre-assigned variables like responses=[...])
                list_items_pattern = re.compile(
                    r"\[([^\[\]]*(?:MagicMock|CalledProcessError)[^\[\]]*)\]",
                    re.DOTALL,
                )
                max_side_effect = 0
                for match in list_items_pattern.finditer(class_body):
                    item_count = len(re.findall(r"MagicMock\(", match.group(1)))
                    max_side_effect = max(max_side_effect, item_count)

                threshold = max_side_effect * 2 + 2
                if subprocess_count > threshold:
                    errors.append(
                        f"cleanup_after_merge mock side_effect count mismatch: "
                        f"function has {subprocess_count} subprocess.run calls but "
                        f"max side_effect list has {max_side_effect} entries "
                        f"(threshold: {threshold}). Update TestCleanupAfterMerge side_effect lists."
                    )

    if errors:
        print("Invariant check errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Invariant checks")
    else:
        print("All invariant checks passed.")


_SLOC_LIMIT = 500
_CC_LIMIT = 20
_WAIVER_PATTERN = re.compile(r"#\s*complexity-waiver:\s*decision-43")
_SLOC_EXCLUDE_DIRS = {"pip", "lambda-packages", "docker", "terraform", ".venv", "node_modules"}
_BRANCH_TYPES = (ast.If, ast.For, ast.While, ast.Try, ast.ExceptHandler, ast.With, ast.BoolOp)


def validate_sloc_limits(failed: list[str]) -> None:
    """Enforce Decision 43: max 500 SLOC per Python file unless waivered."""
    print("\n=== SLOC limits (Decision 43) ===")
    errors: list[str] = []

    for search_dir in (ROOT / "scripts", ROOT / "src"):
        if not search_dir.exists():
            continue
        for py_file in sorted(search_dir.glob("**/*.py")):
            if py_file.name == "__init__.py":
                continue
            if any(part in _SLOC_EXCLUDE_DIRS for part in py_file.parts):
                continue
            content = py_file.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            sloc = len([ln for ln in lines if ln.strip() and not ln.strip().startswith("#")])
            if sloc <= _SLOC_LIMIT:
                continue
            # Check first 10 lines for waiver
            header = "\n".join(lines[:10])
            if _WAIVER_PATTERN.search(header):
                continue
            rel = py_file.relative_to(ROOT)
            errors.append(
                f"{str(rel).replace(chr(92), '/')}: {sloc} SLOC "
                f"(limit {_SLOC_LIMIT}). Add '# complexity-waiver: decision-43' or reduce."
            )

    if errors:
        print("SLOC limit violations:")
        for e in errors:
            print(f"  - {e}")
        failed.append("SLOC limits (Decision 43)")
    else:
        print("All files within SLOC limits or waivered.")


def validate_cc_limits(failed: list[str]) -> None:
    """Enforce Decision 43: max 20 cyclomatic-complexity branches per function unless waivered."""
    print("\n=== Cyclomatic complexity limits (Decision 43) ===")
    errors: list[str] = []

    for search_dir in (ROOT / "scripts", ROOT / "src"):
        if not search_dir.exists():
            continue
        for py_file in sorted(search_dir.glob("**/*.py")):
            if py_file.name == "__init__.py":
                continue
            if any(part in _SLOC_EXCLUDE_DIRS for part in py_file.parts):
                continue
            content = py_file.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()
            header = "\n".join(lines[:10])
            if _WAIVER_PATTERN.search(header):
                continue
            try:
                tree = ast.parse(content)
            except SyntaxError:
                continue
            rel = str(py_file.relative_to(ROOT)).replace(chr(92), "/")
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                branch_count = sum(1 for sub in ast.walk(node) if isinstance(sub, _BRANCH_TYPES))
                if branch_count > _CC_LIMIT:
                    errors.append(
                        f"{rel}::{node.name}: {branch_count} branches "
                        f"(limit {_CC_LIMIT}). Add '# complexity-waiver: decision-43' or reduce."
                    )

    if errors:
        print("Cyclomatic complexity violations:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Cyclomatic complexity limits (Decision 43)")
    else:
        print("All functions within CC limits or waivered.")


def validate_complexity(failed: list[str]) -> list[dict]:
    """Analyze code complexity by package (Python) and prompt density.

    Performs AST-based analysis of Python files counting public functions
    and import fan-out grouped by top-level package. Analyzes prompt files
    for imperative-statement density. Flags files >2 std-devs above their
    package mean as warnings. Packages with <3 files are skipped. Writes
    warnings to logs/.complexity-warnings.json. Never appends to failed.
    """
    print("\n=== Code complexity analysis ===")

    _EXCLUDE_PATTERNS = {"__init__.py", "conftest.py"}
    _EXCLUDE_DIRS = {"pip", "lambda-packages", "docker", "terraform"}

    def _should_exclude(path: Path) -> bool:
        if path.name in _EXCLUDE_PATTERNS:
            return True
        for part in path.parts:
            if part in _EXCLUDE_DIRS:
                return True
        return False

    def _count_public_functions(filepath: Path) -> int:
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError):
            return 0
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                count += 1
        return count

    def _count_imports(filepath: Path) -> int:
        try:
            tree = ast.parse(filepath.read_text(encoding="utf-8"))
        except (SyntaxError, ValueError):
            return 0
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        return len(imports)

    def _get_package(filepath: Path) -> str:
        try:
            rel = filepath.relative_to(ROOT)
            parts = rel.parts
            if parts[0] == "src" and len(parts) > 1:
                return parts[1]
            return parts[0]
        except ValueError:
            return "unknown"

    def _count_imperative_statements(filepath: Path) -> float:
        try:
            content = filepath.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            return 0.0
        if not content:
            return 0.0
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            return 0.0
        imperative_count = sum(
            1
            for line in lines
            if re.match(
                r"^(You |Do |Must |Should |Add |Create |Implement |Update )",
                line,
            )
        )
        return imperative_count / len(lines)

    # Collect Python file metrics
    py_metrics: dict[str, list[tuple[Path, float]]] = {}

    src_dir = ROOT / "src"
    if src_dir.exists():
        for py_file in sorted(src_dir.glob("**/*.py")):
            if _should_exclude(py_file):
                continue
            pkg = _get_package(py_file)
            complexity = float(_count_public_functions(py_file) + _count_imports(py_file))
            if pkg not in py_metrics:
                py_metrics[pkg] = []
            py_metrics[pkg].append((py_file, complexity))

    scripts_dir = ROOT / "scripts"
    if scripts_dir.exists():
        for py_file in sorted(scripts_dir.glob("**/*.py")):
            if _should_exclude(py_file):
                continue
            pkg = _get_package(py_file)
            complexity = float(_count_public_functions(py_file) + _count_imports(py_file))
            if pkg not in py_metrics:
                py_metrics[pkg] = []
            py_metrics[pkg].append((py_file, complexity))

    # Flag outliers in Python files
    py_warnings: list[dict] = []
    for pkg, entries in py_metrics.items():
        if len(entries) < 3:
            continue
        values = [c for _, c in entries]
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if len(values) > 1 else 0.0
        if stdev <= 0:
            continue
        threshold = mean + 2 * stdev
        for py_file, complexity in entries:
            if complexity > threshold:
                rel = py_file.relative_to(ROOT)
                py_warnings.append(
                    {
                        "file": str(rel).replace("\\", "/"),
                        "type": "python",
                        "complexity": complexity,
                        "package": pkg,
                        "mean": round(mean, 2),
                        "stdev": round(stdev, 2),
                        "threshold": round(threshold, 2),
                    }
                )

    # Collect prompt file metrics
    prompt_warnings: list[dict] = []
    prompts_dir = ROOT / ".github" / "prompts"
    if prompts_dir.exists():
        prompt_entries: list[tuple[Path, float]] = []
        for md_file in sorted(prompts_dir.glob("**/*.md")):
            density = _count_imperative_statements(md_file)
            prompt_entries.append((md_file, density))

        if len(prompt_entries) >= 3:
            densities = [d for _, d in prompt_entries]
            mean = statistics.mean(densities)
            stdev = statistics.stdev(densities) if len(densities) > 1 else 0.0
            if stdev > 0:
                threshold = mean + 2 * stdev
                for md_file, density in prompt_entries:
                    if density > threshold:
                        rel = md_file.relative_to(ROOT)
                        prompt_warnings.append(
                            {
                                "file": str(rel).replace("\\", "/"),
                                "type": "prompt",
                                "density": round(density, 3),
                                "mean": round(mean, 3),
                                "stdev": round(stdev, 3),
                                "threshold": round(mean + 2 * stdev, 3),
                            }
                        )

    warnings = py_warnings + prompt_warnings

    # Write warnings to JSON file
    warnings_file = ROOT / "logs" / ".complexity-warnings.json"
    warnings_file.parent.mkdir(parents=True, exist_ok=True)
    warnings_file.write_text(json.dumps(warnings, indent=2), encoding="utf-8")

    if warnings:
        print("Complexity warnings (>2 stdev above package mean):")
        for w in warnings:
            if w["type"] == "python":
                print(
                    f"  {w['file']}: complexity {w['complexity']} "
                    f"(pkg {w['package']} mean={w['mean']}, "
                    f"stdev={w['stdev']}, threshold={w['threshold']})"
                )
            else:
                print(
                    f"  {w['file']}: imperative density {w['density']} "
                    f"(mean={w['mean']}, stdev={w['stdev']}, "
                    f"threshold={w['threshold']})"
                )
    else:
        print("No complexity warnings found.")

    return warnings


def validate_iam_runner_policy(failed: list[str]) -> None:
    """Verify that all IAM actions in iam_runner_manifest.yaml are present in terraform/ec2_runner.tf.

    Wired into --pre mode: provides a static local gate that ensures infrastructure
    policy stays in sync with code requirements without requiring an AWS connection.
    """
    manifest_path = ROOT / "config" / "agent" / "validate" / "iam_runner_manifest.yaml"
    terraform_path = ROOT / "terraform" / "ec2_runner.tf"

    if not manifest_path.exists():
        print(f"SKIPPED: IAM runner manifest missing at {manifest_path}")
        return

    if not terraform_path.exists():
        failed.append(f"IAM runner policy check: {terraform_path} not found")
        return

    import yaml as _yaml

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = _yaml.safe_load(f) or {}
    except Exception as exc:
        failed.append(f"IAM runner policy check: Failed to load manifest: {exc}")
        return

    actions = manifest.get("actions", [])
    if not actions:
        return

    try:
        hcl_content = terraform_path.read_text(encoding="utf-8")
    except Exception as exc:
        failed.append(f"IAM runner policy check: Failed to read {terraform_path}: {exc}")
        return

    missing = []
    for entry in actions:
        action = entry.get("action")
        if not action:
            continue
        # Ensure action appears within quotes to prevent partial matches
        if f'"{action}"' not in hcl_content:
            missing.append(action)

    if missing:
        failed.append(f"IAM runner policy check: Missing actions in {terraform_path}: {', '.join(missing)}")
    else:
        print("  PASS: IAM runner policy matches manifest")


def _file_budget_breach_rec(elapsed_s: float, diff_manifest: list[str], dominant_phase: str | None) -> None:
    try:
        from scripts.ops_data_portal import file_rec  # noqa: PLC0415

        branch_r = run(["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        branch = branch_r.stdout.strip() or "unknown"
        elapsed_min = elapsed_s / 60
        manifest_summary = ", ".join(diff_manifest[:20]) + ("..." if len(diff_manifest) > 20 else "")
        context = (
            f"Fast-tier budget breach: {elapsed_min:.1f} min elapsed (limit 5 min). "
            f"Branch: {branch}. Dominant phase: {dominant_phase or 'unknown'}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}. "
            f"Investigate which check caused the overrun and move it to the full tier or optimise it."
        )
        file_rec(
            {
                "title": f"Fast-tier budget breach ({elapsed_min:.1f} min) on {branch}",
                "file": "scripts/validate.py",
                "status": "open",
                "source": "budget_breach",
                "effort": "S",
                "priority": "medium",
                "context": context,
                "acceptance": "bin/venv-python -m scripts.validate --pre",
                "risk": "low",
                "automatable": False,
            }
        )
    except Exception:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        print(f"WARNING: budget breach rec filing failed (outbox may handle): {traceback.format_exc()}", file=sys.stderr)


def _file_budget_bypass_rec(elapsed_s: float | None, diff_manifest: list[str], reason: str | None) -> None:
    try:
        from scripts.ops_data_portal import file_rec  # noqa: PLC0415

        branch_r = run(["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        branch = branch_r.stdout.strip() or "unknown"
        manifest_summary = ", ".join(diff_manifest[:20]) + ("..." if len(diff_manifest) > 20 else "")
        elapsed_part = f"{elapsed_s / 60:.1f} min" if elapsed_s is not None else "unknown"
        context = (
            f"Fast-tier budget assertion bypassed via --ignore-budget on branch {branch}. "
            f"Elapsed: {elapsed_part}. Reason: {reason or 'none provided'}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}. "
            f"Repeated bypass (>= 3 in 7 days) triggers a soft alert in session_preflight."
        )
        file_rec(
            {
                "title": f"Fast-tier budget bypassed on {branch}",
                "file": "scripts/validate.py",
                "status": "open",
                "source": "budget_bypass",
                "effort": "S",
                "priority": "low",
                "context": context,
                "acceptance": "bin/venv-python -m scripts.validate --pre",
                "risk": "low",
                "automatable": False,
            }
        )
    except Exception:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        print(f"WARNING: budget bypass rec filing failed (outbox may handle): {traceback.format_exc()}", file=sys.stderr)


def run_lint_checks(failed: list[str], files: list[str] | None = None) -> None:
    if files is not None and not files:
        return
    targets: list[str] = [f for f in files if f.endswith(".py")] if files is not None else ["src/", "tests/"]
    if not targets:
        return
    invoke_step("Lint (ruff check)", [PYTHON, "-m", "ruff", "check"] + targets, failed)
    invoke_step("Format check (ruff format)", [PYTHON, "-m", "ruff", "format", "--check"] + targets, failed)


def _extract_enforced_map(yaml_content: str) -> dict[tuple[str, str | None, str], bool]:
    """Extract {(table, col, test): enforced} from YAML content string for the graduation guard."""
    import yaml as _yaml

    try:
        spec = _yaml.safe_load(yaml_content) or {}
    except Exception:
        return {}
    result: dict[tuple[str, str | None, str], bool] = {}
    for table_name, table_def in (spec.get("tables") or {}).items():
        if not isinstance(table_def, dict):
            continue
        if "row_count" in table_def:
            rc = table_def["row_count"]
            if isinstance(rc, dict):
                result[(table_name, None, "row_count")] = bool(rc.get("enforced", True))
        if "recency" in table_def:
            rec = table_def["recency"]
            if isinstance(rec, dict):
                col = rec.get("column", "")
                result[(table_name, col, "recency")] = bool(rec.get("enforced", True))
        for col_name, col_def in (table_def.get("columns") or {}).items():
            if not isinstance(col_def, dict):
                continue
            for test in col_def.get("tests") or []:
                if isinstance(test, str):
                    result[(table_name, col_name, test)] = True
                elif isinstance(test, dict):
                    test_type = next(iter(test))
                    params = test[test_type]
                    enforced = bool(params.get("enforced", True)) if isinstance(params, dict) else True
                    result[(table_name, col_name, test_type)] = enforced
    return result


def check_source_registry(failed: list[str]) -> None:
    """Verify that all agent names in schedule.yaml are registered canonical_ids.

    Also checks ops_data_portal.py for hardcoded source string literals and verifies
    each is registered. Wired into run_python_checks() -- runs on presubmit.
    """
    import yaml as _yaml

    print("\n=== Source registry CI guard ===")

    registry_path = ROOT / "config" / "agent" / "data_quality" / "source_registry.yaml"
    if not registry_path.exists():
        print(f"  FAIL: {registry_path} not found -- create source_registry.yaml first")
        failed.append("Source registry CI guard")
        return

    registry_data = _yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    valid_ids: set[str] = {e["canonical_id"] for e in registry_data.get("entries", [])}

    violations: list[str] = []

    schedule_path = ROOT / ".github" / "agents" / "schedule.yaml"
    if schedule_path.exists():
        schedule_data = _yaml.safe_load(schedule_path.read_text(encoding="utf-8"))
        for agent in schedule_data.get("agents", []):
            name = agent.get("name", "")
            if name and name not in valid_ids:
                violations.append(f"schedule.yaml agent name '{name}' not in source_registry.yaml")
    else:
        print(f"  WARNING: {schedule_path} not found -- skipping agent name check")

    portal_path = ROOT / "scripts" / "ops_data_portal.py"
    if portal_path.exists():
        portal_source = portal_path.read_text(encoding="utf-8")
        import re as _re

        for match in _re.finditer(r'source\s*==\s*[\'"]([^\'"]+)[\'"]|"source"\s*:\s*"([^"]+)"', portal_source):
            literal = match.group(1) or match.group(2)
            if literal and not literal.startswith("{") and literal not in valid_ids:
                violations.append(f"ops_data_portal.py hardcoded source '{literal}' not in source_registry.yaml")

    if violations:
        for v in violations:
            print(f"  FAIL: {v}")
        failed.append("Source registry CI guard")
    else:
        print(f"  PASS: all agent names and hardcoded source values registered ({len(valid_ids)} entries)")


_YAML_TO_DQ: dict[str, str] = {
    "not_null": "DqNotNull",
    "accepted_values": "DqAcceptedValues",
    "unique": "DqUnique",
    "relationships": "DqRelationship",
    # DqRecency and DqRowCount are intentionally absent: these markers are table-level
    # blocks in ops.yaml (not column-level tests), so they never appear in the per-column
    # check sets that the drift detector compares. Adding them here would cause false drifts.
}


def _check_drift_for_table(failed: list[str], model_cls: type, table_data: dict) -> None:
    """Compare DqXxx Annotated markers in model_cls against YAML table_data column checks.

    Only in-vocabulary checks are compared (not_null, accepted_values, unique, relationships).
    expression, path_syntax, acceptance_lint have no Pydantic equivalents per CD.12.
    DqDeleted fields short-circuit before YAML lookup. MigratingMarker allows divergence
    until target date passes. Added by T0.12.
    """
    import typing  # noqa: PLC0415

    from src.schemas.annotations import DqDeleted, MigratingMarker  # noqa: PLC0415

    columns: dict = table_data.get("columns", {})
    hints = typing.get_type_hints(model_cls, include_extras=True)

    for field_name, hint in hints.items():
        if typing.get_origin(hint) is not typing.Annotated:
            continue

        args = typing.get_args(hint)
        metadata = args[1:]

        if any(isinstance(m, DqDeleted) for m in metadata):
            continue

        migrating_marker = next((m for m in metadata if isinstance(m, MigratingMarker)), None)

        if field_name not in columns:
            continue

        if migrating_marker and not migrating_marker.is_expired():
            continue

        pydantic_dq_names: set[str] = {type(m).__name__ for m in metadata if type(m).__name__.startswith("Dq")}

        col_entry = columns[field_name] or {}
        yaml_tests = col_entry.get("tests", []) if isinstance(col_entry, dict) else []
        yaml_dq_names: set[str] = set()
        for test in yaml_tests:
            if isinstance(test, str):
                mapped = _YAML_TO_DQ.get(test)
                if mapped:
                    yaml_dq_names.add(mapped)
            elif isinstance(test, dict):
                for check_name in test:
                    mapped = _YAML_TO_DQ.get(check_name)
                    if mapped:
                        yaml_dq_names.add(mapped)

        diff = pydantic_dq_names.symmetric_difference(yaml_dq_names)
        if diff:
            note = ""
            if migrating_marker and migrating_marker.is_expired():
                note = f" (@migrating target={migrating_marker.target!r} expired)"
            print(
                f"  DRIFT: {model_cls.__name__}.{field_name}: "
                f"Pydantic={sorted(pydantic_dq_names)}, YAML={sorted(yaml_dq_names)}{note}"
            )
            failed.append(f"Pydantic-YAML drift: {model_cls.__name__}.{field_name}")


def validate_pydantic_yaml_drift(failed: list[str]) -> None:
    """Detect drift between Annotated DqXxx markers in Pydantic models and ops.yaml.

    Walks RecPayload and DecisionPayload annotated fields. For each overlapping field
    (present in both model and YAML columns), compares in-vocabulary check sets.
    Fails CI when the symmetric difference is non-empty and no active migration marker exists.
    Added by T0.12. Runs in full presubmit only (not --pre).
    """
    import yaml as _yaml  # noqa: PLC0415

    print("\n=== Pydantic-YAML DQ drift ===")

    yaml_path = ROOT / "config" / "agent" / "data_quality" / "ops.yaml"
    if not yaml_path.exists():
        print(f"  FAIL: {yaml_path.relative_to(ROOT)} not found")
        failed.append("Pydantic-YAML drift")
        return

    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from src.schemas import DecisionPayload, RecPayload  # noqa: PLC0415

        with yaml_path.open(encoding="utf-8") as fh:
            ops = _yaml.safe_load(fh)
        tables: dict = ops.get("tables", {})

        before = len(failed)
        _check_drift_for_table(failed, RecPayload, tables.get("ops_recommendations", {}))
        _check_drift_for_table(failed, DecisionPayload, tables.get("ops_decisions", {}))

        if len(failed) == before:
            print("  PASS: pydantic-yaml drift check")
    except ImportError as exc:
        print(f"  ERROR: Could not import src.schemas: {exc}")
        failed.append("Pydantic-YAML drift")
    except _yaml.YAMLError as exc:
        print(f"  FAIL: YAML parse error:\n{exc}")
        failed.append("Pydantic-YAML drift")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Pydantic-YAML drift")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


def validate_platform_roadmap(failed: list[str]) -> None:
    """Validate docs/ROADMAP-PLATFORM.yaml against the RoadmapDocument Pydantic schema.

    Rejects structural drift: duplicate ids, dangling depends_on, dependency cycles,
    unknown gate-rule helpers, invalid filed_via, unsupported document version.
    Added by T-1.5. Runs in full presubmit only (not --pre).
    """
    import yaml as _yaml  # noqa: PLC0415

    print("\n=== Platform roadmap schema validation ===")

    roadmap_path = ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
    if not roadmap_path.exists():
        print(f"  FAIL: {roadmap_path.relative_to(ROOT)} not found")
        failed.append("Platform roadmap schema validation")
        return

    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from pydantic import ValidationError  # noqa: PLC0415

        from scripts.platform_roadmap import load  # noqa: PLC0415

        load(roadmap_path)
        print("  PASS: platform roadmap schema validation passed.")
    except ImportError as exc:
        print(f"  ERROR: Could not import platform_roadmap: {exc}")
        failed.append("Platform roadmap schema validation")
    except ValidationError as exc:
        print(f"  FAIL: Pydantic validation error:\n{exc}")
        failed.append("Platform roadmap schema validation")
    except _yaml.YAMLError as exc:
        print(f"  FAIL: YAML parse error:\n{exc}")
        failed.append("Platform roadmap schema validation")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Platform roadmap schema validation")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


def validate_lambda_manifests(failed: list[str]) -> None:
    """Schema-validate all src/lambdas/<name>/manifest.yaml files.

    Delegates to scripts.lambda_manifest.cmd_validate. Parallel to
    validate_platform_roadmap; runs in the full presubmit tier (NOT --pre).
    Rejects structural drift: unknown fields, missing artifact, invalid status.
    """
    print("\n=== Lambda manifest schema validation ===")

    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.lambda_manifest import cmd_validate  # noqa: PLC0415

        rc = cmd_validate(None)
        if rc != 0:
            failed.append("Lambda manifest schema validation")
    except ImportError as exc:
        print(f"  ERROR: Could not import lambda_manifest: {exc}")
        failed.append("Lambda manifest schema validation")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Lambda manifest schema validation")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


def validate_lambda_manifest_coverage(failed: list[str]) -> None:
    """Every src/lambdas/<name>/ directory must have a schema-valid manifest.yaml.

    Scalability gate: each new Lambda artifact added to src/lambdas/ automatically
    fails CI until its manifest is authored. Delegates to cmd_check_coverage.
    Runs in the full presubmit tier.
    """
    print("\n=== Lambda manifest coverage ===")

    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.lambda_manifest import cmd_check_coverage  # noqa: PLC0415

        rc = cmd_check_coverage(None)
        if rc != 0:
            failed.append("Lambda manifest coverage")
    except ImportError as exc:
        print(f"  ERROR: Could not import lambda_manifest: {exc}")
        failed.append("Lambda manifest coverage")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Lambda manifest coverage")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


def validate_lambda_bundle_completeness(failed: list[str]) -> None:
    """Stage each active Lambda artifact and verify handler imports + declared assets.

    Delegates to scripts.lambda_manifest.cmd_check_bundles, which stages each
    active manifest into a temp dir, checks that every handler module can be
    imported from the staged tree, and checks that every declared assets[]/config[]
    path is physically present in the staged bundle.

    Full presubmit tier ONLY -- NOT --pre (Decision 73: the import-resolution check
    catches missing includes that py_compile cannot see; the asset-presence check
    catches undeclared runtime filesystem reads).
    """
    print("\n=== Lambda bundle completeness ===")

    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.lambda_manifest import cmd_check_bundles  # noqa: PLC0415

        rc = cmd_check_bundles(None)
        if rc != 0:
            failed.append("Lambda bundle completeness")
    except ImportError as exc:
        print(f"  ERROR: Could not import lambda_manifest: {exc}")
        failed.append("Lambda bundle completeness")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Lambda bundle completeness")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


def validate_lambda_deploy_gating(failed: list[str]) -> None:
    """Advisory per-Lambda deploy-scope check (CD.16 + Decision 79).

    Calls compute_affected_artifacts() with the current branch's changed files
    and reports which active Lambda artifacts need per-Lambda deploy/verify
    attention in the plan. Advisory only -- never fails the build; only appends
    to failed on import or setup errors.
    """
    print("\n=== Lambda deploy gating (advisory) ===")

    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.lambda_manifest import compute_affected_artifacts  # noqa: PLC0415

        changed = list(get_changed_files())
        if not changed:
            print("  No changed files detected; skipping deploy-gating scope check.")
            return

        affected = compute_affected_artifacts(changed)
        if not affected:
            print("  No active Lambda artifacts affected by current branch changes.")
            return

        print("  Active Lambda artifacts affected by branch changes (plan must include deploy steps):")
        for slug, files in sorted(affected.items()):
            print(f"    {slug}: {len(files)} file(s) changed")
    except ImportError as exc:
        print(f"  ERROR: Could not import lambda_manifest: {exc}")
        failed.append("Lambda deploy gating")
    except Exception as exc:
        print(f"  FAIL: Unexpected error: {exc}")
        failed.append("Lambda deploy gating")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


def validate_product_roadmap(failed: list[str]) -> None:
    """Validate docs/ROADMAP-PRODUCT.yaml against the ProductRoadmapDocument Pydantic schema.

    Includes cross-roadmap resolution against PLATFORM. Runs in BOTH --pre and full
    presubmit (diverges from validate_platform_roadmap which is full-tier only; the product
    check is pure Python over a single YAML file and runs in well under 100ms -- ROADMAP-
    PRODUCT.yaml is the active editing surface and catching structural drift in the fast-tier
    loop is high-value for product editors without denting the fast-tier budget).
    """
    import yaml as _yaml  # noqa: PLC0415

    print("\n=== Product roadmap schema validation ===")

    product_path = ROOT / "docs" / "ROADMAP-PRODUCT.yaml"
    platform_path = ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
    if not product_path.exists():
        print(f"  FAIL: {product_path.relative_to(ROOT)} not found")
        failed.append("Product roadmap schema validation")
        return

    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from pydantic import ValidationError  # noqa: PLC0415

        from scripts.product_roadmap import load  # noqa: PLC0415

        load(product_path, platform_path=platform_path)
        print("  PASS: product roadmap schema validation passed.")
    except ImportError as exc:
        print(f"  ERROR: Could not import product_roadmap: {exc}")
        failed.append("Product roadmap schema validation")
    except _yaml.YAMLError as exc:
        print(f"  FAIL: YAML parse error:\n{exc}")
        failed.append("Product roadmap schema validation")
    except ValidationError as exc:
        print(f"  FAIL: Pydantic validation error:\n{exc}")
        failed.append("Product roadmap schema validation")
    except (ValueError, OSError) as exc:
        print(f"  FAIL: {exc}")
        failed.append("Product roadmap schema validation")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


def _check_graduation_guard(failed: list[str]) -> None:
    """Block enforced:false->true flips when the check's verdict in dq-latest.json is not PASS.

    Note: --pre skips the enforced graduation guard.
    """
    import json as _json

    print("\n=== Enforced graduation guard ===")
    print("  Note: --pre skips the enforced graduation guard.")

    diff_result = run(
        ["git", "diff", "HEAD", "--name-only", "--", "config/agent/data_quality/"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    changed_files = [f.strip() for f in diff_result.stdout.splitlines() if f.strip().endswith(".yaml")]
    if not changed_files:
        print("  No DQ YAML changes detected -- guard has nothing to check.")
        return

    dq_file = ROOT / "logs" / "debug" / "dq-latest.json"
    if not dq_file.exists():
        print("  WARN: dq-latest.json missing -- cannot verify enforced flips (warn only).")
        return

    try:
        data = _json.loads(dq_file.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        print("  WARN: dq-latest.json unreadable -- cannot verify enforced flips (warn only).")
        return

    checks_list = data.get("checks")
    if not checks_list:
        print("  WARN: dq-latest.json has no 'checks' array -- cannot verify enforced flips (warn only).")
        return

    verdict_lookup: dict[tuple[str, str | None, str], str] = {}
    for entry in checks_list:
        key = (entry.get("table"), entry.get("column"), entry.get("test"))
        verdict_lookup[key] = entry.get("verdict", "UNKNOWN")

    for rel_path in changed_files:
        show_result = run(
            ["git", "show", f"HEAD:{rel_path}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
        )
        old_map = _extract_enforced_map(show_result.stdout) if show_result.returncode == 0 else {}
        new_file = ROOT / rel_path
        if not new_file.exists():
            continue
        new_map = _extract_enforced_map(new_file.read_text(encoding="utf-8"))

        for key, new_enforced in new_map.items():
            if not new_enforced:
                continue
            old_enforced = old_map.get(key, False)
            if old_enforced:
                continue

            verdict = verdict_lookup.get(key)
            table, col, test = key
            col_str = f".{col}" if col else ""
            label = f"{table}{col_str}.{test}"

            if verdict is None:
                print(f"  WARN: {label} flipped to enforced:true but not found in dq-latest.json checks.")
                continue
            if verdict == "SKIP":
                print(f"  WARN: {label} has verdict=SKIP (dry-run only, inconclusive) -- flip not blocked but unverified.")
                continue
            if verdict != "PASS":
                failed.append(
                    f"Graduation guard: {label} cannot be graduated to enforced:true "
                    f"(current verdict: {verdict}). Run data_quality_runner and verify PASS first."
                )


def validate_dq_manifest_gate(failed: list[str]) -> None:
    """For every enforced: true test in ops.yaml, assert the decisions manifest is in an allowed state.

    Allowed states: READY_NOW, write_fix_deployed, GRADUATED, NEEDS_TEMPORAL_GATE.
    Any other state (including NEEDS_WRITE_FIX, NEEDS_DATA_CORRECTION, missing, or unknown)
    is rejected so that unrecognised states fail closed rather than silently passing.
    """
    import yaml as _yaml  # noqa: PLC0415

    print("\n=== DQ manifest gate ===")

    ops_yaml_path = ROOT / "config" / "agent" / "data_quality" / "ops.yaml"
    decisions_dir = ROOT / "config" / "agent" / "data_quality" / "decisions"

    if not ops_yaml_path.exists():
        print("  ops.yaml not found -- skipping.")
        return

    try:
        ops_data = _yaml.safe_load(ops_yaml_path.read_text(encoding="utf-8")) or {}
    except (OSError, _yaml.YAMLError) as exc:
        print(f"  WARN: could not parse ops.yaml: {exc}")
        return

    manifests: dict[str, dict] = {}
    if decisions_dir.exists():
        for mf in decisions_dir.glob("*.yaml"):
            try:
                manifest = _yaml.safe_load(mf.read_text(encoding="utf-8")) or {}
                table = manifest.get("table")
                if table:
                    manifests[table] = manifest
            except (OSError, _yaml.YAMLError):
                pass

    _ALLOWED_STATES = {"READY_NOW", "write_fix_deployed", "GRADUATED", "NEEDS_TEMPORAL_GATE"}
    errors: list[str] = []

    for table_name, table_def in ops_data.get("tables", {}).items():
        manifest_fields = manifests.get(table_name, {}).get("fields", {})
        for col_name, col_def in table_def.get("columns", {}).items():
            if not isinstance(col_def, dict):
                continue
            for test_entry in col_def.get("tests", []):
                if not isinstance(test_entry, dict):
                    continue
                for test_name, params in test_entry.items():
                    if not isinstance(params, dict) or not params.get("enforced"):
                        continue
                    state = manifest_fields.get(col_name, {}).get("enforcement_ready", "")
                    if state not in _ALLOWED_STATES:
                        errors.append(
                            f"{table_name}.{col_name} ({test_name}) is enforced: true "
                            f"but manifest shows enforcement_ready: {state!r} "
                            f"(allowed: {sorted(_ALLOWED_STATES)}). "
                            f"Update manifest before promoting enforcement."
                        )

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        failed.append("DQ manifest gate")
    else:
        print("  DQ manifest gate: all enforced checks have allowed enforcement_ready states.")


def check_claude_md_pointer_invariant(path: str = "CLAUDE.md") -> bool:
    """Return True iff the file at path contains exactly '@AGENTS.md\n'."""
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    try:
        content = p.read_text(encoding="utf-8")
    except OSError:
        return False
    return content == "@AGENTS.md\n"


def validate_claude_md_pointer_invariant(failed: list[str]) -> None:
    """Fail if root CLAUDE.md is anything other than exactly '@AGENTS.md\n'."""
    print("\n=== CLAUDE.md pointer invariant ===")
    if not check_claude_md_pointer_invariant():
        print("  FAIL: CLAUDE.md must contain exactly '@AGENTS.md\\n'. Content diverges from expected pointer.")
        failed.append("CLAUDE.md pointer invariant")
    else:
        print("  PASS: CLAUDE.md is exactly '@AGENTS.md\\n'.")


def validate_scheduled_agent_logs(failed: list[str]) -> None:
    """Validate log files from scheduled-agent branches.

    Skips when non-log files are changed (feature branch, not a scheduled-agent run).
    Fails on canonical-state write violations or invalid JSONL schema.
    """
    print("\n=== Scheduled agent log validation ===")

    result = run(
        ["git", "diff", "--name-only", "main...HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    changed = [f for f in result.stdout.strip().splitlines() if f]

    if not changed:
        print("No files changed relative to main -- skipping.")
        return

    # Only engage when all changed files are under the logs/ hierarchy.
    # Source-file changes indicate a feature branch, not a scheduled-agent run.
    if not all(f.startswith("logs/") for f in changed):
        print("Not a scheduled-agent branch (non-log files changed) -- skipping.")
        return

    canonical_files = {"logs/.recommendations-log.jsonl", "logs/.decisions-index.jsonl"}
    violations = [f for f in changed if f in canonical_files]
    if violations:
        print(f"Canonical-state write violation -- scheduled agents must not modify: {violations}")
        failed.append("Scheduled agent log validation")
        return

    ts_pattern = re.compile(r"^\d{8}T\d{6}Z\.jsonl$")
    errors: list[str] = []

    for filepath in changed:
        if not filepath.startswith("logs/agents/"):
            continue
        filename = Path(filepath).name
        if not ts_pattern.match(filename):
            errors.append(f"{filepath}: filename does not match pattern YYYYMMDDTHHMMSSZ.jsonl")
            continue
        full_path = ROOT / filepath
        if not full_path.exists():
            continue
        for lineno, line in enumerate(full_path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                errors.append(f"{filepath}:{lineno}: invalid JSON")
                break
            if "type" not in row or "timestamp" not in row:
                errors.append(f"{filepath}:{lineno}: missing required fields 'type' and/or 'timestamp'")
                break

    if errors:
        print("Scheduled agent log errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Scheduled agent log validation")
    else:
        agent_files = [f for f in changed if f.startswith("logs/agents/")]
        print(f"Scheduled agent log validation passed ({len(agent_files)} file(s) checked).")


def _ensure_root_on_path() -> bool:
    """Inject ROOT into sys.path if absent; return True if injection was performed."""
    root_str = str(ROOT)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
        return True
    return False


def validate_ci_rca_trigger(failed: list[str]) -> None:
    """Assert ci-rca.yml fires only on the authoritative main-branch CI gate.

    Wires the ci-rca-filter guard from scripts/verify_ci_workflow.py into the
    presubmit tier per Decision 60: a check is only a gate if it runs via validate.py.
    """
    print("\n=== ci-rca trigger gate ===")
    root_str = str(ROOT)
    injected = _ensure_root_on_path()
    try:
        from scripts.verify_ci_workflow import _check_ci_rca_filter

        _check_ci_rca_filter()
        print("  PASS: ci-rca trigger gate (main-branch gate + FILED: marker contract present)")
    except Exception as exc:
        print(f"  FAIL: {exc}")
        failed.append("ci-rca trigger gate")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


def validate_ci_workflow_guards(failed: list[str]) -> None:
    """Assert CI workflow structural invariants are met (Decision 60, CD.21).

    Wires _check_jobs_and_flags, _check_fetch_depth, _check_concurrency, and
    _check_canary from scripts/verify_ci_workflow.py into the presubmit tier.
    Each guard failure appends a distinct label; a non-AssertionError exception
    records a failure rather than crashing presubmit (rec-2027 pattern).
    """
    print("\n=== ci-workflow guards gate ===")
    root_str = str(ROOT)
    injected = _ensure_root_on_path()
    try:
        from scripts.verify_ci_workflow import (
            _check_canary,
            _check_concurrency,
            _check_fetch_depth,
            _check_jobs_and_flags,
        )

        guards = [
            ("jobs-and-flags", _check_jobs_and_flags),
            ("fetch-depth", _check_fetch_depth),
            ("concurrency", _check_concurrency),
            ("canary", _check_canary),
        ]
        for label, fn in guards:
            try:
                fn()
                print(f"  PASS: {label}")
            except Exception as exc:
                print(f"  FAIL: {label}: {exc}")
                failed.append(f"ci-workflow guard: {label}")
    except Exception as exc:
        # Import or setup failure (e.g. verify_ci_workflow unimportable) must
        # record a gate failure, not crash presubmit (rec-2027).
        print(f"  FAIL: ci-workflow guards gate (import/setup): {exc}")
        failed.append("ci-workflow guards gate")
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)


_UNIT_TEST_HERMETICITY_FLAGS: tuple[str, ...] = ("--disable-socket", "--randomly-seed=last")


def _build_unit_test_cmd() -> list[str]:
    """Return the pytest command for the 'Unit tests + coverage' step."""
    return [
        PYTHON,
        "-m",
        "pytest",
        "tests/",
        "-v",
        "-m",
        "not integration",
        "--cov=src",
        "--cov-report=term-missing",
        "--disable-socket",
        "--randomly-seed=last",
    ]


def validate_hermeticity_flags(failed: list[str], _cmd: list[str] | None = None) -> None:
    """Fail CI if mandatory hermeticity flags are absent from the unit-test pytest command.

    Guards against accidental removal of --disable-socket or --randomly-seed=last from the
    test invocation. Accepts an optional _cmd override for unit-testing this function itself.
    """
    cmd = _cmd if _cmd is not None else _build_unit_test_cmd()
    for flag in _UNIT_TEST_HERMETICITY_FLAGS:
        if flag not in cmd:
            failed.append(f"hermeticity-flags: {flag!r} missing from pytest invocation")


def run_python_checks(failed: list[str]) -> None:
    run_lint_checks(failed)
    validate_subprocess_encoding(failed)
    validate_sys_executable(failed)
    validate_copilot_multipliers(failed)
    validate_cli_tools_in_prompts(failed)
    validate_imports(failed)
    validate_recommendations_schema(failed)
    validate_outbox_staleness(failed)
    validate_executor_boundary(failed)
    validate_rec_write_paths(failed)
    validate_decisions_local_writes(failed)
    validate_warehouse_write_sources(failed)
    validate_invariants(failed)
    validate_ci_rca_trigger(failed)
    validate_ci_workflow_guards(failed)
    validate_sloc_limits(failed)
    check_source_registry(failed)
    validate_platform_roadmap(failed)
    validate_lambda_manifests(failed)
    validate_lambda_manifest_coverage(failed)
    validate_lambda_bundle_completeness(failed)
    validate_lambda_deploy_gating(failed)
    validate_product_roadmap(failed)
    validate_pydantic_yaml_drift(failed)
    _check_graduation_guard(failed)
    validate_dq_manifest_gate(failed)
    validate_test_coverage(failed)
    validate_no_underscore_instructions(failed)
    validate_claude_md_pointer_invariant(failed)
    validate_environment_taxonomy(failed)
    validate_complexity(failed)
    validate_scheduled_agent_logs(failed)
    validate_hermeticity_flags(failed)
    invoke_step("Unit tests + coverage", _build_unit_test_cmd(), failed)

    print("\n=== mypy (informational) ===")
    result = run([PYTHON, "-m", "mypy", "src/"], cwd=ROOT)
    if result.returncode != 0:
        print("mypy: type errors found (informational - not blocking). Fix progressively.")


# Both terraform roots are standalone (own provider + required_providers). terraform/ is
# retained per CD.21 but no longer applied; terraform/personal/ is the applied root.
# terraform/github/ is the isolated GitHub-settings module (human-gated local apply only -- T2.12).
_TERRAFORM_ROOTS = ("terraform", "terraform/personal", "terraform/github")


def run_terraform_creds_free(failed: list[str], roots: tuple[str, ...] = _TERRAFORM_ROOTS) -> None:
    """Credential-free terraform gate: init -backend=false + validate + fmt -check per root.

    -backend=false skips backend initialisation (no AWS credentials required); validate and
    fmt are offline operations. Tool-gated on terraform presence with a visible SKIP so the
    check degrades cleanly where terraform is absent (the terraform-validate CI job enforces it).
    This is the single source of truth for terraform validation -- both the full presubmit tier
    and `--terraform-only` (CI) call it; there is no parallel/duplicate validation.
    """
    if not shutil.which("terraform"):
        print("\n=== Terraform checks skipped (terraform not found in PATH) ===")
        print("Terraform validate/fmt run in the terraform-validate CI job.")
        return
    for root in roots:
        chdir = f"-chdir={root}"
        invoke_step(
            f"Terraform init [{root}]", ["terraform", chdir, "init", "-backend=false", "-input=false", "-no-color"], failed
        )
        invoke_step(f"Terraform validate [{root}]", ["terraform", chdir, "validate", "-no-color"], failed)
        invoke_step(f"Terraform fmt check [{root}]", ["terraform", chdir, "fmt", "-check", "-no-color"], failed)


def validate_environment_taxonomy(failed: list[str]) -> None:
    """Enforce the two-axis vocabulary reservation (docs/contracts/environment-taxonomy.md).

    On changed docs, flag conflation of the PLATFORM environment axis (sandbox/SIT/PROD) with the
    PRODUCT phase axis (research..live_full): a product-phase token used as an "environment", or a
    platform-tier token used as a "phase". Compound tokens (research_sandbox, production_ensemble)
    are safe via word boundaries. The canonical contract, decisions and roadmaps are allowlisted --
    they define the vocabulary and legitimately span both axes; workflow and test files are skipped.
    """
    print("\n=== Environment/phase taxonomy lint ===")
    allowlist_files = {
        "docs/contracts/environment-taxonomy.md",
        "docs/DECISIONS.md",
        "docs/ROADMAP-PRODUCT.yaml",
        "docs/ROADMAP-PLATFORM.yaml",
        "docs/INTENT-ci-cd-architecture.md",
    }
    product_phases = ("research", "backtest_canonical", "paper", "live_small", "live_full")
    platform_tiers = ("sandbox", "sit", "prod", "production", "staging")
    phase_as_env = re.compile(r"\b(" + "|".join(product_phases) + r")[ \t]+environment\b", re.IGNORECASE)
    tier_as_phase = re.compile(r"\b(" + "|".join(platform_tiers) + r")[ \t]+phase\b", re.IGNORECASE)
    errors: list[str] = []
    for rel in get_changed_files():
        if not rel.endswith((".md", ".yaml", ".yml")):
            continue
        if rel in allowlist_files or rel.startswith(".github/") or rel.startswith("tests/"):
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if phase_as_env.search(line):
                errors.append(f"{rel}:{lineno}: product phase used as an 'environment' (product states are phases)")
            if tier_as_phase.search(line):
                errors.append(f"{rel}:{lineno}: platform tier used as a 'phase' (platform tiers are environments)")
    if errors:
        print("Environment/phase taxonomy violations (see docs/contracts/environment-taxonomy.md):")
        for e in errors:
            print(f"  - {e}")
        failed.append("Environment/phase taxonomy")
    else:
        print("No environment/phase taxonomy violations in changed docs.")


def run_terraform_checks(failed: list[str]) -> None:
    """Full-presubmit terraform gate: creds-free checks on both roots, plus a creds-needing
    drift check (plan -detailed-exitcode) on the applied terraform/personal root only."""
    validate_terraform_try(failed)
    run_terraform_creds_free(failed)
    if not shutil.which("terraform"):
        return
    # Informational drift check on the APPLIED root only (terraform/ is no longer applied per
    # CD.21). Creds-needing: re-init the local backend, then plan. Never blocks -- when creds or
    # backend are unavailable the step degrades to a visible skip (Decision 60 actionable note).
    print("\n=== Terraform changes pending check (terraform/personal, informational) ===")
    init_res = run(
        ["terraform", "-chdir=terraform/personal", "init", "-input=false", "-no-color", "-reconfigure"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    if init_res.returncode != 0:
        print("Terraform plan skipped: backend/init unavailable (credentials missing) -- non-blocking.")
        return
    result = run(
        ["terraform", "-chdir=terraform/personal", "plan", "-detailed-exitcode", "-no-color", "-input=false"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=ROOT,
    )
    if result.returncode == 2:
        print("WARNING: Terraform changes pending in terraform/personal. Run `terraform apply` before merge.")
    elif result.returncode not in (0, 2):
        print("Terraform plan skipped or failed (credentials unavailable) -- non-blocking.")


def run_dependency_checks() -> None:
    print("\n=== Dependency health -- CVE scan (informational) ===")
    try:
        result = run(["pip-audit", "--strict"], cwd=ROOT)
        if result.returncode != 0:
            print("pip-audit: vulnerabilities found (see above)")
    except FileNotFoundError:
        print("pip-audit not installed. Run: pip install pip-audit")

    print("\n=== Dependency health -- outdated packages (informational) ===")
    try:
        run(["pip", "list", "--outdated"], cwd=ROOT)
    except FileNotFoundError:
        print("Could not check outdated packages.")


def validate_workflow_agent_safety(failed: list[str]) -> None:
    """Headless `claude -p` workflow steps that mask failures must assert their output.

    Guards the silent-failure class behind the ci-rca "Input must be provided ... when
    using --print" regression: a masked invocation (|| true / continue-on-error) with no
    output assertion passes as a green no-op. See scripts/check_workflow_agent_safety.py.
    """
    print("\n=== Workflow agent-safety (headless claude -p) ===")
    from scripts.check_workflow_agent_safety import check_workflow_agent_safety

    violations = check_workflow_agent_safety()
    if violations:
        print("Workflow agent-safety violations:")
        for v in violations:
            print(f"  - {v}")
        failed.append("Workflow agent-safety")
    else:
        print("All headless claude -p steps assert their output.")


def validate_prompt_files(failed: list[str]) -> None:
    print("\n=== Prompt file validation ===")
    prompts_dir = ROOT / ".github" / "prompts"
    prompt_files = list(prompts_dir.glob("*.prompt.md"))
    errors: list[str] = []

    for f in prompt_files:
        content = f.read_text(encoding="utf-8")
        name = f.name

        if not content.startswith("---"):
            errors.append(f"{name} : missing YAML frontmatter")
            continue

        fm_match = re.search(r"(?s)^---[\r\n](.*?)[\r\n]---", content)
        fm = fm_match.group(1) if fm_match else ""

        if not re.search(r"name\s*:", fm):
            errors.append(f"{name} : missing 'name' in frontmatter")
        if not re.search(r"description\s*:", fm):
            errors.append(f"{name} : missing 'description' in frontmatter")

        model_match = re.search(r"model\s*:\s*(.+)", fm)
        if model_match:
            model_value = model_match.group(1).strip().strip('"').strip("'")
            if model_value not in KNOWN_MODELS:
                errors.append(f"{name} : unrecognised model '{model_value}' -- verify against VS Code model picker")

        if "## Intent" not in content:
            errors.append(f"{name} : missing '## Intent' section")

        for ref_match in re.finditer(r"\[.*?\]\((\.\.?/[^)# \s]+)\)", content):
            ref_path = ref_match.group(1)
            resolved = (f.parent / ref_path).resolve()
            if not resolved.exists():
                errors.append(f"{name} : dead reference '{ref_path}'")

    if errors:
        print("Prompt validation errors:")
        for e in errors:
            print(f"  - {e}")
        failed.append("Prompt file validation")
    else:
        print(f"All {len(prompt_files)} prompt files passed validation.")


def validate_verification_harness(failed: list[str]) -> None:
    """Run all registered programmatic verifiers (V3 integration gates)."""
    print("\n=== Verification Harness (V3) ===")
    try:
        import asyncio
        import sys

        # Ensure repo root is in sys.path so scripts.verifiers resolves
        root_str = str(ROOT)
        injected = root_str not in sys.path
        if injected:
            sys.path.insert(0, root_str)
        try:
            from scripts.verifiers import VerifierSeverity, VerifierStatus, run_all_verifiers

            results = asyncio.run(run_all_verifiers())
        finally:
            if injected and root_str in sys.path:
                sys.path.remove(root_str)

        has_fail = False
        for res in results:
            status_str = f"[{res.status}]"
            # res.severity is an enum; we want its name for display
            print(f"  {status_str:<10} ({res.severity}) {res.name}: {res.message} ({res.duration_ms:.1f}ms)")
            if res.status == VerifierStatus.FAIL and res.severity.rank >= VerifierSeverity.HARD_GATE.rank:
                has_fail = True

        if has_fail:
            failed.append("Verification Harness")
    except Exception as exc:
        print(f"  [ERROR] Verification harness failed to run: {exc}")
        failed.append("Verification Harness")


_DQ_FRESHNESS_SECONDS = 3600  # 1 hour


def ensure_fresh_dq_results(failed: list[str]) -> None:
    """Auto-invoke data_quality_runner if logs/debug/dq-latest.json is missing or stale.

    Called during the presubmit tier so the DQ verifier sees fresh data instead
    of SKIPPING on staleness or absence.

    Decision 57: when SSO is unavailable, prints an actionable message and skips
    rather than crashing.
    """
    import time

    print("\n=== Ensure fresh DQ results ===")

    dq_file = ROOT / "logs" / "debug" / "dq-latest.json"

    if dq_file.exists():
        age_seconds = time.time() - dq_file.stat().st_mtime
        if age_seconds <= _DQ_FRESHNESS_SECONDS:
            print(f"DQ cache fresh ({age_seconds / 60:.1f}m old) -- skipping data_quality_runner.")
            return
        print(f"DQ cache stale ({age_seconds / 3600:.1f}h old) -- re-running data_quality_runner.")
    else:
        print("DQ cache missing -- running data_quality_runner.")

    try:
        import boto3

        from scripts.aws_profile import resolve_aws_profile

        profile = resolve_aws_profile(default="agent_platform")
        boto3.Session(profile_name=profile).client("sts", region_name="eu-west-2").get_caller_identity()
    except Exception:
        print(
            "AWS credentials not available -- skipping data_quality_runner auto-invoke. "
            "Ensure AWS credentials are configured to enable DQ refresh (Decision 57)."
        )
        return

    invoke_step("Data quality runner", [PYTHON, "-m", "scripts.data_quality_runner"], failed)


def run_coverage_check() -> None:
    """Print scope files not covered by any registered verifier (advisory only).

    Wave 1 of INTENT-verification-system.md: surfaces V3 verifier coverage gaps.
    Never appends to the failed list -- exit 0 unconditionally.
    """
    print("\n=== Verifier coverage report (advisory) ===")
    changed = get_changed_files()
    if not changed:
        print("No changed files detected on this branch -- coverage check has nothing to report.")
        return

    root_str = str(ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.verifiers import check_coverage as _check_coverage

        uncovered = _check_coverage(changed)
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)

    if not uncovered:
        print(f"All scope files covered by at least one verifier ({len(changed)} files checked).")
        return

    print(f"{len(uncovered)} of {len(changed)} scope files lack verifier coverage:")
    for f in uncovered:
        print(f"  - {f}")
    print("\n(Advisory only -- this does not fail the build.)")


def main() -> None:
    # Recursion guard: validate.py spawns pytest, which may collect tests that
    # import/call validate.py again.  _VALIDATE_DEPTH prevents infinite loops.
    depth = int(os.environ.get("_VALIDATE_DEPTH", "0"))
    if depth >= 1:
        print(f"[SKIP] validate.py recursion detected (depth={depth}). Exiting.")
        sys.exit(0)
    os.environ["_VALIDATE_DEPTH"] = str(depth + 1)

    parser = argparse.ArgumentParser(description="Local CI validation. Run before every commit.")
    parser.add_argument(
        "--pre",
        action="store_true",
        help="Run diff-aware lint/format/mypy/pytest + prompt validation only. Skips terraform and dependencies. "
        "Use for per-step validation during implementation. Subject to a 5-minute wall-clock budget.",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Report scope files lacking verifier coverage (advisory; exits 0 unconditionally).",
    )
    parser.add_argument(
        "--terraform-only",
        action="store_true",
        help="Run ONLY the credential-free terraform gate (init -backend=false + validate + fmt -check) "
        "for terraform/ and terraform/personal/. Used by the terraform-validate CI job; no AWS creds needed.",
    )
    parser.add_argument(
        "--ignore-budget",
        action="store_true",
        help="Skip the 5-minute fast-tier budget assertion. Emergency escape hatch only. "
        "Disallowed when CI=true. Bypass is audited via ops_data_portal.",
    )
    parser.add_argument(
        "--ignore-budget-reason",
        default=None,
        metavar="TEXT",
        help="Optional reason for bypassing the budget assertion (captured in the bypass audit rec).",
    )
    args = parser.parse_args()

    # CI guard: --ignore-budget is forbidden in CI environments
    if args.ignore_budget and os.environ.get("CI") == "true":
        print("[ERROR] --ignore-budget cannot be used in CI. The escape hatch is for local sessions only.")
        sys.exit(1)

    # Branch guard (skip in CI to allow running from CI environments)
    if os.environ.get("CI") != "true":
        result = run(["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
        if result.stdout.strip() == "main":
            print("\n[ERROR] validate.py refused to run on 'main'.")
            print("Create a feature branch first: git checkout -b agent/{slug}")
            sys.exit(1)

    failed: list[str] = []

    # --coverage: advisory verifier-coverage report, then exit 0
    if args.coverage:
        run_coverage_check()
        sys.exit(0)

    # --terraform-only: creds-free terraform gate for both roots (CI terraform-validate job)
    if args.terraform_only:
        run_terraform_creds_free(failed)
        print("\n=== Validation Summary (scope: terraform-only) ===")
        if not failed:
            print("All checks passed.")
            sys.exit(0)
        print("Failed checks:")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)

    # --pre: diff-aware lint/format/mypy/picked-pytest + prompt validation, with 5-min budget
    if args.pre:
        _t0 = time.monotonic()
        print("Pre mode: diff-aware lint/format/mypy/pytest and prompt validation.")

        changed = get_changed_files()
        diff_manifest = list(changed)

        run_lint_checks(failed, files=changed)

        # pre-commit on the changed files: diff-aware detect-secrets + denylist + hygiene gate.
        run_precommit_checks(failed, all_files=False, files=changed)

        changed_py = [f for f in changed if f.endswith(".py")]
        if changed_py:
            print("\n=== Type check (mypy -- informational) ===")
            mypy_result = run(
                [PYTHON, "-m", "mypy", "--follow-imports=silent"] + changed_py,
                cwd=ROOT,
            )
            if mypy_result.returncode != 0:
                print("mypy: type errors found in changed files (informational - not blocking). Fix progressively.")

        has_test_changes = any(re.match(r"tests/.*test_[^/]+\.py$", f) for f in changed)
        if has_test_changes:
            print("\n=== Tests (pytest --picked) ===")
            pytest_result = run(
                [PYTHON, "-m", "pytest", "--picked", "--mode=branch", "-m", "not integration", "-v"],
                cwd=ROOT,
            )
            if pytest_result.returncode not in (0, 5):  # exit 5 = no tests collected
                failed.append("Tests (pytest --picked)")

        validate_iam_runner_policy(failed)
        validate_copilot_multipliers(failed)
        validate_prompt_files(failed)
        validate_cli_tools_in_prompts(failed)
        validate_workflow_agent_safety(failed)
        # Product-roadmap check runs in --pre: pure Python, sub-100ms, active editing surface
        validate_product_roadmap(failed)
        # CC-gate in --pre: O(lines) AST check, per rec-859 RCA earliest_viable_gate="pre" (docs/INTENT-ci-rca-methodology.md)
        validate_cc_limits(failed)
        # SLOC-gate in --pre: mirrors validate_cc_limits -- both are O(lines) file scans; SLOC breach
        # missed pre-merge in PR #106 because it ran in full-tier only (rec-2106 RCA).
        validate_sloc_limits(failed)

        elapsed = time.monotonic() - _t0

        if args.ignore_budget:
            _file_budget_bypass_rec(elapsed, diff_manifest, args.ignore_budget_reason)
            print(f"\nBudget assertion skipped (--ignore-budget). Elapsed: {elapsed / 60:.1f} min.")
        elif elapsed > _FAST_TIER_BUDGET_SECONDS:
            _file_budget_breach_rec(elapsed, diff_manifest, None)
            print(
                f"\nERROR: Fast tier exceeded budget (5 min). Elapsed: {elapsed / 60:.1f} min.\n"
                "This tier has grown beyond its design contract. Either:\n"
                "  1. Move the slow check to the full tier, or\n"
                "  2. Optimise the check, or\n"
                "  3. Open a planning session to revise this budget (requires Decision Record)."
            )
            sys.exit(1)

        print("\n=== Validation Summary (scope: pre) ===")
        if not failed:
            print("All checks passed.")
            sys.exit(0)
        else:
            print("Failed checks:")
            for f in failed:
                print(f"  - {f}")
            print("\nFix all failures before committing.")
            sys.exit(1)

    scope = "all"

    if scope in ("python", "all"):
        run_python_checks(failed)

    if scope in ("terraform", "all"):
        run_terraform_checks(failed)
        validate_iam_runner_policy(failed)

    if scope in ("python", "all"):
        run_dependency_checks()
        validate_requirements(failed)

    if scope in ("prompts", "all"):
        validate_prompt_files(failed)
        validate_cli_tools_in_prompts(failed)
        validate_workflow_agent_safety(failed)
        validate_prompt_compliance(failed)

    ensure_fresh_dq_results(failed)
    validate_verification_harness(failed)

    # Full tier: run the entire pre-commit suite across all files (detect-secrets,
    # shape denylist, file hygiene). main-validate's authoritative full-tree gate.
    run_precommit_checks(failed, all_files=True)

    print(f"\n=== Validation Summary (scope: {scope}) ===")
    if not failed:
        print("All checks passed.")
        sys.exit(0)
    else:
        print("Failed checks:")
        for f in failed:
            print(f"  - {f}")
        print("\nFix all failures before committing.")
        sys.exit(1)


if __name__ == "__main__":
    main()
