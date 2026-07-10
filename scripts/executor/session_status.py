# complexity-waiver: decision-43
"""Session status dashboard and recommendation eligibility for the executor.

Extracted from scripts/execute_recommendation.py (SLOC decomposition, Decision
102/104 facade mechanism, operator-descoped per the plan's ORCHESTRATOR
RATIFICATION context bullet -- this is a low-risk cluster extraction, not part
of the phase-shatter). print_session_status exceeds CC 20 (branches over the
run-summary aggregation), hence the module-level decision-43 waiver above.

Routed-name references (Path, subprocess, load_all_recommendations) resolve
through the scripts.execute_recommendation facade via a function-local import
so the existing test suite's patches on scripts.execute_recommendation.<name>
keep intercepting with zero migration.
"""

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


def print_session_status(*, root: "Optional[Path]" = None) -> None:
    """Print an aggregated session dashboard from today's run summaries.

    Args:
        root: Repository root directory. Defaults to cwd.
    """
    import scripts.execute_recommendation as _er

    base = root or _er.Path(".")
    today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    run_dir = base / "logs" / "runs"

    # -- (a) Aggregate run summaries for today --
    recs_attempted: set[str] = set()
    recs_closed: set[str] = set()
    recs_failed: set[str] = set()
    first_ts: Optional[datetime] = None

    if run_dir.exists():
        for fpath in sorted(run_dir.glob("*.json")):
            if today_str not in fpath.stem:
                continue
            try:
                data = json.loads(fpath.read_text(encoding="utf-8", errors="replace"))
            except (json.JSONDecodeError, OSError):
                continue
            rid = data.get("rec_id", "")
            recs_attempted.add(rid)
            outcome = data.get("outcome", "")
            if outcome == "success":
                recs_closed.add(rid)
            elif outcome in ("failure", "error"):
                recs_failed.add(rid)
            ts_str = data.get("timestamp_start")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if first_ts is None or ts < first_ts:
                        first_ts = ts
                except ValueError:
                    pass

    # -- (b) Friction recs drafted today --
    friction_count = 0
    recs_jsonl = base / "logs" / ".recommendations-log.jsonl"
    if recs_jsonl.exists():
        for line in recs_jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("source") == "executor-supervision" and entry.get("date", "").replace("-", "") == today_str:
                friction_count += 1

    # -- (c) Hotfix commits today --
    hotfix_count = 0
    try:
        result = _er.subprocess.run(
            [
                "git",
                "--no-pager",
                "log",
                "--oneline",
                "--all",
                "--since=midnight",
                "--grep=hotfix",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if result.returncode == 0:
            hotfix_count = len([ln for ln in result.stdout.splitlines() if ln.strip()])
    except (_er.subprocess.TimeoutExpired, OSError):
        pass

    # -- (d) Machinery failure ratio --
    total_runs = len(recs_attempted) if recs_attempted else 0
    fail_count = len(recs_failed)
    ratio = f"{fail_count}/{total_runs}" if total_runs else "n/a"

    # -- (e) Elapsed time --
    if first_ts is not None:
        now = datetime.now(timezone.utc)
        if first_ts.tzinfo is None:
            first_ts = first_ts.replace(tzinfo=timezone.utc)
        elapsed = now - first_ts
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes = remainder // 60
        elapsed_str = f"{hours}h {minutes}m"
    else:
        elapsed_str = "n/a"

    # -- Print dashboard --
    print("=== Executor Session Status ===")
    print(f"Recs attempted: {total_runs}  closed: {len(recs_closed)}  failed: {fail_count}")
    print(f"Friction recs drafted: {friction_count}")
    print(f"Hotfix commits: {hotfix_count}")
    print(f"Machinery failure ratio: {ratio}")
    print(f"Elapsed since first run: {elapsed_str}")


def is_eligible(rec: dict, recs_by_id: dict[str, dict] | None = None) -> bool:
    """Check if recommendation is eligible for execution.

    Returns True only if risk==low, automatable==True, status is not
    closed/failed/declined, and all dependency IDs resolve to closed entries.
    Missing dependency IDs are treated as unresolved (conservative).
    """
    import scripts.execute_recommendation as _er

    status = rec.get("status", "open")
    if status in ("closed", "failed", "declined"):
        return False
    if not (rec.get("risk") == "low" and rec.get("automatable") is True):
        return False

    # Effort gate: only XS/S recs are eligible for automated execution
    if rec.get("effort", "M") not in ("XS", "S"):
        return False

    # SLOC gate: target files over 800 SLOC exceed the context budget
    target_file = rec.get("file", "")
    if target_file and _er.Path(target_file).exists():
        sloc = sum(1 for line in _er.Path(target_file).read_text(encoding="utf-8").splitlines() if line.strip())
        if sloc > 800:
            return False

    dependencies: list[str] = rec.get("dependencies", [])
    if not dependencies:
        return True

    if recs_by_id is None:
        recs_by_id = _er.load_all_recommendations()

    for dep_id in dependencies:
        dep = recs_by_id.get(dep_id)
        if dep is None or dep.get("status") != "closed":
            return False

    return True
