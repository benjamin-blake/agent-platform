"""Tests for scripts/ops_data_portal.py (Decision 84 contracts).

The offline outbox is retired: file_rec/file_decision raise loudly on failure and
never return 'pending-...'. IDs are allocated by the ducklake_writer (file_ops) or
supplied by the caller (decisions / migration backfill). All warehouse reads transit
the DuckLake reader's named-verb surface.

Decision 124 namespace migration: most patches below target the facade
(scripts.ops_data_portal) because the driving call (file_rec/update_rec/propose_or_close_rec/
_fetch_rec_from_reader/sync/get_ci_rca_strict_mode) is facade-resident and resolves its
dependencies as its own module globals. Where the driving call has MOVED to a
scripts/ops_portal submodule that holds its own bare-imported copy of the dependency
(file_decision/update_decision/backfill_decisions_from_md -> decisions.py;
selftest_roundtrip/find_open_postmortem_for -> maintenance_ops.py; compute_risk ->
risk_scoring.py; _load_write_time_validators's cache -> write_validators.py;
_run_ci_rca_cross_check's bundle load -> ci_rca_schema.py; _ducklake_write's URL
resolution -> writer_transport.py), the patch targets that submodule instead -- the
namespace the moved caller actually resolves at call time (tests/CLAUDE.md namespace
migration discipline).
"""

from __future__ import annotations

import pytest

duckdb = pytest.importorskip("duckdb")


# ---------------------------------------------------------------------------
# Minimal valid rec fields (all required Recommendation fields)
# ---------------------------------------------------------------------------
_VALID_FIELDS = {
    "title": "Test recommendation",
    "file": "scripts/ops_data_portal.py",
    "context": "This is a test rec context with enough detail to satisfy the 80-character minimum requirement.",
    "acceptance": "grep -q 'ops_data_portal' scripts/ops_data_portal.py",
    "effort": "XS",
    "priority": "Low",
    "source": "planning",
    "risk": "low",
    "status": "open",
    "automatable": True,
}

_VALID_DECISION_FIELDS = {
    "title": "Test decision",
    "status": "open",
    "decision_id": 56,
}


_CI_RCA_FIELDS = {
    **_VALID_FIELDS,
    "source": "ci_rca",
    "context": ("CI RCA test rec with sufficient length to satisfy the 80-char minimum for the legacy context column field."),
}

_VALID_CONTEXT_V2 = {
    "schema_version": 1,
    "proximate_cause": (
        "validate_sloc_limits() raised: scripts/roadmap/product_roadmap.py is 810 SLOC, exceeds 500 limit "
        "(Decision 43, no complexity-waiver header found in first 10 lines)."
    ),
    "why_chain": [
        "The file was committed at over 500 SLOC in a single PR with no incremental breakpoint.",
        "No local --pre check fired because validate_sloc_limits() is presubmit-tier only.",
        "The validate_sloc_limits() check was placed in the presubmit tier not --pre despite being O(lines); "
        "this tier placement defect is the gap at scripts/validate.py:2294.",
    ],
    "detection_gap": {
        "earliest_viable_gate": "pre",
        "actual_gate_that_caught_it": "CI",
        "gap_explanation": (
            "validate_sloc_limits() gates on scope=='all' at scripts/validate.py:2294, unreachable from "
            "--pre (exits at scripts/validate.py:2284). Gap is tier-placement, not logic."
        ),
    },
    "recurrence_class": "instance_of_known_pattern",
    "corrective_action": (
        "Add a complexity-waiver header OR refactor the module below 500 SLOC to satisfy the "
        "validate_sloc_limits() check in scripts/validate.py and unblock CI."
    ),
    "preventive_action": (
        "Promote validate_sloc_limits() to the --pre tier at scripts/validate.py so the check fires "
        "during local development and prevents the same tier-placement failure mode in future PRs. "
        "Additionally gate new check additions: require a documented tier-placement rationale."
    ),
}
