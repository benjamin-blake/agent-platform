"""Tests for validate_vp_replay() -- Interactive VP replay (T3.15 c2, VF-01). Mirror of
scripts/checks/verification/validate_vp_replay.py, rec-2709 Wave 1."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.verification.validate_vp_replay import validate_vp_replay


def _vp_replay_plan_dict(slug: str, verification_plan: list[dict]) -> dict:
    return {
        "schema_version": 2,
        "slug": slug,
        "intent": "Fixture plan for validate_vp_replay unit tests.",
        "plan_type": "IMPLEMENTATION",
        "verification_tier": "V2",
        "plan_path": f"docs/plans/PLAN-{slug}.yaml",
        "phase": "Test fixture",
        "scope": [{"file": "scripts/dummy.py", "action": "Modify", "purpose": "test fixture"}],
        "acceptance_criteria": ["dummy criterion"],
        "verification_plan": verification_plan,
        "execution_steps": ["dummy step"],
    }


def _write_vp_replay_plan(tmp_path: Path, slug: str, verification_plan: list[dict]) -> str:
    import yaml as _yaml  # noqa: PLC0415

    plans_dir = tmp_path / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    rel = f"docs/plans/PLAN-{slug}.yaml"
    (plans_dir / f"PLAN-{slug}.yaml").write_text(_yaml.dump(_vp_replay_plan_dict(slug, verification_plan)), encoding="utf-8")
    return rel


class TestValidateVpReplay:
    """Tests for validate_vp_replay() (T3.15 c2, VF-01) via the changed_files/root injection seam."""

    def test_vp_replay_no_plan_in_diff_is_noop_pass(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["scripts/foo.py"], root=tmp_path)
        assert failed == []

    def test_vp_replay_deleted_plan_path_is_skipped(self, tmp_path: Path) -> None:
        """A plan path present in changed_files but absent on disk (deleted in the diff) is a no-op."""
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["docs/plans/PLAN-vpr-gone.yaml"], root=tmp_path)
        assert failed == []

    def test_vp_replay_hermetic_step_failing_command_reddens(self, tmp_path: Path) -> None:
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-fail",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a command that fails.",
                    "command": "exit 1",
                    "expected": "Exit 0.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert any("vp-replay" in f and "exit 1" in f for f in failed)

    def test_vp_replay_hermetic_step_missing_literal_reddens(self, tmp_path: Path) -> None:
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-literal",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a command whose output lacks the expected literal.",
                    "command": "echo something-else",
                    "expected": "stdout contains `expected-literal`.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert any("expected-literal" in f for f in failed)

    def test_vp_replay_hermetic_step_passing_command_is_clean(self, tmp_path: Path) -> None:
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-pass",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a passing command.",
                    "command": "echo expected-literal",
                    "expected": "stdout contains `expected-literal`.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert failed == []

    def test_vp_replay_non_hermetic_and_post_deploy_steps_are_excluded_but_listed(self, tmp_path: Path, capsys) -> None:
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-excluded",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": False,
                    "action": "Non-hermetic pre-deploy step.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                },
                {
                    "step": 2,
                    "phase": "post-deploy",
                    "hermetic": True,
                    "action": "Hermetic but post-deploy step.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                },
                {
                    "step": 3,
                    "phase": "post-deploy",
                    "hermetic": False,
                    "action": "Non-hermetic post-deploy step -- phase disqualifies it regardless of hermetic marker.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                },
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        out = capsys.readouterr().out
        assert failed == []
        assert f"EXCLUDED: {rel}:1 (not-hermetic)" in out
        assert f"EXCLUDED: {rel}:2 (post-deploy)" in out
        assert f"EXCLUDED: {rel}:3 (post-deploy)" in out

    def test_vp_replay_timeout_path_reddens(self, tmp_path: Path) -> None:
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-timeout",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a command that hangs past the per-step timeout.",
                    "command": "sleep 5",
                    "expected": "Exit 0.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.PER_STEP_TIMEOUT_SECONDS", 0.1):
            validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert any("TIMEOUT" in f for f in failed)

    def test_vp_replay_load_error_path_is_skipped_with_note(self, tmp_path: Path, capsys) -> None:
        plans_dir = tmp_path / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / "PLAN-vpr-bad.yaml").write_text("not: [valid, plan, shape", encoding="utf-8")
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["docs/plans/PLAN-vpr-bad.yaml"], root=tmp_path)
        out = capsys.readouterr().out
        assert failed == []
        assert "SKIP" in out and "load error" in out

    def test_vp_replay_import_error_reddens_distinctly_from_content_error(self, tmp_path: Path) -> None:
        """A broken scripts.roadmap.plan_document import is an infra failure -- it must redden failed[],
        not be downgraded to a silent SKIP alongside routine content-validation errors."""
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-importerror",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Irrelevant -- load fails before any step runs.",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        with patch("scripts.roadmap.plan_document.load", side_effect=ImportError("broken plan_document")):
            validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert any("vp-replay" in f and "could not import" in f for f in failed)

    def test_vp_replay_aggregate_step_count_budget_guard(self, tmp_path: Path) -> None:
        steps = [
            {
                "step": i,
                "phase": "pre-deploy",
                "hermetic": True,
                "action": "quick pass",
                "command": "true",
                "expected": "n/a",
                "fix_if": "n/a",
            }
            for i in range(1, 5)
        ]
        rel = _write_vp_replay_plan(tmp_path, "vpr-budget", steps)
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.MAX_REPLAYED_STEPS", 2):
            validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        assert any("budget exceeded" in f for f in failed)

    def test_vp_replay_default_changed_files_falls_back_to_common_get_changed_files(self) -> None:
        """No changed_files arg -- falls back to _common.get_changed_files()."""
        failed: list[str] = []
        with patch("scripts.checks._common.get_changed_files", return_value=[]):
            validate_vp_replay(failed)
        assert failed == []
