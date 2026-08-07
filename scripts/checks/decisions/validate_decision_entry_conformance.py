"""Decision-entry authoring-grammar forward conformance check (DAF-03 / Decision 134 cl.3 /
PLAN-daf-authoring-grammar; extended by PLAN-decision-entry-flow-governance / Decision 167 with
the typed metadata envelope, the Significance routing claim, and the envelope/body conflict and
number-match sub-checks).

Enforces docs/contracts/decision-entry.yaml's canonical markers on GENUINELY-NEW decision
entries only -- a decision number absent from the origin/main baseline. Modified, amended, or
promoted historical entries (e.g. this same plan's own DECISIONS_ARCHIVE.md h3->h2 promote of
Decisions 52/53/54) are grandfathered: they carry only a "**Status:** Decided -- April 2026"
line with no separate "**Date:**" marker, and would self-fail this check if the historical band
were retro-enforced. A Decision 149 compacted stub (its body wholly replaced with the fixed
stub_grammar shape, including a literal "**Status:** Superseded" and a "**Superseded by:
Decision N**" pointer) is likewise exempt from the envelope obligation -- a compaction replaces a
body it never authored.

Baseline and current populations are both computed via the SAME shared grammar
(scripts.decisions_md.iter_decision_headings, the '#{2,3}' regex) so a header-level promote
(h3->h2) never manufactures a false "new" entry -- Decisions 52/53/54 are counted as
already-present at origin/main regardless of which heading level either snapshot used. The
origin/main baseline read itself is delegated to scripts.checks.decisions._baseline (Decision
153 fast-tier budget: one shared, memoized git read for both --pre DECISIONS consumers).

Required markers and the significance vocabulary are read from docs/contracts/decision-entry.yaml
at check time (never a hardcoded copy) -- the contract is the single source of truth.

Advisory SKIP (never a failure) when origin/main is unreachable (mirrors the
validate_graduation_completeness precedent): the check cannot resolve new-vs-baseline without
it. The baseline_reader injection seam returns None for exactly this case, so the default
reader's own reachability check and a test's synthetic "unreachable" case share one code path.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from scripts.checks import _common, registry
from scripts.checks.decisions._baseline import BaselineReaderFn
from scripts.checks.decisions._baseline import baseline_decision_numbers as _default_baseline_decision_numbers
from scripts.decisions_md import _DECISION_MARKER_BODY, extract_entry_envelope, extract_superseded_by, iter_decision_headings

_CONTRACT_REL_PATH = "docs/contracts/decision-entry.yaml"
_DECISIONS_REL_PATHS = ("docs/DECISIONS.md", "docs/DECISIONS_ARCHIVE.md")

_BOLD_STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(.+)")
_BOLD_DATE_RE = re.compile(r"\*\*Date:\*\*\s*(.+)")
_NEVER_NUMBERED_DECISION_TEXT = "Never a numbered Decision"


def _current_decision_entries(root: Path) -> dict[int, str]:
    """decision number -> heading-inclusive raw block, from the CURRENT working tree.

    First-wins on a duplicate number across the two files, mirroring
    scripts.decisions_md.parse_decisions_md's dedup rule.
    """
    entries: dict[int, str] = {}
    for rel in _DECISIONS_REL_PATHS:
        path = root / rel
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        headings = list(iter_decision_headings(content))
        for i, m in enumerate(headings):
            n = int(m.group(1))
            if n in entries:
                continue
            end = headings[i + 1].start() if i + 1 < len(headings) else len(content)
            entries[n] = content[m.start() : end]
    return entries


def _load_required_markers(root: Path, failed: list[str]) -> Optional[list[str]]:
    contract_path = root / _CONTRACT_REL_PATH
    if not contract_path.exists():
        failed.append(f"Decision-entry conformance: {_CONTRACT_REL_PATH} not found")
        return None
    try:
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        failed.append(f"Decision-entry conformance: could not parse {_CONTRACT_REL_PATH}: {exc}")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("required_markers"), list):
        failed.append(f"Decision-entry conformance: {_CONTRACT_REL_PATH} has no required_markers list")
        return None
    return [str(m) for m in data["required_markers"]]


def _missing_markers(block: str, required_markers: list[str]) -> list[str]:
    """Return the subset of required_markers absent from block.

    The "Decision" marker tolerates the decorated form (e.g. "**Decision (four invariants):**")
    per decision-entry.yaml's decision_marker_tolerance -- reuses decisions_md's own
    _DECISION_MARKER_BODY pattern so this check never diverges from the shared parser's notion
    of what counts as a Decision marker. Every other required marker uses its exact spelling.
    """
    missing: list[str] = []
    for marker in required_markers:
        pattern = rf"\*\*{_DECISION_MARKER_BODY}:\*\*" if marker == "Decision" else rf"\*\*{re.escape(marker)}:\*\*"
        if not re.search(pattern, block):
            missing.append(marker)
    return missing


def _load_block_separator_form(root: Path) -> Optional[str]:
    """Return the declared block_separator form (e.g. '---'), or None when the contract is
    unreadable or declares no block_separator section.

    A missing block_separator key is a TOLERATED absence, not a failure -- unlike
    required_markers (mandatory), this sub-check is additive (CFG-06 / rec-2991) and must not
    fail every conformance test fixture pre-dating the section's existence.
    """
    contract_path = root / _CONTRACT_REL_PATH
    if not contract_path.exists():
        return None
    try:
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    block_separator = data.get("block_separator")
    if not isinstance(block_separator, dict):
        return None
    form = block_separator.get("form")
    return str(form) if form else None


def _load_envelope_config(root: Path, failed: list[str]) -> Optional[tuple[list[str], dict[str, str]]]:
    """Return (metadata_envelope.required_fields, significance.routing) from the contract, or
    None (with a FAIL appended) when either section is absent or malformed.

    Read fresh at check time (never a hardcoded copy of the token vocabulary), mirroring
    _load_required_markers -- both required_markers and this pair of sections are mandatory
    contract shape, not a tolerated-absence sub-check like block_separator.
    """
    contract_path = root / _CONTRACT_REL_PATH
    if not contract_path.exists():
        failed.append(f"Decision-entry conformance: {_CONTRACT_REL_PATH} not found")
        return None
    try:
        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        failed.append(f"Decision-entry conformance: could not parse {_CONTRACT_REL_PATH}: {exc}")
        return None
    if not isinstance(data, dict):
        failed.append(f"Decision-entry conformance: {_CONTRACT_REL_PATH} has an unexpected top-level shape")
        return None
    envelope_cfg = data.get("metadata_envelope")
    if not isinstance(envelope_cfg, dict) or not isinstance(envelope_cfg.get("required_fields"), list):
        failed.append(f"Decision-entry conformance: {_CONTRACT_REL_PATH} has no metadata_envelope.required_fields list")
        return None
    significance = data.get("significance")
    routing = significance.get("routing") if isinstance(significance, dict) else None
    if not isinstance(routing, dict) or not routing:
        failed.append(f"Decision-entry conformance: {_CONTRACT_REL_PATH} has no significance.routing mapping")
        return None
    return [str(f) for f in envelope_cfg["required_fields"]], {str(k): str(v) for k, v in routing.items()}


def _is_compacted_stub(block: str) -> bool:
    """A Decision 149 compacted stub: '**Status:** Superseded' plus a live '**Superseded by:
    Decision N**' pointer -- the fixed shape compaction.stub_grammar mandates. Exempt from the
    envelope obligation (a compaction replaces a body it never authored)."""
    status_m = _BOLD_STATUS_RE.search(block)
    if not status_m:
        return False
    status = status_m.group(1).strip().split("--")[0].strip()
    return status == "Superseded" and bool(extract_superseded_by(block))


def _envelope_body_conflicts(envelope: dict, block: str) -> list[str]:
    """Field-by-field envelope-vs-bold-marker comparison. Agreement or the bold marker's
    absence both pass; only a genuine value mismatch is a conflict."""
    conflicts: list[str] = []
    status_m = _BOLD_STATUS_RE.search(block)
    if status_m and envelope.get("status") is not None:
        bold_status = status_m.group(1).strip().split("--")[0].strip()
        if str(envelope["status"]).strip() != bold_status:
            conflicts.append(f"status (envelope={envelope['status']!r} vs body={bold_status!r})")
    date_m = _BOLD_DATE_RE.search(block)
    if date_m and envelope.get("decided_date") is not None:
        bold_date = date_m.group(1).strip()
        if str(envelope["decided_date"]).strip() != bold_date:
            conflicts.append(f"decided_date (envelope={envelope['decided_date']!r} vs body={bold_date!r})")
    return conflicts


def _significance_issues(envelope: dict, routing_tokens: dict[str, str]) -> list[str]:
    """Validate the envelope's `significance` claim: present, one of the contract's routing
    tokens, carrying a non-empty one-line justification, and never one of the routing rows whose
    own contract text says the content is "Never a numbered Decision"."""
    significance = envelope.get("significance")
    if not isinstance(significance, dict) or not significance.get("value"):
        return ["significance element is missing (required: value naming a routing token, plus a justification)"]
    value = str(significance["value"])
    justification = str(significance.get("justification") or "").strip()
    issues: list[str] = []
    if value not in routing_tokens:
        issues.append(f"significance.value {value!r} does not name a decision-entry.yaml significance.routing token")
        return issues
    if _NEVER_NUMBERED_DECISION_TEXT in routing_tokens[value]:
        issues.append(
            f"significance.value {value!r} routes to a row whose own contract text reads "
            f"{_NEVER_NUMBERED_DECISION_TEXT!r} -- never a numbered Decision"
        )
    if not justification:
        issues.append("significance.justification is missing or empty")
    return issues


@registry.register("validate_decision_entry_conformance", owner="platform")
def validate_decision_entry_conformance(
    failed: list[str],
    root: Path | None = None,
    baseline_reader: BaselineReaderFn | None = None,
) -> None:
    """Enforce the decision-entry authoring grammar on new-in-diff decision numbers only.

    root / baseline_reader are test/dogfood injection seams (mirrors the vp_replay /
    graduation_completeness precedents) -- default to _common.ROOT and a real
    `git show origin/main:...` reader respectively.
    """
    print("\n=== Decision-entry authoring-grammar conformance (DAF-03) ===")
    root = root if root is not None else _common.ROOT
    baseline_reader = baseline_reader or _default_baseline_decision_numbers

    baseline_numbers = baseline_reader(root)
    if baseline_numbers is None:
        print("  SKIP: origin/main unreachable (advisory locally, authoritative in CI).")
        return

    required_markers = _load_required_markers(root, failed)
    if required_markers is None:
        return

    current_entries = _current_decision_entries(root)
    new_numbers = sorted(set(current_entries) - baseline_numbers)

    if not new_numbers:
        print("  PASS: no genuinely-new decision entries in this diff (origin/main baseline unchanged).")
        return

    envelope_config = _load_envelope_config(root, failed)
    if envelope_config is None:
        return
    envelope_required_fields, routing_tokens = envelope_config

    block_separator_form = _load_block_separator_form(root)

    issues: list[str] = []
    for n in new_numbers:
        block = current_entries[n]
        missing = _missing_markers(block, required_markers)
        if missing:
            issues.append(
                f"  FAIL: Decision {n} is new (absent from the origin/main baseline) but missing marker(s): {missing}"
            )
        if block_separator_form and not block.rstrip().endswith(block_separator_form):
            issues.append(
                f"  FAIL: Decision {n} is new (absent from the origin/main baseline) but its block does not "
                f"end with the required separator {block_separator_form!r} (docs/contracts/decision-entry.yaml "
                "block_separator)."
            )

        if _is_compacted_stub(block):
            continue  # Decision 149 compacted stub -- exempt from the envelope obligation

        envelope = extract_entry_envelope(block)
        if envelope is None:
            issues.append(
                f"  FAIL: Decision {n} is new (absent from the origin/main baseline) but carries no well-formed "
                "metadata envelope (a fenced ```yaml block immediately after the heading, per "
                "docs/contracts/decision-entry.yaml metadata_envelope)."
            )
            continue

        missing_fields = [f for f in envelope_required_fields if f != "significance" and not envelope.get(f)]
        if missing_fields:
            issues.append(f"  FAIL: Decision {n} envelope is missing required field(s): {missing_fields}")

        if "number" in envelope_required_fields and envelope.get("number") is not None and int(envelope["number"]) != n:
            issues.append(
                f"  FAIL: Decision {n} envelope declares number={envelope['number']!r}, which disagrees with its heading."
            )

        if "significance" in envelope_required_fields:
            for sig_issue in _significance_issues(envelope, routing_tokens):
                issues.append(f"  FAIL: Decision {n} {sig_issue}.")

        for conflict in _envelope_body_conflicts(envelope, block):
            issues.append(f"  FAIL: Decision {n} envelope conflicts with its bold-marker twin on {conflict}.")

    if issues:
        for issue in issues:
            print(issue)
        failed.append("Decision-entry conformance")
    else:
        plural = "y" if len(new_numbers) == 1 else "ies"
        print(f"  PASS: {len(new_numbers)} new decision entr{plural} conform to the canonical grammar ({new_numbers}).")
