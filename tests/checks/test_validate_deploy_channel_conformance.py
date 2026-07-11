"""Tests for validate_deploy_channel_conformance() (Decision 104, Decision 125/126).

VP step 1: a canned channel_class<->ignore_changes mismatch fixture asserts the check
FAILS (proves it is behavioural, not vacuous); a matching-state fixture asserts it PASSES.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.ops_governance.validate_deploy_channel_conformance import (
    validate_deploy_channel_conformance,
)

_TF_DECOUPLED = """
resource "aws_lambda_function" "writer" {
  function_name = "agent-platform-ducklake-writer"
  source_code_hash = try(filemd5("x.zip"), null)

  lifecycle {
    ignore_changes = [source_code_hash]
  }
}

resource "aws_lambda_function" "reader" {
  function_name = "agent-platform-ducklake-reader"
  source_code_hash = try(filemd5("y.zip"), null)

  lifecycle {
    ignore_changes = [source_code_hash]
  }
}
"""

_TF_COUPLED = """
resource "aws_lambda_function" "writer" {
  function_name = "agent-platform-ducklake-writer"
  source_code_hash = try(filemd5("x.zip"), null)
}

resource "aws_lambda_function" "reader" {
  function_name = "agent-platform-ducklake-reader"
  source_code_hash = try(filemd5("y.zip"), null)
}
"""

_TF_MIXED = """
resource "aws_lambda_function" "writer" {
  function_name = "agent-platform-ducklake-writer"
  source_code_hash = try(filemd5("x.zip"), null)

  lifecycle {
    ignore_changes = [source_code_hash]
  }
}

resource "aws_lambda_function" "reader" {
  function_name = "agent-platform-ducklake-reader"
  source_code_hash = try(filemd5("y.zip"), null)
}
"""

_BUILD_LAMBDA_DECOUPLED = """
deploy_channels:
  ducklake_functions:
    root: terraform/personal
    channel_class: terraform_personal_ignore_changes_decoupled
"""

_BUILD_LAMBDA_COUPLED = """
deploy_channels:
  ducklake_functions:
    root: terraform/personal
    channel_class: terraform_personal_filemd5_coupled
"""

_TAXONOMY_DECOUPLED = """## 5. Lambda code/infra decoupling principle (personal-account Lambdas)

**Conformance status:** the four DuckLake Lambdas are now DECOUPLED
(ignore_changes=[source_code_hash]).

## 6. Next section
Unrelated content.
"""

_TAXONOMY_COUPLED = """## 5. Lambda code/infra decoupling principle (personal-account Lambdas)

**Conformance status:** the four DuckLake Lambdas are currently COUPLED, not conformant.

## 6. Next section
Unrelated content.
"""


class TestValidateDeployChannelConformance:
    def _write(self, tmp_path: Path, tf: str, build_lambda: str, taxonomy: str) -> None:
        personal_dir = tmp_path / "terraform" / "personal"
        personal_dir.mkdir(parents=True, exist_ok=True)
        (personal_dir / "ducklake_lambdas.tf").write_text(tf, encoding="utf-8")

        contracts_dir = tmp_path / "docs" / "contracts"
        contracts_dir.mkdir(parents=True, exist_ok=True)
        (contracts_dir / "build-lambda.yaml").write_text(build_lambda, encoding="utf-8")
        (contracts_dir / "environment-taxonomy.md").write_text(taxonomy, encoding="utf-8")

    def _run(self, tmp_path: Path) -> list[str]:
        with patch("scripts.checks._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_deploy_channel_conformance(failed)
        return failed

    def test_matching_decoupled_state_passes(self, tmp_path: Path) -> None:
        self._write(tmp_path, _TF_DECOUPLED, _BUILD_LAMBDA_DECOUPLED, _TAXONOMY_DECOUPLED)
        assert self._run(tmp_path) == []

    def test_matching_coupled_state_passes(self, tmp_path: Path) -> None:
        self._write(tmp_path, _TF_COUPLED, _BUILD_LAMBDA_COUPLED, _TAXONOMY_COUPLED)
        assert self._run(tmp_path) == []

    def test_stale_build_lambda_channel_class_fails(self, tmp_path: Path) -> None:
        """Actual state is decoupled but build-lambda.yaml still claims coupled -- the #544 drift class."""
        self._write(tmp_path, _TF_DECOUPLED, _BUILD_LAMBDA_COUPLED, _TAXONOMY_DECOUPLED)
        failed = self._run(tmp_path)
        assert len(failed) == 1
        assert "build-lambda.yaml" in failed[0]
        assert "decoupled" in failed[0] and "coupled" in failed[0]

    def test_stale_taxonomy_conformance_marker_fails(self, tmp_path: Path) -> None:
        """Actual state is decoupled but environment-taxonomy.md section 5 still claims COUPLED."""
        self._write(tmp_path, _TF_DECOUPLED, _BUILD_LAMBDA_DECOUPLED, _TAXONOMY_COUPLED)
        failed = self._run(tmp_path)
        assert len(failed) == 1
        assert "environment-taxonomy.md" in failed[0]

    def test_no_ducklake_functions_found_fails(self, tmp_path: Path) -> None:
        personal_dir = tmp_path / "terraform" / "personal"
        personal_dir.mkdir(parents=True, exist_ok=True)
        contracts_dir = tmp_path / "docs" / "contracts"
        contracts_dir.mkdir(parents=True, exist_ok=True)
        (contracts_dir / "build-lambda.yaml").write_text(_BUILD_LAMBDA_DECOUPLED, encoding="utf-8")
        (contracts_dir / "environment-taxonomy.md").write_text(_TAXONOMY_DECOUPLED, encoding="utf-8")
        failed = self._run(tmp_path)
        assert len(failed) == 1
        assert "no aws_lambda_function resources found" in failed[0]

    def test_partial_rollout_fails(self, tmp_path: Path) -> None:
        self._write(tmp_path, _TF_MIXED, _BUILD_LAMBDA_DECOUPLED, _TAXONOMY_DECOUPLED)
        failed = self._run(tmp_path)
        assert len(failed) == 1
        assert "partial rollout" in failed[0]
