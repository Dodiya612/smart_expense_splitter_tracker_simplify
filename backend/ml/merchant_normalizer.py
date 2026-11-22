"""Placeholder MerchantNormalizer for tests.
Provides a `normalize` method expected by category_suggestion_service.
"""

class MerchantNormalizer:
    def __init__(self, *args, **kwargs):
        pass

    def normalize(self, merchant: str) -> str:
        # Return the merchant unchanged – sufficient for tests.
        return merchant
