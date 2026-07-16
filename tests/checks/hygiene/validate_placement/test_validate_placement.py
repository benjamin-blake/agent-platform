"""Tests for validate_placement() core router/dead-target logic (RS-04 link-validity gate,
docs/contracts/file-router.yaml). Concern-split module 1 of 2 (OPEN RISK 1, rec-2709 Wave 1):
the former 522-SLOC TestValidatePlacement class is split across this module (generic router
behavior) and test_root_allowlists.py (docs-root / scripts-root allowlist enforcement), both
under scripts/checks/hygiene/validate_placement.py's declared _CONCERN_SPLIT_TEST_PACKAGES
package. Retains the original TestValidatePlacement class name (this half's methods keep
their exact pre-move class::function id); the other half is TestValidatePlacementRootAllowlists
(the one permitted class-qualifier id delta for this wave, per the plan's OPEN RISK 1
resolution).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks.hygiene.validate_placement import validate_placement


class TestValidatePlacement:
    """Tests for validate_placement() (RS-04 link-validity gate, docs/contracts/file-router.yaml)."""

    validate_placement = staticmethod(validate_placement)

    @staticmethod
    def _router(tmp_path: Path, content: str) -> Path:
        router = tmp_path / "file-router.yaml"
        router.write_text(content, encoding="utf-8")
        return router

    @staticmethod
    def _mock_ls_files(tracked_paths: list[str]):
        def _run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 0
            result.stdout = "".join(f"{p}\n" for p in tracked_paths)
            result.stderr = ""
            return result

        return _run

    def test_happy_path_zero_dead_targets(self, tmp_path: Path) -> None:
        """A well-formed router with a file target and a directory target and zero dead
        targets passes with an empty failed list (proves directory-prefix resolution works,
        not just exact-file matches)."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: file-target\n"
            "    targets: [docs/ARCHITECTURE.md]\n"
            "  - topic: dir-target\n"
            "    targets: [src/lambdas/]\n",
        )
        with patch(
            "scripts.checks._common.run",
            side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md", "src/lambdas/handler.py"]),
        ):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert failed == []

    def test_dead_target_reports_failure(self, tmp_path: Path) -> None:
        """A non-runtime target absent from the tracked snapshot fails the gate."""
        router = self._router(
            tmp_path,
            "schema_version: 1\nroutes:\n  - topic: bogus-topic\n    targets: [scripts/does_not_exist.py]\n",
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "dead target" in failed[0]
        assert "scripts/does_not_exist.py" in failed[0]

    def test_runtime_row_parent_tracked_passes(self, tmp_path: Path) -> None:
        """A runtime:true row whose target is untracked but whose parent dir is tracked passes."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: recommendations-log\n"
            "    targets: [logs/.recommendations-log.jsonl]\n"
            "    runtime: true\n",
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["logs/.friction-analysis-log.jsonl"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert failed == []

    def test_runtime_row_bogus_parent_fails(self, tmp_path: Path) -> None:
        """A runtime:true row whose parent directory is not tracked at all fails the gate."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: orphan-cache\n"
            "    targets: [nonexistent_dir/.cache.json]\n"
            "    runtime: true\n",
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "runtime target" in failed[0]

    def test_duplicate_topic_fails(self, tmp_path: Path) -> None:
        """Two route objects sharing the same topic string fail the gate. Detected by
        iterating the routes LIST, not by mapping-key uniqueness -- yaml.safe_load would
        silently collapse a topic-keyed mapping, making this gate unconstructable."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: dup-topic\n"
            "    targets: [docs/ARCHITECTURE.md]\n"
            "  - topic: dup-topic\n"
            "    targets: [docs/DECISIONS.md]\n",
        )
        with patch(
            "scripts.checks._common.run",
            side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md", "docs/DECISIONS.md"]),
        ):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "duplicate topic" in failed[0]
        assert "dup-topic" in failed[0]

    def test_missing_router_file_fails(self, tmp_path: Path) -> None:
        """A router_path that does not exist on disk fails the gate (never raises)."""
        failed: list[str] = []
        self.validate_placement(failed, router_path=tmp_path / "does-not-exist.yaml")
        assert len(failed) == 1
        assert "does not exist" in failed[0]

    def test_malformed_yaml_syntax_fails(self, tmp_path: Path) -> None:
        """Unparseable YAML content is a gate failure, never an unhandled exception."""
        router = self._router(tmp_path, "routes: [unclosed\n")
        failed: list[str] = []
        self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "could not read/parse" in failed[0]

    def test_router_not_a_mapping_fails(self, tmp_path: Path) -> None:
        """A top-level YAML list (not a mapping) fails the gate."""
        router = self._router(tmp_path, "- one\n- two\n")
        failed: list[str] = []
        self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "not a YAML mapping" in failed[0]

    def test_routes_not_a_list_fails(self, tmp_path: Path) -> None:
        """A top-level mapping with 'routes' missing (or not a list) fails the gate."""
        router = self._router(tmp_path, "schema_version: 1\n")
        failed: list[str] = []
        self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "'routes' is missing or not a non-empty list" in failed[0]

    def test_route_not_a_mapping_fails(self, tmp_path: Path) -> None:
        """A routes-list entry that is not itself a mapping is a malformed row, not a crash."""
        router = self._router(tmp_path, "schema_version: 1\nroutes:\n  - just-a-string\n")
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files([])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "malformed route" in failed[0]
        assert "not a mapping" in failed[0]

    def test_route_missing_topic_fails(self, tmp_path: Path) -> None:
        """A route missing 'topic' is a malformed row."""
        router = self._router(tmp_path, "schema_version: 1\nroutes:\n  - targets: [docs/ARCHITECTURE.md]\n")
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files([])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "malformed route" in failed[0]
        assert "topic" in failed[0]

    def test_route_missing_targets_fails(self, tmp_path: Path) -> None:
        """A route missing 'targets' is a malformed row."""
        router = self._router(tmp_path, "schema_version: 1\nroutes:\n  - topic: no-targets\n")
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files([])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "malformed route" in failed[0]
        assert "targets" in failed[0]

    def test_git_ls_files_failure_yields_dead_targets(self, tmp_path: Path) -> None:
        """A non-zero git ls-files exit falls back to an empty tracked set -- fails loud on
        every non-runtime target rather than silently passing (Decision 55)."""
        router = self._router(
            tmp_path,
            "schema_version: 1\nroutes:\n  - topic: whatever\n    targets: [docs/ARCHITECTURE.md]\n",
        )

        def _failing_run(cmd: list, **kwargs: object) -> MagicMock:
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = "fatal: not a git repository"
            return result

        with patch("scripts.checks._common.run", side_effect=_failing_run):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "dead target" in failed[0]

    def test_non_string_target_int_fails_without_raising(self, tmp_path: Path) -> None:
        """A non-string (int) element in a targets list is a malformed row, NOT an
        AttributeError -- honours the module's never-raise import-safety contract. A bare
        globals()[name](failed) dispatch in validate.py has no try/except, so a raise here
        would crash the entire validate run and silently skip every later check."""
        router = self._router(
            tmp_path,
            "schema_version: 1\nroutes:\n  - topic: bad-int\n    targets: [42]\n",
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "malformed route" in failed[0]
        assert "non-string/empty target" in failed[0]

    def test_null_target_fails_without_raising(self, tmp_path: Path) -> None:
        """A null (None) element in a targets list is a malformed row, not a crash."""
        router = self._router(
            tmp_path,
            "schema_version: 1\nroutes:\n  - topic: bad-null\n    targets: [null]\n",
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "malformed route" in failed[0]
        assert "non-string/empty target" in failed[0]

    def test_nested_list_target_fails_without_raising(self, tmp_path: Path) -> None:
        """A nested-list element in a targets list is a malformed row, not a crash."""
        router = self._router(
            tmp_path,
            "schema_version: 1\nroutes:\n  - topic: bad-nested\n    targets: [[docs/ARCHITECTURE.md]]\n",
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "malformed route" in failed[0]
        assert "non-string/empty target" in failed[0]

    def test_runtime_target_without_slash_passes(self, tmp_path: Path) -> None:
        """A runtime:true target with no '/' (repo-root-relative, parent == '') passes when
        the tracked snapshot is non-empty -- every path starts with the empty prefix. Covers
        the else-branch of the runtime parent-dir computation."""
        router = self._router(
            tmp_path,
            "schema_version: 1\nroutes:\n  - topic: root-cache\n    targets: [.rootcache.json]\n    runtime: true\n",
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert failed == []
