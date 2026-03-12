"""Training metadata storage.

Records training run metadata alongside model artifacts for
reproducibility and registry integration.

Usage::

    meta = TrainingMetadata(
        model_id="mlb_pa_model_v1",
        sport="mlb",
        model_type="plate_appearance",
    )
    meta.record_split(train_count=12000, test_count=3000)
    meta.record_metrics({"accuracy": 0.61, "log_loss": 0.94})
    meta.save("models/mlb/metadata/mlb_pa_model_v1.json")
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TrainingMetadata:
    """Collect and persist training run metadata."""

    def __init__(
        self,
        model_id: str,
        sport: str,
        model_type: str,
        *,
        feature_config: str = "",
        random_state: int = 42,
    ) -> None:
        self._data: dict[str, Any] = {
            "model_id": model_id,
            "sport": sport,
            "model_type": model_type,
            "feature_config": feature_config,
            "random_state": random_state,
            "training_row_count": 0,
            "train_split": 0.0,
            "test_split": 0.0,
            "artifact_path": "",
            "metrics": {},
            "created_at": datetime.now(UTC).isoformat(),
        }

    def record_split(
        self,
        train_count: int,
        test_count: int,
        train_split: float = 0.8,
        test_split: float = 0.2,
    ) -> None:
        """Record train/test split information."""
        self._data["training_row_count"] = train_count + test_count
        self._data["train_split"] = train_split
        self._data["test_split"] = test_split

    def record_metrics(self, metrics: dict[str, Any]) -> None:
        """Record evaluation metrics."""
        self._data["metrics"] = metrics

    def record_artifact(self, path: str) -> None:
        """Record the path to the saved model artifact."""
        self._data["artifact_path"] = path

    def to_dict(self) -> dict[str, Any]:
        """Return metadata as a plain dict."""
        return dict(self._data)

    def save(self, path: str | Path) -> Path:
        """Write metadata JSON to disk.

        Creates parent directories if needed.

        Returns:
            Path to the saved metadata file.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w") as f:
            json.dump(self._data, f, indent=2)
        logger.info("training_metadata_saved", extra={"path": str(p)})
        return p

    @classmethod
    def load(cls, path: str | Path) -> TrainingMetadata:
        """Load metadata from a JSON file."""
        with open(path) as f:
            data = json.load(f)
        meta = cls(
            model_id=data.get("model_id", ""),
            sport=data.get("sport", ""),
            model_type=data.get("model_type", ""),
            feature_config=data.get("feature_config", ""),
            random_state=data.get("random_state", 42),
        )
        meta._data = data
        return meta
