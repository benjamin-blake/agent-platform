"""ESB-03 persona-routing-rationale guards (PLAN-esb-routing-rationale, wave 4).

Guards the Decision 164 governance record that closes audit finding ESB-03: why T4.2's executor
personas route to the Decision 122 LiteLLM tiers even though they satisfy Decision 116's agentic
criterion, and the consequence a reopen would carry (the viable persona substrate set collapses to
the CLI-hosting class, taking the CD.27 incumbent `durable_functions` and its ESB-02 fallback
`self_checkpointed_lambda_dynamodb` with it).

Three hazards this wave measured that the eight-field registry rows structurally cannot carry:

MATCHER ASYMMETRY -- two different matchers read Decision 164's title and disagree, which is why
the Decision 122 forward pointer is guard-enforced while the Decision 116 one is voluntary.
`_EDGE_RE` in scripts/checks/decisions/validate_supersession_annotations.py requires the relation
word IMMEDIATELY adjacent to its target, so on the title's `(amends Decision 122 and Decision 116)`
parenthetical it extracts ONLY 122 -- making the (164, 122) edge real and FAILing that guard unless
Decision 122's block carries a "Decision 164" backpointer. `extract_amends_edges` in
scripts/decisions_md.py uses the whitelist-continuation grammar ("and-continuation") and extracts
BOTH, which is why the index projection reads `amends: [116, 122]`. No (164, 116) supersession edge
is extracted, so the Decision 116 trailer is a class-versus-site sweep rather than a mechanical
obligation. This module deliberately does NOT assert the absence of a (164, 116) edge: that would
pin a current limitation of someone else's regex, and widening `_EDGE_RE` to handle the
and-continuation (owned by rec-2971) is a legitimate improvement that must not redden these guards.

TITLE-STRIP TRUNCATION -- the parser stores `title` as `re.sub(r"\\s*\\(.*?\\)\\s*$", "", raw_title)`
(scripts/decisions_md.py), whose lazy quantifier plus end-anchor drops EVERYTHING from the FIRST
opening parenthesis onward. Every load-bearing phrase must therefore sit BEFORE the `(amends ...)`
parenthetical or it is invisible to the decision-scout index.

RETIREMENT OWNER -- the index-projection test below reads docs/decisions-index.json, which Decision
160 point 13 designates an INTERIM triage surface. T1.5 c1 owns replacing decision-scout's Phase 1
step 1 with a queried portal/tool call; when that lands, this file stops being the triage surface
and the graduated row `dec-164-index-triage-discoverable` (plus the test below) RETIRES WITH T1.5 c1
rather than becoming a standing maintenance obligation.

The grep-row CLASS test at the bottom is not graduable (it passes on origin/main, so it cannot meet
VF-05 / Decision 132 differential admission) and ships as a standing unit test instead -- which is
also the only carrier that keeps guarding the class after this PR merges, since merged registry rows
are never re-executed.
"""

from __future__ import annotations

import json
import re

import yaml

from scripts.decisions_md import decision_header_numbers, parse_decisions_md
from scripts.verification_checks import CheckStatus, GrepCountCheck
from tests.esb_text_fix._anchors import REPO_ROOT, load_roadmap

#: The decision number this wave mints. Shifted in lockstep with every other site if a concurrent
#: PR claims it (the plan's DECISION NUMBER constraint -- all sites or none).
DECISION_NUMBER = 164

DECISIONS_PATH = "docs/DECISIONS.md"
DECISIONS_INDEX_PATH = "docs/decisions-index.json"
ROADMAP_PATH = "docs/ROADMAP-PLATFORM.yaml"
REGISTRY_PATH = "config/agent/verification_registry/registry.yaml"

AMENDMENT_TRAILER_PREFIX = "[Amendment 2026-08-03:"
AMENDED_ENTRIES = (116, 122)

#: Relation phrases that would manufacture a spurious supersession edge if they appeared inside an
#: amendment trailer -- each such edge would need its own forward pointer on a further victim.
_RELATION_RE = re.compile(r"(?:Supersedes|supersedes|amends|Amends|partially supersedes) Decision [0-9]+")

#: The rationale strands and consequence names the finding requires the entry to state as a
#: principle rather than merely gesture at.
REQUIRED_BODY_TOKENS = (
    "SCHEDULED AGENTS ONLY",
    "CLI-hosting class",
    "long_running_container",
    "hosted_cli_runner",
    "self_checkpointed_lambda_dynamodb",
    "durable_functions",
    "0.05/rec",
    "Max x5 programmatic pool",
    "Decision 47",
    "Escape-hatch preservation",
    "price that collapse explicitly",
    "**Related:**",
)

#: Decision 151 clause 1: the Intent marker is placed narratively after Problem and before Decision.
MARKER_ORDER = ("**Problem:**", "**Intent:**", "**Decision:**")

#: The dec-122 ratification header literal is a live graduated grep_count row with operator `eq`
#: and count 1 over docs/DECISIONS.md, and its pattern is NOT line-anchored -- reproducing it inside
#: Decision 164's body would double the count.
DEC_122_HEADER_LITERAL = "## Decision 122: Ratify CD.28"


def _entry() -> dict:
    rows = {r["decision_id"]: r for r in parse_decisions_md()}
    assert DECISION_NUMBER in rows, f"no ## Decision {DECISION_NUMBER}: entry in {DECISIONS_PATH}"
    return rows[DECISION_NUMBER]


def _blocks() -> dict[int, str]:
    return {r["decision_id"]: r["raw_block"] for r in parse_decisions_md()}


def _index_entry() -> dict:
    data = json.loads((REPO_ROOT / DECISIONS_INDEX_PATH).read_text(encoding="utf-8"))
    hits = [e for e in data["decisions"] if e["number"] == DECISION_NUMBER]
    assert hits, f"no entry numbered {DECISION_NUMBER} in {DECISIONS_INDEX_PATH}"
    return hits[0]


class TestDecisionEntryRecorded:
    """The rationale and the reopen consequence are recorded as a principle, read via the shared parser."""

    def test_status_and_date_markers(self) -> None:
        row = _entry()
        assert row["status"] == "Decided", row["status"]
        assert row["decided_date"] == "2026-08-03", row["decided_date"]

    def test_intent_reversal_and_decision_markers_present(self) -> None:
        row = _entry()
        assert row["intent"], "**Intent:** marker missing or empty"
        assert row["reversal_conditions"], "**Reversal conditions:** marker missing or empty"
        assert row["decision_text"], "**Decision:** marker missing or empty"

    def test_marker_order_is_problem_intent_decision(self) -> None:
        """Decision 151 clause 1's narrative order, made executable on this plan's own artifact."""
        block = _entry()["raw_block"]
        offsets = [block.find(marker) for marker in MARKER_ORDER]
        assert all(off >= 0 for off in offsets), (MARKER_ORDER, offsets)
        assert offsets == sorted(offsets), (MARKER_ORDER, offsets)

    def test_body_states_every_rationale_strand_and_consequence(self) -> None:
        block = _entry()["raw_block"]
        missing = [tok for tok in REQUIRED_BODY_TOKENS if tok not in block]
        assert not missing, missing

    def test_body_does_not_reproduce_the_dec_122_header_literal(self) -> None:
        block = _entry()["raw_block"]
        assert DEC_122_HEADER_LITERAL not in block, (
            "the dec-122 header literal is reproduced inside the new entry and would double the "
            "pinned grep_count row dec-122-ratification-header-present"
        )

    def test_title_survives_the_parenthetical_strip(self) -> None:
        """The load-bearing phrases sit BEFORE the first parenthesis -- see TITLE-STRIP TRUNCATION."""
        title = _entry()["title"]
        missing = [k for k in ("LiteLLM", "claude -p", "CLI-hosting class") if k not in title]
        assert not missing, (missing, title)


class TestIndexProjection:
    """Discoverability, asserted on docs/decisions-index.json -- the surface decision-scout triages.

    RETIREMENT OWNER: retires with T1.5 c1 (Decision 160 point 13). See the module docstring.
    """

    def test_entry_is_live(self) -> None:
        assert _index_entry()["live"] is True

    def test_amends_projects_both_parents_sorted(self) -> None:
        """`extract_amends_edges` reads the and-continuation, so both parents project (sorted)."""
        assert _index_entry()["amends"] == sorted(AMENDED_ENTRIES)

    def test_triage_excerpt_is_intent_sourced_and_bounded(self) -> None:
        entry = _index_entry()
        assert entry["triage_excerpt_source"] == "Intent", entry["triage_excerpt_source"]
        assert len(entry["triage_excerpt"]) <= 320, len(entry["triage_excerpt"])

    def test_reopen_consequence_is_inside_the_triage_window(self) -> None:
        excerpt = _index_entry()["triage_excerpt"]
        assert "CLI-hosting class" in excerpt, excerpt

    def test_lambda_category_tag_present(self) -> None:
        """`lambda` is the tag a future T4.2 persona plan's own approach derives."""
        assert "lambda" in _index_entry()["category_tags"], _index_entry()["category_tags"]


class TestForwardPointersOnBothAmendedEntries:
    """CLASS sweep: both amended entries carry the trailer, not only the guard-enforced one."""

    def test_both_blocks_carry_the_dated_trailer_naming_the_successor(self) -> None:
        blocks = _blocks()
        bad = [
            n
            for n in AMENDED_ENTRIES
            if AMENDMENT_TRAILER_PREFIX not in blocks[n] or f"Decision {DECISION_NUMBER}" not in blocks[n]
        ]
        assert not bad, bad

    def test_neither_trailer_introduces_a_spurious_relation_phrase(self) -> None:
        blocks = _blocks()
        spurious = {n: _RELATION_RE.findall(blocks[n].split(AMENDMENT_TRAILER_PREFIX)[1]) for n in AMENDED_ENTRIES}
        assert not any(spurious.values()), spurious


class TestRoadmapCitations:
    """The finding's own acceptance clause, plus the referential property no repo-wide guard supplies."""

    @staticmethod
    def _items() -> tuple[dict, dict]:
        roadmap = load_roadmap()
        by_id = {i["id"]: i for i in roadmap["tier_items"]}
        return by_id["T4.2"], by_id["T4.12"]

    def test_t4_2_intent_cites_the_decision(self) -> None:
        t42, _ = self._items()
        assert f"Decision {DECISION_NUMBER}" in t42["intent"], "T4.2 intent does not cite the new Decision"

    def test_both_items_carry_the_expected_related_decisions(self) -> None:
        t42, t412 = self._items()
        r42 = t42.get("related_decisions") or []
        r412 = t412.get("related_decisions") or []
        assert DECISION_NUMBER in r42 and DECISION_NUMBER in r412, (r42, r412)
        assert 116 in r42 and 122 in r42, r42
        assert 116 in r412, r412

    def test_no_cited_decision_is_dangling(self) -> None:
        """tier_item related_decisions are unvalidated ints today -- asserted for the two items touched."""
        t42, t412 = self._items()
        cited = set(t42.get("related_decisions") or []) | set(t412.get("related_decisions") or [])
        live = decision_header_numbers(paths=[REPO_ROOT / DECISIONS_PATH])
        dangling = sorted(n for n in cited if n not in live)
        assert not dangling, dangling


class TestGraduatedDecisionsMdGrepRows:
    """CLASS sweep over every graduated grep_count row reading the file this wave edits.

    Not graduable: this passes on origin/main too, so it cannot meet VF-05 differential admission.
    It ships as a standing unit test because a merged registry row is never re-executed, making a
    unit test the only carrier that keeps guarding the class after this PR merges.
    """

    @staticmethod
    def _rows() -> list[dict]:
        registry = yaml.safe_load((REPO_ROOT / REGISTRY_PATH).read_text(encoding="utf-8"))
        return [
            e
            for e in registry["entries"]
            if e["primitive_slot"] == "grep_count" and e["check_spec"].get("path") == DECISIONS_PATH
        ]

    def test_the_class_is_non_empty(self) -> None:
        """A zero-row class would make the sweep below vacuously green."""
        assert self._rows(), f"no graduated grep_count rows read {DECISIONS_PATH}"

    def test_graduated_decisions_md_grep_rows_still_read_their_pinned_counts(self) -> None:
        failures = []
        for row in self._rows():
            spec = row["check_spec"]
            check = GrepCountCheck(
                name=row["check_id"],
                path=str(REPO_ROOT / spec["path"]),
                pattern=spec["pattern"],
                operator=spec["operator"],
                count=spec["count"],
            )
            result = check.run()
            if result.status is not CheckStatus.PASS:
                failures.append((row["check_id"], result.message, result.actual))
        assert not failures, failures
