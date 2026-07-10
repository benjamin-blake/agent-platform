# complexity-waiver: decision-43
"""Review, verifier, and scope gates for the executor's finalize() flow.

Extracted from scripts/executor/postflight.py (Decision 102/104 SLOC decomposition). The
scripts.executor.postflight facade re-exports these symbols and remains the sole import path
for callers and tests; bodies reach shared collaborators through that facade at call time.
"""

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _commits_ahead_of_main() -> int:
    """Return the number of commits on HEAD not on main (local).

    Returns 0 on any git error so uncertainty never causes phases to be skipped.
    """
    import scripts.executor.postflight as _pf

    try:
        result = _pf.subprocess.run(
            ["git", "rev-list", "--count", "main..HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        if result.returncode == 0:
            return int(result.stdout.strip() or "0")
    except (_pf.subprocess.CalledProcessError, _pf.subprocess.TimeoutExpired, ValueError, OSError):
        pass
    return 0


def _scope_drift_check(plan_steps: list[dict]) -> list[str]:
    """Compare git diff against planned files and return unplanned file paths.

    Runs ``git diff origin/main --name-only`` and checks whether every changed
    file appears in the plan's step list.  Files under ``logs/`` and
    ``__pycache__/`` are always excluded (they are expected side-effects).

    Returns:
        List of file paths that are in the diff but not in any plan step.
        Empty list means no drift.
    """
    import scripts.executor.postflight as _pf

    planned_files = {s.get("file", "") for s in plan_steps if s.get("file")}

    try:
        result = _pf.subprocess.run(
            ["git", "diff", "origin/main", "--name-only"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("[SCOPE] git diff failed (exit %d) — skipping drift check", result.returncode)
            return []
    except (_pf.subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("[SCOPE] git diff unavailable — skipping drift check")
        return []

    changed = [p for p in result.stdout.splitlines() if p.strip()]
    _EXCLUDED_PREFIXES = (
        "logs/",
        "__pycache__/",
        ".venv/",
        "build/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".mypy_cache/",
    )
    _EXCLUDED_NAMES = {"requirements.txt", "scripts/execute_recommendation.py"}
    _EXCLUDED_EXTENSIONS = (".jsonl",)
    unplanned = [
        p
        for p in changed
        if not any(p.startswith(prefix) for prefix in _EXCLUDED_PREFIXES)
        and p not in planned_files
        and p not in _EXCLUDED_NAMES
        and not any(p.endswith(ext) for ext in _EXCLUDED_EXTENSIONS)
    ]
    if unplanned:
        _pf.emit_process_event(
            tier="decision",
            category="scope_drift_detected",
            severity="warning",
            description=f"{len(unplanned)} unplanned file(s): {', '.join(unplanned[:5])}",
        )
    return unplanned


# Resolve review model via registry; fall back to COPILOT_MODEL_REVIEW env var.
# model_registry.resolve_model() checks COPILOT_MODEL_REVIEW internally (env override).
# MODEL_REVIEW is deprecated -- use _code_review_gate(effort=...) for per-effort routing.


def _code_review_gate(
    rec: dict,
    plan: "ExecutionPlan",  # noqa: F821 -- forward ref; real type lives behind _pf to avoid a module cycle
    changed_files: list[str],
    effort: str = "",
) -> tuple[bool, float, list[str]]:
    """Run a focused automated code review via the Copilot CLI.

    Returns:
        Tuple of (passed, blocking_findings) where:
        - passed is True if no CRITICAL or HIGH findings were found
        - blocking_findings is a list of finding strings
    """
    import scripts.executor.postflight as _pf

    rec_id = rec.get("id", "unknown")

    review_model = _pf.model_registry.resolve_model("review", effort or "M")

    per_file_budget = max(2000, 40000 // max(len(changed_files), 1))
    file_snippets: list[str] = []
    for fpath in changed_files:
        p = Path(fpath)
        if not p.exists():
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
            if len(content) > per_file_budget:
                omitted = content[per_file_budget:].count("\n")
                content = content[:per_file_budget] + f"\n# ... ({omitted} lines omitted)\n"
            file_snippets.append(f"### {fpath}\n```\n{content}\n```")
        except OSError:
            continue

    files_block = "\n\n".join(file_snippets) if file_snippets else "(no readable changed files)"

    try:
        template, _ = _pf.load_prompt("code-review")
    except FileNotFoundError:
        logger.warning("[REVIEW] code-review.prompt.md not found — skipping gate")
        return True, 0.0, []

    prompt = template.format(
        rec_id=rec_id,
        title=rec.get("title", "(no title)"),
        acceptance=rec.get("acceptance", "(no acceptance criteria)"),
        plan_steps=plan.plan_text[:3000],
        changed_files="\n".join(changed_files),
        files_block=files_block,
    )

    logger.info("[REVIEW] Running focused code review (%d files)...", len(changed_files))
    context_path = _pf.build_context_path("review", rec_id)
    try:
        result = _pf.llm_call(
            prompt,
            model=review_model if review_model else None,
            timeout=300,
            context_file_path=context_path,
            inline_instruction="Review the code changes and report findings per the attached context.",
            check=False,
            purpose="code_review",
        )
    except _pf.subprocess.TimeoutExpired:
        logger.warning("[REVIEW] Code review timed out (300s) -- treating as passed")
        return True, 0.0, []

    cost = result.cost_usd
    if result.exit_code != 0 or not result.content.strip():
        logger.warning("[REVIEW] Code review call failed or returned empty — treating as passed")
        return True, cost, []

    output = result.content
    blocking: list[str] = []
    gate_passed = False
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^\s*(?:\*\*)?(?:CRITICAL|HIGH)(?:\*\*)?\s*:\s", stripped):
            cleaned = stripped.strip(" -#*")
            if cleaned and not cleaned.isupper():
                blocking.append(cleaned)
        if stripped.startswith("GATE: PASSED"):
            gate_passed = True
        if stripped.startswith("GATE: FAILED"):
            gate_passed = False

    if blocking:
        logger.error("[REVIEW] %d blocking finding(s) found:", len(blocking))
        for f in blocking:
            logger.error("[REVIEW]   %s", f)
    else:
        logger.info("[REVIEW] No CRITICAL or HIGH findings — gate passed")
        _pf.emit_process_event(
            tier="decision",
            category="code_review_pass",
            severity="info",
            description="Code review passed",
        )

    return gate_passed and not blocking, cost, blocking


def _handle_failure(
    rec_id: str,
    rec: dict,
    failure_step: Optional[int],
    failure_reason: str,
    steps_completed: int,
    total_steps: int,
) -> None:
    """Push partial branch and create a draft PR on execution failure.

    Best-effort: logs warnings on push/PR errors but does not raise.
    """
    import scripts.executor.postflight as _pf

    try:
        branch_result = _pf.subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        branch = branch_result.stdout.strip() or f"agent/{rec_id}"
    except Exception:
        branch = f"agent/{rec_id}"

    title = rec.get("title", rec_id)
    pr_title = f"[FAILED] {rec_id}: {title}"
    pr_body = (
        f"## Automated Execution Failed\n\n"
        f"**Recommendation**: {rec_id}\n"
        f"**Failure step**: {failure_step if failure_step is not None else 'post-impl'}\n"
        f"**Reason**: {failure_reason[:500]}\n"
        f"**Steps completed**: {steps_completed}/{total_steps}\n\n"
        f"This draft PR preserves partial work for manual review or retry."
    )

    try:
        _pf.subprocess.run(
            ["git", "push", "--set-upstream", "origin", branch],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        logger.info("[FAILURE] Pushed partial branch %s", branch)
    except _pf.subprocess.CalledProcessError as e:
        logger.warning("[FAILURE] Push failed (non-critical): %s", (e.stderr or str(e))[:200])
        return

    try:
        _pf.subprocess.run(
            ["gh", "pr", "create", "--draft", "--head", branch, "--title", pr_title, "--body", pr_body],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        logger.info("[FAILURE] Draft PR created: %s", pr_title)
    except _pf.subprocess.CalledProcessError as e:
        logger.warning("[FAILURE] Draft PR creation failed (non-critical): %s", (e.stderr or str(e))[:200])


def _parse_scope_files(plan_text: str) -> list[str]:
    """Extract file paths from a ## Scope markdown table."""
    import re

    match = re.search(r"##\s+Scope\s*\n(.*?)(?=\n##|\Z)", plan_text, re.DOTALL)
    if not match:
        return []
    files: list[str] = []
    for line in match.group(1).split("\n"):
        if line.strip().startswith("|") and "---" not in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3 and parts[1] and parts[1].lower() != "file":
                files.append(parts[1])
    return files


def _run_verifiers_gate(rec_id: str) -> bool:
    """Run all registered programmatic verifiers.

    Returns:
        False (blocking) if a failing HARD_GATE verifier's covers intersects the
        plan's scope. Falls back to V3-only blocking when scope cannot be loaded.
        True otherwise.
    """
    import scripts.executor.postflight as _pf

    logger.info("[VERIFY] Running programmatic verifier harness...")
    try:
        import asyncio
        import re

        from scripts.verifiers import VerifierSeverity, VerifierStatus, run_all_verifiers
        from scripts.verifiers.harness import scope_intersects_covers

        # Load scope files for coverage-based predicate; V3 flag retained as fallback
        scope_files: list[str] = []
        is_v3 = False
        try:
            plan = _pf.ExecutionPlan.load(rec_id)
            if plan:
                plan_text = getattr(plan, "plan_text", "")
                if isinstance(plan_text, str) and plan_text:
                    scope_files = _parse_scope_files(plan_text)
                    tier_match = re.search(r"##\s+Verification\s+Tier\s*\n\s*(\w+)", plan_text, re.IGNORECASE)
                    if tier_match:
                        is_v3 = tier_match.group(1).strip() == "V3"
                if not is_v3:
                    is_v3 = getattr(plan, "verification_tier", "") == "V3"
        except Exception as e:
            logger.warning("[VERIFY] Could not load plan scope for coverage predicate: %s", e)

        results = asyncio.run(run_all_verifiers())
        has_blocking_fail = False
        for res in results:
            status_str = f"[{res.status}]"
            logger.info("[VERIFY]   %-10s %s: %s (severity=%s)", status_str, res.name, res.message, res.severity)

            if res.status == VerifierStatus.FAIL and res.severity == VerifierSeverity.HARD_GATE:
                if scope_files:
                    blocking = scope_intersects_covers(scope_files, res.covers)
                else:
                    blocking = is_v3
                if blocking:
                    has_blocking_fail = True
                else:
                    logger.info(
                        "[VERIFY] Non-blocking: %s covers %s (no scope intersection or non-V3 fallback)",
                        res.name,
                        res.covers,
                    )
            elif res.status == VerifierStatus.FAIL:
                logger.info("[VERIFY] Advisory failure (non-blocking)")

        if has_blocking_fail:
            logger.error("[VERIFY] Hard gate failure: one or more verifiers blocked execution.")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("[VERIFY] Verifier harness threw unexpectedly: %s", exc)
        _pf.emit_process_event("verification_gate_error", {"error": str(exc)})
        return False
