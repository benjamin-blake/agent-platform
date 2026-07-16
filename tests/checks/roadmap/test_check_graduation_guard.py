"""Tests for _check_graduation_guard() / _extract_enforced_map() (check_graduation_guard.py)."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks.roadmap.check_graduation_guard import _check_graduation_guard, _extract_enforced_map
from tests.fixtures.validate_module import _validate


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


@pytest.mark.usefixtures("_neutralized_pre_registry")
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
        def _run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            joined = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
            if "--show-current" in joined:
                result.stdout = "agent/test\n"
            elif "--name-only" in joined:
                result.stdout = "" if no_changes else "config/agent/data_quality/test.yaml\n"
            elif "show" in joined and "HEAD:" in joined:
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
        """main() --pre does not invoke _check_graduation_guard."""
        with (
            patch("validate._check_graduation_guard") as mock_guard,
            patch("validate.run_lint_checks"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("scripts.checks._common.run", return_value=MagicMock(stdout="agent/test\n", returncode=0)),
            patch.dict("os.environ", {"_VALIDATE_DEPTH": "0"}),
            patch("sys.argv", ["validate.py", "--pre"]),
        ):
            with pytest.raises(SystemExit):
                _validate.main()
        mock_guard.assert_not_called()


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
        def _run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            joined = " ".join(str(c) for c in cmd) if isinstance(cmd, list) else str(cmd)
            if "--show-current" in joined:
                result.stdout = "agent/test\n"
            elif "--name-only" in joined:
                result.stdout = "config/agent/data_quality/test.yaml\n"
            elif "show" in joined and "HEAD:" in joined:
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
