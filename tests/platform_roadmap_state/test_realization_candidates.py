"""Fixture tests for PlatformRoadmapState.realization_candidates() (audit PCD-01).

New tests for the deterministic third CD-feed tier -- derived-plausible, strictly disjoint from
ratifiable_cds() and realized_but_pending_cds() by construction (Decision 55 epistemic split).
Fixtures only, per Decision 130/131 constraints; the live-roadmap acceptance anchor (CD.4/CD.5/
CD.9/CD.39 present, CD.7 absent) is verified separately by the plan's Verification Plan step 2,
not by this file.
"""

from __future__ import annotations

from tests.fixtures.platform_roadmap_state import _cd, _doc, _item, _state_from_doc

# ---------------------------------------------------------------------------
# TestRealizationCandidatesGateCompleteness -- the _TIER_SHORTCUT_RE gate-resolution reuse
# ---------------------------------------------------------------------------


class TestRealizationCandidatesGateCompleteness:
    def test_all_gates_complete_included(self) -> None:
        doc = _doc(
            tier_items=[_item("T0.1", status="complete")],
            candidate_decisions=[_cd("CD.4", gates=["T0.1"])],
        )
        result = _state_from_doc(doc).realization_candidates()
        assert [c["id"] for c in result] == ["CD.4"]

    def test_vacuous_empty_gates_included(self) -> None:
        doc = _doc(candidate_decisions=[_cd("CD.5", gates=[])])
        result = _state_from_doc(doc).realization_candidates()
        assert [c["id"] for c in result] == ["CD.5"]

    def test_deferred_post_mvp_gate_nonblocking(self) -> None:
        doc = _doc(
            tier_items=[_item("T0.1", status="deferred_post_mvp")],
            candidate_decisions=[_cd("CD.9", gates=["T0.1"])],
        )
        result = _state_from_doc(doc).realization_candidates()
        assert [c["id"] for c in result] == ["CD.9"]

    def test_reserved_gate_nonblocking(self) -> None:
        doc = _doc(
            tier_items=[_item("T0.1", status="reserved")],
            candidate_decisions=[_cd("CD.39", gates=["T0.1"])],
        )
        result = _state_from_doc(doc).realization_candidates()
        assert [c["id"] for c in result] == ["CD.39"]

    def test_gate_incomplete_excluded(self) -> None:
        doc = _doc(
            tier_items=[_item("T0.1", status="not_started")],
            candidate_decisions=[_cd("CD.1", gates=["T0.1"])],
        )
        result = _state_from_doc(doc).realization_candidates()
        assert result == []

    def test_tier_shortcut_all_complete_included(self) -> None:
        doc = _doc(
            tier_items=[
                _item("T0.1", tier="T0", status="complete"),
                _item("T0.2", tier="T0", status="complete"),
            ],
            candidate_decisions=[_cd("CD.2", gates=["T0"])],
        )
        result = _state_from_doc(doc).realization_candidates()
        assert [c["id"] for c in result] == ["CD.2"]

    def test_tier_shortcut_incomplete_excluded(self) -> None:
        doc = _doc(
            tier_items=[
                _item("T0.1", tier="T0", status="complete"),
                _item("T0.2", tier="T0", status="not_started"),
            ],
            candidate_decisions=[_cd("CD.2", gates=["T0"])],
        )
        result = _state_from_doc(doc).realization_candidates()
        assert result == []

    def test_tier_shortcut_with_no_matching_items_vacuously_true(self) -> None:
        # "T99" is a valid tier-shortcut token (regex matches) even though no tier_item carries
        # that tier -- all() over the resulting empty item list is vacuously True, mirroring
        # the resolver's existing tolerance (tier_complete() has the same vacuous-true shape).
        doc = _doc(candidate_decisions=[_cd("CD.3", gates=["T99"])])
        result = _state_from_doc(doc).realization_candidates()
        assert [c["id"] for c in result] == ["CD.3"]


# ---------------------------------------------------------------------------
# TestRealizationCandidatesExclusions
# ---------------------------------------------------------------------------


class TestRealizationCandidatesExclusions:
    def test_already_evidenced_excluded(self) -> None:
        doc = _doc(candidate_decisions=[_cd("CD.6", realization_evidence="Realized 2026-05-28: shipped.")])
        result = _state_from_doc(doc).realization_candidates()
        assert result == []

    def test_empty_string_evidence_not_truthy_still_a_candidate(self) -> None:
        # rec-2468: realization_evidence="" is falsy -- must be treated as "not evidenced" (a
        # truthy check, never `is not None`), so the CD is still a realization candidate.
        doc = _doc(candidate_decisions=[_cd("CD.7", realization_evidence="")])
        result = _state_from_doc(doc).realization_candidates()
        assert [c["id"] for c in result] == ["CD.7"]

    def test_realized_marker_excluded_and_disjoint(self) -> None:
        doc = _doc(candidate_decisions=[{**_cd("CD.2"), "detail": "Some prose. [Realized 2026-05-30: shipped."}])
        state = _state_from_doc(doc)
        rc = {c["id"] for c in state.realization_candidates()}
        rbp = {c["id"] for c in state.realized_but_pending_cds()}
        assert "CD.2" not in rc
        assert "CD.2" in rbp

    def test_realized_marker_with_complete_gates_still_excluded_and_disjoint(self) -> None:
        # A CD carrying BOTH a [Realized prose marker AND complete gates surfaces only in
        # realized_but_pending_cds -- never in realization_candidates (disjoint-by-construction).
        doc = _doc(
            tier_items=[_item("T0.1", status="complete")],
            candidate_decisions=[{**_cd("CD.8", gates=["T0.1"]), "detail": "[Realized 2026-06-01: gates done."}],
        )
        state = _state_from_doc(doc)
        rc = {c["id"] for c in state.realization_candidates()}
        rbp = {c["id"] for c in state.realized_but_pending_cds()}
        assert "CD.8" not in rc
        assert "CD.8" in rbp

    def test_superseded_prose_edge_excluded_even_with_vacuous_gates(self) -> None:
        # CD.7-pattern: a pending CD "fully superseded by CD.NN" with emptied gates must NOT
        # vacuously surface -- superseded-in-prose is excluded regardless of gate completeness,
        # and regardless of the named superseder's own state (defensive: fires even when the
        # superseder is itself still pending, the case the marking-convention guard cannot
        # catch -- see the plan's Superseded-prose-edge context note).
        doc = _doc(
            tier_items=[_item("T5.1", status="complete")],
            candidate_decisions=[
                _cd("CD.10", gates=[], detail="[Amendment 2026-06-01: fully superseded by CD.28]."),
                _cd("CD.28", gates=["T5.1"]),
            ],
        )
        result = _state_from_doc(doc).realization_candidates()
        assert "CD.10" not in {c["id"] for c in result}

    def test_narrow_supersession_not_excluded(self) -> None:
        # "narrowly superseded by CD.NN" does not match the "fully superseded by" phrase --
        # narrow supersession (CD.11's shape) is a different relationship and is NOT excluded.
        doc = _doc(candidate_decisions=[_cd("CD.11", gates=[], detail="[Note: narrowly superseded by CD.99].")])
        result = _state_from_doc(doc).realization_candidates()
        assert [c["id"] for c in result] == ["CD.11"]

    def test_self_demotion_amendment_not_excluded(self) -> None:
        # CD.10's real self-demotion shape ("[Amendment ...]" prose with no successor CD named)
        # does not match "fully superseded by CD.NN" -- not excluded by this guard.
        doc = _doc(candidate_decisions=[_cd("CD.12", gates=[], detail="[Amendment 2026-05-01: scope narrowed to X].")])
        result = _state_from_doc(doc).realization_candidates()
        assert [c["id"] for c in result] == ["CD.12"]

    def test_ratified_cd_excluded(self) -> None:
        doc = _doc(candidate_decisions=[_cd("CD.13", state="ratified")])
        result = _state_from_doc(doc).realization_candidates()
        assert result == []


# ---------------------------------------------------------------------------
# TestRealizationCandidatesDisjointness -- Decision 55 epistemic split, provable by construction
# ---------------------------------------------------------------------------


class TestRealizationCandidatesDisjointness:
    def test_pairwise_disjoint_across_all_three_feeds(self) -> None:
        doc = _doc(
            tier_items=[_item("T0.1", status="complete")],
            candidate_decisions=[
                _cd("CD.1", realization_evidence="Realized: evidenced"),  # ratifiable_cds()
                {**_cd("CD.2"), "detail": "[Realized 2026-05-30: prose only."},  # realized_but_pending_cds()
                _cd("CD.3", gates=["T0.1"]),  # realization_candidates()
            ],
        )
        state = _state_from_doc(doc)
        rat = {c["id"] for c in state.ratifiable_cds()}
        rbp = {c["id"] for c in state.realized_but_pending_cds()}
        rc = {c["id"] for c in state.realization_candidates()}
        assert rat == {"CD.1"}
        assert rbp == {"CD.2"}
        assert rc == {"CD.3"}
        assert rat.isdisjoint(rbp)
        assert rat.isdisjoint(rc)
        assert rbp.isdisjoint(rc)


# ---------------------------------------------------------------------------
# TestRealizationCandidatesPreflightDict
# ---------------------------------------------------------------------------


class TestRealizationCandidatesPreflightDict:
    def test_to_preflight_dict_carries_key(self) -> None:
        doc = _doc(
            tier_items=[_item("T0.1", status="complete")],
            candidate_decisions=[_cd("CD.4", gates=["T0.1"])],
        )
        full = _state_from_doc(doc).to_preflight_dict()
        assert "realization_candidates" in full
        assert [c["id"] for c in full["realization_candidates"]] == ["CD.4"]


# ---------------------------------------------------------------------------
# TestRealizationCandidatesF4dec93Equivalent -- acceptance-criteria fixture anchor
# ---------------------------------------------------------------------------


class TestRealizationCandidatesF4dec93Equivalent:
    """A fixture equivalent to the f4dec93 audit roadmap: CD.4/CD.5/CD.9/CD.39 are pending,
    unevidenced, gate-complete-or-vacuous CDs (the acceptance targets); CD.7 is
    fully-superseded-in-prose and must NOT appear (superseded-prose edge); CD.18/CD.28 are
    ratified and must not appear either."""

    def test_f4dec93_equivalent_yields_at_least_four_targets(self) -> None:
        doc = _doc(
            tier_items=[
                _item("T1.1", status="complete"),
                _item("T2.1", status="complete"),
                _item("T3.1", status="deferred_post_mvp"),
            ],
            candidate_decisions=[
                _cd("CD.4", gates=["T1.1"]),
                _cd("CD.5", gates=[]),
                _cd("CD.9", gates=["T3.1"]),
                _cd("CD.39", gates=["T2.1"]),
                _cd("CD.7", gates=[], detail="[Amendment 2026-06-01: fully superseded by CD.28]."),
                _cd("CD.28", state="ratified", gates=["T2.1"]),
                _cd("CD.18", state="ratified", gates=[]),
            ],
        )
        result = {c["id"] for c in _state_from_doc(doc).realization_candidates()}
        assert {"CD.4", "CD.5", "CD.9", "CD.39"} <= result
        assert "CD.7" not in result
        assert "CD.18" not in result
        assert "CD.28" not in result
