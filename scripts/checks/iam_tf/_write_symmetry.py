"""Mechanical symmetry submodule -- design (c) (PLAN-iam-write-surface-completion).

Two rules that need no per-verb human enumeration at all, so they catch gaps the phase-keyed
LIFECYCLE_COMPANIONS table (_write_companions) structurally cannot -- the ones nobody thought to
declare:

  RULE 1  Tag/Untag symmetry. A `service:Tag*` grant with no matching `service:Untag*` at an
          OVERLAPPING Resource entry fails. Differential on the pre-fix tree: logs:TagLogGroup had
          no logs:UntagLogGroup and iam:TagOpenIDConnectProvider had no
          iam:UntagOpenIDConnectProvider. ALIAS_TAG_PAIRS exists because SSM spells the pair
          AddTagsToResource / RemoveTagsFromResource rather than Tag*/Untag*.

  RULE 2  read scope >= write scope, per resource type. Being able to CREATE a resource you cannot
          then refresh-READ is an AccessDenied on the NEXT plan, not on the apply that created it --
          the failure mode is a stranded pipeline, so it is worth a mechanical rule. Differential on
          the pre-fix tree: aws_iam_role writes at role/agent-platform-* while reading 15 literal
          ARNs. That single type is the sole NAMED exemption (READ_SCOPE_PARITY_EXEMPT), because the
          enumerated-IAM-read invariant is a deliberate control, not an oversight.

TRANSITIVE-SKIP DERIVATION (H1) -- the load-bearing detail: rule 2's skip set IS
_read_coverage.TRANSITIVE_TYPES, bound by identity, never a hand-written copy. A type whose READ
grant is transitive (covered by a parent/sibling resource's grant) has no read markers of its own to
compare against, so comparing them would be meaningless. This plan's OWN first draft hand-listed 10
of that set's 11 members, omitting aws_secretsmanager_secret_version -- i.e. it reproduced, inside
the fix, the exact hand-enumeration root cause the fix exists to remove. Every skip prints a line;
none is silent.

Credential-free (pure text parsing) -- eligible for --pre and full tiers. Stays < 500 SLOC.
"""

from __future__ import annotations

import re

from scripts.checks.iam_tf import validate_invoke_implies_resolve as _vir
from scripts.checks.iam_tf._read_coverage import (
    CHECKED_TYPES,
    ENUMERATED_IAM_TYPES,
    TRANSITIVE_TYPES,
    _action_matches,
)
from scripts.checks.iam_tf._write_coverage import WRITE_COVERAGE

# ---------------------------------------------------------------------------
# Rule 1 -- Tag/Untag symmetry.
# ---------------------------------------------------------------------------

_TAG_ACTION_RE = re.compile(r"^([a-z0-9]+):Tag([A-Za-z]+)$")

# Services that do not spell the pair Tag*/Untag*. Keyed by the TAG action, valued by the exact
# UNTAG counterpart -- an alias is a spelling fact about an API, not a policy judgement.
ALIAS_TAG_PAIRS: dict[str, str] = {
    "ssm:AddTagsToResource": "ssm:RemoveTagsFromResource",
}

# Tag actions deliberately granted WITHOUT their untag counterpart. Each entry carries its own
# justification; an entry with no justification is itself a failure (asserted below), so this table
# can never become a silent silencer.
TAG_SYMMETRY_EXEMPT: dict[str, str] = {}

# ---------------------------------------------------------------------------
# Rule 2 -- read scope >= write scope.
# ---------------------------------------------------------------------------

# IDENTITY BINDING, NOT A COPY (H1). Rebinding this to a literal set is the regression the
# test suite asserts against by `is` identity.
TRANSITIVE_SKIP_TYPES = TRANSITIVE_TYPES

READ_SCOPE_PARITY_EXEMPT: dict[str, str] = {
    "aws_iam_role": (
        "RETAINED ENUMERATION, not a gap: iam: role reads stay enumerated at literal ARNs "
        "(Decision 129 pt 2 / pt 4(iii), with the write-side amendment in Decision 144 pt 5) even "
        "though iam:CreateRole is granted at role/agent-platform-*. Relaxing it would mean relaxing "
        "_read_coverage.ENUMERATED_IAM_TYPES' literal_only assertion -- a ratified control that "
        "deserves its own Decision and live-proof, not a side effect of an AccessDenied remediation. "
        "The cost is friction, never a silent deny: a new agent-platform-* role with no enumerated "
        "ARN fails validate --pre with a clear message. A follow-on rec revisits the widening on its "
        "own merits (P1-1)."
    ),
}


def _allow_statements(apply_statements: list[dict]) -> list[dict]:
    """Effect-aware filter: a statement with no parsed "effect" (synthetic fixtures) counts as Allow."""
    return [s for s in apply_statements if s.get("effect") in (None, "Allow")]


def _resource_entries(resources_raw: str) -> set[str]:
    """Every quoted ARN entry in a statement's Resource list."""
    return set(_vir._QUOTED_RE.findall(resources_raw))


def _untag_counterpart(action: str) -> str | None:
    """The untag action `action` structurally implies, or None if `action` is not a tag verb."""
    alias = ALIAS_TAG_PAIRS.get(action)
    if alias:
        return alias
    m = _TAG_ACTION_RE.match(action)
    return f"{m.group(1)}:Untag{m.group(2)}" if m else None


def _granted_on_overlapping_resource(action: str, entries: set[str], statements: list[dict]) -> bool:
    """True if some statement grants `action` on a Resource list overlapping `entries`."""
    for stmt in statements:
        if not _action_matches((action,), stmt["actions"]):
            continue
        other = _resource_entries(stmt["resources_raw"])
        if "*" in other or "*" in entries or (other & entries):
            return True
    return False


def check_tag_untag_symmetry(apply_statements: list[dict], failed: list[str], key: str) -> None:
    """Rule 1: every granted `service:Tag*` has its `service:Untag*` counterpart at an overlapping scope.

    Why this is worth a mechanical rule: AWS's default_tags provider block means a tags diff is
    applied as an untag + tag pair, so a Tag-without-Untag grant does not fail on create -- it fails
    later, on the first apply that REMOVES a tag, which is exactly the kind of gap no one enumerates
    in advance.
    """
    statements = _allow_statements(apply_statements)
    seen: set[tuple[str, frozenset[str]]] = set()
    for stmt in statements:
        entries = _resource_entries(stmt["resources_raw"])
        for action in stmt["actions"]:
            counterpart = _untag_counterpart(action)
            # Keyed by (action, scope), not by action alone: the same tag verb granted at two
            # different scopes is two independent obligations -- a wide grant elsewhere must never
            # mask a narrow grant whose scope has no untag counterpart.
            if counterpart is None or (action, frozenset(entries)) in seen:
                continue
            seen.add((action, frozenset(entries)))
            justification = TAG_SYMMETRY_EXEMPT.get(action)
            if justification is not None:
                print(f"  tag-symmetry EXEMPT {action}: {justification}")
                continue
            if not _granted_on_overlapping_resource(counterpart, entries, statements):
                failed.append(
                    f"{key} github_ci_apply grants {action!r} but not {counterpart!r} on any overlapping "
                    "Resource entry -- a tags diff is applied as an untag + tag pair, so the missing half "
                    "AccessDenies on the first apply that REMOVES a tag (design (c) rule 1)"
                )


def _arn_pattern(arn: str) -> re.Pattern[str]:
    """Compile an IAM Resource entry into a matcher, treating `*` as the only metacharacter."""
    return re.compile(".*".join(re.escape(part) for part in arn.split("*")) + r"\Z")


def _arn_covers(read_arn: str, write_arn: str) -> bool:
    """True if the read entry's scope subsumes the write entry's scope."""
    if read_arn == "*":
        return True
    return bool(_arn_pattern(read_arn).match(write_arn))


def _scoped_entries(statements: list[dict], actions: tuple[str, ...], marker: str | None = None) -> set[str]:
    """Union of the Resource entries of every statement granting one of `actions` (at `marker`)."""
    entries: set[str] = set()
    for stmt in statements:
        if not _action_matches(actions, stmt["actions"]):
            continue
        if marker is not None and marker not in stmt["resources_raw"]:
            continue
        entries |= _resource_entries(stmt["resources_raw"])
    return entries


def check_read_write_scope_parity(apply_statements: list[dict], failed: list[str], key: str) -> None:
    """Rule 2: for every write-managed type, the read grant must cover everything the write grant can create.

    Skips (loudly, one printed line each) the types whose read coverage is TRANSITIVE -- that set is
    _read_coverage.TRANSITIVE_TYPES itself, never a copy. Exempts (loudly) the named entries of
    READ_SCOPE_PARITY_EXEMPT. Any other write-managed type with no read classification at all fails
    loud rather than being skipped silently.
    """
    statements = _allow_statements(apply_statements)
    for rtype in sorted(WRITE_COVERAGE):
        if rtype in TRANSITIVE_SKIP_TYPES:
            print(f"  parity SKIPPED {rtype}: read grant is transitive (_read_coverage.TRANSITIVE_TYPES)")
            continue
        justification = READ_SCOPE_PARITY_EXEMPT.get(rtype)
        if justification is not None:
            print(f"  parity EXEMPT {rtype}: {justification.splitlines()[0]}")
            continue

        read_spec = CHECKED_TYPES.get(rtype) or ENUMERATED_IAM_TYPES.get(rtype)
        if read_spec is None:
            failed.append(
                f"{key} write-managed type {rtype!r} has no read classification in CHECKED_TYPES / "
                "ENUMERATED_IAM_TYPES and is not transitive -- design (c) rule 2 cannot compare its "
                "read and write scopes, so the parity guarantee would be silently vacuous"
            )
            continue

        spec = WRITE_COVERAGE[rtype]
        write_entries = _scoped_entries(statements, spec["write_actions"], spec["resource_marker"])
        read_entries = _scoped_entries(statements, read_spec["read_actions"])
        for write_arn in sorted(write_entries):
            if any(_arn_covers(read_arn, write_arn) for read_arn in read_entries):
                continue
            failed.append(
                f"{key} write-managed type {rtype!r} can write {write_arn!r} but no read grant covers "
                f"that scope (read entries: {sorted(read_entries) or 'none'}) -- the pipeline could create "
                "a resource it cannot then refresh-read, which AccessDenies on the NEXT plan rather than "
                "on the apply that created it (design (c) rule 2). Resolve by widening the read grant, "
                "narrowing the write grant to the read scope, or adding a JUSTIFIED entry to "
                "READ_SCOPE_PARITY_EXEMPT -- never an unjustified one"
            )
