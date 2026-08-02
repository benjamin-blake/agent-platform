"""ESB-05 + ESB-01 guards (PLAN-esb-text-fix-bundle).

Exactly P1/P2/P3 are defined once, in CD.27's resume_properties discipline point. T4.2 c1, all
four T4.1 persona-node typings AND CD.27's personas discipline point each reference the property
ids POSITIVELY -- the personas point is not exempt, since it is the exact site ESB-10 targets and
a negative-only check there is the mechanism-free-but-property-free failure this guard exists to
catch. Mechanism vocabulary is absent from all NINE de-mechanised sites: the seven property-bound
contract sites (c1, the four node typings, the personas point, the Fargate escape-hatch point)
plus the two descriptive sites (CD.27's title and its narrowly_supersedes clause). c1 asserts
workspace continuity and names no backing store. T4.2's exit criteria remain bare strings.
"""

from __future__ import annotations

from tests.esb_text_fix._anchors import cd27, load_roadmap, mechanism_hits, persona_node_lines, tier_item

PROPERTY_IDS = ("P1", "P2", "P3")

BACKING_STORE_TOKENS = ("dynamodb", "efs", "s3 ", "s3-", " s3", "database", "disk", "elasticache", "rds")


def _resume_properties_entries(cd: dict) -> list[dict]:
    return [p for p in cd["discipline_points"] if isinstance(p, dict) and "resume_properties" in p]


def _personas_discipline_points(cd: dict) -> list[str]:
    return [p for p in cd["discipline_points"] if isinstance(p, str) and "Agent personas" in p]


def _fargate_discipline_points(cd: dict) -> list[str]:
    return [p for p in cd["discipline_points"] if isinstance(p, str) and "ECS Run Task escape hatch" in p]


def test_resume_properties_defined_exactly_once_as_p1_p2_p3():
    cd = cd27()
    rp = _resume_properties_entries(cd)
    assert len(rp) == 1, f"resume_properties must be defined exactly once, found {len(rp)}"
    props = rp[0]["resume_properties"]
    assert set(props) == {"P1", "P2", "P3"}, f"expected exactly P1/P2/P3, got {sorted(props)}"
    for pid in PROPERTY_IDS:
        assert not mechanism_hits(props[pid]), f"{pid} definition carries mechanism vocabulary"


def test_four_persona_node_typings_present():
    t41 = tier_item("T4.1")
    nodes = persona_node_lines(t41)
    assert len(nodes) == 4, f"expected 4 persona-node typings, found {len(nodes)}"


def test_property_bound_sites_reference_p1_p2_p3_positively():
    d = load_roadmap()
    cd = cd27(d)
    t41 = tier_item("T4.1", d)
    t42 = tier_item("T4.2", d)
    c1 = t42["exit_criteria"][0]
    nodes = persona_node_lines(t41)
    personas = _personas_discipline_points(cd)
    fargate = _fargate_discipline_points(cd)
    assert len(personas) == 1, f"expected 1 personas discipline point, found {len(personas)}"
    assert len(fargate) == 1, f"expected 1 Fargate escape-hatch discipline point, found {len(fargate)}"

    property_bound = {"c1": c1, "personas_discipline_point": personas[0], "fargate_discipline_point": fargate[0]}
    property_bound.update({f"node[{n}]": t for n, t in enumerate(nodes)})

    missing = {k: [p for p in PROPERTY_IDS if p not in v] for k, v in property_bound.items()}
    missing = {k: v for k, v in missing.items() if v}
    assert not missing, f"contract text does not reference the resume properties: {missing}"


def test_nine_de_mechanised_sites_are_mechanism_free():
    d = load_roadmap()
    cd = cd27(d)
    t41 = tier_item("T4.1", d)
    t42 = tier_item("T4.2", d)
    c1 = t42["exit_criteria"][0]
    nodes = persona_node_lines(t41)
    personas = _personas_discipline_points(cd)
    fargate = _fargate_discipline_points(cd)

    sites = {"c1": c1, "personas_discipline_point": personas[0], "fargate_discipline_point": fargate[0]}
    sites.update({f"node[{n}]": t for n, t in enumerate(nodes)})
    sites["cd_title"] = cd["title"]
    sites["narrowly_supersedes_clause"] = cd["narrowly_supersedes"]["clause"]
    assert len(sites) == 9, f"expected 9 de-mechanised sites, found {len(sites)}"

    hits = {k: mechanism_hits(v) for k, v in sites.items()}
    hits = {k: v for k, v in hits.items() if v}
    assert not hits, f"mechanism vocabulary survives at a de-mechanised site: {hits}"


def test_c1_asserts_workspace_continuity_and_names_no_backing_store():
    t42 = tier_item("T4.2")
    c1 = t42["exit_criteria"][0].lower()
    assert "workspace" in c1, "c1 must assert workspace continuity (ESB-01 half)"
    hits = [tok for tok in BACKING_STORE_TOKENS if tok in c1]
    assert not hits, f"c1 must name no backing store (ESB-01 defers the store choice): {hits}"


def test_t42_criteria_remain_bare_strings():
    t42 = tier_item("T4.2")
    for crit in t42["exit_criteria"]:
        assert isinstance(crit, str), f"T4.2 exit criterion became non-string (colon-hazard?): {crit!r}"
