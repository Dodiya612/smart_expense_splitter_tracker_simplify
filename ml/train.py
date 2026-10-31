"""Training script for the Category Classification Model (T-22).

Loads ml/data/categories_train.csv, validates the 12 categories,
performs 5-Fold Stratified Cross-Validation on the training set,
fits the CategoryClassifier pipeline, and saves the compressed model
artifact to ml/models/category_model.joblib (< 5 MB).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import StratifiedKFold

from ml.classifier import CATEGORIES, CategoryClassifier

MAX_MODEL_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB strictly required by T-22

DEFAULT_TRAIN_DATA_PATH = REPO_ROOT / "ml" / "data" / "categories_train.csv"
DEFAULT_MODEL_PATH = REPO_ROOT / "ml" / "models" / "category_model.joblib"


def validate_with_stratified_cv(
    df: pd.DataFrame,
    n_splits: int = 5,
    c: float = 5.0,
) -> float:
    """Perform Stratified K-Fold Cross Validation strictly on training data.

    Eliminates test-set leakage by evaluating hyperparameter configurations
    and feature settings exclusively on the training dataset.

    Args:
        df: Training dataframe containing 'description' and 'category'.
        n_splits: Number of cross-validation folds (default 5).
        c: Regularization parameter for Logistic Regression.

    Returns:
        Mean Macro-F1 score across all validation folds.
    """
    print(f"\n--- Running {n_splits}-Fold Stratified Cross-Validation on Training Data ---")
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)

    descriptions = df["description"].tolist()
    categories = df["category"].tolist()
    y = np.array(categories)

    fold_scores: list[float] = []

    for fold, (train_idx, val_idx) in enumerate(skf.split(descriptions, y), 1):
        tr_desc = [descriptions[i] for i in train_idx]
        tr_cat = [categories[i] for i in train_idx]
        val_desc = [descriptions[i] for i in val_idx]
        val_cat = [categories[i] for i in val_idx]

        fold_clf = CategoryClassifier(c=c, random_state=42, max_iter=1000)
        fold_clf.fit(tr_desc, tr_cat)
        val_preds = fold_clf.predict(val_desc)

        score = float(f1_score(val_cat, val_preds, average="macro"))
        fold_scores.append(score)
        print(f"  Fold {fold}/{n_splits} Macro-F1: {score:.4f}")

    mean_score = float(np.mean(fold_scores))
    std_score = float(np.std(fold_scores))
    print(f"Mean CV Macro-F1: {mean_score:.4f} (+/- {std_score:.4f})")
    return mean_score


def train_category_model(
    train_data_path: str | Path = DEFAULT_TRAIN_DATA_PATH,
    output_model_path: str | Path = DEFAULT_MODEL_PATH,
    run_cv: bool = True,
) -> CategoryClassifier:
    """Train the expense category classification model.

    Args:
        train_data_path: Path to categories_train.csv.
        output_model_path: Destination path for category_model.joblib.
        run_cv: Whether to run Stratified K-Fold CV before final fitting.

    Returns:
        Fitted CategoryClassifier instance.
    """
    data_file = Path(train_data_path)
    if not data_file.is_file():
        raise FileNotFoundError(f"Training data not found at: {data_file}")

    print(f"Loading training data from: {data_file}")
    df = pd.read_csv(data_file)

    # Validate dataset shape and columns
    print(f"Training dataset shape: {df.shape}")
    assert "description" in df.columns and "category" in df.columns, (
        "Dataset must contain 'description' and 'category' columns."
    )

    # Validate all 12 categories are present
    unique_categories = sorted(df["category"].unique())
    print(f"Number of unique categories: {len(unique_categories)}")
    assert len(unique_categories) == 12, (
        f"Expected exactly 12 categories, found {len(unique_categories)}"
    )

    for cat in CATEGORIES:
        count = (df["category"] == cat).sum()
        assert count > 0, f"Category '{cat}' has 0 training rows."

    # Perform reproducible 5-Fold Stratified Cross Validation on training set
    if run_cv:
        validate_with_stratified_cv(df, n_splits=5, c=5.0)

    descriptions = df["description"].tolist()
    categories = df["category"].tolist()

    # Train final CategoryClassifier on full training dataset
    print("\nTraining final CategoryClassifier (TF-IDF + Logistic Regression C=5.0)...")
    clf = CategoryClassifier(c=5.0, random_state=42, max_iter=1000)
    clf.fit(descriptions, categories)

    # Evaluate on training data
    train_preds = clf.predict(descriptions)
    train_acc = accuracy_score(categories, train_preds)
    train_f1 = f1_score(categories, train_preds, average="macro")
    print(f"Training Accuracy: {train_acc * 100:.2f}%")
    print(f"Training Macro-F1: {train_f1:.4f}")

    # Serialize model artifact
    out_path = Path(output_model_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    clf.save(out_path)

    artifact_size = out_path.stat().st_size
    size_mb = artifact_size / (1024 * 1024)
    print(f"Saved model artifact to: {out_path}")
    print(f"Artifact size: {artifact_size} bytes ({size_mb:.2f} MB)")

    # Strict acceptance criteria: must be under 5 MB
    assert artifact_size < MAX_MODEL_SIZE_BYTES, (
        f"Artifact size ({size_mb:.2f} MB) exceeds maximum limit of 5.0 MB!"
    )
    print("Artifact size check: PASSED (< 5 MB)")

    return clf


if __name__ == "__main__":
    train_category_model()
