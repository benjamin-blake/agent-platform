"""Tests for validate_placement()'s docs-root and scripts-root allowlist enforcement
(RS-03 / RS-01 completion). Concern-split module 2 of 2 (OPEN RISK 1, rec-2709 Wave 1) -- see
test_validate_placement.py for the core router/dead-target logic half and the class-naming
rationale. This class is renamed from the original TestValidatePlacement to
TestValidatePlacementRootAllowlists (the one permitted class-qualifier id delta for this
wave's OPEN RISK 1 resolution -- method bodies are otherwise verbatim).
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks.hygiene.validate_placement import (
    _docs_root_stray_files,
    _load_docs_root_allowlist,
    _load_scripts_root_allowlist,
    _scripts_root_stray_files,
    validate_placement,
)


class TestValidatePlacementRootAllowlists:
    """Tests for validate_placement()'s docs-root and scripts-root allowlist enforcement."""

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

    # -- Docs-root allowlist (RS-03) -- _load_docs_root_allowlist direct unit tests --------

    load_docs_root_allowlist = staticmethod(_load_docs_root_allowlist)
    docs_root_stray_files = staticmethod(_docs_root_stray_files)

    def test_docs_root_allowlist_absent_key_skips(self, tmp_path: Path) -> None:
        """No docs_root_allowlist key at all -> (None, [], None): the back-compat skip signal."""
        router = self._router(tmp_path, "schema_version: 1\nroutes:\n  - topic: t\n    targets: [docs/ARCHITECTURE.md]\n")
        allowed, globs, err = self.load_docs_root_allowlist(router)
        assert allowed is None
        assert globs == []
        assert err is None

    def test_docs_root_allowlist_well_formed(self, tmp_path: Path) -> None:
        """A well-formed block parses to (set, list, None)."""
        router = self._router(
            tmp_path,
            "docs_root_allowlist:\n  allowed_files: [ARCHITECTURE.md, CLAUDE.md]\n  grandfathered_globs: ['INTENT-*.md']\n",
        )
        allowed, globs, err = self.load_docs_root_allowlist(router)
        assert allowed == {"ARCHITECTURE.md", "CLAUDE.md"}
        assert globs == ["INTENT-*.md"]
        assert err is None

    def test_docs_root_allowlist_block_not_a_mapping_fails(self, tmp_path: Path) -> None:
        """docs_root_allowlist present but not a mapping (e.g. a bare scalar) is malformed."""
        router = self._router(tmp_path, "docs_root_allowlist: not-a-mapping\n")
        allowed, globs, err = self.load_docs_root_allowlist(router)
        assert allowed is None
        assert globs == []
        assert err is not None
        assert "not a mapping" in err

    def test_docs_root_allowlist_allowed_files_not_a_list_fails(self, tmp_path: Path) -> None:
        """allowed_files as a scalar (not a list) is malformed."""
        router = self._router(tmp_path, "docs_root_allowlist:\n  allowed_files: not-a-list\n")
        allowed, globs, err = self.load_docs_root_allowlist(router)
        assert allowed is None
        assert err is not None
        assert "allowed_files" in err

    def test_docs_root_allowlist_allowed_files_non_string_entry_fails(self, tmp_path: Path) -> None:
        """A non-string element in allowed_files (e.g. an int) is malformed."""
        router = self._router(tmp_path, "docs_root_allowlist:\n  allowed_files: [ARCHITECTURE.md, 42]\n")
        allowed, globs, err = self.load_docs_root_allowlist(router)
        assert allowed is None
        assert err is not None
        assert "allowed_files" in err

    def test_docs_root_allowlist_globs_not_a_list_fails(self, tmp_path: Path) -> None:
        """grandfathered_globs as a scalar (not a list) is malformed."""
        router = self._router(
            tmp_path,
            "docs_root_allowlist:\n  allowed_files: [ARCHITECTURE.md]\n  grandfathered_globs: not-a-list\n",
        )
        allowed, globs, err = self.load_docs_root_allowlist(router)
        assert allowed is None
        assert err is not None
        assert "grandfathered_globs" in err

    def test_docs_root_allowlist_globs_non_string_entry_fails(self, tmp_path: Path) -> None:
        """A non-string (null) element in grandfathered_globs is malformed."""
        router = self._router(
            tmp_path,
            "docs_root_allowlist:\n  allowed_files: [ARCHITECTURE.md]\n  grandfathered_globs: [null]\n",
        )
        allowed, globs, err = self.load_docs_root_allowlist(router)
        assert allowed is None
        assert err is not None
        assert "grandfathered_globs" in err

    def test_docs_root_allowlist_unparseable_file_fails(self, tmp_path: Path) -> None:
        """Unparseable YAML content is a gate failure, never an unhandled exception."""
        router = self._router(tmp_path, "docs_root_allowlist: [unclosed\n")
        allowed, globs, err = self.load_docs_root_allowlist(router)
        assert allowed is None
        assert err is not None
        assert "could not read/parse" in err

    def test_docs_root_allowlist_top_level_non_dict_skips(self, tmp_path: Path) -> None:
        """A top-level YAML list (not a mapping) is treated the same as an absent key: skip,
        never a crash -- _load_router already fails this shape independently, so this path is
        only reachable via direct unit test of the helper."""
        router = self._router(tmp_path, "- one\n- two\n")
        allowed, globs, err = self.load_docs_root_allowlist(router)
        assert allowed is None
        assert globs == []
        assert err is None

    # -- Docs-root allowlist (RS-03) -- _docs_root_stray_files direct unit tests -----------

    def test_docs_root_stray_files_mixed_returns_only_stray(self) -> None:
        """A mix of an allowed file, a grandfathered INTENT-*.md, a non-docs path, a nested
        docs/<subdir>/ file, and a genuine stray returns ONLY the stray."""
        tracked = {
            "docs/ARCHITECTURE.md",
            "docs/INTENT-foo.md",
            "docs/contracts/file-router.yaml",
            "src/lambdas/handler.py",
            "docs/STRAY.md",
        }
        strays = self.docs_root_stray_files(tracked, {"ARCHITECTURE.md"}, ["INTENT-*.md"])
        assert strays == ["docs/STRAY.md"]

    def test_docs_root_stray_files_all_covered_returns_empty(self) -> None:
        """When every depth-1 docs/ file is allowlisted or grandfathered, no strays."""
        tracked = {"docs/ARCHITECTURE.md", "docs/INTENT-foo.md", "docs/contracts/file-router.yaml"}
        strays = self.docs_root_stray_files(tracked, {"ARCHITECTURE.md"}, ["INTENT-*.md"])
        assert strays == []

    # -- Docs-root allowlist (RS-03) -- integration via validate_placement() ---------------

    def test_docs_root_allowlist_integration_happy_path(self, tmp_path: Path) -> None:
        """A router with a well-formed docs_root_allowlist and a fully-covered docs/ root
        snapshot passes with an empty failed list (both RS-04 and RS-03 blocks PASS)."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: file-target\n"
            "    targets: [docs/ARCHITECTURE.md]\n"
            "docs_root_allowlist:\n"
            "  allowed_files: [ARCHITECTURE.md]\n"
            "  grandfathered_globs: ['INTENT-*.md']\n",
        )
        tracked = ["docs/ARCHITECTURE.md", "docs/INTENT-x.md", "docs/contracts/file-router.yaml"]
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(tracked)):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert failed == []

    def test_docs_root_allowlist_integration_stray_fails(self, tmp_path: Path) -> None:
        """An out-of-class docs-root file in the tracked snapshot fails with a message
        naming the file and citing RS-03."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: file-target\n"
            "    targets: [docs/ARCHITECTURE.md]\n"
            "docs_root_allowlist:\n"
            "  allowed_files: [ARCHITECTURE.md]\n"
            "  grandfathered_globs: ['INTENT-*.md']\n",
        )
        tracked = [
            "docs/ARCHITECTURE.md",
            "docs/INTENT-x.md",
            "docs/contracts/file-router.yaml",
            "docs/STRAY.md",
        ]
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(tracked)):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "docs/STRAY.md" in failed[0]
        assert "RS-03" in failed[0]

    def test_docs_root_allowlist_backcompat_absent_key_no_stray_failure(self, tmp_path: Path) -> None:
        """A router with NO docs_root_allowlist key: the docs-root scan SKIPs (no failure for
        docs/STRAY.md) while link-validity still runs and still passes -- proves the additive
        change is back-compat with routers that predate this key."""
        router = self._router(
            tmp_path,
            "schema_version: 1\nroutes:\n  - topic: file-target\n    targets: [docs/ARCHITECTURE.md]\n",
        )
        tracked = ["docs/ARCHITECTURE.md", "docs/STRAY.md"]
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(tracked)):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert failed == []

    def test_docs_root_allowlist_integration_malformed_fails(self, tmp_path: Path) -> None:
        """A present-but-malformed docs_root_allowlist (a string, not a mapping) is a single
        gate failure carrying the malformed message."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: file-target\n"
            "    targets: [docs/ARCHITECTURE.md]\n"
            'docs_root_allowlist: "x"\n',
        )
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(["docs/ARCHITECTURE.md"])):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "docs_root_allowlist is not a mapping" in failed[0]

    def test_docs_root_allowlist_claude_md_not_flagged(self, tmp_path: Path) -> None:
        """Self-consistency regression (Decision 86 mechanism-interaction): docs/CLAUDE.md,
        added by this same phase, must be allowlisted and not flagged as a stray by the very
        check it introduces."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: file-target\n"
            "    targets: [docs/ARCHITECTURE.md]\n"
            "docs_root_allowlist:\n"
            "  allowed_files: [ARCHITECTURE.md, CLAUDE.md]\n"
            "  grandfathered_globs: []\n",
        )
        tracked = ["docs/ARCHITECTURE.md", "docs/CLAUDE.md"]
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(tracked)):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert failed == []

    # -- Scripts-root allowlist (RS-01 completion) -- _load_scripts_root_allowlist direct unit tests --

    load_scripts_root_allowlist = staticmethod(_load_scripts_root_allowlist)
    scripts_root_stray_files = staticmethod(_scripts_root_stray_files)

    def test_scripts_root_allowlist_absent_key_skips(self, tmp_path: Path) -> None:
        """No scripts_root_allowlist key at all -> (None, [], None): the back-compat skip signal."""
        router = self._router(tmp_path, "schema_version: 1\nroutes:\n  - topic: t\n    targets: [docs/ARCHITECTURE.md]\n")
        allowed, globs, err = self.load_scripts_root_allowlist(router)
        assert allowed is None
        assert globs == []
        assert err is None

    def test_scripts_root_allowlist_well_formed(self, tmp_path: Path) -> None:
        """A well-formed block parses to (set, list, None)."""
        router = self._router(
            tmp_path,
            "scripts_root_allowlist:\n"
            "  allowed_files: [validate.py, CLAUDE.md]\n"
            "  grandfathered_globs: ['ops_data_portal.py']\n",
        )
        allowed, globs, err = self.load_scripts_root_allowlist(router)
        assert allowed == {"validate.py", "CLAUDE.md"}
        assert globs == ["ops_data_portal.py"]
        assert err is None

    def test_scripts_root_allowlist_block_not_a_mapping_fails(self, tmp_path: Path) -> None:
        """scripts_root_allowlist present but not a mapping (e.g. a bare scalar) is malformed."""
        router = self._router(tmp_path, "scripts_root_allowlist: not-a-mapping\n")
        allowed, globs, err = self.load_scripts_root_allowlist(router)
        assert allowed is None
        assert globs == []
        assert err is not None
        assert "not a mapping" in err

    def test_scripts_root_allowlist_allowed_files_not_a_list_fails(self, tmp_path: Path) -> None:
        """allowed_files as a scalar (not a list) is malformed."""
        router = self._router(tmp_path, "scripts_root_allowlist:\n  allowed_files: not-a-list\n")
        allowed, globs, err = self.load_scripts_root_allowlist(router)
        assert allowed is None
        assert err is not None
        assert "allowed_files" in err

    def test_scripts_root_allowlist_globs_non_string_entry_fails(self, tmp_path: Path) -> None:
        """A non-string (null) element in grandfathered_globs is malformed."""
        router = self._router(
            tmp_path,
            "scripts_root_allowlist:\n  allowed_files: [validate.py]\n  grandfathered_globs: [null]\n",
        )
        allowed, globs, err = self.load_scripts_root_allowlist(router)
        assert allowed is None
        assert err is not None
        assert "grandfathered_globs" in err

    # -- Scripts-root allowlist (RS-01 completion) -- _scripts_root_stray_files direct unit tests --

    def test_scripts_root_stray_files_mixed_returns_only_stray(self) -> None:
        """A mix of an allowed file, a grandfathered ops_* entry, a non-scripts path, a nested
        scripts/<subdir>/ file, and a genuine stray returns ONLY the stray."""
        tracked = {
            "scripts/validate.py",
            "scripts/ops_data_portal.py",
            "scripts/llm/client.py",
            "src/lambdas/handler.py",
            "scripts/STRAY.py",
        }
        strays = self.scripts_root_stray_files(tracked, {"validate.py"}, ["ops_data_portal.py", "ops_writer.py"])
        assert strays == ["scripts/STRAY.py"]

    def test_scripts_root_stray_files_all_covered_returns_empty(self) -> None:
        """When every depth-1 scripts/ file is allowlisted or grandfathered, no strays."""
        tracked = {"scripts/validate.py", "scripts/ops_data_portal.py", "scripts/llm/client.py"}
        strays = self.scripts_root_stray_files(tracked, {"validate.py"}, ["ops_data_portal.py", "ops_writer.py"])
        assert strays == []

    # -- Scripts-root allowlist (RS-01 completion) -- integration via validate_placement() ---------

    def test_scripts_root_allowlist_integration_happy_path(self, tmp_path: Path) -> None:
        """A router with a well-formed scripts_root_allowlist and a fully-covered scripts/ root
        snapshot passes with an empty failed list (both RS-04 and RS-01 blocks PASS)."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: file-target\n"
            "    targets: [scripts/validate.py]\n"
            "scripts_root_allowlist:\n"
            "  allowed_files: [validate.py]\n"
            "  grandfathered_globs: ['ops_data_portal.py', 'ops_writer.py']\n",
        )
        tracked = ["scripts/validate.py", "scripts/ops_data_portal.py", "scripts/ops_writer.py", "scripts/llm/client.py"]
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(tracked)):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert failed == []

    def test_scripts_root_allowlist_integration_stray_fails(self, tmp_path: Path) -> None:
        """An out-of-class scripts-root file in the tracked snapshot fails with a message
        naming the file and citing RS-01."""
        router = self._router(
            tmp_path,
            "schema_version: 1\n"
            "routes:\n"
            "  - topic: file-target\n"
            "    targets: [scripts/validate.py]\n"
            "scripts_root_allowlist:\n"
            "  allowed_files: [validate.py]\n"
            "  grandfathered_globs: ['ops_data_portal.py']\n",
        )
        tracked = ["scripts/validate.py", "scripts/ops_data_portal.py", "scripts/STRAY.py"]
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(tracked)):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert len(failed) == 1
        assert "scripts/STRAY.py" in failed[0]
        assert "RS-01" in failed[0]

    def test_scripts_root_allowlist_backcompat_absent_key_no_stray_failure(self, tmp_path: Path) -> None:
        """A router with NO scripts_root_allowlist key: the scripts-root scan SKIPs (no failure
        for scripts/STRAY.py) while link-validity still runs and still passes -- proves the
        additive change is back-compat with routers that predate this key."""
        router = self._router(
            tmp_path,
            "schema_version: 1\nroutes:\n  - topic: file-target\n    targets: [scripts/validate.py]\n",
        )
        tracked = ["scripts/validate.py", "scripts/STRAY.py"]
        with patch("scripts.checks._common.run", side_effect=self._mock_ls_files(tracked)):
            failed: list[str] = []
            self.validate_placement(failed, router_path=router)
        assert failed == []
