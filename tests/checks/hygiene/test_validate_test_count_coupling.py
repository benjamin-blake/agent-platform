"""Tests for validate_test_count_coupling() (Decision 104 test-count-coupling guard)."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.hygiene.validate_test_count_coupling import _find_violations


class TestValidateTestCountCoupling:
    """Tests for validate_test_count_coupling() (Decision 104 test-count-coupling guard).

    Exercises the pure _find_violations(paths) core directly on synthetic temp files --
    the incident's three brittle shapes (direct reference, aliased local, string-subscript
    key), both comparison orders, the waiver escape hatch, and both-tiers registration.
    """

    def _write(self, tmp_path: Path, name: str, body: str) -> Path:
        path = tmp_path / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_direct_reference_is_flagged(self, tmp_path: Path) -> None:
        """assert len(TABLE_NAMES) == N -- direct reference to a curated collection."""
        path = self._write(tmp_path, "test_a.py", "def test_x():\n    assert len(TABLE_NAMES) == 11\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_aliased_local_is_flagged(self, tmp_path: Path) -> None:
        """entries = load_source_registry(); assert len(entries) == N -- the incident's blind spot."""
        path = self._write(
            tmp_path,
            "test_b.py",
            "def test_x():\n    entries = load_source_registry()\n    assert len(entries) == 35\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_string_subscript_key_is_flagged(self, tmp_path: Path) -> None:
        """assert len(g["source"]["registered_values"]) == N -- string-subscript key shape."""
        path = self._write(
            tmp_path,
            "test_c.py",
            'def test_x():\n    assert len(g["source"]["registered_values"]) == 35\n',
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_derived_assertion_not_flagged(self, tmp_path: Path) -> None:
        """RHS not an int literal -- a genuine derivation, not a hardcoded count."""
        path = self._write(
            tmp_path,
            "test_d.py",
            "def test_x():\n    entries = load_source_registry()\n    assert len(entries) == len(raw_ids)\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_waived_assertion_not_flagged(self, tmp_path: Path) -> None:
        """A `# count-coupling-ok:` comment on the assert's line silences the guard."""
        path = self._write(
            tmp_path,
            "test_e.py",
            "def test_x():\n    assert len(TABLE_NAMES) == 11  # count-coupling-ok: deliberate tripwire\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_non_curated_count_not_flagged(self, tmp_path: Path) -> None:
        """A hardcoded exact-count assertion against a non-curated collection is not the anti-pattern."""
        path = self._write(tmp_path, "test_f.py", "def test_x():\n    assert len(rows) == 3\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert violations == []

    def test_tainted_controlled_fixture_flagged_then_waived(self, tmp_path: Path) -> None:
        """The test_rec_write_guidance.py:43 class: a curated-tainted local with a small,
        deliberately-sized fixture count IS flagged unwaived, but NOT once waived."""
        unwaived = self._write(
            tmp_path,
            "test_g.py",
            "def test_x():\n    e = load_source_registry(p)\n    assert len(e) == 1\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert len(_find_violations([unwaived])) == 1

        waived = self._write(
            tmp_path,
            "test_h.py",
            "def test_x():\n    e = load_source_registry(p)\n    assert len(e) == 1  # count-coupling-ok: fixture\n",
        )
        with patch("scripts.checks._common.ROOT", tmp_path):
            assert _find_violations([waived]) == []

    def test_yoda_order_is_flagged(self, tmp_path: Path) -> None:
        """assert N == len(TABLE_NAMES) -- reversed comparison order, same anti-pattern."""
        path = self._write(tmp_path, "test_i.py", "def test_x():\n    assert 11 == len(TABLE_NAMES)\n")
        with patch("scripts.checks._common.ROOT", tmp_path):
            violations = _find_violations([path])
        assert len(violations) == 1

    def test_registered_in_both_tiers(self) -> None:
        """validate_test_count_coupling appears in both pre_sequence() and full_sequence()."""
        from scripts.checks import registry

        names = [s.name for s in registry.pre_sequence() + registry.full_sequence()]
        assert names.count("validate_test_count_coupling") >= 2
