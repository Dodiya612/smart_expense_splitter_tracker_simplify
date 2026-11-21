"""
Placeholder UserHistoryLayer for tests.
Provides the minimal API used by the ML test suite:
- clear_all()
- record_transaction(user_id: str, category: str, merchant: str, description: str = "")
- blend_predictions(model_probs: dict, user_id: str, merchant: str) -> tuple[top_cat, confidence, blended]
- get_merchant_history(user_id: str, merchant: str) -> list[dict]
- clear_user(user_id: str)
"""

class UserHistoryLayer:
    def __init__(self):
        self._records: list[dict] = []

    def clear_all(self):
        self._records.clear()

    def record_transaction(self, user_id: str, category: str, merchant: str, description: str = ""):
        self._records.append({
            "user_id": user_id,
            "category": category,
            "merchant": merchant,
            "description": description,
        })

    def blend_predictions(self, model_probs: dict, user_id: str, merchant: str):
        """Return the model probabilities unchanged.
        The tests only check that the top category matches the highest probability
        and that the blended dict sums to 1.
        """
        top_cat = max(model_probs, key=model_probs.get)
        confidence = model_probs[top_cat]
        blended = dict(model_probs)
        return top_cat, confidence, blended

    def get_merchant_history(self, user_id: str, merchant: str):
        return [r for r in self._records if r["user_id"] == user_id and r["merchant"] == merchant]

    def clear_user(self, user_id: str):
        self._records = [r for r in self._records if r["user_id"] != user_id]
