"""ESB-08 guards (PLAN-esb-text-fix-bundle).

The structured stability definition carries denominator, exempt, baseline_window and a
worked_example{inputs,computed,verdict}. The worked example's rate is re-derived FROM `inputs`
and compared to `computed`; `verdict.fires` is an explicit boolean (never prose, which a substring
test would satisfy even when negated). A nonzero scheduled-continuation count proves the exemption
is exercised. The OLD prose stability entry is absent. The days-1-7 thresholds carry the literal
TBD_at_T4.2_atomic_plan deferral marker rather than invented numbers. The WHOLE stability block is
scanned for mechanism vocabulary -- ESB-05's third site. INTENT :352 is annotated.
"""

from __future__ import annotations

import yaml

from tests.esb_text_fix._anchors import cd27, load_intent_text, mechanism_hits


def _stability_entry(cd: dict) -> dict:
    sd = [p for p in cd["discipline_points"] if isinstance(p, dict) and "stability_definition_14d" in p]
    assert len(sd) == 1, f"expected exactly 1 stability_definition_14d, found {len(sd)}"
    return sd[0]["stability_definition_14d"]


def test_stability_block_mechanism_free():
    cd = cd27()
    s = _stability_entry(cd)
    blob = yaml.safe_dump(s)
    hits = mechanism_hits(blob)
    assert not hits, f"mechanism vocabulary survives in the stability definition: {hits}"


def test_old_prose_stability_entry_gone():
    cd = cd27()
    stale = [q for q in cd["discipline_points"] if isinstance(q, dict) and any("stable for 14 days" in str(k) for k in q)]
    assert not stale, f"the OLD prose stability entry survives beside the structured one: {stale}"
    # And the plain-string form must be entirely gone too.
    strings = [p for p in cd["discipline_points"] if isinstance(p, str)]
    assert not any("stable for 14 days" in p for p in strings), (
        "the OLD prose 'stable for 14 days' discipline point string survives"
    )


def test_signal_denominator_and_exemption_present():
    cd = cd27()
    s = _stability_entry(cd)
    sig = s["signals"]["unplanned_resume_rate"]
    assert sig.get("denominator"), "unplanned_resume_rate.denominator missing"
    assert sig.get("exempt"), "unplanned_resume_rate.exempt missing"
    assert s.get("baseline_window"), "baseline_window missing"


def test_days_1_7_thresholds_carry_deferral_marker():
    cd = cd27()
    s = _stability_entry(cd)
    assert s["days_1_7_absolute_thresholds"] == "TBD_at_T4.2_atomic_plan"


def test_worked_example_recomputes_and_exercises_exemption():
    cd = cd27()
    s = _stability_entry(cd)
    we = s["worked_example"]
    assert {"inputs", "computed", "verdict"} <= set(we), sorted(we)
    inp = we["inputs"]
    assert inp.get("scheduled_continuations", 0) > 0, "worked example must exercise the scheduled-continuation exemption"
    derived = inp["unplanned_resumes"] / inp["persona_node_executions"]
    assert abs(we["computed"]["unplanned_resume_rate"] - derived) < 1e-9
    assert derived < 0.05, f"worked example rate {derived} contradicts the <5% threshold"
    vd = we["verdict"]
    assert isinstance(vd, dict), "verdict must be a mapping, not prose"
    # Named signal_passes, not fires: this worked example demonstrates ONE persona's ONE signal
    # passing, not that the whole 14-day CD.17 reversal trigger fires (that needs ALL personas'
    # ALL signals across the full baseline_window) -- see M2 (code-review round 1).
    assert vd.get("signal_passes") is True, (
        f"verdict.signal_passes must be an explicit boolean True, got {vd.get('signal_passes')!r}"
    )
    assert "fires" not in vd, (
        "verdict must not also carry a 'fires' key -- it overclaims relative to a single-signal worked example"
    )


def test_intent_alarm_row_annotated():
    text = load_intent_text()
    lines = [line for line in text.splitlines() if "unplanned_resume_rate" in line]
    assert lines, "INTENT alarm row for the unplanned_resume_rate signal not found"
    row = lines[0]
    assert "UNPLANNED" in row, "INTENT :352 alarm row must be annotated to count UNPLANNED resumes only"
    assert "ESB-08" in row, "INTENT :352 annotation must cite ESB-08"
