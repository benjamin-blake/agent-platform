"""Derived selector over the LIVE scripts.checks.registry sequence (Decision 131 clause 3).

Replaces hand-authored Step literals: ``select_steps`` filters ``registry.pre_sequence()`` /
``registry.full_sequence()`` down to the names a caller declares, returning the REAL Step
objects (with their real ``pre_globs``) in TIER order -- never the requested order. A name
absent from the live sequence raises ``UnknownStepError`` naming the valid options, so a
renamed or removed check surfaces as a test failure instead of a silently-stale selection.

Lives in tests/fixtures/ (exempt from validate_no_cross_test_imports per Decision 131 clause 2,
its names never starting with ``test_``) so both tests/validate/ and
tests/validate/test_driver_seam.py can import it directly.
"""

from __future__ import annotations

from scripts.checks import registry as _registry


class UnknownStepError(ValueError):
    """Raised when a requested check or scaffold name is absent from the live sequence."""


def _live_sequence(sequence: str) -> list[_registry.Step]:
    if sequence == "pre":
        return _registry.pre_sequence()
    if sequence == "full":
        return _registry.full_sequence()
    raise UnknownStepError(f"Unknown sequence {sequence!r}; expected 'pre' or 'full'")


def select_steps(
    *,
    checks: tuple[str, ...] = (),
    scaffolds: str | tuple[str, ...] = "all",
    sequence: str = "pre",
) -> list[_registry.Step]:
    """Return real Step objects from the live ``sequence``, filtered to ``checks`` (kind ==
    "check") plus ``scaffolds`` (kind == "scaffold"; "all" keeps every scaffold step),
    preserving the live sequence's own TIER order regardless of the order names are passed in.

    Raises UnknownStepError, naming the valid options, for any requested check or scaffold name
    absent from the live sequence.
    """
    live = _live_sequence(sequence)
    live_check_names = {step.name for step in live if step.kind == "check"}
    live_scaffold_names = {step.name for step in live if step.kind == "scaffold"}

    unknown_checks = set(checks) - live_check_names
    if unknown_checks:
        raise UnknownStepError(f"Unknown check name(s) {sorted(unknown_checks)}; valid checks: {sorted(live_check_names)}")

    if scaffolds == "all":
        wanted_scaffolds = live_scaffold_names
    else:
        unknown_scaffolds = set(scaffolds) - live_scaffold_names
        if unknown_scaffolds:
            raise UnknownStepError(
                f"Unknown scaffold name(s) {sorted(unknown_scaffolds)}; valid scaffolds: {sorted(live_scaffold_names)}"
            )
        wanted_scaffolds = set(scaffolds)

    wanted_checks = set(checks)
    return [
        step
        for step in live
        if (step.kind == "check" and step.name in wanted_checks) or (step.kind == "scaffold" and step.name in wanted_scaffolds)
    ]
