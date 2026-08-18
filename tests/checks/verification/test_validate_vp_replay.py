"""Tests for validate_vp_replay() -- Interactive VP replay (T3.15 c2, VF-01). Mirror of
scripts/checks/verification/validate_vp_replay.py.

Content-keyed resolution (Decision 148/plan-resolution-content-keyed, mirrors
validate_graduation_completeness): TestPlanOnlyLeg exercises the DEFER path via the
changed_files/root injection seams. TestImplementLeg exercises the replay path against a
real git fixture whose plan resolves via `implementation_declared`. TestContentKeyedResolution
covers the defect this re-key closes (a checkpoint-only commit-message branch still resolves)
plus the single-harvested-declaration composition rule.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import yaml as _yaml

from scripts.checks import registry
from scripts.checks.verification.validate_vp_replay import validate_vp_replay


def _vp_replay_plan_dict(slug: str, verification_plan: list[dict], declared: bool = False) -> dict:
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
        "implementation_declared": declared,
    }


def _write_vp_replay_plan(root: Path, slug: str, verification_plan: list[dict], declared: bool = False) -> str:
    plans_dir = root / "docs" / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    rel = f"docs/plans/PLAN-{slug}.yaml"
    (plans_dir / f"PLAN-{slug}.yaml").write_text(
        _yaml.dump(_vp_replay_plan_dict(slug, verification_plan, declared)), encoding="utf-8"
    )
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


class _ResolvedFixture:
    """Shared repo builder: a base commit (origin/main), then a second commit declaring the
    plan's implementation_declared true -- the resolvable, replayable shape."""

    def build(self, tmp_path: Path, slug: str, verification_plan: list[dict], commit_message: str = "checkpoint") -> Path:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        rel = _write_vp_replay_plan(repo, slug, verification_plan, declared=True)
        _commit_all(repo, commit_message)
        return repo, rel


class TestPlanOnlyLeg:
    """A diff-present plan whose implementation_declared did not newly flip true DEFERs."""

    def test_no_plan_in_diff_is_noop_pass(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["scripts/foo.py"], root=tmp_path)
        assert failed == []

    def test_deleted_plan_path_is_skipped(self, tmp_path: Path) -> None:
        """A plan path present in changed_files but absent on disk (deleted in the diff) is a
        no-op, even though origin/main is unreachable here too (no git repo at tmp_path)."""
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=["docs/plans/PLAN-vpr-gone.yaml"], root=tmp_path)
        assert failed == []

    def test_undeclared_plan_defers_no_execution(self, tmp_path: Path, capsys) -> None:
        """A plan-only PR (plan in diff, implementation_declared false) defers -- the hermetic
        step's command ('exit 1') is never executed, so it never reddens failed[]."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        rel = _write_vp_replay_plan(
            repo,
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
            declared=False,
        )
        _commit_all(repo, "add undeclared plan")

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"DEFER: {rel}" in out
        assert "not newly true" in out

    def test_deleted_plan_path_is_skipped_with_reachable_base(self, tmp_path: Path, capsys) -> None:
        """A plan path in the diff but absent on disk (deleted in the diff) is a no-op even when
        origin/main IS reachable -- distinct from the unreachable-base DEFER-everything path."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_vp_replay_plan(repo, "vpr-real-then-gone", [], declared=True)
        _commit_all(repo, "add then delete")
        (repo / rel).unlink()
        _commit_all(repo, "delete plan")

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"SKIP: {rel} (not present on disk -- deleted in this diff)" in out

    def test_resolved_plan_hands_off_to_implement_leg(self, tmp_path: Path, capsys) -> None:
        """A resolved plan (implementation_declared newly true) is NOT deferred -- it is printed
        as handed off and actually replayed against the complete tree."""
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-resolved",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "Run a passing command.",
                    "command": "echo resolved-ran",
                    "expected": "stdout contains `resolved-ran`.",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"DEFER: {rel}" not in out
        assert f"PASS: {rel}:1 replayed" in out


class TestImplementLeg:
    def test_hermetic_step_failing_command_reddens(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
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
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("vp-replay" in f and "exit 1" in f for f in failed)

    def test_hermetic_step_missing_literal_reddens(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
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
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("expected-literal" in f for f in failed)

    def test_hermetic_step_passing_command_is_clean(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
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
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert failed == []

    def test_non_hermetic_and_post_deploy_steps_are_excluded_but_listed(self, tmp_path: Path, capsys) -> None:
        repo, rel = _ResolvedFixture().build(
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
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert f"EXCLUDED: {rel}:1 (not-hermetic)" in out
        assert f"EXCLUDED: {rel}:2 (post-deploy)" in out
        assert f"EXCLUDED: {rel}:3 (post-deploy)" in out

    def test_timeout_path_reddens(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
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
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("TIMEOUT" in f for f in failed)

    def test_load_error_path_is_skipped_with_note(self, tmp_path: Path, capsys) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        plans_dir = repo / "docs" / "plans"
        plans_dir.mkdir(parents=True)
        rel = "docs/plans/PLAN-vpr-bad.yaml"
        # Valid YAML (so the resolver's raw read succeeds and resolves it -- implementation_declared
        # is true), but not a valid PlanDocument (missing required fields) -- load_plan's schema
        # validation is what must skip this, not the resolver.
        (plans_dir / "PLAN-vpr-bad.yaml").write_text(
            _yaml.dump({"implementation_declared": True, "slug": "vpr-bad"}), encoding="utf-8"
        )
        _commit_all(repo, "checkpoint")

        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        out = capsys.readouterr().out
        assert failed == []
        assert "SKIP" in out and "load error" in out

    def test_import_error_reddens_distinctly_from_content_error(self, tmp_path: Path) -> None:
        """A broken scripts.roadmap.plan_document import is an infra failure -- it must redden failed[],
        not be downgraded to a silent SKIP alongside routine content-validation errors."""
        repo, rel = _ResolvedFixture().build(
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
            validate_vp_replay(failed, changed_files=[rel], root=repo)
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
        repo, rel = _ResolvedFixture().build(tmp_path, "vpr-budget", steps)
        failed: list[str] = []
        with patch("scripts.checks.verification.validate_vp_replay.MAX_REPLAYED_STEPS", 2):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("budget exceeded" in f for f in failed)

    def test_default_changed_files_falls_back_to_common_get_changed_files(self) -> None:
        """No changed_files arg -- falls back to _common.get_changed_files(). An empty diff means
        no plan paths at all, so the check no-ops without ever touching git state."""
        failed: list[str] = []
        with patch("scripts.checks._common.get_changed_files", return_value=[]):
            validate_vp_replay(failed)
        assert failed == []


class TestContentKeyedResolution:
    """The defect this re-key closes: a branch whose only content commit is an automated
    checkpoint (no feat({slug}) commit subject) still resolves and replays, because resolution
    is keyed off implementation_declared, not commit-message shape. Also covers the single
    terminal Decision 170 declaration composed once per dispatch."""

    def test_checkpoint_only_commit_message_branch_still_resolves(self, tmp_path: Path) -> None:
        """Red before this plan: a checkpoint-only branch with a declaration resolved nothing
        and no-opped (commit-subject resolution found no feat({slug}) subject). Green after:
        the hermetic step is genuinely replayed and reddens on a real failure."""
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-checkpoint-only",
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
            commit_message="chore: automated checkpoint",
        )
        failed: list[str] = []
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        assert any("vp-replay" in f and "exit 1" in f for f in failed)

    def test_declaration_enforced_when_a_plan_resolves(self, tmp_path: Path) -> None:
        repo, rel = _ResolvedFixture().build(
            tmp_path,
            "vpr-declared-enforced",
            [
                {
                    "step": 1,
                    "phase": "pre-deploy",
                    "hermetic": True,
                    "action": "pass",
                    "command": "true",
                    "expected": "n/a",
                    "fix_if": "n/a",
                }
            ],
        )
        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1
        assert declaration.unit == "declared_plans"

    def test_declaration_vacuous_when_plan_present_but_undeclared(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_vp_replay_plan(repo, "vpr-declared-vacuous", [], declared=False)
        _commit_all(repo, "add undeclared plan")

        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_declaration_vacuous_when_no_plan_in_diff(self) -> None:
        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=["scripts/foo.py"], root=Path("/nonexistent"))
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_declaration_skipped_when_base_unreachable(self, tmp_path: Path) -> None:
        rel = _write_vp_replay_plan(tmp_path, "vpr-declared-skipped", [], declared=False)

        failed: list[str] = []
        registry.pop_declaration()
        validate_vp_replay(failed, changed_files=[rel], root=tmp_path)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert failed == []


class TestRootScopedBase:
    """rec-3166 class: content-keyed plan resolution must read its base from the INJECTED
    `root`'s repository, never from `_common.ROOT` (patched to an unrelated DECOY repo in
    every test here). A plan already declared at the true base (steady state) must NOT
    spuriously re-resolve just because push context derived its base from the wrong repo."""

    def _build_steady_repo(self, tmp_path: Path, slug: str) -> tuple[Path, str, str]:
        """A repo whose plan is ALREADY declared at `before_sha` (steady state, no flip), then
        merged to main (`origin/main` pinned to HEAD, simulating post-merge main)."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        rel = _write_vp_replay_plan(repo, slug, [], declared=True)
        before_sha = _commit_all(repo, "base, already declared")
        (repo / "unrelated.txt").write_text("x\n", encoding="utf-8")
        after_sha = _commit_all(repo, "unrelated follow-up commit")
        _git(repo, ["update-ref", "refs/remotes/origin/main", after_sha])
        return repo, rel, before_sha

    def test_push_event_trigger_does_not_spuriously_reresolve(self, tmp_path: Path, monkeypatch) -> None:
        decoy = tmp_path / "decoy"
        _init_repo(decoy)
        (decoy / "d.txt").write_text("decoy\n", encoding="utf-8")
        _commit_all(decoy, "decoy first")
        (decoy / "d2.txt").write_text("decoy2\n", encoding="utf-8")
        _commit_all(decoy, "decoy second")

        repo, rel, before_sha = self._build_steady_repo(tmp_path, "vpr-root-scoped-push")

        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        monkeypatch.setenv("GITHUB_EVENT_BEFORE", before_sha)

        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks._common.ROOT", decoy):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0, "already-declared-at-base plan must not spuriously re-resolve"
        assert failed == []

    def test_on_main_trigger_does_not_spuriously_reresolve(self, tmp_path: Path) -> None:
        # The decoy must ALSO trigger push_context_base()'s on-main branch (own branch=="main"
        # AND merge-base(origin/main, HEAD)==HEAD) so the pre-fix bare call returns a WRONG but
        # non-None sha (absent from `repo`) instead of harmlessly falling through to None --
        # otherwise this test would pass even pre-fix, proving nothing.
        decoy = tmp_path / "decoy"
        decoy.mkdir()
        _git(decoy, ["init", "-q", "-b", "main"])
        _git(decoy, ["config", "user.email", "test@example.com"])
        _git(decoy, ["config", "user.name", "Test"])
        (decoy / "d.txt").write_text("decoy\n", encoding="utf-8")
        _commit_all(decoy, "decoy first")
        (decoy / "d2.txt").write_text("decoy2\n", encoding="utf-8")
        decoy_head = _commit_all(decoy, "decoy second")
        _git(decoy, ["update-ref", "refs/remotes/origin/main", decoy_head])

        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, ["init", "-q", "-b", "main"])
        _git(repo, ["config", "user.email", "test@example.com"])
        _git(repo, ["config", "user.name", "Test"])
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        rel = _write_vp_replay_plan(repo, "vpr-root-scoped-onmain", [], declared=True)
        _commit_all(repo, "base, already declared")
        (repo / "unrelated.txt").write_text("x\n", encoding="utf-8")
        after_sha = _commit_all(repo, "unrelated follow-up commit")
        _git(repo, ["update-ref", "refs/remotes/origin/main", after_sha])  # merge-base(origin/main, HEAD) == HEAD

        failed: list[str] = []
        registry.pop_declaration()
        with patch("scripts.checks._common.ROOT", decoy):
            validate_vp_replay(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0, "already-declared-at-base plan must not spuriously re-resolve"
        assert failed == []
