"""Workflow agent-safety (headless claude -p) check."""

from __future__ import annotations

from scripts.checks import registry


@registry.register("validate_workflow_agent_safety", owner="platform")
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
