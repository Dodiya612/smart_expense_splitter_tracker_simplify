# Bill Evaluation Test Set (Task T-11 / Story US-16)

This directory contains the **frozen evaluation dataset of 40 bills** for testing Optical Character Recognition (OCR) and expense extraction models for Coinscious (Task **T-11**, Story **US-16: Scan Bill to Create Expense**).

---

## Taxonomy and Distribution

The 40 bills cover all 6 required domains with realistic Indian commercial templates, itemizations, GST breakdowns, and payment methods:

| Category | Count | Merchant Examples | Typical Items |
|---|---|---|---|
| **Restaurant** | 7 | Haldiram's, Domino's, Starbucks, Sagar Gaire, Barbeque Nation, Chai Point, Mainland China | Dine-in & QSR items, beverage, dessert, CGST/SGST |
| **Grocery** | 7 | D-Mart, Reliance Smart, Nature's Basket, BigBasket, Blinkit, Zepto, Local Kirana | Produce, dairy, staples, packaged food, delivery fee |
| **Pharmacy** | 7 | Apollo Pharmacy, MedPlus, Netmeds, Wellness Forever, Tata 1mg, Frank Ross, Guardian | OTC medicines, prescription drugs, lab tests, supplements |
| **Fuel** | 7 | Indian Oil, BPCL, HPCL, Shell India, Nayara Energy, Gujarat Gas (CNG), Jio-bp | Petrol, Speed, Diesel, CNG, volume, rate/L |
| **Utility** | 6 | Adani Electricity, Torrent Power, JioFiber, Airtel Postpaid, Mahanagar Gas, Municipal Water | Power kWh, broadband, cellular rental, PNG SCM, water KL |
| **Online Orders** | 6 | Amazon India, Flipkart, Myntra, Swiggy Food, Zomato, Nykaa | Electronics, apparel, food delivery, cosmetics, IGST |
| **Total** | **40** | | |

---

## Directory Structure

```
evals/bills/
├── README.md               # This documentation and evaluation guide
├── CONSENT.md              # Privacy compliance, redaction note, and consent declaration
├── ground_truth.json       # Structured annotations including line items and redacted fields
├── ground_truth.csv        # Tabular summary of all 40 bills for fast metric evaluation
└── receipts/               # 40 individual raw receipt text files (BILL-0001 to BILL-0040)
    ├── BILL-0001_restaurant.txt
    ├── BILL-0002_restaurant.txt
    ...
    └── BILL-0040_online_orders.txt
```

---

## Ground Truth Schema

Each entry in `ground_truth.json` follows this schema:

```json
{
  "bill_id": "BILL-0001",
  "category": "Restaurant",
  "merchant_name": "Haldiram's Express",
  "date": "2026-09-15",
  "currency": "INR",
  "subtotal": 520.00,
  "tax": 26.00,
  "total_amount": 546.00,
  "payment_mode": "UPI",
  "items": [
    {
      "item_name": "Special Chole Bhature",
      "quantity": 2,
      "unit_price": 160.00,
      "total_price": 320.00
    }
  ],
  "redacted_fields": {
    "customer_name": "[REDACTED_CUSTOMER]",
    "phone_number": "+91 98XXX XXXXX",
    "upi_id": "[REDACTED]@okhdfcbank"
  }
}
```

---

## Privacy & Redaction

In compliance with India's DPDP Act 2023 and project privacy standards:
- Customer names are replaced with `[REDACTED_CUSTOMER]`, `[REDACTED_BUYER]`, etc.
- Phone numbers are masked (`+91 98XXX XXXXX`).
- Addresses and locations are redacted (`[REDACTED_ADDRESS]`).
- Card numbers are masked to the last 4 digits (`XXXX-XXXX-XXXX-1234`).
- UPI IDs are masked (`[REDACTED]@bank`).

See [CONSENT.md](CONSENT.md) for full compliance details.

---

## Acceptance Criteria Checklist (Issue #37)

- [x] **Dataset contains 40 bills**: Exactly 40 receipt files present under `receipts/`.
- [x] **Required fields are labelled**: Merchant, date, subtotal, tax, total, payment mode, items.
- [x] **Personal details are redacted**: All customer identifying information masked.
- [x] **Consent note is included**: Stored at `evals/bills/CONSENT.md`.
- [x] **Dataset is committed under `evals/bills`**: Self-contained in this directory.
