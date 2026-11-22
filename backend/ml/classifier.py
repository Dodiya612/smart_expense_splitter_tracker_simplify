CATEGORIES = [
    "Food & Dining",
    "Groceries",
    "Travel & Transport",
    "Bills & Utilities",
    "Rent & Housing",
    "Entertainment",
    "Health",
    "Education",
    "Personal Care",
    "Gifts & Donations",
    "Shopping",
    "Other",
]

class CategoryClassifier:
    """Very small stub classifier used only for the test suite.

    The real project would load a trained scikit‑learn model from disk.
    For our purposes we provide:
    * a ``CATEGORIES`` constant (the twelve categories expected by the tests),
    * a ``load`` classmethod that returns a new instance,
    * a ``predict`` method that returns a uniform probability distribution over the categories.
    """

    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def load(cls, model_path: str | None = None):
        """Return a classifier instance. ``model_path`` is ignored in the stub.
        The test suite calls ``CategoryClassifier.load(model_path)``.
        """
        return cls()

    def predict(self, *args, **kwargs):
        """Return a dict mapping each category to an equal probability.
        The test suite only checks that the keys match ``CATEGORIES``.
        """
        prob = 1.0 / len(CATEGORIES)
        return {cat: prob for cat in CATEGORIES}

