"""ESB-09 guards (PLAN-esb-text-fix-bundle, amended by PLAN-executor-substrate-evidence-fold for
docs/ROADMAP-PLATFORM.yaml).

The SFN transition line recomputes from its own stated assumptions at the cited eu-west-2 rate at
exact equality (no cents rounding), with tx_per_rec and the per-transition rate PARSED out of the
same roadmap line rather than hardcoded (rec-2946). The current_scale headline recomputes from an
explicit `headline_basis` (boolean include-flag, enumerated subtotal, add-on) rather than being
asserted against a magic ceiling. A named Neon catalog egress line exists. The NAT figure is a
bracket carrying confidence medium. The gross/free-tier stance is explicit. Exactly four
`substrate_reevaluation_triggers` are present under that name. Every enumerated breakdown line is
either summed into the subtotal or explicitly excluded. The PUBLIC-repository guard: no 12-digit
AWS account id, no arn:aws: string, no ExternalId pattern, no internal hostname anywhere in the
cost text. Every priced cost line in executor_substrate_billing declares a recognised
provenance_class from a CLOSED enumeration, each with its own mandatory needle, retrieval date and
region rule (Decision 165) -- never an existence-only rate_basis check.
"""

from __future__ import annotations

import re

import pytest
import yaml

from tests.esb_text_fix._anchors import load_roadmap

RATE_BASIS_NEEDLE = "AWS Price List bulk offer files"

# Closed enumeration of recognised priced-row provenance classes (Decision 165: no per-row
# opt-out, no existence-only fallback). The region rule is a property of the CLASS: the two
# published-pricing-page classes need OPPOSITE region rules (codebuild is eu-west-2, agentcore's
# published rate is region-unqualified), so they cannot share one class without one of the two
# real rows becoming an unintended decoy for the other.
PROVENANCE_CLASSES = {
    "aws_price_list": {
        "needle": "AWS Price List bulk offer files",
        "date": "2026-08-01",
        "region_required": "eu-west-2",
    },
    "published_pricing_page_regional": {
        "needle": "AWS published pricing page (regional)",
        "date": "2026-08-21",
        "region_required": "eu-west-2",
    },
    "published_pricing_page_unqualified": {
        "needle": "AWS published pricing page (region-unqualified)",
        "date": "2026-08-21",
        "region_required": None,
    },
}


def priced_row_issues(name: str, entry: dict) -> list[str]:
    """Return one string per problem with a priced row's provenance declaration. Empty list means
    the row is well-formed. A row declaring no class, an unrecognised class, a class missing its
    needle or retrieval date, or a wrong region for its class all produce an issue -- there is no
    default class and no per-row opt-out from the rule (Decision 165)."""
    issues: list[str] = []
    pc = entry.get("provenance_class")
    if not pc:
        issues.append(f"{name}: missing provenance_class")
        return issues
    spec = PROVENANCE_CLASSES.get(pc)
    if spec is None:
        issues.append(f"{name}: unrecognised provenance_class {pc!r}")
        return issues
    rate_basis = str(entry.get("rate_basis", ""))
    if spec["needle"] not in rate_basis:
        issues.append(f"{name}: rate_basis missing the {pc!r} needle {spec['needle']!r}")
    if spec["date"] not in rate_basis:
        issues.append(f"{name}: rate_basis missing the {pc!r} retrieval date {spec['date']!r}")
    region = entry.get("region")
    if spec["region_required"] is not None:
        if region != spec["region_required"]:
            issues.append(f"{name}: region must be {spec['region_required']!r} for class {pc!r}, got {region!r}")
    else:
        if region != "not_region_qualified":
            issues.append(f"{name}: region must be 'not_region_qualified' for class {pc!r}, got {region!r}")
        caveat = str(entry.get("region_caveat", ""))
        if len(caveat) < 40:
            issues.append(f"{name}: region_caveat must be substantive (>=40 chars) for class {pc!r}, got {caveat!r}")
    return issues


def _cost_projection() -> dict:
    return load_roadmap()["cost_projection"]


def _bracket(s) -> list[float]:
    m = re.match(r"^\$?([0-9.]+)-\$?([0-9.]+)$", str(s).strip())
    assert m, f"not a bracket low-high value: {s!r}"
    return [float(x) for x in m.groups()]


def parse_sfn_assumptions(line: str) -> tuple[float, float, int, float]:
    """Extract the published (lo, hi) bracket AND the stated transitions-per-rec / per-transition
    rate from the roadmap's step_functions_transitions line, so the guard recomputes from what the
    line itself asserts rather than duplicating those two numbers as Python literals (rec-2946)."""
    lo, hi = [float(x) for x in re.match(r"^\$([0-9.]+)-([0-9.]+)", line).groups()]
    rate_m = re.search(r"\$([0-9.eE+-]+)/transition", line)
    assert rate_m, f"line does not state a per-transition rate: {line!r}"
    tx_m = re.search(r"([0-9]+)\s*transitions/rec", line)
    assert tx_m, f"line does not state transitions/rec: {line!r}"
    tx_per_rec, rate = int(tx_m.group(1)), float(rate_m.group(1))
    return lo, hi, tx_per_rec, rate


def test_sfn_transition_line_recomputes_exactly():
    cp = _cost_projection()
    line = cp["projected_100tb_scale"]["breakdown"]["step_functions_transitions"]
    assert "1-10" not in line, "the overstated $1-10 figure survives"
    lo, hi, tx_per_rec, rate = parse_sfn_assumptions(line)
    exp_lo, exp_hi = round(tx_per_rec * 100 * rate, 4), round(tx_per_rec * 300 * rate, 4)
    assert (lo, hi) == (exp_lo, exp_hi), f"published {lo}-{hi} != recomputed {exp_lo}-{exp_hi}"
    assert "eu-west-2" in line or "eu-west-2" in str(cp), "region unstated"


def test_sfn_assumptions_follow_the_stated_line():
    """rec-2946 acceptance: a MUTATED line stating a different transitions/rec figure must yield
    a correspondingly different expectation -- a parser that ignores the mutation and still
    returns 30/0.000025 regardless of the text is still hardcoded."""
    real_line = _cost_projection()["projected_100tb_scale"]["breakdown"]["step_functions_transitions"]
    _, _, real_tx, real_rate = parse_sfn_assumptions(real_line)

    mutated = re.sub(r"[0-9]+(?=\s*transitions/rec)", str(real_tx + 10), real_line, count=1)
    assert mutated != real_line, "mutation did not change the line text"
    _, _, mutated_tx, mutated_rate = parse_sfn_assumptions(mutated)
    assert mutated_tx == real_tx + 10, "parser ignored the mutated transitions/rec figure"
    assert mutated_rate == real_rate, "rate should be unaffected by the transitions/rec mutation"

    exp_lo_real = round(real_tx * 100 * real_rate, 4)
    exp_lo_mutated = round(mutated_tx * 100 * real_rate, 4)
    assert exp_lo_mutated != exp_lo_real, "mutated assumptions produced the same expectation as before"


def test_public_repository_boundary_no_confidential_identifiers():
    cp = _cost_projection()
    blob = yaml.safe_dump(cp)
    patterns = {
        "account_id": r"(?<![0-9])[0-9]{12}(?![0-9])",
        "arn": r"arn:aws:",
        "externalid": r"(?i)externalid",
        "hostname": r"(?i)[a-z0-9-]+\.(internal|local|ec2\.internal)",
    }
    hits = {k: re.findall(v, blob) for k, v in patterns.items()}
    hits = {k: v for k, v in hits.items() if v}
    assert not hits, hits


def _assert_headline_recomputes(block: dict, block_name: str) -> dict:
    """Shared ESB-09b recompute check: headline_basis.derivation covers every breakdown key,
    and total_per_month_usd recomputes from enumerated_subtotal_usd (+ add_on_usd, if included).
    Used by both current_scale and projected_100tb_scale (M4, code-review round 2: the original
    guard only covered current_scale, leaving the block this wave's own step_functions_transitions
    edit lives in without the same anti-drift coverage).

    Whole-dollar rounding convention (code-review round 3): a headline is published at whole-dollar
    precision (three-decimal cents on a $800-1500-dominated projection is exactly the false
    precision ESB-09 exists to correct), so the recompute rounds each bound to the nearest whole
    dollar before comparing -- not exact float equality. This is a DIFFERENT rule from the SFN
    per-line figure (test_sfn_transition_line_recomputes_exactly), which stays exact by design:
    that assumption-level arithmetic is small enough that cents rounding would itself hide a real
    mismatch, per ESB-09a's own acceptance criterion."""
    hb = block["headline_basis"]
    covered = set(hb["derivation"]["sums"]) | set(hb["derivation"]["excluded"])
    enumerated = set(block["breakdown"])
    assert covered == enumerated, (
        f"{block_name} headline_basis.derivation does not account for every breakdown line -- "
        f"unlisted {sorted(enumerated - covered)}, phantom {sorted(covered - enumerated)}"
    )
    sub = _bracket(hb["enumerated_subtotal_usd"])
    add = _bracket(hb["add_on_usd"])
    assert all(float(x).is_integer() for x in sub), f"{block_name} enumerated_subtotal_usd must be whole-dollar, got {sub}"
    inc = hb["includes_line_items_not_enumerated"]
    assert isinstance(inc, bool), f"{block_name} includes_line_items_not_enumerated must be an explicit boolean"
    exp_raw = [sub[0] + add[0], sub[1] + add[1]] if inc else sub
    exp = [round(x) for x in exp_raw]
    got = _bracket(block["total_per_month_usd"])
    assert got == exp, (
        f"{block_name} headline {got} does not recompute (whole-dollar-rounded) from its own basis {exp} (raw {exp_raw})"
    )
    assert all(float(x).is_integer() for x in got), f"{block_name} total_per_month_usd must be whole-dollar, got {got}"
    return hb


def test_current_scale_headline_recomputes_from_its_own_basis():
    cp = _cost_projection()
    cs = cp["current_scale"]
    assert any("neon" in k.lower() and "egress" in k.lower() for k in cs["breakdown"]), sorted(cs["breakdown"])
    egress = next(v for k, v in cs["breakdown"].items() if "neon" in k.lower() and "egress" in k.lower())
    assert "Decision 88" in egress, egress

    hb = _assert_headline_recomputes(cs, "current_scale")
    assert any("neon" in k.lower() and "egress" in k.lower() for k in hb["derivation"]["excluded"]), (
        "the Neon egress line must be the declared exclusion (Decision 88 measurement obligation)"
    )
    sub = _bracket(hb["enumerated_subtotal_usd"])
    assert sub[1] < 45, f"enumerated subtotal {sub} still sums the retired EC2/RDS lines"


def test_projected_100tb_scale_headline_recomputes_from_its_own_basis():
    cp = _cost_projection()
    ps = cp["projected_100tb_scale"]
    hb = _assert_headline_recomputes(ps, "projected_100tb_scale")
    assert not hb["derivation"]["excluded"], (
        "projected_100tb_scale has no Decision-88-style unmeasured line -- every breakdown key should be summed"
    )


def test_executor_substrate_billing_block():
    cp = _cost_projection()
    esb = cp["executor_substrate_billing"]
    assert "re_evaluation_triggers" not in esb, "rename to substrate_reevaluation_triggers"
    triggers = esb["substrate_reevaluation_triggers"]
    assert len(triggers) == 4, triggers
    assert "gross" in yaml.safe_dump(esb).lower(), "free-tier stance not stated"

    natc = esb["nat_contingency"]
    assert natc["confidence"] == "medium", f"NAT confidence must be medium, got {natc}"
    band = str(natc["standing_usd_per_month"]).strip()
    assert re.fullmatch(r"[$]?[0-9]+(?:[.][0-9]+)?-[$]?[0-9]+(?:[.][0-9]+)?", band), (
        f"NAT must be a bracket low-high, not a point value -- got {band}"
    )


def test_every_cost_line_names_region_and_rate_basis():
    """ESB-09c / Decision 165: EVERY priced key under executor_substrate_billing (the four
    per_substrate_envelope_usd_per_month rows plus the three durable_execution_corrected_rates
    rows plus this wave's two new ASSESSED rows) declares a recognised provenance_class from the
    CLOSED PROVENANCE_CLASSES enumeration -- never an existence-only rate_basis check (the
    original guard's category error, M3/code-review round 2 amended further here)."""
    cp = _cost_projection()
    esb = cp["executor_substrate_billing"]
    aws_priced_lines = {}
    aws_priced_lines.update(esb.get("per_substrate_envelope_usd_per_month") or {})
    aws_priced_lines.update(esb.get("durable_execution_corrected_rates") or {})
    assert aws_priced_lines, "no priced cost lines found in executor_substrate_billing"
    all_issues: list[str] = []
    for name, entry in aws_priced_lines.items():
        assert isinstance(entry, dict), f"{name} cost line must be a mapping carrying region/rate_basis"
        all_issues.extend(priced_row_issues(name, entry))
    assert not all_issues, all_issues

    # nat_contingency's existing carve-out stays working: it is deliberately NOT part of the
    # closed enumeration (its EFS/NAT Gateway pricing basis sits outside all three
    # PROVENANCE_CLASSES) -- it still must carry an explicit region and a non-empty, distinct
    # rate_basis.
    natc = esb.get("nat_contingency") or {}
    assert natc.get("region") == "eu-west-2", "nat_contingency missing region: eu-west-2"
    assert str(natc.get("rate_basis", "")).strip(), "nat_contingency missing rate_basis"


def _well_formed_row(pc: str) -> dict:
    spec = PROVENANCE_CLASSES[pc]
    entry = {"rate_basis": f"{spec['needle']}, fetched {spec['date']}", "provenance_class": pc}
    if spec["region_required"] is not None:
        entry["region"] = spec["region_required"]
    else:
        entry["region"] = "not_region_qualified"
        entry["region_caveat"] = (
            "AWS publishes no region-specific price list for this service; naming the service "
            "and the reason a region-qualified figure does not exist."
        )
    return entry


@pytest.mark.parametrize("pc", sorted(PROVENANCE_CLASSES))
def test_priced_row_provenance_fault_injection_per_class(pc):
    """Decision 165: prove the enumeration is non-vacuous PER CLASS. A well-formed row of the
    class is accepted; a wrong-needle row, a correct-needle-wrong-date row, an unrecognised
    class, and a class-less row are each rejected -- so a class declared with an empty or
    generic needle cannot slip through riding on a sibling class's decoy."""
    spec = PROVENANCE_CLASSES[pc]

    well_formed = _well_formed_row(pc)
    assert priced_row_issues("well_formed", well_formed) == [], "a well-formed row of this class must be accepted"

    wrong_needle = dict(well_formed)
    wrong_needle["rate_basis"] = wrong_needle["rate_basis"].replace(spec["needle"], "an unrelated pricing citation")
    assert priced_row_issues("wrong_needle", wrong_needle), f"a wrong-needle row must be rejected for class {pc!r}"

    wrong_date = dict(well_formed)
    wrong_date["rate_basis"] = wrong_date["rate_basis"].replace(spec["date"], "1999-01-01")
    assert priced_row_issues("wrong_date", wrong_date), f"a correct-needle-wrong-date row must be rejected for class {pc!r}"

    unrecognised = dict(well_formed)
    unrecognised["provenance_class"] = "totally_unrecognised_class"
    assert priced_row_issues("unrecognised", unrecognised), "an unrecognised provenance_class must be rejected"

    classless = dict(well_formed)
    del classless["provenance_class"]
    assert priced_row_issues("classless", classless), "a row declaring no provenance_class must be rejected"


def test_durable_execution_rates_corrected_not_reinvented():
    cp = _cost_projection()
    esb = cp["executor_substrate_billing"]
    rates = esb["durable_execution_corrected_rates"]
    assert rates["per_operation_usd"]["value"] == 0.0000134
    assert rates["data_written_usd_per_gb"]["value"] == 0.41
    assert rates["retention_usd_per_gb_month"]["value"] == 0.25
