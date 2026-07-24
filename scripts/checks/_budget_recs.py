"""Fast-tier budget-breach / budget-bypass recommendation-filing helpers.

Decision 128 decomposition: extracted from scripts/checks/_scaffolding.py, which sat at 485/500
SLOC and would have breached the 500-line budget once the VTS-20 dedupe (below) was added --
decompose-don't-raise, not a config/sloc_budgets.yaml raise. _scaffolding.py re-exports both
public names as a facade (Decision 80/104/124 pattern) so `patch("validate._file_budget_breach_rec")`
/ `patch("validate._file_budget_bypass_rec")` and `from scripts.checks._scaffolding import
_file_budget_breach_rec` keep resolving unchanged; scripts/validate.py's own facade re-export of
those two names (sourced from _scaffolding) is likewise untouched.

VTS-20 (audit validate-test-suite-4df4d48): a repeated fast-tier budget breach on the same
(branch, dominant_phase) now UPDATES the existing open budget_breach rec instead of filing a
duplicate. The dedupe lookup reads the open_recs reader boundary
(src.common.iceberg_reader.make_reader -- Decision 84 warehouse-SoT), never
logs/.recommendations-log.jsonl (a read cache is never a write source). A reader failure
loud-warns and falls through to filing a new rec -- the breach itself is always recorded; only
the dedupe is best-effort (Decision 55: no silent skip). Decision 142 is the closest prior art
for a non-LLM, reader-verb-based update-instead-of-insert dedupe.
"""

from __future__ import annotations

import os
import sys

from scripts.checks import _common


def _fetch_open_recs(profile: str | None = None) -> list[dict]:
    """Fetch all open recs from the DuckLake reader (live, never the local JSONL cache).

    Mirrors the established open_recs reader-boundary precedent (scripts.convergence_health.
    escalate._fetch_open_recs, scripts.preflight.recs_cache._derive_open_recs's server-side
    counterpart) -- the named verb returns every open rec; callers filter client-side.
    """
    from src.common.iceberg_reader import make_reader  # noqa: PLC0415

    return make_reader(profile=profile).named("open_recs") or []


def _find_open_budget_breach_rec(open_recs: list[dict], branch: str, dedup_phase: str) -> dict | None:
    """Return the open budget_breach rec matching (branch, dedup_phase), or None (VTS-20).

    Matches on the same context substrings _file_budget_breach_rec writes into a fresh rec
    ("Branch: {branch}." / "Dominant phase: {dedup_phase}."), so a rec filed before this dedupe
    landed still matches correctly on its next repeat breach.
    """
    branch_marker = f"Branch: {branch}."
    phase_marker = f"Dominant phase: {dedup_phase}."
    for rec in open_recs:
        if rec.get("source") != "budget_breach" or rec.get("status") != "open":
            continue
        context = rec.get("context") or ""
        if branch_marker in context and phase_marker in context:
            return rec
    return None


def _file_budget_breach_rec(elapsed_s: float, diff_manifest: list[str], dominant_phase: str | None) -> None:
    elapsed_min = elapsed_s / 60
    manifest_summary = ", ".join(diff_manifest[:20]) + ("..." if len(diff_manifest) > 20 else "")

    if os.environ.get("CI") == "true":
        # CI-guard (Decision 84 I-4): the pr-validate CI job installs requirements-fast.txt (no
        # python-ulid) and has no AWS credentials, so file_rec's portal write can never complete
        # there -- it previously raised a swallowed ModuleNotFoundError inside the bare except
        # below. Skip the write (and the VTS-20 dedupe reader lookup, which needs the same
        # credentials) and print the full diagnostic LOUDLY instead: this is a no-op-plus
        # -loud-log, never a silent `if CI: return` (Decision 55) and never a buffered/replayed
        # outbox entry (Decision 84 I-4 -- nothing is staged for later delivery).
        message = (
            f"WARNING: fast-tier budget breach ({elapsed_min:.1f}m, limit 5m): dominant_phase="
            f"{dominant_phase or 'unknown'}, diff ({len(diff_manifest)} files): {manifest_summary}. Rec NOT filed (CI)."
        )
        print(message, file=sys.stderr)
        # CI-native diagnosability (no portal, no outbox -- Decision 84 I-4): mirror to the job's
        # step summary; falls back to the stderr print above if unset.
        if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(f"\n## Fast-tier budget breach\n\n{message}\n")
        return

    try:
        from scripts.ops_data_portal import file_rec, update_rec  # noqa: PLC0415

        branch_r = _common.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT
        )
        branch = branch_r.stdout.strip() or "unknown"
        dedup_phase = dominant_phase or "unknown"
        context = (
            f"Fast-tier budget breach: {elapsed_min:.1f} min elapsed (limit 5 min). "
            f"Branch: {branch}. Dominant phase: {dedup_phase}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}. "
            f"Investigate which check caused the overrun and move it to the full tier or optimise it."
        )
        title = f"Fast-tier budget breach ({elapsed_min:.1f} min) on {branch}"

        # VTS-20 dedupe: look up an existing open budget_breach rec for (branch, dedup_phase) via
        # the open_recs reader boundary -- never logs/.recommendations-log.jsonl. A reader
        # exception here degrades to "no match" (loud warning, fall through to file_rec below) --
        # it must never crash the breach-recording path itself.
        existing = None
        try:
            from scripts.aws_profile import resolve_aws_profile  # noqa: PLC0415

            profile = resolve_aws_profile(default="agent_platform")
            existing = _find_open_budget_breach_rec(_fetch_open_recs(profile=profile), branch, dedup_phase)
        except Exception as reader_exc:  # noqa: BLE001
            print(
                f"WARNING: budget-breach dedupe lookup failed (filing a new rec instead): {reader_exc}",
                file=sys.stderr,
            )
            existing = None

        if existing is not None:
            update_rec(existing["id"], {"title": title, "context": context})
            return

        file_rec(
            {
                "title": title,
                "file": "scripts/validate.py",
                "status": "open",
                "source": "budget_breach",
                "effort": "S",
                "priority": "Medium",
                "context": context,
                "acceptance": "bin/venv-python -m scripts.validate --pre",
                "risk": "low",
                "automatable": False,
            }
        )
    except Exception:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        print(
            f"WARNING: budget breach rec filing failed (NOT filed; no outbox -- re-file manually): {traceback.format_exc()}",
            file=sys.stderr,
        )


def _file_budget_bypass_rec(elapsed_s: float | None, diff_manifest: list[str], reason: str | None) -> None:
    manifest_summary = ", ".join(diff_manifest[:20]) + ("..." if len(diff_manifest) > 20 else "")
    elapsed_part = f"{elapsed_s / 60:.1f} min" if elapsed_s is not None else "unknown"

    if os.environ.get("CI") == "true":
        # Defensive-only: validate.py's CI guard already hard-rejects --ignore-budget when
        # CI=="true" before this helper can be reached in the integrated flow. Kept for parity
        # with _file_budget_breach_rec and to cover any direct/test invocation (Decision 55: no
        # silent skip, never a buffered outbox -- Decision 84 I-4).
        print(
            f"WARNING: fast-tier budget bypass rec NOT filed (CI environment, no portal access): "
            f"Elapsed: {elapsed_part}. Reason: {reason or 'none provided'}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}.",
            file=sys.stderr,
        )
        return

    try:
        from scripts.ops_data_portal import file_rec  # noqa: PLC0415

        branch_r = _common.run(
            ["git", "branch", "--show-current"], capture_output=True, text=True, encoding="utf-8", cwd=_common.ROOT
        )
        branch = branch_r.stdout.strip() or "unknown"
        context = (
            f"Fast-tier budget assertion bypassed via --ignore-budget on branch {branch}. "
            f"Elapsed: {elapsed_part}. Reason: {reason or 'none provided'}. "
            f"Diff manifest ({len(diff_manifest)} files): {manifest_summary}. "
            f"Repeated bypass (>= 3 in 7 days) triggers a soft alert in session_preflight."
        )
        file_rec(
            {
                "title": f"Fast-tier budget bypassed on {branch}",
                "file": "scripts/validate.py",
                "status": "open",
                "source": "budget_bypass",
                "effort": "S",
                "priority": "Low",
                "context": context,
                "acceptance": "bin/venv-python -m scripts.validate --pre",
                "risk": "low",
                "automatable": False,
            }
        )
    except Exception:  # noqa: BLE001
        import traceback  # noqa: PLC0415

        print(
            f"WARNING: budget bypass rec filing failed (NOT filed; no outbox -- re-file manually): {traceback.format_exc()}",
            file=sys.stderr,
        )
