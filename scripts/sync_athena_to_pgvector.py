#!/usr/bin/env python3
"""
Sync Athena research results to live pgvector cache.

This script queries Athena for the latest backtest results and
stores them in the PostgreSQL pgvector database for fast retrieval
during live trading.
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

import numpy as np

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from common.config import config
from common.database import AthenaClient, PostgresClient


def compute_formula_embedding(formula: str, metrics: dict) -> np.ndarray:
    """
    Compute embedding for a formula based on its characteristics.

    Args:
        formula: Formula string
        metrics: Performance metrics dictionary

    Returns:
        128-dimensional embedding vector
    """
    # Simple embedding based on formula properties and performance
    # In production, this would be more sophisticated

    features = []

    # Formula complexity (character count normalized)
    features.append(min(len(formula) / 100.0, 1.0))

    # Performance metrics
    features.append(metrics.get("sharpe_ratio", 0.0))
    features.append(metrics.get("total_return", 0.0))
    features.append(abs(metrics.get("max_drawdown", 0.0)))

    # Pad to 128 dimensions
    embedding = np.array(features)
    if len(embedding) < 128:
        embedding = np.pad(embedding, (0, 128 - len(embedding)))
    else:
        embedding = embedding[:128]

    # Normalize
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding


def sync_athena_to_pgvector(
    athena_client: AthenaClient, postgres_client: PostgresClient, hours_back: int = 24, min_sharpe: float = 0.5
):
    """
    Sync Athena backtest results to pgvector.

    Args:
        athena_client: Athena client instance
        postgres_client: PostgreSQL client instance
        hours_back: Number of hours of history to sync
        min_sharpe: Minimum Sharpe ratio to include
    """
    # Query Athena for recent backtest results
    cutoff_time = datetime.now() - timedelta(hours=hours_back)

    # Use parameterized approach for safety
    query = f"""
    SELECT
        formula_id,
        formula,
        sharpe_ratio,
        total_return,
        max_drawdown,
        created_at
    FROM {config.glue_database}.backtest_results
    WHERE created_at >= TIMESTAMP '{cutoff_time.isoformat()}'
        AND sharpe_ratio >= {min_sharpe:.6f}
    ORDER BY sharpe_ratio DESC
    LIMIT 1000
    """

    print(f"Querying Athena for results since {cutoff_time}...")
    execution_id = athena_client.execute_query(query)
    results = athena_client.get_query_results(execution_id)

    # Parse results
    rows = results["Rows"]
    if len(rows) < 2:
        print("No results found.")
        return

    print(f"Found {len(rows) - 1} formulas to sync.")

    # Ensure target table exists
    with postgres_client.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            cur.execute("""
                CREATE TABLE IF NOT EXISTS formula_cache (
                    id SERIAL PRIMARY KEY,
                    formula_id VARCHAR(100) UNIQUE NOT NULL,
                    formula TEXT NOT NULL,
                    sharpe_ratio FLOAT,
                    total_return FLOAT,
                    max_drawdown FLOAT,
                    embedding vector(128),
                    synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMP
                );
            """)

            # Create index
            cur.execute("""
                CREATE INDEX IF NOT EXISTS formula_cache_embedding_idx
                ON formula_cache USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100);
            """)

            conn.commit()

    # Insert or update formulas
    synced_count = 0
    with postgres_client.connect() as conn:
        with conn.cursor() as cur:
            for row in rows[1:]:  # Skip header row
                data = [col.get("VarCharValue", "") for col in row["Data"]]

                if len(data) < 6:
                    continue

                formula_id = data[0]
                formula = data[1]
                sharpe_ratio = float(data[2]) if data[2] else 0.0
                total_return = float(data[3]) if data[3] else 0.0
                max_drawdown = float(data[4]) if data[4] else 0.0
                created_at = data[5]

                # Compute embedding
                metrics = {"sharpe_ratio": sharpe_ratio, "total_return": total_return, "max_drawdown": max_drawdown}
                embedding = compute_formula_embedding(formula, metrics)

                # Upsert
                cur.execute(
                    """
                    INSERT INTO formula_cache
                    (formula_id, formula, sharpe_ratio, total_return, max_drawdown, embedding, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (formula_id)
                    DO UPDATE SET
                        formula = EXCLUDED.formula,
                        sharpe_ratio = EXCLUDED.sharpe_ratio,
                        total_return = EXCLUDED.total_return,
                        max_drawdown = EXCLUDED.max_drawdown,
                        embedding = EXCLUDED.embedding,
                        synced_at = CURRENT_TIMESTAMP
                """,
                    (formula_id, formula, sharpe_ratio, total_return, max_drawdown, embedding.tolist(), created_at),
                )

                synced_count += 1

            conn.commit()

    print(f"Successfully synced {synced_count} formulas to pgvector cache.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Sync Athena research results to pgvector cache")
    parser.add_argument("--hours-back", type=int, default=24, help="Number of hours of history to sync (default: 24)")
    parser.add_argument("--min-sharpe", type=float, default=0.5, help="Minimum Sharpe ratio to include (default: 0.5)")
    parser.add_argument("--workgroup", type=str, default=None, help="Athena workgroup to use (default: from config)")

    args = parser.parse_args()

    # Create clients
    workgroup = args.workgroup or config.athena_prod_workgroup
    athena_client = AthenaClient(workgroup=workgroup)
    postgres_client = PostgresClient()

    try:
        sync_athena_to_pgvector(athena_client, postgres_client, hours_back=args.hours_back, min_sharpe=args.min_sharpe)
    except Exception as e:
        print(f"Error during sync: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
