"""Tests for validate_graduation_completeness() (T3.21, VF-05 enforcement).

TestPlanPrLeg exercises the plan-PR leg via the changed_files/root injection seams (no real
git needed for most cases; one net-new case uses a throwaway git repo, mirroring
tests/test_verification_graduation.py's `refs/remotes/origin/main` pattern). TestImplementPrLeg
and TestWaiver exercise the implement-PR leg, which resolves feat({slug}) commits via real
`git log origin/main..HEAD` and reads the registry baseline via the seamed
baseline_registry_reader (avoiding a second real-git fixture for registry content).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from scripts.checks.verification.validate_graduation_completeness import (
    validate_graduation_completeness,
)

_REGISTRY_REL = "config/agent/verification_registry/registry.yaml"


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


def _plan_dict(slug: str, steps: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "slug": slug,
        "intent": "Test fixture plan.",
        "plan_type": "IMPLEMENTATION",
        "verification_tier": "V2",
        "plan_path": f"docs/plans/PLAN-{slug}.yaml",
        "phase": "Test fixture -- no roadmap phase.",
        "scope": [{"file": "scripts/example.py", "action": "Create", "purpose": "Demo."}],
        "acceptance_criteria": ["Example acceptance criterion."],
        "verification_plan": steps,
        "execution_steps": ["Create scripts/example.py."],
    }


def _write_plan(root: Path, slug: str, steps: list[dict]) -> str:
    rel = f"docs/plans/PLAN-{slug}.yaml"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(_plan_dict(slug, steps), sort_keys=False), encoding="utf-8")
    return rel


def _step(step: int, phase: str = "pre-deploy", **overrides) -> dict:
    base = {
        "step": step,
        "phase": phase,
        "action": "do something",
        "command": "echo ok",
        "expected": "prints ok",
        "fix_if": "never fails in practice",
    }
    base.update(overrides)
    return base


def _write_registry(root: Path, entries: list[dict]) -> None:
    path = root / _REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"entries": entries}, sort_keys=False), encoding="utf-8")


class TestPlanPrLeg:
    def test_missing_disposition_fails(self, tmp_path: Path) -> None:
        rel = _write_plan(
            tmp_path,
            "gc-missing",
            [
                _step(1, graduation="waive", graduation_waiver_reason="needs live infra"),
                _step(2),  # no disposition -- has_any_disposition=True bypasses the pre-field skip
            ],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        assert any("lack a graduation disposition" in f and "[2]" in f for f in failed)

    def test_all_dispositions_present_passes(self, tmp_path: Path) -> None:
        rel = _write_plan(
            tmp_path,
            "gc-complete",
            [
                _step(1, graduation="graduate", graduation_check_id="gc-complete-check"),
                _step(2, graduation="not-applicable"),
            ],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        assert failed == []

    def test_historical_plan_not_in_diff_is_untouched(self, tmp_path: Path) -> None:
        _write_plan(tmp_path, "gc-historical", [_step(1)])
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=["scripts/unrelated.py"], root=tmp_path)
        assert failed == []

    def test_merely_modified_pre_field_plan_is_skipped(self, tmp_path: Path) -> None:
        """Zero dispositions anywhere + not net-new (no git repo -> never 'added') is skipped, not failed."""
        rel = _write_plan(tmp_path, "gc-pre-field", [_step(1), _step(2)])
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        assert failed == []

    def test_net_new_plan_with_zero_dispositions_fails(self, tmp_path: Path) -> None:
        """A genuinely net-new plan (git diff --diff-filter=A) is enforced even with zero dispositions."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        rel = _write_plan(repo, "gc-net-new", [_step(1), _step(2)])
        _commit_all(repo, "add plan")

        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo)
        assert any("lack a graduation disposition" in f for f in failed)

    def test_deleted_plan_path_is_skipped(self, tmp_path: Path) -> None:
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=["docs/plans/PLAN-gc-gone.yaml"], root=tmp_path)
        assert failed == []

    def test_no_pre_deploy_steps_passes(self, tmp_path: Path) -> None:
        rel = _write_plan(tmp_path, "gc-post-only", [_step(1, phase="post-deploy")])
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        assert failed == []


class _ImplementFixture:
    """Shared repo builder for the implement-PR leg: a git repo with a feat({slug}) commit
    ahead of a refs/remotes/origin/main ref, plus the plan file and registry state."""

    def build(self, tmp_path: Path, slug: str, steps: list[dict], registry_entries: list[dict] | None = None) -> Path:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        _write_plan(repo, slug, steps)
        if registry_entries is not None:
            _write_registry(repo, registry_entries)
        _commit_all(repo, f"feat({slug}): implement fixture")
        return repo


class TestImplementPrLeg:
    fixture = _ImplementFixture()

    def test_graduate_step_missing_row_fails(self, tmp_path: Path) -> None:
        repo = self.fixture.build(
            tmp_path,
            "gc-impl-missing",
            [_step(1, graduation="graduate", graduation_check_id="gc-impl-missing-check")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[], root=repo, baseline_registry_reader=lambda r: [])
        assert any("no matching new-in-diff registry row" in f for f in failed)

    def test_graduate_step_with_matching_row_passes(self, tmp_path: Path) -> None:
        cid = "gc-impl-present-check"
        slug = "gc-impl-present"
        repo = self.fixture.build(
            tmp_path,
            slug,
            [_step(1, graduation="graduate", graduation_check_id=cid)],
            registry_entries=[
                {
                    "check_id": cid,
                    "primitive_slot": "command_exit_zero",
                    "guard_target": "scripts/example.py",
                    "plan_slug": slug,
                    "graduated_at": "2026-07-16",
                }
            ],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_flip_to_waive_passes_with_no_row(self, tmp_path: Path) -> None:
        repo = self.fixture.build(
            tmp_path,
            "gc-impl-waived",
            [_step(1, graduation="waive", graduation_waiver_reason="proved un-graduatable at implement time")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_unresolvable_plan_advisory_skips(self, tmp_path: Path) -> None:
        """A feat({slug}) commit naming a plan absent on disk (typo/archived/.md-era) never fails."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        (repo / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "feat(gc-nonexistent-slug): code with no matching plan file")

        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_origin_main_unreachable_advisory_skips(self, tmp_path: Path) -> None:
        """No git repo at all (origin/main unreachable) never fails the implement-PR leg."""
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[], root=tmp_path)
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
        validate_graduation_completeness(failed, changed_files=[], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []


class TestWaiver:
    fixture = _ImplementFixture()

    def test_waive_with_reason_requires_no_registry_row(self, tmp_path: Path) -> None:
        repo = self.fixture.build(
            tmp_path,
            "gc-waiver-only",
            [_step(1, graduation="waive", graduation_waiver_reason="requires live infra, not kernel-expressible")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_not_applicable_requires_no_registry_row(self, tmp_path: Path) -> None:
        repo = self.fixture.build(
            tmp_path,
            "gc-not-applicable-only",
            [_step(1, graduation="not-applicable")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []
