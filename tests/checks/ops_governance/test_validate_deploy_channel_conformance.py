"""Tests for validate_deploy_channel_conformance() (Decision 104, Decision 125/126, T2.43).

VP step 1: a canned channel_class<->ignore_changes mismatch fixture asserts the check
FAILS (proves it is behavioural, not vacuous); a matching-state fixture asserts it PASSES.

Every test writes BOTH the ducklake AND the prod class fixtures (via _write's defaults) so a
scenario targeting one class doesn't spuriously fail on the other, unless the test is
specifically exercising a prod-class (or ducklake-class) mismatch.
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

_PROD_TF_DECOUPLED = """
resource "aws_lambda_function" "scheduled_agent_dispatcher" {
  function_name = "agent-platform-scheduled-agent-dispatcher"
  source_code_hash = try(filemd5("a.zip"), null)

  lifecycle {
    ignore_changes = [source_code_hash]
  }
}

resource "aws_lambda_function" "findings_processor" {
  function_name = "agent-platform-findings-processor"
  source_code_hash = try(filemd5("b.zip"), null)

  lifecycle {
    ignore_changes = [source_code_hash]
  }
}

resource "aws_lambda_function" "ops_compaction" {
  function_name = "agent-platform-ops-compaction"
  source_code_hash = try(filemd5("c.zip"), null)

  lifecycle {
    ignore_changes = [source_code_hash]
  }
}
"""

_PROD_TF_COUPLED = """
resource "aws_lambda_function" "scheduled_agent_dispatcher" {
  function_name = "agent-platform-scheduled-agent-dispatcher"
  source_code_hash = try(filemd5("a.zip"), null)
}

resource "aws_lambda_function" "findings_processor" {
  function_name = "agent-platform-findings-processor"
  source_code_hash = try(filemd5("b.zip"), null)
}

resource "aws_lambda_function" "ops_compaction" {
  function_name = "agent-platform-ops-compaction"
  source_code_hash = try(filemd5("c.zip"), null)
}
"""

_PROD_TF_MIXED = """
resource "aws_lambda_function" "scheduled_agent_dispatcher" {
  function_name = "agent-platform-scheduled-agent-dispatcher"
  source_code_hash = try(filemd5("a.zip"), null)

  lifecycle {
    ignore_changes = [source_code_hash]
  }
}

resource "aws_lambda_function" "findings_processor" {
  function_name = "agent-platform-findings-processor"
  source_code_hash = try(filemd5("b.zip"), null)
}
"""

_BUILD_LAMBDA_CHANNELS_COMPLETE = """
deploy_channels:
  ducklake_functions:
    root: terraform/personal
    channel_class: {ducklake_channel_class}
  prod_functions:
    root: terraform/personal
    channel_class: decoupled_build_pipeline
    governed_channel: .github/workflows/deploy-prod-lambdas.yml
    break_glass_only: "bin/venv-python -m scripts.build_lambda --deploy"
  ops_compaction:
    root: terraform/personal
    channel_class: decoupled_build_pipeline
    governed_channel: .github/workflows/deploy-prod-lambdas.yml
    break_glass_only: "bin/venv-python -m scripts.build_lambda --deploy"
"""

_BUILD_LAMBDA_DECOUPLED = _BUILD_LAMBDA_CHANNELS_COMPLETE.format(
    ducklake_channel_class="terraform_personal_ignore_changes_decoupled"
)
_BUILD_LAMBDA_COUPLED = _BUILD_LAMBDA_CHANNELS_COMPLETE.format(ducklake_channel_class="terraform_personal_filemd5_coupled")

_BUILD_LAMBDA_PROD_CHANNELS_INCOMPLETE = """
deploy_channels:
  ducklake_functions:
    root: terraform/personal
    channel_class: terraform_personal_ignore_changes_decoupled
  prod_functions:
    root: terraform/personal
    channel_class: decoupled_build_pipeline
  ops_compaction:
    root: terraform/personal
    channel_class: decoupled_build_pipeline
    governed_channel: .github/workflows/deploy-prod-lambdas.yml
    break_glass_only: "bin/venv-python -m scripts.build_lambda --deploy"
"""

_TAXONOMY_CHANNELS_COMPLETE = """## 5. Lambda code/infra decoupling principle (personal-account Lambdas)

**Conformance status:** the four DuckLake Lambdas are now {ducklake_marker}
(ignore_changes=[source_code_hash]).

**Conformance status (prod class):** the three prod-class Lambdas are now {prod_marker}
(ignore_changes=[source_code_hash]).

## 6. Next section
Unrelated content.
"""

_TAXONOMY_DECOUPLED = _TAXONOMY_CHANNELS_COMPLETE.format(ducklake_marker="DECOUPLED", prod_marker="DECOUPLED")
_TAXONOMY_COUPLED = _TAXONOMY_CHANNELS_COMPLETE.format(ducklake_marker="COUPLED", prod_marker="DECOUPLED")
_TAXONOMY_PROD_COUPLED = _TAXONOMY_CHANNELS_COMPLETE.format(ducklake_marker="DECOUPLED", prod_marker="COUPLED")


class TestValidateDeployChannelConformance:
    def _write(
        self,
        tmp_path: Path,
        tf: str,
        build_lambda: str,
        taxonomy: str,
        prod_tf: str = _PROD_TF_DECOUPLED,
    ) -> None:
        personal_dir = tmp_path / "terraform" / "personal"
        personal_dir.mkdir(parents=True, exist_ok=True)
        (personal_dir / "ducklake_lambdas.tf").write_text(tf, encoding="utf-8")
        (personal_dir / "prod_lambdas.tf").write_text(prod_tf, encoding="utf-8")

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
        (personal_dir / "prod_lambdas.tf").write_text(_PROD_TF_DECOUPLED, encoding="utf-8")
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

    # --- prod class (T2.43) ---

    def test_prod_matching_decoupled_state_passes(self, tmp_path: Path) -> None:
        self._write(tmp_path, _TF_DECOUPLED, _BUILD_LAMBDA_DECOUPLED, _TAXONOMY_DECOUPLED, prod_tf=_PROD_TF_DECOUPLED)
        assert self._run(tmp_path) == []

    def test_prod_no_functions_found_fails(self, tmp_path: Path) -> None:
        """prod_lambdas.tf absent entirely -- cannot determine the prod class's actual state."""
        personal_dir = tmp_path / "terraform" / "personal"
        personal_dir.mkdir(parents=True, exist_ok=True)
        (personal_dir / "ducklake_lambdas.tf").write_text(_TF_DECOUPLED, encoding="utf-8")
        contracts_dir = tmp_path / "docs" / "contracts"
        contracts_dir.mkdir(parents=True, exist_ok=True)
        (contracts_dir / "build-lambda.yaml").write_text(_BUILD_LAMBDA_DECOUPLED, encoding="utf-8")
        (contracts_dir / "environment-taxonomy.md").write_text(_TAXONOMY_DECOUPLED, encoding="utf-8")
        failed = self._run(tmp_path)
        assert len(failed) == 1
        assert "no aws_lambda_function resources found" in failed[0]
        assert "prod" in failed[0]

    def test_prod_partial_rollout_fails(self, tmp_path: Path) -> None:
        self._write(tmp_path, _TF_DECOUPLED, _BUILD_LAMBDA_DECOUPLED, _TAXONOMY_DECOUPLED, prod_tf=_PROD_TF_MIXED)
        failed = self._run(tmp_path)
        assert len(failed) == 1
        assert "partial rollout" in failed[0]
        assert "prod" in failed[0]

    def test_prod_stale_taxonomy_marker_fails(self, tmp_path: Path) -> None:
        """prod is actually decoupled but the prod-class taxonomy paragraph still claims COUPLED --
        the check must catch this WITHOUT tripping the single-paragraph ambiguous-marker guard,
        since the ducklake paragraph (which stays DECOUPLED) is a separate paragraph."""
        self._write(tmp_path, _TF_DECOUPLED, _BUILD_LAMBDA_DECOUPLED, _TAXONOMY_PROD_COUPLED, prod_tf=_PROD_TF_DECOUPLED)
        failed = self._run(tmp_path)
        assert len(failed) == 1
        assert "environment-taxonomy.md" in failed[0]
        assert "prod" in failed[0]

    def test_prod_missing_governed_channel_fails(self, tmp_path: Path) -> None:
        """build-lambda.yaml deploy_channels.prod_functions is missing governed_channel/
        break_glass_only -- the completeness check (distinct from the channel_class comparison,
        since decoupled_build_pipeline doesn't use the _decoupled/_coupled suffix convention)."""
        self._write(
            tmp_path, _TF_DECOUPLED, _BUILD_LAMBDA_PROD_CHANNELS_INCOMPLETE, _TAXONOMY_DECOUPLED, prod_tf=_PROD_TF_DECOUPLED
        )
        failed = self._run(tmp_path)
        assert len(failed) == 1
        assert "deploy_channels.prod_functions" in failed[0]
        assert "governed_channel" in failed[0]

    def test_prod_and_ducklake_mismatches_both_reported(self, tmp_path: Path) -> None:
        """A single run can surface BOTH a ducklake-class failure and a prod-class failure --
        the two classes' checks are independent, not short-circuiting on the first failure."""
        self._write(tmp_path, _TF_DECOUPLED, _BUILD_LAMBDA_COUPLED, _TAXONOMY_PROD_COUPLED, prod_tf=_PROD_TF_DECOUPLED)
        failed = self._run(tmp_path)
        assert len(failed) == 2
        assert any("build-lambda.yaml" in f for f in failed)
        assert any("prod" in f and "environment-taxonomy.md" in f for f in failed)
