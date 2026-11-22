class KeywordRuleBaseline:
    """Placeholder fallback rule used by category suggestion service.
    In production this would contain keyword‑based heuristics; for tests we just need a stub.
    """
    def __init__(self, *args, **kwargs):
        pass
    def apply(self, *args, **kwargs):
        return []

# Minimal rule patterns placeholder – the real project expects a dict of regexes.
RULE_PATTERNS = {}

