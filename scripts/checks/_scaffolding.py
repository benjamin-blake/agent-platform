"""CLI scaffolding steps that are not registered checks (Decision 104).

These implement the non-check scaffolding steps referenced by
scripts/checks/registry.py's pre_sequence()/full_sequence() (lint, precommit,
terraform gates, dependency health, DQ freshness, verifier-coverage report,
budget-breach/bypass rec filing, and the unit-test command builder). They stay
outside the check registry (no @register decorator, not a `validate_*(failed)`
uniform check signature in every case) but outside scripts/validate.py too, so
the CLI entrypoint stays thin. scripts/validate.py imports and re-exports all
of these for back-compat (`patch("validate.<name>")` / `from scripts.validate
import <name>` keep resolving).
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import time

from scripts.checks import _common
from scripts.checks.iam_tf.validate_terraform_try import validate_terraform_try

# Transient terraform registry.terraform.io 5xx signatures; used by _terraform_init_with_retry and
# by the bounded retry loop in .github/workflows/terraform-apply-sandbox.yml (parity required).
_TRANSIENT_INIT_SIGNATURES: tuple[str, ...] = ("502", "Bad Gateway", "could not query provider registry", "failed after ")

# Transient Claude API error signatures; parity with _is_transient() in scripts/ci/claude_p_retry.sh.
# Distinct from _TRANSIENT_INIT_SIGNATURES (terraform registry 5xx). Decision 73, Decision 92.
_TRANSIENT_CLAUDE_SIGNATURES: tuple[str, ...] = ("500", "502", "503", "API Error: 5", "Internal server error", "overloaded")

# Both terraform roots are standalone (own provider + required_providers). terraform/ is
# retained per CD.21 but no longer applied; terraform/personal/ is the applied root.
# terraform/github/ is the isolated GitHub-settings module (human-gated local apply only -- T2.12).
# terraform/bootstrap/ is the CI/CD bootstrap root (admin-only, NEVER auto-apply -- CD.35 Wave 4 / T2.23).
_TERRAFORM_ROOTS = ("terraform", "terraform/personal", "terraform/github", "terraform/bootstrap")

_DQ_FRESHNESS_SECONDS = 3600  # 1 hour


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
    cmd = [_common.PYTHON, "-m", "pre_commit", "run", "--show-diff-on-failure", "--color", "never"]
    if all_files:
        cmd.append("--all-files")
    else:
        target = files if files is not None else _common.get_changed_files()
        if not target:
            print(f"\n=== {name} ===\nNo changed files vs origin/main; skipping.")
            return
        cmd += ["--files", *target]
    print(f"\n=== {name} ===")
    env = {**os.environ, "SKIP": "no-commit-to-branch"}
    result = _common.run(cmd, cwd=_common.ROOT, env=env)
    if result.returncode != 0:
        failed.append(name)


def run_lint_checks(failed: list[str], files: list[str] | None = None) -> None:
    if files is not None and not files:
        return
    targets: list[str] = [f for f in files if f.endswith(".py")] if files is not None else ["src/", "tests/"]
    if not targets:
        return
    _common.invoke_step("Lint (ruff check)", [_common.PYTHON, "-m", "ruff", "check"] + targets, failed)
    _common.invoke_step("Format check (ruff format)", [_common.PYTHON, "-m", "ruff", "format", "--check"] + targets, failed)


def _file_budget_breach_rec(elapsed_s: float, diff_manifest: list[str], dominant_phase: str | None) -> None:
    try:
        from scripts.ops_data_portal import file_rec  # noqa: PLC0415

        branch_r = _common.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT
        )
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

        print(
            f"WARNING: budget breach rec filing failed (NOT filed; no outbox -- re-file manually): {traceback.format_exc()}",
            file=sys.stderr,
        )


def _file_budget_bypass_rec(elapsed_s: float | None, diff_manifest: list[str], reason: str | None) -> None:
    try:
        from scripts.ops_data_portal import file_rec  # noqa: PLC0415

        branch_r = _common.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT
        )
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

        print(
            f"WARNING: budget bypass rec filing failed (NOT filed; no outbox -- re-file manually): {traceback.format_exc()}",
            file=sys.stderr,
        )


def _build_unit_test_cmd() -> list[str]:
    """Return the pytest command for the 'Unit tests + coverage' step."""
    return [
        _common.PYTHON,
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


def _terraform_init_with_retry(label: str, cmd: list[str], failed: list[str]) -> bool:
    """Run a terraform init command with bounded retry on transient registry 5xx.

    Returns True if init succeeded (never appends to failed), False if permanently failed
    (label is appended to failed). Matches invoke_step output format for the step header.
    Transient signatures: _TRANSIENT_INIT_SIGNATURES (parity with the workflow retry loop).
    """
    print(f"\n=== {label} ===")
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        result = _common.run(cmd, capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT)
        if result.returncode == 0:
            print(result.stdout, end="")
            return True
        combined = result.stdout + result.stderr
        is_transient = any(sig in combined for sig in _TRANSIENT_INIT_SIGNATURES)
        if is_transient and attempt < max_attempts:
            delay = 2**attempt
            print(f"transient registry error (attempt {attempt}/{max_attempts}); retrying in {delay}s...")
            print(combined, end="")
            time.sleep(delay)
            continue
        print(combined, end="")
        failed.append(label)
        return False
    return False  # pragma: no cover -- unreachable: loop body always returns on the final attempt


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
        if not _terraform_init_with_retry(
            f"Terraform init [{root}]",
            ["terraform", chdir, "init", "-backend=false", "-input=false", "-no-color"],
            failed,
        ):
            continue
        _common.invoke_step(f"Terraform validate [{root}]", ["terraform", chdir, "validate", "-no-color"], failed)
        _common.invoke_step(f"Terraform fmt check [{root}]", ["terraform", chdir, "fmt", "-check", "-no-color"], failed)


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
    init_res = _common.run(
        ["terraform", "-chdir=terraform/personal", "init", "-input=false", "-no-color", "-reconfigure"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    if init_res.returncode != 0:
        print("Terraform plan skipped: backend/init unavailable (credentials missing) -- non-blocking.")
        return
    result = _common.run(
        ["terraform", "-chdir=terraform/personal", "plan", "-detailed-exitcode", "-no-color", "-input=false"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    if result.returncode == 2:
        print("WARNING: Terraform changes pending in terraform/personal. Run `terraform apply` before merge.")
    elif result.returncode not in (0, 2):
        print("Terraform plan skipped or failed (credentials unavailable) -- non-blocking.")


def run_dependency_checks() -> None:
    print("\n=== Dependency health -- CVE scan (informational) ===")
    try:
        result = _common.run(["pip-audit", "--strict"], cwd=_common.ROOT)
        if result.returncode != 0:
            print("pip-audit: vulnerabilities found (see above)")
    except FileNotFoundError:
        print("pip-audit not installed. Run: pip install pip-audit")

    print("\n=== Dependency health -- outdated packages (informational) ===")
    try:
        _common.run(["pip", "list", "--outdated"], cwd=_common.ROOT)
    except FileNotFoundError:
        print("Could not check outdated packages.")


def ensure_fresh_dq_results(failed: list[str]) -> None:
    """Auto-invoke data_quality_runner if logs/debug/dq-latest.json is missing or stale.

    Called during the presubmit tier so the DQ verifier sees fresh data instead
    of SKIPPING on staleness or absence.

    Decision 57: when SSO is unavailable, prints an actionable message and skips
    rather than crashing.
    """
    print("\n=== Ensure fresh DQ results ===")

    dq_file = _common.ROOT / "logs" / "debug" / "dq-latest.json"

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

    _common.invoke_step("Data quality runner", [_common.PYTHON, "-m", "scripts.data_quality_runner"], failed)


def run_coverage_check() -> None:
    """Print scope files not covered by any registered verifier (advisory only).

    Wave 1 of INTENT-verification-system.md: surfaces V3 verifier coverage gaps.
    Never appends to the failed list -- exit 0 unconditionally.
    """
    print("\n=== Verifier coverage report (advisory) ===")
    changed = _common.get_changed_files()
    if not changed:
        print("No changed files detected on this branch -- coverage check has nothing to report.")
        return

    root_str = str(_common.ROOT)
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
