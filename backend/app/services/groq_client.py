"""Groq LLM Client for expense category classification fallback.

Provides a resilient, timeout-bounded client to query Groq's chat completion
API when local model confidence is below the established 60% threshold.
Ensures zero data retention, strict validation against the 12 canonical categories,
and safe fallback without raising unhandled exceptions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

CANONICAL_CATEGORIES: list[str] = [
    "Bills & Utilities",
    "Education",
    "Entertainment",
    "Food & Dining",
    "Gifts & Donations",
    "Groceries",
    "Health",
    "Other",
    "Personal Care",
    "Rent & Housing",
    "Shopping",
    "Travel & Transport",
]

# Case-insensitive map including common synonyms for robust matching
CATEGORY_LOOKUP: dict[str, str] = {c.lower(): c for c in CANONICAL_CATEGORIES}
CATEGORY_LOOKUP.update(
    {
        "food & drink": "Food & Dining",
        "food and drink": "Food & Dining",
        "food and dining": "Food & Dining",
        "dining": "Food & Dining",
        "transport": "Travel & Transport",
        "transportation": "Travel & Transport",
        "travel": "Travel & Transport",
        "travel & transport": "Travel & Transport",
        "travel and transport": "Travel & Transport",
        "utilities": "Bills & Utilities",
        "bills": "Bills & Utilities",
        "bills and utilities": "Bills & Utilities",
        "health & fitness": "Health",
        "health and fitness": "Health",
        "gifts": "Gifts & Donations",
        "donations": "Gifts & Donations",
        "gifts and donations": "Gifts & Donations",
        "rent": "Rent & Housing",
        "housing": "Rent & Housing",
        "rent and housing": "Rent & Housing",
    }
)


class GroqClient:
    """Async Groq API client with bounded timeout and category validation."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 2.0,
        base_url: str = "https://api.groq.com/openai/v1",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.GROQ_API_KEY
        self.model = model if model is not None else settings.GROQ_MODEL
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self._custom_client = http_client

    def is_configured(self) -> bool:
        """Check whether a non-empty Groq API key is present."""
        return bool(self.api_key and self.api_key.strip())

    async def classify_category(
        self,
        description: str,
        merchant: str | None = None,
    ) -> str | None:
        """Query Groq to classify an ambiguous expense into a canonical category.

        Args:
            description: Raw description of the expense.
            merchant: Optional merchant name.

        Returns:
            Canonical category name if successfully classified, else None.
        """
        if not self.is_configured():
            logger.debug("Groq API key not configured. Skipping LLM fallback.")
            return None

        prompt_system = (
            "You are an expense categorization assistant. Categorize the transaction into "
            "EXACTLY ONE of the following 12 canonical categories:\n"
            + "\n".join(f"- {c}" for c in CANONICAL_CATEGORIES)
            + "\nRespond ONLY with a valid JSON object in the exact format: "
            '{"category": "<category_name>"}'
        )

        user_content = f"Description: {description.strip()}"
        if merchant and merchant.strip():
            user_content += f"\nMerchant: {merchant.strip()}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt_system},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.0,
            "max_tokens": 50,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            if self._custom_client is not None:
                response = await self._custom_client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=self.timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=headers,
                    )

            if response.status_code != 200:
                logger.warning(
                    "Groq API returned HTTP status %s: %s",
                    response.status_code,
                    response.text[:200],
                )
                return None

            data = response.json()
            choices = data.get("choices")
            if not choices:
                return None

            message_content = choices[0].get("message", {}).get("content", "")
            parsed = json.loads(message_content)
            raw_category = parsed.get("category", "").strip().lower()

            canonical = CATEGORY_LOOKUP.get(raw_category)
            if canonical:
                return canonical

            logger.warning(
                "Groq LLM returned non-canonical category: '%s'", raw_category
            )
            return None

        except httpx.TimeoutException:
            logger.warning("Groq API request timed out after %s seconds", self.timeout)
            return None
        except httpx.RequestError as exc:
            logger.warning("Groq API network error: %s", exc)
            return None
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Failed to parse Groq response: %s", exc)
            return None
