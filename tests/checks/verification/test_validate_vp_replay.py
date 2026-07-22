"""Tests for validate_vp_replay() -- Interactive VP replay (T3.15 c2, VF-01). Mirror of
scripts/checks/verification/validate_vp_replay.py.

Two-leg model (Decision 148, mirrors validate_graduation_completeness / Decision 132):
TestPlanOnlyPrLeg exercises the plan-only-PR leg via the changed_files/root injection seams
(no real git needed for the no-op/deleted-path cases; a git fixture proves the co-present
defer-skip). TestImplementPrLeg exercises the implement-PR leg, which resolves feat({slug})
commits via real `git log origin/main..HEAD` and replays against the complete tree -- mirroring
tests/checks/verification/test_validate_graduation_completeness.py's `_ImplementFixture`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml as _yaml

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


def _write_vp_replay_plan(root: Path, slug: str, verification_plan: list[dict]) -> str:
    plans_dir = root / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    rel = f"docs/plans/PLAN-{slug}.yaml"
    (plans_dir / f"PLAN-{slug}.yaml").write_text(_yaml.dump(_vp_replay_plan_dict(slug, verification_plan)), encoding="utf-8")
    return rel


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, ["init", "-q"])
    _git(repo, ["config", "user.email", "test@example.com"])
    _git(repo, ["config", "user.name", "Test"])


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-q", "-m", message])
    return _git(repo, ["rev-parse", "HEAD"]).stdout.strip()


class _ImplementFixture:
    """Shared repo builder for the implement-PR leg: a git repo with a feat({slug}) commit
    ahead of a refs/remotes/origin/main ref, plus the plan file."""

    def build(self, tmp_path: Path, slug: str, verification_plan: list[dict], plan_present: bool = True) -> Path:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        if plan_present:
            _write_vp_replay_plan(repo, slug, verification_plan)
        else:
            (repo / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, f"feat({slug}): implement fixture")
        return repo


class TestPlanOnlyPrLeg:
    """The plan-only-PR leg: no co-present feat({slug}) commit -> DEFER, never replays."""

    def test_no_plan_in_diff_is_noop_pass(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["scripts/foo.py"], root=tmp_path)
        assert failed == []

    def test_deleted_plan_path_is_skipped(self, tmp_path: Path) -> None:
        """A plan path present in changed_files but absent on disk (deleted in the diff) is a no-op."""
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["docs/plans/PLAN-vpr-gone.yaml"], root=tmp_path)
        assert failed == []

    def test_plan_only_pr_defers_no_execution(self, tmp_path: Path, capsys) -> None:
        """A plan-only PR (plan in diff, no feat({slug}) commit anywhere) defers -- the hermetic
        step's command ('exit 1') is never executed, so it never reddens failed[]."""
        rel = _write_vp_replay_plan(
            tmp_path,
            "vpr-plan-only",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a command that would fail if replayed.",
                    "command": "exit 1",
                    "expected": "Exit 0.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        out = capsys.readouterr().out
        assert failed == []
        assert f"DEFER: {rel}" in out
        assert "plan-only PR" in out

    def test_co_present_plan_and_code_defers_in_plan_leg_but_replays_in_implement_leg(self, tmp_path: Path, capsys) -> None:
        """A PR carrying BOTH the plan file (as a diff-added path) and its feat({slug}) commit
        is co-present: the plan-only-PR leg recognizes it and hands off (no DEFER), while the
        implement-PR leg actually replays the hermetic step against the complete tree."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        rel = _write_vp_replay_plan(
            repo,
            "vpr-co-present",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a passing command.",
                    "command": "echo co-present-ran",
                    "expected": "stdout contains `co-present-ran`.",
                    "fix_if": "n/a",
                }
            ],
        )
        _commit_all(repo, "feat(vpr-co-present): implement fixture")

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"DEFER: {rel}" not in out
        assert "co-present" in out
        assert f"PASS: {rel}:1 replayed" in out


class TestImplementPrLeg:
    fixture = _ImplementFixture()

    def test_hermetic_step_failing_command_reddens(self, tmp_path: Path) -> None:
        repo = self.fixture.build(
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
        validate_vp_replay(failed, changed_files=[], root=repo)
        assert any("vp-replay" in f and "exit 1" in f for f in failed)

    def test_hermetic_step_missing_literal_reddens(self, tmp_path: Path) -> None:
        repo = self.fixture.build(
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
        validate_vp_replay(failed, changed_files=[], root=repo)
        assert any("expected-literal" in f for f in failed)

    def test_hermetic_step_passing_command_is_clean(self, tmp_path: Path) -> None:
        repo = self.fixture.build(
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
        validate_vp_replay(failed, changed_files=[], root=repo)
        assert failed == []

    def test_non_hermetic_and_post_deploy_steps_are_excluded_but_listed(self, tmp_path: Path, capsys) -> None:
        repo = self.fixture.build(
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
        rel = "docs/plans/PLAN-vpr-excluded.yaml"
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"EXCLUDED: {rel}:1 (not-hermetic)" in out
        assert f"EXCLUDED: {rel}:2 (post-deploy)" in out
        assert f"EXCLUDED: {rel}:3 (post-deploy)" in out

    def test_timeout_path_reddens(self, tmp_path: Path) -> None:
        repo = self.fixture.build(
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
            validate_vp_replay(failed, changed_files=[], root=repo)
        assert any("TIMEOUT" in f for f in failed)

    def test_load_error_path_is_skipped_with_note(self, tmp_path: Path, capsys) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        plans_dir = repo / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        (plans_dir / "PLAN-vpr-bad.yaml").write_text("not: [valid, plan, shape", encoding="utf-8")
        _commit_all(repo, "feat(vpr-bad): implement fixture")

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert "SKIP" in out and "load error" in out

    def test_import_error_reddens_distinctly_from_content_error(self, tmp_path: Path) -> None:
        """A broken scripts.roadmap.plan_document import is an infra failure -- it must redden failed[],
        not be downgraded to a silent SKIP alongside routine content-validation errors."""
        repo = self.fixture.build(
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
            validate_vp_replay(failed, changed_files=[], root=repo)
        assert any("vp-replay" in f and "could not import" in f for f in failed)

    def test_aggregate_step_count_budget_guard(self, tmp_path: Path) -> None:
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
        repo = self.fixture.build(tmp_path, "vpr-budget", steps)
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.MAX_REPLAYED_STEPS", 2):
            validate_vp_replay(failed, changed_files=[], root=repo)
        assert any("budget exceeded" in f for f in failed)

    def test_unresolvable_plan_advisory_skips(self, tmp_path: Path) -> None:
        """A feat({slug}) commit naming a plan absent on disk (typo/archived/.md-era) never fails."""
        repo = self.fixture.build(tmp_path, "vpr-nonexistent-slug", [], plan_present=False)
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[], root=repo)
        assert failed == []

    def test_origin_main_unreachable_advisory_skips(self, tmp_path: Path) -> None:
        """No git repo at all (origin/main unreachable) never fails the implement-PR leg."""
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[], root=tmp_path)
        assert failed == []

    def test_no_feat_commits_is_noop_pass(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        (repo / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "docs: unrelated non-feat commit")

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[], root=repo)
        assert failed == []

    def test_default_changed_files_falls_back_to_common_get_changed_files(self) -> None:
        """No changed_files arg -- falls back to _common.get_changed_files(). Also stubs
        origin_main_reachable so the implement-PR leg (which ignores changed_files and reasons
        about real git state) doesn't reach into this session's live repo/branch state -- this
        test proves the injection seam wiring, not live-repo behaviour."""
        failed: list[str] = []
        with (
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch("scripts.checks._common.origin_main_reachable", return_value=False),
        ):
            validate_vp_replay(failed)
        assert failed == []
