"""Keyword-rule baseline categorizer for expense classification.

Implements rule-based and regex pattern matching directly reflecting the
ground-truth guidelines in ml/LABELLING_GUIDE.md. Used as the deterministic
baseline against which the ML model is evaluated.
"""

from __future__ import annotations

import re

from ml.merchant_normalizer import MerchantNormalizer

# Category rules with regex patterns ordered by priority
RULE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # 1. Tricky case: Specific services that override brand-level categories
    (
        "Groceries",
        re.compile(
            r"\b(?:swiggy\s*instamart|instamart|blinkit|zepto|big\s*basket|bigbasket|bb\s*daily|dmart|d-mart|reliance\s*fresh|kirana|doodh|milk|bread|butter|atta|sabzi|vegetables?|fruits?|butcher|mutton|paneer|eggs?|dahi|curd|tomatoes|onions|groceries|grocery)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Entertainment",
        re.compile(
            r"\b(?:amazon\s*prime|prime\s*video|netflix|hotstar|spotify|bookmyshow|pvr|inox|cinema|movie|theatre|concert|bgmi|steam|playstation|gaming|game|wonderla|kindle\s*novel|novel|comic|sonyliv|smaaash)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Gifts & Donations",
        re.compile(
            r"\b(?:amazon\s*gift\s*card|gift\s*card|birthday\s*gift|anniversary\s*gift|gift|rakhi\s*gift|shagun|temple\s*donation|donation|charity|giveindia|ngo|flowers\s*for)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Personal Care",
        re.compile(
            r"\b(?:urban\s*company\s*(?:salon|spa|grooming)|haircut|salon|parlour|parlor|spa|massage|nykaa|purplle|mamaearth|shampoo|soap|conditioner|cosmetics|toiletries|dhobi|dry\s*cleaning|laundry|tailor|tailoring|alteration|threading|shaving|perfume)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Rent & Housing",
        re.compile(
            r"\b(?:urban\s*company\s*(?:cleaning|pest\s*control|plumber|repair)|pg\s*rent|room\s*rent|flat\s*rent|rent|hostel\s*room|hostel\s*charges|maintenance|society\s*maintenance|deposit|brokerage|plumber|electrician|carpenter|maid\s*salary|maid|cook\s*salary|packers\s*and\s*movers|movers|pest\s*control|painting|house\s*repair)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Health",
        re.compile(
            r"\b(?:apollo\s*pharmacy|apollo|1mg|pharmeasy|netmeds|pharmacy|chemist|medicine|medicines|dawai|doctor|clinic|hospital|dentist|dental|root\s*canal|blood\s*test|pathlabs?|dr\s*lal|lenskart|glasses|contact\s*lens|gym\s*membership|gym|cult\.?fit|fitness|health\s*insurance|supplements?|protein)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Bills & Utilities",
        re.compile(
            r"\b(?:electricity\s*bill|electricity|water\s*bill|water|lpg|gas\s*cylinder|piped\s*gas|mobile\s*recharge|recharge|jio\s*recharge|airtel\s*recharge|broadband|wifi\s*bill|wifi|internet\s*bill|tata\s*play|dth|dish\s*tv|bescom|tneb|mseb|generator\s*diesel)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Education",
        re.compile(
            r"\b(?:semester\s*fees|college\s*fees|tuition\s*fees|tuition|school\s*fees|coaching|udemy|coursera|course|textbooks?|stationery|xerox|printouts?|photocopy|gate\s*registration|exam\s*registration|exam\s*fee|notebooks?|pen|pencil|arduino)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Travel & Transport",
        re.compile(
            r"\b(?:uber|ola|rapido|auto\s*fare|auto|cab|taxi|metro\s*card|metro|irctc|train\s*ticket|train|bus\s*ticket|bus|flight\s*ticket|flight|air\s*ticket|petrol|diesel|fuel|fastag\s*recharge|fastag|toll|parking|puncture|vehicle\s*service|bike\s*service|car\s*service|car\s*wash|oyo\s*room|hotel\s*booking|makemytrip|redbus|indigo)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Shopping",
        re.compile(
            r"\b(?:amazon|flipkart|myntra|ajio|zara|h&m|pantaloons|decathlon|croma|reliance\s*digital|snapdeal|earphones|headphones|jeans|shirt|t-?shirt|shoes|sneakers|dress|clothes|clothing|jacket|pressure\s*cooker|laptop|mobile\s*phone|gadgets?|watch|bedsheet|curtains?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Food & Dining",
        re.compile(
            r"\b(?:swiggy|zomato|canteen|mess|tiffin|dhaba|restaurant|cafe|coffee|ccd|starbucks|chaayos|chai|tea|bakery|baskin\s*robbins|kfc|mcdonalds?|mcd|burger\s*king|dominos?|pizza\s*hut|pizza|biryani|burger|maggi|samosa|vada|dosa|idli|paratha|roll|shawarma|ice\s*cream|pastr(?:y|ies)|cake|dinner|lunch|breakfast|nashta|snacks?|cutting\s*chai|faasos|behrouz|bbq\s*nation|barbeque)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Other",
        re.compile(
            r"\b(?:dtdc|courier|speed\s*post|post\s*office|passport\s*fee|visa\s*fee|atm\s*fee|bank\s*charges|traffic\s*challan|challan|fine|dog\s*food|cat\s*food|pet\s*vet|pet|stamp\s*paper|affidavit|notary|misc|miscellaneous|random\s*expense|cash\s*expense)\b",
            re.IGNORECASE,
        ),
    ),
]


class KeywordRuleBaseline:
    """Baseline rule-based categorizer using regex heuristics."""

    @classmethod
    def predict(cls, description: str, merchant: str | None = None) -> str:
        """Predict category using deterministic keyword heuristics.

        Args:
            description: Raw description of the expense.
            merchant: Optional raw merchant name.

        Returns:
            One of the 12 category names.
        """
        text = MerchantNormalizer.prepare_input(description, merchant)

        for category, pattern in RULE_PATTERNS:
            if pattern.search(text):
                return category

        return "Other"

