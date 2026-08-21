"""Standing regression guards for the 2026-08-21 executor substrate-billing evidence round
(PLAN-executor-substrate-evidence-fold), asserting content this wave folds into
docs/ROADMAP-PLATFORM.yaml: the nine operator estimates, the two new ASSESSED envelope rows and
their set-membership declarations, the narrowed non-discrimination conclusion and its
per-scale-point delta arithmetic, T4.15 exit criteria c9 and c10, and the in-place trigger-row
extension. A separate module from test_cost_projection.py: that module's subject is the
priced-row provenance guard contract, this one's is the evidence fold itself.
"""

from __future__ import annotations

import re

from tests.esb_text_fix._anchors import load_roadmap, tier_item

RECOGNISED_PROVENANCE_CLASSES = {
    "aws_price_list",
    "published_pricing_page_regional",
    "published_pricing_page_unqualified",
}

PINNED_ENVELOPE_ROWS = {
    "durable_functions",
    "sfn_over_stateless_workers",
    "self_checkpointed_lambda_dynamodb",
    "long_running_container",
}


def _cost_projection() -> dict:
    return load_roadmap()["cost_projection"]


def _t415(roadmap=None) -> dict:
    return tier_item("T4.15", roadmap)


def test_operator_estimates_block_is_complete_and_disclaimed():
    oe = _cost_projection()["operator_estimates"]
    source = str(oe["source"])
    assert "not measurement" in source.lower(), "source must explicitly disclaim measurement"
    assert "2026-08-21" in source, "source must name the session date"

    entries = oe["entries"]
    ids = [e["id"] for e in entries]
    assert ids == [f"OE-{i:02d}" for i in range(1, 10)], f"expected nine ordered ids OE-01..OE-09, got {ids}"

    required_fields = {"id", "input", "assumed_value", "why", "sensitivity"}
    for e in entries:
        assert set(e.keys()) == required_fields, f"{e['id']} must carry exactly {required_fields}, got {set(e.keys())}"
        assert len(str(e["why"])) <= 200, f"{e['id']} why field exceeds 200 chars"

    assert any("HIGH" in str(e["sensitivity"]) for e in entries), "at least one entry must carry HIGH sensitivity"


def test_new_envelope_rows_declare_set_membership_and_verdicts():
    cp = _cost_projection()
    esb = cp["executor_substrate_billing"]
    envelope = esb["per_substrate_envelope_usd_per_month"]

    for pinned_name in PINNED_ENVELOPE_ROWS:
        assert pinned_name in envelope, f"pinned row {pinned_name!r} must survive"
        assert envelope[pinned_name].get("in_pinned_candidate_set") is True, (
            f"pinned row {pinned_name!r} must declare in_pinned_candidate_set: true"
        )

    for new_name in ("aws_native_codebuild_runner", "agentcore_managed_runtime"):
        assert new_name in envelope, f"new assessed row {new_name!r} must be present"
        row = envelope[new_name]
        assert row.get("in_pinned_candidate_set") is False, f"{new_name} must declare in_pinned_candidate_set: false"
        assert str(row.get("assessment", "")).strip(), f"{new_name} must carry an assessment verdict"
        assert len(str(row["note"])) <= 1500, f"{new_name} note exceeds 1500 chars"

    all_priced_rows = dict(envelope)
    all_priced_rows.update(esb.get("durable_execution_corrected_rates") or {})
    for name, entry in all_priced_rows.items():
        pc = entry.get("provenance_class")
        assert pc in RECOGNISED_PROVENANCE_CLASSES, f"{name} missing/unrecognised provenance_class: {pc!r}"

    lrc = envelope["long_running_container"]
    basis = str(lrc.get("utilisation_basis", ""))
    assert "2026-08-01" in basis, "long_running_container utilisation_basis must name the Price-List rate provenance date"
    assert "2026-08-21" in basis, "long_running_container utilisation_basis must name the operator-estimate utilisation date"

    blob = str(cp)
    assert "arn:aws:" not in blob, "no arn:aws: literal may reach cost_projection"
    assert "codebuild:startBuild.sync" in blob, "the SFN integration must be named codebuild:startBuild.sync"


def test_non_discrimination_conclusion_narrowed_and_deltas_reconcile():
    cp = _cost_projection()
    esb = cp["executor_substrate_billing"]
    conclusion = str(esb["non_discrimination_conclusion"])

    assert "codebuild" in conclusion.lower(), "conclusion must name the narrowed-against candidate"
    assert "narrow" in conclusion.lower(), "conclusion must record that it narrowed"
    assert "unchanged" in conclusion.lower() and "pinned" in conclusion.lower(), (
        "conclusion must state the pinned set is unchanged"
    )
    assert "per-scale-point" in conclusion.lower() or "fixed scale point" in conclusion.lower(), (
        "conclusion must frame the delta clause per-scale-point"
    )
    assert "recorded scale 100-300 recs/month" in conclusion, (
        "conclusion must cite executor_substrate_billing.provenance's block-level scale citation"
    )

    envelope = esb["per_substrate_envelope_usd_per_month"]
    pinned_bands = {}
    for name, entry in envelope.items():
        assert "in_pinned_candidate_set" in entry, f"{name} must explicitly declare in_pinned_candidate_set"
        if entry["in_pinned_candidate_set"] is True:
            lo, hi = [float(x) for x in re.match(r"^([0-9.]+)-([0-9.]+)$", str(entry["envelope"])).groups()]
            pinned_bands[name] = (lo, hi)

    assert set(pinned_bands) == PINNED_ENVELOPE_ROWS, f"expected exactly the pinned four, got {sorted(pinned_bands)}"

    computed_low_delta = max(lo for lo, _ in pinned_bands.values()) - min(lo for lo, _ in pinned_bands.values())
    computed_high_delta = max(hi for _, hi in pinned_bands.values()) - min(hi for _, hi in pinned_bands.values())

    maxima = [float(x) for x in re.findall(r"max delta ([0-9.]+)/month", conclusion)]
    assert len(maxima) == 2, f"expected two published maxima (band low, band high), found {maxima}"
    published_low_delta, published_high_delta = maxima
    assert published_low_delta == computed_low_delta, (
        f"published band-low max delta {published_low_delta} != computed {computed_low_delta}"
    )
    assert published_high_delta == computed_high_delta, (
        f"published band-high max delta {published_high_delta} != computed {computed_high_delta}"
    )


def test_t415_c9_verification_split():
    t415 = _t415()
    for c in t415["exit_criteria"]:
        assert isinstance(c, dict), "exit criteria must be {id, text, status} objects, never bare strings"

    c9 = next(c for c in t415["exit_criteria"] if c["id"] == "c9")
    assert c9["status"] == "open"
    text = str(c9["text"])
    low = text.lower()

    assert "regardless" in low, "c9 must bind verification/validation regardless of substrate"
    assert "validate.py" in text, "c9 must name validate.py"
    assert "github actions" in low, "c9 must name GitHub Actions"
    assert "exclude" in low and "wall-clock" in low, "c9 must exclude verification/validation wall-clock"
    assert "clause 3" in low, "c9 must cite Decision 163 clause 3 specifically"
    assert "decision 112" in low, "c9 must cite Decision 112"
    assert "t4.9 c1" in low and "t4.9a c1" in low, "c9 must name both T4.9 c1 and T4.9a c1"
    assert "not rehomed" in low, "c9 must state neither is rehomed"
    assert "distinct workflow run" in low, "c9 must carry the distinct-workflow-runs formulation"


def test_t415_c10_github_tos_predicate():
    t415 = _t415()
    c10 = next(c for c in t415["exit_criteria"] if c["id"] == "c10")
    assert c10["status"] == "open"
    text = str(c10["text"])
    low = text.lower()

    assert "clause 5" in low, "c10 must name clause 5"
    assert "clause 4" in low, "c10 must name clause 4 as the binding constraint"
    assert "2026-08-21" in text, "c10 must carry the ToS retrieval date"
    assert "disproportionate to the benefits" in low, "c10 must quote the disproportionate-burden test"
    assert "measured burden posture" in low, "c10 must require a measured burden posture"
    assert "busl-1.1" in low, "c10 must carry the BUSL-1.1 relicensing note"
    assert "repo-visibility" in low, "c10 must name the repo-visibility re-evaluation trigger"


def test_reevaluation_triggers_extended_in_place():
    esb = _cost_projection()["executor_substrate_billing"]
    triggers = esb["substrate_reevaluation_triggers"]
    assert len(triggers) == 4, f"row count must stay exactly 4, got {len(triggers)}"

    tos_naming = [t for t in triggers if "tos" in t.lower() or "usage-policy" in t.lower() or "t4.15 c10" in t.lower()]
    assert len(tos_naming) == 3, f"expected exactly three rows naming the ToS predicate, found {len(tos_naming)}"
    assert len(tos_naming) == len(set(tos_naming)), "trigger rows must not be duplicated"
