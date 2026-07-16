"""Candidate-decision supersession marking-convention guard (audit PCD-03).

A state==pending CD whose free-text detail records "fully superseded by CD.NN" is a
marking-convention violation once CD.NN itself reaches state==ratified: the superseding
CD is decision-final, so the superseded CD should have been flipped to state==superseded
in the same edit. Left pending, the CD stays bound to every state-keyed surface (gates
resolution, the ratification guard's R2, ratifiable_cds()) that a superseded CD is exempt
from.

Narrow supersession ("narrowly superseded by CD.NN", CD.11's shape) and self-demotion
("[Amendment ... ]" prose that demotes a CD's own scope without naming a successor CD,
CD.10's shape) are NOT "fully superseded by CD.NN" and MUST NOT trigger this guard --
they are a different, non-full-supersession relationship by construction (the regex only
matches the literal "fully superseded by CD.NN" phrase).

This guard deliberately does NOT flag a dangling "fully superseded by CD.NN" whose CD.NN
does not exist in the roadmap (unknown superseder -> no match -> no fail) -- see
docs/contracts/candidate-decision-ratification.yaml and the owning plan's constraints.
"""

from __future__ import annotations

import re
import sys

from scripts.checks import _common, registry

_FULLY_SUPERSEDED_RE = re.compile(r"fully superseded by (CD\.\d+)")


@registry.register("validate_candidate_decision_supersession", owner="platform")
def validate_candidate_decision_supersession(failed: list[str]) -> None:
    """Enforce the CD marking convention: a pending CD fully superseded by a ratified CD must flip."""
    print("\n=== Candidate decision supersession guard (audit PCD-03) ===")

    roadmap_path = _common.ROOT / "docs" / "ROADMAP-PLATFORM.yaml"
    if not roadmap_path.exists():
        print(f"  FAIL: {roadmap_path.relative_to(_common.ROOT)} not found")
        failed.append("Candidate decision supersession guard")
        return

    root_str = str(_common.ROOT)
    injected = root_str not in sys.path
    if injected:
        sys.path.insert(0, root_str)
    try:
        from scripts.roadmap.platform_roadmap import load  # noqa: PLC0415

        doc = load(roadmap_path)
    except Exception as exc:  # noqa: BLE001
        print(f"  FAIL: could not load roadmap: {exc}")
        failed.append("Candidate decision supersession guard")
        return
    finally:
        if injected and root_str in sys.path:
            sys.path.remove(root_str)

    cd_by_id = {cd.id: cd for cd in doc.candidate_decisions}
    issues: list[str] = []

    for cd in doc.candidate_decisions:
        if cd.state != "pending":
            continue
        m = _FULLY_SUPERSEDED_RE.search(cd.detail)
        if not m:
            continue
        superseder_id = m.group(1)
        superseder = cd_by_id.get(superseder_id)
        if superseder is None:
            continue  # unknown superseder -- deliberately not flagged (see module docstring)
        if superseder.state == "ratified":
            issues.append(
                f"  FAIL: {cd.id} is state=pending but its detail records 'fully superseded by "
                f"{superseder_id}', and {superseder_id} is state=ratified -- flip {cd.id} to "
                "state=superseded in this same edit (the superseding decision is decision-final)."
            )

    if issues:
        for issue in issues:
            print(issue)
        failed.append("Candidate decision supersession guard")
    else:
        print("  PASS: no pending CD is fully superseded by an already-ratified CD.")
