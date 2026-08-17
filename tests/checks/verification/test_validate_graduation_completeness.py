"""Tests for validate_graduation_completeness() (T3.21, VF-05 enforcement, re-keyed to content
resolution -- Decision 148/plan-resolution-content-keyed).

TestPlanPrLeg exercises the plan-PR leg via the changed_files/root injection seams (no real
git needed for most cases; one net-new case uses a throwaway git repo, mirroring
tests/test_verification_graduation.py's `refs/remotes/origin/main` pattern). TestImplementPrLeg,
TestWaiver, and TestContentKeyedResolution exercise the implement leg, which resolves plans via
`_common.resolve_declared_plans` (implementation_declared, content-keyed) and reads the registry
baseline via the seamed baseline_registry_reader (avoiding a second real-git fixture for registry
content).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.checks import registry
from scripts.checks.verification.validate_graduation_completeness import (
    _current_registry_entries,
    _default_baseline_registry_entries,
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


def _plan_dict(slug: str, steps: list[dict], overrides: dict | None = None) -> dict:
    plan = {
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
    plan.update(overrides or {})
    return plan


def _write_plan(root: Path, slug: str, steps: list[dict], overrides: dict | None = None) -> str:
    rel = f"docs/plans/PLAN-{slug}.yaml"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(_plan_dict(slug, steps, overrides), sort_keys=False), encoding="utf-8")
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
    """Shared repo builder for the implement leg: a git repo with a base commit (origin/main)
    then a second commit that DECLARES the plan (implementation_declared: true) -- the
    resolvable, content-keyed shape. Registry state is written alongside."""

    def build(
        self,
        tmp_path: Path,
        slug: str,
        steps: list[dict],
        registry_entries: list[dict] | None = None,
        plan_overrides: dict | None = None,
        commit_message: str = "checkpoint",
    ) -> tuple[Path, str]:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])

        overrides = {"implementation_declared": True}
        overrides.update(plan_overrides or {})
        rel = _write_plan(repo, slug, steps, overrides)
        if registry_entries is not None:
            _write_registry(repo, registry_entries)
        _commit_all(repo, commit_message)
        return repo, rel


class TestImplementPrLeg:
    fixture = _ImplementFixture()

    def test_graduate_step_missing_row_fails(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-impl-missing",
            [_step(1, graduation="graduate", graduation_check_id="gc-impl-missing-check")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert any("no matching new-in-diff registry row" in f for f in failed)

    def test_graduate_step_with_matching_row_passes(self, tmp_path: Path) -> None:
        cid = "gc-impl-present-check"
        slug = "gc-impl-present"
        repo, rel = self.fixture.build(
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
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_flip_to_waive_passes_with_no_row(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-impl-waived",
            [_step(1, graduation="waive", graduation_waiver_reason="proved un-graduatable at implement time")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_undeclared_plan_is_noop_pass(self, tmp_path: Path) -> None:
        """A plan in the diff whose implementation_declared is false resolves nothing -- the
        implement leg no-ops (plan-only PR, not yet implemented)."""
        rel = _write_plan(
            tmp_path, "gc-undeclared", [_step(1, graduation="graduate", graduation_check_id="gc-undeclared-check")]
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_origin_main_unreachable_advisory_skips(self, tmp_path: Path, capsys) -> None:
        """No git repo at all (origin/main unreachable) never fails the implement leg."""
        rel = _write_plan(tmp_path, "gc-unreachable", [_step(1)])
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        assert failed == []
        assert "SKIP (implement-PR leg)" in capsys.readouterr().out

    def test_no_plan_in_diff_is_noop_pass(self) -> None:
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=["scripts/unrelated.py"], root=Path("/nonexistent"))
        assert failed == []


class TestWaiver:
    fixture = _ImplementFixture()

    def test_waive_with_reason_requires_no_registry_row(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-waiver-only",
            [_step(1, graduation="waive", graduation_waiver_reason="requires live infra, not kernel-expressible")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []

    def test_not_applicable_requires_no_registry_row(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-not-applicable-only",
            [_step(1, graduation="not-applicable")],
            registry_entries=[],
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert failed == []


class TestObligationAwareDiagnostics:
    """Schema-v4 obligations reuse the existing (plan_slug, check_id) linkage -- the only
    addition is naming which declared behaviors lose their guard when the row is missing."""

    fixture = _ImplementFixture()
    _SELECTOR = "tests/test_example.py::test_behavior"

    def _overrides(self, sources: list[str]) -> dict:
        return {
            "schema_version": 4,
            "handoff_policy": {"full_validation_required_before_commit": True, "timeout_disposition": "blocked"},
            "test_obligations": [
                {
                    "source": source,
                    "behavior": "stays guarded by the graduated check",
                    "test_selector": self._SELECTOR,
                    "verification_step": 1,
                    "red_green_expectation": "fails before the change and passes after it",
                }
                for source in sources
            ],
        }

    def _steps(self) -> list[dict]:
        return [
            _step(
                1,
                command=f"bin/venv-python -m pytest {self._SELECTOR}",
                graduation="graduate",
                graduation_check_id="gc-obligation-check",
            )
        ]

    def test_missing_row_names_the_obligation_sources_losing_their_guard(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-obligation-named",
            self._steps(),
            registry_entries=[],
            plan_overrides=self._overrides(["scripts/example.py", "scripts/other.py"]),
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert any("test obligation(s) losing their guard: scripts/example.py, scripts/other.py" in f for f in failed)

    def test_missing_row_without_obligations_keeps_the_original_diagnostic(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-obligation-absent",
            self._steps(),
            registry_entries=[],
            plan_overrides=self._overrides([]),
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert any("no matching new-in-diff registry row" in f for f in failed)
        assert not any("losing their guard" in f for f in failed)


class TestLoadErrorHandling:
    """A schema-invalid plan is validate_plan_documents' verdict to report, not this check's;
    an import failure is a genuine error and stays fail-loud (Decision 55)."""

    fixture = _ImplementFixture()

    @staticmethod
    def _raiser(exc: Exception):
        def _loader(plan_rel: str, root: Path) -> object:
            raise exc

        return _loader

    def test_plan_leg_import_error_is_fail_loud(self, tmp_path: Path) -> None:
        rel = _write_plan(tmp_path, "gc-plan-import", [_step(1)])
        failed: list[str] = []
        validate_graduation_completeness(
            failed, changed_files=[rel], root=tmp_path, load_plan=self._raiser(ImportError("no module"))
        )
        assert any("could not import scripts.roadmap.plan_document" in f for f in failed)

    def test_plan_leg_schema_error_skips_without_double_reporting(self, tmp_path: Path, capsys) -> None:
        rel = _write_plan(tmp_path, "gc-plan-schema", [_step(1)])
        failed: list[str] = []
        validate_graduation_completeness(
            failed, changed_files=[rel], root=tmp_path, load_plan=self._raiser(ValueError("bad schema"))
        )
        assert failed == []
        assert "SKIP (plan-PR leg)" in capsys.readouterr().out

    def test_implement_leg_import_error_is_fail_loud(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(tmp_path, "gc-impl-import", [_step(1)], registry_entries=[])
        failed: list[str] = []
        validate_graduation_completeness(
            failed,
            changed_files=[rel],
            root=repo,
            load_plan=self._raiser(ImportError("no module")),
            baseline_registry_reader=lambda r: [],
        )
        assert any("could not import scripts.roadmap.plan_document" in f for f in failed)

    def test_implement_leg_schema_error_skips_without_double_reporting(self, tmp_path: Path, capsys) -> None:
        repo, rel = self.fixture.build(tmp_path, "gc-impl-schema", [_step(1)], registry_entries=[])
        failed: list[str] = []
        validate_graduation_completeness(
            failed,
            changed_files=[rel],
            root=repo,
            load_plan=self._raiser(ValueError("bad schema")),
            baseline_registry_reader=lambda r: [],
        )
        assert failed == []
        assert "SKIP (implement-PR leg)" in capsys.readouterr().out


_MALFORMED_REGISTRIES = ["{", "- not a mapping\n", "entries: 5\n"]


class TestRegistryReaders:
    """Both readers degrade to an empty list rather than raising -- a missing or malformed
    registry must not wedge the check, it must simply contribute no baseline rows."""

    def test_current_entries_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert _current_registry_entries(tmp_path) == []

    @pytest.mark.parametrize("body", _MALFORMED_REGISTRIES)
    def test_current_entries_malformed_is_empty(self, tmp_path: Path, body: str) -> None:
        path = tmp_path / _REGISTRY_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        assert _current_registry_entries(tmp_path) == []

    def test_baseline_without_origin_main_is_empty(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        _commit_all(repo, "base")
        assert _default_baseline_registry_entries(repo) == []

    def test_baseline_reads_entries_from_origin_main(self, tmp_path: Path) -> None:
        repo = self._repo_with_baseline(tmp_path, yaml.safe_dump({"entries": [{"check_id": "baseline-row"}]}))
        assert _default_baseline_registry_entries(repo) == [{"check_id": "baseline-row"}]

    def test_baseline_reads_entries_from_injected_base(self, tmp_path: Path) -> None:
        """The base is an injected parameter, not hardcoded -- a non-'origin/main' ref works too."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        path = repo / _REGISTRY_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"entries": [{"check_id": "tagged-row"}]}), encoding="utf-8")
        sha = _commit_all(repo, "base")
        _git(repo, ["tag", "custom-base", sha])
        assert _default_baseline_registry_entries(repo, base="custom-base") == [{"check_id": "tagged-row"}]

    @pytest.mark.parametrize("body", _MALFORMED_REGISTRIES)
    def test_malformed_baseline_is_empty(self, tmp_path: Path, body: str) -> None:
        assert _default_baseline_registry_entries(self._repo_with_baseline(tmp_path, body)) == []

    @staticmethod
    def _repo_with_baseline(tmp_path: Path, body: str) -> Path:
        repo = tmp_path / "repo"
        _init_repo(repo)
        path = repo / _REGISTRY_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", sha])
        return repo


class TestContentKeyedResolution:
    """The defect this re-key closes: a checkpoint-only commit-message branch still resolves for
    the implement leg (resolution is content-keyed, not commit-message-keyed). Also covers the
    single terminal Decision 170 declaration and the push-aware registry baseline."""

    fixture = _ImplementFixture()

    def test_checkpoint_only_commit_message_still_resolves_for_implement_leg(self, tmp_path: Path) -> None:
        """Red before this plan: a checkpoint-only branch with a declaration resolved nothing
        and no-opped (commit-subject resolution found no feat({slug}) subject). Green after:
        the missing registry row is genuinely detected."""
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-checkpoint-only",
            [_step(1, graduation="graduate", graduation_check_id="gc-checkpoint-only-check")],
            registry_entries=[],
            commit_message="chore: automated checkpoint",
        )
        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
        assert any("no matching new-in-diff registry row" in f for f in failed)

    def test_declaration_enforced_when_a_plan_resolves(self, tmp_path: Path) -> None:
        repo, rel = self.fixture.build(
            tmp_path,
            "gc-declared-enforced",
            [_step(1, graduation="not-applicable")],
            registry_entries=[],
        )
        failed: list[str] = []
        registry.pop_declaration()
        validate_graduation_completeness(failed, changed_files=[rel], root=repo, baseline_registry_reader=lambda r: [])
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
        rel = _write_plan(repo, "gc-declared-vacuous", [_step(1)])
        _commit_all(repo, "add undeclared plan")

        failed: list[str] = []
        registry.pop_declaration()
        validate_graduation_completeness(failed, changed_files=[rel], root=repo)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_declaration_vacuous_when_no_plan_in_diff(self) -> None:
        failed: list[str] = []
        registry.pop_declaration()
        validate_graduation_completeness(failed, changed_files=["scripts/foo.py"], root=Path("/nonexistent"))
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_declaration_skipped_when_base_unreachable(self, tmp_path: Path) -> None:
        rel = _write_plan(tmp_path, "gc-declared-skipped", [_step(1)])
        failed: list[str] = []
        registry.pop_declaration()
        validate_graduation_completeness(failed, changed_files=[rel], root=tmp_path)
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"
        assert failed == []

    def test_registry_baseline_and_resolution_stay_correct_on_simulated_post_merge_main(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Both diff baselines must be push-aware, not hardcoded to "origin/main" (Decision 159
        class): origin/main is pinned to HEAD here (simulating post-merge main) while
        GITHUB_EVENT_BEFORE names the true pre-merge commit; a hardcoded baseline would equal
        HEAD and falsely report the registry row missing."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        before_sha = _commit_all(repo, "before merge")

        slug = "gc-post-merge-main"
        cid = "gc-post-merge-main-check"
        rel = _write_plan(
            repo,
            slug,
            [_step(1, graduation="graduate", graduation_check_id=cid)],
            {"implementation_declared": True},
        )
        _write_registry(
            repo,
            [
                {
                    "check_id": cid,
                    "primitive_slot": "command_exit_zero",
                    "guard_target": "scripts/example.py",
                    "plan_slug": slug,
                    "graduated_at": "2026-08-17",
                }
            ],
        )
        after_sha = _commit_all(repo, "feature merged to main")
        _git(repo, ["update-ref", "refs/remotes/origin/main", after_sha])  # origin/main == HEAD

        monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
        monkeypatch.setenv("GITHUB_EVENT_BEFORE", before_sha)

        failed: list[str] = []
        validate_graduation_completeness(failed, changed_files=[rel], root=repo)
        assert failed == []
