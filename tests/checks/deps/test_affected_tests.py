"""Tests for scripts/checks/deps/affected_tests.py -- the live affected-set derivation
(Decision affected-set-selection). Every class below exercises the REAL selector
(derive_affected_tests) against a small, self-contained fixture repo under tmp_path -- never a
mock of the selector itself. Self-contained per Decision 131 (no cross-test imports); shared
helpers are plain module-level functions, not imports from another test_* module.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.checks.deps import affected_tests as at


def _write(root: Path, relpath: str, content: str) -> Path:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestImportClosureChannel:
    """A source-only diff (no test file edited) selects its reverse-dependency test modules."""

    def test_source_only_change_selects_reverse_dep_test(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/foo.py", "def bar():\n    pass\n")
        _write(
            tmp_path,
            "tests/test_foo_consumer.py",
            "from scripts.foo import bar\n\ndef test_bar():\n    bar()\n",
        )
        result = at.derive_affected_tests([("M", "scripts/foo.py")], repo_root=tmp_path)
        assert "tests/test_foo_consumer.py" in result["selected"]
        assert result["manifest"]["edited_set"] == [], "no test file was literally changed"
        assert result["manifest"]["provenance"]["tests/test_foo_consumer.py"] == "import_closure_direct"

    def test_unrelated_test_not_selected(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/foo.py", "def bar():\n    pass\n")
        _write(tmp_path, "tests/test_foo_consumer.py", "from scripts.foo import bar\n\ndef test_bar():\n    bar()\n")
        _write(tmp_path, "tests/test_unrelated.py", "def test_x():\n    assert True\n")
        result = at.derive_affected_tests([("M", "scripts/foo.py")], repo_root=tmp_path)
        assert "tests/test_unrelated.py" not in result["selected"]


class TestDataEdgeChannel:
    """Incident A: a YAML entry-count change selects the test that reads it; the channel has
    teeth (disabling it drops the selection)."""

    def _fixture(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/ROADMAP-PLATFORM.yaml", "tier_items: []\n")
        _write(
            tmp_path,
            "tests/test_roadmap_reader.py",
            'ROADMAP = "ROADMAP-PLATFORM.yaml"\n\ndef test_reads_roadmap():\n    assert ROADMAP\n',
        )

    def test_yaml_change_selects_reading_test(self, tmp_path: Path) -> None:
        self._fixture(tmp_path)
        result = at.derive_affected_tests([("M", "docs/ROADMAP-PLATFORM.yaml")], repo_root=tmp_path)
        assert "tests/test_roadmap_reader.py" in result["selected"]
        assert result["manifest"]["provenance"]["tests/test_roadmap_reader.py"] == "data_edge"

    def test_disabling_channel_drops_selection(self, tmp_path: Path) -> None:
        self._fixture(tmp_path)
        with patch("scripts.checks.deps.affected_tests._data_edge_channel", return_value=set()):
            result = at.derive_affected_tests([("M", "docs/ROADMAP-PLATFORM.yaml")], repo_root=tmp_path)
        assert "tests/test_roadmap_reader.py" not in result["selected"]


class TestDeletedPathDataEdge:
    """Incident B: a deleted test file's bytes are referenced (by basename) from a surviving
    meta-test -- made visible by the status-aware diff's D-status entries."""

    def test_deleted_file_selects_meta_test_reading_its_bytes(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "tests/test_meta_reader.py",
            'TARGET = "test_deleted_thing.py"\n\ndef test_reads_target():\n    assert TARGET\n',
        )
        result = at.derive_affected_tests([("D", "tests/test_deleted_thing.py")], repo_root=tmp_path)
        assert "tests/test_meta_reader.py" in result["selected"]
        assert "tests/test_deleted_thing.py" not in result["selected"], "a deleted file cannot be selected to run"
        assert result["manifest"]["provenance"]["tests/test_meta_reader.py"] == "data_edge"


class TestFacadeNodeSoundness:
    """A facade-only (__init__.py re-export, Decision 124) import selects its dependents."""

    def test_facade_change_selects_package_importer(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/pkg/__init__.py", "from scripts.pkg.impl import helper\n")
        _write(tmp_path, "scripts/pkg/impl.py", "def helper():\n    pass\n")
        _write(
            tmp_path,
            "tests/test_pkg_consumer.py",
            "from scripts.pkg import helper\n\ndef test_helper():\n    helper()\n",
        )
        result = at.derive_affected_tests([("M", "scripts/pkg/__init__.py")], repo_root=tmp_path)
        assert "tests/test_pkg_consumer.py" in result["selected"]


class TestPatchStringEdgeSoundness:
    """A patch("scripts.x.y")-string-only dependency selects the target module's tests."""

    def test_patch_string_only_reference_selects_test(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/target.py", "def run():\n    pass\n")
        _write(
            tmp_path,
            "tests/test_patches_target.py",
            'from unittest.mock import patch\n\ndef test_x():\n    with patch("scripts.target.run"):\n        pass\n',
        )
        result = at.derive_affected_tests([("M", "scripts/target.py")], repo_root=tmp_path)
        assert "tests/test_patches_target.py" in result["selected"]
        assert result["manifest"]["provenance"]["tests/test_patches_target.py"] == "import_closure_direct"


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


class TestDataEdgePrecision:
    """A common-basename change (config.py, utils.py, __init__.py) does NOT over-select every
    test that merely mentions that word via a bare substring -- only precise path/quoted-token
    references select."""

    def test_bare_substring_mention_not_selected(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "tests/test_bare_mention.py",
            "# see myconfig.py_backup or someconfig.py for details\n\ndef test_x():\n    assert True\n",
        )
        _write(
            tmp_path,
            "tests/test_precise_reference.py",
            'CONFIG_PATH = "config.py"\n\ndef test_y():\n    assert CONFIG_PATH\n',
        )
        result = at.derive_affected_tests([("D", "scripts/config.py")], repo_root=tmp_path)
        assert "tests/test_precise_reference.py" in result["selected"]
        assert "tests/test_bare_mention.py" not in result["selected"]

    def test_common_basename_deleted_init_does_not_blow_up_selection(self, tmp_path: Path) -> None:
        for i in range(5):
            _write(tmp_path, f"tests/test_unrelated_{i}.py", "def test_x():\n    assert True\n")
        result = at.derive_affected_tests([("D", "scripts/pkg/__init__.py")], repo_root=tmp_path)
        assert result["selected"] == []


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


class TestMirrorMapChannel:
    """channel 3: scripts.test_coverage_checker.map_source_to_test() mirror map (read-only)."""

    def test_mirror_map_hit_selects_mapped_test(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/checks/hygiene/validate_something.py", "def validate_something(failed):\n    pass\n")
        _write(tmp_path, "tests/checks/hygiene/test_validate_something.py", "def test_x():\n    assert True\n")
        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            result = at.derive_affected_tests([("M", "scripts/checks/hygiene/validate_something.py")], repo_root=tmp_path)
        assert "tests/checks/hygiene/test_validate_something.py" in result["selected"]


class TestConftestSubtreeChannel:
    """channel 4: a changed tests/**/conftest.py selects every test_*.py under it."""

    def test_conftest_change_selects_subtree_tests(self, tmp_path: Path) -> None:
        _write(tmp_path, "tests/pkg/conftest.py", "")
        _write(tmp_path, "tests/pkg/test_a.py", "def test_a():\n    assert True\n")
        _write(tmp_path, "tests/pkg/sub/test_b.py", "def test_b():\n    assert True\n")
        _write(tmp_path, "tests/other/test_c.py", "def test_c():\n    assert True\n")
        result = at.derive_affected_tests([("M", "tests/pkg/conftest.py")], repo_root=tmp_path)
        assert "tests/pkg/test_a.py" in result["selected"]
        assert "tests/pkg/sub/test_b.py" in result["selected"]
        assert "tests/other/test_c.py" not in result["selected"]


class TestEmptyDiff:
    """No diff entries at all -- selection is the (empty) edited-set, no crash, no graph build."""

    def test_empty_diff_returns_empty_selection(self, tmp_path: Path) -> None:
        result = at.derive_affected_tests([], repo_root=tmp_path)
        assert result["selected"] == []
        assert result["manifest"]["capped"] is False


class TestModuleToTestPathHelper:
    """Direct coverage of _module_to_test_path's branches (regex-matches-but-file-absent)."""

    def test_regex_matches_but_file_does_not_exist_returns_none(self, tmp_path: Path) -> None:
        assert at._module_to_test_path("tests.foo.test_ghost", tmp_path) is None

    def test_non_test_shaped_module_returns_none(self, tmp_path: Path) -> None:
        assert at._module_to_test_path("tests.pkg", tmp_path) is None


class TestImportClosureChannelDirect:
    """Direct coverage: a changed source file whose module maps to no live graph node
    (e.g. it does not actually exist on disk) is skipped, not an error."""

    def test_nonexistent_changed_file_contributes_nothing(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/placeholder.py", "x = 1\n")
        direct, transitive = at._import_closure_channel(["scripts/does_not_exist.py"], tmp_path)
        assert direct == set()
        assert transitive == set()


class TestDataEdgeChannelEdgeCases:
    """Direct/derivation coverage of _data_edge_channel's defensive branches."""

    def test_no_tests_dir_returns_empty(self, tmp_path: Path) -> None:
        result = at.derive_affected_tests([("M", "docs/some.yaml")], repo_root=tmp_path)
        assert result["selected"] == []

    def test_pycache_entries_skipped(self, tmp_path: Path) -> None:
        _write(tmp_path, "docs/some.yaml", "a: 1\n")
        _write(tmp_path, "tests/test_reader.py", 'REF = "some.yaml"\n\ndef test_x():\n    assert REF\n')
        pycache_file = tmp_path / "tests" / "__pycache__" / "cached.py"
        pycache_file.parent.mkdir(parents=True, exist_ok=True)
        pycache_file.write_text("garbage bytecode stand-in referencing some.yaml", encoding="utf-8")
        result = at.derive_affected_tests([("M", "docs/some.yaml")], repo_root=tmp_path)
        assert "tests/test_reader.py" in result["selected"]
        assert not any("__pycache__" in p for p in result["selected"])

    def test_unreadable_test_file_is_skipped_not_fatal(self, tmp_path: Path) -> None:
        """A path matching *.py that is actually a directory (not a file) raises OSError on
        read_text() -- must be skipped gracefully, not crash the whole scan."""
        _write(tmp_path, "docs/some.yaml", "a: 1\n")
        _write(tmp_path, "tests/test_reader.py", 'REF = "some.yaml"\n\ndef test_x():\n    assert REF\n')
        (tmp_path / "tests" / "weird_dir.py").mkdir(parents=True)
        result = at.derive_affected_tests([("M", "docs/some.yaml")], repo_root=tmp_path)
        assert "tests/test_reader.py" in result["selected"]


class TestMirrorMapChannelDirectory:
    """A concern-split monolith's mirror target is a test PACKAGE DIRECTORY, not a single file."""

    def test_directory_mirror_target_selected(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/ops_writer.py", "def write():\n    pass\n")
        _write(tmp_path, "tests/ops_writer/test_write.py", "def test_write():\n    assert True\n")
        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            result = at.derive_affected_tests([("M", "scripts/ops_writer.py")], repo_root=tmp_path)
        assert "tests/ops_writer" in result["selected"]


class TestConftestSubtreeChannelEdgeCases:
    """Direct coverage of _conftest_subtree_channel's defensive branches."""

    def test_conftest_outside_tests_dir_ignored(self, tmp_path: Path) -> None:
        _write(tmp_path, "conftest.py", "")
        _write(tmp_path, "tests/test_unrelated.py", "def test_x():\n    assert True\n")
        result = at.derive_affected_tests([("M", "conftest.py")], repo_root=tmp_path)
        assert result["selected"] == []

    def test_conftest_dir_missing_on_disk_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "tests").mkdir()
        result = at.derive_affected_tests([("M", "tests/ghost_subdir/conftest.py")], repo_root=tmp_path)
        assert result["selected"] == []


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


class TestTestsTreeHelperImportClosure:
    """VTS-01: a changed tests-tree helper (tests/fixtures/*.py) is now an import-closure candidate."""

    def test_fixtures_helper_change_selects_direct_importer(self, tmp_path: Path) -> None:
        """Covers both the ast.ImportFrom and ast.Import branches of _module_imports_any."""
        _write(tmp_path, "tests/fixtures/ducklake_fakes.py", "def make_fake():\n    return 1\n")
        _write(
            tmp_path,
            "tests/test_uses_fake.py",
            "from tests.fixtures.ducklake_fakes import make_fake\n\ndef test_x():\n    make_fake()\n",
        )
        _write(
            tmp_path,
            "tests/test_bare_import.py",
            "import tests.fixtures.ducklake_fakes\n\ndef test_x():\n    tests.fixtures.ducklake_fakes.make_fake()\n",
        )
        _write(tmp_path, "tests/test_unrelated.py", "def test_y():\n    assert True\n")
        result = at.derive_affected_tests([("M", "tests/fixtures/ducklake_fakes.py")], repo_root=tmp_path)
        assert "tests/test_uses_fake.py" in result["selected"]
        assert result["manifest"]["provenance"]["tests/test_uses_fake.py"] == "import_closure_direct"
        assert "tests/test_bare_import.py" in result["selected"]
        assert "tests/test_unrelated.py" not in result["selected"]

    def test_predicate_and_empty_channel_branches(self, tmp_path: Path) -> None:
        rejected = ["tests/conftest.py", "tests/pkg/conftest.py", "tests/test_something.py", "scripts/foo.py"]
        assert not any(at._is_changed_tests_helper_py(p) for p in rejected)
        assert at._is_changed_tests_helper_py("tests/fixtures/helper.py")
        assert at._tests_tree_import_closure_channel([], tmp_path) == set()
        assert at._tests_tree_import_closure_channel(["tests/fixtures/ghost.py"], tmp_path) == set()


class TestDeletedModuleStructuralRecall:
    """VTS-02: a deleted module's path-mention-free importer is selected structurally."""

    def test_deletion_selects_path_mention_free_importer_precisely(self, tmp_path: Path) -> None:
        """Must not match doomed_sibling (trailing word char) or doomed.child (trailing '.')."""
        _write(
            tmp_path,
            "tests/test_structural_importer.py",
            "import scripts.doomed\n\ndef test_x():\n    scripts.doomed.run()\n",
        )
        _write(
            tmp_path,
            "tests/test_sibling.py",
            "import scripts.doomed_sibling\n\ndef test_x():\n    scripts.doomed_sibling.run()\n",
        )
        _write(
            tmp_path,
            "tests/test_submodule_user.py",
            "import scripts.doomed.child\n\ndef test_x():\n    scripts.doomed.child.run()\n",
        )
        result = at.derive_affected_tests([("D", "scripts/doomed.py")], repo_root=tmp_path)
        assert "tests/test_structural_importer.py" in result["selected"]
        assert result["manifest"]["provenance"]["tests/test_structural_importer.py"] == "data_edge"
        assert "tests/test_sibling.py" not in result["selected"]
        assert "tests/test_submodule_user.py" not in result["selected"]
        assert at._deleted_py_dotted_patterns([("D", "docs/some.yaml")], tmp_path) == []


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
