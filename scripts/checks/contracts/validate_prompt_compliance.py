"""Prompt compliance check against declared behavioural invariants."""

from __future__ import annotations

from pathlib import Path

from scripts.checks import _common, registry
from scripts.checks.contracts._shared import _load_prompt_compliance


@registry.register("validate_prompt_compliance", owner="platform")
def validate_prompt_compliance(failed: list[str]) -> None:
    """Run prompt compliance checks against declared behavioural invariants."""
    print("\n=== Prompt compliance check ===")
    compliance = _load_prompt_compliance()
    if compliance is None:
        print("prompt_compliance.py not found — skipping.")
        return

    sources = compliance.get_behavioural_invariant_sources()
    prompt_files: list[Path] = []
    for glob_pattern in sources:
        prompt_files.extend(_common.ROOT.glob(glob_pattern))
    violations: list[str] = []

    retro_log = _common.ROOT / "logs" / ".retro-lite-log.jsonl"
    state_path = _common.ROOT / "logs" / ".execution-state.json"

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
        print(f"Prompt compliance: {len(prompt_files)} file(s) checked, no violations.")
