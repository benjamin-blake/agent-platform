"""Deterministic gate analysis for CI-RCA evidence bundles.

AST-walks scripts/validate.py to produce tier_membership: {func_name: [tier, ...]}.
Handles four control-flow cases per INTENT-ci-rca-methodology Section 3.2 step 3.
Provides runtime probe (N=5, drop-extremes) and earliest_viable_gate decision tree.

AST_WALKER_VERSION is pinned by tests/test_ci_rca_evidence_ast.py.
"""

import ast
import logging
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
AST_WALKER_VERSION = 1
_FAST_TIER_BUDGET_SECONDS = 300

_KNOWN_EXTERNAL_DEP_CHECKS: frozenset[str] = frozenset(
    {
        "validate_iam_runner_policy",
        "validate_copilot_multipliers",
        "validate_outbox_staleness",
        "validate_warehouse_write_sources",
        "validate_dq_manifest_gate",
        "validate_test_coverage",
        "ensure_fresh_dq_results",
    }
)


def _get_call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return f"{func.value.id}.{func.attr}"
    return None


def _is_exit_or_return(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Return):
        return True
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
        name = _get_call_name(stmt.value)
        if name in ("sys.exit", "exit"):
            return True
    return False


def _collect_validate_calls_stopping_at_exit(stmts: list) -> list[str]:
    """Collect validate_* call names, halting at first sys.exit or return statement."""
    calls: list[str] = []
    for stmt in stmts:
        if _is_exit_or_return(stmt):
            break
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            name = _get_call_name(stmt.value)
            if name and name.startswith("validate_"):
                calls.append(name)
        if isinstance(stmt, ast.If):
            calls.extend(_collect_validate_calls_stopping_at_exit(stmt.body))
            calls.extend(_collect_validate_calls_stopping_at_exit(stmt.orelse))
    return calls


def _collect_all_validate_calls(func_def: ast.FunctionDef) -> list[str]:
    """Collect all validate_* calls within a function definition (no exit guard)."""
    calls: list[str] = []
    for node in ast.walk(func_def):
        if isinstance(node, ast.Call):
            name = _get_call_name(node)
            if name and name.startswith("validate_"):
                calls.append(name)
    return calls


def _build_tier_membership_from_registry() -> dict[str, list[str]]:
    """Build tier_membership from scripts.checks.registry (Decision 104).

    The live scripts/validate.py is a thin CLI whose dispatch is registry-driven, not the
    literal validate_X() call lists / if args.pre: blocks the AST walker below was designed
    to parse -- so tier membership for the LIVE file is sourced from the registry directly.
    """
    from scripts.checks import registry  # noqa: PLC0415

    membership: dict[str, set[str]] = {}
    for step in registry.pre_sequence():
        if step.kind == "check":
            membership.setdefault(step.name, set()).add("pre")
    for step in registry.full_sequence():
        if step.kind == "check":
            membership.setdefault(step.name, set()).add("presubmit")
    return {fn: sorted(tiers) for fn, tiers in membership.items()}


def _is_live_validate_path(vpath: Path, real_validate_path: Path) -> bool:
    """True if vpath resolves to the live repo's scripts/validate.py (not a synthetic/historical copy)."""
    try:
        return Path(vpath).resolve() == real_validate_path.resolve()
    except OSError:
        return False


def build_tier_membership(validate_path: Path | None = None) -> dict[str, list[str]] | None:
    """Build tier_membership via AST walk of validate.py, or via the registry for the live file.

    Returns dict mapping func_name -> sorted list of tiers, or None on parse failure.
    Handles: (a) direct --pre calls, (b) aggregator indirection, (c) sys.exit short-circuits,
    (d) duplicate registration -> ["pre", "presubmit"].

    Decision 104: when `validate_path` resolves to the live repo's scripts/validate.py (the
    default, and what ci_rca_evidence.py's --validate-path defaults to), tier membership is
    sourced from scripts.checks.registry instead -- the live file no longer contains the literal
    call-list structure this AST walker parses. Synthetic/historical validate.py snapshots
    (as used by this module's own test suite) still go through the AST walker unchanged.
    """
    real_validate_path = ROOT / "scripts" / "validate.py"
    vpath = validate_path or real_validate_path
    if _is_live_validate_path(vpath, real_validate_path):
        return _build_tier_membership_from_registry()
    try:
        source = Path(vpath).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(vpath))
    except (OSError, SyntaxError) as exc:
        logger.error("AST parse failure on %s: %s", vpath, exc)
        return None

    func_defs: dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_defs[node.name] = node  # type: ignore[assignment]

    aggregator_calls: dict[str, list[str]] = {}
    for agg in ("run_python_checks", "run_terraform_checks"):
        if agg in func_defs:
            aggregator_calls[agg] = _collect_all_validate_calls(func_defs[agg])

    main_def = func_defs.get("main")
    if main_def is None:
        logger.error("No main() in %s", vpath)
        return None

    pre_calls: list[str] = []
    presubmit_calls: list[str] = []

    for stmt in ast.walk(main_def):
        if not isinstance(stmt, ast.If):
            continue
        test = stmt.test
        is_pre = (
            isinstance(test, ast.Attribute)
            and isinstance(test.value, ast.Name)
            and test.value.id == "args"
            and test.attr == "pre"
        )
        if is_pre:
            pre_calls.extend(_collect_validate_calls_stopping_at_exit(stmt.body))

    for node in ast.walk(main_def):
        if not isinstance(node, ast.Call):
            continue
        name = _get_call_name(node)
        if name in aggregator_calls:
            presubmit_calls.extend(aggregator_calls[name])
        elif name and name.startswith("validate_") and name not in pre_calls:
            presubmit_calls.append(name)

    membership: dict[str, set[str]] = {}
    for fn in pre_calls:
        membership.setdefault(fn, set()).add("pre")
    for fn in presubmit_calls:
        membership.setdefault(fn, set()).add("presubmit")

    return {fn: sorted(tiers) for fn, tiers in membership.items()}


def probe_runtime(
    check_name: str,
    validate_path: Path | None = None,
) -> tuple[str, float | None]:
    """Time check_name over N=5 invocations; drop extremes; return (confidence_str, median_sec).

    Returns (error_str, None) on probe failure or dispersion > 50%.
    """
    vpath = str(validate_path or (ROOT / "scripts" / "validate.py"))
    probe_code = (
        f"import importlib.util, sys, time\n"
        f"spec = importlib.util.spec_from_file_location('validate', {vpath!r})\n"
        f"mod = importlib.util.module_from_spec(spec)\n"
        f"spec.loader.exec_module(mod)\n"
        f"fn = getattr(mod, {check_name!r}, None)\n"
        f"if fn is None: sys.exit(1)\n"
        f"failed = []\n"
        f"t0 = time.monotonic()\n"
        f"fn(failed)\n"
        f"print(f'{{time.monotonic() - t0:.6f}}')\n"
    )

    samples: list[float] = []
    for _ in range(5):
        try:
            r = subprocess.run(
                [sys.executable, "-c", probe_code],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                cwd=str(ROOT),
            )
            if r.returncode == 0 and r.stdout.strip():
                samples.append(float(r.stdout.strip()))
            else:
                return (f"probe_failed: non-zero exit or empty stdout for {check_name}", None)
        except Exception as exc:
            return (f"probe_failed: {exc}", None)

    raw = sorted(samples)
    trimmed = raw[1:4]
    median = sorted(trimmed)[1]

    if median == 0:
        return ("probe_failed: zero median", None)

    dispersion = max(abs(s - median) / median for s in trimmed)
    disp_pct = int(dispersion * 100)
    raw_ms = [f"{s * 1000:.0f}ms" for s in samples]
    conf = f"median={median * 1000:.0f}ms n=5 trimmed_n=3 raw=[{', '.join(raw_ms)}] dispersion={disp_pct}%"

    if dispersion > 0.50:
        return (f"dispersion_too_high: {conf}", None)

    return (conf, median)


def compute_earliest_viable_gate(
    check_name: str,
    tier_membership: dict[str, list[str]] | None,
    runtime_confidence: str | None,
    median_seconds: float | None,
    current_pre_runtime: float = 0.0,
) -> tuple[str, str]:
    """Compute earliest_viable_gate. Returns (gate_or_None, rationale_str).

    Decision tree per INTENT-ci-rca-methodology Section 3.2 step 4.
    """
    if check_name in _KNOWN_EXTERNAL_DEP_CHECKS:
        return ("presubmit", f"{check_name} has external AWS/network deps; --pre is offline-tolerant (Decision 60).")

    if tier_membership is None:
        return ("undetermined", "AST parse failure on validate.py; tier_membership unavailable.")

    tiers = tier_membership.get(check_name, [])
    if "pre" in tiers:
        return ("pre", f"{check_name} already in --pre tier (tier_membership={tiers!r}).")

    if not tiers:
        return ("presubmit", f"{check_name} not found in tier_membership; defaulting to presubmit.")

    if median_seconds is None:
        if runtime_confidence and (
            runtime_confidence.startswith("dispersion_too_high") or runtime_confidence.startswith("probe_failed")
        ):
            return ("undetermined", f"Runtime probe inconclusive: {runtime_confidence}.")
        return ("undetermined", "Runtime probe result unavailable.")

    headroom = _FAST_TIER_BUDGET_SECONDS - current_pre_runtime
    if median_seconds <= headroom:
        return (
            "pre",
            (
                f"{check_name} in presubmit only. Runtime: median {median_seconds * 1000:.0f}ms. "
                f"--pre runtime: {current_pre_runtime:.1f}s. "
                f"Budget={_FAST_TIER_BUDGET_SECONDS}s; headroom={headroom:.1f}s. Recommend promotion to --pre."
            ),
        )

    return (
        "presubmit",
        f"{check_name} median {median_seconds * 1000:.0f}ms exceeds --pre headroom ({headroom:.1f}s). Stay presubmit.",
    )
