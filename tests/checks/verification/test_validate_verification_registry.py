"""Tests for validate_verification_registry() (VF-06). Mirror of
scripts/checks/verification/validate_verification_registry.py -- merges
TestVerificationRegistry, TestVerificationRegistryDifferential, TestEntriesAtRef,
and the module-level test_registry_differential_skip_is_non_fatal /
test_verification_registry_accepts_empty_file (rec-2709 Wave 1)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts import verification_graduation
from scripts.checks.verification.validate_verification_registry import validate_verification_registry


class TestVerificationRegistry:
    """Tests for validate_verification_registry() in validate.py --pre tier."""

    def test_pass_with_empty_entries(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text("entries: []\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert not failed

    def test_fail_missing_entries_key(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text("other_key: 1\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("missing top-level 'entries' key" in f for f in failed), failed

    def test_fail_entries_not_a_list(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text("entries: not-a-list\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("'entries' must be a list" in f for f in failed), failed

    def test_schema_error_non_dict_entry(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text("entries:\n  - just-a-string\n", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_fail_missing_file(self, tmp_path: Path) -> None:
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("not found" in f for f in failed)

    def test_fail_invalid_yaml(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text("entries: [\n  - invalid: yaml: :", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert any("YAML" in f for f in failed)

    def test_fail_missing_required_field(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text(
            "entries:\n  - check_id: x\n    primitive_slot: grep_count\n",
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_fail_unknown_slot(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text(
            (
                "entries:\n"
                "  - check_id: x\n"
                "    primitive_slot: unknown_slot\n"
                "    guard_target: scripts/foo.py\n"
                "    plan_slug: my-plan\n"
                "    graduated_at: '2026-06-29'\n"
            ),
            encoding="utf-8",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_fail_duplicate_check_id(self, tmp_path: Path) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        entry = (
            "  - check_id: dup\n"
            "    primitive_slot: grep_count\n"
            "    guard_target: scripts/foo.py\n"
            "    plan_slug: my-plan\n"
            "    graduated_at: '2026-06-29'\n"
        )
        (reg / "registry.yaml").write_text(f"entries:\n{entry}{entry}", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_verification_registry(failed)
        assert "Verification registry" in failed

    def test_pass_valid_entry(self, tmp_path: Path) -> None:
        """Schema-valid entry with no check_spec: treated as pre-existing (not added), so the
        VF-06 c2 differential does not fire (no check_spec means it can't be materialized)."""
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text(
            (
                "entries:\n"
                "  - check_id: my-check\n"
                "    primitive_slot: grep_count\n"
                "    guard_target: scripts/foo.py\n"
                "    plan_slug: my-plan\n"
                "    graduated_at: '2026-06-29'\n"
            ),
            encoding="utf-8",
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[],
            ),
        ):
            validate_verification_registry(failed)
        assert not failed


class TestVerificationRegistryDifferential:
    """VP step 6: validate_verification_registry's added-entry differential branch (VF-06 c2).

    The differential mechanism itself (real worktree revert) is covered by
    tests/test_verification_graduation.py; here we drive the validate.py wiring with a stubbed
    scripts.verification_graduation to verify the diff-gating, message shape, and fail-loud
    error surfacing.
    """

    def _write_registry(self, tmp_path: Path, entries_yaml: str) -> None:
        reg = tmp_path / "config" / "agent" / "verification_registry"
        reg.mkdir(parents=True)
        (reg / "registry.yaml").write_text(entries_yaml, encoding="utf-8")

    def test_added_entry_admitted(self, tmp_path: Path) -> None:
        self._write_registry(
            tmp_path,
            (
                "entries:\n"
                "  - check_id: new-check\n"
                "    primitive_slot: grep_count\n"
                "    guard_target: scripts/foo.py\n"
                "    plan_slug: my-plan\n"
                "    graduated_at: '2026-07-04'\n"
                "    check_spec: {path: scripts/foo.py, pattern: 'x', operator: eq, count: 1}\n"
            ),
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[{"check_id": "new-check"}],
            ),
            patch(
                "scripts.verification_graduation.run_differential",
                return_value=verification_graduation.DifferentialOutcome(
                    admitted=True, reason="admitted -- fails on origin/main, passes on HEAD"
                ),
            ),
        ):
            validate_verification_registry(failed)
        assert not failed

    def test_added_entry_not_admitted_tautological(self, tmp_path: Path) -> None:
        self._write_registry(
            tmp_path,
            (
                "entries:\n"
                "  - check_id: taut\n"
                "    primitive_slot: grep_count\n"
                "    guard_target: x\n"
                "    plan_slug: p\n"
                "    graduated_at: '2026-07-04'\n"
            ),
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[{"check_id": "taut"}],
            ),
            patch(
                "scripts.verification_graduation.run_differential",
                return_value=verification_graduation.DifferentialOutcome(
                    admitted=False, reason="not admitted -- revert did not produce FAIL (tautological)"
                ),
            ),
        ):
            validate_verification_registry(failed)
        assert any("not admitted" in f for f in failed), failed

    def test_no_added_entry_is_noop(self, tmp_path: Path) -> None:
        self._write_registry(
            tmp_path,
            (
                "entries:\n"
                "  - check_id: x\n"
                "    primitive_slot: grep_count\n"
                "    guard_target: y\n"
                "    plan_slug: p\n"
                "    graduated_at: '2026-07-04'\n"
            ),
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks.verification.validate_verification_registry._added_entries", return_value=[]),
            patch("scripts.verification_graduation.run_differential") as mock_diff,
        ):
            validate_verification_registry(failed)
        assert not failed
        mock_diff.assert_not_called()

    def test_graduation_error_surfaces_as_failure(self, tmp_path: Path) -> None:
        self._write_registry(
            tmp_path,
            (
                "entries:\n"
                "  - check_id: bad\n"
                "    primitive_slot: grep_count\n"
                "    guard_target: y\n"
                "    plan_slug: p\n"
                "    graduated_at: '2026-07-04'\n"
            ),
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.verification.validate_verification_registry._added_entries",
                return_value=[{"check_id": "bad"}],
            ),
            patch(
                "scripts.verification_graduation.run_differential",
                side_effect=verification_graduation.GraduationError("worktree add failed"),
            ),
        ):
            validate_verification_registry(failed)
        assert any("error --" in f for f in failed), failed


class TestEntriesAtRef:
    """Direct unit tests for _entries_at_ref (VF-06 c2 baseline-fetch helper)."""

    def test_returns_empty_on_nonzero_returncode(self) -> None:
        from scripts.checks.verification.validate_verification_registry import _entries_at_ref

        with patch("scripts.checks._common.run", return_value=MagicMock(returncode=1, stdout="")):
            assert _entries_at_ref("origin/main") == []

    def test_returns_empty_on_yaml_parse_error(self) -> None:
        from scripts.checks.verification.validate_verification_registry import _entries_at_ref

        with patch(
            "scripts.checks._common.run",
            return_value=MagicMock(returncode=0, stdout="entries: [\n  - broken: yaml: :"),
        ):
            assert _entries_at_ref("origin/main") == []

    def test_returns_empty_on_non_dict_content(self) -> None:
        from scripts.checks.verification.validate_verification_registry import _entries_at_ref

        with patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="just-a-string\n")):
            assert _entries_at_ref("origin/main") == []

    def test_returns_entries_list_on_valid_content(self) -> None:
        from scripts.checks.verification.validate_verification_registry import _entries_at_ref

        stdout = "entries:\n  - check_id: x\n    primitive_slot: grep_count\n"
        with patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=stdout)):
            entries = _entries_at_ref("origin/main")
        assert entries == [{"check_id": "x", "primitive_slot": "grep_count"}]


def test_registry_differential_skip_is_non_fatal(tmp_path: Path) -> None:
    """rec-2655: a skipped DifferentialOutcome (importorskip-guarded, fast-tier-excluded node)
    does not append to failed -- distinct from a genuine not-admitted rejection."""
    reg = tmp_path / "config" / "agent" / "verification_registry"
    reg.mkdir(parents=True)
    (reg / "registry.yaml").write_text(
        (
            "entries:\n"
            "  - check_id: guarded\n"
            "    primitive_slot: test_selector\n"
            "    guard_target: scripts/foo.py\n"
            "    plan_slug: my-plan\n"
            "    graduated_at: '2026-07-04'\n"
            "    check_spec: {node_id: 'tests/test_foo.py::test_x'}\n"
        ),
        encoding="utf-8",
    )
    failed: list[str] = []
    with (
        patch("scripts.checks._common.ROOT", tmp_path),
        patch(
            "scripts.checks.verification.validate_verification_registry._added_entries",
            return_value=[{"check_id": "guarded"}],
        ),
        patch(
            "scripts.verification_graduation.run_differential",
            return_value=verification_graduation.DifferentialOutcome(
                admitted=False,
                skipped=True,
                reason="skipped -- node in importorskip-guarded fast-tier-excluded file (duckdb)",
            ),
        ),
    ):
        validate_verification_registry(failed)
    assert failed == []


def test_verification_registry_accepts_empty_file(tmp_path: Path) -> None:
    """VP step 5: registry guard accepts an empty well-formed entries list."""
    reg = tmp_path / "config" / "agent" / "verification_registry"
    reg.mkdir(parents=True)
    (reg / "registry.yaml").write_text("entries: []\n", encoding="utf-8")
    failed: list = []
    with patch("scripts.checks._common.ROOT", tmp_path):
        validate_verification_registry(failed)
    assert not failed
