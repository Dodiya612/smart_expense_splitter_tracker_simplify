#!/usr/bin/env python3
"""Evaluation Runner for Bill OCR Extraction Pipeline (Task T-47 / Story US-16 / T-11).

Evaluates the rule parser and extraction pipeline on the frozen test set of 40 bills
(evals/bills) against the ground truth annotations. Measures accuracy for Date, Total,
Merchant, and line items, broken down by category.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Add project root and backend to python path for modular execution
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.rule_parser import RuleParser


def run_evaluation() -> dict[str, any]:
    bills_dir = PROJECT_ROOT / "evals" / "bills"
    gt_file = bills_dir / "ground_truth.json"
    receipts_dir = bills_dir / "receipts"

    if not gt_file.exists():
        raise FileNotFoundError(f"Ground truth file not found at {gt_file}")

    with open(gt_file, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    total_bills = len(ground_truth)
    date_correct = 0
    total_correct = 0
    merchant_correct = 0
    items_extracted_count = 0

    category_stats: dict[str, dict[str, int]] = {}

    results = []

    for item in ground_truth:
        bill_id = item["bill_id"]
        category = item["category"]
        gt_date = item["date"]
        gt_total = float(item["total_amount"])
        gt_merchant = item["merchant_name"]

        cat_slug = category.lower().replace(" ", "_")
        receipt_path = receipts_dir / f"{bill_id}_{cat_slug}.txt"

        if not receipt_path.exists():
            # Try finding by bill_id prefix
            candidates = list(receipts_dir.glob(f"{bill_id}_*.txt"))
            if candidates:
                receipt_path = candidates[0]
            else:
                raise FileNotFoundError(f"Receipt file missing for {bill_id}")

        with open(receipt_path, "r", encoding="utf-8") as rf:
            receipt_text = rf.read()

        parsed = RuleParser.parse_text(receipt_text)

        # 1. Date match check
        extracted_date_str = parsed.expense_date.isoformat() if parsed.expense_date else None
        d_match = (extracted_date_str == gt_date)
        if d_match:
            date_correct += 1

        # 2. Total amount match check
        extracted_total = parsed.total_amount
        t_match = (
            extracted_total is not None
            and abs(extracted_total - gt_total) < 0.01
        )
        if t_match:
            total_correct += 1

        # 3. Merchant match check (fuzzy substring/token overlap)
        extracted_merchant = parsed.merchant or ""
        m_norm_gt = gt_merchant.lower().replace("'", "").replace(".", "")
        m_norm_ex = extracted_merchant.lower().replace("'", "").replace(".", "")
        # Check if one contains the other or primary tokens match
        gt_tokens = set(m_norm_gt.split())
        ex_tokens = set(m_norm_ex.split())
        m_match = bool(
            m_norm_gt in m_norm_ex
            or m_norm_ex in m_norm_gt
            or len(gt_tokens.intersection(ex_tokens)) >= 1
        )
        if m_match:
            merchant_correct += 1

        # 4. Items check
        items_count = len(parsed.items)
        if items_count > 0:
            items_extracted_count += 1

        # Category accumulation
        if category not in category_stats:
            category_stats[category] = {"total": 0, "date_ok": 0, "total_ok": 0, "merchant_ok": 0}
        category_stats[category]["total"] += 1
        if d_match:
            category_stats[category]["date_ok"] += 1
        if t_match:
            category_stats[category]["total_ok"] += 1
        if m_match:
            category_stats[category]["merchant_ok"] += 1

        results.append({
            "bill_id": bill_id,
            "category": category,
            "date_match": d_match,
            "total_match": t_match,
            "merchant_match": m_match,
            "gt_date": gt_date,
            "ex_date": extracted_date_str,
            "gt_total": gt_total,
            "ex_total": extracted_total,
            "confidence": parsed.confidence,
        })

    date_acc = (date_correct / total_bills) * 100
    total_acc = (total_correct / total_bills) * 100
    merchant_acc = (merchant_correct / total_bills) * 100

    print("\n" + "=" * 70)
    print("      COINSCIOUS OCR PIPELINE EVALUATION REPORT (Task T-47 / US-16)")
    print("=" * 70)
    print(f"Total Evaluated Bills: {total_bills}")
    print(f"Date Extraction Accuracy:     {date_correct:2d}/{total_bills} ({date_acc:5.1f}%)")
    print(f"Total Amount Accuracy:       {total_correct:2d}/{total_bills} ({total_acc:5.1f}%)")
    print(f"Merchant Recognition Rate:   {merchant_correct:2d}/{total_bills} ({merchant_acc:5.1f}%)")
    print(f"Bills with Line Items:       {items_extracted_count:2d}/{total_bills} ({(items_extracted_count/total_bills)*100:5.1f}%)")
    print("-" * 70)
    print(f"{'Category':<16} | {'Count':<5} | {'Date Acc':<10} | {'Total Acc':<10} | {'Merchant Acc':<12}")
    print("-" * 70)
    for cat, stats in sorted(category_stats.items()):
        c_tot = stats["total"]
        c_date = (stats["date_ok"] / c_tot) * 100
        c_amount = (stats["total_ok"] / c_tot) * 100
        c_merch = (stats["merchant_ok"] / c_tot) * 100
        print(f"{cat:<16} | {c_tot:<5} | {c_date:5.1f}%     | {c_amount:5.1f}%     | {c_merch:5.1f}%")
    print("=" * 70)

    # Acceptance criteria verification
    assert total_bills == 40, f"Expected 40 bills, got {total_bills}"
    assert date_acc >= 95.0, f"Date accuracy below 95% threshold: {date_acc:.1f}%"
    assert total_acc >= 95.0, f"Total accuracy below 95% threshold: {total_acc:.1f}%"

    print("\n[PASSED] Acceptance Criteria for T-47 / US-16 successfully verified!\n")

    return {
        "total_bills": total_bills,
        "date_accuracy": date_acc,
        "total_accuracy": total_acc,
        "merchant_accuracy": merchant_acc,
        "category_stats": category_stats,
    }


if __name__ == "__main__":
    run_evaluation()
