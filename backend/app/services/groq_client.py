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

    # ------------------------------------------------------------------
    # Expense assistant (US-24 / T-57)
    # ------------------------------------------------------------------

    async def _chat(self, messages: list[dict[str, str]], max_tokens: int, json_mode: bool) -> str | None:
        """One bounded chat completion; None on any failure (the caller falls back)."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            if self._custom_client is not None:
                response = await self._custom_client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            if response.status_code != 200:
                logger.warning("Groq assistant call returned HTTP status %s", response.status_code)
                return None
            choices = response.json().get("choices")
            if not choices:
                return None
            content = choices[0].get("message", {}).get("content")
            return content if isinstance(content, str) and content.strip() else None
        except httpx.TimeoutException:
            logger.warning("Groq assistant call timed out after %s seconds", self.timeout)
            return None
        except httpx.RequestError as exc:
            logger.warning("Groq assistant call network error: %s", type(exc).__name__)
            return None
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as exc:
            logger.warning("Failed to parse Groq assistant response: %s", type(exc).__name__)
            return None

    async def select_tool_call(
        self,
        question: str,
        tool_definitions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Ask the model to pick ONE query tool and fill its slots.

        The model sees only the question and the tool definitions (names, purposes,
        slot schemas): no data, no SQL, no database access. Returns the parsed JSON
        object ``{"tool": ..., "slots": {...}}`` without validating it (the caller
        validates), or None if the call or the JSON fails.
        """
        if not self.is_configured():
            return None
        system = (
            "You choose a query tool for a personal expense tracker in India.\n"
            "Pick EXACTLY ONE tool from the list and fill its slots from the question. Use only "
            "slots defined in the tool's schema and leave out slots the question does not give.\n"
            "A period is an object with ONE of: date_range; month (with an optional year); year; "
            "last_days; or start_date and end_date (YYYY-MM-DD) only when the question writes both "
            "dates. Never work out a date yourself; leave the period out if none is named.\n"
            "Never write SQL or code. If no tool fits, or the question is about someone else's "
            'data, moving money or anything else, answer {"tool": null, "slots": {}}.\n'
            'Reply with JSON only, in the form {"tool": "<name or null>", "slots": {...}}.\n\n'
            "TOOLS:\n" + json.dumps(tool_definitions)
        )
        content = await self._chat(
            [{"role": "system", "content": system}, {"role": "user", "content": question.strip()}],
            max_tokens=200,
            json_mode=True,
        )
        if content is None:
            return None
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Groq tool selection was not valid JSON")
            return None
        return parsed if isinstance(parsed, dict) else None

    async def write_answer(
        self,
        question: str,
        tool_name: str,
        facts: dict[str, str],
    ) -> str | None:
        """Ask the model to word the answer using placeholders only.

        ``facts`` maps placeholder names to values the backend formatted (totals,
        counts, the period and labels taken from the question); a list built from
        stored data is only named, never sent. The model must write the placeholders,
        never the numbers; the backend fills them in and checks the result
        (app/ai/grounding.py).
        """
        if not self.is_configured():
            return None
        system = (
            "You word answers for a personal expense tracker. Write one or two short, friendly "
            "sentences that answer the question using the facts given.\n"
            "RULES: refer to every fact by its placeholder in curly braces, e.g. {total} or "
            "{period}. Some facts are lists the app fills in; use their placeholder where the list "
            "should go. Never write any digit, amount, date, percentage or number word yourself, "
            "and never add facts that are not listed. Reply with the sentence only."
        )
        listed = "\n".join(f"{{{name}}} = {value}" for name, value in facts.items())
        content = await self._chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": f"Question: {question.strip()}\nTool: {tool_name}\nFacts:\n{listed}"},
            ],
            max_tokens=150,
            json_mode=False,
        )
        return content.strip() if content else None
