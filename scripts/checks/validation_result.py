"""Atomic, output-only evidence for completed full validator runs."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from scripts.checks import registry

RESULT_PATH = Path("logs/debug/validation-result.json")

# Accumulator of (check, label) attributions, populated by dispatch_recording() as each
# registered check runs and reset by clear() (validate.py's own start-of-run lifecycle) so
# runs never cross-contaminate.
_ATTRIBUTIONS: list[dict[str, str]] = []

# Accumulator of CheckOutcome rows (Decision 170) -- one per dispatched check, plus any scaffold
# that opens a registry.outcome_scope. Reset by clear(), same lifecycle as _ATTRIBUTIONS. Write
# mode is append-within-run then whole-file replace (see write_completed): this is a run artifact,
# never read as history, so it needs no merge key/identity/partitioning.
_OUTCOMES: list[registry.CheckOutcome] = []


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def clear(path: Path = RESULT_PATH) -> None:
    path.unlink(missing_ok=True)
    _ATTRIBUTIONS.clear()
    _OUTCOMES.clear()


def _harvest_declared_outcome(name: str, kind: str, appended_to_failed: bool) -> None:
    declaration = registry.pop_declaration()
    _OUTCOMES.append(registry.build_outcome(name, kind, declaration, appended_to_failed))


def record_scaffold_outcome(name: str, before: int, failed: list[str]) -> None:
    """Harvest a non-check scaffold's declared outcome after its registry.outcome_scope(...)
    block has exited. `before` is len(failed) captured BEFORE the scope opened."""
    _harvest_declared_outcome(name, "scaffold", appended_to_failed=bool(failed[before:]))


def dispatch_recording(name: str, failed: list[str], fn: Callable[[list[str]], None]) -> None:
    """Run a registered check via `fn(failed)`, attributing each label it newly appends to
    `failed` back to `name`. `fn` is resolved by the CALLER (scripts.checks.registry.resolve(name),
    late-bound at call time -- Decision 169, amending Decision 104's namespace-dict dispatch) so a
    `patch("<the check's defining module>.<name>", ...)` interception still resolves through a
    real dispatch pass.

    Brackets the call with registry.outcome_scope() (Decision 170) so the check's own
    examined()/skipped() declaration -- or lack of one -- is harvested into _OUTCOMES alongside
    the existing failed-label attribution.
    """
    before = len(failed)
    with registry.outcome_scope(name, kind="check"):
        fn(failed)
    appended = failed[before:]
    for label in appended:
        _ATTRIBUTIONS.append({"check": name, "label": label})
    _harvest_declared_outcome(name, "check", appended_to_failed=bool(appended))


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


# Status -> rollup-key map (Decision 170). "failed" checks are already tracked by the existing
# failed_checks/failed_check_attributions fields, so they are deliberately NOT double-counted in
# a rollup bucket here.
_ROLLUP_KEY_BY_STATUS: dict[str, str] = {
    "enforced": "ran_checks",
    "skipped": "skipped_checks",
    "vacuous": "vacuous_checks",
    "undeclared": "undeclared_checks",
}


def _rollups(outcomes: list[registry.CheckOutcome]) -> dict[str, int]:
    counts = {key: 0 for key in _ROLLUP_KEY_BY_STATUS.values()}
    for outcome in outcomes:
        key = _ROLLUP_KEY_BY_STATUS.get(outcome.status)
        if key is not None:
            counts[key] += 1
    return counts


def write_completed(
    *, started_at: str, exit_code: int, failed_checks: list[str], path: Path = RESULT_PATH
) -> dict[str, object]:
    outcomes_snapshot = list(_OUTCOMES)
    record: dict[str, object] = {
        "schema_version": 3,
        "command": "bin/venv-python -m scripts.validate",
        "scope": "all",
        "git_head": git_head(),
        "started_at": started_at,
        "completed_at": utc_now(),
        "exit_code": exit_code,
        "failed_checks": failed_checks,
        "failed_check_attributions": list(_ATTRIBUTIONS),
        "check_outcomes": [dataclasses.asdict(outcome) for outcome in outcomes_snapshot],
        **_rollups(outcomes_snapshot),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return record


def write_completed_visible(**kwargs: object) -> None:
    try:
        write_completed(**kwargs)  # type: ignore[arg-type]
    except OSError as exc:
        print(f"WARNING: validation evidence could not be written: {type(exc).__name__}")
