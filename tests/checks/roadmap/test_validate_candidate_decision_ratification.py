"""Tests for validate_candidate_decision_ratification()."""

from pathlib import Path
from unittest.mock import patch

from scripts.checks.roadmap.validate_candidate_decision_ratification import (
    _dec_number,
    _load_roadmap,
    validate_candidate_decision_ratification,
)
from scripts.decisions_md import decision_header_numbers


class TestCandidateDecisionRatification:
    """Tests for validate_candidate_decision_ratification() (Decision 105): R1/R2/R3."""

    _MINIMAL_ROADMAP = (
        "document:\n  id: test-roadmap\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
    )

    def _setup(self, tmp_path: Path, cd_yaml: str, decisions_md: str = "", archive_md: str | None = None) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text(self._MINIMAL_ROADMAP + cd_yaml, encoding="utf-8")
        (docs_dir / "DECISIONS.md").write_text(decisions_md, encoding="utf-8")
        if archive_md is not None:
            (docs_dir / "DECISIONS_ARCHIVE.md").write_text(archive_md, encoding="utf-8")

    def test_ratified_cd_resolves_via_header_passes(self, tmp_path: Path) -> None:
        """dec-078 resolves via the '## Decision 78:' header (int-derived, not string-padded)."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.31\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-078\n    filed_via: ops_decisions:dec-078\n",
            decisions_md="## Decision 78: Adopt DuckLake (Decided)\n\nbody with stale Warehouse ID: dec-1085 text\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_ratified_cd_unknown_dec_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.99\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-999\n    filed_via: ops_decisions:dec-999\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_pending_cd_with_ratified_as_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.29\n    title: t\n    state: pending\n    ratified_as: dec-1\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_pending_cd_with_dec_pointer_filed_via_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.29\n    title: t\n    state: pending\n    filed_via: ops_decisions:dec-1\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_pending_cd_with_pending_literal_passes(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.6\n    title: t\n    state: pending\n"
            "    filed_via: pending_log_decision_lambda\n    realization_evidence: Realized.\n",
            decisions_md="",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_ratified_as_filed_via_mismatch_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.16\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-079\n    filed_via: ops_decisions:dec-080\n",
            decisions_md="## Decision 79: X (Decided)\n## Decision 80: Y (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_superseded_cd_exempt_from_r1(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n  - id: CD.14\n    title: t\n    state: superseded\n    ratified_as: dec-999\n",
            decisions_md="## Decision 1: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_malformed_dec_pointer_does_not_partially_resolve_rec_2467(self, tmp_path: Path) -> None:
        """rec-2467: a malformed pointer 'dec-0123abc' must fail loudly, not partially resolve to dec-123."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.99\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-0123abc\n    filed_via: ops_decisions:dec-0123abc\n",
            decisions_md="## Decision 123: Something (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed
        assert _dec_number("dec-0123abc") is None

    def test_well_formed_dec_pointer_still_resolves_rec_2467(self) -> None:
        """The anchor must not regress a valid pointer like 'ops_decisions:dec-078'."""
        assert _dec_number("ops_decisions:dec-078") == 78

    def test_dec_resolves_via_archive_only(self, tmp_path: Path) -> None:
        """A dec-NNN whose header lives only in DECISIONS_ARCHIVE.md still resolves (union read)."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.50\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-34\n    filed_via: ops_decisions:dec-34\n",
            decisions_md="## Decision 1: Something (Decided)\n",
            archive_md="## Decision 34: Unified Cross-Workflow Session Telemetry\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_r4_still_runs_when_r1_header_unresolved(self, tmp_path: Path) -> None:
        """Pins _check_r1_ratified's chosen behaviour (code review round 1): an R1 failure that
        is specifically an unresolvable '## Decision NNN:' header (dec_num itself DID resolve --
        ratified_as/filed_via agree) does not block R4 from also running and reporting its own
        finding in the same pass. Both issues must be present together."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-999\n    filed_via: ops_decisions:dec-999\n"
            "    discipline_points:\n"
            "      - Layer-2 ratification precondition (ESB-04). Do the thing.\n",
            decisions_md="## Decision 1: Something else (Decided)\n",
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("builtins.print") as mock_print,
        ):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        assert "no '## Decision 999:' header" in printed
        assert "ESB-04" in printed and "precondition_discharge" in printed

    # R4 (ESB-02 remediation wave 3): precondition-discharge coverage.

    def test_precondition_discharge_no_discharge_fails(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n"
            "    discipline_points:\n"
            "      - Layer-2 ratification precondition (ESB-04). Do the thing.\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_precondition_discharge_null_valued_entry_fails(self, tmp_path: Path) -> None:
        """Code review round 2 (High): a bare-key discharge entry (`ESB-04:` with no value)
        parses to YAML null (Python None). str(None) == 'None', which is truthy, so a naive
        `not str(discharge.get(pid, '')).strip()` predicate is satisfied by None and WRONGLY
        passes -- the module docstring and R4's contract text both promise a present-but-empty
        entry FAILS. This must fail, naming the id, not pass silently."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n"
            "    discipline_points:\n"
            "      - Layer-2 ratification precondition (ESB-04). Do the thing.\n"
            "      - precondition_discharge:\n"
            "          ESB-04:\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("builtins.print") as mock_print,
        ):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        assert "ESB-04" in printed and "precondition_discharge is missing a non-empty entry" in printed

    def test_precondition_discharge_not_a_mapping_fails(self, tmp_path: Path) -> None:
        """The 'also worth closing' branch (code review round 1): a precondition_discharge KEY
        present but whose value isn't a dict (a str here) must fail, not silently pass through."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n"
            "    discipline_points:\n"
            "      - Layer-2 ratification precondition (ESB-04). Do the thing.\n"
            "      - precondition_discharge: not-a-mapping-just-a-string\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("builtins.print") as mock_print,
        ):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        assert "precondition_discharge is not a mapping" in printed

    def test_precondition_discharge_multiple_blocks_fails(self, tmp_path: Path) -> None:
        """The 'also worth closing' branch (code review round 1): TWO precondition_discharge
        dict entries must fail (must be exactly 1), not silently pick the first/last."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n"
            "    discipline_points:\n"
            "      - Layer-2 ratification precondition (ESB-04). Do the thing.\n"
            "      - precondition_discharge:\n"
            "          ESB-04: First block.\n"
            "      - precondition_discharge:\n"
            "          ESB-04: Second, duplicate block.\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("builtins.print") as mock_print,
        ):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        assert "carries 2 precondition_discharge block(s)" in printed

    def test_precondition_id_inside_colon_hazard_entry_is_found_and_requires_discharge(self, tmp_path: Path) -> None:
        """Code review round 3 (Medium, promoted to blocking). A colon-hazard accidental YAML
        mapping -- the exact shape of CD.27's own pre-existing 'T4.x atomic-plan template' entry
        -- must not silently hide a declared precondition id from R4. Confirmed failing-first: the
        pre-fix `isinstance(pt, str)`-only filter in _precondition_ids never sees this id at all,
        so R4 wrongly no-ops (passes) despite zero discharge coverage -- partial enforcement
        presenting as full, the exact phantom-control shape this wave exists to remove."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n"
            "    discipline_points:\n"
            "      - Layer-2 ratification precondition (ESB-04): must do the thing.\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed

    def test_precondition_discharge_text_present_but_not_a_clean_block_fails_loud(self, tmp_path: Path) -> None:
        """Code review round 3 (Medium, promoted to blocking) -- the chosen mechanism's own
        loud-failure path. A `precondition_discharge`-adjacent entry that colon-hazards into a
        dict whose KEY is 'precondition_discharge for ESB-04' (not exactly 'precondition_discharge')
        is textually present but does not resolve as a clean top-level block. With no real
        precondition id declared anywhere, the pre-fix code's `if not precondition_ids: return`
        early-continue skips discharge-checking entirely and this passes silently -- confirmed
        failing-first. The integrity check (text-mention count vs structurally-recognized block
        count) must fail loud instead, naming the mismatch, BEFORE the early-continue."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n"
            "    discipline_points:\n"
            "      - precondition_discharge for ESB-04: a stray description, no real precondition declared.\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("builtins.print") as mock_print,
        ):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        assert "precondition_discharge for ESB-04" in printed and "without matching it exactly" in printed

    def test_precondition_discharge_partial_coverage_fails_naming_missing_id(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n"
            "    discipline_points:\n"
            "      - Layer-2 ratification precondition (ESB-04). Do the thing.\n"
            "      - Layer-2 ratification precondition (ESB-06). Do the other thing.\n"
            "      - precondition_discharge:\n"
            "          ESB-04: Discharged at ratification -- comparative record landed.\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch("builtins.print") as mock_print,
        ):
            validate_candidate_decision_ratification(failed)
        assert "Candidate decision ratification guard" in failed
        printed = "\n".join(str(c.args[0]) for c in mock_print.call_args_list if c.args)
        assert "ESB-06" in printed

    def test_precondition_discharge_full_coverage_passes(self, tmp_path: Path) -> None:
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n"
            "    discipline_points:\n"
            "      - Layer-2 ratification precondition (ESB-04). Do the thing.\n"
            "      - Layer-2 ratification precondition (ESB-06). Do the other thing.\n"
            "      - precondition_discharge:\n"
            "          ESB-04: Discharged at ratification -- comparative record landed.\n"
            "          ESB-06: Discharged at ratification -- determinism rules landed.\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_precondition_discharge_lapse_entry_counts_as_discharge(self, tmp_path: Path) -> None:
        """A LAPSE-worded entry is still a non-empty string -- R4 checks presence, not verdict."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n"
            "    discipline_points:\n"
            "      - Layer-2 ratification precondition (ESB-06). Do the other thing.\n"
            "      - precondition_discharge:\n"
            "          ESB-06: LAPSED -- spike selected a non-replay substrate; obligation does not apply.\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_precondition_discharge_no_op_ratified_no_preconditions_passes(self, tmp_path: Path) -> None:
        """A ratified CD declaring zero preconditions needs no precondition_discharge block at all."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.28\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n"
            "    discipline_points:\n"
            "      - Some unrelated discipline point with no precondition pattern in it.\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_precondition_discharge_no_op_no_discipline_points_passes(self, tmp_path: Path) -> None:
        """A ratified CD with no discipline_points key at all is a clean no-op for R4."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.28\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-200\n    filed_via: ops_decisions:dec-200\n",
            decisions_md="## Decision 200: X (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_precondition_discharge_no_op_pending_with_preconditions_passes(self, tmp_path: Path) -> None:
        """A pending CD carrying preconditions is not yet due -- R4 applies only to state==ratified."""
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.27\n    title: t\n    state: pending\n"
            "    filed_via: pending_log_decision_lambda\n"
            "    discipline_points:\n"
            "      - Layer-2 ratification precondition (ESB-04). Do the thing.\n",
            decisions_md="",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    def test_multiple_cds_share_one_ratified_as_passes(self, tmp_path: Path) -> None:
        # batch-wave: >=2 CDs share one ratified_as (CD.16/CD.24 -> dec-079 precedent)
        self._setup(
            tmp_path,
            "candidate_decisions:\n"
            "  - id: CD.16\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-079\n    filed_via: ops_decisions:dec-079\n"
            "  - id: CD.24\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-079\n    filed_via: ops_decisions:dec-079\n",
            decisions_md="## Decision 79: X (Decided)\n",
        )
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []

    # Coverage paydown (rec-2965 / PLAN-coverage-gate-handoff-integrity): the four arms below
    # were uncovered pre-836 too (measured 87% on the pre-extraction file, identical four arms) --
    # PR #836's _load_roadmap extraction merely moved them, it did not introduce them.

    def test_dec_number_falsy_pointer_returns_none(self) -> None:
        """_dec_number's falsy-pointer short-circuit (None and empty string both return None
        before the regex is ever consulted)."""
        assert _dec_number(None) is None
        assert _dec_number("") is None

    def test_roadmap_file_not_found_fails(self, tmp_path: Path) -> None:
        """The roadmap-not-found guard: docs/ exists but ROADMAP-PLATFORM.yaml does not."""
        (tmp_path / "docs").mkdir(parents=True)
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == ["Candidate decision ratification guard"]

    def test_load_roadmap_except_arm_via_malformed_yaml_fails(self, tmp_path: Path) -> None:
        """The _load_roadmap except-Exception arm, reached through the public entry point via a
        genuinely malformed ROADMAP-PLATFORM.yaml (not a mock) -- covers both the except arm
        and the caller's doc-is-None early return in the same pass."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text("candidate_decisions: [\n  - broken: [\n", encoding="utf-8")
        (docs_dir / "DECISIONS.md").write_text("", encoding="utf-8")
        (docs_dir / "DECISIONS_ARCHIVE.md").write_text("", encoding="utf-8")
        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == ["Candidate decision ratification guard"]

    def test_load_roadmap_direct_call_returns_none_on_error(self, tmp_path: Path) -> None:
        """_load_roadmap called directly (not through the public entry point) returns None and
        appends exactly one failure on a load error."""
        bad_path = tmp_path / "does-not-exist.yaml"
        failed: list[str] = []
        result = _load_roadmap(bad_path, failed)
        assert result is None
        assert failed == ["Candidate decision ratification guard"]


class TestConsolidatedHeaderHelper:
    """DAF-03 consolidation (PLAN-daf-authoring-grammar): the R1 guard's header-number scan now
    delegates to scripts.decisions_md.decision_header_numbers(paths=...), rooted at the
    (patchable) _common.ROOT -- never a no-arg call, which would silently read decisions_md's
    own module-level repo root instead of a patched _common.ROOT and break every re-rooting
    test in this file."""

    def test_decision_header_numbers_called_with_explicit_rooted_paths(self, tmp_path: Path) -> None:
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text(
            "document:\n  id: t\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
            "candidate_decisions: []\n",
            encoding="utf-8",
        )
        (docs_dir / "DECISIONS.md").write_text("## Decision 1: X (Decided)\n", encoding="utf-8")

        with (
            patch("scripts.checks._common.ROOT", tmp_path),
            patch(
                "scripts.checks.roadmap.validate_candidate_decision_ratification.decision_header_numbers",
                wraps=decision_header_numbers,
            ) as mock_header_numbers,
        ):
            failed: list[str] = []
            validate_candidate_decision_ratification(failed)

        mock_header_numbers.assert_called_once()
        _, kwargs = mock_header_numbers.call_args
        assert kwargs["paths"] == [tmp_path / "docs" / "DECISIONS.md", tmp_path / "docs" / "DECISIONS_ARCHIVE.md"]

    def test_promoted_archive_decision_resolves_via_consolidated_helper(self, tmp_path: Path) -> None:
        """Post-DPI-07-promote regression: a CD ratified against dec-52 (now '## Decision 52:'
        h2 in the archive, was h3 pre-promote) resolves cleanly through the consolidated
        decision_header_numbers() path -- the R1 guard's population includes it either way."""
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        (docs_dir / "ROADMAP-PLATFORM.yaml").write_text(
            "document:\n  id: t\n  version: 1\n  status: draft\n  filed_via: pending_log_decision_lambda\n"
            "candidate_decisions:\n"
            "  - id: CD.1\n    title: t\n    state: ratified\n"
            "    ratified_as: dec-52\n    filed_via: ops_decisions:dec-52\n",
            encoding="utf-8",
        )
        (docs_dir / "DECISIONS.md").write_text("", encoding="utf-8")
        (docs_dir / "DECISIONS_ARCHIVE.md").write_text(
            "## Decision 52: Bedrock Migration (Decided)\n\n**Status:** Decided -- April 2026\n",
            encoding="utf-8",
        )

        failed: list[str] = []
        with patch("scripts.checks._common.ROOT", tmp_path):
            validate_candidate_decision_ratification(failed)
        assert failed == []
