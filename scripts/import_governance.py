#!/usr/bin/env python3
"""Import governance checks for Decision 80 / T3.11.

Three checks, each callable as a function or via __main__ CLI:
  run_import_contracts()          -- run import-linter against .importlinter; non-zero exit on violation
  check_lockfile_sync()           -- verify requirements.lock pins every top-level requirements.txt package
  evaluate_bazel_revisit_trigger() -- evaluate Decision 80 cl.4 predicate; advisory only, never auto-acts

CLI flags (mutually exclusive):
  --check-contracts   runs run_import_contracts();  exit 0 on pass, 1 on violation
  --check-lockfile    runs check_lockfile_sync();   exit 0 on pass, 1 on drift
  --revisit-trigger   runs evaluate_bazel_revisit_trigger(); exit 0 always (advisory, Decision 55)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
_REQUIREMENTS_TXT = ROOT / "requirements.txt"
_REQUIREMENTS_LOCK = ROOT / "requirements.lock"


def run_import_contracts() -> tuple[bool, str]:
    """Shell out to lint-imports and return (passed, combined_output).

    Uses the lint-imports entry point installed alongside this interpreter
    so the correct venv binary is always selected.
    """
    lint_imports_bin = Path(sys.executable).parent / "lint-imports"
    cmd: list[str] = [str(lint_imports_bin)] if lint_imports_bin.exists() else ["lint-imports"]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=ROOT,
    )
    output = result.stdout + result.stderr
    return result.returncode == 0, output


def check_lockfile_sync() -> tuple[bool, str]:
    """Verify requirements.lock pins every top-level package declared in requirements.txt.

    "Top-level" is every non-comment, non-empty, non-option line; version
    constraints and extras are stripped to recover the bare package name.

    Returns (in_sync, message). Source-identity of requirements.txt is recorded
    in the message so callers can surface it in audit trails.
    """
    if not _REQUIREMENTS_TXT.exists():
        return False, f"requirements.txt not found at {_REQUIREMENTS_TXT}"
    if not _REQUIREMENTS_LOCK.exists():
        return False, (
            f"requirements.lock not found at {_REQUIREMENTS_LOCK}; "
            "regenerate with: pip-compile requirements.txt -o requirements.lock"
        )

    req_text = _REQUIREMENTS_TXT.read_text(encoding="utf-8")
    top_level: list[str] = []
    for raw_line in req_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name = re.split(r"[>=<!\[;\s@]", line)[0].strip()
        if name:
            top_level.append(_normalize_pkg(name))

    lock_text = _REQUIREMENTS_LOCK.read_text(encoding="utf-8")
    pinned: set[str] = set()
    for raw_line in lock_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Match both plain pins (boto3==1.x) and extras pins (pyiceberg[glue,duckdb]==0.x).
        m = re.match(r"^([A-Za-z0-9_\-\.]+)(?:\[[^\]]*\])?==", line)
        if m:
            pinned.add(_normalize_pkg(m.group(1)))

    missing = [pkg for pkg in top_level if pkg not in pinned]
    req_identity = f"{len(req_text)} bytes, {len(top_level)} top-level packages"
    if missing:
        return False, f"requirements.lock missing pins for: {', '.join(missing)} (requirements.txt: {req_identity})"

    return True, f"requirements.lock pins all {len(top_level)} top-level packages (requirements.txt: {req_identity})"


def _normalize_pkg(name: str) -> str:
    """Normalize a package name to lowercase with underscores (PEP 503 canonical form)."""
    return name.lower().replace("-", "_").replace(".", "_")


def evaluate_bazel_revisit_trigger() -> tuple[bool, str]:
    """Evaluate the Decision 80 cl.4 Bazel revisit trigger predicate.

    Predicate (AND-gate -- BOTH conditions must be true for the trigger to fire):
      1. Executor concurrency > 1  (T4.4 milestone; currently 1)
      2. KG.13 tier_item filed  OR  _FAST_TIER_BUDGET_SECONDS breach recurred

    Returns (fired, advisory_message). The trigger is ADVISORY ONLY -- never auto-acts
    (Decision 55 / alarm-not-gate). Callers must exit 0 regardless of fired.
    """
    concurrency = _read_executor_concurrency()

    if concurrency <= 1:
        return False, (
            f"Bazel revisit trigger: DORMANT "
            f"(executor concurrency={concurrency}; "
            "trigger requires concurrency>1 AND (KG.13 filed OR budget breach) -- Decision 80 cl.4)"
        )

    kg13 = _kg13_tier_item_filed()
    breach = _fast_tier_budget_breach_open()

    if not (kg13 or breach):
        return False, (
            f"Bazel revisit trigger: DORMANT "
            f"(concurrency={concurrency}>1 but neither KG.13 filed nor budget breach open "
            "-- Decision 80 cl.4 AND-gate not satisfied)"
        )

    reasons: list[str] = []
    if kg13:
        reasons.append("KG.13 tier_item filed")
    if breach:
        reasons.append("_FAST_TIER_BUDGET_SECONDS breach open")
    return True, (
        f"ADVISORY: Bazel revisit trigger FIRED "
        f"(concurrency={concurrency}, {', '.join(reasons)}). "
        "Decision 80 cl.4 signal: schedule a build-orchestrator re-evaluation session. "
        "No automatic action taken (Decision 55 / alarm-not-gate)."
    )


def _read_executor_concurrency() -> int:
    capabilities = ROOT / "config" / "agent" / "executor" / "capabilities.yaml"
    if not capabilities.exists():
        return 1
    try:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load(capabilities.read_text(encoding="utf-8"))
        return int(data.get("concurrency", 1))
    except Exception:
        return 1


def _kg13_tier_item_filed() -> bool:
    roadmap = ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
    if not roadmap.exists():
        return False
    try:
        text = roadmap.read_text(encoding="utf-8")
        return bool(re.search(r"\bid:\s*['\"]?KG\.13['\"]?", text))
    except Exception:
        return False


def _fast_tier_budget_breach_open() -> bool:
    recs_log = ROOT / "logs" / ".recommendations-log.jsonl"
    if not recs_log.exists():
        return False
    try:
        with recs_log.open(encoding="utf-8") as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") == "open" and "fast" in rec.get("title", "").lower() and "budget" in rec.get(
                    "title", ""
                ).lower():
                    return True
    except Exception:
        return False
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Import governance checks (Decision 80 / T3.11)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check-contracts", action="store_true", help="Run import-linter contracts (exit 0=pass)")
    group.add_argument("--check-lockfile", action="store_true", help="Verify requirements.lock sync (exit 0=pass)")
    group.add_argument("--revisit-trigger", action="store_true", help="Evaluate Bazel revisit trigger (advisory; exit 0 always)")
    args = parser.parse_args()

    if args.check_contracts:
        passed, output = run_import_contracts()
        print(output, end="")
        sys.exit(0 if passed else 1)

    if args.check_lockfile:
        in_sync, message = check_lockfile_sync()
        print(message)
        sys.exit(0 if in_sync else 1)

    if args.revisit_trigger:
        _fired, message = evaluate_bazel_revisit_trigger()
        print(message)
        sys.exit(0)


if __name__ == "__main__":
    main()
