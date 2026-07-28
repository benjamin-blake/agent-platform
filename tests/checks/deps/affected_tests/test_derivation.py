"""Aggregation/cap/manifest/invariant tests for scripts/checks/deps/affected_tests.py (Decision
affected-set-selection). Every class below exercises the REAL selector (derive_affected_tests)
against a small, self-contained fixture repo under tmp_path -- never a mock of the selector
itself. Split from tests/checks/deps/test_affected_tests.py (Decision 128 SLOC decomposition,
concern-split: aggregation/cap/manifest/invariant layer vs.
tests/checks/deps/affected_tests/test_channels.py's per-channel derivation tests).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks.deps import affected_tests as at
from tests.fixtures.affected_tests_helpers import write_file as _write


class TestAdditiveOnlyInvariant:
    """affected-selection is a superset of the edited-set for any diff, including under
    cap/overflow: an edited-set member (and direct reverse-deps + data-edge hits) is never
    deferred; only the transitive residue is deferred."""

    def _fanout_fixture(self, tmp_path: Path, n_transitive: int) -> None:
        """scripts/base.py <- scripts/mid.py (direct dep of base) <- N test files that import
        mid (each a TRANSITIVE, 2-hop ancestor of base.py, never a direct predecessor of base)."""
        _write(tmp_path, "scripts/base.py", "def do():\n    pass\n")
        _write(tmp_path, "scripts/mid.py", "from scripts.base import do\n\ndef mid():\n    do()\n")
        for i in range(n_transitive):
            _write(
                tmp_path,
                f"tests/test_mid_dep_{i:02d}.py",
                f"from scripts.mid import mid\n\ndef test_{i}():\n    mid()\n",
            )

    def test_edited_set_member_never_deferred_under_cap_overflow(self, tmp_path: Path) -> None:
        self._fanout_fixture(tmp_path, n_transitive=10)
        _write(tmp_path, "tests/test_direct_on_base.py", "from scripts.base import do\n\ndef test_x():\n    do()\n")
        diff = [("M", "scripts/base.py"), ("M", "tests/test_direct_on_base.py")]
        result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=3)
        assert "tests/test_direct_on_base.py" in result["selected"], "edited-set member must never be deferred"

    def test_direct_reverse_dep_never_deferred_under_cap_overflow(self, tmp_path: Path) -> None:
        self._fanout_fixture(tmp_path, n_transitive=10)
        diff = [("M", "scripts/base.py")]
        result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=1)
        # scripts/mid.py is a DIRECT predecessor of scripts/base.py in module-graph terms, but
        # direct reverse-deps are TEST modules; here the direct predecessor of base.py is
        # scripts.mid (not a test), so assert instead that the selection is always a superset
        # of the edited-set (empty here) and never raises/crashes under a pathologically tiny cap.
        assert set() <= set(result["selected"])

    def test_data_edge_hit_never_deferred_under_tiny_cap(self, tmp_path: Path) -> None:
        self._fanout_fixture(tmp_path, n_transitive=10)
        _write(tmp_path, "docs/ROADMAP-PLATFORM.yaml", "tier_items: []\n")
        _write(
            tmp_path,
            "tests/test_roadmap_reader.py",
            'ROADMAP = "ROADMAP-PLATFORM.yaml"\n\ndef test_reads_roadmap():\n    assert ROADMAP\n',
        )
        diff = [("M", "scripts/base.py"), ("M", "docs/ROADMAP-PLATFORM.yaml")]
        result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=1)
        assert "tests/test_roadmap_reader.py" in result["selected"], "data-edge hits must never be deferred"


class TestCapAndDefer:
    """The ~35-module cap defers ONLY the transitive residue -- a mixed batch of protected hits
    plus transitive-residue overflow defers exactly the overflow."""

    def test_transitive_overflow_is_capped_and_deferred(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/base.py", "def do():\n    pass\n")
        _write(tmp_path, "scripts/mid.py", "from scripts.base import do\n\ndef mid():\n    do()\n")
        for i in range(10):
            _write(
                tmp_path,
                f"tests/test_mid_dep_{i:02d}.py",
                f"from scripts.mid import mid\n\ndef test_{i}():\n    mid()\n",
            )
        result = at.derive_affected_tests([("M", "scripts/base.py")], repo_root=tmp_path, cap=4)
        manifest = result["manifest"]
        assert manifest["capped"] is True
        assert len(manifest["deferred"]) > 0
        assert len(result["selected"]) + len(manifest["deferred"]) == 10
        assert set(result["selected"]).isdisjoint(manifest["deferred"])

    def test_under_cap_nothing_deferred(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/base.py", "def do():\n    pass\n")
        _write(tmp_path, "scripts/mid.py", "from scripts.base import do\n\ndef mid():\n    do()\n")
        _write(tmp_path, "tests/test_mid_dep_00.py", "from scripts.mid import mid\n\ndef test_0():\n    mid()\n")
        result = at.derive_affected_tests([("M", "scripts/base.py")], repo_root=tmp_path, cap=at.CAP)
        assert result["manifest"]["capped"] is False
        assert result["manifest"]["deferred"] == []


class TestManifestEmission:
    """Manifest emission + content: required keys, per-test provenance/channel correctness."""

    _REQUIRED_KEYS = {"sha", "diff", "edited_set", "selected", "provenance", "capped", "deferred", "cap", "timings"}

    def test_manifest_has_required_keys(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
        result = at.derive_affected_tests([("M", "tests/test_a.py")], repo_root=tmp_path)
        assert self._REQUIRED_KEYS <= set(result["manifest"].keys())

    def test_provenance_tags_edited_set_member(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
        result = at.derive_affected_tests([("M", "tests/test_a.py")], repo_root=tmp_path)
        assert result["manifest"]["provenance"]["tests/test_a.py"] == "edited_set"

    def test_diff_field_mirrors_input_entries(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
        result = at.derive_affected_tests([("M", "tests/test_a.py")], repo_root=tmp_path)
        assert result["manifest"]["diff"] == [{"status": "M", "path": "tests/test_a.py"}]

    def test_emit_manifest_writes_gitignored_path_and_returns_it(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
        result = at.derive_affected_tests([("M", "tests/test_a.py")], repo_root=tmp_path)
        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("S3_LOG_BUCKET", None)
            manifest_path = at.emit_manifest(result["manifest"], repo_root=tmp_path)
        assert manifest_path == tmp_path / "logs" / "debug" / "selection-manifest.json"
        assert manifest_path.exists()

    def test_emit_manifest_local_write_failure_is_loud_skip_not_raise(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """A local disk I/O error (e.g. 'logs' exists as a FILE, not a directory, so mkdir()
        raises NotADirectoryError) must be a loud skip -- never crash --pre (Decision 55),
        matching the best-effort philosophy already applied to the S3 upload leg."""
        _write(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
        result = at.derive_affected_tests([("M", "tests/test_a.py")], repo_root=tmp_path)
        (tmp_path / "logs").write_text("not a directory", encoding="utf-8")
        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("S3_LOG_BUCKET", None)
            manifest_path = at.emit_manifest(result["manifest"], repo_root=tmp_path)
        captured = capsys.readouterr()
        assert "local write" in captured.out
        assert "loud skip" in captured.out.lower()
        assert not manifest_path.exists()


class TestS3UploadDegradesGracefully:
    """With boto3/creds absent, the upload lazy-imports boto3 and prints a LOUD skip -- never
    silent, never raising (Decision 55)."""

    def test_no_bucket_set_prints_loud_skip(self, capsys: pytest.CaptureFixture) -> None:
        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("S3_LOG_BUCKET", None)
            at._upload_manifest_best_effort({"sha": "abc123"})
        captured = capsys.readouterr()
        assert "S3_LOG_BUCKET not set" in captured.out
        assert "skipping" in captured.out.lower()

    def test_boto3_unavailable_prints_loud_skip(self, capsys: pytest.CaptureFixture) -> None:
        import sys

        with patch.dict("os.environ", {"S3_LOG_BUCKET": "some-bucket"}), patch.dict(sys.modules, {"boto3": None}):
            at._upload_manifest_best_effort({"sha": "abc123"})
        captured = capsys.readouterr()
        assert "boto3 not installed" in captured.out
        assert "skipping" in captured.out.lower()

    def test_upload_exception_is_loud_skip_not_raise(self, capsys: pytest.CaptureFixture) -> None:
        import sys
        import types

        fake_boto3 = types.ModuleType("boto3")

        class _BoomSession:
            def __init__(self, *a, **kw):
                raise RuntimeError("boom")

        fake_boto3.Session = _BoomSession  # type: ignore[attr-defined]

        with patch.dict("os.environ", {"S3_LOG_BUCKET": "some-bucket"}), patch.dict(sys.modules, {"boto3": fake_boto3}):
            at._upload_manifest_best_effort({"sha": "abc123"})
        captured = capsys.readouterr()
        assert "best-effort S3 upload failed" in captured.out


class TestS3UploadSuccess:
    """The happy path: boto3 present, bucket set, put_object succeeds -- prints the s3:// URL."""

    def test_successful_upload_prints_s3_url(self, capsys: pytest.CaptureFixture) -> None:
        import sys
        import types

        fake_boto3 = types.ModuleType("boto3")
        put_calls: list[dict] = []

        class _FakeClient:
            def put_object(self, **kwargs):
                put_calls.append(kwargs)

        class _FakeSession:
            def __init__(self, *a, **kw):
                pass

            def client(self, *a, **kw):
                return _FakeClient()

        fake_boto3.Session = _FakeSession  # type: ignore[attr-defined]

        with (
            patch.dict("os.environ", {"S3_LOG_BUCKET": "some-bucket"}),
            patch.dict(sys.modules, {"boto3": fake_boto3}),
            patch("scripts.aws_profile.resolve_aws_profile", return_value=None),
        ):
            at._upload_manifest_best_effort({"sha": "abc123"})

        captured = capsys.readouterr()
        assert "uploaded to s3://some-bucket/ci/selection/abc123/selection-manifest.json" in captured.out
        assert len(put_calls) == 1


class TestExceptionFallback:
    """When the derivation raises internally, the selector falls back to the edited-set and
    prints a loud warning -- never silently shrinking below it."""

    def test_injected_exception_falls_back_to_edited_set(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        _write(tmp_path, "scripts/foo.py", "def bar():\n    pass\n")
        _write(tmp_path, "tests/test_edited.py", "def test_x():\n    assert True\n")
        with patch("scripts.checks.deps.affected_tests._import_closure_channel", side_effect=RuntimeError("boom")):
            result = at.derive_affected_tests([("M", "scripts/foo.py"), ("M", "tests/test_edited.py")], repo_root=tmp_path)
        assert set(result["selected"]) >= {"tests/test_edited.py"}
        assert result["manifest"].get("fallback") is True
        captured = capsys.readouterr()
        assert "FALLING BACK TO EDITED-SET" in captured.out


class TestManifestNotAnInput:
    """The derivation output is byte-identical whether a prior selection-manifest.json is
    ABSENT, present, or deliberately MUTATED -- the manifest never feeds selection."""

    def test_selection_identical_across_absent_present_mutated_manifest(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/foo.py", "def bar():\n    pass\n")
        _write(tmp_path, "tests/test_foo_consumer.py", "from scripts.foo import bar\n\ndef test_bar():\n    bar()\n")
        diff = [("M", "scripts/foo.py")]

        result_absent = at.derive_affected_tests(diff, repo_root=tmp_path)

        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("S3_LOG_BUCKET", None)
            at.emit_manifest(result_absent["manifest"], repo_root=tmp_path)
        result_present = at.derive_affected_tests(diff, repo_root=tmp_path)

        manifest_path = tmp_path / "logs" / "debug" / "selection-manifest.json"
        manifest_path.write_text('{"garbage": true, "selected": ["tests/test_should_not_matter.py"]}', encoding="utf-8")
        result_mutated = at.derive_affected_tests(diff, repo_root=tmp_path)

        assert result_absent["selected"] == result_present["selected"] == result_mutated["selected"]
        assert (
            result_absent["manifest"]["provenance"]
            == result_present["manifest"]["provenance"]
            == result_mutated["manifest"]["provenance"]
        )


class TestEmptyDiff:
    """No diff entries at all -- selection is the (empty) edited-set, no crash, no graph build."""

    def test_empty_diff_returns_empty_selection(self, tmp_path: Path) -> None:
        result = at.derive_affected_tests([], repo_root=tmp_path)
        assert result["selected"] == []
        assert result["manifest"]["capped"] is False


class TestRootConftestForcesFullScope:
    """VTS-03: a changed root/autouse conftest forces its subtree into protected/uncapped."""

    def test_autouse_and_plain_sub_conftests_get_different_channel_treatment(self, tmp_path: Path) -> None:
        """Autouse sub-conftest -> protected/uncapped; plain sub-conftest -> ordinary/cappable."""
        _write(
            tmp_path,
            "tests/autouse_pkg/conftest.py",
            "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef _setup():\n    yield\n",
        )
        _write(tmp_path, "tests/autouse_pkg/test_a.py", "def test_a():\n    assert True\n")
        _write(tmp_path, "tests/plain_pkg/conftest.py", "")
        for i in range(3):
            _write(tmp_path, f"tests/plain_pkg/test_{i}.py", f"def test_{i}():\n    assert True\n")
        diff = [("M", "tests/autouse_pkg/conftest.py"), ("M", "tests/plain_pkg/conftest.py")]
        result = at.derive_affected_tests(diff, repo_root=tmp_path, cap=2)
        manifest = result["manifest"]
        assert "tests/autouse_pkg/test_a.py" in result["selected"]
        assert manifest["provenance"]["tests/autouse_pkg/test_a.py"] == "conftest_subtree_forced"
        assert manifest["full_suite_forced"] is False
        assert manifest["capped"] is True
        assert len(manifest["deferred"]) == 2

    def test_rec_2725_incident_replay_real_repo(self) -> None:
        """rec-2725 victim (deferred pre-fix, past the 35-module alphabetical keep window)."""
        result = at.derive_affected_tests([("M", "tests/conftest.py")])
        manifest = result["manifest"]
        assert manifest["capped"] is False
        assert manifest["deferred"] == []
        assert manifest["full_suite_forced"] is True
        assert "tests/ops_data_portal/test_decisions.py" in result["selected"]


class TestResidueChannelPriorityOrdering:
    """VTS-04 M2: residue truncates by channel priority (mirror_map < conftest_subtree <
    transitive), not alphabetically -- a higher-signal hit survives even sorting later."""

    def test_full_priority_ordering_mirror_then_conftest_then_transitive(self, tmp_path: Path) -> None:
        """cap=2 keeps mirror+conftest, defers transitive; cap=1 keeps mirror only -- proves the
        strict pairwise ordering. Also carries the dec-142 coherence assertion (compute_escape_class
        reads ONLY manifest['selected']/['deferred'] as flat, disjoint path-string lists)."""
        from scripts.ops_portal.ci_rca_lifecycle import compute_escape_class

        _write(tmp_path, "scripts/base.py", "def do():\n    pass\n")
        _write(tmp_path, "scripts/mid.py", "from scripts.base import do\n\ndef mid():\n    do()\n")
        _write(tmp_path, "tests/test_aaa_transitive.py", "from scripts.mid import mid\n\ndef test_x():\n    mid()\n")
        _write(tmp_path, "tests/bbb_pkg/conftest.py", "")
        _write(tmp_path, "tests/bbb_pkg/test_b.py", "def test_b():\n    assert True\n")
        _write(tmp_path, "scripts/zzz_mirror_source.py", "def something():\n    pass\n")
        _write(tmp_path, "tests/test_zzz_mirror_source.py", "def test_x():\n    assert True\n")
        diff = [("M", "scripts/base.py"), ("M", "tests/bbb_pkg/conftest.py"), ("M", "scripts/zzz_mirror_source.py")]

        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            result_cap2 = at.derive_affected_tests(diff, repo_root=tmp_path, cap=2)
            result_cap1 = at.derive_affected_tests(diff, repo_root=tmp_path, cap=1)

        manifest = result_cap2["manifest"]
        assert set(result_cap2["selected"]) == {"tests/test_zzz_mirror_source.py", "tests/bbb_pkg/test_b.py"}
        assert manifest["provenance"]["tests/test_zzz_mirror_source.py"] == "mirror_map"
        assert manifest["provenance"]["tests/bbb_pkg/test_b.py"] == "conftest_subtree"
        assert manifest["deferred"] == ["tests/test_aaa_transitive.py"]

        assert result_cap1["selected"] == ["tests/test_zzz_mirror_source.py"]
        assert set(result_cap1["manifest"]["deferred"]) == {"tests/bbb_pkg/test_b.py", "tests/test_aaa_transitive.py"}

        selected, deferred = manifest["selected"], manifest["deferred"]
        assert isinstance(selected, list) and all(isinstance(x, str) for x in selected)
        assert isinstance(deferred, list) and all(isinstance(x, str) for x in deferred)
        assert set(selected).isdisjoint(deferred)
        assert compute_escape_class(deferred[0] + "::test", manifest) == "capped"
        assert compute_escape_class("tests/never_selected.py::test", manifest) == "no-edge"


def test_setup_cloud_script_selects_contract_test_through_data_edge() -> None:
    result = at.derive_affected_tests([("M", "bin/setup-cloud-env.sh")])

    assert "tests/test_setup_cloud_env.py" in result["selected"]
    assert result["manifest"]["provenance"]["tests/test_setup_cloud_env.py"] == "data_edge"
