"""V2 tests for bin/sync-deps.sh: fingerprint drift detection, fingerprint write,
terraform version-compare, and a real end-to-end install + idempotency check.

bin/sync-deps.sh resolves its own REPO_ROOT relative to its own script location
(mirrors bin/setup-cloud-env.sh and the SessionStart hooks), so each test copies
the real script into a throwaway repo layout under tmp_path (bin/sync-deps.sh +
requirements.txt + requirements-dev.txt [+ config/terraform-version]) rather than
mocking the script's internals.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_SCRIPT_SRC = Path(__file__).resolve().parent.parent / "bin" / "sync-deps.sh"


def _make_fake_repo(
    tmp_path: Path,
    requirements: str = "six==1.16.0\n",
    requirements_dev: str = "typing-extensions==4.12.2\n",
) -> Path:
    """Build a throwaway repo layout with a real copy of bin/sync-deps.sh."""
    repo = tmp_path / "repo"
    (repo / "bin").mkdir(parents=True)
    shutil.copy(_SCRIPT_SRC, repo / "bin" / "sync-deps.sh")
    (repo / "bin" / "sync-deps.sh").chmod(0o755)
    (repo / "requirements.txt").write_text(requirements, encoding="utf-8")
    (repo / "requirements-dev.txt").write_text(requirements_dev, encoding="utf-8")
    return repo


def _expected_fingerprint(repo: Path) -> str:
    """Replicate the script's own fingerprint formula: sha256sum of both files, then sha256sum of that."""
    inner = subprocess.run(
        ["sha256sum", "requirements.txt", "requirements-dev.txt"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return hashlib.sha256(inner.encode("utf-8")).hexdigest()


def _run_sync(repo: Path, args: list[str] | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    cmd = ["bash", str(repo / "bin" / "sync-deps.sh"), *(args or [])]
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env=env, timeout=120)


class TestCheckModeDriftDetection:
    """--check reports drift status without installing anything."""

    def test_check_reports_drift_when_fingerprint_missing(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        result = _run_sync(repo, ["--check"])
        assert result.returncode == 1
        assert "drift" in result.stdout
        assert not (repo / ".venv").exists()

    def test_check_reports_drift_when_fingerprint_stale(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        (repo / ".venv").mkdir()
        (repo / ".venv" / ".requirements-fingerprint").write_text("0" * 64, encoding="utf-8")
        result = _run_sync(repo, ["--check"])
        assert result.returncode == 1
        assert "drift" in result.stdout
        # --check must never install -- the fingerprint file is left untouched.
        assert (repo / ".venv" / ".requirements-fingerprint").read_text(encoding="utf-8") == "0" * 64

    def test_check_reports_in_sync_when_fingerprint_matches(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(tmp_path)
        (repo / ".venv").mkdir()
        (repo / ".venv" / ".requirements-fingerprint").write_text(_expected_fingerprint(repo), encoding="utf-8")
        result = _run_sync(repo, ["--check"])
        assert result.returncode == 0
        assert "in sync" in result.stdout


class TestTerraformDriftDetection:
    """INSTALL_TERRAFORM=1 self-heal decision, proven via a stub terraform on PATH (no real install)."""

    def _stub_terraform(self, tmp_path: Path, version: str) -> Path:
        stub_dir = tmp_path / "stubbin"
        stub_dir.mkdir(exist_ok=True)
        stub = stub_dir / "terraform"
        stub.write_text(f'#!/usr/bin/env bash\necho "Terraform v{version}"\n', encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        return stub_dir

    def _in_sync_repo(self, tmp_path: Path, terraform_version: str = "1.10.5") -> Path:
        repo = _make_fake_repo(tmp_path)
        (repo / "config").mkdir()
        (repo / "config" / "terraform-version").write_text(f"{terraform_version}\n", encoding="utf-8")
        (repo / ".venv").mkdir()
        (repo / ".venv" / ".requirements-fingerprint").write_text(_expected_fingerprint(repo), encoding="utf-8")
        return repo

    def test_terraform_stub_version_mismatch_is_drift(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = self._in_sync_repo(tmp_path, terraform_version="1.10.5")
        stub_dir = self._stub_terraform(tmp_path, version="1.9.0")
        env = {**dict(**{"PATH": f"{stub_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"})}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 1
        assert "terraform=1" in result.stdout

    def test_terraform_stub_version_match_is_no_drift(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = self._in_sync_repo(tmp_path, terraform_version="1.10.5")
        stub_dir = self._stub_terraform(tmp_path, version="1.10.5")
        env = {**dict(**{"PATH": f"{stub_dir}:/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"})}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 0
        assert "in sync" in result.stdout

    def test_terraform_absent_from_path_is_drift(self, tmp_path: Path) -> None:
        repo = self._in_sync_repo(tmp_path, terraform_version="1.10.5")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "INSTALL_TERRAFORM": "1"}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 1
        assert "terraform=1" in result.stdout

    def test_install_terraform_unset_is_never_drift(self, tmp_path: Path) -> None:
        # No terraform on PATH at all, but INSTALL_TERRAFORM is unset -- must be a no-op.
        repo = self._in_sync_repo(tmp_path, terraform_version="1.10.5")
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
        result = _run_sync(repo, ["--check"], env=env)
        assert result.returncode == 0


class TestRealInstallAndIdempotency:
    """Real end-to-end python install in a throwaway venv: install, fingerprint write, idempotency."""

    def test_real_sync_installs_writes_fingerprint_and_is_idempotent(self, tmp_path: Path) -> None:
        repo = _make_fake_repo(
            tmp_path,
            requirements="six==1.16.0\n",
            requirements_dev="typing-extensions==4.12.2\n",
        )

        # 1. First sync: no .venv yet -- must create it, install both files, write the fingerprint.
        result = _run_sync(repo)
        assert result.returncode == 0, result.stdout + result.stderr
        fp_file = repo / ".venv" / ".requirements-fingerprint"
        assert fp_file.exists()
        assert fp_file.read_text(encoding="utf-8") == _expected_fingerprint(repo)

        venv_python = repo / ".venv" / "bin" / "python"
        assert venv_python.exists()
        import_check = subprocess.run(
            [str(venv_python), "-c", "import six, typing_extensions"],
            capture_output=True,
            text=True,
        )
        assert import_check.returncode == 0, import_check.stdout + import_check.stderr

        # 2. Second sync (unchanged files): must be a no-op per --check.
        check_result = _run_sync(repo, ["--check"])
        assert check_result.returncode == 0
        assert "in sync" in check_result.stdout

        # 3. Mutate requirements-dev.txt -- must detect drift and reinstall.
        (repo / "requirements-dev.txt").write_text("typing-extensions==4.12.2\npackaging==24.1\n", encoding="utf-8")
        drift_check = _run_sync(repo, ["--check"])
        assert drift_check.returncode == 1

        resync_result = _run_sync(repo)
        assert resync_result.returncode == 0, resync_result.stdout + resync_result.stderr
        assert fp_file.read_text(encoding="utf-8") == _expected_fingerprint(repo)

        import_check_2 = subprocess.run(
            [str(venv_python), "-c", "import six, typing_extensions, packaging"],
            capture_output=True,
            text=True,
        )
        assert import_check_2.returncode == 0, import_check_2.stdout + import_check_2.stderr

        # 4. Third sync (now in sync again): idempotent no-op.
        final_check = _run_sync(repo, ["--check"])
        assert final_check.returncode == 0
        assert "in sync" in final_check.stdout
