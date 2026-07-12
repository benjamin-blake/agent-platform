"""Tests for scripts/ci/reconcile_target.py (T2.37 -- input-free Reconcile heal button).

Covers: red-commit extraction from an injected convergence record, green/absent -> clean no-op,
and rec-id OPEN validation via an injected reader (never live AWS).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.ci.reconcile_target import (
    ReconcileTarget,
    main,
    read_convergence_record,
    resolve_reconcile_target,
    validate_rec_id_open,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# resolve_reconcile_target (pure, injected record)
# ---------------------------------------------------------------------------


def test_red_record_returns_commit_sha() -> None:
    # Non-hex sentinel SHA: resolve_reconcile_target does no SHA-format validation, and a realistic
    # 12-hex-char value trips the detect-secrets high-entropy hook as a false positive.
    record = {"status": "red", "commit_sha": "red-commit-sentinel"}
    target = resolve_reconcile_target(record)
    assert target.actionable is True
    assert target.commit_sha == "red-commit-sentinel"


def test_green_record_is_clean_noop() -> None:
    target = resolve_reconcile_target({"status": "green", "commit_sha": "abc123"})
    assert target.actionable is False
    assert target.commit_sha is None
    assert "not red" in target.reason


def test_absent_record_is_clean_noop() -> None:
    target = resolve_reconcile_target(None)
    assert target.actionable is False
    assert target.commit_sha is None
    assert "absent" in target.reason


def test_unknown_status_is_clean_noop() -> None:
    # Any non-"red" status (unknown, missing, malformed) is treated as nothing-to-reconcile --
    # Reconcile only ever acts on an explicit red.
    target = resolve_reconcile_target({"status": "unknown"})
    assert target.actionable is False


def test_red_record_without_commit_sha_is_not_actionable_and_not_silently_green() -> None:
    target = resolve_reconcile_target({"status": "red"})
    assert target.actionable is False
    assert target.commit_sha is None
    assert "malformed" in target.reason


def test_reconcile_target_dataclass_defaults() -> None:
    t = ReconcileTarget(actionable=False)
    assert t.commit_sha is None
    assert t.reason == ""


# ---------------------------------------------------------------------------
# read_convergence_record (injected S3 client, mirrors convergence_health.py's own test pattern)
# ---------------------------------------------------------------------------


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3Client:
    def __init__(self, obj: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self._obj = obj
        self._error = error

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if self._error is not None:
            raise self._error
        import json as _json

        return {"Body": _FakeBody(_json.dumps(self._obj).encode("utf-8"))}


class _NoSuchKeyError(Exception):
    pass


def test_read_convergence_record_parses_body() -> None:
    client = _FakeS3Client(obj={"status": "red", "commit_sha": "abc"})
    record = read_convergence_record(client)
    assert record == {"status": "red", "commit_sha": "abc"}


def test_read_convergence_record_returns_none_on_nosuchkey() -> None:
    client = _FakeS3Client(error=_NoSuchKeyError("NoSuchKey: object not found"))
    assert read_convergence_record(client) is None


def test_read_convergence_record_reraises_other_errors() -> None:
    client = _FakeS3Client(error=RuntimeError("AccessDenied: nope"))
    with pytest.raises(RuntimeError):
        read_convergence_record(client)


# ---------------------------------------------------------------------------
# validate_rec_id_open (injected reader)
# ---------------------------------------------------------------------------


def _reader_returning(rows: list[dict[str, Any]]):
    def _r(rec_id: str) -> list[dict[str, Any]]:
        return rows

    return _r


def test_open_rec_id_validates() -> None:
    reader = _reader_returning([{"id": "rec-2658", "status": "open"}])
    assert validate_rec_id_open("rec-2658", reader) is True


def test_closed_rec_id_rejected() -> None:
    reader = _reader_returning([{"id": "rec-2658", "status": "closed"}])
    assert validate_rec_id_open("rec-2658", reader) is False


def test_absent_rec_id_rejected() -> None:
    reader = _reader_returning([])
    assert validate_rec_id_open("rec-9999999", reader) is False


def test_malformed_rec_id_rejected_without_calling_reader() -> None:
    calls: list[str] = []

    def _reader(rec_id: str) -> list[dict[str, Any]]:
        calls.append(rec_id)
        return [{"status": "open"}]

    assert validate_rec_id_open("not-a-rec-id", _reader) is False
    assert calls == []  # never called the reader -- fail-closed on input shape


@pytest.mark.parametrize("bad_id", ["rec-", "rec-abc", "REC-123", "rec-123 ", " rec-123", "rec-123extra"])
def test_various_malformed_rec_ids_rejected(bad_id: str) -> None:
    reader = _reader_returning([{"status": "open"}])
    assert validate_rec_id_open(bad_id, reader) is False


# ---------------------------------------------------------------------------
# CLI entrypoint: convergence read path (mock boto3 via monkeypatch on the module's boto3 import
# site is awkward for a deferred import; exercise the read/resolve path directly and the rec-id
# validation failure path through main(), which is fully injectable there).
# ---------------------------------------------------------------------------


def test_main_invalid_rec_id_fails_closed_before_convergence_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import scripts.ci.reconcile_target as rt

    monkeypatch.setattr(rt, "_default_reader", lambda profile: _reader_returning([{"status": "closed"}]))
    rc = main(["--rec-id", "rec-1"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "does not resolve to an OPEN rec" in err


def test_main_malformed_rec_id_fails_closed(capsys: pytest.CaptureFixture) -> None:
    rc = main(["--rec-id", "not-valid"])
    assert rc == 1


def test_main_open_rec_id_proceeds_to_convergence_read(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    import scripts.ci.reconcile_target as rt

    monkeypatch.setattr(rt, "_default_reader", lambda profile: _reader_returning([{"status": "open"}]))

    class _FakeSession:
        def __init__(self, profile_name: str | None = None) -> None:
            pass

        def client(self, name: str):
            return _FakeS3Client(error=_NoSuchKeyError("NoSuchKey"))

    class _FakeBoto3Module:
        Session = _FakeSession

    monkeypatch.setitem(__import__("sys").modules, "boto3", _FakeBoto3Module())

    rc = main(["--rec-id", "rec-2658"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "rec_id_validated=rec-2658" in out
    assert "actionable=false" in out


def test_main_no_rec_id_reads_convergence_directly(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    class _FakeSession:
        def __init__(self, profile_name: str | None = None) -> None:
            pass

        def client(self, name: str):
            return _FakeS3Client(obj={"status": "red", "commit_sha": "deadbeef"})

    class _FakeBoto3Module:
        Session = _FakeSession

    monkeypatch.setitem(__import__("sys").modules, "boto3", _FakeBoto3Module())

    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "actionable=true" in out
    assert "commit_sha=deadbeef" in out


# ---------------------------------------------------------------------------
# Invocation-path regression guard (code-review High finding, 2026-07-12).
#
# The optional --rec-id path does a deferred `from src.common.iceberg_reader import make_reader`,
# which only resolves when the REPO ROOT is on sys.path. Invoking the helper as a FILE PATH
# (`python3 scripts/ci/reconcile_target.py`) puts scripts/ci/ on sys.path[0] instead, so `src`
# fails to import and every rec-id dispatch fails closed -- which the pure unit tests above never
# caught because they monkeypatch _default_reader. reconcile.yml must invoke via `-m` so the
# repo-root cwd lands on sys.path.
# ---------------------------------------------------------------------------


def test_default_reader_import_resolves_under_module_invocation() -> None:
    # Hermetic (no network): _default_reader only performs the deferred `src` import and returns a
    # closure -- it does NOT invoke the reader. A subprocess from the repo root proves the import
    # chain resolves under the invocation shape reconcile.yml now uses (`python -m ...`).
    result = subprocess.run(
        [sys.executable, "-c", "import scripts.ci.reconcile_target as rt; rt._default_reader(None); print('IMPORT_OK')"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, f"src import chain failed under module invocation: {result.stderr}"
    assert "IMPORT_OK" in result.stdout
    assert "No module named 'src'" not in result.stderr


def test_file_path_invocation_would_break_src_import() -> None:
    # Documents the bug the workflow fix avoids: run the script BY FILE PATH from an unrelated cwd
    # (so sys.path[0] is scripts/ci/, not the repo root) and confirm the deferred `src` import is
    # exactly what breaks -- the failure mode reconcile.yml's `-m` invocation sidesteps.
    script = _REPO_ROOT / "scripts" / "ci" / "reconcile_target.py"
    result = subprocess.run(
        [sys.executable, str(script), "--rec-id", "rec-1", "--profile", ""],
        cwd=str(_REPO_ROOT / "scripts" / "ci"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={"PATH": __import__("os").environ.get("PATH", "")},  # scrub PYTHONPATH so the repo root is not injected
    )
    # main() catches the import failure and returns 1 (fails closed) -- it must NOT print a
    # validated marker, and the specific breakage is the src import.
    assert result.returncode == 1
    assert "No module named 'src'" in result.stderr
    assert "rec_id_validated" not in result.stdout


def test_reconcile_workflow_invokes_helper_as_module() -> None:
    # Static guard on the fix: reconcile.yml must invoke the helper as a module, never by file
    # path -- otherwise the rec-id validation path regresses to the broken-import behaviour above.
    # Scanned per-line so a file-path mention inside an explanatory COMMENT (which documents why
    # the file-path form is avoided) does not trip the guard -- only actual invocation lines count
    # (a run-command line invoking the helper is not a `#`-prefixed comment).
    wf = (_REPO_ROOT / ".github" / "workflows" / "reconcile.yml").read_text(encoding="utf-8")
    assert "python3 -m scripts.ci.reconcile_target" in wf
    invocation_lines = [ln for ln in wf.splitlines() if "reconcile_target.py" in ln and not ln.lstrip().startswith("#")]
    assert invocation_lines == [], f"file-path invocation must not appear in run commands: {invocation_lines}"


def test_main_convergence_read_failure_fails_closed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    class _FakeSession:
        def __init__(self, profile_name: str | None = None) -> None:
            pass

        def client(self, name: str):
            raise RuntimeError("no credentials")

    class _FakeBoto3Module:
        Session = _FakeSession

    monkeypatch.setitem(__import__("sys").modules, "boto3", _FakeBoto3Module())

    rc = main([])
    assert rc == 1
    err = capsys.readouterr().err
    assert "could not read convergence record" in err
