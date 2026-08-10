"""Masked-errexit inline-body guard (round-2 census extension of Decision 162's defect class,
scoped to .github/workflows/ inline run: bodies specifically; PLAN-pr-conflict-signal-exit-status).

Defect shape: a step declares continue-on-error: true and its inline run: body inherits errexit
(GitHub's default run-step invocation is "bash --noprofile --norc -e -o pipefail {0}"; the body
inherits -e unless it clears it with its own `set +e`). Inside such a body, an unguarded
VAR=$(...) command-substitution assignment ABORTS THE STEP the instant its inner command fails --
but because the step is continue-on-error, the JOB STAYS GREEN while every statement after the
abort point silently never runs. This is the shape rec-2735 exhibited (pr-conflict-signal.yml,
before its extraction to scripts/ci/) and the shape ci-rca.yml's CATEGORIES assignment exhibited
independently: a sort/paste failure could abort the evidence step before its GITHUB_OUTPUT writes,
handing downstream steps silently empty bundle_sha / bundle_s3_uri / bundle_path.

POSITIONAL GUARD RULE (load-bearing -- the whole guard turns on it). A `||` counts as guarding a
VAR=$(...) assignment ONLY when it terminates the substitution's TOP-LEVEL command list: either
immediately after the closing paren (`VAR=$(...) || VAR=""`), or as the LAST top-level element
strictly inside the parens (`VAR=$(cmd | cmd2 || echo "")`). A `||` nested inside a
for/while/until...do...done body, or inside a further nested (...)/$(...) substitution, does NOT
guard the outer assignment -- it guards only its own immediately-enclosing command. Two broken
alternatives were measured and rejected at plan time: a PER-LINE detector fires on ci-rca.yml's
CATEGORIES assignment both before and after the fix (the guarding `|| CATEGORIES=""` lands three
lines below the assignment line, so a per-line scan can never discriminate); a PAREN-BALANCED
joiner that merely tests for any `||` anywhere inside the substitution fires on NEITHER shape (it
is satisfied by the INNER `|| echo "unknown"` inside the for-loop), which would silently make this
guard's zero population an artifact of a blind detector rather than an earned one. Only the
positional rule fires on the pre-fix shape and clears on the post-fix one, while still recognising
the simpler single-line BUNDLE_SHA=$(... | cut -d= -f2 || echo "") shape as already-guarded.

Round-2 census correction, the OTHER failure mode a naive implementation exhibits: the guard's
real predicate is "inherits errexit" (GitHub's default), never "declares `set -u`/`set -o
pipefail` without clearing errexit" -- a body with NO set line at all still inherits errexit and
is MORE exposed, not less (a declares-set filter measured at plan time missed 10 of 11 real
continue-on-error inline bodies outright). A candidate body is therefore any continue-on-error
inline run: body that does NOT contain its own `set +e` -- irrespective of what else it declares.
Backslash continuations are joined against the RAW body text (not line-by-line) before any other
scanning, so a continuation-split assignment (e.g. ci-rca.yml's ARTIFACT_ID=$(... \\n ... || echo
"")) is read as one contiguous stream rather than reported unguarded by a per-line scan that never
saw the trailing guard.

Scope, deliberately narrow: INLINE `.github/workflows/*.yml`/`*.yaml` run: bodies only. A
DELEGATED script (scripts/ci/*.sh) runs in a child bash that does NOT inherit the parent's errexit
at all (confirmed empirically: a child bash does not inherit SHELLOPTS), so this exact defect
class cannot occur there by construction -- that surface is the KNOWN COVERAGE GAP this plan
records deliberately (a follow-on rec extends Decision 162 R2's literal-argv test-coverage
obligation to workflow delegates; it is a different mechanism, not this guard widened). A
composite-action manifest (.github/actions/**) is likewise out of scope -- R1 already forces every
OUTPUT-PRODUCING composite body to be a thin delegate, and .github/actions/ carries zero
step-level continue-on-error declarations today, so a composite leg would govern an empty
universe. Filesystem-only: no subprocess, no network (Decision 153 fast-tier budget), matching
every sibling ci_guards module.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from scripts.checks import _common, registry
from scripts.checks.ci_guards import _workflow_shell_bodies

# A body "clears" inherited errexit only via its OWN `set ... +e` statement at line-start (not a
# substring inside a comment or a quoted string) -- absence of this is what makes a body a
# candidate; presence of `set -e`/`set -u`/`set -o pipefail` alone does NOT clear it (`set` only
# touches the options it names).
_HAS_SET_PLUS_E_RE = re.compile(r"(?m)^[ \t]*set\s+(?:[-+]\S+\s+)*\+e\b")

# Bash's own line-continuation token, applied to the RAW multi-line body text (not line-by-line).
_LINE_CONTINUATION_RE = re.compile(r"\\\r?\n")

# A command-substitution assignment start: an identifier immediately followed by `=$(`, not
# preceded by a word character or `.` (excludes e.g. a trailing fragment of a larger token).
_ASSIGN_SUBST_RE = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)=\$\(")

# The last top-level element inside a masked substitution body is `||`-guarded when a `||`,
# possibly followed by inline content, runs uninterrupted (no `;`/newline -- a NEW top-level
# statement) all the way to the end of the (rstripped) masked text.
_TRAILING_GUARD_RE = re.compile(r"\|\|[ \t]*\S[^;\n]*[ \t]*\Z")

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def scanned_workflow_files() -> list[Path]:
    """The SINGLE SOURCE of this guard's file set. Delegates to the shared workflow walker
    (scripts.checks.ci_guards._workflow_shell_bodies._iter_workflows) rather than a private glob,
    so validate_masked_errexit_steps() can never silently scan a narrower set than it reports --
    the guard's own zero-violations claim would otherwise be unfalsifiable by an independent scan.
    """
    return _workflow_shell_bodies._iter_workflows()


def _join_backslash_continuations(text: str) -> str:
    """Bash's own `\\<newline>` continuation, applied to the raw text (never line-by-line) so a
    backslash-continued assignment reads as one contiguous stream before any guard/paren scan."""
    return _LINE_CONTINUATION_RE.sub(" ", text)


def _leading_word(text: str, index: int) -> str:
    """The identifier word starting exactly at `index`, or "" if `index` is mid-word or no
    identifier starts there -- recognises `do`/`done` as whole-word keywords only (never a
    substring of e.g. "domino"/"undone"). No trailing-boundary check is needed: `_WORD_RE` is
    greedy over `[A-Za-z0-9_]`, so a successful match already consumes every following word
    character -- the character at its end (if any) can never itself be alnum/underscore."""
    if index > 0 and (text[index - 1].isalnum() or text[index - 1] == "_"):
        return ""
    match = _WORD_RE.match(text, index)
    return match.group() if match else ""


def _find_matching_paren(text: str, open_index: int) -> int | None:
    """Index of the ')' matching the '(' at `open_index`, tracking nested parens and skipping
    quoted regions (single/double, backslash-escaped double quotes honoured). None if unmatched
    before the text ends."""
    depth = 0
    in_single = in_double = False
    i = open_index
    n = len(text)
    while i < n:
        ch = text[i]
        if in_single:
            in_single = ch != "'"
        elif in_double:
            if ch == '"' and text[i - 1] != "\\":
                in_double = False
        elif ch == "'":
            in_single = True
        elif ch == '"':
            in_double = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _mask_nested_regions(inner: str) -> str:
    """Blank out (with spaces, same length) every nested (...) group and do...done block inside
    `inner`, so only the substitution's TOP-LEVEL text remains non-blank -- the positional guard
    rule is then evaluated against this masked text. A single stack handles arbitrarily mixed
    nesting of parens and do/done pairs; quote tracking is global (a shell string literal never
    nests a same-type quote inside itself)."""
    n = len(inner)
    masked = list(inner)
    stack: list[tuple[str, int]] = []  # (kind, start_index); kind is "paren" or "do"
    in_single = in_double = False
    i = 0
    while i < n:
        ch = inner[i]
        if in_single:
            in_single = ch != "'"
            i += 1
            continue
        if in_double:
            if ch == '"' and inner[i - 1] != "\\":
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue

        if ch == "(":
            stack.append(("paren", i))
            i += 1
            continue
        if ch == ")":
            if stack and stack[-1][0] == "paren":
                _, start = stack.pop()
                if not stack:
                    for j in range(start, i + 1):
                        masked[j] = " "
            i += 1
            continue

        word = _leading_word(inner, i)
        if word == "do":
            stack.append(("do", i))
            i += 2
            continue
        if word == "done":
            if stack and stack[-1][0] == "do":
                _, start = stack.pop()
                end = i + 4
                if not stack:
                    for j in range(start, end):
                        masked[j] = " "
                i = end
                continue
            i += 4
            continue

        i += 1
    return "".join(masked)


def _assignment_is_guarded(body: str, open_paren_index: int, close_paren_index: int) -> bool:
    """True iff the VAR=$(...) assignment whose substitution spans
    [open_paren_index, close_paren_index] in `body` is guarded per the positional rule."""
    after = body[close_paren_index + 1 :]
    inline_ws_len = len(after) - len(after.lstrip(" \t"))
    if after[inline_ws_len : inline_ws_len + 2] == "||":
        return True

    inner = body[open_paren_index + 1 : close_paren_index]
    masked = _mask_nested_regions(inner)
    return bool(_TRAILING_GUARD_RE.search(masked.rstrip()))


def _unguarded_assignments(body: str) -> list[str]:
    """Variable names of VAR=$(...) assignments in `body` (backslash-continuations already
    joined) that the positional guard rule finds unguarded."""
    violations: list[str] = []
    for match in _ASSIGN_SUBST_RE.finditer(body):
        open_paren_index = match.end() - 1
        close_paren_index = _find_matching_paren(body, open_paren_index)
        if close_paren_index is None:
            continue
        if not _assignment_is_guarded(body, open_paren_index, close_paren_index):
            violations.append(match.group(1))
    return violations


def _is_candidate_body(body: str) -> bool:
    """A body is a candidate (inherits errexit) iff it does NOT clear it with its own `set +e` --
    GitHub's run-step default already applies -e, so it is the ABSENCE of `set +e` (never the
    presence or absence of `set -e`/`-u`/pipefail) that makes a body errexit-inheriting."""
    return _HAS_SET_PLUS_E_RE.search(body) is None


@registry.register("validate_masked_errexit_steps", owner="platform")
def validate_masked_errexit_steps(failed: list[str]) -> None:
    """Flag a continue-on-error step whose INLINE .github/workflows/ body inherits errexit and
    holds an unguarded VAR=$(...) command-substitution assignment. See the module docstring for
    the full derivation and the positional guard rule. Filesystem-only, both presubmit tiers."""
    print("\n=== Masked-errexit inline-body guard ===")
    violations: list[str] = []

    for path in scanned_workflow_files():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        rel_path = str(path.relative_to(_common.ROOT)).replace("\\", "/")
        jobs = data.get("jobs")
        if not isinstance(jobs, dict):
            continue
        workflow_shell = _workflow_shell_bodies._default_shell(data)
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            job_shell = _workflow_shell_bodies._default_shell(job) or workflow_shell
            for index, step in enumerate(steps):
                if not isinstance(step, dict) or step.get("continue-on-error") is not True:
                    continue
                run_body = step.get("run")
                if not isinstance(run_body, str):
                    continue
                if not _workflow_shell_bodies._is_governed_shell(step.get("shell", job_shell)):
                    continue
                if not _is_candidate_body(run_body):
                    continue
                joined = _join_backslash_continuations(run_body)
                unguarded_vars = _unguarded_assignments(joined)
                if unguarded_vars:
                    identity = _workflow_shell_bodies._step_identity(step, index)
                    violations.append(
                        f"{rel_path}::{job_id}::{identity}: unguarded command-substitution "
                        f"assignment(s) {unguarded_vars} under inherited errexit -- "
                        "continue-on-error: true means the job stays green while everything "
                        "after the abort point silently never runs."
                    )

    if violations:
        for v in violations:
            print(f"  FAIL: {v}")
            failed.append(f"masked-errexit inline-body guard: {v}")
    else:
        print("  PASS: no unguarded command-substitution assignments under inherited errexit")
