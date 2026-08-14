"""c2 convergence-writer isolation (T2.49 / DEP-12 hardening item 1, Decision 92 pt2).

JSON-SEMANTIC STANDING CHECK (family-matches validate_invoke_implies_resolve.py): parses
terraform/personal/oidc.tf's aws_iam_policy_document blocks -- resolving source_policy_documents
transitively, the same composition model the refresh-read coverage checks use -- and asserts the
c2 fail-closed convergence-write design holds STRUCTURALLY, not merely by grep-presence:

  (a) EVERY statement granting s3:PutObject on convergence/personal/* in the github_ci_planner
      policy carries a condition on aws:userid keyed to local.convergence_writer_session_name.
  (b) Exactly one such Allow exists (no SECOND, unconditioned Allow added alongside the good one
      -- the blind spot a grep for "ConvergenceRecordWrite" cannot see: it would grep-pass while
      being fail-open).
  (c) github_ci_branch still carries its explicit DenyConvergenceRecordWrite statement.
  (d) github_ci_pr grants no s3:PutObject on convergence/personal/* (stays read-only).

Credential-free (pure text parsing, no boto3/terraform invocation) -- eligible for --pre and full
tiers, mirroring validate_invoke_implies_resolve / validate_ci_refresh_read_coverage. This is a
STATIC-TEXT check (not a full IAM policy evaluation): a resource scoped by an unrelated broad
wildcard that happens to also cover convergence/personal/* would not be detected here -- the
creds-gated simulate-principal-policy VP step (post-deploy, operator-assisted) is the layer that
proves actual runtime IAM evaluation; this check proves the structural invariant is present in
the committed HCL.
"""

from __future__ import annotations

import re

from scripts.checks import _common, registry
from scripts.checks.iam_tf import validate_invoke_implies_resolve as _vir

_CONVERGENCE_RESOURCE_MARKER = "convergence/personal"
_PUTOBJECT_ACTIONS = {"s3:PutObject", "s3:*"}
_RESERVED_SESSION_LOCAL_MARKER = "local.convergence_writer_session_name"

_EFFECT_RE = re.compile(r'\beffect\s*=\s*"([^"]*)"')
_CONDITION_BLOCK_RE = re.compile(r"condition\s*\{")
_TEST_RE = re.compile(r'\btest\s*=\s*"([^"]*)"')
_VARIABLE_RE = re.compile(r'\bvariable\s*=\s*"([^"]*)"')
_VALUES_RE = re.compile(r"\bvalues\s*=\s*\[(?P<body>.*?)\]", re.DOTALL)


def _find_full_statements(body: str) -> list[dict]:
    """Like validate_invoke_implies_resolve._find_statements, but also captures effect +
    condition sub-blocks -- this check needs both and the shared helper captures neither."""
    statements = []
    for m in _vir._STATEMENT_BLOCK_RE.finditer(body):
        stmt_body = _vir._extract_block(body, m.end() - 1)
        sid_m = _vir._SID_RE.search(stmt_body)
        effect_m = _EFFECT_RE.search(stmt_body)
        actions_m = _vir._ACTIONS_RE.search(stmt_body)
        resources_m = _vir._RESOURCES_RE.search(stmt_body)
        conditions = []
        for cond_m in _CONDITION_BLOCK_RE.finditer(stmt_body):
            cond_body = _vir._extract_block(stmt_body, cond_m.end() - 1)
            test_m = _TEST_RE.search(cond_body)
            var_m = _VARIABLE_RE.search(cond_body)
            values_m = _VALUES_RE.search(cond_body)
            conditions.append(
                {
                    "test": test_m.group(1) if test_m else None,
                    "variable": var_m.group(1) if var_m else None,
                    "values_raw": values_m.group("body") if values_m else "",
                }
            )
        statements.append(
            {
                "sid": sid_m.group(1) if sid_m else None,
                "effect": effect_m.group(1) if effect_m else "Allow",
                "actions": _vir._QUOTED_RE.findall(actions_m.group("body")) if actions_m else [],
                "resources_raw": resources_m.group("body") if resources_m else "",
                "conditions": conditions,
            }
        )
    return statements


def _parse_full_policy_documents(text: str) -> dict[str, dict]:
    """Mirrors validate_invoke_implies_resolve._parse_policy_documents, but stores the richer
    _find_full_statements shape (effect + condition) under the same 'sources'/'statements' keys
    -- _vir._resolve_statements is generic over those two keys and works unmodified here."""
    docs: dict[str, dict] = {}
    for m in _vir._DATA_BLOCK_RE.finditer(text):
        body = _vir._extract_block(text, m.end() - 1)
        source_m = _vir._SOURCE_DOCS_RE.search(body)
        sources = _vir._SOURCE_DOC_REF_RE.findall(source_m.group("body")) if source_m else []
        docs[m.group("name")] = {"sources": sources, "statements": _find_full_statements(body)}
    return docs


def _convergence_putobject_allows(statements: list[dict]) -> list[dict]:
    """Every Allow statement granting s3:PutObject (or s3:*) on a convergence/personal/*-matching
    resource."""
    return [
        s
        for s in statements
        if s["effect"] == "Allow"
        and _CONVERGENCE_RESOURCE_MARKER in s["resources_raw"]
        and any(a in _PUTOBJECT_ACTIONS for a in s["actions"])
    ]


def _has_reserved_session_userid_condition(stmt: dict) -> bool:
    return any(
        c.get("variable") == "aws:userid" and _RESERVED_SESSION_LOCAL_MARKER in (c.get("values_raw") or "")
        for c in stmt["conditions"]
    )


def _sids(statements: list[dict]) -> str:
    return ", ".join(s["sid"] or "<no-sid>" for s in statements)


def _resolve_role_or_fail(role: str, doc_name: str, docs: dict[str, dict], key: str, failed: list[str]) -> list[dict] | None:
    """Resolve a role's statements; append a fail-loud finding and return None on any unresolvable
    document (top-level or nested source) rather than letting an empty statement list masquerade
    as a legitimate pass (Decision 129 clause 4)."""
    unresolved: list[str] = []
    statements = _vir._resolve_statements(doc_name, docs, unresolved=unresolved)
    if unresolved:
        failed.append(
            f"{key} {role} references unresolvable policy document(s) {sorted(set(unresolved))!r} -- cannot "
            "determine whether its convergence-write isolation holds (Decision 129 clause 4: fail loud, "
            "never a silent pass)"
        )
        print(f"  FAIL: {role} references unresolvable document(s) {sorted(set(unresolved))}.")
        return None
    return statements


@registry.register("validate_convergence_writer_isolation", owner="platform")
def validate_convergence_writer_isolation(failed: list[str]) -> None:
    """See module docstring for the four assertions (a)-(d)."""
    print("\n=== c2 convergence-writer isolation (T2.49 / DEP-12 hardening item 1, Decision 92 pt2) ===")
    key = "convergence-writer-isolation:"
    personal_dir = _common.ROOT / _vir._PERSONAL_DIR_REL
    personal_files = sorted(personal_dir.glob("*.tf"))
    text = _vir._read_root_text(personal_dir)
    if not text:
        registry.skipped(f"no *.tf file readable under {personal_dir}")
        failed.append(f"{key} cannot read any *.tf file under {personal_dir}")
        print(f"  FAIL: cannot read any *.tf file under {personal_dir}")
        return

    docs = _parse_full_policy_documents(text)
    role_policy = _vir._parse_role_policy_map(text)

    if not docs or not role_policy:
        failed.append(f"{key} no aws_iam_policy_document / aws_iam_role_policy blocks found under {personal_dir}")
        print("  FAIL: no policy documents or role policies parsed -- has the HCL shape changed?")
        return

    registry.examined(len(personal_files), unit="personal_tf_files")

    # (a) + (b): the planner's convergence-write must be exactly one, aws:userid-conditioned Allow.
    planner_doc = role_policy.get("github_ci_planner")
    if not planner_doc:
        failed.append(f"{key} could not resolve github_ci_planner's policy document under {personal_dir}")
        print("  FAIL: github_ci_planner role_policy -> policy document mapping not found.")
    else:
        planner_statements = _resolve_role_or_fail("github_ci_planner", planner_doc, docs, key, failed)
        if planner_statements is not None:
            writes = _convergence_putobject_allows(planner_statements)
            if not writes:
                failed.append(
                    f"{key} github_ci_planner grants NO s3:PutObject Allow on convergence/personal/* -- expected "
                    "exactly one, aws:userid-conditioned to local.convergence_writer_session_name (c2 design)"
                )
                print("  FAIL: no convergence-write Allow found on the planner policy.")
            else:
                unconditioned = [s for s in writes if not _has_reserved_session_userid_condition(s)]
                if unconditioned:
                    failed.append(
                        f"{key} github_ci_planner has {len(unconditioned)} convergence-write Allow(s) NOT "
                        f"aws:userid-conditioned to local.convergence_writer_session_name (sid(s): "
                        f"{_sids(unconditioned)}) -- every s3:PutObject Allow on convergence/personal/* MUST "
                        "carry this condition (Decision 92 pt2 fail-closed; an unconditioned second Allow is a "
                        "FAIL-OPEN regression)"
                    )
                    print(f"  FAIL: {len(unconditioned)} unconditioned convergence-write Allow(s): {_sids(unconditioned)}")
                elif len(writes) > 1:
                    failed.append(
                        f"{key} github_ci_planner has {len(writes)} convergence-write Allow statements (expected "
                        f"exactly 1; sid(s): {_sids(writes)}) -- consolidate to a single conditioned Allow"
                    )
                    print(f"  FAIL: {len(writes)} convergence-write Allow statements (expected 1): {_sids(writes)}")
                else:
                    print(
                        "  PASS: exactly one convergence-write Allow, aws:userid-conditioned to the "
                        f"reserved session (sid={writes[0]['sid']})."
                    )

    # (c): github_ci_branch retains its explicit DenyConvergenceRecordWrite.
    branch_doc = role_policy.get("github_ci_branch")
    if not branch_doc:
        failed.append(f"{key} could not resolve github_ci_branch's policy document under {personal_dir}")
        print("  FAIL: github_ci_branch role_policy -> policy document mapping not found.")
    else:
        branch_statements = _resolve_role_or_fail("github_ci_branch", branch_doc, docs, key, failed)
        if branch_statements is not None:
            has_deny = any(
                s["effect"] == "Deny"
                and _CONVERGENCE_RESOURCE_MARKER in s["resources_raw"]
                and any(a in _PUTOBJECT_ACTIONS for a in s["actions"])
                for s in branch_statements
            )
            if not has_deny:
                failed.append(
                    f"{key} github_ci_branch is missing its DenyConvergenceRecordWrite statement "
                    "(explicit Deny on s3:PutObject convergence/personal/*)"
                )
                print("  FAIL: github_ci_branch's DenyConvergenceRecordWrite is missing.")
            else:
                print("  PASS: github_ci_branch retains DenyConvergenceRecordWrite.")

    # (d): github_ci_pr stays read-only on convergence (no PutObject grant at all). The unresolvable
    # branch matters MOST here: an absent grant is what a PASS looks like, so an unresolved document
    # must never fall through to "no writes found" -- see the module docstring's "live hazard" note.
    pr_doc = role_policy.get("github_ci_pr")
    if not pr_doc:
        failed.append(f"{key} could not resolve github_ci_pr's policy document under {personal_dir}")
        print("  FAIL: github_ci_pr role_policy -> policy document mapping not found.")
    else:
        pr_statements = _resolve_role_or_fail("github_ci_pr", pr_doc, docs, key, failed)
        if pr_statements is not None:
            pr_writes = _convergence_putobject_allows(pr_statements)
            if pr_writes:
                failed.append(
                    f"{key} github_ci_pr grants s3:PutObject Allow on convergence/personal/* (sid(s): "
                    f"{_sids(pr_writes)}) -- it must stay read-only on the convergence record"
                )
                print(f"  FAIL: github_ci_pr has convergence-write grant(s): {_sids(pr_writes)}")
            else:
                print("  PASS: github_ci_pr stays read-only on the convergence record (no PutObject grant).")


if __name__ == "__main__":  # pragma: no cover
    # Standalone entry point so `python -m scripts.checks.iam_tf.validate_convergence_writer_isolation`
    # actually exercises the check (exit 1 on any finding), mirroring validate_ci_refresh_read_coverage's runner.
    _failed: list[str] = []
    validate_convergence_writer_isolation(_failed)
    for _f in _failed:
        print(f"  - {_f}")
    raise SystemExit(1 if _failed else 0)
