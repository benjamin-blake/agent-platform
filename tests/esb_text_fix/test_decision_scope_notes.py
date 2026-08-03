"""ESB-10 / ESB-11 / ESB-04 / ESB-06 guards (PLAN-esb-text-fix-bundle).

Both DECISIONS.md trailers use the PINNED `> **Update (YYYY-MM-DD):**` form read from
docs/contracts/decision-entry.yaml amendment_forms (with `[Amendment ...]` explicitly rejected,
since neither trailer amends anything) and sit after the entry body; neither uses a supersession
verb; Decision 39's and Decision 75's original bodies are unchanged versus origin/main (append-only
-- no line removed or rewritten). CD.27's title no longer names the layer-2 substrate; CD.27's
cross-references name T4.12 and no longer offer the retired runner-cron option; the runtime list
includes .NET/C#. Both ratification-obligation discipline_points are present with the Decision 39
managed-primitive clause and the ESB-06 lapse clause. CD.27 remains state pending with
filed_via pending_log_decision_lambda.
"""

from __future__ import annotations

import difflib
import re
import subprocess

import yaml

from tests.esb_text_fix._anchors import REPO_ROOT, cd27, load_decisions_text, load_roadmap, mechanism_hits, tier_item

DECISION_HEADING_RE = re.compile(r"^## Decision (\d+):.*$", re.MULTILINE)


def _sections(text: str) -> dict[int, str]:
    headings = list(DECISION_HEADING_RE.finditer(text))
    out = {}
    for i, m in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        out[int(m.group(1))] = text[m.start() : end]
    return out


def _origin_main_decisions_text() -> str:
    result = subprocess.run(
        ["git", "show", "origin/main:docs/DECISIONS.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _amendment_forms() -> list[dict]:
    contract_path = REPO_ROOT / "docs/contracts/decision-entry.yaml"
    return yaml.safe_load(contract_path.read_text(encoding="utf-8"))["amendment_forms"]


def test_both_trailers_use_pinned_blockquote_update_form():
    forms = _amendment_forms()
    pinned = [f for f in forms if f["form"] == "blockquote_update"]
    assert len(pinned) == 1, f"blockquote_update form missing from the contract -- {[f['form'] for f in forms]}"
    prefix = pinned[0]["example"].split("(")[0].strip()

    text = load_decisions_text()
    blocks = _sections(text)
    for n in (39, 75):
        assert prefix in blocks[n], f"Decision {n} trailer missing or not the pinned blockquote_update form"
        assert "[Amendment " not in blocks[n], f"Decision {n} must not use [Amendment ...] -- it amends nothing"


def test_neither_trailer_uses_a_supersession_verb():
    forms = _amendment_forms()
    prefix = [f for f in forms if f["form"] == "blockquote_update"][0]["example"].split("(")[0].strip()
    text = load_decisions_text()
    blocks = _sections(text)
    verb = re.compile(r"(?:[Ss]upersedes|[Aa]mends|partially supersedes)\s+Decision\s+\d+")
    for n in (39, 75):
        tail = blocks[n][blocks[n].rindex(prefix) :]
        hits = verb.findall(tail)
        assert not hits, f"supersession verb in Decision {n} trailer: {hits}"


def test_decision_bodies_unchanged_append_only_vs_origin_main():
    current_blocks = _sections(load_decisions_text())
    original_blocks = _sections(_origin_main_decisions_text())
    for n in (39, 75):
        orig_lines = original_blocks[n].splitlines()
        cur_lines = current_blocks[n].splitlines()
        sm = difflib.SequenceMatcher(a=orig_lines, b=cur_lines, autojunk=False)
        bad_ops = [op for op in sm.get_opcodes() if op[0] in ("replace", "delete")]
        assert not bad_ops, f"Decision {n} body was edited in place (non-append change): {bad_ops}"


def test_cd27_title_no_longer_names_layer2_substrate():
    cd = cd27()
    hits = mechanism_hits(cd["title"])
    assert not hits, f"CD.27 title still mandates the layer-2 substrate by name: {hits}"


def test_cd27_cross_references_point_at_t412_and_drop_runner_cron():
    cd = cd27()
    detail = cd["detail"]
    assert "T4.12" in detail, "CD.27 cross-reference must name T4.12, not the rewritten T4.3"
    # Normalise hyphens/whitespace before the ban check -- a spelling change (space vs hyphen)
    # must not silently pass this guard (M1, code-review round 2).
    normalised = re.sub(r"[\s-]+", " ", detail.lower())
    assert "self hosted runner cron" not in normalised, "the CD.21-retired self-hosted-runner-cron option must be dropped"


def test_runtime_list_includes_dotnet():
    cd = cd27()
    detail = cd["detail"]
    assert ".NET" in detail or "C#" in detail, "CD.27 runtime list must include .NET/C#"


def test_cd27_stays_pending_with_expected_filed_via():
    cd = cd27()
    assert cd["state"] == "pending"
    assert cd.get("ratified_as") is None
    assert cd["filed_via"] == "pending_log_decision_lambda"


def test_ratification_obligations_present():
    cd = cd27()
    blob = str(cd["discipline_points"]).lower()
    assert "managed orchestration primitive" in blob, "ESB-04 obligation missing its Decision 39 managed-primitive clause"
    assert "lapse" in blob, "ESB-06 obligation missing its explicit lapse clause"
    assert "decision 39" in blob, "ESB-04 obligation must cite Decision 39"


def test_cd27_scheduled_agent_loop_reference_resolves():
    """H1 class guard: a cross-reference this diff renamed must still resolve to something real.

    CD.27's closing note identifies which tier_item decides the scheduled-agent loop's own
    substrate. Whatever id it names there must actually exist in tier_items -- catching a
    reference left dangling by a rename (the H1 defect class). It does NOT also need to be
    gated: `gates` and this closing-note cross-reference are different fields with different
    meanings (code-review round 2, M2) -- CD.27 legitimately gates on T4.3 (which still declares
    `related_candidate_decisions: [CD.27, CD.28]`) while its closing note correctly names T4.12
    as the tier_item that owns the still-open substrate choice; conflating the two was round 1's
    error, not this plan's to re-introduce.
    """
    d = load_roadmap()
    cd = cd27(d)
    m = re.search(r"(T4\.\d+[a-z]?)\s*\(scheduled-agent loop", cd["detail"])
    assert m, "CD.27 detail no longer names a tier_item as the scheduled-agent loop owner"
    owner_id = m.group(1)
    tier_item_ids = {i["id"] for i in d["tier_items"]}
    assert owner_id in tier_item_ids, f"CD.27 names nonexistent tier_item {owner_id!r} as the scheduled-agent loop owner"


def test_cd27_does_not_preempt_t412_substrate_choice():
    """H1 guard (code-review round 2): CD.27's closing note may drop the CD.21-retired
    execution alternative, but must not assert what T4.12's own still-open exit criterion cD
    (Step Functions scheduled execution vs GitHub-hosted Actions schedule) has not yet decided."""
    d = load_roadmap()
    cd = cd27(d)
    detail = cd["detail"]
    t412 = tier_item("T4.12", d)
    cd_criterion = next(c for c in t412["exit_criteria"] if isinstance(c, dict) and c.get("id") == "cD")
    assert cd_criterion["status"] == "open", "T4.12 cD must still be open for this guard to be meaningful"
    assert "GitHub-hosted Actions schedule" in cd_criterion["text"], (
        "T4.12 cD's alternative option text moved -- re-derive this guard"
    )
    assert re.search(r"is\s+Step Functions scheduled execution\b", detail) is None, (
        "CD.27 must not assert T4.12's substrate outcome while T4.12 cD is still open"
    )


def test_cd27_gates_reference_only_existing_tier_items():
    d = load_roadmap()
    cd = cd27(d)
    tier_item_ids = {i["id"] for i in d["tier_items"]}
    gates = cd.get("gates") or []
    dangling = [g for g in gates if g not in tier_item_ids]
    assert not dangling, f"CD.27 gates references nonexistent tier_item id(s): {dangling}"


def test_cd27_exit_criterion_cross_references_resolve():
    """H1 class guard: a discipline_points reference to 'T4.x exit criterion <id-or-quote>'
    must resolve against that tier_item's actual exit_criteria -- catching the H1 defect
    (CD.27's maturity-monitoring point quoted T4.2's old c1 text verbatim; renaming c1 left the
    quote dangling). Strictly stronger as of wave 3 (ESB-02 remediation,
    PLAN-esb-fallback-spec-carrier): the former protected-stale-quote exemption module constant
    (which guarded the T4.2 "checkpoint-replay verified" quote) is retired now that wave 3 has
    rewritten the maturity-monitoring point in place and the stale quote it protected no longer
    exists -- every quoted T4.x criterion reference must now resolve, with no exempt set."""
    d = load_roadmap()
    cd = cd27(d)
    points = [p for p in cd["discipline_points"] if isinstance(p, str)]
    blob = " ".join(points)

    quoted_refs = re.findall(r"(T4\.\d+[a-z]?) exit criterion \"([^\"]+)\"", blob)
    for item_id, phrase in quoted_refs:
        item = tier_item(item_id, d)
        criteria_text = " ".join(str(c) for c in item["exit_criteria"])
        assert phrase in criteria_text, (
            f"CD.27 quotes {item_id} exit criterion {phrase!r} verbatim, but it no longer appears "
            f"in {item_id}'s exit_criteria -- a renamed criterion left a dangling quoted reference"
        )

    id_refs = re.findall(r"(T4\.\d+[a-z]?) exit criterion ([a-z][a-z0-9_]*)\b", blob)
    for item_id, crit_ref in id_refs:
        item = tier_item(item_id, d)
        assert item["exit_criteria"], (
            f"CD.27 references {item_id} exit criterion {crit_ref!r}, but {item_id} has no exit_criteria"
        )
        # This plan's own convention treats a bare "c<N>" reference as the (N-1)-th bare-string
        # criterion (see this plan's VP steps' `c1=t42['exit_criteria'][0]`). Verify it resolves
        # to a real index and, since every such reference in this plan is property-bound, that
        # the resolved criterion actually names at least one of P1/P2/P3.
        if re.fullmatch(r"c[0-9]+", crit_ref):
            idx = int(crit_ref[1:]) - 1
            n_criteria = len(item["exit_criteria"])
            assert 0 <= idx < n_criteria, (
                f"CD.27 references {item_id} exit criterion {crit_ref!r}, out of range for {n_criteria} criteria"
            )
            resolved = str(item["exit_criteria"][idx])
            assert any(p in resolved for p in ("P1", "P2", "P3")), (
                f"CD.27's {crit_ref!r} reference for {item_id} resolves to a criterion carrying none of P1/P2/P3: {resolved!r}"
            )
