"""ESB-09 guards (PLAN-esb-text-fix-bundle).

The SFN transition line recomputes from its own stated assumptions at the cited eu-west-2 rate at
exact equality (no cents rounding). The current_scale headline recomputes from an explicit
`headline_basis` (boolean include-flag, enumerated subtotal, add-on) rather than being asserted
against a magic ceiling. A named Neon catalog egress line exists. The NAT figure is a bracket
carrying confidence medium. The gross/free-tier stance is explicit. Exactly four
`substrate_reevaluation_triggers` are present under that name. Every enumerated breakdown line is
either summed into the subtotal or explicitly excluded. The PUBLIC-repository guard: no 12-digit
AWS account id, no arn:aws: string, no ExternalId pattern, no internal hostname anywhere in the
cost text. Every cost line in executor_substrate_billing names region: eu-west-2 and a rate_basis.
"""

from __future__ import annotations

import re

import yaml

from tests.esb_text_fix._anchors import load_roadmap

RATE_BASIS_NEEDLE = "AWS Price List bulk offer files"


def _cost_projection() -> dict:
    return load_roadmap()["cost_projection"]


def _bracket(s) -> list[float]:
    m = re.match(r"^\$?([0-9.]+)-\$?([0-9.]+)$", str(s).strip())
    assert m, f"not a bracket low-high value: {s!r}"
    return [float(x) for x in m.groups()]


def test_sfn_transition_line_recomputes_exactly():
    cp = _cost_projection()
    line = cp["projected_100tb_scale"]["breakdown"]["step_functions_transitions"]
    assert "1-10" not in line, "the overstated $1-10 figure survives"
    lo, hi = [float(x) for x in re.match(r"^\$([0-9.]+)-([0-9.]+)", line).groups()]
    tx_per_rec, rate = 30, 0.000025
    exp_lo, exp_hi = round(tx_per_rec * 100 * rate, 4), round(tx_per_rec * 300 * rate, 4)
    assert (lo, hi) == (exp_lo, exp_hi), f"published {lo}-{hi} != recomputed {exp_lo}-{exp_hi}"
    assert "eu-west-2" in line or "eu-west-2" in str(cp), "region unstated"


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
    """ESB-09c: EVERY priced key under executor_substrate_billing names a region and a
    rate_basis -- not just the two AWS-Price-List-sourced categories (M3, code-review round 2:
    the original guard scoped itself around nat_contingency, the one line that would have
    failed it)."""
    cp = _cost_projection()
    esb = cp["executor_substrate_billing"]
    aws_priced_lines = {}
    aws_priced_lines.update(esb.get("per_substrate_envelope_usd_per_month") or {})
    aws_priced_lines.update(esb.get("durable_execution_corrected_rates") or {})
    assert aws_priced_lines, "no priced cost lines found in executor_substrate_billing"
    for name, entry in aws_priced_lines.items():
        assert isinstance(entry, dict), f"{name} cost line must be a mapping carrying region/rate_basis"
        assert entry.get("region") == "eu-west-2", f"{name} missing region: eu-west-2"
        assert RATE_BASIS_NEEDLE in str(entry.get("rate_basis", "")), f"{name} missing rate_basis"
        assert "2026-08-01" in str(entry.get("rate_basis", "")), f"{name} rate_basis missing fetch date"

    # nat_contingency is priced too, but its rate_basis is deliberately NOT the AWS Price List
    # (EFS/NAT Gateway pricing sits outside those bulk offer files -- see the plan's context) --
    # it still must carry an explicit region and a non-empty, distinct rate_basis.
    natc = esb.get("nat_contingency") or {}
    assert natc.get("region") == "eu-west-2", "nat_contingency missing region: eu-west-2"
    assert str(natc.get("rate_basis", "")).strip(), "nat_contingency missing rate_basis"


def test_durable_execution_rates_corrected_not_reinvented():
    cp = _cost_projection()
    esb = cp["executor_substrate_billing"]
    rates = esb["durable_execution_corrected_rates"]
    assert rates["per_operation_usd"]["value"] == 0.0000134
    assert rates["data_written_usd_per_gb"]["value"] == 0.41
    assert rates["retention_usd_per_gb_month"]["value"] == 0.25
