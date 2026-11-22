"""Receipt Text Rule Parser (US-16 / T-47).

Extracts merchant name, transaction date, total amount (in paise/minor units),
suggested category, line items, payment mode, and per-field confidence scores from
receipt text.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from ml.fallback_rules import RULE_PATTERNS
from ml.merchant_normalizer import MerchantNormalizer

logger = logging.getLogger(__name__)

MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# Grand total keywords ordered by specificity
TOTAL_KEYWORDS = [
    r"TOTAL AMOUNT PAYABLE",
    r"NET AMOUNT PAYABLE",
    r"NET AMOUNT DUE",
    r"NET AMOUNT PAID",
    r"NET AMOUNT",
    r"TOTAL BILL AMOUNT",
    r"TOTAL AMOUNT DUE",
    r"AMOUNT DUE",
    r"TOTAL DUE",
    r"CURRENT BILL PAYABLE",
    r"TOTAL INVOICE VALUE",
    r"INVOICE TOTAL",
    r"BILL TOTAL",
    r"BILL VALUE",
    r"FINAL AMOUNT",
    r"PAID AMOUNT",
    r"TOTAL AMOUNT PAID",
    r"TOTAL CASH RECEIVED",
    r"TOTAL CASH DUE",
    r"TOTAL PAID",
    r"TOTAL AMOUNT",
    r"TOTAL PAYABLE",
    r"TOTAL SALE",
    r"TOTAL CHARGED",
    r"ROUNDED TOTAL",
    r"ORDER TOTAL",
    r"GRAND TOTAL",
    r"AMOUNT PAYABLE",
    r"(?<!SUB\s)(?<!SUB)TOTAL(?!S)(?! SAVINGS)",
]

SUBTOTAL_KEYWORDS = [
    r"ITEMS SUBTOTAL",
    r"FOOD SUBTOTAL",
    r"SUB TOTAL",
    r"SUBTOTAL",
    r"TAXABLE AMOUNT",
    r"TAXABLE SERVICE VALUE",
    r"NET ENERGY CHARGES",
    r"NET GAS VALUE",
    r"FUEL VALUE",
]

TAX_KEYWORDS = [
    r"GST PAYABLE",
    r"ELECTRICITY DUTY",
    r"INTEGRATED GST",
    r"RESTAURANT GST",
    r"CONVENIENCE TAX",
    r"VAT / CESS",
    r"VAT",
    r"CGST",
    r"SGST",
    r"IGST",
    r"TAX",
]

PAYMENT_MODE_PATTERNS = [
    (re.compile(r"\b(?:UPI|GPay|GooglePay|PhonePe|Paytm|BHIM)\b", re.IGNORECASE), "UPI"),
    (re.compile(r"\b(?:Credit Card|CreditCard)\b", re.IGNORECASE), "Credit Card"),
    (re.compile(r"\b(?:Debit Card|DebitCard)\b", re.IGNORECASE), "Debit Card"),
    (re.compile(r"\b(?:NetBanking|Net\s*Banking|Online\s*Banking)\b", re.IGNORECASE), "NetBanking"),
    (re.compile(r"\b(?:Cash|Cash\s*Payment)\b", re.IGNORECASE), "Cash"),
]


@dataclass
class ParsedReceipt:
    """Structured representation of parsed receipt fields."""

    merchant: str | None = None
    amount_minor: int | None = None  # in paise (integer)
    total_amount: float | None = None  # in rupees (float)
    subtotal: float | None = None
    tax: float | None = None
    expense_date: date | None = None
    category: str | None = None
    payment_mode: str | None = None
    notes: str | None = None
    raw_text: str | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    is_draft: bool = True
    ocr_engine_used: str | None = None


class RuleParser:
    """Robust rule-based parser for receipt OCR text."""

    @classmethod
    def parse_text(cls, text: str | None, ocr_engine: str | None = None) -> ParsedReceipt:
        """Parse raw OCR text into structured fields with confidence scores."""
        if not text or not text.strip():
            return ParsedReceipt(
                confidence={"merchant": 0.0, "date": 0.0, "total": 0.0, "items": 0.0, "overall": 0.0},
                raw_text="",
                ocr_engine_used=ocr_engine or "none",
                is_draft=True,
            )

        raw = text.strip()
        lines = [line.strip() for line in raw.splitlines() if line.strip()]

        merchant, conf_merchant = cls.extract_merchant(lines)
        exp_date, conf_date = cls.extract_date(raw)
        total_amt, conf_total = cls.extract_total(raw)
        subtotal = cls.extract_subtotal(raw)
        tax = cls.extract_tax(raw)
        payment_mode = cls.extract_payment_mode(raw)
        items, conf_items = cls.extract_items(lines)
        category = cls.suggest_category(merchant, raw)

        # Convert total to minor units (paise)
        amount_minor = int(round(total_amt * 100)) if total_amt is not None else None

        # Calculate overall confidence
        weights = [conf_merchant, conf_date, conf_total]
        overall = sum(weights) / len(weights) if weights else 0.0

        confidence = {
            "merchant": round(conf_merchant, 2),
            "date": round(conf_date, 2),
            "total": round(conf_total, 2),
            "items": round(conf_items, 2),
            "overall": round(overall, 2),
        }

        # Build descriptive draft notes
        notes_parts = []
        if merchant:
            notes_parts.append(f"Scanned bill from {merchant}")
        if items:
            notes_parts.append(f"({len(items)} line item{'s' if len(items) > 1 else ''})")
        if payment_mode:
            notes_parts.append(f"Paid via {payment_mode}")
        notes = " · ".join(notes_parts) if notes_parts else "Draft receipt from scan"

        return ParsedReceipt(
            merchant=merchant,
            amount_minor=amount_minor,
            total_amount=total_amt,
            subtotal=subtotal,
            tax=tax,
            expense_date=exp_date,
            category=category,
            payment_mode=payment_mode,
            notes=notes,
            raw_text=raw,
            items=items,
            confidence=confidence,
            is_draft=True,
            ocr_engine_used=ocr_engine,
        )

    @classmethod
    def extract_merchant(cls, lines: list[str]) -> tuple[str | None, float]:
        """Extract merchant name from receipt header lines."""
        if not lines:
            return None, 0.0

        # Discard decorative divider lines
        clean_lines = [
            l for l in lines
            if not set(l).issubset({"=", "-", "*", "_", "#", "~"})
        ]

        if not clean_lines:
            return None, 0.0

        # Scan the first 5 non-divider lines for merchant name
        candidate_lines = clean_lines[:5]

        # Ignore lines that are metadata tags
        ignore_keywords = [
            "GSTIN", "TAX INVOICE", "INVOICE", "BILL NO", "DATE", "TIME",
            "WELCOME", "CASHIER", "ORDER ID", "PHONE", "TEL:", "RECEIPT NO",
            "TABLE:", "CUSTOMER", "BUYER", "ADDRESS", "DL NO",
        ]

        for line in candidate_lines:
            upper = line.upper()
            if any(upper.startswith(kw) or f" {kw}" in upper for kw in ignore_keywords):
                continue
            # Also skip if line contains only numbers or dates
            if re.match(r"^[\d\s\:\/\-\,\.]+$", line):
                continue

            cleaned = re.sub(r"^[=\-\*\#\s]+|[=\-\*\#\s]+$", "", line)
            # Remove trailing suffixes like 'HOSP.', 'LTD', 'PVT LTD'
            norm = MerchantNormalizer.normalize_merchant(cleaned)
            conf = 0.95 if norm else 0.85
            return cleaned.title() if cleaned.isupper() else cleaned, conf

        return None, 0.0

    @classmethod
    def extract_date(cls, text: str) -> tuple[date | None, float]:
        """Extract transaction date, favoring labeled date lines."""
        # Pattern 1: Prefixed with Date / Bill Date / Invoice Date / Dated
        prefix_pattern = (
            r"(?:Date|Bill Date|Invoice Date|Dated)\s*[:\-]?\s*"
            r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
            r"\d{1,2}\s+[A-Za-z]{3,9}\s+\d{2,4})"
        )
        m = re.search(prefix_pattern, text, re.IGNORECASE)
        if m:
            d = cls._parse_single_date(m.group(1))
            if d:
                return d, 0.98

        # Pattern 2: Standalone numeric dates (DD/MM/YYYY or YYYY-MM-DD)
        standalone_patterns = [
            r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})\b",
            r"\b(\d{4}[/-]\d{1,2}[/-]\d{1,2})\b",
            r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})\b",
        ]
        for p in standalone_patterns:
            matches = re.finditer(p, text, re.IGNORECASE)
            for match in matches:
                d = cls._parse_single_date(match.group(1))
                if d:
                    return d, 0.88

        return None, 0.0

    @classmethod
    def _parse_single_date(cls, raw: str) -> date | None:
        """Parse raw string into date object."""
        raw = raw.strip().replace(".", "/")
        # Handle textual month like '15 Sep 2026' or '15-September-2026'
        text_match = re.match(r"^(\d{1,2})[\s\-]+([A-Za-z]{3,9})[\s\-]+(\d{2,4})$", raw)
        if text_match:
            day = int(text_match.group(1))
            month_str = text_match.group(2).lower()
            year = int(text_match.group(3))
            if year < 100:
                year += 2000
            month = MONTH_MAP.get(month_str[:3])
            if month and 1 <= day <= 31:
                try:
                    return date(year, month, day)
                except ValueError:
                    return None

        # Handle numeric delimiters
        normalized = raw.replace("-", "/")
        parts = normalized.split("/")
        if len(parts) == 3:
            try:
                p1, p2, p3 = int(parts[0]), int(parts[1]), int(parts[2])
                if p1 > 1900:  # YYYY/MM/DD
                    return date(p1, p2, p3)
                if p3 < 100:
                    p3 += 2000
                # DD/MM/YYYY
                return date(p3, p2, p1)
            except ValueError:
                return None
        return None

    @classmethod
    def extract_total(cls, text: str) -> tuple[float | None, float]:
        """Extract final payable total amount, filtering out subtotals and discounts."""
        for kw in TOTAL_KEYWORDS:
            pattern = rf"\b{kw}\s*[:\-]?\s*(?:INR|Rs\.?|₹)?\s*([\d,]+\.?\d*)"
            matches = list(re.finditer(pattern, text, re.IGNORECASE))
            if matches:
                # Use the last occurrence since grand total typically comes after subtotals
                last_m = matches[-1]
                try:
                    val_str = last_m.group(1).replace(",", "")
                    val = float(val_str)
                    if val > 0:
                        conf = 0.98 if "TOTAL" in kw or "NET" in kw else 0.90
                        return val, conf
                except ValueError:
                    continue

        return None, 0.0

    @classmethod
    def extract_subtotal(cls, text: str) -> float | None:
        """Extract subtotal or taxable amount if present."""
        for kw in SUBTOTAL_KEYWORDS:
            pattern = rf"\b{kw}\s*[:\-]?\s*(?:INR|Rs\.?|₹)?\s*([\d,]+\.?\d*)"
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    @classmethod
    def extract_tax(cls, text: str) -> float | None:
        """Extract tax amount (CGST, SGST, IGST, VAT) if present."""
        for kw in TAX_KEYWORDS:
            pattern = rf"\b{kw}\s*(?:@\s*[\d\.]+%|\([\d\.]+%\))?\s*[:\-]?\s*(?:INR|Rs\.?|₹)?\s*([\d,]+\.?\d*)"
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                try:
                    return float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
        return None

    @classmethod
    def extract_payment_mode(cls, text: str) -> str | None:
        """Detect payment mode (UPI, Card, NetBanking, Cash)."""
        for pattern, mode in PAYMENT_MODE_PATTERNS:
            if pattern.search(text):
                return mode
        return None

    @classmethod
    def extract_items(cls, lines: list[str]) -> tuple[list[dict[str, Any]], float]:
        """Extract itemized line items from tabular receipt text."""
        items: list[dict[str, Any]] = []
        in_items = False

        header_re = re.compile(r"(?:Item|Description|Particulars|Product|Dishes|Charge)", re.IGNORECASE)
        end_re = re.compile(
            r"^(?:Subtotal|Sub\s*Total|Taxable|VAT|GST|Total|Items\s*Subtotal|Net\s*Gas|Energy\s*Charges|Fuel\s*Value)",
            re.IGNORECASE,
        )

        # Pattern for: Description   Qty   Rate   Amount
        item_re_full = re.compile(
            r"^\s*([A-Za-z0-9\(\)\'\s\.\-\&\/\+,]+?)\s+(\d+(?:\.\d+)?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$"
        )
        # Pattern for: Description   Amount (single item or fixed charge)
        item_re_simple = re.compile(
            r"^\s*([A-Za-z0-9\(\)\'\s\.\-\&\/\+,]+?)\s{2,}([\d,]+\.\d{2})\s*$"
        )

        for line in lines:
            stripped = line.strip()
            if not stripped or set(stripped).issubset({"=", "-", "*", "_"}):
                continue

            if header_re.search(stripped) and any(w in stripped.lower() for w in ["qty", "rate", "amount", "mrp", "price"]):
                in_items = True
                continue

            if in_items:
                if end_re.search(stripped) or stripped.startswith("==="):
                    in_items = False
                    break

                m = item_re_full.match(line)
                if m:
                    name = m.group(1).strip()
                    try:
                        qty = float(m.group(2))
                        rate = float(m.group(3).replace(",", ""))
                        amt = float(m.group(4).replace(",", ""))
                        items.append({
                            "item_name": name,
                            "quantity": qty,
                            "unit_price": rate,
                            "total_price": amt,
                        })
                    except ValueError:
                        continue
                else:
                    m2 = item_re_simple.match(line)
                    if m2:
                        name = m2.group(1).strip()
                        # Avoid catching subtotal / total lines mistakenly
                        if not any(k in name.upper() for k in ["TOTAL", "SUBTOTAL", "TAX", "CESS", "VAT"]):
                            try:
                                amt = float(m2.group(2).replace(",", ""))
                                items.append({
                                    "item_name": name,
                                    "quantity": 1.0,
                                    "unit_price": amt,
                                    "total_price": amt,
                                })
                            except ValueError:
                                continue

        conf = 0.92 if items else 0.0
        return items, conf

    @classmethod
    def suggest_category(cls, merchant: str | None, text: str) -> str:
        """Infer best matching expense category from merchant and receipt text."""
        combined = f"{merchant or ''} {text}".lower()
        for cat, pattern in RULE_PATTERNS:
            if pattern.search(combined):
                return cat
        return "Other"
