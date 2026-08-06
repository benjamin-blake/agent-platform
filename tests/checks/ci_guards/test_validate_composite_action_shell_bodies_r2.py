from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from scripts.checks.ci_guards.validate_composite_action_shell_bodies import _r2_test_covers

_MODULE = "scripts.checks.ci_guards.validate_composite_action_shell_bodies"


def test_r2_read_error_continues_to_later_literal_argv_test(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    unreadable = tests_dir / "test_a_unreadable.py"
    unreadable.write_text("foo.sh", encoding="utf-8")
    readable = tests_dir / "test_z_readable.py"
    readable.write_text(
        'ARGV = ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")\n# drives foo.sh\n',
        encoding="utf-8",
    )
    original_read_text = Path.read_text

    def read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == unreadable:
            raise OSError("simulated read failure")
        return original_read_text(path, *args, **kwargs)

    with patch(f"{_MODULE}._common.ROOT", tmp_path), patch.object(Path, "read_text", read_text):
        assert _r2_test_covers("foo.sh") is True
