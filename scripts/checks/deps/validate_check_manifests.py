"""Class D evaluator for docs/contracts/check-manifest.yaml (Decision 168/169).

Asserts, by AST over all 18 domain manifests (scripts/checks/*/_manifest.py), that every
Entry.module/Entry.attr is a plain ast.Constant str (never an f-string, a computed constant, or a
"module:attr" colon form); that every Entry.module resolves to a real
scripts.dependency_graph node; and that scripts.checks._schema.SEGMENT_TOKENS equals
check-manifest.yaml's declared_segment_tokens (derive-and-assert, so contract and dataclass
cannot drift with both gates green).
"""

from __future__ import annotations

import ast

import yaml

from scripts.checks import _common, registry
from scripts.checks._schema import SEGMENT_TOKENS

_MANIFEST_GLOB = "scripts/checks/*/_manifest.py"


def _entry_calls(tree: ast.Module) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == "Entry") or (
                isinstance(func, ast.Attribute) and func.attr == "Entry"
            ):
                calls.append(node)
    return calls


def _kwarg_value(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _entry_display_name(call: ast.Call) -> str:
    node = _kwarg_value(call, "name")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return "<unnamed>"


@registry.register("validate_check_manifests", owner="platform")
def validate_check_manifests(failed: list[str]) -> None:
    print("\n=== Check-manifest grammar (Decision 168/169, docs/contracts/check-manifest.yaml) ===")
    error_count_before = len(failed)

    # Genuine runtime use (read below), not merely an assignment -- this is what makes this
    # module's {check: validate_check_manifests} evaluator declaration in check-manifest.yaml
    # resolve (executable-context basename match, not a docstring mention). Computed HERE (not a
    # module-level constant) so a patched _common.ROOT is honoured on every call, not just the
    # module's own import time.
    contract_path = _common.ROOT / "docs" / "contracts" / "check-manifest.yaml"

    manifest_paths = sorted(_common.ROOT.glob(_MANIFEST_GLOB))
    if not manifest_paths:
        failed.append("Check-manifest grammar: no scripts/checks/*/_manifest.py files found.")
        return

    # Deferred import: scripts.dependency_graph imports networkx at module scope, and this is the
    # sole place it is used here -- the same pattern validate_import_contracts/
    # validate_dependency_graph_freshness already use.
    from scripts.dependency_graph import build_graph  # noqa: PLC0415

    graph = build_graph(repo_root=_common.ROOT)

    for path in manifest_paths:
        rel = path.relative_to(_common.ROOT).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError) as exc:
            failed.append(f"Check-manifest grammar: {rel}: {exc}")
            continue

        for call in _entry_calls(tree):
            entry_name = _entry_display_name(call)
            for field in ("module", "attr"):
                value_node = _kwarg_value(call, field)
                if value_node is None:
                    failed.append(f"Check-manifest grammar: {rel}: Entry {entry_name!r} is missing `{field}=`.")
                    continue
                if not (isinstance(value_node, ast.Constant) and isinstance(value_node.value, str)):
                    failed.append(
                        f"Check-manifest grammar: {rel}: Entry {entry_name!r}'s `{field}=` is not a bare "
                        "string-literal constant (f-string, computed value, or non-string constant)."
                    )
                    continue
                if field == "module":
                    module_value = value_node.value
                    if ":" in module_value:
                        failed.append(
                            f"Check-manifest grammar: {rel}: Entry {entry_name!r}'s module={module_value!r} uses "
                            "a colon 'module:attr' form -- module and attr must be two separate fields."
                        )
                        continue
                    if module_value not in graph:
                        failed.append(
                            f"Check-manifest grammar: {rel}: Entry {entry_name!r}'s module={module_value!r} does "
                            "not resolve to a real scripts.dependency_graph node."
                        )

    try:
        contract_data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        failed.append(f"Check-manifest grammar: {contract_path}: {exc}")
        contract_data = None

    if isinstance(contract_data, dict):
        declared = contract_data.get("entry_grammar", {}).get("declared_segment_tokens")
        declared_set = set(declared) if isinstance(declared, list) else None
        if declared_set is None:
            failed.append("Check-manifest grammar: check-manifest.yaml is missing entry_grammar.declared_segment_tokens.")
        elif declared_set != SEGMENT_TOKENS:
            failed.append(
                "Check-manifest grammar: scripts.checks._schema.SEGMENT_TOKENS != check-manifest.yaml's "
                f"declared_segment_tokens (symmetric difference: {sorted(declared_set ^ SEGMENT_TOKENS)})."
            )
    else:
        failed.append(f"Check-manifest grammar: {contract_path} did not parse to a YAML mapping.")

    new_failures = len(failed) - error_count_before
    if new_failures == 0:
        print(f"  PASS: {len(manifest_paths)} manifest(s) scanned.")
    else:
        print(f"  FAIL: {new_failures} violation(s).")
