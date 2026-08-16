"""Tests for validate_iam_simulate_fixture_shape() -- PLAN-class-d-enforcers-wave-2 (rec-3059).

Covers: green path against a minimal fixture that passes iam_simulate's pure validation layer,
expected_decision_values-drift and placeholders-drift red paths, malformed-triple/unknown-decision/
wildcard-target red paths (all surfaced through the pure validation layer itself), ABSENT/EMPTY
target red paths, missing-file, and malformed-YAML red paths. Never touches AWS, boto3, or a live
decision -- see the module docstring's scope boundary.
"""

from __future__ import annotations

from pathlib import Path

from scripts.checks import registry
from scripts.checks.contracts.validate_iam_simulate_fixture_shape import validate_iam_simulate_fixture_shape

_CONTRACT_NAME = "iam-simulate-fixture.yaml"

_VALID_TRIPLES = """
  - id: allowed-verb
    verb: "iam:ListInstanceProfilesForRole"
    target_arn_template: "arn:aws:iam::${account_id}:role/agent-platform-simulate-probe"
    expected_decision: allowed
    required_context_keys: {}
    why: "rec-2882 companion verb."
  - id: denied-verb
    verb: "s3:DeleteBucket"
    target_arn_template: "arn:aws:s3:::agent-platform-data-lake"
    expected_decision: implicitDeny
    required_context_keys: {}
    why: "Bucket destruction stays admin-tier."
  - id: explicit-denied-verb
    verb: "iam:CreatePolicyVersion"
    target_arn_template: "arn:aws:iam::${account_id}:policy/agent-platform-github-ci-apply-reads"
    expected_decision: explicitDeny
    required_context_keys: {}
    why: "S5 policy-architecture split."
"""


def _write(
    tmp_path: Path,
    *,
    principal: str = 'principal:\n  arn_template: "arn:aws:iam::${account_id}:role/agent-platform-github-ci-apply"\n',
    expected_decision_values: str = "expected_decision_values:\n  - allowed\n  - implicitDeny\n  - explicitDeny\n",
    placeholders: str = 'placeholders:\n  account_id: "resolved at run time"\n  region: "resolved at run time"\n',
    triples: str = f"triples:{_VALID_TRIPLES}",
    name: str = _CONTRACT_NAME,
) -> Path:
    body = f"schema_version: 1\n{principal}{expected_decision_values}{placeholders}{triples}"
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


class TestGreenPath:
    def test_valid_fixture_passes(self, tmp_path: Path) -> None:
        _write(tmp_path)

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert failed == []


class TestPureValidationLayerRedPath:
    def test_no_triples_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, triples="triples: []\n")

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("failed the pure validation layer" in f for f in failed)

    def test_malformed_triple_missing_field_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, triples='triples:\n  - id: only-an-id\n    verb: "iam:GetRole"\n')

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("failed the pure validation layer" in f for f in failed)

    def test_unknown_expected_decision_fails(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            triples=(
                'triples:\n  - id: bad-decision\n    verb: "iam:GetRole"\n'
                '    target_arn_template: "arn:aws:iam::${account_id}:role/x"\n'
                '    expected_decision: maybe\n    required_context_keys: {}\n    why: "x"\n'
            ),
        )

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("failed the pure validation layer" in f for f in failed)

    def test_wildcard_target_fails(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            triples=(
                'triples:\n  - id: wildcard\n    verb: "iam:GetRole"\n'
                '    target_arn_template: "arn:aws:iam::${account_id}:role/*"\n'
                '    expected_decision: allowed\n    required_context_keys: {}\n    why: "x"\n'
            ),
        )

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("failed the pure validation layer" in f for f in failed)

    def test_no_principal_arn_template_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, principal="principal: {}\n")

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("failed the pure validation layer" in f for f in failed)


class TestDriftRedPath:
    def test_expected_decision_values_drift_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, expected_decision_values="expected_decision_values:\n  - allowed\n  - implicitDeny\n")

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("expected_decision_values" in f and "VALID_DECISIONS" in f for f in failed)

    def test_placeholders_key_drift_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, placeholders='placeholders:\n  acct_id: "resolved at run time"\n  region: "resolved at run time"\n')

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("placeholders keys" in f for f in failed)


class TestAbsentEmptyTarget:
    def test_missing_expected_decision_values_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, expected_decision_values="")

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("expected_decision_values" in f and "missing or empty" in f for f in failed)

    def test_empty_expected_decision_values_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, expected_decision_values="expected_decision_values: []\n")

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("expected_decision_values" in f and "missing or empty" in f for f in failed)

    def test_missing_placeholders_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, placeholders="")

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("placeholders" in f and "missing or empty" in f for f in failed)

    def test_empty_placeholders_fails(self, tmp_path: Path) -> None:
        _write(tmp_path, placeholders="placeholders: {}\n")

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("placeholders" in f and "missing or empty" in f for f in failed)


class TestMissingFile:
    def test_missing_contract_file_fails(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("not found" in f for f in failed)


class TestMalformedYaml:
    def test_malformed_yaml_fails(self, tmp_path: Path) -> None:
        (tmp_path / _CONTRACT_NAME).write_text("triples: [unterminated", encoding="utf-8")

        failed: list[str] = []
        validate_iam_simulate_fixture_shape(failed, contracts_dir=tmp_path)

        assert any("failed the pure validation layer" in f for f in failed)


class TestWiring:
    def test_wiring_registered_in_pre_and_full(self) -> None:
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}

        assert "validate_iam_simulate_fixture_shape" in pre_names
        assert "validate_iam_simulate_fixture_shape" in full_names

    def test_wiring_resolves_via_registry(self) -> None:
        resolved = registry.resolve("validate_iam_simulate_fixture_shape")

        assert callable(resolved)
        assert resolved is validate_iam_simulate_fixture_shape
