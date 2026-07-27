"""Per-channel selection tests for scripts/checks/deps/affected_tests.py (Decision
affected-set-selection). Every class below exercises the REAL selector (derive_affected_tests)
against a small, self-contained fixture repo under tmp_path -- never a mock of the selector
itself. Split from tests/checks/deps/test_affected_tests.py (Decision 128 SLOC decomposition,
concern-split: per-channel derivation vs. tests/checks/deps/affected_tests/test_derivation.py's
aggregation/cap/manifest/invariant tests).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.deps import affected_tests as at
from tests.fixtures.affected_tests_helpers import write_file as _write


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


class TestMirrorMapChannel:
    """channel 3: scripts.test_coverage_checker.map_source_to_test() mirror map (read-only)."""

    def test_mirror_map_hit_selects_mapped_test(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/checks/hygiene/validate_something.py", "def validate_something(failed):\n    pass\n")
        _write(tmp_path, "tests/checks/hygiene/test_validate_something.py", "def test_x():\n    assert True\n")
        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            result = at.derive_affected_tests([("M", "scripts/checks/hygiene/validate_something.py")], repo_root=tmp_path)
        assert "tests/checks/hygiene/test_validate_something.py" in result["selected"]


class TestMirrorMapChannelDirectory:
    """A concern-split mirror package contributes file-grained affected-set entries."""

    def test_directory_mirror_target_expands_to_test_modules(self, tmp_path: Path) -> None:
        _write(tmp_path, "scripts/ops_writer.py", "def write():\n    pass\n")
        _write(tmp_path, "tests/ops_writer/test_write.py", "def test_write():\n    assert True\n")
        _write(tmp_path, "tests/ops_writer/nested/test_retry.py", "def test_retry():\n    assert True\n")
        _write(tmp_path, "tests/ops_writer/helper.py", "VALUE = 1\n")
        _write(tmp_path, "tests/ops_writer/__pycache__/test_cached.py", "garbage\n")
        with patch("scripts.test_coverage_checker.ROOT", tmp_path):
            result = at.derive_affected_tests([("M", "scripts/ops_writer.py")], repo_root=tmp_path)
        assert "tests/ops_writer/test_write.py" in result["selected"]
        assert "tests/ops_writer/nested/test_retry.py" in result["selected"]
        assert "tests/ops_writer" not in result["selected"]
        assert "tests/ops_writer/helper.py" not in result["selected"]
        assert not any("__pycache__" in path for path in result["selected"])


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
