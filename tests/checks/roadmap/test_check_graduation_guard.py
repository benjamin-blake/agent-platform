"""Tests for _check_graduation_guard() / _extract_enforced_map() (check_graduation_guard.py)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from scripts.checks import registry
from scripts.checks.roadmap.check_graduation_guard import _check_graduation_guard, _extract_enforced_map


class TestExtractEnforcedMap:
    """Unit tests for _extract_enforced_map() YAML parser."""

    def test_empty_string_returns_empty(self) -> None:
        assert _extract_enforced_map("") == {}

    def test_invalid_yaml_returns_empty(self) -> None:
        assert _extract_enforced_map("{invalid: [yaml: content}") == {}

    def test_no_tables_key_returns_empty(self) -> None:
        assert _extract_enforced_map("database: db\n") == {}

    def test_row_count_enforced_false(self) -> None:
        yaml_text = "tables:\n  t:\n    row_count:\n      min: 1\n      enforced: false\n"
        result = _extract_enforced_map(yaml_text)
        assert result[("t", None, "row_count")] is False

    def test_row_count_default_true(self) -> None:
        yaml_text = "tables:\n  t:\n    row_count:\n      min: 1\n"
        result = _extract_enforced_map(yaml_text)
        assert result[("t", None, "row_count")] is True

    def test_recency_enforced(self) -> None:
        yaml_text = "tables:\n  t:\n    recency:\n      column: ts\n      enforced: false\n"
        result = _extract_enforced_map(yaml_text)
        assert result[("t", "ts", "recency")] is False

    def test_bare_string_test_defaults_true(self) -> None:
        yaml_text = "tables:\n  t:\n    columns:\n      c:\n        tests:\n          - not_null\n"
        result = _extract_enforced_map(yaml_text)
        assert result[("t", "c", "not_null")] is True

    def test_dict_test_with_enforced(self) -> None:
        yaml_text = (
            "tables:\n  t:\n    columns:\n      c:\n        tests:\n"
            "          - accepted_values:\n              values: [a]\n              enforced: false\n"
        )
        result = _extract_enforced_map(yaml_text)
        assert result[("t", "c", "accepted_values")] is False

    def test_dict_test_params_not_dict(self) -> None:
        yaml_text = "tables:\n  t:\n    columns:\n      c:\n        tests:\n          - not_null: null\n"
        result = _extract_enforced_map(yaml_text)
        assert result[("t", "c", "not_null")] is True

    def test_non_dict_table_def_skipped(self) -> None:
        yaml_text = "tables:\n  t: null\n"
        result = _extract_enforced_map(yaml_text)
        assert result == {}

    def test_non_dict_col_def_skipped(self) -> None:
        yaml_text = "tables:\n  t:\n    columns:\n      c: null\n"
        result = _extract_enforced_map(yaml_text)
        assert result == {}


class TestGraduationGuard:
    """Tests for _check_graduation_guard() -- enforced flip validation."""

    _OLD_YAML_ENFORCED_FALSE = (
        "tables:\n"
        "  tbl:\n"
        "    columns:\n"
        "      col:\n"
        "        tests:\n"
        "          - accepted_values:\n"
        "              values: [a]\n"
        "              enforced: false\n"
    )
    _NEW_YAML_ENFORCED_TRUE = (
        "tables:\n"
        "  tbl:\n"
        "    columns:\n"
        "      col:\n"
        "        tests:\n"
        "          - accepted_values:\n"
        "              values: [a]\n"
        "              enforced: true\n"
    )

    def _write_dq_latest(self, tmp_path: Path, checks: list) -> None:

        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True, exist_ok=True)
        (dq_dir / "dq-latest.json").write_text(
            json.dumps({"verdict": "FAIL", "checks": checks}),
            encoding="utf-8",
        )

    def _write_new_yaml(self, tmp_path: Path, content: str) -> None:
        yaml_file = tmp_path / "config" / "agent" / "data_quality" / "test.yaml"
        yaml_file.parent.mkdir(parents=True, exist_ok=True)
        yaml_file.write_text(content, encoding="utf-8")

    def _make_run(self, old_yaml: str = "", git_show_rc: int = 0, no_changes: bool = False):
        """Keyed on "show" alone (not "HEAD:") -- the guard now derives its old-content read from
        the same committed, push-aware base as its changed-file diff (Decision 170), never the
        literal "HEAD". The "--show-current" branch is checked first, so it still claims the
        push_context_base() branch-name probe before this broader "show" match would."""

        def _run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            joined = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
            if "--show-current" in joined:
                result.stdout = "agent/test\n"
            elif "--name-only" in joined:
                result.stdout = "" if no_changes else "config/agent/data_quality/test.yaml\n"
            elif "show" in joined:
                result.stdout = old_yaml
                result.returncode = git_show_rc
            else:
                result.stdout = ""
            return result

        return _run

    def test_blocks_flip_when_fail(self, tmp_path: Path) -> None:
        """Blocks enforced:false -> enforced:true flip when verdict is FAIL."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "accepted_values", "verdict": "FAIL"}],
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML_ENFORCED_FALSE)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert len(failed) == 1
        assert "tbl.col.accepted_values" in failed[0]
        assert "enforced:true" in failed[0]

    def test_allows_flip_when_pass(self, tmp_path: Path) -> None:
        """Allows enforced:false -> enforced:true flip when verdict is PASS."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "accepted_values", "verdict": "PASS"}],
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML_ENFORCED_FALSE)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []

    def test_warns_no_block_missing_dq_file(self, tmp_path: Path, capsys) -> None:
        """Warns but does not block when dq-latest.json is missing."""
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run()),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []
        assert "missing" in capsys.readouterr().out

    def test_warns_no_block_no_checks_array(self, tmp_path: Path, capsys) -> None:
        """Warns but does not block when dq-latest.json has no 'checks' array."""

        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        (dq_dir / "dq-latest.json").write_text(json.dumps({"verdict": "FAIL"}), encoding="utf-8")
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run()),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []
        assert "checks" in capsys.readouterr().out

    def test_warns_no_block_on_skip_verdict(self, tmp_path: Path, capsys) -> None:
        """Treats SKIP verdict as inconclusive -- warns but does not block."""
        old_yaml = (
            "tables:\n  tbl:\n    columns:\n      col:\n        tests:\n          - not_null:\n              enforced: false\n"
        )
        new_yaml = (
            "tables:\n  tbl:\n    columns:\n      col:\n        tests:\n          - not_null:\n              enforced: true\n"
        )
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "not_null", "verdict": "SKIP"}],
        )
        self._write_new_yaml(tmp_path, new_yaml)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=old_yaml)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []
        assert "SKIP" in capsys.readouterr().out

    def test_blocks_new_enforced_true_when_fail(self, tmp_path: Path) -> None:
        """Blocks a new check added directly as enforced:true when verdict is FAIL."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "accepted_values", "verdict": "FAIL"}],
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(git_show_rc=1)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert len(failed) == 1
        assert "tbl.col.accepted_values" in failed[0]

    def test_no_dq_yaml_changes_returns_early(self, tmp_path: Path) -> None:
        """Returns without loading dq-latest.json when no YAML files changed."""
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(no_changes=True)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []

    def test_pre_mode_does_not_call_guard(self) -> None:
        """_check_graduation_guard is a full-tier-only check: present in full_sequence(),
        absent from pre_sequence(). Hermetic registry assertion -- no main() run needed."""
        pre_names = {step.name for step in registry.pre_sequence() if step.kind == "check"}
        full_names = {step.name for step in registry.full_sequence() if step.kind == "check"}
        assert "_check_graduation_guard" in full_names
        assert "_check_graduation_guard" not in pre_names

    def test_unreadable_dq_latest_json_warns_no_block(self, tmp_path: Path, capsys) -> None:
        """Malformed dq-latest.json content warns (registered as a skip) and does not block."""
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)
        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True)
        (dq_dir / "dq-latest.json").write_text("not valid json{{{", encoding="utf-8")

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run()),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []
        assert "unreadable" in capsys.readouterr().out

    def test_changed_yaml_deleted_on_disk_is_skipped(self, tmp_path: Path) -> None:
        """A changed DQ YAML path reported as changed but absent on disk (get_changed_files()
        itself existence-filters, so this only arises via a TOCTOU race between the diff and the
        read) is skipped rather than crashing on a missing read. get_changed_files() is patched
        directly here since its real implementation would already filter the path out."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "accepted_values", "verdict": "FAIL"}],
        )
        # Deliberately do NOT write config/agent/data_quality/test.yaml -- it's "changed" per the
        # diff but absent on disk.
        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML_ENFORCED_FALSE)),
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.get_changed_files", return_value=["config/agent/data_quality/test.yaml"]),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []

    def test_non_enforced_new_entry_is_skipped(self, tmp_path: Path) -> None:
        """A new_map entry that is enforced:false is never a flip candidate."""
        new_yaml = (
            "tables:\n"
            "  tbl:\n"
            "    columns:\n"
            "      col:\n"
            "        tests:\n"
            "          - accepted_values:\n"
            "              values: [a]\n"
            "              enforced: false\n"
        )
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "accepted_values", "verdict": "FAIL"}],
        )
        self._write_new_yaml(tmp_path, new_yaml)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML_ENFORCED_FALSE)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []

    def test_already_enforced_true_is_not_a_flip(self, tmp_path: Path) -> None:
        """old_enforced already True (true->true, no flip) is never blocked, regardless of
        verdict."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "accepted_values", "verdict": "FAIL"}],
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._NEW_YAML_ENFORCED_TRUE)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []

    def test_flip_with_no_matching_dq_latest_entry_warns_no_block(self, tmp_path: Path, capsys) -> None:
        """A flip to enforced:true with NO matching (table, column, test) key anywhere in
        dq-latest.json's checks array warns but does not block."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "other_table", "column": "col", "test": "accepted_values", "verdict": "FAIL"}],
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML_ENFORCED_TRUE)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML_ENFORCED_FALSE)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []
        assert "not found in dq-latest.json checks" in capsys.readouterr().out


class TestGraduationGuardUnavailableCarveout:
    """UNAVAILABLE per-check verdict warns (inconclusive) and does NOT block graduation."""

    _OLD_YAML = (
        "tables:\n  tbl:\n    columns:\n      col:\n        tests:\n          - not_null:\n              enforced: false\n"
    )
    _NEW_YAML = (
        "tables:\n  tbl:\n    columns:\n      col:\n        tests:\n          - not_null:\n              enforced: true\n"
    )

    def _write_dq_latest(self, tmp_path: Path, checks: list) -> None:

        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True, exist_ok=True)
        (dq_dir / "dq-latest.json").write_text(
            json.dumps({"verdict": "DEGRADED", "checks": checks}),
            encoding="utf-8",
        )

    def _write_new_yaml(self, tmp_path: Path, content: str) -> None:
        yaml_file = tmp_path / "config" / "agent" / "data_quality" / "test.yaml"
        yaml_file.parent.mkdir(parents=True, exist_ok=True)
        yaml_file.write_text(content, encoding="utf-8")

    def _make_run(self, old_yaml: str = "", git_show_rc: int = 0):
        """See TestGraduationGuard._make_run's docstring -- same "show"-only keying (Decision 170)."""

        def _run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            joined = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
            if "--show-current" in joined:
                result.stdout = "agent/test\n"
            elif "--name-only" in joined:
                result.stdout = "config/agent/data_quality/test.yaml\n"
            elif "show" in joined:
                result.stdout = old_yaml
                result.returncode = git_show_rc
            else:
                result.stdout = ""
            return result

        return _run

    def test_unavailable_verdict_warns_does_not_block(self, tmp_path: Path, capsys) -> None:
        """UNAVAILABLE per-check verdict warns (inconclusive) and does not append a graduation failure."""
        self._write_dq_latest(
            tmp_path,
            [{"table": "tbl", "column": "col", "test": "not_null", "verdict": "UNAVAILABLE"}],
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert failed == []
        assert "UNAVAILABLE" in capsys.readouterr().out

    def test_non_pass_non_skip_non_unavailable_still_blocks(self, tmp_path: Path) -> None:
        """A genuine non-PASS/non-SKIP/non-UNAVAILABLE verdict (FAIL) still blocks graduation."""
        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True, exist_ok=True)

        checks_data = [{"table": "tbl", "column": "col", "test": "not_null", "verdict": "FAIL"}]
        (dq_dir / "dq-latest.json").write_text(
            json.dumps({"verdict": "FAIL", "checks": checks_data}),
            encoding="utf-8",
        )
        self._write_new_yaml(tmp_path, self._NEW_YAML)

        with (
            patch("scripts.checks._common.run", side_effect=self._make_run(old_yaml=self._OLD_YAML)),
            patch("scripts.checks._common.ROOT", tmp_path),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        assert len(failed) == 1
        assert "tbl.col.not_null" in failed[0]


class TestBaseDerivation:
    """VP step 9, THE DISCRIMINATING PROOF (Decision 170): the graduation guard's base fix
    converts a reading that was unconditionally vacuous into an examined one, hermetically and
    replayably. Two assertions: (a) the changed-file set derives from the COMMITTED, push-aware
    base, never the working tree; (b) the old-content `git show` read targets that same derived
    base, never the literal "HEAD"."""

    _OLD_YAML = (
        "tables:\n  tbl:\n    columns:\n      col:\n        tests:\n          - not_null:\n              enforced: false\n"
    )
    _NEW_YAML = (
        "tables:\n  tbl:\n    columns:\n      col:\n        tests:\n          - not_null:\n              enforced: true\n"
    )

    def _write_dq_latest(self, tmp_path: Path, verdict: str = "PASS") -> None:
        dq_dir = tmp_path / "logs" / "debug"
        dq_dir.mkdir(parents=True, exist_ok=True)
        (dq_dir / "dq-latest.json").write_text(
            json.dumps(
                {"verdict": verdict, "checks": [{"table": "tbl", "column": "col", "test": "not_null", "verdict": verdict}]}
            ),
            encoding="utf-8",
        )

    def _write_new_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "config" / "agent" / "data_quality" / "test.yaml"
        yaml_file.parent.mkdir(parents=True, exist_ok=True)
        yaml_file.write_text(self._NEW_YAML, encoding="utf-8")

    def test_changed_file_half_examined_positive_on_committed_diff(self, tmp_path: Path) -> None:
        """(a) A committed DQ YAML change against the push-aware base is examined>0 -- not
        vacuous. This is the reading that was unconditionally impossible pre-fix."""
        self._write_dq_latest(tmp_path)
        self._write_new_yaml(tmp_path)

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout=self._OLD_YAML)),
            patch("scripts.checks._common.push_context_base", return_value=None),
            patch("scripts.checks._common.get_changed_files", return_value=["config/agent/data_quality/test.yaml"]),
            patch.object(registry, "examined") as mock_examined,
        ):
            failed: list = []
            _check_graduation_guard(failed)

        mock_examined.assert_called_once_with(1, unit="dq_yaml_files")

    def test_changed_file_half_examined_zero_when_no_committed_diff(self, tmp_path: Path) -> None:
        """The discriminating negative: when get_changed_files() (the committed, push-aware diff)
        reports NOTHING -- e.g. a change that exists only in the uncommitted working tree, which
        this guard no longer reads at all -- the guard declares examined(0): vacuous."""
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", return_value=MagicMock(returncode=0, stdout="")),
            patch("scripts.checks._common.push_context_base", return_value=None),
            patch("scripts.checks._common.get_changed_files", return_value=[]),
            patch.object(registry, "examined") as mock_examined,
        ):
            failed: list = []
            _check_graduation_guard(failed)

        mock_examined.assert_called_once_with(0, unit="dq_yaml_files")

    def test_old_content_half_uses_the_derived_base_never_the_literal_head(self, tmp_path: Path) -> None:
        """(b) The `git show` call's ref is the base push_context_base() derived (never the
        literal "HEAD"), and no invocation matches the retired
        `git diff HEAD ... -- config/agent/data_quality/` shape."""
        self._write_dq_latest(tmp_path)
        self._write_new_yaml(tmp_path)

        calls: list[list[str]] = []

        def _run(cmd, **kwargs):
            calls.append([str(c) for c in cmd] if isinstance(cmd, list) else [str(cmd)])
            result = MagicMock()
            result.returncode = 0
            result.stdout = self._OLD_YAML
            return result

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("scripts.checks._common.run", side_effect=_run),
            patch("scripts.checks._common.push_context_base", return_value="fake-push-base-ref"),
            patch("scripts.checks._common.get_changed_files", return_value=["config/agent/data_quality/test.yaml"]),
        ):
            failed: list = []
            _check_graduation_guard(failed)

        show_calls = [c for c in calls if "show" in c]
        assert show_calls, "expected a `git show` call for the old-content read"
        assert show_calls[0] == ["git", "show", "fake-push-base-ref:config/agent/data_quality/test.yaml"]
        assert not any(
            "diff" in c and "HEAD" in c and any("config/agent/data_quality" in part for part in c) for c in calls
        ), "guard must not call the retired `git diff HEAD ... -- config/agent/data_quality/` shape"
