from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.checks import _common, registry


@registry.register("validate_scheduled_agent_logs", owner="platform")
def validate_scheduled_agent_logs(failed: list[str]) -> None:
    """Validate log files from scheduled-agent branches.

    Skips when non-log files are changed (feature branch, not a scheduled-agent run).
    Fails on canonical-state write violations or invalid JSONL schema.
    """
    print("\n=== Scheduled agent log validation ===")

    result = _common.run(
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=_common.ROOT,
    )
    changed = [f for f in result.stdout.strip().splitlines() if f]

    if not changed:
        print("No files changed relative to origin/main -- skipping.")
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
        full_path = _common.ROOT / filepath
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
