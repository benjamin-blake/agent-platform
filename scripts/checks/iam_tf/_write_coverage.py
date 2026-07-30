"""Write-coverage submodule (Decision 128 decomposition + Decision 144 / T2.48 c5, DEP-01).

The enumerated-model recurrence (rec-2703 / rec-2757) was a resource whose refresh-READ was covered
but whose WRITE verb was missing from github_ci_apply's inline policy, so a real apply AccessDenied.
The read-coverage gate (_read_coverage) closes the read half; this submodule closes the write half:
for every resource TYPE the github_ci_apply pipeline is expected to WRITE (create / modify / destroy
at apply time), assert the apply role's inline policy grants the required write verbs on a matching
resource prefix. An apply-role-written type with no covering write grant FAILS LOUD, mirroring the
read-coverage loud-fail (Decision 55: fail loud, never silently pass).

rec-2831 anti-recurrence (T2.48 c1, PLAN-t248-passrole-liveproof): a SECOND, verb-pair recurrence
class -- lambda:CreateFunction was write-covered (above) but AWS also REQUIRES iam:PassRole on the
Lambda execution role for CreateFunction to succeed, and the enumerated model never paired the two.
check_passrole_implies_coverage() closes this: if CreateFunction is granted, both the identity
policy AND the boundary DataPlaneAllow ceiling must grant iam:PassRole scoped to
role/agent-platform-*. The identity-side check uses the apply_statements the facade already passes;
the boundary-side check re-reads github_ci_apply.tf itself, because the orchestrator facade
(validate_ci_refresh_read_coverage.py) passes only the identity apply_statements, never the boundary
policy. That re-read now goes through _read_coverage._parse_boundary_dataplane_statement, which is
built on the SHARED policy locator and therefore follows the rec-2793 hoisted-local indirection --
the previous forward-search-from-the-resource-match implementation returned None the moment the
boundary document was hoisted into a local to carry its own size precondition.

Credential-free (pure text parsing) -- eligible for --pre and full tiers. Stays < 500 SLOC.
"""

from __future__ import annotations

from scripts.checks import _common

# _parse_boundary_dataplane_statement / _parse_managed_policy_statements MOVED to _read_coverage so
# they can be expressed on the shared, hoist-resolving policy locator (see their docstrings there).
# Imported -- and thus still importable FROM this module -- so existing importers keep working.
from scripts.checks.iam_tf._read_coverage import (
    _BOOTSTRAP_TF_REL,
    _action_matches,
    _parse_boundary_dataplane_statement,  # noqa: F401 -- re-exported for existing importers
    _parse_managed_policy_statements,  # noqa: F401 -- re-exported for existing importers
)

# rec-2831 / Decision 143 worst-verb scoping: the identity PassRole grant must target exactly this
# execution-role prefix, never role/* or a specific privileged role by name.
_PASSROLE_ACTION = "iam:PassRole"
_PASSROLE_RESOURCE_MARKER = "role/agent-platform-*"

# rec-2842 (DEP-02, T2.48 c2): the create-companion recurrence-killer. AWS's default_tags provider
# block (terraform/personal/main.tf) forces a TagRole call on EVERY taggable resource's create, so
# iam:CreateRole@role/agent-platform-* structurally REQUIRES these companion verbs at the SAME
# prefix (UpdateRole folded in per Fable's predicted-next-gap consult, same risk class as Tag/Untag).
_CREATE_ROLE_ACTION = "iam:CreateRole"
_CREATE_ROLE_RESOURCE_MARKER = "role/agent-platform-*"
_CREATE_COMPANION_ACTIONS = ("iam:TagRole", "iam:UntagRole", "iam:UpdateRole")

# check_identity_iam_actions_subset_of_boundary (defense-in-depth, generalizes the PassRole-specific
# boundary check above): scoped to iam: actions ONLY -- iam is the sole ACTION-ENUMERATED service in
# the boundary's DataPlaneAllow ceiling; s3:*/lambda:*/logs:*/etc. are already service-wide wildcards
# there, so a subset test over those services would be vacuous (plan-critique implementer guidance).
_IAM_ACTION_PREFIX = "iam:"
# Whole-file substring check (mirrors the plan's own VP step 2 rigor level -- a simple presence
# check, not a statement-scoped parse): the PassedToService=lambda.amazonaws.com condition text
# must be present somewhere in the bootstrap HCL, or the identity grant is an unconditioned
# over-grant (any service, any pass).
_PASSROLE_CONDITION_MARKERS = ("iam:PassedToService", "lambda.amazonaws.com")
# (_BOUNDARY_RESOURCE_RE / _STATEMENT_ARRAY_RE removed with the boundary parser they served -- the
# forward-search-from-resource-match approach is what the hoist breaks; the replacement resolves the
# policy-local indirection instead. See _read_coverage._locate_policy_statement_array.)

# ---------------------------------------------------------------------------
# WRITE-coverage map: managed resource type -> the write actions github_ci_apply's inline policy MUST
# grant + a marker substring the granting statement's Resource list must contain (the broadened
# agent-platform-* / ducklake-* prefix from the DEP-01 write-surface inversion). A required action is
# covered when SOME apply statement grants it on a Resource containing the marker.
# ---------------------------------------------------------------------------

WRITE_COVERAGE: dict[str, dict] = {
    "aws_lambda_function": {
        "write_actions": ("lambda:CreateFunction", "lambda:UpdateFunctionConfiguration"),
        "resource_marker": "function:agent-platform-*",
    },
    "aws_cloudwatch_log_group": {
        "write_actions": ("logs:CreateLogGroup", "logs:PutRetentionPolicy"),
        "resource_marker": "log-group:/aws/lambda/agent-platform-*",
    },
    "aws_cloudwatch_metric_alarm": {
        "write_actions": ("cloudwatch:PutMetricAlarm",),
        "resource_marker": "alarm:",
    },
    "aws_cloudwatch_event_rule": {
        "write_actions": ("events:PutRule",),
        "resource_marker": "rule/agent-platform-*",
    },
    "aws_iam_role": {
        # Role CREATE routes to gated-apply (guard), but the apply role still needs the VERB to execute
        # the approved create; IAMRoleCreateBounded grants iam:CreateRole on role/agent-platform-* under
        # the boundary-propagation condition (DEP-02 / Decision 144).
        "write_actions": ("iam:CreateRole",),
        "resource_marker": "role/agent-platform-*",
    },
}

# The resource TYPES the github_ci_apply pipeline writes at apply time. Every entry MUST have a
# WRITE_COVERAGE mapping (asserted below) -- an apply-role-written type present in terraform/personal
# with no write-coverage entry AccessDenies at a real apply (rec-2703/rec-2757 recurrence).
APPLY_WRITTEN_TYPES: frozenset[str] = frozenset(WRITE_COVERAGE)


def _write_grant_present(apply_statements: list[dict], spec: dict) -> bool:
    """True if each required write action is granted by some apply statement on a matching Resource."""
    marker = spec["resource_marker"]
    for action in spec["write_actions"]:
        covered = False
        for stmt in apply_statements:
            if _action_matches((action,), stmt["actions"]) and marker in stmt["resources_raw"]:
                covered = True
                break
        if not covered:
            return False
    return True


def _create_function_granted(apply_statements: list[dict]) -> bool:
    """True if some apply statement grants lambda:CreateFunction (the PassRole trigger condition)."""
    return any(_action_matches(("lambda:CreateFunction",), stmt["actions"]) for stmt in apply_statements)


def _passrole_present(statements: list[dict]) -> bool:
    """True if some statement grants iam:PassRole on a Resource matching the agent-platform-* prefix."""
    return any(
        _action_matches((_PASSROLE_ACTION,), stmt["actions"]) and _PASSROLE_RESOURCE_MARKER in stmt["resources_raw"]
        for stmt in statements
    )


def check_passrole_implies_coverage(apply_statements: list[dict], failed: list[str], key: str) -> None:
    """rec-2831 anti-recurrence (T2.48 c1): CreateFunction-implies-PassRole.

    AWS requires iam:PassRole on a Lambda's execution role for lambda:CreateFunction to succeed. If
    github_ci_apply grants CreateFunction, assert:
      1. The identity policy (apply_statements, as passed by the facade) grants iam:PassRole scoped
         to role/agent-platform-*.
      2. The boundary DataPlaneAllow ceiling (re-read + parsed from github_ci_apply.tf directly --
         see _parse_boundary_dataplane_statement) ALSO grants iam:PassRole -- a grant absent from the
         boundary ceiling is silently denied by the identity/boundary intersection.
      3. The PassedToService=lambda.amazonaws.com condition text is present in the bootstrap HCL
         (Decision 143 worst-verb scoping) -- an unconditioned PassRole over-grants.

    A CreateFunction grant with no covering PassRole (either layer, or no condition) FAILS LOUD --
    this is the exact rec-2831 recurrence (a guard-PASS auto-apply that then AccessDenies at
    CreateFunction) the check exists to prevent from ever silently recurring.
    """
    if not _create_function_granted(apply_statements):
        return  # CreateFunction isn't granted -- PassRole isn't a requirement here.

    if not _passrole_present(apply_statements):
        failed.append(
            f"{key} github_ci_apply grants lambda:CreateFunction but its identity policy has no "
            f"iam:PassRole grant on a Resource matching {_PASSROLE_RESOURCE_MARKER!r} -- AWS requires "
            "PassRole on the Lambda execution role for CreateFunction to succeed (rec-2831 recurrence)"
        )

    bootstrap_path = _common.ROOT / _BOOTSTRAP_TF_REL
    try:
        bootstrap_text = bootstrap_path.read_text(encoding="utf-8")
    except OSError as exc:
        failed.append(f"{key} cannot re-read {bootstrap_path} for the boundary PassRole check: {exc}")
        return

    boundary_stmt = _parse_boundary_dataplane_statement(bootstrap_text)
    if boundary_stmt is None:
        failed.append(
            f"{key} could not locate the github_ci_apply_boundary DataPlaneAllow statement in "
            f"{bootstrap_path.name} -- has the boundary HCL shape changed?"
        )
    elif not _action_matches((_PASSROLE_ACTION,), boundary_stmt["actions"]):
        failed.append(
            f"{key} github_ci_apply grants lambda:CreateFunction and iam:PassRole is present in the "
            "identity policy, but the github_ci_apply_boundary DataPlaneAllow ceiling does not grant "
            "iam:PassRole -- a grant absent from the boundary ceiling is silently denied by the "
            "identity/boundary intersection (rec-2831 recurrence)"
        )

    if not all(marker in bootstrap_text for marker in _PASSROLE_CONDITION_MARKERS):
        failed.append(
            f"{key} github_ci_apply's iam:PassRole grant is missing the iam:PassedToService="
            "lambda.amazonaws.com condition (Decision 143 worst-verb scoping) -- an unconditioned "
            "PassRole over-grants (any service, any pass)"
        )


def _create_role_granted_on_prefix(apply_statements: list[dict]) -> bool:
    """True if some apply statement grants iam:CreateRole on a Resource matching the agent-platform-* prefix."""
    return any(
        _action_matches((_CREATE_ROLE_ACTION,), stmt["actions"]) and _CREATE_ROLE_RESOURCE_MARKER in stmt["resources_raw"]
        for stmt in apply_statements
    )


def check_create_companion_scope_coverage(apply_statements: list[dict], failed: list[str], key: str) -> None:
    """rec-2842 anti-recurrence (DEP-02, T2.48 c2): CreateRole@prefix-implies-companions@SAME-prefix.

    This is the RECURRENCE-KILLER for rec-2842 (run 30126122217): AWS's default_tags provider block
    forces a TagRole call on EVERY taggable resource's create, so if github_ci_apply grants
    iam:CreateRole on a Resource matching role/agent-platform-*, it structurally requires
    iam:TagRole/iam:UntagRole/iam:UpdateRole to ALSO be granted on a Resource covering that SAME
    prefix -- not merely present somewhere in the policy. rec-2842's actual bug was exactly this: the
    Resource for iam:TagRole/iam:UntagRole was narrower (the two enumerated branch/pr roles) than
    iam:CreateRole's role/agent-platform-* prefix, so the two verbs' action-presence looked fine but
    their resource scopes diverged -- a RESOURCE-SCOPE mismatch, not an action-absence gap (that
    sibling class is check_identity_iam_actions_subset_of_boundary below). A companion verb missing
    or narrower than the CreateRole prefix FAILS LOUD.
    """
    if not _create_role_granted_on_prefix(apply_statements):
        return  # CreateRole isn't prefix-granted -- the companion-scope requirement doesn't apply.

    for action in _CREATE_COMPANION_ACTIONS:
        covered = any(
            _action_matches((action,), stmt["actions"]) and _CREATE_ROLE_RESOURCE_MARKER in stmt["resources_raw"]
            for stmt in apply_statements
        )
        if not covered:
            failed.append(
                f"{key} github_ci_apply grants iam:CreateRole on a Resource matching "
                f"{_CREATE_ROLE_RESOURCE_MARKER!r} but {action!r} is missing, or granted only on a "
                "narrower Resource -- AWS's default_tags provider block forces a tag-on-create call "
                "on every new role, so CreateRole@prefix structurally requires the companion "
                "metadata verbs at the SAME prefix (rec-2842 recurrence)"
            )


def _identity_allow_iam_actions(apply_statements: list[dict]) -> set[str]:
    """Every distinct iam: action GRANTED (Effect=Allow) somewhere in the identity policy.

    Effect-aware: a statement with no parsed "effect" (older callers / synthetic fixtures that never
    set the key) is treated as Allow, matching every pre-existing apply_statements fixture in this
    test module (they omit Effect entirely, and none of them is a Deny statement).
    """
    actions: set[str] = set()
    for stmt in apply_statements:
        if stmt.get("effect") not in (None, "Allow"):
            continue
        for action in stmt["actions"]:
            if action.startswith(_IAM_ACTION_PREFIX):
                actions.add(action)
    return actions


def check_identity_iam_actions_subset_of_boundary(apply_statements: list[dict], failed: list[str], key: str) -> None:
    """Defense-in-depth (DEP-02 plan): every identity-policy iam: Allow action must also be granted by
    the boundary DataPlaneAllow ceiling, generalizing the rec-2831 PassRole-specific boundary check
    (check_passrole_implies_coverage) to the whole iam: action family so the single enumerated IAM
    list (Decision 144) can never split into silent drift between the two layers.

    Scoped to iam: actions ONLY (plan-critique implementer guidance): iam is the sole
    ACTION-ENUMERATED service in DataPlaneAllow -- s3:*/lambda:*/logs:*/etc. are already service-wide
    wildcards there, so a subset test over those services would be vacuous. "The boundary covers
    action a" is implemented with the boundary's action list as the PATTERNS
    (_action_matches(tuple(boundary_actions), [a])), so a future iam:* in the ceiling is honored --
    not literal string-equality membership.

    Does NOT catch the rec-2842 recurrence itself (a RESOURCE-SCOPE mismatch: iam:TagRole IS present
    in both layers in that bug, see check_create_companion_scope_coverage above) -- this check closes
    the sibling class: an iam action present in the identity policy but entirely ABSENT from the
    boundary ceiling (the rec-2831/PassRole class, generalized beyond PassRole so the single list can
    never split into drift). Effect-aware: a Deny-only identity iam action is never flagged -- it
    grants nothing, so it has no boundary-ceiling obligation.
    """
    identity_actions = _identity_allow_iam_actions(apply_statements)
    if not identity_actions:
        return

    bootstrap_path = _common.ROOT / _BOOTSTRAP_TF_REL
    try:
        bootstrap_text = bootstrap_path.read_text(encoding="utf-8")
    except OSError as exc:
        failed.append(f"{key} cannot re-read {bootstrap_path} for the identity/boundary subset check: {exc}")
        return

    boundary_stmt = _parse_boundary_dataplane_statement(bootstrap_text)
    if boundary_stmt is None:
        failed.append(
            f"{key} could not locate the github_ci_apply_boundary DataPlaneAllow statement in "
            f"{bootstrap_path.name} -- has the boundary HCL shape changed?"
        )
        return

    boundary_actions = tuple(boundary_stmt["actions"])
    for action in sorted(identity_actions):
        if not _action_matches(boundary_actions, [action]):
            failed.append(
                f"{key} identity policy grants {action!r} (Effect=Allow) but the "
                "github_ci_apply_boundary DataPlaneAllow ceiling does not grant it (or a covering "
                "pattern) -- a grant absent from the boundary ceiling is silently denied by the "
                "identity/boundary intersection"
            )


def check_write_coverage(
    apply_statements: list[dict], resources: list[tuple[str, str, str]], failed: list[str], key: str
) -> int:
    """Assert github_ci_apply's inline policy write-covers every apply-role-written managed type (c5).

    Two loud-fail directions (mirroring read-coverage):
      1. Every WRITE_COVERAGE type's required write verbs are present in the apply policy on the
         broadened prefix. A removed / narrowed write grant fails the PR (DEP-01 write-surface gap).
      2. A terraform/personal resource of an apply-role-written type with NO WRITE_COVERAGE entry
         fails loud -- a new write-managed resource class must declare its write grant.

    Also runs three verb-pair/verb-family anti-recurrence checks, each closing a DIFFERENT drift class:
      - check_passrole_implies_coverage() (rec-2831, T2.48 c1): CreateFunction-implies-PassRole.
      - check_create_companion_scope_coverage() (rec-2842, T2.48 c2, DEP-02): CreateRole@prefix
        implies its companion verbs (TagRole/UntagRole/UpdateRole) are granted on that SAME prefix --
        a RESOURCE-SCOPE mismatch class (the exact rec-2842 recurrence).
      - check_identity_iam_actions_subset_of_boundary() (DEP-02 plan, defense-in-depth): every
        identity-policy Allow iam: action must also be granted by the boundary DataPlaneAllow
        ceiling -- an action-absent-from-the-ceiling class, generalizing the PassRole-specific
        boundary check above.

    Returns the count of write-managed types asserted (for the PASS summary). Appends to `failed`.
    """
    for rtype, spec in WRITE_COVERAGE.items():
        if not _write_grant_present(apply_statements, spec):
            failed.append(
                f"{key} apply-role write-managed type {rtype!r} has no covering write grant in "
                f"github_ci_apply.tf (expected {spec['write_actions']} on a Resource matching "
                f"{spec['resource_marker']!r}) -- DEP-01 write-surface gap (rec-2703/rec-2757)"
            )

    for rtype, rname, fname in resources:
        if rtype in APPLY_WRITTEN_TYPES and rtype not in WRITE_COVERAGE:
            failed.append(
                f"{key} apply-role-written type {rtype!r} (resource {rname} in {fname}) has no "
                "WRITE_COVERAGE entry -- add one to scripts/checks/iam_tf/_write_coverage.py"
            )

    check_passrole_implies_coverage(apply_statements, failed, key)
    check_create_companion_scope_coverage(apply_statements, failed, key)
    check_identity_iam_actions_subset_of_boundary(apply_statements, failed, key)

    return len(WRITE_COVERAGE)
