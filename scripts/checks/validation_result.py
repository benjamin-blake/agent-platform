"""Atomic, output-only evidence for completed full validator runs."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RESULT_PATH = Path("logs/debug/validation-result.json")

# Accumulator of (check, label) attributions, populated by dispatch_recording() as each
# registered check runs and reset by clear() (validate.py's own start-of-run lifecycle) so
# runs never cross-contaminate.
_ATTRIBUTIONS: list[dict[str, str]] = []


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def clear(path: Path = RESULT_PATH) -> None:
    path.unlink(missing_ok=True)
    _ATTRIBUTIONS.clear()


def dispatch_recording(name: str, failed: list[str], namespace: dict[str, Any]) -> None:
    """Run a registered check via `namespace[name](failed)`, attributing each label it newly
    appends to `failed` back to `name`. `namespace` is the caller's own globals() (validate.py's
    _dispatch_check passes its module globals()) so a `patch("validate.<name>")` interception
    still resolves -- this preserves validate.py's existing dispatch contract exactly.
    """
    before = len(failed)
    namespace[name](failed)
    for label in failed[before:]:
        _ATTRIBUTIONS.append({"check": name, "label": label})


def git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def write_completed(
    *, started_at: str, exit_code: int, failed_checks: list[str], path: Path = RESULT_PATH
) -> dict[str, object]:
    record: dict[str, object] = {
        "schema_version": 2,
        "command": "bin/venv-python -m scripts.validate",
        "scope": "all",
        "git_head": git_head(),
        "started_at": started_at,
        "completed_at": utc_now(),
        "exit_code": exit_code,
        "failed_checks": failed_checks,
        "failed_check_attributions": list(_ATTRIBUTIONS),
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
