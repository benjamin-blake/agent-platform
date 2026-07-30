"""Bootstrap IAM policy-size PRECONDITION-PRESENCE gate (H3 -- PLAN-iam-write-surface-completion).

Every ``aws_iam_role_policy`` / ``aws_iam_policy`` declared under terraform/bootstrap/ must carry a
``lifecycle { precondition { ... } }`` whose condition names its CORRECT AWS hard limit: 10,240 B
for an inline role policy, 6,144 B for a customer-managed policy. A LimitExceeded on either is
INVISIBLE to ``terraform plan`` and surfaces only at apply -- and the bootstrap root is applied by
hand, out of band, so a byte overflow discovered at apply time strands a half-applied IAM change.

PRESENCE ONLY, deliberately (H3). This check does NOT render, minify, or var-substitute HCL: a
hand-rolled HCL->JSON renderer in the fast tier would red every PR on any shape it cannot parse,
and the policy-architecture split changes that shape twice (the read relocation + the boundary
hoist). The byte ASSERTION stays where terraform can evaluate it correctly -- inside the
preconditions themselves, at admin plan time. This gate only guarantees those preconditions exist
and are wired to the right constant, so the assertion cannot be silently dropped or mis-typed
(e.g. 6144 pasted onto an inline role policy, which would pass every plan while permitting a
4,096 B overflow).

Pure text, credential-free, position-independent -- eligible for the --pre and full tiers. Test
isolation: patch ``scripts.checks._common.ROOT`` (the bootstrap dir is computed from it at call
time), mirroring validate_boundary_attached's convention.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.checks import _common, registry

_BOOTSTRAP_DIR_REL = Path("terraform") / "bootstrap"

# AWS hard limits per policy container, keyed by terraform resource type. Both are the
# whitespace-stripped ("minified") measure AWS actually enforces -- see rec-2793.
POLICY_SIZE_LIMITS: dict[str, int] = {
    "aws_iam_role_policy": 10240,
    "aws_iam_policy": 6144,
}

_KIND_LABEL: dict[str, str] = {
    "aws_iam_role_policy": "inline role policy",
    "aws_iam_policy": "customer-managed policy",
}

# The closing quote after the alternation is what keeps aws_iam_role_policy_attachment out.
_RESOURCE_RE = re.compile(r'resource\s+"(?P<rtype>aws_iam_role_policy|aws_iam_policy)"\s+"(?P<name>[^"]+)"\s*\{')
_LIFECYCLE_RE = re.compile(r"(?<![\w.])lifecycle\s*\{")
_PRECONDITION_RE = re.compile(r"(?<![\w.])precondition\s*\{")
_CONDITION_RE = re.compile(r"(?<![\w.])condition\s*=")
_ERROR_MESSAGE_RE = re.compile(r"(?<![\w.])error_message\s*=")
_INT_RE = re.compile(r"\d+")


def _mask_noise(text: str) -> str:
    """Return an equal-length copy of `text` with comment bodies and string contents blanked.

    Offsets are preserved (every blanked character becomes a space; newlines survive), so any
    index found in the mask indexes straight back into the original. Masking both comments and
    string literals is what makes the structural scan below immune to (a) a `lifecycle {` or a
    stray brace written inside an HCL comment -- this file is heavily commented and actively
    edited -- and (b) digits or braces living inside a string, e.g. the "10,240 B" error_message
    prose or an "${var.account_id}" interpolation.

    Heredocs are not masked; terraform/bootstrap uses none, and a heredoc body would only ever
    add false FINDINGS (never a false pass) since a policy resource still needs its precondition.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        char = text[i]
        if char == "#" or (char == "/" and i + 1 < n and text[i + 1] == "/"):
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif char == "/" and i + 1 < n and text[i + 1] == "*":
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            for j in range(i, min(i + 2, n)):
                out[j] = " "
            i += 2
        elif char == '"':
            i += 1  # the quotes themselves stay, so the resource header still matches on the original
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    out[i] = " "
                    i += 1
                if i < n:
                    if text[i] != "\n":
                        out[i] = " "
                    i += 1
            i += 1
        else:
            i += 1
    return "".join(out)


def _extract_block(masked: str, open_brace_idx: int) -> str:
    """Body between the '{' at open_brace_idx and its matching '}' in already-masked text."""
    depth = 0
    for i in range(open_brace_idx, len(masked)):
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return masked[open_brace_idx + 1 : i]
    raise ValueError(f"unbalanced braces starting at index {open_brace_idx}")


def _condition_expressions(masked_body: str) -> list[str]:
    """Every lifecycle/precondition `condition = ...` expression in a masked resource body.

    The expression is cut at `error_message` so a limit quoted in the message prose can never
    stand in for the real assertion (the message is masked anyway -- belt and braces).
    """
    exprs: list[str] = []
    for life_m in _LIFECYCLE_RE.finditer(masked_body):
        try:
            lifecycle_body = _extract_block(masked_body, life_m.end() - 1)
        except ValueError:
            continue
        for pre_m in _PRECONDITION_RE.finditer(lifecycle_body):
            try:
                precondition_body = _extract_block(lifecycle_body, pre_m.end() - 1)
            except ValueError:
                continue
            cond_m = _CONDITION_RE.search(precondition_body)
            if cond_m is None:
                continue
            expr = precondition_body[cond_m.end() :]
            err_m = _ERROR_MESSAGE_RE.search(expr)
            exprs.append(expr[: err_m.start()] if err_m else expr)
    return exprs


@registry.register("validate_iam_policy_size", owner="platform")
def validate_iam_policy_size(failed: list[str]) -> None:
    """Assert every bootstrap IAM policy resource carries a size precondition naming its limit."""
    print("\n=== Bootstrap IAM policy-size precondition gate (H3 / PLAN-iam-write-surface-completion) ===")
    key = "iam-policy-size:"

    bootstrap_dir = _common.ROOT / _BOOTSTRAP_DIR_REL
    tf_files = sorted(bootstrap_dir.glob("*.tf"))
    if not tf_files:
        failed.append(f"{key} no .tf files under {bootstrap_dir}")
        print(f"  FAIL: no terraform/bootstrap .tf files found under {bootstrap_dir}.")
        return

    checked = 0
    for path in tf_files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            failed.append(f"{key} cannot read {path}: {exc}")
            print(f"  FAIL: cannot read {path.name}: {exc}")
            continue

        masked = _mask_noise(text)
        for match in _RESOURCE_RE.finditer(text):
            if masked[match.start()] != text[match.start()]:
                continue  # the header sits inside a comment or a string literal, not real HCL
            rtype, rname = match.group("rtype"), match.group("name")
            label = f"{rtype}.{rname} ({path.name})"
            try:
                body = _extract_block(masked, match.end() - 1)
            except ValueError as exc:
                failed.append(f"{key} {label}: cannot parse the resource block -- {exc}")
                print(f"  FAIL {label}: {exc}")
                continue

            checked += 1
            expected = POLICY_SIZE_LIMITS[rtype]
            exprs = _condition_expressions(body)
            if not exprs:
                failed.append(
                    f"{key} {label} declares no lifecycle precondition -- every {_KIND_LABEL[rtype]} in "
                    f"terraform/bootstrap must assert its rendered document is <= {expected} B "
                    f"(a LimitExceeded is invisible to terraform plan and surfaces only at apply)"
                )
                print(f"  FAIL {label}: no lifecycle precondition (expected a <= {expected} B assertion)")
                continue

            found = {int(tok) for expr in exprs for tok in _INT_RE.findall(expr)}
            if expected in found:
                print(f"  OK   {label}: precondition names the {expected} B {_KIND_LABEL[rtype]} limit")
                continue

            wrong = sorted(found & (set(POLICY_SIZE_LIMITS.values()) - {expected}))
            detail = (
                f"names the WRONG limit constant {wrong[0]} (that is the "
                f"{_KIND_LABEL['aws_iam_policy' if wrong[0] == 6144 else 'aws_iam_role_policy']} limit)"
                if wrong
                else f"names no recognised limit constant (saw {sorted(found) or 'none'})"
            )
            failed.append(
                f"{key} {label}: its lifecycle precondition {detail} -- a {_KIND_LABEL[rtype]} must assert <= {expected} B"
            )
            print(f"  FAIL {label}: precondition {detail}; expected {expected}")

    if checked == 0:
        failed.append(
            f"{key} no aws_iam_role_policy / aws_iam_policy resources discovered under {bootstrap_dir} "
            f"-- has the HCL shape changed? (a silent zero-resource pass would make this gate inert)"
        )
        print("  FAIL: no policy resources discovered -- refusing to pass vacuously.")
        return

    if not any(f.startswith(key) for f in failed):
        print(f"  PASS: all {checked} bootstrap IAM policy resources carry a size precondition naming their limit.")


if __name__ == "__main__":  # pragma: no cover
    # Standalone entry point so `python -m scripts.checks.iam_tf.validate_iam_policy_size` exercises
    # the check (exit 1 on any finding), mirroring validate_ci_refresh_read_coverage's runner.
    _failed: list[str] = []
    validate_iam_policy_size(_failed)
    for _f in _failed:
        print(f"  - {_f}")
    raise SystemExit(1 if _failed else 0)
