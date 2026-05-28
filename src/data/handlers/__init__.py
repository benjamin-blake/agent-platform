"""Lambda handlers for the Step Functions data pipeline.

Each handler corresponds to a state in the state machine:
    1. fetch_handler — fetches raw OHLCV from yfinance → staging S3
    2. feature_handler — computes features from staged raw data → staging S3
    3. write_handler — writes enriched data to Iceberg table
    4. maintenance_handler — OPTIMIZE (BIN_PACK) + VACUUM on Iceberg tables
    5. discovery_handler — triggers PySR formula discovery
"""
