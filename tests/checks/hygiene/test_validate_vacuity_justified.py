"""Tests for validate_vacuity_justified() -- the rec-3163 vacuity alarm
(PLAN-probe-discrimination-vacuity-alarm). Mirror of
scripts/checks/hygiene/validate_vacuity_justified.py.

TestVacuityMatrix exercises the four (oracle, checker) combinations plus the
oracle-uncomputable skip case, via a throwaway git repo for the base-free oracle side
(root injection seam) and test_coverage_checker.get_changed_source_files()'s own public
`files=` parameter for the checker side -- never a mock of that function itself.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.checks import registry
from scripts.checks.hygiene.validate_vacuity_justified import validate_vacuity_justified


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


class TestVacuityMatrix:
    """The four (base-free oracle, checker) combinations, plus the oracle-uncomputable skip."""

    def test_oracle_non_empty_checker_empty_fails(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        _commit_all(repo, "base")
        (repo / "scripts").mkdir()
        (repo / "scripts" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "add scripts/foo.py")

        failed: list[str] = []
        registry.pop_declaration()
        validate_vacuity_justified(failed, root=repo, checker_files=[])
        assert len(failed) == 1
        assert "EMPTY" in failed[0]
        assert "scripts/foo.py" in failed[0]
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1

    def test_oracle_non_empty_checker_non_empty_passes(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        _commit_all(repo, "base")
        (repo / "scripts").mkdir()
        (repo / "scripts" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "add scripts/foo.py")

        failed: list[str] = []
        registry.pop_declaration()
        # checker_files references a real, always-present file in THIS repository --
        # get_changed_source_files() resolves against its own module ROOT, not the throwaway repo.
        validate_vacuity_justified(failed, root=repo, checker_files=["scripts/ops_data_portal.py"])
        assert failed == []
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1

    def test_both_empty_with_computable_oracle_passes_vacuous(self, tmp_path: Path) -> None:
        """A genuinely test/docs-only diff: the oracle is computable and legitimately empty."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        _commit_all(repo, "base")
        (repo / "README.md").write_text("base changed\n", encoding="utf-8")
        _commit_all(repo, "docs-only change")

        failed: list[str] = []
        registry.pop_declaration()
        validate_vacuity_justified(failed, root=repo, checker_files=[])
        assert failed == []
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0

    def test_oracle_empty_checker_non_empty_passes_on_checker_count(self, tmp_path: Path) -> None:
        """The checker seeing MORE than the last commit is the normal multi-commit case -- never
        evidence of vacuity."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        _commit_all(repo, "base")
        (repo / "README.md").write_text("base changed\n", encoding="utf-8")
        _commit_all(repo, "docs-only change")

        failed: list[str] = []
        registry.pop_declaration()
        validate_vacuity_justified(failed, root=repo, checker_files=["scripts/ops_data_portal.py"])
        assert failed == []
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 1

    def test_oracle_uncomputable_skips_never_a_silent_pass(self, tmp_path: Path) -> None:
        """A single-commit repo: HEAD~1 does not resolve -- absence of evidence is skipped(),
        never a pass."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        _commit_all(repo, "base")

        failed: list[str] = []
        registry.pop_declaration()
        validate_vacuity_justified(failed, root=repo, checker_files=[])
        assert failed == []
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "skipped"

    def test_delete_only_commit_never_false_alarms(self, tmp_path: Path) -> None:
        """A deleted source file is listed by raw `git diff --name-only` but must be dropped by
        the oracle's existence filter -- otherwise a delete-only commit fires a false fail-closed
        alarm (mirrors get_changed_source_files' own p.resolve().exists() filter)."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        (repo / "scripts").mkdir()
        (repo / "scripts" / "foo.py").write_text("x = 1\n", encoding="utf-8")
        _commit_all(repo, "base")
        (repo / "scripts" / "foo.py").unlink()
        _commit_all(repo, "delete scripts/foo.py")

        failed: list[str] = []
        registry.pop_declaration()
        validate_vacuity_justified(failed, root=repo, checker_files=[])
        assert failed == []
        declaration = registry.pop_declaration()
        assert declaration is not None
        assert declaration.kind == "examined"
        assert declaration.count == 0
