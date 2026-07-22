"""Tests for scripts/ci/ducklake_artifacts.py (T2.42 c4 / rec-2659, DEP-08).

Covers: byte-mismatch fails closed; on push the assert runs and a missing per-sha object fails
closed; the dual-write targets BOTH the fixed and per-sha keys; workflow_dispatch (any non-"push"
event_name) skips the assert. No live S3 -- boto3 is fully mocked via an injected fake client.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from scripts.ci.ducklake_artifacts import (
    DUCKLAKE_ARTIFACT_NAMES,
    DucklakeArtifactError,
    _md5_hex,
    assert_and_upload,
    build_ducklake_only,
    main,
)

# ---------------------------------------------------------------------------
# Fake S3 client -- get_object (per-sha reference read) + upload_file (dual-write)
# ---------------------------------------------------------------------------


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _NoSuchKeyError(Exception):
    pass


class _FakeS3Client:
    """objects: {key: bytes} pre-seeds get_object reads. uploads: list of (local_path, bucket, key)."""

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects or {}
        self.uploads: list[tuple[str, str, str]] = []

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        if Key not in self.objects:
            raise _NoSuchKeyError(f"NoSuchKey: {Key}")
        return {"Body": _FakeBody(self.objects[Key])}

    def upload_file(self, local_path: str, bucket: str, key: str) -> None:
        self.uploads.append((local_path, bucket, key))


def _write_packages(tmp_path: Path, names: list[str], content: bytes = b"zip-bytes") -> Path:
    packages_dir = tmp_path / "lambda-packages"
    packages_dir.mkdir()
    for name in names:
        (packages_dir / name).write_bytes(content)
    return packages_dir


# ---------------------------------------------------------------------------
# assert_and_upload -- push path: byte-identical passes, dual-write happens
# ---------------------------------------------------------------------------


def test_push_byte_identical_passes_and_dual_writes(tmp_path: Path) -> None:
    names = ["ducklake-writer.zip", "ducklake-reader.zip"]
    packages_dir = _write_packages(tmp_path, names, content=b"same-bytes")
    sha = "artifactsha123"
    client = _FakeS3Client(objects={f"lambda-packages/{sha}/{n}": b"same-bytes" for n in names})

    assert_and_upload(names, sha, "push", "my-bucket", packages_dir=packages_dir, s3_client=client)

    assert len(client.uploads) == 4  # 2 names x (fixed + per-sha)
    for name in names:
        assert (str(packages_dir / name), "my-bucket", f"lambda-packages/{name}") in client.uploads
        assert (str(packages_dir / name), "my-bucket", f"lambda-packages/{sha}/{name}") in client.uploads


# ---------------------------------------------------------------------------
# assert_and_upload -- push path: byte MISMATCH fails closed, no upload attempted
# ---------------------------------------------------------------------------


def test_push_byte_mismatch_fails_closed(tmp_path: Path) -> None:
    names = ["ducklake-writer.zip"]
    packages_dir = _write_packages(tmp_path, names, content=b"local-bytes")
    sha = "artifactsha123"
    client = _FakeS3Client(objects={f"lambda-packages/{sha}/ducklake-writer.zip": b"different-remote-bytes"})

    with pytest.raises(DucklakeArtifactError, match="DUCKLAKE_ZIP_MISMATCH"):
        assert_and_upload(names, sha, "push", "my-bucket", packages_dir=packages_dir, s3_client=client)

    assert client.uploads == []  # fails closed BEFORE any upload


def test_push_missing_per_sha_object_fails_closed(tmp_path: Path) -> None:
    names = ["ducklake-writer.zip"]
    packages_dir = _write_packages(tmp_path, names, content=b"local-bytes")
    sha = "artifactsha123"
    client = _FakeS3Client(objects={})  # nothing uploaded yet -- PR job never ran

    with pytest.raises(DucklakeArtifactError, match="DUCKLAKE_ZIP_MISMATCH"):
        assert_and_upload(names, sha, "push", "my-bucket", packages_dir=packages_dir, s3_client=client)

    assert client.uploads == []


def test_push_mismatch_stops_at_first_bad_name_not_partial_upload(tmp_path: Path) -> None:
    # rec-2755 parity: a mismatch on ANY artifact must fail the whole batch closed, never a
    # partial dual-write of the artifacts that happened to check out fine before it.
    names = ["ducklake-writer.zip", "ducklake-reader.zip", "ducklake-maintenance.zip"]
    packages_dir = _write_packages(tmp_path, names, content=b"local-bytes")
    sha = "sha1"
    client = _FakeS3Client(
        objects={
            f"lambda-packages/{sha}/ducklake-writer.zip": b"local-bytes",  # matches
            f"lambda-packages/{sha}/ducklake-reader.zip": b"MISMATCHED",  # fails here
            # ducklake-maintenance.zip never checked -- mismatch on #2 stops the loop
        }
    )
    with pytest.raises(DucklakeArtifactError):
        assert_and_upload(names, sha, "push", "my-bucket", packages_dir=packages_dir, s3_client=client)
    assert client.uploads == []


# ---------------------------------------------------------------------------
# assert_and_upload -- non-push event_name skips the assert entirely
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("event_name", ["workflow_dispatch", "pull_request", "something_else"])
def test_non_push_event_names_skip_assert_and_upload_directly(tmp_path: Path, event_name: str) -> None:
    names = ["ducklake-writer.zip"]
    packages_dir = _write_packages(tmp_path, names, content=b"whatever-bytes")
    sha = "shaXYZ"
    # No pre-seeded objects at all -- if the assert ran, get_object would raise _NoSuchKeyError.
    client = _FakeS3Client(objects={})

    assert_and_upload(names, sha, event_name, "my-bucket", packages_dir=packages_dir, s3_client=client)

    assert len(client.uploads) == 2  # fixed + per-sha, no assert attempted
    assert (str(packages_dir / "ducklake-writer.zip"), "my-bucket", "lambda-packages/ducklake-writer.zip") in client.uploads
    assert (
        str(packages_dir / "ducklake-writer.zip"),
        "my-bucket",
        f"lambda-packages/{sha}/ducklake-writer.zip",
    ) in client.uploads


# ---------------------------------------------------------------------------
# Dual-write targets BOTH keys for every artifact (full 7-artifact roster)
# ---------------------------------------------------------------------------


def test_dual_write_targets_both_fixed_and_per_sha_keys_for_all_artifacts(tmp_path: Path) -> None:
    names = list(DUCKLAKE_ARTIFACT_NAMES)
    packages_dir = _write_packages(tmp_path, names, content=b"content")
    sha = "fullrostersha"
    client = _FakeS3Client(objects={})

    assert_and_upload(names, sha, "workflow_dispatch", "bucket-x", packages_dir=packages_dir, s3_client=client)

    fixed_keys = {key for (_, _, key) in client.uploads if not key.startswith(f"lambda-packages/{sha}/")}
    per_sha_keys = {key for (_, _, key) in client.uploads if key.startswith(f"lambda-packages/{sha}/")}
    assert fixed_keys == {f"lambda-packages/{n}" for n in names}
    assert per_sha_keys == {f"lambda-packages/{sha}/{n}" for n in names}
    assert len(names) == 7  # sanity: the roster is genuinely the full seven artifacts


# ---------------------------------------------------------------------------
# _md5_hex + s3_client=None default construction
# ---------------------------------------------------------------------------


def test_md5_hex_matches_hashlib() -> None:
    data = b"some artifact bytes"
    assert _md5_hex(data) == hashlib.md5(data).hexdigest()


def test_assert_and_upload_constructs_boto3_client_when_none_injected(tmp_path: Path) -> None:
    names = ["ducklake-writer.zip"]
    packages_dir = _write_packages(tmp_path, names)
    fake_client = _FakeS3Client(objects={})
    fake_boto3 = MagicMock()
    fake_boto3.client.return_value = fake_client

    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        assert_and_upload(names, "sha1", "workflow_dispatch", "bucket", region="eu-west-1", packages_dir=packages_dir)

    fake_boto3.client.assert_called_once_with("s3", region_name="eu-west-1")
    assert len(fake_client.uploads) == 2


# ---------------------------------------------------------------------------
# build_ducklake_only -- thin subprocess wrapper
# ---------------------------------------------------------------------------


def test_build_ducklake_only_invokes_expected_command() -> None:
    with patch("scripts.ci.ducklake_artifacts.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        build_ducklake_only(cwd="/some/dir")
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert "scripts.build_lambda" in cmd
    assert "--ducklake-only" in cmd
    assert "--skip-upload" in cmd
    assert kwargs["cwd"] == "/some/dir"
    assert kwargs["check"] is True


# ---------------------------------------------------------------------------
# CLI entrypoint (main) -- build + assert_and_upload wiring, --skip-build, error surfacing
# ---------------------------------------------------------------------------


def test_main_skip_build_calls_assert_and_upload_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_packages(tmp_path, list(DUCKLAKE_ARTIFACT_NAMES))
    calls: list[Any] = []

    def _fake_assert_and_upload(names, artifact_sha, event_name, bucket, region, **kwargs):
        calls.append((names, artifact_sha, event_name, bucket, region))

    with patch("scripts.ci.ducklake_artifacts.build_ducklake_only") as mock_build:
        with patch("scripts.ci.ducklake_artifacts.assert_and_upload", side_effect=_fake_assert_and_upload):
            rc = main(["push", "sha1", "my-bucket", "--skip-build"])

    assert rc == 0
    mock_build.assert_not_called()
    assert len(calls) == 1
    names, sha, event_name, bucket, region = calls[0]
    assert list(names) == list(DUCKLAKE_ARTIFACT_NAMES)
    assert (sha, event_name, bucket, region) == ("sha1", "push", "my-bucket", "eu-west-2")


def test_main_without_skip_build_calls_build_first() -> None:
    with patch("scripts.ci.ducklake_artifacts.build_ducklake_only") as mock_build:
        with patch("scripts.ci.ducklake_artifacts.assert_and_upload") as mock_assert:
            rc = main(["workflow_dispatch", "sha2", "bucket-y"])
    assert rc == 0
    mock_build.assert_called_once()
    mock_assert.assert_called_once()


def test_main_surfaces_ducklake_artifact_error_as_exit_one(capsys: pytest.CaptureFixture) -> None:
    with patch("scripts.ci.ducklake_artifacts.build_ducklake_only"):
        with patch(
            "scripts.ci.ducklake_artifacts.assert_and_upload",
            side_effect=DucklakeArtifactError("DUCKLAKE_ZIP_MISMATCH boom"),
        ):
            rc = main(["push", "sha3", "bucket-z"])
    assert rc == 1
    assert "DUCKLAKE_ZIP_MISMATCH" in capsys.readouterr().err


def test_main_custom_region_is_passed_through() -> None:
    with patch("scripts.ci.ducklake_artifacts.build_ducklake_only"):
        with patch("scripts.ci.ducklake_artifacts.assert_and_upload") as mock_assert:
            main(["push", "sha4", "bucket-w", "--region", "us-east-1"])
    assert mock_assert.call_args == call(list(DUCKLAKE_ARTIFACT_NAMES), "sha4", "push", "bucket-w", "us-east-1")
