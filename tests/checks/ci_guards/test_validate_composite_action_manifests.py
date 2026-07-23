"""Tests for validate_composite_action_manifests() -- composite-action manifest guard (rec-2795/2796)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from scripts.checks.ci_guards.validate_composite_action_manifests import (
    _scan_manifest,
    validate_composite_action_manifests,
)

_MODULE = "scripts.checks.ci_guards.validate_composite_action_manifests"


class TestScanManifestActionMetadataExprFailCases:
    """`${{ }}` in a metadata position must be flagged -- one case per named field."""

    def test_action_metadata_expr_in_description(self) -> None:
        data = {
            "name": "deterministic-guard",
            "description": "Path to the guard resolved via ${{ github.workspace }} (composite-action path discipline).",
        }
        violations = _scan_manifest(data)
        assert len(violations) == 1
        assert violations[0].startswith("description:")
        assert "${{ github.workspace }}" in violations[0]

    def test_action_metadata_expr_in_name(self) -> None:
        data = {"name": "guard-${{ github.run_id }}", "description": "fine"}
        violations = _scan_manifest(data)
        assert len(violations) == 1
        assert violations[0].startswith("name:")

    def test_action_metadata_expr_in_input_description(self) -> None:
        data = {
            "name": "x",
            "inputs": {"working-directory": {"description": "Root dir ${{ inputs.foo }} here", "required": False}},
        }
        violations = _scan_manifest(data)
        assert len(violations) == 1
        assert violations[0].startswith("inputs.working-directory.description:")

    def test_action_metadata_expr_in_input_default(self) -> None:
        data = {
            "name": "x",
            "inputs": {"mode": {"description": "fine", "default": "${{ inputs.other }}"}},
        }
        violations = _scan_manifest(data)
        assert len(violations) == 1
        assert violations[0].startswith("inputs.mode.default:")

    def test_action_metadata_expr_in_output_description(self) -> None:
        data = {
            "name": "x",
            "outputs": {"routed": {"description": "Set when ${{ steps.guard.outputs.routed }}", "value": "fine"}},
        }
        violations = _scan_manifest(data)
        assert len(violations) == 1
        assert violations[0].startswith("outputs.routed.description:")

    def test_action_metadata_expr_multiple_violations_all_reported(self) -> None:
        data = {
            "name": "bad-${{ github.run_id }}",
            "description": "Also bad ${{ github.workspace }}",
        }
        violations = _scan_manifest(data)
        assert len(violations) == 2

    def test_action_metadata_expr_non_dict_input_returns_no_violations(self) -> None:
        assert _scan_manifest(None) == []
        assert _scan_manifest("not-a-manifest") == []
        assert _scan_manifest([1, 2, 3]) == []

    def test_action_metadata_expr_inside_a_list_value(self) -> None:
        """The walk recurses into list nodes too, not just dicts -- e.g. a metadata list field."""
        data = {"name": "x", "aliases": ["clean", "bad-${{ github.token }}"]}
        violations = _scan_manifest(data)
        assert len(violations) == 1
        assert violations[0].startswith("aliases[1]:")


class TestScanManifestLegalExemptions:
    """`${{ }}` under `runs:` and in `outputs.*.value` is legal and must not be flagged."""

    def test_runs_subtree_fully_exempt(self) -> None:
        data = {
            "name": "x",
            "description": "clean",
            "runs": {
                "using": "composite",
                "steps": [
                    {
                        "name": "step",
                        "shell": "bash",
                        "working-directory": "${{ inputs.working-directory }}",
                        "env": {"TOKEN": "${{ github.token }}"},
                        "with": {"path": "${{ inputs.path }}"},
                        "run": 'echo "${{ github.workspace }}"',
                    }
                ],
            },
        }
        assert _scan_manifest(data) == []

    def test_outputs_value_exempt(self) -> None:
        data = {
            "name": "x",
            "outputs": {"routed": {"description": "clean", "value": "${{ steps.guard.outputs.routed }}"}},
        }
        assert _scan_manifest(data) == []

    def test_outputs_non_dict_entry_skipped_without_error(self) -> None:
        data = {"name": "x", "outputs": {"routed": "not-a-dict"}}
        assert _scan_manifest(data) == []

    def test_no_outputs_key_at_all(self) -> None:
        data = {"name": "x", "description": "clean"}
        assert _scan_manifest(data) == []

    def test_full_deterministic_guard_style_manifest_is_clean(self) -> None:
        data = {
            "name": "deterministic-guard",
            "description": "Path resolved via the github.workspace runner context (composite-action path discipline).",
            "inputs": {
                "working-directory": {"description": "Terraform root", "required": False, "default": "terraform/personal"}
            },
            "outputs": {"routed": {"description": "routed flag", "value": "${{ steps.guard.outputs.routed }}"}},
            "runs": {
                "using": "composite",
                "steps": [{"shell": "bash", "run": 'python3 "${{ github.workspace }}/scripts/guard.py"'}],
            },
        }
        assert _scan_manifest(data) == []


class TestValidateCompositeActionManifestsIntegration:
    """Integration: the real repo tree passes; a synthetic bad manifest fails."""

    def test_passes_against_real_repository_tree(self) -> None:
        failed: list[str] = []
        validate_composite_action_manifests(failed)
        assert failed == []

    def test_no_manifests_found_passes_cleanly(self, tmp_path) -> None:
        with patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_composite_action_manifests(failed)
        assert failed == []

    def test_synthetic_bad_manifest_is_flagged(self, tmp_path) -> None:
        action_dir = tmp_path / ".github" / "actions" / "bad-action"
        action_dir.mkdir(parents=True)
        (action_dir / "action.yml").write_text(
            "name: bad-action\n"
            "description: Path to the guard resolved via ${{ github.workspace }} (composite-action path discipline).\n"
            "runs:\n"
            "  using: composite\n"
            "  steps:\n"
            "    - run: echo hi\n",
            encoding="utf-8",
        )
        with patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_composite_action_manifests(failed)
        assert len(failed) == 1
        assert "bad-action" in failed[0]
        assert "description" in failed[0]

    def test_synthetic_clean_manifest_with_yaml_extension_passes(self, tmp_path) -> None:
        action_dir = tmp_path / ".github" / "actions" / "clean-action"
        action_dir.mkdir(parents=True)
        (action_dir / "action.yaml").write_text(
            "name: clean-action\ndescription: clean\nruns:\n  using: composite\n  steps: []\n",
            encoding="utf-8",
        )
        with patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            validate_composite_action_manifests(failed)
        assert failed == []


class TestValidateCompositeActionManifestsUnparseable:
    """An unparseable manifest records a failure without raising (rec-2027 pattern)."""

    def test_unparseable_yaml_records_failure_no_raise(self, tmp_path) -> None:
        action_dir = tmp_path / ".github" / "actions" / "broken-action"
        action_dir.mkdir(parents=True)
        (action_dir / "action.yml").write_text("name: [unterminated\n  description: oops", encoding="utf-8")
        with patch(f"{_MODULE}._common.ROOT", tmp_path):
            failed: list[str] = []
            try:
                validate_composite_action_manifests(failed)
            except Exception as exc:  # pragma: no cover -- defensive; must not be reached
                pytest.fail(f"validate_composite_action_manifests raised: {exc}")
        assert len(failed) == 1
        assert "unparseable" in failed[0]
