from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONTEXT = ROOT / "docs" / "PROJECT_CONTEXT.md"


def _text() -> str:
    return PROJECT_CONTEXT.read_text(encoding="utf-8")


def test_project_context_preserves_roadmap_end_state_orientation() -> None:
    text = _text()

    assert "Platform roadmap end-state map" in text
    assert "T2.18 DuckLake maintenance" in text
    assert "T2.36 telemetry rebuild on DuckLake" in text
    assert "T4.2 Lambda Durable Function agent personas" in text
    assert "T4.3 priority-queue producer repoint to DuckLake" in text
    assert "roadmap_tier_id_set sha256: 5ce59be4136f4c884d0aa427c09f29ed728e5192f41da0f2128fb02a60dc7307" in text


def test_project_context_keeps_operational_boundaries_actionable() -> None:
    text = _text()

    assert "Repository visibility: public" in text
    assert "Never commit credentials" in text
    assert "Agent-facing operations are only" in text
    assert "file_rec" in text and "update_rec" in text and "sync" in text
    assert "Never append to `logs/.recommendations-log.jsonl`" in text
    assert "governed GitHub workflows" in text
    assert "break-glass only" in text


def test_project_context_removes_stale_local_executor_branch_guidance() -> None:
    text = _text()

    assert "git worktree add ../agent-platform-{slug} agent/{slug}" not in text
    assert "agent/{slug}" not in text
    assert "direct Bedrock local path" not in text
