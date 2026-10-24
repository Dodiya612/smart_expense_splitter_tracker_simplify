# Consent Note and Privacy Compliance Declaration

**Task:** T-11 (US-16 Scan Bill to Create Expense)  
**Repository:** `smart_expense_splitter_tracker_simplify` (Coinscious)  
**Dataset Path:** `evals/bills/`  
**Date:** October 2026  
**Curator / Assignee:** Parthiv Panchal

---

## 1. Purpose of the Dataset
The dataset contained in `evals/bills/` consists of **40 realistic, curated receipt/bill test samples** designed strictly for evaluation and benchmarking of Optical Character Recognition (OCR) and Named Entity Recognition (NER) models for the Coinscious Smart Expense Tracker application (Story **US-16**, Task **T-11**).

---

## 2. PII Redaction and Privacy Guarantee
In accordance with the project guidelines, academic integrity policies, and applicable data privacy frameworks (including India's **Digital Personal Data Protection Act, 2023** and **GDPR** principles):

1. **No Real PII Present:**
   - All customer names have been completely masked with placeholder tags (e.g., `[REDACTED_CUSTOMER]`, `[REDACTED_BUYER]`, `[REDACTED_PATIENT]`).
   - Personal phone numbers have been anonymized with masked digits (e.g., `+91 98XXX XXXXX`).
   - Personal home addresses, flat numbers, and hostel rooms have been fully redacted (`[REDACTED_ADDRESS]`, `[REDACTED_SHIPPING_ADDRESS]`).
   - Financial identifiers, bank account numbers, and credit/debit card numbers have been truncated to industry standard masked formats (e.g., `XXXX-XXXX-XXXX-1234`).
   - Vehicle registration numbers on fuel slips are anonymized (e.g., `GJ-01-XX-XXXX`).
   - UPI virtual payment handles are masked (e.g., `[REDACTED]@okhdfcbank`).

2. **Synthetic and Consented Artifacts:**
   - All receipts have been synthesized or structured from de-identified common commercial templates across 6 standard merchant categories.
   - No confidential, proprietary, or personal banking documents were ingested without sanitization.

---

## 3. Explicit Consent Declaration
The creator, contributors, and evaluation team grant explicit consent for this dataset to be:
- Stored in the project evaluation directory `evals/bills/`.
- Processed by automated OCR pipelines (Tesseract, PaddleOCR, LLM-based parsers) during continuous integration and offline benchmarking.
- Evaluated for field extraction precision, recall, and end-to-end character accuracy.

---

## 4. Verification Checklist
- [x] 40 bills across 6 required categories.
- [x] Zero unredacted personal identifying information (PII).
- [x] Ground truth field labels matching OCR extraction schema (`merchant_name`, `date`, `total_amount`, `tax`, `subtotal`, `items`, `payment_mode`).
- [x] Ready for OCR evaluation pipeline integration.
