"""Evaluation script for Category Classification Model (T-22).

Evaluates the trained CategoryClassifier and KeywordRuleBaseline against the
frozen held-out dataset (evals/categories/heldout.csv).
Outputs:
- Top-1 and Top-3 accuracy
- Macro-F1 score
- Per-class precision, recall, and F1
- Confusion matrix
- Model artifact file size verification (< 5 MB)
- Baseline vs ML comparison table
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
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    top_k_accuracy_score,
)

from ml.classifier import CATEGORIES, CategoryClassifier
from ml.fallback_rules import KeywordRuleBaseline

MAX_MODEL_SIZE_BYTES = 5 * 1024 * 1024

DEFAULT_HELDOUT_DATA_PATH = REPO_ROOT / "evals" / "categories" / "heldout.csv"
DEFAULT_MODEL_PATH = REPO_ROOT / "ml" / "models" / "category_model.joblib"


def evaluate_models(
    heldout_data_path: str | Path = DEFAULT_HELDOUT_DATA_PATH,
    model_path: str | Path = DEFAULT_MODEL_PATH,
) -> dict[str, float]:
    """Run full evaluation on heldout dataset.

    Args:
        heldout_data_path: Path to evals/categories/heldout.csv.
        model_path: Path to serialized category_model.joblib.

    Returns:
        Dictionary of summary metric scores.
    """
    heldout_file = Path(heldout_data_path)
    if not heldout_file.is_file():
        raise FileNotFoundError(f"Heldout dataset not found at: {heldout_file}")

    print("=" * 70)
    print("EVALUATION ON DEVELOPMENT HELDOUT DATASET (evals/categories/heldout.csv)")
    print("Note: Development-informed evaluation; not an independent unexposed test set.")
    print(f"Path: {heldout_file}")
    print("=" * 70)

    df_test = pd.read_csv(heldout_file)
    print(f"Total heldout samples: {len(df_test)}")
    assert len(df_test) == 300, f"Expected exactly 300 rows, got {len(df_test)}"

    y_true = df_test["category"].tolist()
    descriptions = df_test["description"].tolist()

    # 1. Evaluate Keyword Rule Baseline
    print("\n--- 1. KEYWORD RULE BASELINE EVALUATION ---")
    baseline_preds = [KeywordRuleBaseline.predict(d) for d in descriptions]
    baseline_acc = float(np.mean([p == t for p, t in zip(baseline_preds, y_true)]))
    baseline_f1 = float(f1_score(y_true, baseline_preds, average="macro"))
    print(f"Baseline Accuracy: {baseline_acc * 100:.2f}%")
    print(f"Baseline Macro-F1: {baseline_f1:.4f}")

    # 2. Evaluate ML Category Classifier
    print("\n--- 2. ML CATEGORY CLASSIFIER EVALUATION ---")
    model_file = Path(model_path)
    if not model_file.is_file():
        print(f"Model file {model_file} not found. Running training first...")
        from ml.train import train_category_model

        train_category_model(output_model_path=model_file)

    clf = CategoryClassifier.load(model_file)
    ml_preds = clf.predict(descriptions)
    ml_probs_list = clf.predict_proba(descriptions)

    # Convert probs to array for top-k accuracy
    classes = list(clf.pipeline.classes_)
    probs_matrix = np.array(
        [[prob_dict[c] for c in classes] for prob_dict in ml_probs_list]
    )

    ml_acc = float(top_k_accuracy_score(y_true, probs_matrix, k=1, labels=classes))
    ml_top3_acc = float(top_k_accuracy_score(y_true, probs_matrix, k=3, labels=classes))
    ml_f1 = float(f1_score(y_true, ml_preds, average="macro"))

    print(f"ML Top-1 Accuracy: {ml_acc * 100:.2f}%")
    print(f"ML Top-3 Accuracy: {ml_top3_acc * 100:.2f}%")
    print(f"ML Macro-F1:       {ml_f1:.4f}")

    # 3. Model Artifact Size
    artifact_size = model_file.stat().st_size
    size_mb = artifact_size / (1024 * 1024)
    print(f"\nModel Artifact File: {model_file}")
    print(f"Artifact Size:       {artifact_size} bytes ({size_mb:.2f} MB)")
    assert artifact_size < MAX_MODEL_SIZE_BYTES, "Model exceeds 5 MB limit!"
    print("Artifact Size Check: PASSED (< 5 MB)")

    # 4. Detailed Classification Report
    print("\n--- DETAILED CLASSIFICATION REPORT (ML MODEL) ---")
    report = classification_report(y_true, ml_preds, digits=4)
    print(report)

    # 5. Confusion Matrix
    print("\n--- CONFUSION MATRIX ---")
    cm = confusion_matrix(y_true, ml_preds, labels=CATEGORIES)
    cm_df = pd.DataFrame(cm, index=CATEGORIES, columns=CATEGORIES)
    print(cm_df.to_string())

    # 6. Side-by-Side Comparison
    print("\n" + "=" * 70)
    print("MODEL COMPARISON SUMMARY")
    print("=" * 70)
    print(f"{'Metric':<25} {'Keyword Baseline':<20} {'ML Model':<20} {'Delta':<10}")
    print("-" * 70)
    print(
        f"{'Accuracy':<25} {baseline_acc * 100:>18.2f}% {ml_acc * 100:>18.2f}% {((ml_acc - baseline_acc) * 100):>+9.2f}%"
    )
    print(
        f"{'Macro-F1':<25} {baseline_f1:>19.4f} {ml_f1:>19.4f} {(ml_f1 - baseline_f1):>+10.4f}"
    )
    print(f"{'Top-3 Accuracy':<25} {'N/A':>19} {ml_top3_acc * 100:>18.2f}% {'N/A':>10}")
    print(f"{'Model Size':<25} {'0 MB (Rules)':>19} {f'{size_mb:.2f} MB':>19} {'< 5 MB':>10}")
    print("=" * 70)

    return {
        "baseline_accuracy": baseline_acc,
        "baseline_macro_f1": baseline_f1,
        "ml_accuracy": ml_acc,
        "ml_top3_accuracy": ml_top3_acc,
        "ml_macro_f1": ml_f1,
        "artifact_size_bytes": artifact_size,
    }


if __name__ == "__main__":
    evaluate_models()
