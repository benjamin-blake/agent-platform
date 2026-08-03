"""ESB-02 fallback-spec carrier guards (PLAN-esb-fallback-spec-carrier, wave 3).

Covers three deliverables this wave lands directly in docs/ROADMAP-PLATFORM.yaml's CD.27 block --
the `fallback_spec` discipline_point's well-formedness, the maturity-monitoring point's
phantom-free/carrier-bound invariants, and the precondition-discharge-rule point -- plus a
growth-safe anchor-phrase membership floor over the four CD.27 string discipline_points that the
retired CD.27-discipline-points byte-identity-vs-origin/main guard (formerly in
tests/esb_text_fix/test_workspace_store_criteria.py) covered only incidentally as a side effect
of asserting byte-identity against origin/main: S3 pointer pattern, "retry policies
are deterministic-only", the T4.x atomic-plan template point, and the EXR-07 amendment. That
guard's own load-bearing coverage (the three Layer-2 precondition strings staying byte-identical,
and the maturity point's stale "recorded as an INTENT Open Question" clause /
"checkpoint-replay verified" pointer being caught if reintroduced) is either already duplicated
by other live guards (cd27-layer2-preconditions-cover-esb01,
t4x-persona-contracts-mechanism-word-free) or asserted here, strictly stronger (exists exactly
once under a startswith anchor; does NOT contain "recorded as an INTENT Open Question"; does NOT
contain "checkpoint-replay verified"; DOES name fallback_spec and validate_fallback_reevaluation).
"""

from __future__ import annotations

import re

import yaml

from scripts.checks.roadmap.validate_fallback_reevaluation import _gate_pattern
from tests.esb_text_fix._anchors import cd27, load_roadmap

REQUIRED_FALLBACK_SPEC_KEYS = {
    "trigger",
    "substrate",
    "state_schema",
    "checkpoint_granularity",
    "driver",
    "cutover",
    "effort",
    "reevaluation_carrier",
    "lapse_condition",
}
REQUIRED_STATE_SCHEMA_KEYS = {"grain", "identity", "partition_key", "sort_key", "attributes", "write_mode"}

#: A fallback_spec key present but under this length is contentless/stubbed, not a real value.
#: Duplicated (not importable) in VP step 1's command and its graduated registry-row check_spec
#: (config/agent/verification_registry/registry.yaml, check_id
#: cd27-fallback-spec-and-carrier-binding) -- both are standalone `bin/venv-python -c` scripts
#: embedded in YAML documents, so they cannot import this constant; this module is the one site
#: where naming it is possible at all (code review round 3, Low).
_FALLBACK_SPEC_KEY_MIN_LEN = 40

#: Growth-safe anchor-phrase floor over the four CD.27 string discipline_points the retired
#: append-only-vs-origin/main guard protected only incidentally.
ANCHOR_PHRASES = (
    "S3 pointer pattern",
    "retry policies are deterministic-only",
    "T4.x atomic-plan template",
    "EXR-07",
)


def _fallback_spec_block(cd: dict) -> dict:
    specs = [p for p in cd["discipline_points"] if isinstance(p, dict) and "fallback_spec" in p]
    assert len(specs) == 1, f"fallback_spec must appear exactly once in CD.27, found {len(specs)}"
    return specs[0]["fallback_spec"]


def _maturity_point(cd: dict) -> str:
    mat = [
        p
        for p in cd["discipline_points"]
        if isinstance(p, str) and p.startswith("Lambda Durable Functions maturity monitoring")
    ]
    assert len(mat) == 1, f"expected exactly 1 maturity-monitoring point, found {len(mat)}"
    return mat[0]


def test_fallback_spec_well_formed():
    cd = cd27()
    s = _fallback_spec_block(cd)
    assert REQUIRED_FALLBACK_SPEC_KEYS <= set(s), f"fallback_spec missing {sorted(REQUIRED_FALLBACK_SPEC_KEYS - set(s))}"
    thin = {k: v for k, v in s.items() if isinstance(v, str) and len(v.strip()) < _FALLBACK_SPEC_KEY_MIN_LEN}
    assert not thin, f"fallback_spec key(s) present but contentless: {sorted(thin)}"

    sch = s["state_schema"]
    assert REQUIRED_STATE_SCHEMA_KEYS <= set(sch), f"state_schema missing {sorted(REQUIRED_STATE_SCHEMA_KEYS - set(sch))}"
    assert "one item per" in sch["grain"].lower(), f"grain must be stated as one-item-per: {sch['grain']!r}"
    assert sch["write_mode"].startswith("append_only"), f"write_mode must be append_only: {sch['write_mode']!r}"
    assert "ULID" in sch["identity"], "identity must mint a ULID at the write boundary"

    assert "validate_fallback_reevaluation" in s["reevaluation_carrier"], "reevaluation_carrier must name the registered check"
    lapse = s["lapse_condition"]
    assert "LAPSE" in lapse.upper(), f"lapse_condition must state a lapse in ESB-06 shape: {lapse!r}"
    assert any(t in lapse for t in ("ESB-04", "ESB-06", "spike")), "lapse_condition must bind to the layer-2 selection"


def test_fallback_spec_carries_no_confidential_identifier():
    cd = cd27()
    s = _fallback_spec_block(cd)
    blob = yaml.safe_dump(s, sort_keys=False)
    assert "arn:" not in blob.lower(), "fallback_spec contains an ARN (PUBLIC repository)"
    assert not re.search(r"(?<!\d)\d{12}(?!\d)", blob), "fallback_spec contains a 12-digit account-id-shaped token"


def test_maturity_point_is_phantom_free_and_carrier_bound():
    """Strictly stronger than the retired guard's incidental byte-identity coverage: the
    maturity-monitoring point must NOT still carry the phantom "recorded as an INTENT Open
    Question" clause, must NOT still carry the stale "checkpoint-replay verified" tracking
    pointer, and MUST name both fallback_spec and validate_fallback_reevaluation."""
    cd = cd27()
    m = _maturity_point(cd)
    for phantom in ("recorded as an INTENT Open Question", "checkpoint-replay verified"):
        assert phantom not in m, f"the maturity-monitoring point still carries the phantom/stale clause: {phantom}"
    for live in ("fallback_spec", "validate_fallback_reevaluation"):
        assert live in m, f"the maturity-monitoring point does not name {live}"


def test_maturity_point_names_every_gate_it_fires_on():
    """DOC-SAYS-X / CONTROL-DOES-Y guard: the control (validate_fallback_reevaluation) fires on
    every item CD.27 gates, so the text must name every one of them -- boundary-aware, so a bare
    substring match on gate T4.1 is not satisfied by a T4.10/T4.12/T4.13-class mention.

    Imports `_gate_pattern` from the carrier module itself rather than rebuilding the
    boundary-aware regex by hand -- the REGEX-IDENTITY RATCHET installed at VP step 3 exists
    precisely because a frozen hand-rolled copy silently diverges from source; a fourth copy
    here would be exactly the kind of copy that ratchet does not cover."""
    d = load_roadmap()
    cd = cd27(d)
    gates = cd["gates"]
    tok = _gate_pattern(gates)
    named = sorted(set(tok.findall(_maturity_point(cd))))
    assert set(named) == set(gates), f"control fires on {gates} but the text names only {named}"


def test_discharge_rule_point_recorded_without_declaring_an_id():
    cd = cd27()
    pts = [p for p in cd["discipline_points"] if isinstance(p, str)]
    rule = [p for p in pts if "precondition_discharge" in p]
    assert len(rule) == 1, f"expected exactly 1 discharge-rule point, found {len(rule)}"
    assert "validate_candidate_decision_ratification" in rule[0], "the discharge rule must name its enforcing guard"
    assert not re.search(r"ratification precondition \((\w+-\d+)\)", rule[0]), (
        "the discharge-rule point must not itself declare a precondition id"
    )


def test_precondition_id_floor_holds_with_no_duplicate():
    cd = cd27()
    pts = [p for p in cd["discipline_points"] if isinstance(p, str)]
    ids = re.findall(r"ratification precondition \((\w+-\d+)\)", " ".join(pts))
    assert len(ids) == len(set(ids)), f"a precondition id is claimed twice: {ids}"
    assert {"ESB-01", "ESB-04", "ESB-06"} <= set(ids), f"precondition floor broken: {sorted(set(ids))}"


def test_anchor_phrase_floor_over_incidentally_protected_strings():
    """Searches the whole discipline_points structure as dumped text, not just isinstance(p, str)
    entries -- one of the four anchors ("T4.x atomic-plan template") pre-exists this wave inside
    an accidental colon-hazard dict entry (out of this wave's scope to fix), so a str-only scan
    would miss it even though the phrase is present and unedited."""
    cd = cd27()
    blob = yaml.safe_dump(cd["discipline_points"], sort_keys=False)
    absent = [a for a in ANCHOR_PHRASES if a not in blob]
    assert not absent, f"incidentally-protected CD.27 string(s) lost: {absent}"
