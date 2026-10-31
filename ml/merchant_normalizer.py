"""Merchant normalization component for expense category classification.

Handles casing, punctuation, transaction prefixes, currency amounts,
and canonical merchant name mapping while preserving service-level distinctions
(e.g., Swiggy vs Swiggy Instamart, Amazon vs Amazon Prime).
"""

from __future__ import annotations

import re

# Canonical mappings for common Indian & global merchants and service variants.
# Patterns are matched against lowercased, stripped strings.
# Specific multi-word service variants MUST come before general brand names.
CANONICAL_MERCHANT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Quick commerce / Groceries vs Food delivery distinctions
    (re.compile(r"\bswiggy\s*instamart\b"), "swiggy instamart"),
    (re.compile(r"\bswiggy\b"), "swiggy"),
    (re.compile(r"\bzomato\s*(?:dining|gold)\b"), "zomato dining"),
    (re.compile(r"\bzomato\b"), "zomato"),
    (re.compile(r"\buber\s*eats\b"), "uber eats"),
    (re.compile(r"\buber\s*(?:india|rides?|auto|trip|moto)?\b"), "uber"),
    (re.compile(r"\bola\s*(?:cabs?|money|auto|bike|ride)?\b"), "ola"),
    (re.compile(r"\brapido\s*(?:bike|auto|ride)?\b"), "rapido"),
    # E-commerce vs Streaming / Subscriptions / Gift Cards
    (re.compile(r"\bamazon\s*prime(?:\s*video)?\b"), "amazon prime"),
    (re.compile(r"\bamazon\s*gift\s*card\b"), "amazon gift card"),
    (re.compile(r"\b(?:amzn\s*mktplace|amzn|amazon\s*pay|amazon(?:\.in)?)\b"), "amazon"),
    (re.compile(r"\bflipkart(?:\s*internet)?\b"), "flipkart"),
    # Home services vs Personal Care
    (re.compile(r"\b(?:urban\s*company|urbanclap)\s*(?:salon|spa|grooming)\b"), "urban company salon"),
    (re.compile(r"\b(?:urban\s*company|urbanclap)\s*(?:cleaning|pest\s*control|plumber|repair)\b"), "urban company cleaning"),
    (re.compile(r"\b(?:urban\s*company|urbanclap)\b"), "urban company"),
    # Groceries & Supermarkets
    (re.compile(r"\b(?:d[\s-]?mart|avenue\s*supermarts?)\b"), "dmart"),
    (re.compile(r"\b(?:big\s*basket|bb\s*daily|bigbasket)\b"), "bigbasket"),
    (re.compile(r"\bblinkit(?:\s*grocery)?\b"), "blinkit"),
    (re.compile(r"\bzepto(?:\s*now)?\b"), "zepto"),
    (re.compile(r"\breliance\s*(?:fresh|smart|retail)\b"), "reliance fresh"),
    # Entertainment & Streaming
    (re.compile(r"\bnetflix(?:\.com)?\b"), "netflix"),
    (re.compile(r"\b(?:disney\+?\s*)?hotstar\b"), "hotstar"),
    (re.compile(r"\bspotify(?:\s*india)?\b"), "spotify"),
    (re.compile(r"\bbookmyshow|bigtree\b"), "bookmyshow"),
    (re.compile(r"\b(?:pvr|inox)\s*cinemas?\b"), "pvr"),
    (re.compile(r"\bsonyliv\b"), "sonyliv"),
    # Health & Pharmacies
    (re.compile(r"\bapollo\s*(?:pharmacy|247|hospital)?\b"), "apollo pharmacy"),
    (re.compile(r"\b(?:tata\s*)?1mg\b"), "1mg"),
    (re.compile(r"\bpharmeasy\b"), "pharmeasy"),
    (re.compile(r"\bnetmeds\b"), "netmeds"),
    (re.compile(r"\blenskart(?:\s*plus)?\b"), "lenskart"),
    (re.compile(r"\b(?:cult\.?fit|cure\.?fit)\b"), "cult.fit"),
    (re.compile(r"\bdr\s*lal\s*pathlabs?\b"), "dr lal pathlabs"),
    # Personal Care & Cosmetics
    (re.compile(r"\bnykaa(?:\s*man)?\b"), "nykaa"),
    (re.compile(r"\bpurplle\b"), "purplle"),
    (re.compile(r"\bmamaearth\b"), "mamaearth"),
    # Shopping & Apparel
    (re.compile(r"\bmyntra(?:\s*designs)?\b"), "myntra"),
    (re.compile(r"\bajio\b"), "ajio"),
    (re.compile(r"\bpantaloons\b"), "pantaloons"),
    (re.compile(r"\bdecathlon\b"), "decathlon"),
    (re.compile(r"\bcroma\b"), "croma"),
    (re.compile(r"\bsnapdeal\b"), "snapdeal"),
    # Travel & Transit
    (re.compile(r"\birctc(?:\s*ticketing)?\b"), "irctc"),
    (re.compile(r"\bmakemytrip|mmt\b"), "makemytrip"),
    (re.compile(r"\bredbus\b"), "redbus"),
    (re.compile(r"\bindigo\s*airlines?\b"), "indigo"),
    # Bills & Telecom / Utilities
    (re.compile(r"\breliance\s*jio|jio\b"), "jio"),
    (re.compile(r"\bbharti\s*airtel|airtel\b"), "airtel"),
    (re.compile(r"\bvodafone\s*idea|vi\b"), "vi"),
    (re.compile(r"\btata\s*play\b"), "tata play"),
]


class MerchantNormalizer:
    """Normalizes raw merchant strings and expense text for classification."""

    @staticmethod
    def normalize_merchant(merchant: str | None) -> str:
        """Normalize a merchant name into its canonical representation.

        Args:
            merchant: Raw merchant string (e.g. 'AMZN MKTPLACE', 'SWIGGY', 'Uber India').

        Returns:
            Normalized canonical merchant string or empty string if None/empty.
        """
        if not merchant or not isinstance(merchant, str):
            return ""

        # Lowercase and clean excess whitespace
        norm = merchant.lower().strip()
        norm = re.sub(r"[\s_]+", " ", norm)

        # Remove trailing corporate / entity identifiers
        norm = re.sub(
            r"\b(pvt\.?\s*ltd\.?|private\s*limited|limited|ltd\.?|inc\.?|corp\.?|llp|india)\b",
            "",
            norm,
        ).strip()

        # Clean punctuation from edges
        norm = re.sub(r"^[^\w]+|[^\w]+$", "", norm)
        norm = re.sub(r"\s+", " ", norm).strip()

        # Match against canonical patterns
        for pattern, canonical in CANONICAL_MERCHANT_PATTERNS:
            if pattern.search(norm):
                return canonical

        return norm

    @staticmethod
    def clean_text(text: str | None) -> str:
        """Clean an expense description or note by stripping noise.

        Removes:
        - Common transaction prefixes (UPI, Paid to, Transfer to, TXN, etc.)
        - Monetary currency symbols and amounts (Rs. 1500, 250/-, INR 99, etc.)
        - Excess whitespace and non-alphanumeric noise characters

        Args:
            text: Raw expense text.

        Returns:
            Cleaned and normalized text.
        """
        if not text or not isinstance(text, str):
            return ""

        s = text.lower().strip()

        # Handle UPI prefixes: upi/merchantname -> merchantname
        s = re.sub(r"\bupi/([a-zA-Z0-9_\']+)", r" \1 ", s)

        # Strip transaction prefixes
        s = re.sub(
            r"^(?:paid(?:\s+(?:to|via|for))?|payment(?:\s+(?:to|via|for))?|transfer(?:\s+(?:to|via|for))?|txn|pos|neft|rtgs|imps)\s+",
            "",
            s,
        )

        # Strip currency amounts: Rs. 1500, Rs 500, INR 200, ₹ 300, 250/-, - 1500, etc.
        s = re.sub(r"(?:rs\.?|inr|₹)\s*\d+(?:\.\d+)?", " ", s)
        s = re.sub(r"\b\d+\s*/-", " ", s)
        s = re.sub(r"-\s*\d+\b", " ", s)
        s = re.sub(r"\b\d+\b", " ", s)

        # Remove parentheses, brackets, and common punctuation
        s = re.sub(r"[\(\)\[\]\{\},:;\-_\'\"\/\\#@!*?]", " ", s)

        # Collapse whitespace
        s = re.sub(r"\s+", " ", s).strip()
        return s

    @classmethod
    def prepare_input(cls, description: str, merchant: str | None = None) -> str:
        """Prepare a combined input string for feature extraction.

        If a merchant is provided, it is normalized and concatenated with
        the cleaned description.

        Args:
            description: Raw description of the expense.
            merchant: Optional raw merchant name.

        Returns:
            Preprocessed input string ready for the vectorizer.
        """
        cleaned_desc = cls.clean_text(description)
        norm_merchant = cls.normalize_merchant(merchant)

        if norm_merchant and norm_merchant not in cleaned_desc:
            combined = f"{cleaned_desc} {norm_merchant}".strip()
        else:
            combined = cleaned_desc

        return combined
