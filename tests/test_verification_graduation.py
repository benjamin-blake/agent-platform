"""Tests for scripts/verification_graduation.py (VF-05/VF-06, audit-remediation-wave-4).

Covers: the materializer, the KERNEL differential (a real git worktree revert against
origin/main on a synthetic repo -- tautological entry rejected, genuine entry admitted),
the VERIFIER differential (synthetic new hermetic verifier -- tautological rejected,
genuine admitted; non-hermetic advisory-skipped), and fail-loud-on-error assertions.
"""

from __future__ import annotations

import json
import runpy
import shutil
import subprocess
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from scripts import verification_graduation as vg
from scripts.verification_checks import CheckStatus

# Files a synthetic tree needs so a subprocess re-invoking
# `python -m scripts.verification_graduation --run-verifier ...` in that tree's cwd can resolve
# its own import chain (the real repo always carries this closure at HEAD; a fixture repo must
# replicate it explicitly).
_GRADUATION_DEPS = (
    "scripts/verification_graduation.py",
    "scripts/verification_checks.py",
    "scripts/checks/__init__.py",
    "scripts/checks/_common.py",
    "scripts/checks/registry.py",
    "scripts/checks/verification/__init__.py",
    "scripts/checks/verification/validate_verifier_hermeticity.py",
)


def _seed_graduation_deps(repo: Path) -> None:
    for rel in _GRADUATION_DEPS:
        src = vg.ROOT / rel
        dst = repo / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _git(repo: Path, args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    _git(repo, ["init", "-q"])
    _git(repo, ["config", "user.email", "test@example.com"])
    _git(repo, ["config", "user.name", "Test"])


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, ["add", "-A"])
    _git(repo, ["commit", "-q", "-m", message])
    return _git(repo, ["rev-parse", "HEAD"]).stdout.strip()


# ---------------------------------------------------------------------------
# TestMaterializeCheck
# ---------------------------------------------------------------------------


class TestMaterializeCheck:
    def test_grep_count_materializes_and_matches_live_run(self, tmp_path: Path) -> None:
        target = tmp_path / "target.txt"
        target.write_text("sentinel line\nother line\n", encoding="utf-8")
        row = {
            "check_id": "t-grep",
            "primitive_slot": "grep_count",
            "check_spec": {"path": "target.txt", "pattern": "sentinel", "operator": "eq", "count": 1},
        }
        check = vg.materialize_check_in_tree(row, tmp_path)
        result = check.run()
        assert result.status == CheckStatus.PASS

    def test_file_presence_exists_mode(self, tmp_path: Path) -> None:
        (tmp_path / "present.txt").write_text("x", encoding="utf-8")
        row = {"check_id": "t-fp", "primitive_slot": "file_presence", "check_spec": {"path": "present.txt", "mode": "exists"}}
        check = vg.materialize_check_in_tree(row, tmp_path)
        assert check.run().status == CheckStatus.PASS

    def test_file_presence_absent_mode(self, tmp_path: Path) -> None:
        row = {"check_id": "t-fa", "primitive_slot": "file_presence", "check_spec": {"path": "missing.txt", "mode": "absent"}}
        check = vg.materialize_check_in_tree(row, tmp_path)
        assert check.run().status == CheckStatus.PASS

    def test_command_exit_zero_materializes(self, tmp_path: Path) -> None:
        row = {"check_id": "t-cmd", "primitive_slot": "command_exit_zero", "check_spec": {"command": ["true"]}}
        check = vg.materialize_check_in_tree(row, tmp_path)
        assert check.run().status == CheckStatus.PASS

    def test_command_output_matches_materializes(self, tmp_path: Path) -> None:
        row = {
            "check_id": "t-com",
            "primitive_slot": "command_output_matches",
            "check_spec": {"command": ["echo", "hello"], "expected": "hello", "use_regex": False},
        }
        check = vg.materialize_check_in_tree(row, tmp_path)
        assert check.run().status == CheckStatus.PASS

    def test_test_selector_materializes(self, tmp_path: Path) -> None:
        row = {
            "check_id": "t-sel",
            "primitive_slot": "test_selector",
            "check_spec": {"node_id": "tests/test_fake.py::T::test_y"},
        }
        check = vg.materialize_check_in_tree(row, tmp_path)
        with mock.patch(
            "scripts.verification_checks.subprocess.run",
            return_value=mock.Mock(returncode=0, stdout="1 passed", stderr=""),
        ):
            result = check.run()
        assert result.status == CheckStatus.PASS

    def test_metric_under_threshold_materializes(self, tmp_path: Path) -> None:
        row = {
            "check_id": "t-metric",
            "primitive_slot": "metric_under_threshold",
            "check_spec": {"command": ["echo", "0.5"], "threshold": 1.0},
        }
        check = vg.materialize_check_in_tree(row, tmp_path)
        assert check.run().status == CheckStatus.PASS

    def test_materialize_check_uses_live_tree_when_no_repoint(self, tmp_path: Path) -> None:
        (tmp_path / "f.txt").write_text("marker\n", encoding="utf-8")
        row = {
            "check_id": "t-live",
            "primitive_slot": "grep_count",
            "check_spec": {"path": str(tmp_path / "f.txt"), "pattern": "marker", "operator": "eq", "count": 1},
        }
        check = vg.materialize_check(row)
        assert check.run().status == CheckStatus.PASS

    def test_unknown_slot_raises(self) -> None:
        row = {"check_id": "t-bad", "primitive_slot": "not_a_slot", "check_spec": {}}
        with pytest.raises(vg.GraduationError, match="unknown primitive_slot"):
            vg.materialize_check(row)

    def test_missing_required_key_raises(self) -> None:
        row = {"check_id": "t-missing", "primitive_slot": "grep_count", "check_spec": {"path": "x"}}
        with pytest.raises(vg.GraduationError, match="missing required key"):
            vg.materialize_check(row)

    def test_bad_file_presence_mode_raises(self, tmp_path: Path) -> None:
        row = {"check_id": "t-mode", "primitive_slot": "file_presence", "check_spec": {"path": "x", "mode": "bogus"}}
        with pytest.raises(vg.GraduationError, match="mode must be"):
            vg.materialize_check_in_tree(row, tmp_path)


# ---------------------------------------------------------------------------
# TestKernelDifferential (c2) -- real git worktree revert on a synthetic repo
# ---------------------------------------------------------------------------


class TestKernelDifferential:
    def _build_repo(self, tmp_path: Path, base_has_sentinel: bool) -> Path:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "target.txt").write_text("sentinel\n" if base_has_sentinel else "nothing here\n", encoding="utf-8")
        (repo / "note.txt").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        (repo / "target.txt").write_text("sentinel\n", encoding="utf-8")
        (repo / "note.txt").write_text("head\n", encoding="utf-8")
        _commit_all(repo, "head")
        return repo

    def test_genuine_entry_is_admitted(self, tmp_path: Path) -> None:
        """origin/main lacks the sentinel (FAIL); HEAD/live has it (PASS) -> admitted."""
        repo = self._build_repo(tmp_path, base_has_sentinel=False)
        row = {
            "check_id": "genuine",
            "primitive_slot": "grep_count",
            "check_spec": {"path": "target.txt", "pattern": "sentinel", "operator": "eq", "count": 1},
        }
        outcome = vg.run_differential(row, repo_root=repo)
        assert outcome.admitted, outcome.reason

    def test_tautological_entry_is_rejected(self, tmp_path: Path) -> None:
        """origin/main ALSO has the sentinel -- passes on both trees -> rejected, not admitted."""
        repo = self._build_repo(tmp_path, base_has_sentinel=True)
        row = {
            "check_id": "tautological",
            "primitive_slot": "grep_count",
            "check_spec": {"path": "target.txt", "pattern": "sentinel", "operator": "eq", "count": 1},
        }
        outcome = vg.run_differential(row, repo_root=repo)
        assert not outcome.admitted
        assert "not admitted" in outcome.reason

    def test_check_failing_on_head_is_not_admitted(self, tmp_path: Path) -> None:
        repo = self._build_repo(tmp_path, base_has_sentinel=False)
        row = {
            "check_id": "wrong-pattern",
            "primitive_slot": "grep_count",
            "check_spec": {"path": "target.txt", "pattern": "does-not-exist-anywhere", "operator": "eq", "count": 1},
        }
        outcome = vg.run_differential(row, repo_root=repo)
        assert not outcome.admitted
        assert "does not pass on HEAD" in outcome.reason

    def test_worktree_revert_is_real_not_simulated(self, tmp_path: Path) -> None:
        """The revert_runner actually checks out origin/main via `git worktree add` (no CheckResult stubbing)."""
        repo = self._build_repo(tmp_path, base_has_sentinel=False)
        row = {
            "check_id": "real-worktree",
            "primitive_slot": "file_presence",
            "check_spec": {"path": "only-on-head.txt", "mode": "exists"},
        }
        (repo / "only-on-head.txt").write_text("x", encoding="utf-8")
        _commit_all(repo, "add head-only file")
        outcome = vg.run_differential(row, repo_root=repo)
        assert outcome.admitted, outcome.reason

    def test_materialize_error_during_differential_raises(self, tmp_path: Path) -> None:
        repo = self._build_repo(tmp_path, base_has_sentinel=False)
        row = {"check_id": "bad-slot", "primitive_slot": "not_a_real_slot", "check_spec": {}}
        with pytest.raises(vg.GraduationError):
            vg.run_differential(row, repo_root=repo)

    def test_worktree_add_failure_raises(self, tmp_path: Path) -> None:
        """A bogus ref (no origin/main configured) surfaces as GraduationError, not a silent skip."""
        repo = tmp_path / "not-a-repo"
        repo.mkdir()
        row = {
            "check_id": "no-repo",
            "primitive_slot": "file_presence",
            "check_spec": {"path": "x.txt", "mode": "absent"},
        }
        with pytest.raises(vg.GraduationError, match="git worktree add failed"):
            vg.run_differential(row, repo_root=repo)


# ---------------------------------------------------------------------------
# TestVerifierDifferential (c3) -- synthetic new verifier files
# ---------------------------------------------------------------------------

_HERMETIC_GENUINE_VERIFIER = """\
from scripts.verifiers.harness import Verifier, VerifierResult, VerifierStatus


class NewVerifier(Verifier):
    covers = ["covered.txt"]

    async def verify(self) -> VerifierResult:
        from pathlib import Path
        text = Path("covered.txt").read_text(encoding="utf-8")
        status = VerifierStatus.PASS if "expected-marker" in text else VerifierStatus.FAIL
        return VerifierResult(name=self.name, status=status)
"""

_HERMETIC_TAUTOLOGICAL_VERIFIER = """\
from scripts.verifiers.harness import Verifier, VerifierResult, VerifierStatus


class NewVerifier(Verifier):
    covers = ["covered.txt"]

    async def verify(self) -> VerifierResult:
        return VerifierResult(name=self.name, status=VerifierStatus.PASS)
"""

_NON_HERMETIC_VERIFIER = """\
from scripts.verifiers.harness import Hermeticity, Verifier, VerifierResult, VerifierStatus


class NewVerifier(Verifier):
    covers = ["covered.txt"]
    hermeticity = Hermeticity.NON_HERMETIC_BY_CONSTRUCTION

    async def verify(self) -> VerifierResult:
        return VerifierResult(name=self.name, status=VerifierStatus.PASS)
"""

_HERMETIC_ALWAYS_FAILS_VERIFIER = """\
from scripts.verifiers.harness import Verifier, VerifierResult, VerifierStatus


class NewVerifier(Verifier):
    covers = ["covered.txt"]

    async def verify(self) -> VerifierResult:
        return VerifierResult(name=self.name, status=VerifierStatus.FAIL)
"""


class TestVerifierDifferential:
    def _build_repo_with_verifier(self, tmp_path: Path, verifier_source: str) -> Path:
        """A synthetic repo with a real scripts/verifiers/harness.py copy (imported at run time)
        plus a brand-new scripts/verifiers/new_verifier.py and its covered file, at HEAD.
        origin/main is set to the base commit, which lacks the new verifier entirely (this
        models the "verifier does not exist on origin/main" c3 scenario).
        """
        real_root = vg.ROOT
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "__init__.py").write_text("", encoding="utf-8")
        (repo / "scripts" / "verifiers").mkdir()
        (repo / "scripts" / "verifiers" / "__init__.py").write_text("", encoding="utf-8")
        harness_src = (real_root / "scripts" / "verifiers" / "harness.py").read_text(encoding="utf-8")
        (repo / "scripts" / "verifiers" / "harness.py").write_text(harness_src, encoding="utf-8")
        _seed_graduation_deps(repo)
        (repo / "covered.txt").write_text("not yet marked\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base (no new verifier, no marker)")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        (repo / "scripts" / "verifiers" / "new_verifier.py").write_text(verifier_source, encoding="utf-8")
        (repo / "covered.txt").write_text("expected-marker\n", encoding="utf-8")
        _commit_all(repo, "head: add new verifier + its covered change")
        return repo

    def test_genuine_hermetic_verifier_is_admitted(self, tmp_path: Path) -> None:
        repo = self._build_repo_with_verifier(tmp_path, _HERMETIC_GENUINE_VERIFIER)
        outcome = vg.run_verifier_differential(
            "scripts/verifiers/new_verifier.py", "NewVerifier", ["covered.txt"], repo_root=repo
        )
        assert outcome.admitted and not outcome.skipped, outcome.reason

    def test_tautological_hermetic_verifier_is_rejected(self, tmp_path: Path) -> None:
        repo = self._build_repo_with_verifier(tmp_path, _HERMETIC_TAUTOLOGICAL_VERIFIER)
        outcome = vg.run_verifier_differential(
            "scripts/verifiers/new_verifier.py", "NewVerifier", ["covered.txt"], repo_root=repo
        )
        assert not outcome.admitted and not outcome.skipped
        assert "passes even with its covered change reverted" in outcome.reason

    def test_non_hermetic_verifier_is_advisory_skipped(self, tmp_path: Path) -> None:
        repo = self._build_repo_with_verifier(tmp_path, _NON_HERMETIC_VERIFIER)
        outcome = vg.run_verifier_differential(
            "scripts/verifiers/new_verifier.py", "NewVerifier", ["covered.txt"], repo_root=repo
        )
        assert outcome.skipped
        assert not outcome.admitted
        assert "NON_HERMETIC_BY_CONSTRUCTION" in outcome.reason

    def test_missing_verifier_file_raises(self, tmp_path: Path) -> None:
        repo = self._build_repo_with_verifier(tmp_path, _HERMETIC_GENUINE_VERIFIER)
        with pytest.raises(vg.GraduationError, match="cannot parse verifier file"):
            vg.run_verifier_differential("scripts/verifiers/does_not_exist.py", "NewVerifier", ["covered.txt"], repo_root=repo)

    def test_missing_class_raises(self, tmp_path: Path) -> None:
        repo = self._build_repo_with_verifier(tmp_path, _HERMETIC_GENUINE_VERIFIER)
        with pytest.raises(vg.GraduationError, match="not found"):
            vg.run_verifier_differential("scripts/verifiers/new_verifier.py", "NoSuchClass", ["covered.txt"], repo_root=repo)

    def test_verifier_failing_at_head_is_not_admitted(self, tmp_path: Path) -> None:
        """A hermetic verifier that never PASSes at HEAD/live is rejected before any worktree op."""
        repo = self._build_repo_with_verifier(tmp_path, _HERMETIC_ALWAYS_FAILS_VERIFIER)
        outcome = vg.run_verifier_differential(
            "scripts/verifiers/new_verifier.py", "NewVerifier", ["covered.txt"], repo_root=repo
        )
        assert not outcome.admitted and not outcome.skipped
        assert "expected PASS" in outcome.reason

    def test_checkout_failure_in_verifier_differential_raises(self, tmp_path: Path) -> None:
        """A covered_changed path that doesn't resolve on origin/main fails the revert checkout."""
        repo = self._build_repo_with_verifier(tmp_path, _HERMETIC_GENUINE_VERIFIER)
        with pytest.raises(vg.GraduationError, match="could not revert covered files"):
            vg.run_verifier_differential(
                "scripts/verifiers/new_verifier.py",
                "NewVerifier",
                ["does-not-exist-anywhere.txt"],
                repo_root=repo,
            )


# ---------------------------------------------------------------------------
# Injected revert_runner + fail-loud-on-error
# ---------------------------------------------------------------------------


class TestInjectedRevertRunnerAndFailLoud:
    def test_make_worktree_revert_runner_real_checkout(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "f.txt").write_text("base\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        (repo / "f.txt").write_text("head\n", encoding="utf-8")
        _commit_all(repo, "head")

        row = {
            "check_id": "revert-runner-check",
            "primitive_slot": "grep_count",
            "check_spec": {"path": "f.txt", "pattern": "head", "operator": "eq", "count": 1},
        }
        runner = vg.make_worktree_revert_runner(row, ref="origin/main", repo_root=repo)
        result = runner(vg.materialize_check_in_tree(row, repo))
        assert result.status == CheckStatus.FAIL

    def test_git_worktree_cleans_up_on_success(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        _commit_all(repo, "base")
        with vg.git_worktree("HEAD", repo_root=repo) as wt:
            assert wt.exists()
            captured = wt
        assert not captured.exists()

    def test_git_worktree_raises_on_bad_ref(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        _commit_all(repo, "base")
        with pytest.raises(vg.GraduationError, match="git worktree add failed"):
            with vg.git_worktree("refs/heads/does-not-exist", repo_root=repo):
                pass  # pragma: no cover

    def test_git_worktree_falls_back_to_prune_on_remove_failure(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "f.txt").write_text("x\n", encoding="utf-8")
        _commit_all(repo, "base")

        real_run_git = vg._run_git
        calls: list[list[str]] = []

        def fake_run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
            calls.append(args)
            if args[:2] == ["worktree", "remove"]:
                return subprocess.CompletedProcess(args=["git", *args], returncode=1, stdout="", stderr="simulated failure")
            return real_run_git(args, cwd)

        monkeypatch.setattr(vg, "_run_git", fake_run_git)
        with vg.git_worktree("HEAD", repo_root=repo):
            pass
        assert any(a[:2] == ["worktree", "prune"] for a in calls), calls

    def test_verifier_differential_non_deterministic_status_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "verifiers").mkdir(parents=True)
        (repo / "scripts" / "__init__.py").write_text("", encoding="utf-8")
        (repo / "scripts" / "verifiers" / "__init__.py").write_text("", encoding="utf-8")
        harness_src = (vg.ROOT / "scripts" / "verifiers" / "harness.py").read_text(encoding="utf-8")
        (repo / "scripts" / "verifiers" / "harness.py").write_text(harness_src, encoding="utf-8")
        _seed_graduation_deps(repo)
        (repo / "covered.txt").write_text("x\n", encoding="utf-8")
        base_sha = _commit_all(repo, "base")
        _git(repo, ["update-ref", "refs/remotes/origin/main", base_sha])
        (repo / "scripts" / "verifiers" / "new_verifier.py").write_text(_HERMETIC_GENUINE_VERIFIER, encoding="utf-8")
        _commit_all(repo, "head")

        statuses = iter(["PASS", "WARN"])
        monkeypatch.setattr(vg, "_run_verifier_subprocess", lambda *a, **k: next(statuses))
        with pytest.raises(vg.GraduationError, match="non-deterministic"):
            vg.run_verifier_differential("scripts/verifiers/new_verifier.py", "NewVerifier", ["covered.txt"], repo_root=repo)


# ---------------------------------------------------------------------------
# _run_verifier_subprocess error paths (fail-loud on a crashed/garbled subprocess)
# ---------------------------------------------------------------------------


class TestRunVerifierSubprocessErrors:
    def test_crash_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=2, stdout="", stderr="boom")
        )
        with pytest.raises(vg.GraduationError, match="crashed"):
            vg._run_verifier_subprocess("mod", "Cls", Path("."))

    def test_no_output_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        )
        with pytest.raises(vg.GraduationError, match="produced no output"):
            vg._run_verifier_subprocess("mod", "Cls", Path("."))

    def test_bad_json_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout="not json", stderr="")
        )
        with pytest.raises(vg.GraduationError, match="could not parse"):
            vg._run_verifier_subprocess("mod", "Cls", Path("."))

    def test_missing_status_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **k: subprocess.CompletedProcess(args=[], returncode=0, stdout='{"foo": "bar"}', stderr=""),
        )
        with pytest.raises(vg.GraduationError, match="missing 'status'"):
            vg._run_verifier_subprocess("mod", "Cls", Path("."))


# ---------------------------------------------------------------------------
# Subprocess entry point (`python -m scripts.verification_graduation --run-verifier ...`)
# ---------------------------------------------------------------------------


class TestSubprocessEntryPoint:
    def _register_fake_verifier(self, monkeypatch: pytest.MonkeyPatch, module_name: str) -> None:
        from scripts.verifiers.harness import Verifier, VerifierResult, VerifierStatus

        class _FakeVerifier(Verifier):
            async def verify(self) -> VerifierResult:
                return VerifierResult(name=self.name, status=VerifierStatus.PASS)

        fake_module = types.ModuleType(module_name)
        fake_module.FakeVerifier = _FakeVerifier
        monkeypatch.setitem(sys.modules, module_name, fake_module)

    def test_run_verifier_entry_prints_json(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        self._register_fake_verifier(monkeypatch, "fake_verifier_module_for_entry_test")
        vg._run_verifier_entry("fake_verifier_module_for_entry_test", "FakeVerifier")
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["status"] == "PASS"

    def test_main_dispatches_to_run_verifier_entry(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        self._register_fake_verifier(monkeypatch, "fake_verifier_module_for_main_test")
        monkeypatch.setattr(sys, "argv", ["prog", "--run-verifier", "fake_verifier_module_for_main_test", "FakeVerifier"])
        runpy.run_module("scripts.verification_graduation", run_name="__main__")
        payload = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
        assert payload["status"] == "PASS"

    def test_main_prints_usage_on_bad_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog"])
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("scripts.verification_graduation", run_name="__main__")
        assert exc_info.value.code == 2
