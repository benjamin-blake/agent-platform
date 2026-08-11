"""Decision-corpus currency invariant guard (PLAN-decision-corpus-currency, rec-3055/rec-3056).

Enforces the five safety invariants that make docs/decisions-index.json's typed `currency`
projection (scripts.decisions_index / scripts.decisions_md.derive_currency) a load-bearing
consumer contract rather than a restatement of status prose:

  I1 every LIVE entry whose bold '**Status:**' marker resolves to 'Superseded'
     (scripts.decisions_md.status_is_superseded -- the single shared status-marker derivation,
     never a substring/findall match, which also matches live entries that merely QUOTE the
     marker, e.g. Decisions 149/160) derives 'superseded_compacted' in the committed index.
  I2 currency is present on every live:true row and absent from every live:false row.
  I3 every emitted currency value is one of docs/contracts/decision-entry.yaml's declared
     currency.values.
  I4 no live entry's bold status marker begins with 'Reversed' or 'Deferred' unless its number
     is listed in the grandfather hook below (empty at install -- the live census is zero such
     entries). Growing this hook is a reviewed code edit, never a config edit (Decision 165
     clause 4's RETRO_SCAN_GRANDFATHER precedent).
  I5 .claude/skills/decision-scout/SKILL.md names 'superseded_compacted' as the sole demoting
     token, states the never-filtered/never-severity-reduced rule for the other tokens, AND no
     longer carries the retired status-prose fallback ("whose status is active") -- presence AND
     absence, so the prose branch cannot be silently reintroduced.

root is a test/dogfood injection seam (mirrors validate_decision_entry_conformance's own root
parameter) -- defaults to _common.ROOT. Reads currency values from the COMMITTED
docs/decisions-index.json, never scripts.decisions_index.build_index() (which takes no arguments
and hardcodes its own paths, so it cannot be pointed at a fixture tree); status markers from
scripts.decisions_md.parse_decisions_md(paths=[...]); live scoping from
scripts.decisions_md.decision_header_numbers(paths=[...]); the vocabulary from
docs/contracts/decision-entry.yaml; and the consumer clauses from the skill file text.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.checks import _common, registry
from scripts.decisions_md import bold_status, decision_header_numbers, parse_decisions_md, status_is_superseded

_CONTRACT_REL_PATH = "docs/contracts/decision-entry.yaml"
_INDEX_REL_PATH = "docs/decisions-index.json"
_LIVE_REL_PATH = "docs/DECISIONS.md"
_ARCHIVE_REL_PATH = "docs/DECISIONS_ARCHIVE.md"
_SKILL_REL_PATH = ".claude/skills/decision-scout/SKILL.md"

_GUARD_NAME = "Decision currency invariants"

# Reversed/Deferred live entries exempted from I4. Empty at install (today's live census is zero
# such entries) -- growing this hook is a reviewed code edit, never a config edit (Decision 165
# clause 4).
_REVERSED_DEFERRED_GRANDFATHER: frozenset[int] = frozenset()

_CONSUMER_CONTRACT_TOKEN = "superseded_compacted"
_NEVER_FILTERED_CLAUSE = "NEVER filtered and NEVER severity-reduced"
_RETIRED_STATUS_PROSE = "whose status is active"


def _load_index_decisions(root: Path, failed: list[str]) -> list[dict] | None:
    index_path = root / _INDEX_REL_PATH
    if not index_path.exists():
        failed.append(f"{_GUARD_NAME}: {_INDEX_REL_PATH} not found")
        return None
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failed.append(f"{_GUARD_NAME}: could not parse {_INDEX_REL_PATH}: {exc}")
        return None
    decisions = data.get("decisions") if isinstance(data, dict) else None
    if not isinstance(decisions, list):
        failed.append(f"{_GUARD_NAME}: {_INDEX_REL_PATH} has no 'decisions' list")
        return None
    return decisions


def _load_currency_vocabulary(root: Path, failed: list[str]) -> list[str] | None:
    contract_path = root / _CONTRACT_REL_PATH
    if not contract_path.exists():
        failed.append(f"{_GUARD_NAME}: {_CONTRACT_REL_PATH} not found")
        return None
    try:
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        failed.append(f"{_GUARD_NAME}: could not parse {_CONTRACT_REL_PATH}: {exc}")
        return None
    currency = data.get("currency") if isinstance(data, dict) else None
    values = currency.get("values") if isinstance(currency, dict) else None
    if not isinstance(values, list) or not values:
        failed.append(f"{_GUARD_NAME}: {_CONTRACT_REL_PATH} has no currency.values list")
        return None
    return [str(v) for v in values]


def _check_i1(decisions: list[dict], blocks: dict[int, str], live_numbers: set[int], failed: list[str]) -> None:
    currency_by_number = {e.get("number"): e.get("currency") for e in decisions}
    bad = sorted(
        n
        for n in live_numbers
        if status_is_superseded(blocks.get(n, "")) and currency_by_number.get(n) != "superseded_compacted"
    )
    if bad:
        failed.append(
            f"{_GUARD_NAME} I1: live decision(s) {bad} carry a '**Status:** Superseded' marker "
            "but did not derive currency 'superseded_compacted' -- a malformed compaction."
        )
    else:
        print("  I1 PASS: every live '**Status:** Superseded' entry derives 'superseded_compacted'.")


def _check_i2(decisions: list[dict], failed: list[str]) -> None:
    bad = sorted(e.get("number", 0) for e in decisions if bool(e.get("live")) != ("currency" in e))
    if bad:
        failed.append(f"{_GUARD_NAME} I2: currency key present iff live is violated for decision(s) {bad}.")
    else:
        print("  I2 PASS: currency present on every live row, absent from every archive row.")


def _check_i3(decisions: list[dict], vocabulary: list[str], failed: list[str]) -> None:
    bad = {e.get("number"): e.get("currency") for e in decisions if e.get("live") and e.get("currency") not in vocabulary}
    if bad:
        failed.append(f"{_GUARD_NAME} I3: currency value(s) outside the contract vocabulary {vocabulary}: {bad}")
    else:
        print("  I3 PASS: every emitted currency value is in the contract vocabulary.")


def _check_i4(blocks: dict[int, str], live_numbers: set[int], failed: list[str]) -> None:
    bad = sorted(
        n
        for n in live_numbers
        if bold_status(blocks.get(n, "")).startswith(("Reversed", "Deferred")) and n not in _REVERSED_DEFERRED_GRANDFATHER
    )
    if bad:
        failed.append(
            f"{_GUARD_NAME} I4: live decision(s) {bad} carry a Reversed/Deferred status marker outside "
            "the empty-at-install grandfather hook (_REVERSED_DEFERRED_GRANDFATHER)."
        )
    else:
        print("  I4 PASS: no live Reversed/Deferred entry outside the grandfather hook.")


def _check_i5(root: Path, failed: list[str]) -> None:
    skill_path = root / _SKILL_REL_PATH
    if not skill_path.exists():
        failed.append(f"{_GUARD_NAME} I5: {_SKILL_REL_PATH} not found")
        return
    text = skill_path.read_text(encoding="utf-8")
    issues: list[str] = []
    if _CONSUMER_CONTRACT_TOKEN not in text:
        issues.append(f"missing {_CONSUMER_CONTRACT_TOKEN!r}")
    if _NEVER_FILTERED_CLAUSE not in text:
        issues.append(f"missing {_NEVER_FILTERED_CLAUSE!r}")
    if _RETIRED_STATUS_PROSE in text:
        issues.append(f"still carries the retired {_RETIRED_STATUS_PROSE!r} fallback")
    if issues:
        failed.append(f"{_GUARD_NAME} I5: {_SKILL_REL_PATH} consumer-contract violation(s): {issues}")
    else:
        print("  I5 PASS: decision-scout consumer-contract clauses present, status-prose fallback absent.")


@registry.register("validate_decision_currency", owner="platform")
def validate_decision_currency(failed: list[str], root: Path | None = None) -> None:
    """Enforce the five decision-corpus currency invariants (I1-I5, see module docstring)."""
    print("\n=== Decision currency invariants ===")
    root = root if root is not None else _common.ROOT

    decisions = _load_index_decisions(root, failed)
    if decisions is None:
        return
    vocabulary = _load_currency_vocabulary(root, failed)
    if vocabulary is None:
        return

    rows = parse_decisions_md(paths=[root / _LIVE_REL_PATH, root / _ARCHIVE_REL_PATH])
    blocks = {row["decision_id"]: row["raw_block"] for row in rows}
    live_numbers = decision_header_numbers(paths=[root / _LIVE_REL_PATH])

    before = len(failed)
    _check_i1(decisions, blocks, live_numbers, failed)
    _check_i2(decisions, failed)
    _check_i3(decisions, vocabulary, failed)
    _check_i4(blocks, live_numbers, failed)
    _check_i5(root, failed)

    if len(failed) == before:
        print(f"  PASS: all five currency invariants hold ({len(live_numbers)} live entries).")
