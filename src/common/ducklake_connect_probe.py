"""Phased, bounded connectivity diagnostic for the DuckLake Neon catalog (T2.19 RCA).

probe_connection(dsn, *, data_path, meta_schema, extension_directory, timeout_s) runs four
sequential phases, each with its own bounded timeout. The first to fail short-circuits and the
result names the failing phase. A fully-successful probe returns ok=True, phase_reached="attach".

Phases:
  dns   -- socket.getaddrinfo(host, 5432): classifies DNS-resolution failures.
  tcp   -- socket.create_connection((host, 5432), timeout=timeout_s): classifies TCP-blackhole
           or firewall failures independent of TLS or Postgres auth.
  auth  -- psycopg2.connect(..., connect_timeout=timeout_s, sslmode=require) then close:
           proves credentials + Postgres auth independent of DuckDB.
  attach -- ducklake_runtime.open_connection(...) + SELECT 1: the full in-Lambda DuckDB/DuckLake
            ATTACH. Only reached when DNS + TCP + AUTH all pass.

Result schema:
  {
    "phase_reached": str,   -- last phase that completed (or "none" on immediate dns fail)
    "failed_phase":  str | None,  -- None on full success
    "dns_ms":        float | None,
    "tcp_ms":        float | None,
    "auth_ms":       float | None,
    "attach_ms":     float | None,
    "ok":            bool,
    "error":         str | None,
  }
"""

from __future__ import annotations

import socket
import time
from typing import Any


def probe_connection(
    dsn: dict[str, str],
    *,
    data_path: str,
    meta_schema: str,
    extension_directory: str | None,
    timeout_s: int = 10,
) -> dict[str, Any]:
    """Run the phased connectivity probe against the Neon catalog endpoint.

    Each phase is bounded by *timeout_s*. The probe never hangs: every network call carries an
    explicit timeout. Returns a structured result dict (see module docstring for schema).
    """
    result: dict[str, Any] = {
        "phase_reached": "none",
        "failed_phase": None,
        "dns_ms": None,
        "tcp_ms": None,
        "auth_ms": None,
        "attach_ms": None,
        "ok": False,
        "error": None,
    }

    host = dsn.get("host", "")
    port = 5432

    # -- Phase 1: DNS ----------------------------------------------------------
    t0 = time.perf_counter()
    try:
        socket.getaddrinfo(host, port)
        result["dns_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["phase_reached"] = "dns"
    except Exception as exc:  # noqa: BLE001
        result["dns_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["failed_phase"] = "dns"
        result["error"] = f"DNS: {exc}"
        return result

    # -- Phase 2: TCP ----------------------------------------------------------
    t0 = time.perf_counter()
    try:
        sock = socket.create_connection((host, port), timeout=timeout_s)
        sock.close()
        result["tcp_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["phase_reached"] = "tcp"
    except Exception as exc:  # noqa: BLE001
        result["tcp_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["failed_phase"] = "tcp"
        result["error"] = f"TCP: {exc}"
        return result

    # -- Phase 3: AUTH (psycopg2 only, no DuckDB) ------------------------------
    t0 = time.perf_counter()
    try:
        import psycopg2  # noqa: PLC0415

        conn = psycopg2.connect(
            dbname=dsn["dbname"],
            host=host,
            user=dsn["username"],
            password=dsn["password"],
            sslmode=dsn.get("sslmode") or "require",
            connect_timeout=timeout_s,
        )
        conn.close()
        result["auth_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["phase_reached"] = "auth"
    except Exception as exc:  # noqa: BLE001
        result["auth_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["failed_phase"] = "auth"
        result["error"] = f"AUTH: {exc}"
        return result

    # -- Phase 4: ATTACH (DuckDB + DuckLake) -----------------------------------
    t0 = time.perf_counter()
    try:
        from src.common import ducklake_runtime  # noqa: PLC0415

        con = ducklake_runtime.open_connection(
            dsn=dsn,
            data_path=data_path,
            meta_schema=meta_schema,
            extension_directory=extension_directory,
        )
        try:
            con.execute("SELECT 1")
        finally:
            con.close()
        result["attach_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["phase_reached"] = "attach"
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001
        result["attach_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["failed_phase"] = "attach"
        result["error"] = f"ATTACH: {exc}"

    return result
