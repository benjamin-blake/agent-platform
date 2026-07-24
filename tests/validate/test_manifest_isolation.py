"""VTS-06 guard: the tracked logs/debug/selection-manifest.json must never be clobbered by a
tests/validate/ orchestrator test driving _validate.main() --pre with the REAL emit_manifest.

Proves two things about the DEBUG_MANIFEST_PATH redirect (scripts/checks/deps/affected_tests.py):
(a) the tracked manifest is byte-identical (or still absent) before and after the run -- no
orchestrator test writes outside tmp_path -- and (b) the autouse _isolate_selection_manifest
fixture's redirected temp target actually received the run's own manifest, proving the write was
redirected rather than silently skipped (a passing (a) alone would not rule out emit_manifest
never firing at all). Self-contained per Decision 131 (no cross-test imports); reuses the shared
tests.fixtures.subprocess_stubs._pre_mock_run and tests.fixtures.validate_module._validate.
"""

from __future__ import annotations

import itertools
import sys
from unittest.mock import MagicMock, patch

import pytest

from scripts.checks import _common
from scripts.checks.deps import affected_tests as at
from tests.fixtures.subprocess_stubs import _pre_mock_run
from tests.fixtures.validate_module import _validate


@pytest.mark.usefixtures("_neutralized_pre_registry")
class TestSelectionManifestIsolation:
    """--pre driven end-to-end (real derive_affected_tests + real emit_manifest) must never
    touch the tracked selection-manifest.json, and must write into the redirected temp target."""

    def test_pre_run_does_not_clobber_tracked_manifest_and_redirects_to_temp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_manifest_path = _common.ROOT / "logs" / "debug" / "selection-manifest.json"
        before = real_manifest_path.read_bytes() if real_manifest_path.exists() else None

        monkeypatch.setattr(sys, "argv", ["validate", "--pre"])
        monkeypatch.setenv("_VALIDATE_DEPTH", "0")
        monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
        monkeypatch.delenv("CI", raising=False)

        def tracking_run(cmd: list[str], **kwargs: object) -> MagicMock:
            return _pre_mock_run(cmd, **kwargs)

        with (
            patch("scripts.checks._common.get_changed_files", return_value=["scripts/validate.py"]),
            patch("scripts.checks._common.run", side_effect=tracking_run),
            patch("validate.validate_iam_runner_policy"),
            patch("validate.validate_prompt_files"),
            patch("validate.validate_cli_tools_in_prompts"),
            patch("time.monotonic", side_effect=itertools.chain([0.0], itertools.repeat(1.0))),
            pytest.raises(SystemExit) as exc_info,
        ):
            _validate.main()

        assert exc_info.value.code == 0

        after = real_manifest_path.read_bytes() if real_manifest_path.exists() else None
        assert after == before, "a tests/validate orchestrator run mutated the tracked selection-manifest.json"

        assert at.DEBUG_MANIFEST_PATH != real_manifest_path, (
            "the autouse _isolate_selection_manifest fixture did not redirect DEBUG_MANIFEST_PATH away from the tracked path"
        )
        assert at.DEBUG_MANIFEST_PATH.exists(), (
            "emit_manifest did not write to the redirected DEBUG_MANIFEST_PATH target -- the real "
            "write path may have been silently skipped rather than redirected"
        )
        redirected_content = at.DEBUG_MANIFEST_PATH.read_text(encoding="utf-8")
        assert '"selected"' in redirected_content, "redirected manifest is missing the expected selection-manifest shape"

    def test_emit_manifest_with_explicit_repo_root_is_unaffected_by_the_redirect(self, tmp_path_factory) -> None:
        """Non-regression companion (belt-and-braces alongside
        tests/checks/deps/test_affected_tests.py): an explicit repo_root caller still writes
        under that root, proving the redirect only ever changes the repo_root=None default."""
        from scripts.checks.deps.affected_tests import derive_affected_tests, emit_manifest

        explicit_root = tmp_path_factory.mktemp("explicit-repo-root")
        (explicit_root / "tests").mkdir()
        (explicit_root / "tests" / "test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
        result = derive_affected_tests([("M", "tests/test_a.py")], repo_root=explicit_root)
        with patch.dict("os.environ", {}, clear=False):
            import os as _os

            _os.environ.pop("S3_LOG_BUCKET", None)
            manifest_path = emit_manifest(result["manifest"], repo_root=explicit_root)
        assert manifest_path == explicit_root / "logs" / "debug" / "selection-manifest.json"
        assert manifest_path.exists()
        assert manifest_path != at.DEBUG_MANIFEST_PATH
