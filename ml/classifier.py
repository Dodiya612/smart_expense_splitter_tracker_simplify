"""Expense category classification model using TF-IDF vectorization and Logistic Regression.

Provides CategoryClassifier with:
- Word and char_wb n-gram feature union
- Regularized Logistic Regression
- Merchant normalization integration
- User history Bayesian probability blending
- Model serialization under 5 MB
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from ml.merchant_normalizer import MerchantNormalizer

if TYPE_CHECKING:
    from ml.history import UserHistoryLayer

# The 12 canonical expense categories defined in ml/LABELLING_GUIDE.md
CATEGORIES: list[str] = [
    "Bills & Utilities",
    "Education",
    "Entertainment",
    "Food & Dining",
    "Gifts & Donations",
    "Groceries",
    "Health",
    "Other",
    "Personal Care",
    "Rent & Housing",
    "Shopping",
    "Travel & Transport",
]


class CategoryClassifier:
    """TF-IDF and Logistic Regression classifier for expense categorization."""

    def __init__(
        self,
        c: float = 5.0,
        random_state: int = 42,
        max_iter: int = 1000,
    ) -> None:
        self.c = c
        self.random_state = random_state
        self.max_iter = max_iter

        # Pipeline: word + character boundary n-grams -> Logistic Regression
        self.pipeline: Pipeline = Pipeline(
            [
                (
                    "features",
                    FeatureUnion(
                        [
                            (
                                "word",
                                TfidfVectorizer(
                                    ngram_range=(1, 2),
                                    sublinear_tf=True,
                                    min_df=1,
                                ),
                            ),
                            (
                                "char",
                                TfidfVectorizer(
                                    ngram_range=(2, 5),
                                    analyzer="char_wb",
                                    sublinear_tf=True,
                                    min_df=1,
                                ),
                            ),
                        ]
                    ),
                ),
                (
                    "clf",
                    LogisticRegression(
                        C=self.c,
                        max_iter=self.max_iter,
                        random_state=self.random_state,
                    ),
                ),
            ]
        )
        self.is_fitted: bool = False

    def _prepare_inputs(
        self,
        descriptions: list[str],
        merchants: list[str | None] | None = None,
    ) -> list[str]:
        """Preprocess descriptions and optional merchants into clean text."""
        if merchants is None:
            merchants = [None] * len(descriptions)

        cleaned_inputs: list[str] = []
        for desc, merch in zip(descriptions, merchants):
            text = MerchantNormalizer.prepare_input(desc or "", merch)
            cleaned_inputs.append(text if text else "other")
        return cleaned_inputs

    def fit(
        self,
        descriptions: list[str],
        categories: list[str],
        merchants: list[str | None] | None = None,
    ) -> CategoryClassifier:
        """Train the classifier pipeline on expense descriptions and categories.

        Args:
            descriptions: List of expense descriptions.
            categories: List of ground-truth category labels.
            merchants: Optional list of merchant names.

        Returns:
            self
        """
        X = self._prepare_inputs(descriptions, merchants)
        self.pipeline.fit(X, categories)
        self.is_fitted = True
        return self

    def predict(
        self,
        descriptions: list[str],
        merchants: list[str | None] | None = None,
    ) -> list[str]:
        """Predict categories for a batch of descriptions.

        Args:
            descriptions: List of expense descriptions.
            merchants: Optional list of merchant names.

        Returns:
            List of predicted category labels.
        """
        if not self.is_fitted:
            raise RuntimeError("Model has not been fitted or loaded yet.")

        X = self._prepare_inputs(descriptions, merchants)
        return list(self.pipeline.predict(X))

    def predict_proba(
        self,
        descriptions: list[str],
        merchants: list[str | None] | None = None,
    ) -> list[dict[str, float]]:
        """Predict class probability distributions for a batch of descriptions.

        Args:
            descriptions: List of expense descriptions.
            merchants: Optional list of merchant names.

        Returns:
            List of dictionaries mapping category names to probability scores.
        """
        if not self.is_fitted:
            raise RuntimeError("Model has not been fitted or loaded yet.")

        X = self._prepare_inputs(descriptions, merchants)
        probs_matrix = self.pipeline.predict_proba(X)
        classes = list(self.pipeline.classes_)

        results: list[dict[str, float]] = []
        for row in probs_matrix:
            row_dict = {cat: float(p) for cat, p in zip(classes, row)}
            results.append(row_dict)
        return results

    def predict_single(
        self,
        description: str,
        merchant: str | None = None,
        user_id: str | None = None,
        history_layer: UserHistoryLayer | None = None,
    ) -> dict[str, Any]:
        """Predict category for a single expense with optional user history blending.

        Args:
            description: Raw description of the expense.
            merchant: Optional raw merchant name.
            user_id: Optional user ID for personalization.
            history_layer: Optional UserHistoryLayer instance.

        Returns:
            Dictionary with category, confidence, probabilities, and normalized fields.
        """
        norm_merchant = MerchantNormalizer.normalize_merchant(merchant)
        cleaned_text = MerchantNormalizer.clean_text(description)

        # Handle empty/uninformative input gracefully
        if not cleaned_text and not norm_merchant:
            uniform_prob = 1.0 / len(CATEGORIES)
            probs = {cat: uniform_prob for cat in CATEGORIES}
            return {
                "category": "Other",
                "confidence": uniform_prob,
                "probabilities": probs,
                "normalized_merchant": norm_merchant,
                "cleaned_text": cleaned_text,
            }

        probs = self.predict_proba([description], [merchant])[0]

        # Apply user history blending if history layer is provided
        if history_layer is not None and user_id is not None:
            top_category, confidence, probs = history_layer.blend_predictions(
                model_probs=probs,
                user_id=user_id,
                merchant=merchant or norm_merchant,
            )
        else:
            top_category = max(probs, key=probs.get)  # type: ignore[arg-type]
            confidence = float(probs[top_category])

        return {
            "category": top_category,
            "confidence": confidence,
            "probabilities": probs,
            "normalized_merchant": norm_merchant,
            "cleaned_text": cleaned_text,
        }

    def save(self, file_path: str | Path) -> None:
        """Serialize the fitted pipeline to disk using joblib compression.

        Args:
            file_path: Destination path for the .joblib artifact.
        """
        if not self.is_fitted:
            raise RuntimeError("Cannot save an unfitted model.")

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, path, compress=3)

    @classmethod
    def load(cls, file_path: str | Path) -> CategoryClassifier:
        """Load a saved pipeline from disk.

        Args:
            file_path: Path to the .joblib artifact.

        Returns:
            Fitted CategoryClassifier instance.
        """
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Model file not found at: {path}")

        instance = cls()
        instance.pipeline = joblib.load(path)
        instance.is_fitted = True
        return instance
