"""Feature vector representation for ML model input.

Wraps a dict of named features with deterministic ordering for
consistent array output between training and inference.

Usage::

    vec = FeatureVector(
        {"batter_contact_rate": 0.83, "pitcher_k_rate": 0.28},
        feature_order=["batter_contact_rate", "pitcher_k_rate"],
    )
    arr = vec.to_array()   # [0.83, 0.28]
    d = vec.to_dict()      # {"batter_contact_rate": 0.83, ...}
"""

from __future__ import annotations

from typing import Any


class FeatureVector:
    """Immutable, ordered feature vector for ML model input.

    Args:
        features: Dict mapping feature names to numeric values.
        feature_order: Explicit ordering of feature names for
            ``to_array()``. If ``None``, uses sorted key order.
    """

    __slots__ = ("_features", "_order")

    def __init__(
        self,
        features: dict[str, float],
        feature_order: list[str] | None = None,
    ) -> None:
        self._features = dict(features)
        self._order = list(feature_order) if feature_order else sorted(features.keys())

    def to_array(self) -> list[float]:
        """Return features as an ordered numeric list.

        Uses the feature order specified at construction. Missing
        features default to ``0.0``.
        """
        return [self._features.get(k, 0.0) for k in self._order]

    def to_dict(self) -> dict[str, float]:
        """Return the raw feature dict."""
        return dict(self._features)

    @property
    def feature_names(self) -> list[str]:
        """Return the ordered feature names."""
        return list(self._order)

    @property
    def size(self) -> int:
        """Number of features in the ordered vector."""
        return len(self._order)

    def get(self, name: str, default: float = 0.0) -> float:
        """Get a single feature value by name."""
        return self._features.get(name, default)

    def __len__(self) -> int:
        return self.size

    def __repr__(self) -> str:
        return f"FeatureVector({len(self._order)} features)"
