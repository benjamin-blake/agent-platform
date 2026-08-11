"""Contract tests REPLACING the retired tests/test_checks_registry.py::TestFacadeCompleteness
reachability suite (Decision 169, amends Decision 104): manifest<->@register bijection against an
INDEPENDENT oracle, no duplicate names across manifests, no cross-package manifest entry, the
all_checks() eager-population contract (TestBijection); the driver->check graph edges the
manifests produce (TestGraphEdges, VP step 5); and CAP=35 survival of the registry/manifest driver
tests under a synthetic diff (TestAffectedSetSurvival, VP step 6).
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import scripts.checks._common as _common
import scripts.checks.registry as registry
from scripts.checks.deps.affected_tests import CAP, derive_affected_tests
from scripts.dependency_graph import build_graph

_CHECKS_DIR = _common.ROOT / "scripts" / "checks"


def _call_registers_name(call: ast.Call) -> str | None:
    """Mirrors scripts/checks/contracts/_population.py::_call_registers_name's idiom: a
    @register(...)/@registry.register(...) decorator call, first positional arg or name= kwarg a
    string constant."""
    func = call.func
    is_register = (isinstance(func, ast.Attribute) and func.attr == "register") or (
        isinstance(func, ast.Name) and func.id == "register"
    )
    if not is_register:
        return None
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    for kw in call.keywords:
        if kw.arg == "name" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            return kw.value.value
    return None


def _registered_names_via_ast(checks_dir: Path) -> dict[str, Path]:
    """Independent oracle: a FILESYSTEM + AST walk over scripts/checks/**/*.py collecting
    @register(...) call sites -- NEVER an import of any check module (which would make a
    registered-but-unmanifested check invisible to its own guard, the exact vacuous-pass CIRCULARITY
    this test exists to avoid; see the module docstring of scripts/checks/contracts/_population.py's
    _find_check_module for the same idiom applied to one name at a time)."""
    found: dict[str, Path] = {}
    for py_path in sorted(checks_dir.rglob("*.py")):
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"), filename=str(py_path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for deco in node.decorator_list:
                    if isinstance(deco, ast.Call):
                        name = _call_registers_name(deco)
                        if name is not None:
                            found[name] = py_path
    return found


class TestBijection:
    """Every @register'd check name has exactly one manifest Entry and vice versa; no name in two
    manifests; no manifest names a module outside its own domain package."""

    def test_registered_names_equal_manifest_names(self) -> None:
        registered = set(_registered_names_via_ast(_CHECKS_DIR))
        manifested = set(registry._ALL_ENTRIES)
        assert registered == manifested, (
            f"registered-but-unmanifested: {sorted(registered - manifested)}; "
            f"manifested-but-unregistered: {sorted(manifested - registered)}"
        )

    def test_no_duplicate_names_across_manifests(self) -> None:
        """registry._ALL_ENTRIES is itself built as {entry.name: entry, ...} from a flat tuple --
        a dict comprehension silently drops an earlier duplicate. Re-derive from the RAW tuples to
        catch a cross-manifest duplicate a dict-based comparison alone would hide."""
        from scripts.checks.ci_guards._manifest import ENTRIES as ci_guards
        from scripts.checks.contracts._manifest import ENTRIES as contracts
        from scripts.checks.decisions._manifest import ENTRIES as decisions
        from scripts.checks.deps._manifest import ENTRIES as deps
        from scripts.checks.executor._manifest import ENTRIES as executor
        from scripts.checks.hygiene._manifest import ENTRIES as hygiene
        from scripts.checks.iam_tf._manifest import ENTRIES as iam_tf
        from scripts.checks.lambda_pkg._manifest import ENTRIES as lambda_pkg
        from scripts.checks.misc._manifest import ENTRIES as misc
        from scripts.checks.ops_governance._manifest import ENTRIES as ops_governance
        from scripts.checks.product._manifest import ENTRIES as product
        from scripts.checks.prompts._manifest import ENTRIES as prompts
        from scripts.checks.prose._manifest import ENTRIES as prose
        from scripts.checks.roadmap._manifest import ENTRIES as roadmap
        from scripts.checks.sloc._manifest import ENTRIES as sloc
        from scripts.checks.structural._manifest import ENTRIES as structural
        from scripts.checks.typing._manifest import ENTRIES as typing
        from scripts.checks.verification._manifest import ENTRIES as verification

        all_entries = (
            *ci_guards,
            *contracts,
            *decisions,
            *deps,
            *executor,
            *hygiene,
            *iam_tf,
            *lambda_pkg,
            *misc,
            *ops_governance,
            *product,
            *prompts,
            *prose,
            *roadmap,
            *sloc,
            *structural,
            *typing,
            *verification,
        )
        names = [entry.name for entry in all_entries]
        assert len(names) == len(set(names)), f"duplicate manifest names: {sorted({n for n in names if names.count(n) > 1})}"

    def test_no_manifest_names_a_module_outside_its_own_package(self) -> None:
        for entry in registry._ALL_ENTRIES.values():
            parts = entry.module.split(".")
            assert parts[:2] == ["scripts", "checks"], entry
            domain_dir = _CHECKS_DIR / parts[2]
            assert domain_dir.is_dir(), f"{entry.name}: module {entry.module!r} names a domain directory that doesn't exist"

    def test_exactly_one_declared_unsequenced_entry(self) -> None:
        unsequenced = [e for e in registry._ALL_ENTRIES.values() if not e.pre and e.full_segment is None]
        assert [e.name for e in unsequenced] == ["validate_terraform_try"]


class TestAllChecksEagerPopulationIsComplete:
    def test_all_checks_equals_the_union_of_manifest_declared_names_without_importing_validate(self) -> None:
        import sys

        assert "scripts.validate" not in sys.modules, "scripts.validate must not already be imported for this assertion"
        checks = registry.all_checks()
        assert "scripts.validate" not in sys.modules, "all_checks() must not import scripts.validate"
        assert set(checks) == set(registry._ALL_ENTRIES)


class TestGraphEdges:
    """The driver->check graph edges the manifests produce equal the set of declared Entry.module
    values -- a genuine differential: Entry.module is read at RUNTIME by importing each manifest
    (never by AST, which would make both sides the same literals and be unable to fail), compared
    against the graph's actual successors after excluding the known infrastructure edge to
    scripts.checks._schema BY NAME."""

    def test_manifest_successor_edges_match_runtime_entry_modules(self) -> None:
        graph = build_graph(repo_root=_common.ROOT)
        manifest_modules = sorted(
            p.relative_to(_common.ROOT).with_suffix("").as_posix().replace("/", ".")
            for p in (_CHECKS_DIR).glob("*/_manifest.py")
        )
        assert manifest_modules, "no _manifest.py files found"

        for manifest_mod_name in manifest_modules:
            module = importlib.import_module(manifest_mod_name)
            entry_modules = {entry.module for entry in module.ENTRIES}

            assert manifest_mod_name in graph, f"{manifest_mod_name} is not a graph node"
            successors = set(graph.successors(manifest_mod_name)) - {"scripts.checks._schema"}
            assert successors == entry_modules, (
                f"{manifest_mod_name}: graph successors != runtime Entry.module values -- "
                f"symmetric difference: {sorted(successors ^ entry_modules)}"
            )


class TestAffectedSetSurvival:
    """The driver edge survives CAP=35 truncation, with truncation asserted to have actually
    occurred (VP step 6). The synthetic diff is ~20 CHECK modules (never manifests, never files
    whose mirror tests already sit adjacent to the registry tests), so the 4-hop transitive
    driver edge (changed check -> its domain _manifest.py -> registry.py -> a test importing
    registry) is genuinely exercised rather than selected directly."""

    _SYNTHETIC_CHECK_MODULES: tuple[str, ...] = (
        "scripts/checks/sloc/cc_limits.py",
        "scripts/checks/sloc/sloc_limits.py",
        "scripts/checks/sloc/complexity.py",
        "scripts/checks/misc/validate_invariants.py",
        "scripts/checks/misc/validate_ghas_probe.py",
        "scripts/checks/hygiene/validate_sys_executable.py",
        "scripts/checks/hygiene/validate_prose_allowlist.py",
        "scripts/checks/ci_guards/validate_ci_workflow_guards.py",
        "scripts/checks/roadmap/validate_platform_roadmap.py",
        "scripts/checks/roadmap/validate_tier_floor.py",
        "scripts/checks/iam_tf/validate_authority_budget.py",
        "scripts/checks/iam_tf/validate_boundary_attached.py",
        "scripts/checks/lambda_pkg/validate_lambda_manifests.py",
        "scripts/checks/verification/validate_verification_registry.py",
        "scripts/checks/typing/mypy_baseline.py",
        "scripts/checks/deps/validate_requirements.py",
        "scripts/checks/decisions/validate_decisions_size.py",
        "scripts/checks/structural/size_limits.py",
        "scripts/checks/prose/prose_limits.py",
        "scripts/checks/executor/validate_executor_boundary.py",
    )

    def test_driver_tests_survive_the_cap(self) -> None:
        entries = [("M", p) for p in self._SYNTHETIC_CHECK_MODULES]
        result = derive_affected_tests(entries, repo_root=_common.ROOT)
        manifest = result["manifest"]

        assert manifest["cap"] == CAP
        assert manifest["capped"] is True, "the synthetic diff did not actually breach the cap -- test premise invalid"

        driver_tests = {
            "tests/checks/registry/test_resolution.py",
            "tests/checks/registry/test_manifest_contracts.py",
            "tests/checks/registry/test_sequences.py",
            "tests/checks/registry/test_check_metadata.py",
        }
        selected = set(result["selected"])
        missing = driver_tests - selected
        assert not missing, f"driver test(s) not selected at all: {sorted(missing)}"
        deferred = driver_tests & set(manifest["deferred"])
        assert not deferred, f"driver test(s) dropped by the cap: {sorted(deferred)}"
