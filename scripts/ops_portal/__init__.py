"""Implementation package backing the scripts.ops_data_portal facade.

Each module owns one concern of the ops-data write gateway (CI-RCA schema, CI-RCA
runtime, DuckLake writer transport, risk scoring, write-time validators, local
read-cache refresh, decisions CRUD, maintenance verbs, and the CLI). The facade at
scripts/ops_data_portal.py stays the sole public entry point (Decision 84/69, 124).
"""

from __future__ import annotations
