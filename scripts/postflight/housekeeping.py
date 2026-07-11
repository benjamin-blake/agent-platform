"""Session-close housekeeping: telemetry close, log pruning, metrics, log-housekeeping commit/push.

Moved verbatim from scripts/session/postflight.py (SLOC decomposition, PLAN-sloc-session-postflight).
Shared primitives resolve via scripts.postflight._common so the facade's single canonical patch
target still intercepts through these moved bodies.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys

from scripts.postflight import _common


def close_telemetry_session(
    outcome: str,
    files_changed: int = 0,
    lines_added: int = 0,
    lines_removed: int = 0,
) -> None:
    """Finalise the active telemetry session opened by ``--open-session``.

    Reads ``logs/.telemetry-active-session.json`` to retrieve the session_id.
    Calls ``scripts.executor.telemetry.close_session()`` to emit the record,
    then removes the state file.  If the state file is missing a warning is
    logged and the function returns without error so session close is never
    blocked.
    """
    if not _common.TELEMETRY_ACTIVE_SESSION_FILE.exists():
        print(
            f"WARNING: close_telemetry_session: no active session file found "
            f"({_common.TELEMETRY_ACTIVE_SESSION_FILE}). Skipping.",
            file=sys.stderr,
        )
        return

    try:
        state = json.loads(_common.TELEMETRY_ACTIVE_SESSION_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARNING: close_telemetry_session: could not read state file: {exc}",
            file=sys.stderr,
        )
        return

    try:
        from scripts.executor.telemetry import close_session, get_context  # noqa: PLC0415

        ctx = get_context()
        # Restore session_id so close_session emits with the correct ID
        ctx.session_id = state.get("session_id")
        ctx.workflow = state.get("workflow", "manual")
        ctx.branch = state.get("branch", "")
        close_session(
            outcome=outcome,
            files_changed=files_changed,
            lines_added=lines_added,
            lines_removed=lines_removed,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARNING: close_telemetry_session: telemetry.close_session failed: {exc}",
            file=sys.stderr,
        )

    try:
        _common.TELEMETRY_ACTIVE_SESSION_FILE.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001
        print(
            f"WARNING: close_telemetry_session: could not remove state file: {exc}",
            file=sys.stderr,
        )


def _load_max_age_days() -> int:
    """Read telemetry.max_age_days from config/config.yaml.

    Falls back to DEFAULT_MAX_AGE_DAYS when the key is missing or
    the file cannot be parsed.
    """
    config_path = _common.ROOT / "config" / "config.yaml"
    if not config_path.exists():
        return _common.DEFAULT_MAX_AGE_DAYS
    try:
        import yaml  # lazy -- optional dep

        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            telemetry = data.get("telemetry")
            if isinstance(telemetry, dict):
                val = telemetry.get("max_age_days")
                if isinstance(val, int) and val > 0:
                    return val
    except Exception:  # noqa: BLE001
        _common.logger.debug("Could not read config.yaml; using default")
    return _common.DEFAULT_MAX_AGE_DAYS


def prune_telemetry_logs(
    max_age_days: int | None = None,
) -> dict[str, list[str]]:
    """Rotate old JSONL entries from logs/ into logs/archive/.

    Each JSONL file in ``logs/`` that is not in ``_PRUNE_SKIP_NAMES``
    is scanned line-by-line. Lines whose ``"date"`` or ``"timestamp"``
    field is older than *max_age_days* are moved to
    ``logs/archive/{stem}-{today}.jsonl``.

    Returns a dict ``{"pruned": [...], "skipped": [...]}``.
    """
    if max_age_days is None:
        max_age_days = _load_max_age_days()

    today = _dt.date.today()
    cutoff = today - _dt.timedelta(days=max_age_days)
    cutoff_str = cutoff.isoformat()

    result: dict[str, list[str]] = {
        "pruned": [],
        "skipped": [],
    }

    if not _common.LOGS_DIR.is_dir():
        return result

    _common.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    for jsonl_file in sorted(_common.LOGS_DIR.glob("*.jsonl")):
        if jsonl_file.name in _common._PRUNE_SKIP_NAMES:
            result["skipped"].append(jsonl_file.name)
            continue

        try:
            lines = jsonl_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            result["skipped"].append(jsonl_file.name)
            continue

        keep: list[str] = []
        archive: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                keep.append(line)
                continue
            ts = entry.get("date") or entry.get("timestamp", "")
            date_part = str(ts)[:10]
            if len(date_part) == 10 and date_part < cutoff_str:
                archive.append(line)
            else:
                keep.append(line)

        if not archive:
            result["skipped"].append(jsonl_file.name)
            continue

        archive_name = f"{jsonl_file.stem}-{today.isoformat()}.jsonl"
        archive_path = _common.ARCHIVE_DIR / archive_name
        with open(archive_path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(archive) + "\n")

        jsonl_file.write_text(
            "\n".join(keep) + ("\n" if keep else ""),
            encoding="utf-8",
        )
        result["pruned"].append(jsonl_file.name)
        _common.logger.info(
            "Pruned %d entries from %s -> %s",
            len(archive),
            jsonl_file.name,
            archive_name,
        )

    return result


def run_metrics(steps_total: int = 0, steps_friction: int = 0) -> int:
    """Run session_metrics.py, plan_audit.py, and telemetry pruning."""
    metrics_cmd = [_common.PYTHON, "scripts/session/metrics.py"]
    if steps_total or steps_friction:
        metrics_cmd += ["--steps-total", str(steps_total), "--steps-friction", str(steps_friction)]
    metrics_result = _common._run(metrics_cmd)
    audit_result = _common._run([_common.PYTHON, "scripts/roadmap/plan_audit.py"])

    prune_result = prune_telemetry_logs()

    combined = {
        "metrics": metrics_result.stdout.strip(),
        "plan_audit": audit_result.stdout.strip(),
        "metrics_exit_code": metrics_result.returncode,
        "audit_exit_code": audit_result.returncode,
        "telemetry_pruning": prune_result,
    }
    print(json.dumps(combined, indent=2))
    return 0


def _stage_document_derived_tables() -> None:
    """Postflight ETL bypass neutered in Phase 0+1 of ops-decisions-graduation arc."""
    _common.logger.warning("ops_decisions postflight ETL bypass neutered per Phase 0+1 of ops-decisions-graduation arc")


def run_log_housekeeping() -> int:
    """Commit and push uncommitted JSONL log files."""
    logs_dir = _common.ROOT / "logs"
    if not logs_dir.exists():
        print("No logs/ directory found.")
        return 0

    status_result = _common._run(["git", "status", "--porcelain", "logs/"])
    if not status_result.stdout.strip():
        print("No uncommitted log files found.")
        return 0

    uncommitted_logs = [
        line.split()[-1]
        for line in status_result.stdout.splitlines()
        if line.strip() and line.strip().split()[-1].endswith(".jsonl")
    ]

    if not uncommitted_logs:
        print("No uncommitted JSONL files in logs/.")
        return 0

    add_result = _common._run(["git", "add"] + uncommitted_logs)
    if add_result.returncode != 0:
        print(f"git add failed: {add_result.stderr}", file=sys.stderr)
        return 1

    commit_result = _common._run(["git", "commit", "-m", "chore: session log updates"])
    if commit_result.returncode != 0:
        print(f"Commit failed: {commit_result.stdout}", file=sys.stderr)
        return 1

    push_result = _common._run(["git", "push"])
    if push_result.returncode != 0:
        print(f"Push failed: {push_result.stderr}", file=sys.stderr)
        return 1

    print(f"Committed and pushed {len(uncommitted_logs)} log file(s).")
    return 0
