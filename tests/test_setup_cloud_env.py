"""Contract tests for bin/setup-cloud-env.sh without executing networked installers."""

from __future__ import annotations

from pathlib import Path

SETUP_SCRIPT = Path("bin/setup-cloud-env.sh")


def test_shared_session_bootstrap_steps_are_ordered_after_prerequisites() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    ordered_commands = (
        'bash "$REPO_ROOT/bin/sync-deps.sh"',
        'bash "$REPO_ROOT/bin/ensure-github-mcp-server.sh"',
        "bash .claude/hooks/session_start_aws.sh",
        "bash .claude/hooks/session_start_precommit.sh",
        "bash .claude/hooks/session_start_sync_main.sh",
    )

    positions = [script.index(command) for command in ordered_commands]
    assert positions == sorted(positions)
    assert script.index("set -euo pipefail") < positions[0]
    assert script.index('REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"') < positions[0]


def test_setup_contract_uses_delegated_bootstrap_commands() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")
    assert script.count('bash "$REPO_ROOT/bin/sync-deps.sh"') == 1
    assert script.count('bash "$REPO_ROOT/bin/ensure-github-mcp-server.sh"') == 1
    assert script.count("bash .claude/hooks/session_start_aws.sh") == 1
    assert script.count("bash .claude/hooks/session_start_precommit.sh") == 1
    assert script.count("bash .claude/hooks/session_start_sync_main.sh") == 1


def test_github_readiness_runs_after_mcp_install_and_before_precommit() -> None:
    script = Path("bin/setup-cloud-env.sh").read_text(encoding="utf-8")
    readiness = script.index("bash .claude/hooks/session_start_github_readiness.sh")
    assert readiness > script.index("ensure-github-mcp-server.sh")
    assert readiness < script.index("bash .claude/hooks/session_start_precommit.sh")
