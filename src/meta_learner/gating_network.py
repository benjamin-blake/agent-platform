"""Gating network for model selection in the trading system."""

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim


@dataclass
class ModelPerformance:
    """Track individual model performance."""

    model_id: str
    predictions: List[float]
    outcomes: List[float]
    recent_sharpe: float = 0.0
    recent_accuracy: float = 0.0
    weight: float = 0.0


class GatingNetwork(nn.Module):
    """Neural network for learning optimal model weights."""

    def __init__(self, input_dim: int, num_models: int, hidden_dim: int = 64):
        """
        Initialize gating network.

        Args:
            input_dim: Dimension of input features
            num_models: Number of models to gate
            hidden_dim: Hidden layer dimension
        """
        super().__init__()

        self.network = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden_dim, num_models),
            nn.Softmax(dim=-1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass - compute model weights.

        Args:
            x: Input features [batch_size, input_dim]

        Returns:
            Model weights [batch_size, num_models]
        """
        return self.network(x)


class MetaLearner:
    """Meta-learner for adaptive model selection and weighting."""

    def __init__(self, num_models: int, feature_dim: int, learning_rate: float = 0.001, use_gating: bool = True):
        """
        Initialize meta-learner.

        Args:
            num_models: Number of base models
            feature_dim: Dimension of market features
            learning_rate: Learning rate for gating network
            use_gating: Whether to use neural gating or simple weighting
        """
        self.num_models = num_models
        self.feature_dim = feature_dim
        self.use_gating = use_gating

        # Model performance tracking
        self.model_performances: Dict[str, ModelPerformance] = {}

        # Gating network
        if use_gating:
            self.gating_network = GatingNetwork(feature_dim, num_models)
            self.optimizer = optim.Adam(self.gating_network.parameters(), lr=learning_rate)
            self.criterion = nn.MSELoss()
        else:
            self.gating_network = None

        # Simple weighting fallback
        self.model_weights = np.ones(num_models) / num_models

    def register_model(self, model_id: str):
        """Register a base model for tracking."""
        if model_id not in self.model_performances:
            self.model_performances[model_id] = ModelPerformance(
                model_id=model_id, predictions=[], outcomes=[], weight=1.0 / self.num_models
            )

    def compute_model_weights(self, features: np.ndarray, model_predictions: List[float]) -> np.ndarray:
        """
        Compute optimal weights for model predictions.

        Args:
            features: Current market features
            model_predictions: Predictions from each base model

        Returns:
            Array of model weights
        """
        if self.use_gating and self.gating_network is not None:
            # Use neural gating network
            self.gating_network.eval()
            with torch.no_grad():
                features_tensor = torch.FloatTensor(features).unsqueeze(0)
                weights = self.gating_network(features_tensor).squeeze(0).numpy()
            self.gating_network.train()
        else:
            # Use simple performance-based weighting
            weights = self.model_weights.copy()

        return weights

    def combine_predictions(self, features: np.ndarray, model_predictions: Dict[str, float]) -> Tuple[float, Dict[str, float]]:
        """
        Combine model predictions using learned weights.

        Args:
            features: Current market features
            model_predictions: Dictionary of {model_id: prediction}

        Returns:
            Tuple of (combined_prediction, model_weights_dict)
        """
        # Ensure all models are registered
        for model_id in model_predictions.keys():
            self.register_model(model_id)

        # Get predictions in consistent order
        model_ids = sorted(model_predictions.keys())
        predictions = np.array([model_predictions[mid] for mid in model_ids])

        # Compute weights
        weights = self.compute_model_weights(features, predictions)

        # Combine predictions
        combined = np.dot(weights, predictions)

        # Return weights as dictionary
        weight_dict = {mid: w for mid, w in zip(model_ids, weights)}

        return combined, weight_dict

    def update(self, features: np.ndarray, model_predictions: Dict[str, float], actual_outcome: float):
        """
        Update meta-learner with observed outcome.

        Args:
            features: Market features used for prediction
            model_predictions: Model predictions
            actual_outcome: Actual observed outcome
        """
        # Update performance tracking
        for model_id, prediction in model_predictions.items():
            if model_id in self.model_performances:
                perf = self.model_performances[model_id]
                perf.predictions.append(prediction)
                perf.outcomes.append(actual_outcome)

                # Keep only recent history (last 100 predictions)
                if len(perf.predictions) > 100:
                    perf.predictions = perf.predictions[-100:]
                    perf.outcomes = perf.outcomes[-100:]

                # Update recent metrics
                if len(perf.predictions) >= 10:
                    errors = np.array(perf.predictions) - np.array(perf.outcomes)
                    perf.recent_accuracy = 1.0 - np.mean(np.abs(errors))

                    if np.std(errors) > 0:
                        perf.recent_sharpe = np.mean(errors) / np.std(errors)

        # Update gating network if enabled
        if self.use_gating and self.gating_network is not None:
            self._train_gating_network(features, model_predictions, actual_outcome)
        else:
            self._update_simple_weights()

    def _train_gating_network(self, features: np.ndarray, model_predictions: Dict[str, float], actual_outcome: float):
        """Train gating network on observed outcome."""
        # Prepare data
        model_ids = sorted(model_predictions.keys())
        predictions = torch.FloatTensor([model_predictions[mid] for mid in model_ids])
        features_tensor = torch.FloatTensor(features).unsqueeze(0)
        target = torch.FloatTensor([actual_outcome])

        # Forward pass
        weights = self.gating_network(features_tensor).squeeze(0)
        combined_pred = torch.dot(weights, predictions)

        # Compute loss
        loss = self.criterion(combined_pred.unsqueeze(0), target)

        # Backward pass
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

    def _update_simple_weights(self):
        """Update simple performance-based weights."""
        if not self.model_performances:
            return

        # Compute weights based on recent Sharpe ratios
        model_ids = sorted(self.model_performances.keys())
        sharpes = np.array([self.model_performances[mid].recent_sharpe for mid in model_ids])

        # Normalize to positive weights
        sharpes = sharpes - np.min(sharpes) + 0.1
        weights = sharpes / np.sum(sharpes)

        self.model_weights = weights

    def get_model_performances(self) -> Dict[str, Dict[str, float]]:
        """Get performance metrics for all models."""
        return {
            model_id: {
                "recent_sharpe": perf.recent_sharpe,
                "recent_accuracy": perf.recent_accuracy,
                "weight": perf.weight,
                "num_predictions": len(perf.predictions),
            }
            for model_id, perf in self.model_performances.items()
        }


class AdaptiveEnsemble:
    """Adaptive ensemble combining multiple models with meta-learning."""

    # Default empty context for predictions
    DEFAULT_MEMORY_CONTEXT = []

    def __init__(self, models: List[Any], feature_dim: int, use_gating: bool = True):
        """
        Initialize adaptive ensemble.

        Args:
            models: List of base models (must have predict method)
            feature_dim: Dimension of input features
            use_gating: Whether to use neural gating network
        """
        self.models = models
        self.meta_learner = MetaLearner(num_models=len(models), feature_dim=feature_dim, use_gating=use_gating)

        # Register all models
        for model in models:
            model_id = getattr(model, "model_id", str(id(model)))
            self.meta_learner.register_model(model_id)

    def predict(self, features: Dict[str, float]) -> Tuple[float, Dict[str, Any]]:
        """
        Make prediction using adaptive ensemble.

        Args:
            features: Market features

        Returns:
            Tuple of (prediction, metadata)
        """
        # Get predictions from all models
        model_predictions = {}
        for model in self.models:
            model_id = getattr(model, "model_id", str(id(model)))
            # Most models should have a predict method
            if hasattr(model, "predict"):
                pred = model.predict(features, self.DEFAULT_MEMORY_CONTEXT)
                model_predictions[model_id] = pred

        # Convert features to array
        feature_array = np.array(list(features.values()))

        # Combine predictions
        combined_pred, weights = self.meta_learner.combine_predictions(feature_array, model_predictions)

        metadata = {"individual_predictions": model_predictions, "model_weights": weights, "num_models": len(self.models)}

        return combined_pred, metadata

    def update(self, features: Dict[str, float], prediction: float, actual_outcome: float):
        """
        Update ensemble with observed outcome.

        Args:
            features: Features used for prediction
            prediction: Ensemble prediction made
            actual_outcome: Actual observed outcome
        """
        # Get individual model predictions
        model_predictions = {}
        for model in self.models:
            model_id = getattr(model, "model_id", str(id(model)))
            if hasattr(model, "predict"):
                pred = model.predict(features, self.DEFAULT_MEMORY_CONTEXT)
                model_predictions[model_id] = pred

        # Update meta-learner
        feature_array = np.array(list(features.values()))
        self.meta_learner.update(feature_array, model_predictions, actual_outcome)
