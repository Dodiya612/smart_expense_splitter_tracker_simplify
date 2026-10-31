"""Unit tests for T-22 Category Classification Model.

Tests:
1. Merchant Normalization (casing, whitespace, punctuation, prefixes, currency, Indian context).
2. Category Classifier (prediction, confidence, probability distribution, handling unknown/empty).
3. User History Layer (cold start, user isolation, bounded Bayesian blending, clear operations).
4. Model Artifact Size (< 5 MB requirement).
5. Keyword Rule Baseline (predict valid categories, deterministic heuristics).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

# Ensure repo root is in sys.path regardless of current working directory
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from ml.classifier import CATEGORIES, CategoryClassifier
from ml.fallback_rules import KeywordRuleBaseline
from ml.history import UserHistoryLayer
from ml.merchant_normalizer import MerchantNormalizer

MODEL_PATH = REPO_ROOT / "ml" / "models" / "category_model.joblib"


class TestMerchantNormalizer:
    """Test suite for MerchantNormalizer component."""

    def test_casing_and_whitespace(self) -> None:
        assert MerchantNormalizer.normalize_merchant("  SWIGGY  ") == "swiggy"
        assert MerchantNormalizer.normalize_merchant("uber   india") == "uber"
        assert MerchantNormalizer.normalize_merchant("NETFLIX") == "netflix"

    def test_punctuation_and_entity_suffixes(self) -> None:
        assert MerchantNormalizer.normalize_merchant("Zomato Ltd.") == "zomato"
        assert MerchantNormalizer.normalize_merchant("BigBasket Pvt Ltd") == "bigbasket"
        assert MerchantNormalizer.normalize_merchant("D-Mart") == "dmart"

    def test_service_level_distinctions(self) -> None:
        # Swiggy vs Swiggy Instamart
        assert MerchantNormalizer.normalize_merchant("Swiggy") == "swiggy"
        assert (
            MerchantNormalizer.normalize_merchant("Swiggy Instamart")
            == "swiggy instamart"
        )

        # Amazon vs Amazon Prime vs Amazon Gift Card
        assert MerchantNormalizer.normalize_merchant("AMZN MKTPLACE") == "amazon"
        assert (
            MerchantNormalizer.normalize_merchant("Amazon Prime Video")
            == "amazon prime"
        )
        assert (
            MerchantNormalizer.normalize_merchant("Amazon Gift Card")
            == "amazon gift card"
        )

        # Urban Company: Salon vs Cleaning
        assert (
            MerchantNormalizer.normalize_merchant("Urban Company Salon")
            == "urban company salon"
        )
        assert (
            MerchantNormalizer.normalize_merchant("Urban Company Cleaning")
            == "urban company cleaning"
        )

    def test_indian_context_merchants(self) -> None:
        assert MerchantNormalizer.normalize_merchant("Blinkit Grocery") == "blinkit"
        assert MerchantNormalizer.normalize_merchant("Zepto Now") == "zepto"
        assert MerchantNormalizer.normalize_merchant("Ola Cabs") == "ola"
        assert MerchantNormalizer.normalize_merchant("Rapido Bike") == "rapido"
        assert (
            MerchantNormalizer.normalize_merchant("Apollo Pharmacy")
            == "apollo pharmacy"
        )
        assert MerchantNormalizer.normalize_merchant("Disney+ Hotstar") == "hotstar"
        assert MerchantNormalizer.normalize_merchant("Reliance Fresh") == "reliance fresh"

    def test_clean_text_strips_transaction_noise(self) -> None:
        # UPI prefix
        assert "swiggy" in MerchantNormalizer.clean_text("upi/swiggyorder")

        # Payment prefixes
        assert MerchantNormalizer.clean_text("Paid to Starbucks") == "starbucks"
        assert MerchantNormalizer.clean_text("Payment for grocery") == "grocery"
        assert MerchantNormalizer.clean_text("TXN Uber Auto") == "uber auto"

        # Currency amounts
        assert MerchantNormalizer.clean_text("Dominos Rs. 450") == "dominos"
        assert MerchantNormalizer.clean_text("Dinner 250/-") == "dinner"
        assert MerchantNormalizer.clean_text("IRCTC ticket - rs 1200") == "irctc ticket"
        assert MerchantNormalizer.clean_text("Petrol INR 500") == "petrol"

    def test_prepare_input(self) -> None:
        res = MerchantNormalizer.prepare_input("lunch with team", "Swiggy")
        assert "lunch with team" in res
        assert "swiggy" in res


class TestUserHistoryLayer:
    """Test suite for UserHistoryLayer personalization."""

    def test_cold_start(self) -> None:
        layer = UserHistoryLayer()
        model_probs = {"Food & Dining": 0.8, "Groceries": 0.2}

        # Cold start returns model top category without alteration
        top_cat, conf, blended = layer.blend_predictions(
            model_probs=model_probs,
            user_id="user_new",
            merchant="Swiggy",
        )
        assert top_cat == "Food & Dining"
        assert conf == pytest.approx(0.8)
        assert blended["Food & Dining"] == pytest.approx(0.8)

    def test_user_isolation(self) -> None:
        layer = UserHistoryLayer()
        model_probs = {"Food & Dining": 0.6, "Groceries": 0.4}

        # User 1 always tags Swiggy as Groceries
        for _ in range(5):
            layer.record_transaction("user_1", "Groceries", merchant="Swiggy")

        # User 1 should get Groceries
        u1_cat, _, _ = layer.blend_predictions(model_probs, "user_1", "Swiggy")
        assert u1_cat == "Groceries"

        # User 2 has no history, should still get Food & Dining
        u2_cat, _, _ = layer.blend_predictions(model_probs, "user_2", "Swiggy")
        assert u2_cat == "Food & Dining"

    def test_bounded_bayesian_blending(self) -> None:
        layer = UserHistoryLayer()
        model_probs = {
            "Shopping": 0.7,
            "Gifts & Donations": 0.3,
        }

        # After 1 transaction: alpha = min(0.6, 1 / (1 + 3)) = 0.25
        layer.record_transaction("user_a", "Gifts & Donations", merchant="Amazon")
        _, _, b1 = layer.blend_predictions(model_probs, "user_a", "Amazon")
        # Gifts & Donations: (1 - 0.25)*0.3 + 0.25*1.0 = 0.225 + 0.25 = 0.475
        assert b1["Gifts & Donations"] == pytest.approx(0.475, rel=1e-2)

        # After 10 transactions: alpha = min(0.6, 10/13) = 0.6 (capped at 0.6)
        for _ in range(9):
            layer.record_transaction("user_a", "Gifts & Donations", merchant="Amazon")
        top_cat, conf, b10 = layer.blend_predictions(model_probs, "user_a", "Amazon")
        assert top_cat == "Gifts & Donations"
        assert conf > 0.0
        # Sum of probabilities must always be 1.0
        assert sum(b10.values()) == pytest.approx(1.0)

    def test_clear_operations(self) -> None:
        layer = UserHistoryLayer()
        layer.record_transaction("user_x", "Education", merchant="Coursera")
        assert len(layer.get_merchant_history("user_x", "Coursera")) == 1

        layer.clear_user("user_x")
        assert len(layer.get_merchant_history("user_x", "Coursera")) == 0


class TestCategoryClassifier:
    """Test suite for CategoryClassifier."""

    @pytest.fixture(scope="module")
    def trained_classifier(self) -> CategoryClassifier:
        model_path = MODEL_PATH
        if not model_path.is_file():
            from ml.train import train_category_model

            return train_category_model(output_model_path=model_path)
        return CategoryClassifier.load(model_path)

    def test_all_12_categories_present(self) -> None:
        assert len(CATEGORIES) == 12
        assert "Food & Dining" in CATEGORIES
        assert "Groceries" in CATEGORIES
        assert "Travel & Transport" in CATEGORIES
        assert "Bills & Utilities" in CATEGORIES
        assert "Rent & Housing" in CATEGORIES
        assert "Entertainment" in CATEGORIES
        assert "Health" in CATEGORIES
        assert "Education" in CATEGORIES
        assert "Personal Care" in CATEGORIES
        assert "Gifts & Donations" in CATEGORIES
        assert "Shopping" in CATEGORIES
        assert "Other" in CATEGORIES

    def test_predict_single_structure(
        self, trained_classifier: CategoryClassifier
    ) -> None:
        res = trained_classifier.predict_single("swiggy lunch biryani", merchant="Swiggy")
        assert "category" in res
        assert res["category"] in CATEGORIES
        assert "confidence" in res
        assert 0.0 <= res["confidence"] <= 1.0
        assert "probabilities" in res
        assert len(res["probabilities"]) == 12
        assert sum(res["probabilities"].values()) == pytest.approx(1.0, rel=1e-2)

    def test_predict_single_with_history(
        self, trained_classifier: CategoryClassifier
    ) -> None:
        history = UserHistoryLayer()
        for _ in range(6):
            history.record_transaction("u_custom", "Gifts & Donations", merchant="Swiggy")

        res = trained_classifier.predict_single(
            description="swiggy order",
            merchant="Swiggy",
            user_id="u_custom",
            history_layer=history,
        )
        assert res["category"] == "Gifts & Donations"

    def test_empty_and_unknown_inputs(
        self, trained_classifier: CategoryClassifier
    ) -> None:
        # Completely empty input
        res = trained_classifier.predict_single("")
        assert res["category"] == "Other"
        assert res["confidence"] > 0.0

        # Random unseen string
        res2 = trained_classifier.predict_single("asdfqwerty12345!@#")
        assert res2["category"] in CATEGORIES
        assert 0.0 <= res2["confidence"] <= 1.0

    def test_save_and_load_consistency(
        self, trained_classifier: CategoryClassifier
    ) -> None:
        with tempfile.NamedTemporaryFile(suffix=".joblib", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            trained_classifier.save(tmp_path)
            loaded = CategoryClassifier.load(tmp_path)

            test_input = ["metro card recharge", "doctor consultation fee"]
            pred_orig = trained_classifier.predict(test_input)
            pred_loaded = loaded.predict(test_input)
            assert pred_orig == pred_loaded
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def test_targeted_service_distinctions(
        self, trained_classifier: CategoryClassifier
    ) -> None:
        # Service vs brand distinctions specified in requirements
        res_swiggy = trained_classifier.predict_single("Swiggy food order")
        assert res_swiggy["category"] == "Food & Dining"

        res_instamart = trained_classifier.predict_single("Swiggy Instamart groceries")
        assert res_instamart["category"] == "Groceries"

        res_food_instamart = trained_classifier.predict_single(
            "Food purchased from Swiggy Instamart"
        )
        assert res_food_instamart["category"] == "Groceries"

        res_prime = trained_classifier.predict_single("Amazon Prime subscription")
        assert res_prime["category"] == "Entertainment"

        res_amazon = trained_classifier.predict_single("Amazon shopping order")
        assert res_amazon["category"] == "Shopping"


class TestModelArtifactSize:
    """Test suite ensuring artifact size meets strict < 5 MB requirement."""

    def test_artifact_file_size_under_5mb(self) -> None:
        model_path = MODEL_PATH
        assert model_path.is_file(), f"Model artifact missing at: {model_path}"

        size_bytes = model_path.stat().st_size
        max_bytes = 5 * 1024 * 1024  # 5 MB

        size_mb = size_bytes / (1024 * 1024)
        assert size_bytes < max_bytes, (
            f"Model artifact size ({size_mb:.2f} MB) exceeds maximum 5.0 MB limit!"
        )
        # Should also be a reasonable non-trivial size (> 50 KB)
        assert size_bytes > 50 * 1024, f"Model artifact abnormally small: {size_bytes} bytes"


class TestKeywordRuleBaseline:
    """Test suite for KeywordRuleBaseline heuristics."""

    def test_baseline_predictions(self) -> None:
        assert KeywordRuleBaseline.predict("swiggy food order") == "Food & Dining"
        assert (
            KeywordRuleBaseline.predict("swiggy instamart delivery")
            == "Groceries"
        )
        assert KeywordRuleBaseline.predict("uber cab ride") == "Travel & Transport"
        assert KeywordRuleBaseline.predict("netflix monthly subscription") == "Entertainment"
        assert KeywordRuleBaseline.predict("amazon prime video") == "Entertainment"
        assert KeywordRuleBaseline.predict("apollo pharmacy medicines") == "Health"
        assert KeywordRuleBaseline.predict("unknown random expense note") == "Other"
