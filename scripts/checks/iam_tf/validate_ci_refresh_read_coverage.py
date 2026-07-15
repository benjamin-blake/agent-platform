from __future__ import annotations

import re
from pathlib import Path

from scripts.checks import _common, registry
from scripts.checks.iam_tf import validate_invoke_implies_resolve as _vir

# ---------------------------------------------------------------------------
# Coverage map (rec-2702 anti-recurrence, PLAN-ci-apply-grant-coupling).
#
# Every managed terraform/personal resource TYPE must be classified into exactly one of:
#   (i)   CHECKED_TYPES     -- needs an independent refresh-read grant. "read_actions" names the
#         marker action(s) that grant covering it must contain; "name_attrs" (if not None) names
#         the HCL attribute(s) whose resolved value must be matched by a literal ARN, an
#         agent-platform-* (or other) prefix, OR a bare/interpolated Terraform resource reference
#         in the Resource list of a statement granting one of those actions. A None name_attrs
#         means the type is covered purely by a Resource:"*" grant (no per-instance name to check).
#   (ii)  ENUMERATED_IAM_TYPES -- iam: role reads. MUST be a literal enumerated ARN (Decision
#         35/98) -- a wildcard/prefix match never counts, unlike CHECKED_TYPES.
#   (iii) TRANSITIVE_TYPES  -- covered by a parent/sibling resource's own grant (e.g.
#         aws_lambda_permission via the function's lambda:Get* grant, aws_iam_role_policy via the
#         owning role's iam: read). No independent assertion.
#   (iv)  NON_AWS_TYPES / NO_GRANT_TYPES -- not AWS-IAM-gated at all (a third-party provider
#         resource, or a resource with no AWS refresh-read API call).
#
# A resource type present in terraform/personal/*.tf that appears in NONE of these sets fails
# loud ("unmapped resource type") -- see validate_ci_refresh_read_coverage() below.
# ---------------------------------------------------------------------------

CHECKED_TYPES: dict[str, dict] = {
    "aws_lambda_function": {"read_actions": ("lambda:Get*", "lambda:List*"), "name_attrs": ("function_name",)},
    "aws_lambda_layer_version": {"read_actions": ("lambda:Get*", "lambda:List*"), "name_attrs": ("layer_name",)},
    "aws_cloudwatch_event_rule": {"read_actions": ("events:Describe*", "events:List*"), "name_attrs": ("name",)},
    "aws_secretsmanager_secret": {
        "read_actions": ("secretsmanager:Describe*", "secretsmanager:Get*"),
        "name_attrs": ("name",),
    },
    "data:aws_secretsmanager_secret_version": {
        "read_actions": ("secretsmanager:Describe*", "secretsmanager:Get*"),
        "name_attrs": ("secret_id",),
    },
    "aws_sns_topic": {"read_actions": ("sns:Get*", "sns:List*"), "name_attrs": ("name",)},
    "aws_dynamodb_table": {"read_actions": ("dynamodb:DescribeTable",), "name_attrs": ("name",)},
    "aws_glue_catalog_database": {"read_actions": ("glue:GetDatabase",), "name_attrs": ("name",)},
    "aws_ssm_parameter": {"read_actions": ("ssm:Get*", "ssm:Describe*", "ssm:List*"), "name_attrs": ("name",)},
    "aws_iam_openid_connect_provider": {"read_actions": ("iam:GetOpenIDConnectProvider",), "name_attrs": ("url",)},
    "aws_s3_bucket": {"read_actions": ("s3:GetBucketLocation",), "name_attrs": ("bucket",)},
    # Resource:"*"-only types -- coverage does not depend on a per-instance name.
    "aws_cloudwatch_log_group": {"read_actions": ("logs:Describe*", "logs:List*"), "name_attrs": None},
    "aws_cloudwatch_metric_alarm": {"read_actions": ("cloudwatch:Describe*", "cloudwatch:List*"), "name_attrs": None},
    "aws_sns_topic_subscription": {"read_actions": ("sns:GetSubscriptionAttributes",), "name_attrs": None},
    "aws_athena_workgroup": {"read_actions": ("athena:GetWorkGroup",), "name_attrs": None},
}

ENUMERATED_IAM_TYPES: dict[str, dict] = {
    "aws_iam_role": {"read_actions": ("iam:GetRole",), "name_attrs": ("name",)},
}

# Covered transitively via a parent/sibling resource's own grant -- no independent assertion.
TRANSITIVE_TYPES = {
    "aws_lambda_permission",  # lambda:GetPolicy is a lambda:Get* action on the same function ARN
    "aws_cloudwatch_event_target",  # events:List* on the same rule ARN
    "aws_lambda_function_url",  # lambda:Get* on the same function ARN
    "aws_iam_role_policy",  # the owning role's iam:GetRolePolicy/ListRolePolicies grant
    "aws_secretsmanager_secret_version",  # the same secret's Describe*/Get* grant
    "aws_s3_bucket_versioning",
    "aws_s3_bucket_server_side_encryption_configuration",
    "aws_s3_bucket_public_access_block",
    "aws_s3_bucket_policy",
    "aws_s3_bucket_notification",
    "aws_s3_bucket_lifecycle_configuration",
}

# Third-party (non-AWS) provider resources -- not IAM-gated at all (Neon auth is an API key secret).
NON_AWS_TYPES = {"neon_project", "neon_role", "neon_database"}

# AWS-adjacent resources with no refresh-read AWS API call to gate (local-exec only).
NO_GRANT_TYPES = {"null_resource"}

_PERSONAL_DIR_REL = Path("terraform") / "personal"
_BOOTSTRAP_TF_REL = Path("terraform") / "bootstrap" / "github_ci_apply.tf"

ROLE_APPLY = "apply"
ROLE_PLAN = "plan"
ROLE_DRIFT = "drift"
_PLAN_ROLE_POLICY_NAME = "github_ci_plan"
_DRIFT_ROLE_POLICY_NAME = "github_ci_drift"

# ---------------------------------------------------------------------------
# Bootstrap (jsonencode, capitalized-key) statement parsing.
#
# terraform/bootstrap/github_ci_apply.tf's inline policy is `policy = jsonencode({ Statement = [
# {Sid=..., Effect=..., Action=[...] or "...", Resource=[...] or "..."}, ... ] })` -- a different
# textual shape from oidc.tf's native `data "aws_iam_policy_document"` `statement {}` blocks, so it
# needs its own (small) parser. Reuses _vir._extract_block (generic brace-depth matcher) and
# _vir._QUOTED_RE for the leaf-level primitives.
# ---------------------------------------------------------------------------

_SID_CAP_RE = re.compile(r'Sid\s*=\s*"([^"]*)"')


def _extract_bracket_block(text: str, open_idx: int) -> str:
    """Return the body between the '[' at open_idx and its matching ']' (depth-counted)."""
    depth = 0
    i = open_idx
    start = open_idx + 1
    while i < len(text):
        c = text[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return text[start:i]
        i += 1
    raise ValueError(f"Unbalanced brackets starting at index {open_idx}")


def _split_top_level_objects(text: str) -> list[str]:
    """Split a `{...}, {...}, ...` array body into each top-level object's body text."""
    objects = []
    depth = 0
    start = None
    for i, c in enumerate(text):
        if c == "{":
            if depth == 0:
                start = i + 1
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(text[start:i])
                start = None
    return objects


def _extract_capitalized_field(body: str, field: str) -> tuple[list[str], str]:
    """Return (quoted values, raw body text) for a capitalized `Field = [...]` or `Field = "..."`."""
    m = re.search(rf"{field}\s*=\s*\[(.*?)\]", body, re.DOTALL)
    if m:
        raw = m.group(1)
        return _vir._QUOTED_RE.findall(raw), raw
    m = re.search(rf'{field}\s*=\s*"([^"]*)"', body)
    if m:
        return [m.group(1)], f'"{m.group(1)}"'
    return [], ""


def _parse_bootstrap_statements(text: str, role_policy_resource_name: str) -> list[dict]:
    block_re = re.compile(rf'resource\s+"aws_iam_role_policy"\s+"{re.escape(role_policy_resource_name)}"\s*\{{')
    m = block_re.search(text)
    if not m:
        return []
    body = _vir._extract_block(text, m.end() - 1)
    stmt_m = re.search(r"Statement\s*=\s*\[", body)
    if not stmt_m:
        return []
    array_text = _extract_bracket_block(body, stmt_m.end() - 1)
    statements = []
    for obj_body in _split_top_level_objects(array_text):
        sid_m = _SID_CAP_RE.search(obj_body)
        actions, _ = _extract_capitalized_field(obj_body, "Action")
        _, resources_raw = _extract_capitalized_field(obj_body, "Resource")
        statements.append({"sid": sid_m.group(1) if sid_m else None, "actions": actions, "resources_raw": resources_raw})
    return statements


# ---------------------------------------------------------------------------
# terraform/personal/*.tf resource + locals scanning.
# ---------------------------------------------------------------------------

_RESOURCE_BLOCK_RE = re.compile(r'resource\s+"([a-zA-Z0-9_]+)"\s+"([a-zA-Z0-9_]+)"\s*\{')
_DATA_SECRET_VERSION_RE = re.compile(r'data\s+"aws_secretsmanager_secret_version"\s+"([a-zA-Z0-9_]+)"\s*\{')
_LOCALS_BLOCK_RE = re.compile(r"\blocals\s*\{")
_LOCAL_ASSIGN_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')

_NAME_ATTR_CANDIDATES = ("function_name", "layer_name", "name", "url", "secret_id", "bucket")
_ATTR_VALUE_RE_TMPL = r'\b{attr}\s*=\s*("(?:[^"\\]|\\.)*"|local\.\w+|aws_\w+\.\w+\.\w+)'


def _parse_locals(text: str) -> dict[str, str]:
    locals_map: dict[str, str] = {}
    for m in _LOCALS_BLOCK_RE.finditer(text):
        body = _vir._extract_block(text, m.end() - 1)
        for am in _LOCAL_ASSIGN_RE.finditer(body):
            locals_map[am.group(1)] = am.group(2)
    return locals_map


def _scan_resources(personal_dir: Path):
    """Scan every terraform/personal/*.tf file for resource blocks + locals.

    Returns (resources: list[(type, name, filename)], locals_map, attr_index[(type, name)] -> {attr: raw}).
    """
    resources: list[tuple[str, str, str]] = []
    locals_map: dict[str, str] = {}
    attr_index: dict[tuple[str, str], dict[str, str]] = {}
    for tf_path in sorted(personal_dir.glob("*.tf")):
        text = tf_path.read_text(encoding="utf-8")
        locals_map.update(_parse_locals(text))
        for m in _RESOURCE_BLOCK_RE.finditer(text):
            rtype, rname = m.group(1), m.group(2)
            body = _vir._extract_block(text, m.end() - 1)
            resources.append((rtype, rname, tf_path.name))
            attrs = {}
            for attr in _NAME_ATTR_CANDIDATES:
                am = re.search(_ATTR_VALUE_RE_TMPL.format(attr=attr), body)
                if am:
                    attrs[attr] = am.group(1)
            attr_index[(rtype, rname)] = attrs
        for m in _DATA_SECRET_VERSION_RE.finditer(text):
            rname = m.group(1)
            body = _vir._extract_block(text, m.end() - 1)
            rtype = "data:aws_secretsmanager_secret_version"
            resources.append((rtype, rname, tf_path.name))
            attrs = {}
            am = re.search(_ATTR_VALUE_RE_TMPL.format(attr="secret_id"), body)
            if am:
                attrs["secret_id"] = am.group(1)
            attr_index[(rtype, rname)] = attrs
    return resources, locals_map, attr_index


_LOCAL_REF_RE = re.compile(r"^local\.(\w+)$")
_RESOURCE_REF_RE = re.compile(r"^(aws_\w+)\.(\w+)\.(\w+)$")


def _resolve_value(raw: str | None, locals_map: dict, attr_index: dict, _depth: int = 0) -> str | None:
    """Resolve a raw HCL attribute value (literal / local.X / aws_type.name.attr) to a string."""
    if raw is None or _depth > 6:
        return None
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    m = _LOCAL_REF_RE.match(raw)
    if m:
        return locals_map.get(m.group(1))
    m = _RESOURCE_REF_RE.match(raw)
    if m:
        rtype, rname, attr = m.groups()
        sub_raw = attr_index.get((rtype, rname), {}).get(attr)
        return _resolve_value(sub_raw, locals_map, attr_index, _depth + 1) if sub_raw else None
    return None


# ---------------------------------------------------------------------------
# Coverage matching.
# ---------------------------------------------------------------------------


def _literal_or_prefix_match(name: str, raw: str, literal_only: bool = False) -> bool:
    """Does `name` match a literal ARN entry, or (unless literal_only) an agent-platform-*-style prefix?"""
    name_clean = name.strip("/")
    for entry in _vir._QUOTED_RE.findall(raw):
        if entry == "*":
            continue  # the bare-wildcard case is handled by the caller's wildcard branch
        if name in entry or (name_clean and name_clean in entry):
            return True
        if not literal_only and "*" in entry:
            prefix = entry.split("*")[0].rstrip("/:")
            tail = re.split(r"[:/]", prefix)[-1] if prefix else ""
            if tail and (name.lstrip("/").startswith(tail) or name.startswith(tail)):
                return True
    return False


def _action_matches(read_actions: tuple[str, ...], stmt_actions: list[str]) -> bool:
    """Does `stmt_actions` grant one of `read_actions`?

    A `service:Verb*`-suffixed pattern also matches a literal same-verb action (e.g.
    `secretsmanager:Describe*` matches a statement that lists the specific
    `secretsmanager:DescribeSecret` rather than the wildcard form -- both are the same class of
    refresh read; a role is free to spell it either way). Patterns without a trailing `*` require
    an exact match (no prefix-matching risk of pulling in an unrelated same-service action).
    """
    for pattern in read_actions:
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            if any(a == pattern or a.startswith(prefix) for a in stmt_actions):
                return True
        elif pattern in stmt_actions:
            return True
    return False


def _resource_covered(
    rtype: str,
    rname: str,
    resolved_name: str | None,
    read_actions: tuple[str, ...],
    statements: list[dict],
    literal_only: bool = False,
) -> bool:
    for stmt in statements:
        if not _action_matches(read_actions, stmt["actions"]):
            continue
        raw = stmt["resources_raw"]
        if not literal_only and "*" in _vir._QUOTED_RE.findall(raw):
            return True
        # Bare or interpolated Terraform resource reference (oidc.tf style), e.g.
        # `aws_sns_topic.alerts.arn` or `${aws_glue_catalog_database.ops.name}`.
        if f"{rtype}.{rname}." in raw:
            return True
        if resolved_name and _literal_or_prefix_match(resolved_name, raw, literal_only=literal_only):
            return True
    return False


def _classify(rtype: str) -> tuple[dict | None, bool]:
    """Return (spec, literal_only) for `rtype`, or (None, False) if unmapped."""
    spec = CHECKED_TYPES.get(rtype)
    if spec is not None:
        return spec, False
    spec = ENUMERATED_IAM_TYPES.get(rtype)
    return spec, spec is not None


def _resolve_resource_name(rtype: str, rname: str, spec: dict, locals_map: dict, attr_index: dict) -> str | None:
    """Resolve a CHECKED_TYPES/ENUMERATED_IAM_TYPES resource's name/id attribute, if it has one."""
    if not spec["name_attrs"]:
        return None
    raw_val = None
    for attr in spec["name_attrs"]:
        raw_val = attr_index.get((rtype, rname), {}).get(attr)
        if raw_val:
            break
    resolved = _resolve_value(raw_val, locals_map, attr_index) if raw_val else None
    if rtype == "aws_iam_openid_connect_provider" and resolved:
        resolved = resolved.split("://", 1)[-1]
    return resolved


def _check_resource(
    rtype: str,
    rname: str,
    fname: str,
    locals_map: dict,
    attr_index: dict,
    role_statements: dict[str, list[dict]],
    key: str,
) -> tuple[list[str], bool]:
    """Check one resource's coverage. Returns (findings, was_checked)."""
    if rtype in NON_AWS_TYPES or rtype in NO_GRANT_TYPES or rtype in TRANSITIVE_TYPES:
        return [], False

    spec, literal_only = _classify(rtype)
    if spec is None:
        return [
            f"{key} unmapped resource type {rtype!r} (resource {rname} in {fname}) -- add a coverage rule "
            "to scripts/checks/iam_tf/validate_ci_refresh_read_coverage.py"
        ], False

    resolved_name = _resolve_resource_name(rtype, rname, spec, locals_map, attr_index)
    if spec["name_attrs"] and not resolved_name:
        return [
            f"{key} could not resolve a name/id for {rtype} {rname!r} in {fname} -- "
            "treating as uncovered until the extraction is fixed"
        ], False

    findings = []
    for role_key, statements in role_statements.items():
        if not _resource_covered(rtype, rname, resolved_name, spec["read_actions"], statements, literal_only=literal_only):
            findings.append(
                f"{key} {rtype} {rname!r}"
                + (f" ({resolved_name!r})" if resolved_name else "")
                + f" in {fname} is not refresh-read-covered in the {role_key} role policy "
                f"(expected one of {spec['read_actions']} on a matching Resource ARN/reference)"
            )
    return findings, True


def _resolve_role_statements(oidc_text: str) -> dict[str, list[dict]] | None:
    docs = _vir._parse_policy_documents(oidc_text)
    role_policy_map = _vir._parse_role_policy_map(oidc_text)
    result: dict[str, list[dict]] = {}
    for role_key, doc_resource_name in ((ROLE_PLAN, _PLAN_ROLE_POLICY_NAME), (ROLE_DRIFT, _DRIFT_ROLE_POLICY_NAME)):
        doc_name = role_policy_map.get(doc_resource_name)
        if not doc_name:
            return None
        result[role_key] = _vir._resolve_statements(doc_name, docs)
    return result


@registry.register("validate_ci_refresh_read_coverage", owner="platform")
def validate_ci_refresh_read_coverage(failed: list[str]) -> None:
    """Whole-module refresh-read coverage gate (rec-2702 anti-recurrence, PLAN-ci-apply-grant-coupling).

    Every grant-requiring resource across terraform/personal/*.tf must be refresh-read-covered in
    ALL THREE plan-capable role policies: github_ci_apply (terraform/bootstrap/github_ci_apply.tf),
    github_ci_plan + github_ci_drift (terraform/personal/oidc.tf, scanned holistically via the
    shared ci_full_refresh_read composition -- not per role-block). A resource of a type this
    module does not classify FAILS LOUD rather than silently passing (Decision 55).

    Credential-free (pure text parsing, no boto3/terraform invocation) -- eligible for --pre and
    full tiers. Test isolation: patch `scripts.checks._common.ROOT` (both paths are computed from
    it at call time), mirroring validate_invoke_implies_resolve's convention.
    """
    print("\n=== CI refresh-read resource coverage gate (rec-2702 anti-recurrence) ===")
    key = "ci-refresh-read-coverage:"

    personal_dir = _common.ROOT / _PERSONAL_DIR_REL
    bootstrap_tf = _common.ROOT / _BOOTSTRAP_TF_REL
    oidc_tf = personal_dir / "oidc.tf"

    try:
        bootstrap_text = bootstrap_tf.read_text(encoding="utf-8")
    except OSError as exc:
        failed.append(f"{key} cannot read {bootstrap_tf}: {exc}")
        print(f"  FAIL: cannot read bootstrap HCL: {exc}")
        return
    try:
        oidc_text = oidc_tf.read_text(encoding="utf-8")
    except OSError as exc:
        failed.append(f"{key} cannot read {oidc_tf}: {exc}")
        print(f"  FAIL: cannot read oidc.tf: {exc}")
        return

    apply_statements = _parse_bootstrap_statements(bootstrap_text, "github_ci_apply")
    if not apply_statements:
        failed.append(f"{key} no statements parsed from the github_ci_apply policy in {bootstrap_tf.name}")
        print("  FAIL: could not parse the apply role's inline policy statements -- has the HCL shape changed?")
        return

    plan_drift_statements = _resolve_role_statements(oidc_text)
    if plan_drift_statements is None:
        failed.append(f"{key} could not resolve github_ci_plan/github_ci_drift role policies in {oidc_tf.name}")
        print("  FAIL: could not resolve the plan/drift role policy documents -- has the HCL shape changed?")
        return

    role_statements: dict[str, list[dict]] = {ROLE_APPLY: apply_statements, **plan_drift_statements}

    resources, locals_map, attr_index = _scan_resources(personal_dir)
    if not resources:
        failed.append(f"{key} no terraform resources discovered under {personal_dir}")
        print("  FAIL: no terraform resources discovered -- has the module moved?")
        return

    checked = 0
    for rtype, rname, fname in resources:
        findings, was_checked = _check_resource(rtype, rname, fname, locals_map, attr_index, role_statements, key)
        failed.extend(findings)
        if was_checked:
            checked += 1

    if not any(f.startswith(key) for f in failed):
        print(f"  PASS: all {checked} grant-requiring resources are refresh-read-covered in apply/plan/drift.")
