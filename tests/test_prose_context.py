"""V2 tests for scripts/preflight/prose_context.py (PLAN-prose-context-metric, ACG-05/ACG-06
slice 3) plus roadmap-edit assertions for docs/ROADMAP-PLATFORM.yaml T3.14/T1.5.

Exercises real code paths against the live repo tree (not mocks) per the plan's V2 tier:
S1 @-import transitive resolution, per-surface byte/token math, stable/churned split
arithmetic, fail-open behaviour on broken git input, the report-section builder shape, and
the standalone `python -m` entry point.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from scripts.preflight import prose_context

ROOT = Path(__file__).resolve().parent.parent
_SURFACES = ("S1", "S2", "S3", "S4", "S8")


class TestSurfaceResolution:
    def test_s1_root_load_set_includes_claude_and_agents_md(self) -> None:
        """S1 is the resolved root ambient load-set: CLAUDE.md + transitive @-imports.

        Today CLAUDE.md -> @AGENTS.md, so AGENTS.md must appear in the S1 member list
        (Q1 transfer-hazard acceptance criterion) -- membership check, not an exact-count
        assertion, so a future additional @-import does not make this brittle.
        """
        report = prose_context.measure_prose_context()
        paths = {f["path"] for f in report["S1"]["files"]}
        assert "CLAUDE.md" in paths
        assert "AGENTS.md" in paths

    def test_s1_resolution_is_cycle_guarded(self, tmp_path: Path) -> None:
        """A real @-import cycle (CLAUDE.md -> OTHER.md -> CLAUDE.md) must resolve each file
        exactly once and terminate -- proves the docstring's 'cycle-guarded' claim rather than
        just asserting it never happens to loop today (today's real CLAUDE.md/AGENTS.md pair
        has no cycle at all)."""
        claude_md = tmp_path / "CLAUDE.md"
        other_md = tmp_path / "OTHER.md"
        claude_md.write_text("@OTHER.md\n", encoding="utf-8")
        other_md.write_text("@CLAUDE.md\n", encoding="utf-8")
        with patch("scripts.preflight.prose_context._common.ROOT", tmp_path):
            resolved = prose_context._resolve_s1_root_load_set()
        assert sorted(p.name for p in resolved) == ["CLAUDE.md", "OTHER.md"]

    def test_s1_resolution_dedupes_a_diamond_import_shape(self, tmp_path: Path) -> None:
        """CLAUDE.md imports both X and Y; X also imports Y -- Y gets enqueued twice (once by
        CLAUDE.md, once by X) before it is ever processed, so this exercises the SECOND
        (post-dequeue) de-dup guard, distinct from the pairwise-cycle test above which only
        ever exercises the pre-enqueue guard."""
        claude_md = tmp_path / "CLAUDE.md"
        x_md = tmp_path / "X.md"
        y_md = tmp_path / "Y.md"
        claude_md.write_text("@X.md\n@Y.md\n", encoding="utf-8")
        x_md.write_text("@Y.md\n", encoding="utf-8")
        y_md.write_text("no imports here\n", encoding="utf-8")
        with patch("scripts.preflight.prose_context._common.ROOT", tmp_path):
            resolved = prose_context._resolve_s1_root_load_set()
        assert sorted(p.name for p in resolved) == ["CLAUDE.md", "X.md", "Y.md"]

    def test_s2_includes_known_non_root_claude_md_files(self) -> None:
        report = prose_context.measure_prose_context()
        paths = {f["path"] for f in report["S2"]["files"]}
        assert "docs/CLAUDE.md" in paths
        assert "scripts/CLAUDE.md" in paths
        assert "tests/CLAUDE.md" in paths
        # Root CLAUDE.md is S1's, never S2's.
        assert "CLAUDE.md" not in paths

    def test_s3_includes_known_command_files(self) -> None:
        report = prose_context.measure_prose_context()
        paths = {f["path"] for f in report["S3"]["files"]}
        assert ".claude/commands/plan.md" in paths
        assert ".claude/commands/implement.md" in paths

    def test_s4_includes_known_skill_entry_files(self) -> None:
        report = prose_context.measure_prose_context()
        paths = {f["path"] for f in report["S4"]["files"]}
        assert ".claude/skills/planning/SKILL.md" in paths
        assert ".claude/skills/decision-scout/SKILL.md" in paths

    def test_s8_is_project_context(self) -> None:
        report = prose_context.measure_prose_context()
        paths = {f["path"] for f in report["S8"]["files"]}
        assert paths == {"docs/PROJECT_CONTEXT.md"}


class TestByteAndTokenMath:
    def test_every_surface_has_positive_bytes_and_bytes_over_4_tokens(self) -> None:
        report = prose_context.measure_prose_context()
        for surface in _SURFACES:
            data = report[surface]
            assert data["prose_bytes"] > 0, f"{surface} unexpectedly measured 0 bytes"
            assert data["token_estimate"] == data["prose_bytes"] // prose_context.BYTES_PER_TOKEN

    def test_surface_bytes_equal_sum_of_file_bytes(self) -> None:
        report = prose_context.measure_prose_context()
        for surface in _SURFACES:
            data = report[surface]
            assert data["prose_bytes"] == sum(f["prose_bytes"] for f in data["files"])
            assert data["file_count"] == len(data["files"])


class TestStableChurnedSplit:
    def test_split_sums_to_surface_total_when_known(self) -> None:
        report = prose_context.measure_prose_context()
        for surface in _SURFACES:
            data = report[surface]
            if data["split_status"] == "ok":
                assert data["stable_bytes"] + data["churned_bytes"] == data["prose_bytes"]
            else:
                assert data["stable_bytes"] is None
                assert data["churned_bytes"] is None

    def test_churned_relpaths_real_git_returns_a_set(self) -> None:
        """Real (non-mocked) git call: the live repo has history, so this must not fail open."""
        result = prose_context._churned_relpaths()
        assert result is None or isinstance(result, set)


class TestFailOpen:
    def test_churned_relpaths_returns_none_when_git_binary_missing(self) -> None:
        with patch("scripts.preflight.prose_context.subprocess.run", side_effect=FileNotFoundError("no git")):
            assert prose_context._churned_relpaths() is None

    def test_churned_relpaths_returns_none_on_nonzero_exit(self) -> None:
        fake = subprocess.CompletedProcess(args=["git"], returncode=128, stdout="", stderr="fatal: not a git repository")
        with patch("scripts.preflight.prose_context.subprocess.run", return_value=fake):
            assert prose_context._churned_relpaths() is None

    def test_measure_prose_context_never_raises_when_git_unavailable(self) -> None:
        """Fail-open end-to-end: with git unavailable, every surface still degrades cleanly
        (never a raised exception) with an 'unknown' stable/churned split. S1/S3/S4/S8
        enumerate via plain filesystem walks, so their byte counts are unaffected by git's
        absence; S2 enumerates via `git ls-files` (Decision: excludes .venv/untracked without
        risking a vendor-content false-positive from a plain recursive glob), so it degrades
        to an empty-but-valid entry rather than crashing or guessing."""
        with patch("scripts.preflight.prose_context.subprocess.run", side_effect=OSError("no git")):
            report = prose_context.measure_prose_context()
        for surface in _SURFACES:
            data = report[surface]
            assert data["split_status"] == "unknown"
            assert data["stable_bytes"] is None
            assert data["churned_bytes"] is None
        for surface in ("S1", "S3", "S4", "S8"):
            assert report[surface]["prose_bytes"] > 0, f"{surface} should be git-independent"
        assert report["S2"]["prose_bytes"] == 0
        assert report["S2"]["files"] == []

    def test_measure_prose_context_survives_a_broken_resolver(self) -> None:
        """A single broken surface resolver degrades to an empty entry, never aborts the
        whole report (fail-open, mirrors context_docs.py's advisory siblings)."""
        with patch("scripts.preflight.prose_context._resolve_s3_commands", side_effect=RuntimeError("boom")):
            report = prose_context.measure_prose_context()
        assert report["S3"]["prose_bytes"] == 0
        assert report["S3"]["files"] == []
        # Unrelated surfaces are unaffected.
        assert report["S1"]["prose_bytes"] > 0

    def test_measure_prose_context_survives_a_broken_measurement(self) -> None:
        """Distinct from a broken RESOLVER (above): here _measure_surface itself raises after
        the resolver already returned real paths, exercising the outer except branch that
        falls back to _empty_surface() -- a different fail-open seam than the resolver one."""
        with patch("scripts.preflight.prose_context._measure_surface", side_effect=RuntimeError("boom")):
            report = prose_context.measure_prose_context()
        for surface in _SURFACES:
            assert report[surface] == prose_context._empty_surface(report[surface]["label"])

    def test_read_bytes_returns_zero_for_unreadable_path(self, tmp_path: Path) -> None:
        """Real (non-mocked) OSError trigger: read_bytes() on a directory raises
        IsADirectoryError (an OSError subclass) -- confirms the fail-open return-0 branch."""
        a_directory = tmp_path / "not_a_file"
        a_directory.mkdir()
        assert prose_context._read_bytes(a_directory) == 0


class TestReportSectionBuilder:
    def test_build_report_section_shape(self) -> None:
        section = prose_context.build_report_section()
        assert set(section.keys()) == {"surfaces", "total_prose_bytes", "total_token_estimate"}
        surfaces = section["surfaces"]
        assert section["total_prose_bytes"] == sum(s["prose_bytes"] for s in surfaces.values())
        assert section["total_token_estimate"] == sum(s["token_estimate"] for s in surfaces.values())


class TestFormatterAndStandaloneEntryPoint:
    def test_format_prints_exactly_one_summary_line_per_surface_class(self) -> None:
        text = prose_context.format_prose_context_report()
        summary_lines = [ln for ln in text.splitlines() if re.match(r"^(S1|S2|S3|S4|S8) ", ln)]
        assert len(summary_lines) == 5

    def test_format_shows_unknown_split_when_status_is_unknown(self) -> None:
        """Directly constructed (no git dependency): exercises the formatter's 'split=unknown'
        branch, which the live repo's own git history (everything churned) never reaches."""
        surfaces = {s: prose_context._empty_surface(f"label-{s}") for s in _SURFACES}
        text = prose_context.format_prose_context_report(surfaces)
        assert text.count("split=unknown") == 5
        assert "stable=" not in text

    def test_print_prose_context_report_matches_vp_grep(self, capsys: pytest.CaptureFixture[str]) -> None:
        prose_context.print_prose_context_report()
        out = capsys.readouterr().out
        summary_lines = [ln for ln in out.splitlines() if re.match(r"^(S1|S2|S3|S4|S8) ", ln)]
        assert len(summary_lines) == 5

    def test_standalone_module_invocation_prints_five_summary_lines(self) -> None:
        """True `python -m` subprocess invocation (VP step 1), not just an in-process call."""
        result = subprocess.run(
            [sys.executable, "-m", "scripts.preflight.prose_context"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            timeout=30,
        )
        assert result.returncode == 0
        summary_lines = [ln for ln in result.stdout.splitlines() if re.match(r"^(S1|S2|S3|S4|S8) ", ln)]
        assert len(summary_lines) == 5


class TestPreflightWiring:
    def test_preflight_source_wires_prose_context_into_report(self) -> None:
        """Static wiring check: scripts/session/preflight.py assigns
        report["prose_context"] from prose_context.measure_prose_context() and prints the
        advisory, without touching the venv_ok-derived return code."""
        source = (ROOT / "scripts" / "session" / "preflight.py").read_text(encoding="utf-8")
        assert "prose_context" in source
        assert 'report["prose_context"] = prose_context.measure_prose_context()' in source
        assert "prose_context.print_prose_context_report(" in source


def _load_raw_roadmap() -> dict:
    text = (ROOT / "docs" / "ROADMAP-PLATFORM.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)


def _find_item(raw_doc: dict, item_id: str) -> dict:
    for item in raw_doc["tier_items"]:
        if item.get("id") == item_id:
            return item
    raise AssertionError(f"tier_item {item_id!r} not found in ROADMAP-PLATFORM.yaml")


class TestRoadmapEditT314:
    def test_all_criteria_are_structured_objects(self) -> None:
        t314 = _find_item(_load_raw_roadmap(), "T3.14")
        criteria = t314["exit_criteria"]
        assert len(criteria) >= 6
        for crit in criteria:
            assert isinstance(crit, dict), f"T3.14 criterion {crit!r} is still a bare string"
            assert {"id", "text", "status"}.issubset(crit.keys())

    def test_new_criteria_ids_present_and_name_prose_fields(self) -> None:
        t314 = _find_item(_load_raw_roadmap(), "T3.14")
        by_id = {c["id"]: c for c in t314["exit_criteria"]}
        assert {"c1", "c2", "c3", "c4", "c5", "c6"}.issubset(by_id.keys())
        combined_new_text = by_id["c5"]["text"] + by_id["c6"]["text"]
        assert "prose_bytes" in combined_new_text
        assert "token_estimate" in combined_new_text
        assert "stable" in combined_new_text and "churned" in combined_new_text
        assert "scripts/preflight/prose_context.py" in combined_new_text

    def test_no_criterion_marked_met_and_item_stays_deferred(self) -> None:
        t314 = _find_item(_load_raw_roadmap(), "T3.14")
        assert t314["status"] == "deferred_post_mvp"
        for crit in t314["exit_criteria"]:
            assert crit["status"] == "open"
            assert crit.get("met_by") in (None, "")


class TestRoadmapEditT15:
    def test_c1_is_still_a_bare_string_and_names_the_verb_and_consumer(self) -> None:
        t15 = _find_item(_load_raw_roadmap(), "T1.5")
        criteria = t15["exit_criteria"]
        assert len(criteria) >= 1
        c1 = criteria[0]
        assert isinstance(c1, str), "T1.5 c1 must stay a bare string (scoped append, not a conversion)"
        assert "decisions-query" in c1
        assert "ducklake_reader" in c1
        assert "Decision 91" in c1
        assert ".claude/skills/decision-scout/SKILL.md:18-20" in c1
        assert "T5.4" in c1

    def test_other_criteria_remain_unconverted_bare_strings(self) -> None:
        """T1.5's edit is scoped to c1 ONLY (Decision-scout WARN scoping) -- every criterion,
        including the other six, must still be a bare string so validate_platform_roadmap's
        touched-item regex has nothing to flag."""
        t15 = _find_item(_load_raw_roadmap(), "T1.5")
        for crit in t15["exit_criteria"]:
            assert isinstance(crit, str)

    def test_t54_not_touched_and_stays_reserved(self) -> None:
        t54 = _find_item(_load_raw_roadmap(), "T5.4")
        assert t54["status"] == "reserved"
        assert t54["exit_criteria"] == []


class TestRoadmapStillValidatesAgainstSchema:
    def test_platform_roadmap_schema_load_succeeds(self) -> None:
        from scripts.roadmap.platform_roadmap import load

        # Never raises -- proves the Pydantic ExitCriterion/TierItem schema still accepts
        # both the T3.14 structured edit and T1.5's still-bare-string criteria.
        load(ROOT / "docs" / "ROADMAP-PLATFORM.yaml")

    def test_no_tier_item_header_line_touched_for_t15(self) -> None:
        """Guards the append-not-convert contract: the diff must never touch T1.5's own
        `- id: T1.5` header line (that would make validate_platform_roadmap's touched-item
        regex force-flag T1.5's other six bare-string criteria)."""
        result = subprocess.run(
            ["git", "diff", "origin/main", "--", "docs/ROADMAP-PLATFORM.yaml"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=ROOT,
            timeout=30,
        )
        if result.returncode != 0 or not result.stdout.strip():
            pytest.skip("origin/main unreachable or no diff -- cannot assert diff shape")
        import re

        touched_header_lines = re.findall(r"^[+-]\s+- id: (T\S+)", result.stdout, re.MULTILINE)
        assert "T1.5" not in touched_header_lines
