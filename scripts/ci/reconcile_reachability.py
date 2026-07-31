#!/usr/bin/env python3
"""One-shot reachability evaluator for .github/workflows/reconcile.yml's apply-reconcile job.

WHAT IT IS FOR. rec-2847's defect was a reachability defect, not a logic defect: every DEP-10
fresh-replan fallthrough step was gated on `steps.apply.outputs.stale`, and a saved-plan guard-BLOCK
SKIPS the `apply` step -- so that output is never set and the whole fallthrough was structurally
unreachable on exactly the episodes that most need it. Workflow `if:` evaluation is not reproducible
locally, so this module evaluates each step's `if:` over the PARSED workflow and reports
REACHABLE / UNREACHABLE under a supplied context. It ground-truths the fix in BOTH directions: the
frozen pre-fix step list reports `replan` UNREACHABLE (matching what live run 30264239445 actually
did), and the post-fix file reports it REACHABLE.

DELIBERATELY NOT A STANDING GATE. This is a SECOND implementation of GitHub Actions expression
semantics, accepted only as a one-shot artifact for this change. Do NOT register it in
scripts/checks/registry.py or scripts/validate.py, do not wrap it in a scripts/checks/ module, and
do not graduate it into config/agent/verification_registry/registry.yaml. The standing,
non-reintroducible protection for this defect is the `recovery-workflow-topology` guard in
scripts/verify_ci_workflow.py, which is registry-backed and yaml-parsed. This harness ground-truths
that guard once, then stops. It proves REACHABILITY only -- never that the workflow runs, and never
that an apply lands.

TOKEN SUBSET. Only what reconcile.yml's apply-reconcile job actually uses: `success()`, `always()`,
`&&`, `==`, `!=`, single-quoted string literals, and `steps.X.outputs.Y` / `steps.X.outcome`
lookups. Anything else RAISES UnsupportedExpressionError. There is deliberately no permissive
fallback: a token that silently evaluated truthy would turn an UNREACHABLE step into a false
REACHABLE, which is precisely the class of error this harness exists to detect.

EFFECT MODEL, STATED SO IT IS NOT MISTAKEN FOR EVIDENCE. An `if:` string alone cannot say what a
step's `run:` body emits, so the outputs of the five effect-bearing steps are MODELLED from the
supplied context (see _apply_effects). A step this evaluator finds UNREACHABLE is skipped: its
outcome becomes 'skipped' and it emits nothing -- which is the whole mechanism behind the pre-fix
result. The `route` step's modelled output is the same union its shell body implements. The effect
model is IDENTICAL across the pre-fix and post-fix evaluations, so the difference between the two
directions comes solely from the `if:` topology in the file under test.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

APPLY_RECONCILE_JOB = "apply-reconcile"

_TEMPLATE_WRAPPER_RE = re.compile(r"^\$\{\{(?P<body>.*)\}\}$", re.DOTALL)
_LOOKUP_RE = r"steps\.[A-Za-z0-9_-]+\.(?:outputs\.[A-Za-z0-9_-]+|outcome)"
_TOKEN_RE = re.compile(rf"\s*(success\(\)|always\(\)|&&|==|!=|'[^']*'|{_LOOKUP_RE})")

_CONTEXT_VALUES: dict[str, tuple[str, ...]] = {
    "guard": ("PASS", "BLOCK"),
    "guard_fresh": ("PASS", "BLOCK"),
    "apply": ("success", "stale", "failure"),
    "recheck": ("actionable", "cleared"),
}
_DEFAULT_CONTEXT: dict[str, str] = {"guard": "PASS", "apply": "success", "guard_fresh": "PASS", "recheck": "actionable"}


class UnsupportedExpressionError(ValueError):
    """A construct outside the declared token subset -- never guessed at, always raised."""


@dataclass
class _State:
    outputs: dict[str, str] = field(default_factory=dict)
    outcomes: dict[str, str] = field(default_factory=dict)
    failed: bool = False

    def lookup(self, token: str) -> str:
        if token.endswith(".outcome"):
            return self.outcomes.get(token.split(".")[1], "")
        return self.outputs.get(token, "")


@dataclass
class StepReachability:
    key: str
    reachable: bool
    condition: str

    def __str__(self) -> str:
        return f"{'REACHABLE' if self.reachable else 'UNREACHABLE'} {self.key}"


def _tokenize(expression: str) -> list[str]:
    body = expression.strip()
    if match := _TEMPLATE_WRAPPER_RE.match(body):
        body = match.group("body").strip()
    tokens: list[str] = []
    position = 0
    while position < len(body):
        match = _TOKEN_RE.match(body, position)
        if match is None:
            remainder = body[position:].strip()
            raise UnsupportedExpressionError(
                f"unsupported construct at {remainder!r} in {expression!r} -- the declared token "
                "subset is success(), always(), &&, ==, !=, single-quoted literals and "
                "steps.X.outputs.Y / steps.X.outcome. Extend the evaluator; never add a permissive "
                "fallback, which would report a false REACHABLE."
            )
        tokens.append(match.group(1))
        position = match.end()
    if not tokens:
        raise UnsupportedExpressionError(f"empty condition expression: {expression!r}")
    return tokens


def _operand_value(token: str, state: _State) -> str:
    if token.startswith("'"):
        return token[1:-1]
    if token.startswith("steps."):
        return state.lookup(token)
    raise UnsupportedExpressionError(f"{token!r} is not a valid comparison operand")


def _evaluate_term(tokens: list[str], state: _State) -> bool:
    if tokens == ["success()"]:
        return not state.failed
    if tokens == ["always()"]:
        return True
    if len(tokens) == 3 and tokens[1] in ("==", "!="):
        left = _operand_value(tokens[0], state)
        right = _operand_value(tokens[2], state)
        return left == right if tokens[1] == "==" else left != right
    raise UnsupportedExpressionError(
        f"unsupported term {' '.join(tokens)!r} -- each `&&` operand must be success(), always(), "
        "or a two-operand ==/!= comparison. A bare lookup in boolean position is deliberately "
        "rejected rather than guessed at."
    )


def evaluate_condition(expression: str | None, state: _State) -> bool:
    """Evaluate one step's `if:` string. A missing `if:` is GitHub's implicit `success()`."""
    if expression is None:
        return not state.failed
    tokens = _tokenize(str(expression))
    term: list[str] = []
    terms: list[list[str]] = []
    for token in tokens:
        if token == "&&":
            terms.append(term)
            term = []
        else:
            term.append(token)
    terms.append(term)
    return all(_evaluate_term(part, state) for part in terms)


def _apply_effects(step_id: str, context: dict[str, str], state: _State) -> None:
    """Record a REACHABLE step's modelled outputs/outcome. See the module docstring's EFFECT MODEL."""
    if step_id == "guard":
        state.outputs["steps.guard.outputs.routed"] = "true" if context["guard"] == "BLOCK" else ""
    elif step_id == "guard_fresh":
        state.outputs["steps.guard_fresh.outputs.routed"] = "true" if context["guard_fresh"] == "BLOCK" else ""
    elif step_id == "recheck":
        state.outputs["steps.recheck.outputs.still_actionable"] = "true" if context["recheck"] == "actionable" else "false"
    elif step_id == "apply":
        state.outputs["steps.apply.outputs.stale"] = "true" if context["apply"] == "stale" else "false"
        if context["apply"] == "failure":
            state.outcomes["apply"] = "failure"
            state.failed = True
    elif step_id == "route":
        # The union the route step's own shell body implements, modelled -- not read from the file.
        needs_fresh = (
            state.outputs.get("steps.apply.outputs.stale") == "true"
            or state.outputs.get("steps.guard.outputs.routed") == "true"
        )
        state.outputs["steps.route.outputs.needs_fresh_plan"] = "true" if needs_fresh else "false"
        if not needs_fresh:
            state.outputs["steps.route.outputs.fresh_reason"] = ""
        elif state.outputs.get("steps.apply.outputs.stale") == "true":
            state.outputs["steps.route.outputs.fresh_reason"] = "stale_saved_plan"
        else:
            state.outputs["steps.route.outputs.fresh_reason"] = "guard_routed"


def _step_key(step: dict[str, Any]) -> str:
    return str(step.get("id") or step.get("name") or "<unnamed>")


def evaluate(steps: list[dict[str, Any]], context: dict[str, str]) -> list[StepReachability]:
    """Walk the job's steps in order, reporting each step's reachability under `context`."""
    resolved = {**_DEFAULT_CONTEXT, **context}
    for key, value in resolved.items():
        if key not in _CONTEXT_VALUES:
            raise ValueError(f"unknown context key {key!r}; known keys: {sorted(_CONTEXT_VALUES)}")
        if value not in _CONTEXT_VALUES[key]:
            raise ValueError(f"context {key}={value!r} is not one of {list(_CONTEXT_VALUES[key])}")

    state = _State()
    results: list[StepReachability] = []
    for step in steps:
        condition = step.get("if")
        reachable = evaluate_condition(condition, state)
        step_id = str(step.get("id") or "")
        if reachable:
            if step_id:
                state.outcomes.setdefault(step_id, "success")
            _apply_effects(step_id, resolved, state)
        elif step_id:
            state.outcomes[step_id] = "skipped"
        results.append(StepReachability(_step_key(step), reachable, str(condition or "success()")))
    return results


def load_steps(workflow_path: str, job_name: str = APPLY_RECONCILE_JOB) -> list[dict[str, Any]]:
    data = yaml.safe_load(Path(workflow_path).read_text(encoding="utf-8"))
    jobs = data.get("jobs", {})
    if job_name not in jobs:
        raise ValueError(f"{workflow_path} has no {job_name!r} job")
    return list(jobs[job_name].get("steps", []) or [])


def parse_context(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    context: dict[str, str] = {}
    for pair in raw.split(","):
        if not pair.strip():
            continue
        if "=" not in pair:
            raise ValueError(f"context entry {pair!r} is not k=v")
        key, value = pair.split("=", 1)
        context[key.strip()] = value.strip()
    return context


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("workflow", help="path to the workflow file (e.g. .github/workflows/reconcile.yml)")
    parser.add_argument("--context", default="", help='comma-separated k=v, e.g. "guard=BLOCK,guard_fresh=PASS"')
    parser.add_argument("--job", default=APPLY_RECONCILE_JOB)
    parser.add_argument("--step", default=None, help="report only this step id/name")
    args = parser.parse_args(argv)

    try:
        results = evaluate(load_steps(args.workflow, args.job), parse_context(args.context))
    except (UnsupportedExpressionError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.step is not None:
        results = [result for result in results if result.key == args.step]
        if not results:
            print(f"ERROR: no step {args.step!r} in job {args.job!r}", file=sys.stderr)
            return 1
    for result in results:
        print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
