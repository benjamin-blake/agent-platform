"""ESB-01 criteria guards (PLAN-esb-workspace-store-criteria, wave 2).

CD.43 records the criteria (W1-W8) against which the executor's workspace backing store is
selected -- it does NOT choose a store. These ten guards join wave 1's tests/esb_text_fix/
package rather than a new one: four are direct siblings of wave 1 guards on the same objects
(T4.1-vs-T4.2 bare-string criteria, the CD.43-vs-CD.27 gates resolution, the CD.43-vs-CD.27
pending/filed_via shape, and the layer-2 precondition floor extending wave 1's ESB-04/ESB-06
obligations test), and _anchors.py already names "docs/ROADMAP-PLATFORM.yaml" as a literal
token that channel-2-selects this package on any roadmap edit, anticipating exactly this in
later ESB waves. Eight of these ten guards fail on the pre-edit tree;
test_t41_exit_criteria_remain_bare_strings is a regression guard that passes before and after
by design. A ninth regression guard that used to sit here -- CD.27 discipline_points
byte-identity vs origin/main -- is retired by wave 3 (ESB-02 remediation,
PLAN-esb-fallback-spec-carrier): it guarded this package's own boundary with wave 3 and was
always transient by construction (wave 2's own waiver said so); wave 3 legitimately owns and
rewrites the CD.27 maturity-monitoring clause it protected, so restoring the pre-edit text
would be wrong, not a regression. Its durable half (the maturity clause staying phantom-free
and carrier-bound) is now asserted, strictly stronger, by tests/esb_text_fix/test_fallback_spec.py.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from tests.esb_text_fix._anchors import cd27, load_roadmap, tier_item

REQUIRED_CRITERIA_IDS = {"W1", "W2", "W3", "W4", "W5", "W6", "W7", "W8"}
REQUIRED_OPTIONS = {
    "efs_mount",
    "s3_sync",
    "container_local_disk",
    "git_as_store_commit_at_step_boundaries",
    "s3_express_one_zone",
    "fsx_managed_filesystem",
    "lambda_ephemeral_tmp_10gb",
}
REQUIRED_COVERAGE_CASES = {"cross_invocation_persistence", "inter_persona_handoff", "persona_to_ecs_task_handoff"}


def cd43(d: dict[str, Any] | None = None) -> dict[str, Any]:
    d = d if d is not None else load_roadmap()
    cds = [c for c in d["candidate_decisions"] if c["id"] == "CD.43"]
    assert cds, "CD.43 absent from candidate_decisions -- the criteria CD was never added"
    return cds[0]


def _workspace_block(cd: dict) -> dict:
    blocks = [p for p in cd["discipline_points"] if isinstance(p, dict) and "workspace_store_selection" in p]
    assert len(blocks) == 1, f"workspace_store_selection must appear exactly once, found {len(blocks)}"
    return blocks[0]["workspace_store_selection"]


def test_cd43_is_pending_and_r2_shaped():
    cd = cd43()
    assert cd["state"] == "pending", cd["state"]
    assert cd.get("ratified_as") is None, cd.get("ratified_as")
    assert cd["filed_via"] == "pending_log_decision_lambda", cd["filed_via"]


def test_cd43_gates_reference_only_existing_tier_items():
    d = load_roadmap()
    cd = cd43(d)
    tier_ids = {i["id"] for i in d["tier_items"]}
    gates = cd.get("gates") or []
    assert gates == ["T4.1", "T4.2"], gates
    dangling = [g for g in gates if g not in tier_ids]
    assert not dangling, f"CD.43 gates nonexistent tier_item(s): {dangling}"


def test_selection_criteria_cover_w1_w8_and_are_non_empty_strings():
    cd = cd43()
    b = _workspace_block(cd)
    sc = b["selection_criteria"]
    assert REQUIRED_CRITERIA_IDS <= set(sc), f"selection_criteria missing {sorted(REQUIRED_CRITERIA_IDS - set(sc))}"
    bad = {k: type(v).__name__ for k, v in sc.items() if not isinstance(v, str) or not v.strip()}
    assert not bad, f"criteria must be non-empty strings (a colon-space turns a scalar into a mapping): {bad}"


def test_store_choice_deferred_and_evaluation_floors_hold():
    cd = cd43()
    b = _workspace_block(cd)
    assert b["status"] == "criteria_only", f"status is not criteria_only: {b['status']!r}"
    assert b["selected_store"] == "TBD_at_CD.43_ratification", f"a store was selected: {b['selected_store']!r}"
    opts, cases = b["option_set"], b["coverage_cases"]
    assert len(opts) == len(set(opts)), f"option_set has duplicates: {opts}"
    assert REQUIRED_OPTIONS <= set(opts), f"option_set missing {sorted(REQUIRED_OPTIONS - set(opts))}"
    assert len(cases) == len(set(cases)), f"coverage_cases has duplicates: {cases}"
    assert REQUIRED_COVERAGE_CASES <= set(cases), cases
    assert b["options_considered_and_rejected"], "a rejected option must be recorded with its reason, not silently omitted"


def test_cd43_and_its_gated_items_are_bidirectionally_linked():
    d = load_roadmap()
    cd = cd43(d)
    items = {i["id"]: i for i in d["tier_items"]}
    unlinked = [g for g in cd["gates"] if "CD.43" not in (items[g].get("related_candidate_decisions") or [])]
    assert not unlinked, f"tier item(s) gated by CD.43 never name it back: {unlinked}"


def test_t41_names_the_criteria_and_leaves_the_choice_open():
    d = load_roadmap()
    cd = cd43(d)
    b = _workspace_block(cd)
    t41 = tier_item("T4.1", d)
    named = [c for c in t41["exit_criteria"] if isinstance(c, str) and "CD.43" in c]
    assert len(named) == 1, f"expected exactly 1 T4.1 criterion naming CD.43, found {len(named)}"
    crit = named[0]
    assert "workspace_uri" in crit, "the criterion must bind to prepare_workspace workspace_uri"
    declared = sorted(b["selection_criteria"])
    missing = [w for w in declared if w not in crit]
    assert not missing, f"T4.1 names CD.43 but not its criteria {missing} (declared: {declared})"
    chosen = [o for o in b["option_set"] if o in crit]
    assert not chosen, f"T4.1 criterion names a candidate store as chosen: {chosen}"


def test_t41_exit_criteria_remain_bare_strings():
    t41 = tier_item("T4.1")
    for crit in t41["exit_criteria"]:
        assert isinstance(crit, str), f"T4.1 exit criterion became non-string (colon-hazard?): {crit!r}"


def test_layer2_ratification_preconditions_cover_esb01_esb04_esb06():
    d = load_roadmap()
    cd = cd27(d)
    points = [p for p in cd["discipline_points"] if isinstance(p, str)]
    required = {"ESB-01", "ESB-04", "ESB-06"}
    found = [m for p in points for m in re.findall(r"Layer-2 ratification precondition \((ESB-\d+)\)", p)]
    assert len(found) == len(set(found)), f"a finding id is claimed by two preconditions: {found}"
    assert required <= set(found), f"missing layer-2 ratification precondition(s): {sorted(required - set(found))}"
    esb01 = [p for p in points if "Layer-2 ratification precondition (ESB-01)" in p]
    assert len(esb01) == 1, f"expected exactly 1 ESB-01 precondition, found {len(esb01)}"
    assert "CD.43" in esb01[0], "the ESB-01 precondition must point at the CD holding the criteria"


def test_criteria_recompute_from_a_stated_basis_and_publish_no_figure():
    cd = cd43()
    sc = _workspace_block(cd)["selection_criteria"]
    money = {k: re.search(r"[\$]\s*\d", v).group(0) for k, v in sc.items() if re.search(r"[\$]\s*\d", v)}
    assert not money, f"a criterion publishes a cost figure instead of a basis: {money}"
    assert "terraform/personal/variables.tf" in sc["W3"], "W3 must name the region-pin source"
    assert "RECOMPUTED" in sc["W3"], "W3 must demand recomputation at decision time"
    assert "Decision 100" in sc["W8"], "W8 must name Decision 100 as the standard a self-built store argues against"


def test_cd43_carries_no_confidential_identifier():
    cd = cd43()
    blob = yaml.safe_dump(cd, sort_keys=False)
    assert "arn:" not in blob.lower(), "CD.43 text contains an ARN (PUBLIC repository)"
    assert not re.search(r"(?<!\d)\d{12}(?!\d)", blob), "CD.43 text contains a 12-digit account-id-shaped token"
