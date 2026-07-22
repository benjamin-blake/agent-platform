"""Tests for the M2 boundary-attached gate (Decision 144 / T2.48, DEP-02)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.iam_tf.validate_boundary_attached import _resolve_name, validate_boundary_attached

_BOUNDARY_ARN = '"arn:aws:iam::1234567890:policy/agent-platform-github-ci-apply-boundary"'


def _run(tmp_path: Path, tf: str) -> list[str]:
    personal = tmp_path / "terraform" / "personal"
    personal.mkdir(parents=True, exist_ok=True)
    (personal / "roles.tf").write_text(tf, encoding="utf-8")
    failed: list[str] = []
    with patch("scripts.checks._common.ROOT", tmp_path):
        validate_boundary_attached(failed)
    return failed


def test_real_tree_all_bounded() -> None:
    """Every agent-platform-* role in the real terraform/personal declares the boundary."""
    failed: list[str] = []
    validate_boundary_attached(failed)
    assert failed == [], failed


def test_agent_platform_role_with_boundary_passes(tmp_path: Path) -> None:
    tf = f"""
resource "aws_iam_role" "exec" {{
  name                 = "agent-platform-new-exec"
  permissions_boundary = {_BOUNDARY_ARN}
}}
"""
    assert _run(tmp_path, tf) == []


def test_agent_platform_role_missing_boundary_fails(tmp_path: Path) -> None:
    tf = """
resource "aws_iam_role" "exec" {
  name = "agent-platform-forgot-boundary"
}
"""
    failed = _run(tmp_path, tf)
    assert len(failed) == 1
    assert "agent-platform-forgot-boundary" in failed[0]
    assert "does not declare" in failed[0]


def test_non_agent_platform_role_skipped(tmp_path: Path) -> None:
    """PlatformAdmin (name not agent-platform-*) is outside the prefix scope -- no boundary required."""
    tf = """
resource "aws_iam_role" "platform_admin" {
  name = "PlatformAdmin"
}
"""
    assert _run(tmp_path, tf) == []


def test_name_via_local_reference_resolved(tmp_path: Path) -> None:
    """A role whose name is a local.* reference (the prod-role pattern) is resolved and checked."""
    tf_missing = """
locals {
  dispatcher_function = "agent-platform-scheduled-agent-dispatcher"
}

resource "aws_iam_role" "dispatcher" {
  name = local.dispatcher_function
}
"""
    failed = _run(tmp_path, tf_missing)
    assert any("agent-platform-scheduled-agent-dispatcher" in f for f in failed)


def test_resolve_name_variants() -> None:
    assert _resolve_name('"agent-platform-x"', {}) == "agent-platform-x"
    assert _resolve_name("local.fn", {"fn": "agent-platform-y"}) == "agent-platform-y"
    assert _resolve_name("local.undefined", {}) is None
    # Neither a quoted literal nor a local.* ref (e.g. a var reference) -> unresolved.
    assert _resolve_name("var.role_name", {}) is None


def test_no_tf_files_fails_loud(tmp_path: Path) -> None:
    (tmp_path / "terraform" / "personal").mkdir(parents=True, exist_ok=True)
    failed: list[str] = []
    with patch("scripts.checks._common.ROOT", tmp_path):
        validate_boundary_attached(failed)
    assert any("no .tf files" in f for f in failed)
