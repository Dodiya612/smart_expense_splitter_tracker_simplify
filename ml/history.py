"""User history layer for personalized expense category classification.

Maintains per-user merchant categorization history and blends historical
user category selections with model prediction probabilities using bounded
Bayesian blending:
    alpha = min(0.6, N / (N + 3))
    P_blended(c) = (1 - alpha) * P_model(c) + alpha * P_user(c)
"""

from __future__ import annotations

from collections import defaultdict

from ml.merchant_normalizer import MerchantNormalizer


class UserHistoryLayer:
    """Manages isolated per-user category history and Bayesian probability blending."""

    def __init__(self) -> None:
        # Structure: user_id -> canonical_merchant -> {category: count}
        self._history: dict[str, dict[str, dict[str, int]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(int))
        )

    def record_transaction(
        self,
        user_id: str,
        category: str,
        merchant: str | None = None,
        description: str | None = None,
    ) -> None:
        """Record a confirmed transaction category for a specific user.

        Args:
            user_id: Unique user identifier.
            category: Confirmed category name.
            merchant: Optional raw merchant string.
            description: Optional raw description string (used if merchant is omitted).
        """
        if not user_id or not category:
            return

        key = ""
        if merchant:
            key = MerchantNormalizer.normalize_merchant(merchant)
        elif description:
            # Fall back to cleaned description if no merchant name was explicitly passed
            key = MerchantNormalizer.clean_text(description)

        if not key:
            return

        self._history[str(user_id)][key][str(category)] += 1

    def get_merchant_history(
        self, user_id: str, merchant: str | None
    ) -> dict[str, int]:
        """Retrieve category counts for a user and merchant.

        Args:
            user_id: Unique user identifier.
            merchant: Raw or normalized merchant string.

        Returns:
            Dictionary mapping category names to historical counts.
        """
        if not user_id or not merchant or str(user_id) not in self._history:
            return {}

        norm_merchant = MerchantNormalizer.normalize_merchant(merchant)
        user_data = self._history[str(user_id)]
        if norm_merchant in user_data:
            return dict(user_data[norm_merchant])
        return {}

    def get_user_distribution(
        self, user_id: str, merchant: str | None
    ) -> tuple[dict[str, float], int]:
        """Compute the empirical probability distribution for a user and merchant.

        Args:
            user_id: Unique user identifier.
            merchant: Raw merchant string.

        Returns:
            Tuple of (probability_distribution, total_transactions_count).
        """
        counts = self.get_merchant_history(user_id, merchant)
        total = sum(counts.values())
        if total == 0:
            return {}, 0

        dist = {cat: count / total for cat, count in counts.items()}
        return dist, total

    def blend_predictions(
        self,
        model_probs: dict[str, float],
        user_id: str | None,
        merchant: str | None,
    ) -> tuple[str, float, dict[str, float]]:
        """Blend model probabilities with user historical preferences.

        Uses bounded Bayesian blending:
            alpha = min(0.6, N / (N + 3))
            P_blended(c) = (1 - alpha) * P_model(c) + alpha * P_user(c)

        Args:
            model_probs: Category probabilities from the ML model {category: prob}.
            user_id: Optional unique user identifier.
            merchant: Optional merchant name.

        Returns:
            Tuple of (top_category, top_confidence, blended_probabilities_dict).
        """
        if not model_probs:
            return "Other", 0.0, {}

        # Cold start: if user_id or merchant missing, or no history exists, return model output
        if not user_id or not merchant:
            top_cat = max(model_probs, key=model_probs.get)  # type: ignore[arg-type]
            return top_cat, float(model_probs[top_cat]), dict(model_probs)

        user_dist, n = self.get_user_distribution(user_id, merchant)
        if n == 0 or not user_dist:
            top_cat = max(model_probs, key=model_probs.get)  # type: ignore[arg-type]
            return top_cat, float(model_probs[top_cat]), dict(model_probs)

        # Bounded blending weight alpha
        alpha = min(0.6, n / (n + 3.0))

        blended: dict[str, float] = {}
        all_categories = set(model_probs.keys()) | set(user_dist.keys())

        for cat in all_categories:
            p_model = model_probs.get(cat, 0.0)
            p_user = user_dist.get(cat, 0.0)
            blended[cat] = (1.0 - alpha) * p_model + alpha * p_user

        # Re-normalize to ensure sum is exactly 1.0
        total_p = sum(blended.values())
        if total_p > 0:
            blended = {cat: p / total_p for cat, p in blended.items()}

        top_cat = max(blended, key=blended.get)  # type: ignore[arg-type]
        top_conf = float(blended[top_cat])
        return top_cat, top_conf, blended

    def clear_user(self, user_id: str) -> None:
        """Clear all historical data for a specific user."""
        if str(user_id) in self._history:
            del self._history[str(user_id)]

    def clear_all(self) -> None:
        """Clear all stored history."""
        self._history.clear()
