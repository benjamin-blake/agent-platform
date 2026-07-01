"""Unit tests for scripts/dead_code_detector.py over a synthetic fixture tree."""

import importlib.util
import json
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "dead_code_detector.py"
_spec = importlib.util.spec_from_file_location("dead_code_detector", _SCRIPT_PATH)
_dc = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_dc)  # type: ignore[union-attr]
sys.modules["dead_code_detector"] = _dc

detect = _dc.detect
_module_short_name = _dc._module_short_name
_module_to_file = _dc._module_to_file
_gather_grep_surfaces = _dc._gather_grep_surfaces
_candidate_defining_file = _dc._candidate_defining_file
_grep_references = _dc._grep_references
_compute_reachable_set = _dc._compute_reachable_set
_candidates = _dc._candidates


# ---------------------------------------------------------------------------
# Fixture helper
# ---------------------------------------------------------------------------


def _make_fixture(tmp_path: Path) -> Path:
    """Create a synthetic repo tree with known dead/orphan/reachable/excluded modules.

    Layout:
      scripts/entrypoint.py     -- def main(); imports scripts.helper (root, reachable)
      scripts/helper.py         -- reachable via entrypoint
      scripts/orphan_dead.py    -- graph-unreachable, referenced nowhere (high confidence)
      scripts/orphan_ref.py     -- graph-unreachable, referenced only from a fixture .tf file
                                    (must downgrade to low confidence)
      terraform/orphan_ref.tf   -- non-Python surface referencing orphan_ref
      tests/test_stuff.py       -- pytest root; must NOT itself appear as a src/scripts candidate
      src/pkg/excluded_from_tests.py -- unreachable, but tests/ dir must be excluded from candidates
                                          (this file lives under src/, so it IS a valid candidate;
                                          a companion file under tests/ proves the tests/ exclusion)
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "entrypoint.py").write_text(
        "from scripts.helper import do_stuff\n\ndef main():\n    do_stuff()\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "helper.py").write_text("def do_stuff():\n    pass\n", encoding="utf-8")
    (tmp_path / "scripts" / "orphan_dead.py").write_text("def unused():\n    pass\n", encoding="utf-8")
    (tmp_path / "scripts" / "orphan_ref.py").write_text("def unused_but_referenced():\n    pass\n", encoding="utf-8")

    (tmp_path / "terraform").mkdir()
    (tmp_path / "terraform" / "orphan_ref.tf").write_text(
        '# references orphan_ref module by name\nresource "null_resource" "x" {\n  trigger = "orphan_ref"\n}\n',
        encoding="utf-8",
    )

    (tmp_path / "scripts" / "orphan_doc_ref.py").write_text("def unused_doc_referenced():\n    pass\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "PROJECT_CONTEXT.md").write_text(
        "See scripts.orphan_doc_ref for the maintained helper.\n", encoding="utf-8"
    )

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_stuff.py").write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    (tmp_path / "tests" / "dead_in_tests.py").write_text("def unused_test_helper():\n    pass\n", encoding="utf-8")

    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "pkg" / "unreachable_module.py").write_text("def orphan_symbol():\n    pass\n", encoding="utf-8")

    return tmp_path


class TestDetectModuleGranularity:
    """Tests for detect() at module granularity."""

    def test_high_confidence_dead_present(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="module")
        names = [e["name"] for e in result["high_confidence_dead"]]
        assert "scripts.orphan_dead" in names

    def test_grep_hit_downgrades_to_low_confidence(self, tmp_path: Path) -> None:
        """A non-Python surface reference downgrades the candidate out of high confidence."""
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="module")
        high_names = [e["name"] for e in result["high_confidence_dead"]]
        low_names = [e["name"] for e in result["low_confidence_dynamically_referenced"]]
        assert "scripts.orphan_ref" not in high_names
        assert "scripts.orphan_ref" in low_names

    def test_low_confidence_records_referencing_surface(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="module")
        entry = next(e for e in result["low_confidence_dynamically_referenced"] if e["name"] == "scripts.orphan_ref")
        assert any("orphan_ref.tf" in ref for ref in entry["referenced_by"])

    def test_docs_md_reference_downgrades_to_low_confidence(self, tmp_path: Path) -> None:
        """A docs/**/*.md reference (e.g. PROJECT_CONTEXT.md) must downgrade a candidate too."""
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="module")
        high_names = [e["name"] for e in result["high_confidence_dead"]]
        low_names = [e["name"] for e in result["low_confidence_dynamically_referenced"]]
        assert "scripts.orphan_doc_ref" not in high_names
        assert "scripts.orphan_doc_ref" in low_names
        entry = next(e for e in result["low_confidence_dynamically_referenced"] if e["name"] == "scripts.orphan_doc_ref")
        assert any("PROJECT_CONTEXT.md" in ref for ref in entry["referenced_by"])

    def test_reachable_module_not_a_candidate(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="module")
        all_names = [e["name"] for e in result["high_confidence_dead"]] + [
            e["name"] for e in result["low_confidence_dynamically_referenced"]
        ]
        assert "scripts.helper" not in all_names
        assert "scripts.entrypoint" not in all_names

    def test_tests_dir_excluded_from_candidates(self, tmp_path: Path) -> None:
        """tests/ modules are never candidates, even when graph-unreachable (T3.13<->T3.7 boundary)."""
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="module")
        all_names = [e["name"] for e in result["high_confidence_dead"]] + [
            e["name"] for e in result["low_confidence_dynamically_referenced"]
        ]
        assert not any(name.startswith("tests.") for name in all_names)

    def test_src_unreachable_module_is_high_confidence(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="module")
        names = [e["name"] for e in result["high_confidence_dead"]]
        assert "src.pkg.unreachable_module" in names

    def test_output_schema_keys(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="module")
        assert set(result.keys()) == {
            "high_confidence_dead",
            "low_confidence_dynamically_referenced",
            "summary",
            "metadata",
        }
        assert result["summary"]["granularity"] == "module"
        assert result["summary"]["high_confidence_count"] == len(result["high_confidence_dead"])
        assert result["summary"]["low_confidence_count"] == len(result["low_confidence_dynamically_referenced"])
        assert "known_unsound" in result["metadata"]

    def test_high_confidence_sorted(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="module")
        names = [e["name"] for e in result["high_confidence_dead"]]
        assert names == sorted(names)

    def test_low_confidence_sorted(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="module")
        names = [e["name"] for e in result["low_confidence_dynamically_referenced"]]
        assert names == sorted(names)


class TestDetectSymbolGranularity:
    """Tests for detect() at symbol granularity."""

    def test_symbol_candidates_present(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="symbol")
        assert result["summary"]["granularity"] == "symbol"
        all_entries = result["high_confidence_dead"] + result["low_confidence_dynamically_referenced"]
        assert any(e["kind"] == "symbol" for e in all_entries)

    def test_orphan_symbol_is_candidate(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="symbol")
        names = [e["name"] for e in result["high_confidence_dead"]]
        assert "src.pkg.unreachable_module.orphan_symbol" in names

    def test_symbol_shape_matches_module_shape(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        result = detect(repo_root=root, granularity="symbol")
        assert set(result.keys()) == {
            "high_confidence_dead",
            "low_confidence_dynamically_referenced",
            "summary",
            "metadata",
        }


class TestDeterminism:
    """Tests for byte-identical determinism across runs."""

    def test_json_byte_identical_across_runs(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        r1 = detect(repo_root=root, granularity="module")
        r2 = detect(repo_root=root, granularity="module")
        j1 = json.dumps(r1, indent=2, sort_keys=True)
        j2 = json.dumps(r2, indent=2, sort_keys=True)
        assert j1 == j2

    def test_symbol_json_byte_identical_across_runs(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        r1 = detect(repo_root=root, granularity="symbol")
        r2 = detect(repo_root=root, granularity="symbol")
        assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


class TestHelpers:
    """Tests for internal helper functions."""

    def test_module_short_name(self) -> None:
        assert _module_short_name("scripts.pkg.module") == "module"
        assert _module_short_name("scripts.pkg.module.func") == "func"

    def test_module_to_file_plain_module(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        f = _module_to_file("scripts.helper", root)
        assert f is not None
        assert f == root / "scripts" / "helper.py"

    def test_module_to_file_package_init(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        f = _module_to_file("src.pkg", root)
        assert f is not None
        assert f == root / "src" / "pkg" / "__init__.py"

    def test_module_to_file_unknown(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        assert _module_to_file("nonexistent.module", root) is None

    def test_gather_grep_surfaces_includes_tf(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        surfaces = _gather_grep_surfaces(root)
        assert any(s.suffix == ".tf" for s in surfaces)

    def test_gather_grep_surfaces_deterministic(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        s1 = _gather_grep_surfaces(root)
        s2 = _gather_grep_surfaces(root)
        assert s1 == s2
        assert s1 == sorted(s1)

    def test_candidate_defining_file_excluded_from_own_hit(self, tmp_path: Path) -> None:
        """A module's own defining file is excluded so its own declaration isn't a false hit."""
        root = _make_fixture(tmp_path)
        surfaces = _gather_grep_surfaces(root)
        defining_file = _candidate_defining_file("scripts.orphan_dead", "module", root)
        assert defining_file == root / "scripts" / "orphan_dead.py"
        refs = _grep_references("scripts.orphan_dead", "module", surfaces, defining_file, root)
        assert refs == []

    def test_candidate_defining_file_for_symbol(self, tmp_path: Path) -> None:
        root = _make_fixture(tmp_path)
        defining_file = _candidate_defining_file("src.pkg.unreachable_module.orphan_symbol", "symbol", root)
        assert defining_file == root / "src" / "pkg" / "unreachable_module.py"
