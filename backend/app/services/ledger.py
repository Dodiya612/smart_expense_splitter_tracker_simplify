"""Pure ledger engine functions for splits, net positions, and debt simplification.

This module implements the deterministic financial arithmetic defined in docs/ledger.md:
1. allocate() - Largest-remainder allocation across four split modes.
2. net_positions() - Derives members' net credit/debit balances in integer paise.
3. simplify() - Greedy debt simplification to suggest minimal settlement transfers.

All monetary arithmetic operates strictly on 64-bit integer paise with zero
floating-point math at calculation boundaries.
"""

from collections import defaultdict
from decimal import Decimal
from fractions import Fraction
from typing import Any, Dict, List, Optional, Union

from app.schemas.ledger import (
    ExpenseRecord,
    SettlementRecord,
    SplitMode,
    SuggestedTransfer,
)

__all__ = [
    "ExpenseRecord",
    "SettlementRecord",
    "SplitMode",
    "SuggestedTransfer",
    "allocate",
    "net_positions",
    "simplify",
]


def allocate(
    amount_paise: int,
    participants: List[str],
    split_mode: Union[SplitMode, str],
    weights: Optional[Union[List[Union[int, float]], Dict[str, Any]]] = None,
) -> Dict[str, int]:
    """Allocate paise across participants using largest-remainder with fixed tie order.

    Supports four split modes:
    - equal: Divided equally; leftover paise distributed in participant order.
    - exact: Explicit integer paise per participant. Sum must equal amount_paise.
    - percentage: Percentages summing to 100.00%. Quotas rounded via Hare-Niemeyer.
    - parts: Integer parts/ratios per participant. Quotas rounded via Hare-Niemeyer.

    Args:
        amount_paise: Total amount to allocate, in integer paise (non-negative).
        participants: Ordered unique member identifiers defining fixed tie order.
        split_mode: Split mode string or SplitMode enum.
        weights: Mode-specific weights (exact paise amounts, percentages, or parts).

    Returns:
        Dict mapping each participant identifier to their allocated share in paise.

    Raises:
        ValueError: If parameters are invalid or weights do not meet invariants.
    """
    if isinstance(amount_paise, bool) or not isinstance(amount_paise, int):
        raise ValueError(
            f"amount_paise must be an integer, got {type(amount_paise).__name__}"
        )
    if amount_paise < 0:
        raise ValueError(f"amount_paise must be non-negative, got {amount_paise}")

    if not isinstance(participants, (list, tuple)):
        raise ValueError("participants must be a list or tuple of member identifiers")
    if len(participants) == 0:
        raise ValueError("participants list cannot be empty")
    if len(set(participants)) != len(participants):
        raise ValueError("participants list contains duplicate identifiers")

    mode_str = (
        split_mode.value if isinstance(split_mode, SplitMode) else str(split_mode)
    )
    normalized_mode = mode_str.strip().lower().replace("-", "_")

    if normalized_mode not in (
        "equal",
        "exact",
        "percentage",
        "percent",
        "parts",
        "parts_based",
    ):
        raise ValueError(f"Unsupported split mode: '{split_mode}'")

    n = len(participants)

    # 1. Equal Split Mode
    if normalized_mode == "equal":
        if amount_paise == 0:
            return {p: 0 for p in participants}

        base = amount_paise // n
        remainder = amount_paise % n
        # First `remainder` participants in fixed order receive +1 paisa
        return {
            p: base + (1 if i < remainder else 0) for i, p in enumerate(participants)
        }

    # 2. Exact Split Mode
    if normalized_mode == "exact":
        if weights is None:
            raise ValueError("weights are required for exact split mode")

        if isinstance(weights, dict):
            missing = [p for p in participants if p not in weights]
            if missing:
                raise ValueError(f"Missing exact weights for participants: {missing}")
            exact_shares = [weights[p] for p in participants]
        elif isinstance(weights, (list, tuple)):
            if len(weights) != n:
                raise ValueError(
                    f"Length of weights ({len(weights)}) does not match "
                    f"participants ({n})"
                )
            exact_shares = list(weights)
        else:
            raise ValueError("weights must be a list or dict")

        for i, w in enumerate(exact_shares):
            if isinstance(w, bool) or not isinstance(w, int):
                raise ValueError(
                    f"Exact share for '{participants[i]}' must be an integer, got {w}"
                )
            if w < 0:
                raise ValueError(
                    f"Exact share for '{participants[i]}' cannot be negative: {w}"
                )

        total_exact = sum(exact_shares)
        if total_exact != amount_paise:
            raise ValueError(
                f"Exact shares sum to {total_exact} paise, but total expense is "
                f"{amount_paise} paise (delta: {total_exact - amount_paise} paise)"
            )

        return {p: s for p, s in zip(participants, exact_shares)}

    # 3. Percentage Split Mode
    if normalized_mode in ("percentage", "percent"):
        if weights is None:
            raise ValueError("weights are required for percentage split mode")

        if isinstance(weights, dict):
            missing = [p for p in participants if p not in weights]
            if missing:
                raise ValueError(
                    f"Missing percentage weights for participants: {missing}"
                )
            pct_list = [weights[p] for p in participants]
        elif isinstance(weights, (list, tuple)):
            if len(weights) != n:
                raise ValueError(
                    f"Length of weights ({len(weights)}) does not match "
                    f"participants ({n})"
                )
            pct_list = list(weights)
        else:
            raise ValueError("weights must be a list or dict")

        # Convert percentages to Decimal with up to 4 decimal places
        pct_decimals: List[Decimal] = []
        for i, p_val in enumerate(pct_list):
            if isinstance(p_val, bool):
                raise ValueError(
                    f"Percentage for '{participants[i]}' cannot be a boolean"
                )
            try:
                dec = Decimal(str(p_val))
            except Exception as e:
                raise ValueError(
                    f"Invalid percentage value '{p_val}' for '{participants[i]}': {e}"
                ) from e
            if dec < 0:
                raise ValueError(
                    f"Percentage for '{participants[i]}' cannot be negative: {dec}"
                )
            pct_decimals.append(dec)

        total_pct = sum(pct_decimals)
        # Invariant: percentages must sum strictly to 100.00% (tolerance 0.01%)
        if abs(total_pct - Decimal("100")) > Decimal("0.01"):
            raise ValueError(
                f"Percentages must sum to 100.00%, got {total_pct}% "
                f"(delta: {total_pct - Decimal('100')}%)"
            )

        if amount_paise == 0:
            return {p: 0 for p in participants}

        # Largest-remainder method over fractions: Quota = (T * pct) / 100
        # Represent percentage as fraction over 10000 (allows 2 decimal places: 33.33% = 3333/10000)
        # Using exact Python Fraction to prevent any floating-point imprecision
        quotas: List[Fraction] = [
            Fraction(amount_paise) * Fraction(dec) / Fraction(100)
            for dec in pct_decimals
        ]

        base_shares = [int(q) for q in quotas]
        remainders = [q - Fraction(b) for q, b in zip(quotas, base_shares)]
        allocated_so_far = sum(base_shares)
        unallocated_paise = amount_paise - allocated_so_far

        # Rank participants by:
        # 1. Fractional remainder descending (-remainder)
        # 2. Fixed member order ascending (index i)
        ranked_indices = sorted(
            range(n),
            key=lambda idx: (-remainders[idx], idx),
        )

        final_shares = list(base_shares)
        for i in range(unallocated_paise):
            target_idx = ranked_indices[i]
            final_shares[target_idx] += 1

        return {p: s for p, s in zip(participants, final_shares)}

    # 4. Parts / Ratios Split Mode
    if normalized_mode in ("parts", "parts_based"):
        if weights is None:
            raise ValueError("weights are required for parts split mode")

        if isinstance(weights, dict):
            missing = [p for p in participants if p not in weights]
            if missing:
                raise ValueError(f"Missing parts weights for participants: {missing}")
            parts_list = [weights[p] for p in participants]
        elif isinstance(weights, (list, tuple)):
            if len(weights) != n:
                raise ValueError(
                    f"Length of weights ({len(weights)}) does not match "
                    f"participants ({n})"
                )
            parts_list = list(weights)
        else:
            raise ValueError("weights must be a list or dict")

        int_parts: List[int] = []
        for i, pt in enumerate(parts_list):
            if isinstance(pt, bool) or not isinstance(pt, int):
                raise ValueError(
                    f"Part for '{participants[i]}' must be an integer, got {pt}"
                )
            if pt < 0:
                raise ValueError(
                    f"Part for '{participants[i]}' cannot be negative: {pt}"
                )
            int_parts.append(pt)

        total_parts = sum(int_parts)
        if total_parts <= 0:
            raise ValueError(
                f"Total parts must be greater than zero, got {total_parts}"
            )

        if amount_paise == 0:
            return {p: 0 for p in participants}

        quotas = [
            Fraction(amount_paise * pt, total_parts) for pt in int_parts
        ]
        base_shares = [int(q) for q in quotas]
        remainders = [q - Fraction(b) for q, b in zip(quotas, base_shares)]
        allocated_so_far = sum(base_shares)
        unallocated_paise = amount_paise - allocated_so_far

        ranked_indices = sorted(
            range(n),
            key=lambda idx: (-remainders[idx], idx),
        )

        final_shares = list(base_shares)
        for i in range(unallocated_paise):
            target_idx = ranked_indices[i]
            final_shares[target_idx] += 1

        return {p: s for p, s in zip(participants, final_shares)}

    raise ValueError(f"Unhandled split mode: {split_mode}")


def net_positions(
    expenses: List[Union[ExpenseRecord, Dict[str, Any]]],
    settlements: List[Union[SettlementRecord, Dict[str, Any]]],
) -> Dict[str, int]:
    """Compute member net positions dynamically from raw records.

    Formula (docs/ledger.md Section 4.1):
        NP_i = (sum(cash_paid_i) + sum(settlements_paid_i)
                - sum(allocated_shares_i) - sum(settlements_received_i))

    Sign conventions:
        NP_i > 0: Creditor (others owe this member money)
        NP_i < 0: Debtor (this member owes money to others)
        NP_i = 0: Settled (even with the group)

    Invariant:
        sum(NP_i for all i) == 0 (zero-sum conservation of money)

    Args:
        expenses: List of ExpenseRecord objects or equivalent dicts.
        settlements: List of SettlementRecord objects or equivalent dicts.

    Returns:
        Dict mapping each participating user ID to their net position in whole paise.
    """
    balances: Dict[str, int] = defaultdict(int)

    for exp in expenses:
        exp_obj = exp if isinstance(exp, ExpenseRecord) else ExpenseRecord(**exp)
        payments = exp_obj.get_payments()
        shares = exp_obj.shares

        total_paid = sum(payments.values())
        total_shares = sum(shares.values())
        if total_paid != total_shares:
            raise ValueError(
                f"Expense payments ({total_paid} paise) must equal total "
                f"shares ({total_shares} paise)"
            )

        # Cash paid increases payer's net position (+ credit)
        for payer, paid_amt in payments.items():
            if paid_amt < 0:
                raise ValueError(f"Negative payment for '{payer}': {paid_amt}")
            balances[payer] += paid_amt

        # Personal share decreases consumer's net position (- liability)
        for participant, share_amt in shares.items():
            if share_amt < 0:
                raise ValueError(f"Negative share for '{participant}': {share_amt}")
            balances[participant] -= share_amt

    for stl in settlements:
        stl_obj = stl if isinstance(stl, SettlementRecord) else SettlementRecord(**stl)
        if stl_obj.amount_paise <= 0:
            raise ValueError(
                f"Settlement amount must be positive, got {stl_obj.amount_paise}"
            )
        if stl_obj.from_user == stl_obj.to_user:
            raise ValueError(
                f"Settlement cannot be from and to the same user: '{stl_obj.from_user}'"
            )

        # Debtor repaid money: net position increases towards zero
        balances[stl_obj.from_user] += stl_obj.amount_paise
        # Creditor received money: net position decreases towards zero
        balances[stl_obj.to_user] -= stl_obj.amount_paise

    return dict(balances)


def simplify(
    net_positions: Dict[str, int],
) -> List[SuggestedTransfer]:
    """Apply greedy debt simplification to propose minimal settlement transfers.

    Algorithm (docs/ledger.md Section 6.3):
        1. Identify largest debtor (most negative net position NP_min).
        2. Identify largest creditor (most positive net position NP_max).
        3. Propose settlement from debtor to creditor of min(|NP_min|, NP_max).
        4. Update tentative positions and repeat until all positions are zero.

    Deterministic tie-breaking:
        Ties among debtors or creditors are broken alphabetically by user ID.

    Args:
        net_positions: Dict mapping member IDs to net positions in paise
            (must sum to zero).

    Returns:
        List of SuggestedTransfer objects minimizing the total transactions needed.

    Raises:
        ValueError: If sum of net positions is not zero.
    """
    total = sum(net_positions.values())
    if total != 0:
        raise ValueError(
            f"Sum of net positions must be zero to simplify, got {total} paise"
        )

    # Work with non-zero balances
    pos: Dict[str, int] = {k: v for k, v in net_positions.items() if v != 0}
    transfers: List[SuggestedTransfer] = []

    while pos:
        debtors = [k for k, v in pos.items() if v < 0]
        creditors = [k for k, v in pos.items() if v > 0]

        if not debtors or not creditors:
            break

        # Largest debtor: most negative position. Tie-break by user ID ascending.
        debtor = min(debtors, key=lambda u: (pos[u], u))

        # Largest creditor: largest positive position. Tie-break by user ID ascending.
        creditor = min(creditors, key=lambda u: (-pos[u], u))

        # Transfer amount is min(|debt|, credit)
        amount = min(-pos[debtor], pos[creditor])
        transfers.append(
            SuggestedTransfer(
                from_user=debtor,
                to_user=creditor,
                amount_paise=amount,
            )
        )

        pos[debtor] += amount
        pos[creditor] -= amount

        if pos[debtor] == 0:
            del pos[debtor]
        if pos[creditor] == 0:
            del pos[creditor]

    return transfers
