"""RAT (Retrieval-Augmented Trading) ensemble using pgvector for market memory."""

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
import psycopg2

from ..common.database import PostgresClient


@dataclass
class MarketState:
    """Market state representation."""

    timestamp: str
    symbol: str
    features: Dict[str, float]
    embedding: np.ndarray


class VectorMemory:
    """Vector memory storage using pgvector."""

    def __init__(self, client: PostgresClient = None):
        """Initialize vector memory."""
        self.client = client or PostgresClient()
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure required tables and extensions exist."""
        with self.client.connect() as conn:
            with conn.cursor() as cur:
                # Create market memory table
                # Note: pgvector extension not available in local dev
                # For production, uncomment: cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
                try:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS market_memory (
                            id SERIAL PRIMARY KEY,
                            timestamp TIMESTAMP NOT NULL,
                            symbol VARCHAR(20) NOT NULL,
                            features JSONB,
                            embedding BYTEA,
                            signal FLOAT,
                            outcome FLOAT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                except Exception as e:
                    print(f"[WARNING] Could not create market_memory table: {e}")

    def store_memory(self, state: MarketState, signal: float, outcome: float = None):
        """Store market state and trading outcome in memory."""
        with self.client.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO market_memory
                    (timestamp, symbol, features, embedding, signal, outcome)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """,
                    (
                        state.timestamp,
                        state.symbol,
                        psycopg2.extras.Json(state.features),
                        state.embedding.tolist(),
                        signal,
                        outcome,
                    ),
                )
                conn.commit()

    def retrieve_similar(self, query_embedding: np.ndarray, top_k: int = 10, symbol: str = None) -> List[Dict[str, Any]]:
        """Retrieve similar market states from memory (mock version without pgvector)."""
        # For local dev without pgvector, return empty or mock data
        # In production with pgvector: would do similarity search
        return []  # Mock: no similar memories yet


class RATModel:
    """Base model for RAT ensemble."""

    def __init__(self, model_id: str):
        """Initialize RAT model."""
        self.model_id = model_id

    def predict(self, features: Dict[str, float], memory_context: List[Dict]) -> float:
        """Predict signal given features and memory context."""
        raise NotImplementedError

    def compute_embedding(self, features: Dict[str, float]) -> np.ndarray:
        """Compute embedding for features."""
        # Simple embedding - in production use learned embeddings
        feature_values = np.array(list(features.values()))
        # Pad or truncate to 128 dimensions
        if len(feature_values) < 128:
            embedding = np.pad(feature_values, (0, 128 - len(feature_values)))
        else:
            embedding = feature_values[:128]
        return embedding / (np.linalg.norm(embedding) + 1e-9)


class MomentumRATModel(RATModel):
    """Momentum-based RAT model."""

    def __init__(self):
        """Initialize momentum model."""
        super().__init__("momentum_rat")

    def predict(self, features: Dict[str, float], memory_context: List[Dict]) -> float:
        """Predict based on momentum and similar past outcomes."""
        # Base signal from current momentum
        momentum = features.get("momentum", 0.0)

        # Adjust based on similar historical outcomes
        if memory_context:
            similar_outcomes = [m["outcome"] for m in memory_context if m["outcome"] is not None]
            if similar_outcomes:
                np.mean(similar_outcomes)
                # Weight by similarity
                weights = [m["similarity"] for m in memory_context if m["outcome"] is not None]
                if weights:
                    weighted_outcome = np.average(similar_outcomes, weights=weights)
                    momentum = 0.7 * momentum + 0.3 * weighted_outcome

        return np.tanh(momentum)


class MeanReversionRATModel(RATModel):
    """Mean reversion RAT model."""

    def __init__(self):
        """Initialize mean reversion model."""
        super().__init__("mean_reversion_rat")

    def predict(self, features: Dict[str, float], memory_context: List[Dict]) -> float:
        """Predict based on mean reversion and similar past outcomes."""
        # Base signal from price deviation
        price_deviation = features.get("price_deviation", 0.0)

        # Adjust based on memory
        if memory_context:
            similar_signals = [m["signal"] for m in memory_context]
            if similar_signals:
                weights = [m["similarity"] for m in memory_context]
                weighted_signal = np.average(similar_signals, weights=weights)
                price_deviation = 0.6 * price_deviation + 0.4 * weighted_signal

        return -np.tanh(price_deviation)  # Negative for mean reversion


class RATEnsemble:
    """Ensemble of RAT models with retrieval-augmented predictions."""

    def __init__(self, memory: VectorMemory = None):
        """Initialize RAT ensemble."""
        self.memory = memory or VectorMemory()
        self.models = [MomentumRATModel(), MeanReversionRATModel()]

    def predict(self, features: Dict[str, float], symbol: str, top_k: int = 10) -> Tuple[float, Dict[str, Any]]:
        """
        Make ensemble prediction with memory retrieval.

        Args:
            features: Current market features
            symbol: Trading symbol
            top_k: Number of similar memories to retrieve

        Returns:
            Tuple of (ensemble signal, metadata)
        """
        # Compute embedding for current state
        embedding = self.models[0].compute_embedding(features)

        # Retrieve similar historical states
        memory_context = self.memory.retrieve_similar(embedding, top_k=top_k, symbol=symbol)

        # Get predictions from each model
        predictions = []
        for model in self.models:
            pred = model.predict(features, memory_context)
            predictions.append(pred)

        # Ensemble via simple averaging (could be more sophisticated)
        ensemble_signal = np.mean(predictions)

        metadata = {
            "individual_predictions": {m.model_id: p for m, p in zip(self.models, predictions)},
            "num_similar_memories": len(memory_context),
            "avg_similarity": np.mean([m["similarity"] for m in memory_context]) if memory_context else 0.0,
        }

        return ensemble_signal, metadata

    def store_outcome(self, state: MarketState, signal: float, outcome: float):
        """Store trading outcome in memory for future retrieval."""
        self.memory.store_memory(state, signal, outcome)
