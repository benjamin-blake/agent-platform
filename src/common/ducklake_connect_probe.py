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

import concurrent.futures
import os
import socket
import time
from typing import Any


def _bounded_getaddrinfo(host: str, port: int, timeout_s: int) -> Any:
    """socket.getaddrinfo with an enforced wall-clock bound.

    The stdlib getaddrinfo has no timeout parameter and relies on the OS resolver, which can
    blackhole-hang. Running it in a worker thread with future.result(timeout=...) caps the DNS
    phase at timeout_s, honouring the "no phase hangs" guarantee (raises TimeoutError on expiry).
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(socket.getaddrinfo, host, port).result(timeout=timeout_s)


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
    explicit timeout (DNS via a bounded worker-thread future; TCP/AUTH via socket/libpq timeouts;
    ATTACH via DUCKLAKE_CONNECT_TIMEOUT_S forwarded from timeout_s). Returns a structured result
    dict (see module docstring for schema).
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

    # -- Phase 1: DNS (bounded by timeout_s via a worker-thread future) ---------
    t0 = time.perf_counter()
    try:
        _bounded_getaddrinfo(host, port, timeout_s)
        result["dns_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        result["phase_reached"] = "dns"
    except Exception as exc:  # noqa: BLE001 -- includes concurrent.futures.TimeoutError on a blackhole resolver
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
    # open_connection builds the libpq conninfo via libpq_conninfo, which reads the
    # DUCKLAKE_CONNECT_TIMEOUT_S env var for the postgres connect_timeout. Forward timeout_s
    # through that env var so the ATTACH phase is bounded by the caller's timeout_s (not a stale
    # default), then restore the prior value.
    from src.common import ducklake_runtime  # noqa: PLC0415

    t0 = time.perf_counter()
    _prev_timeout = os.environ.get("DUCKLAKE_CONNECT_TIMEOUT_S")
    os.environ["DUCKLAKE_CONNECT_TIMEOUT_S"] = str(timeout_s)
    try:
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
    finally:
        if _prev_timeout is None:
            os.environ.pop("DUCKLAKE_CONNECT_TIMEOUT_S", None)
        else:
            os.environ["DUCKLAKE_CONNECT_TIMEOUT_S"] = _prev_timeout

    return result
