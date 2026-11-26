"""Words people use for the default expense categories (US-24).

Used by the assistant to read a category out of a question. The category
suggestion pipeline (US-26) keeps its own lookup in app/services/groq_client.py;
this table is only for questions, so adding a word here never changes how an
expense is categorised.
"""

from __future__ import annotations

import re
from enum import StrEnum


class CategoryName(StrEnum):
    """The twelve default categories seeded by migration 004."""

    BILLS_UTILITIES = "Bills & Utilities"
    EDUCATION = "Education"
    ENTERTAINMENT = "Entertainment"
    FOOD_DINING = "Food & Dining"
    GIFTS_DONATIONS = "Gifts & Donations"
    GROCERIES = "Groceries"
    HEALTH = "Health"
    OTHER = "Other"
    PERSONAL_CARE = "Personal Care"
    RENT_HOUSING = "Rent & Housing"
    SHOPPING = "Shopping"
    TRAVEL_TRANSPORT = "Travel & Transport"


_TERMS: dict[CategoryName, tuple[str, ...]] = {
    CategoryName.BILLS_UTILITIES: (
        "bills and utilities", "bills & utilities", "bills", "bill", "utilities", "utility",
        "electricity", "internet", "broadband", "phone bill", "mobile bill",
    ),
    CategoryName.EDUCATION: ("education", "course", "courses", "tuition", "school fees", "college fees"),
    CategoryName.ENTERTAINMENT: ("entertainment", "movie", "movies", "streaming", "concert", "concerts"),
    CategoryName.FOOD_DINING: (
        "food and dining", "food & dining", "food", "dining", "eating out", "restaurant",
        "restaurants", "lunch", "dinner", "breakfast",
    ),
    CategoryName.GIFTS_DONATIONS: (
        "gifts and donations", "gifts & donations", "gifts", "gift", "donations", "donation", "charity",
    ),
    CategoryName.GROCERIES: ("groceries", "grocery", "vegetables", "fruits", "supermarket"),
    CategoryName.HEALTH: (
        "health and fitness", "health", "medicine", "medicines", "pharmacy", "doctor", "medical",
    ),
    CategoryName.OTHER: ("other category", "miscellaneous"),
    CategoryName.PERSONAL_CARE: ("personal care", "salon", "haircut", "haircuts", "spa"),
    CategoryName.RENT_HOUSING: ("rent and housing", "rent & housing", "rent", "housing"),
    CategoryName.SHOPPING: ("shopping", "clothes", "clothing"),
    CategoryName.TRAVEL_TRANSPORT: (
        "travel and transport", "travel & transport", "travel", "transport", "transportation",
        "cab", "cabs", "taxi", "fuel", "petrol", "flight", "flights", "train", "trains", "bus", "metro",
    ),
}

# Longest phrase first, so "food and dining" wins over "food".
_LOOKUP: list[tuple[re.Pattern[str], CategoryName]] = sorted(
    (
        (re.compile(r"(?<![\w&])" + re.escape(term) + r"(?![\w&])"), category)
        for category, terms in _TERMS.items()
        for term in terms
    ),
    key=lambda item: len(item[0].pattern),
    reverse=True,
)


def find_category(text: str) -> CategoryName | None:
    """The category a question names, matching whole words only."""
    norm = text.lower()
    for pattern, category in _LOOKUP:
        if pattern.search(norm):
            return category
    return None


def is_category_word(word: str) -> bool:
    return find_category(word) is not None
