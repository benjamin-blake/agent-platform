# complexity-waiver: decision-43
"""Gate-rule mini-language: tokenizer, recursive-descent evaluator, and grammar parser."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scripts.platform_roadmap_state import PlatformRoadmapState

_INACTIVE_FOR_TIER: frozenset[str] = frozenset({"reserved", "deferred_post_mvp"})

# ---------------------------------------------------------------------------
# Gate-rule evaluator (GateRuleEvaluator) -- T-1.20
#
# No eval()/exec(). Tokenizer + recursive-descent over the gate mini-grammar.
# Three-valued (Kleene) logic with proper short-circuit:
#   false AND deferred -> false  (not deferred-poisoning)
#   true  OR  deferred -> true   (not deferred-poisoning)
# Static fields: only 'status' is resolvable from the YAML. Any other field
# path (latest_run.verdict, uptime_days, ...) and item_field_eq -> deferred.
# Field-path resolution: longest-known-tier-item-id prefix (dot-delimited).
# ---------------------------------------------------------------------------

_EVAL_TOKEN_RE = re.compile(
    r'(?P<STRING>"[^"]*"|\'[^\']*\')'
    r"|(?P<NUMBER>\d+)"
    r"|(?P<OP>==)"
    r"|(?P<LPAREN>\()"
    r"|(?P<RPAREN>\))"
    r"|(?P<COMMA>,)"
    r"|(?P<NAME>[A-Za-z_][A-Za-z0-9_.\\-]*)"
    r"|(?P<WS>\s+)"
)


class _Token:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: str) -> None:
        self.kind = kind
        self.value = value


def _tokenize(rule: str) -> list[_Token]:
    tokens: list[_Token] = []
    for m in _EVAL_TOKEN_RE.finditer(rule):
        kind = m.lastgroup
        if kind == "WS":
            continue
        value = m.group()
        if kind == "STRING":
            value = value[1:-1]
        elif kind == "NAME" and value in ("and", "or", "not"):
            kind = "KEYWORD"
        if kind is None:
            raise ValueError(f"_tokenize: regex matched but lastgroup is None for {m.group()!r}")
        tokens.append(_Token(kind, value))
    tokens.append(_Token("EOF", ""))
    return tokens


_Verdict = str  # "pass" | "fail" | "deferred"


class GateRuleEvaluator:
    """Recursive-descent evaluator for cross-tier gate rule expressions.

    Implements Kleene three-valued logic with proper short-circuit so a false
    conjunct short-circuits a deferred operand to false (not deferred-poisoning).
    No eval() or exec() is used anywhere.
    """

    def __init__(self, state: PlatformRoadmapState) -> None:
        self._state = state
        self._sorted_ids: list[str] = sorted(state._by_id.keys(), key=len, reverse=True)

    def evaluate(self, rule: str) -> tuple[_Verdict, str]:
        tokens = _tokenize(rule)
        v, r, _ = self._parse_or(tokens, 0)
        return v, r

    def _parse_or(self, tokens: list[_Token], pos: int) -> tuple[_Verdict, str, int]:
        v, r, pos = self._parse_and(tokens, pos)
        while pos < len(tokens) and tokens[pos].kind == "KEYWORD" and tokens[pos].value == "or":
            pos += 1
            v2, r2, pos = self._parse_and(tokens, pos)
            if v == "pass" or v2 == "pass":
                v, r = "pass", (r if v == "pass" else r2)
            elif v == "fail" and v2 == "fail":
                v, r = "fail", f"({r}) or ({r2})"
            else:
                v, r = "deferred", (r if v == "deferred" else r2)
        return v, r, pos

    def _parse_and(self, tokens: list[_Token], pos: int) -> tuple[_Verdict, str, int]:
        v, r, pos = self._parse_not(tokens, pos)
        while pos < len(tokens) and tokens[pos].kind == "KEYWORD" and tokens[pos].value == "and":
            pos += 1
            v2, r2, pos = self._parse_not(tokens, pos)
            if v == "fail" or v2 == "fail":
                v, r = "fail", (r if v == "fail" else r2)
            elif v == "pass" and v2 == "pass":
                v, r = "pass", f"({r}) and ({r2})"
            else:
                v, r = "deferred", (r if v == "deferred" else r2)
        return v, r, pos

    def _parse_not(self, tokens: list[_Token], pos: int) -> tuple[_Verdict, str, int]:
        if pos < len(tokens) and tokens[pos].kind == "KEYWORD" and tokens[pos].value == "not":
            pos += 1
            v, r, pos = self._parse_not(tokens, pos)
            flipped = {"pass": "fail", "fail": "pass", "deferred": "deferred"}
            return flipped.get(v, "deferred"), f"not ({r})", pos
        return self._parse_atom(tokens, pos)

    def _parse_atom(self, tokens: list[_Token], pos: int) -> tuple[_Verdict, str, int]:
        if pos >= len(tokens) or tokens[pos].kind == "EOF":
            return "fail", "empty expression", pos
        tok = tokens[pos]
        if tok.kind == "LPAREN":
            pos += 1
            v, r, pos = self._parse_or(tokens, pos)
            if pos < len(tokens) and tokens[pos].kind == "RPAREN":
                pos += 1
            return v, r, pos
        if tok.kind == "NAME":
            name = tok.value
            if pos + 1 < len(tokens) and tokens[pos + 1].kind == "LPAREN":
                return self._eval_function(tokens, pos)
            pos += 1
            if pos < len(tokens) and tokens[pos].kind == "OP":
                pos += 1
                if pos < len(tokens) and tokens[pos].kind in ("STRING", "NUMBER"):
                    rhs = tokens[pos].value
                    pos += 1
                    v, r = self._eval_field_cmp(name, rhs)
                    return v, r, pos
            return "deferred", f"unresolvable: {name}", pos
        return "fail", f"unexpected token: {tok.value}", pos + 1

    def _eval_function(self, tokens: list[_Token], pos: int) -> tuple[_Verdict, str, int]:
        name = tokens[pos].value
        pos += 2
        args: list[_Token] = []
        while pos < len(tokens) and tokens[pos].kind not in ("RPAREN", "EOF"):
            if tokens[pos].kind == "COMMA":
                pos += 1
                continue
            args.append(tokens[pos])
            pos += 1
        if pos < len(tokens) and tokens[pos].kind == "RPAREN":
            pos += 1

        if name == "tier_complete":
            tier = args[0].value if args else ""
            result = self._state.tier_complete(tier)
            return ("pass" if result else "fail"), f"tier_complete({tier!r}) = {result}", pos

        if name == "all_in_tier_with_status":
            tier = args[0].value if len(args) > 0 else ""
            status = args[1].value if len(args) > 1 else ""
            items = [i for i in self._state._doc.tier_items if i.tier == tier and i.status not in _INACTIVE_FOR_TIER]
            result = bool(items) and all(i.status == status for i in items)
            return ("pass" if result else "fail"), f"all_in_tier_with_status({tier!r}, {status!r}) = {result}", pos

        if name == "grace_period_elapsed":
            item_id = args[0].value if len(args) > 0 else ""
            try:
                days = int(args[1].value) if len(args) > 1 else 0
            except (ValueError, TypeError):
                return "fail", "grace_period_elapsed: invalid days arg", pos
            item = self._state._by_id.get(item_id)
            if item is None:
                return "fail", f"grace_period_elapsed: item {item_id!r} not found", pos
            if item.status != "complete":
                reason = f"grace_period_elapsed({item_id}, {days}): item not complete (status={item.status})"
                return "fail", reason, pos
            if not item.completed_at:
                return "deferred", f"grace_period_elapsed({item_id}, {days}): completed_at unset", pos
            try:
                completed = datetime.strptime(str(item.completed_at), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                elapsed = (datetime.now(timezone.utc) - completed).days
                result = elapsed >= days
                reason = f"grace_period_elapsed({item_id}, {days}): {elapsed}d >= {days}d = {result}"
                return ("pass" if result else "fail"), reason, pos
            except (ValueError, TypeError):
                return "deferred", f"grace_period_elapsed({item_id}, {days}): cannot parse completed_at", pos

        if name == "item_field_eq":
            arg_vals = [a.value for a in args]
            return "deferred", f"item_field_eq({', '.join(arg_vals)}): runtime field (not statically resolvable)", pos

        return "fail", f"unknown helper: {name}", pos

    def _eval_field_cmp(self, field_path: str, rhs: str) -> tuple[_Verdict, str]:
        item_id, field = self._resolve_field_path(field_path)
        if item_id is None or field is None or field == "":
            return "deferred", f"{field_path}: cannot resolve to a known item id and field"
        item = self._state._by_id.get(item_id)
        if item is None:
            return "deferred", f"{field_path}: item {item_id!r} not found"
        if field == "status":
            actual = item.status
            result = actual == rhs
            return ("pass" if result else "fail"), f"{field_path} is {actual!r} (expected {rhs!r})"
        return "deferred", f"{field_path}: field {field!r} is a runtime path (not statically resolvable)"

    def _resolve_field_path(self, path: str) -> tuple[str | None, str | None]:
        """Resolve a dotted field path to (item_id, field) using longest-known-id prefix."""
        for known_id in self._sorted_ids:
            prefix = known_id + "."
            if path.startswith(prefix):
                return known_id, path[len(prefix) :]
            if path == known_id:
                return known_id, ""
        return None, None


class GateRuleParser:
    """Validates gate-rule expressions against the gate_helpers table.

    Tokenises function calls only (name + arity). Never evaluates. Field-path
    resolution is a runtime concern handled by T-1.4.
    """

    _CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")

    @classmethod
    def validate(cls, rule: str, helpers: dict[str, int]) -> None:
        for m in cls._CALL_RE.finditer(rule):
            name = m.group(1)
            if name not in helpers:
                raise ValueError(f"Unknown gate-rule helper '{name}'. Valid: {sorted(helpers)}")
            close = cls._find_close(rule, m.end())
            arity = cls._count_args(rule[m.end() : close])
            if arity != helpers[name]:
                raise ValueError(f"Helper '{name}': expected {helpers[name]} arg(s), got {arity}")

    @staticmethod
    def _find_close(s: str, start: int) -> int:
        depth, i = 1, start
        while i < len(s) and depth:
            if s[i] == "(":
                depth += 1
            elif s[i] == ")":
                depth -= 1
            i += 1
        return i - 1

    @staticmethod
    def _count_args(s: str) -> int:
        s = s.strip()
        if not s:
            return 0
        depth, in_str, str_char, count = 0, False, "", 1
        for ch in s:
            if in_str:
                if ch == str_char:
                    in_str = False
            elif ch in ('"', "'"):
                in_str, str_char = True, ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and not depth:
                count += 1
        return count
