"""Property-based tests for the Coinscious ledger engine using Hypothesis.

Requirements coverage:
- docs/ledger.md Section 9.2 (T-05 / US-36)
- Invariant 1: Conservation of Shares (sum(shares) == amount_paise)
- Invariant 2: Zero-Sum Balance (sum(net_position) == 0)
- Invariant 3: Deterministic Output (identical inputs -> identical allocations)
- Invariant 4: Non-Negativity (all allocated shares >= 0)
- Invariant 5: Debt Simplification Correctness (transfers zero out balances)
- Executes at least 10,000 randomized test cases.
"""

from typing import List, Tuple

from hypothesis import given, settings
from hypothesis import strategies as st

from app.schemas.ledger import (
    ExpenseRecord,
    SettlementRecord,
)
from app.services.ledger import (
    allocate,
    net_positions,
    simplify,
)

# ── Strategies ──────────────────────────────────────────────────────────

# Member identifiers pool
MEMBER_IDS = [f"usr_{chr(ord('a') + i)}" for i in range(12)]


@st.composite
def participants_strategy(draw, min_size: int = 1, max_size: int = 8) -> List[str]:
    """Generate a non-empty list of unique participant identifiers."""
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    return draw(
        st.lists(
            st.sampled_from(MEMBER_IDS),
            min_size=size,
            max_size=size,
            unique=True,
        )
    )


@st.composite
def allocate_case_strategy(draw) -> Tuple[int, List[str], str, object]:
    """Generate arbitrary valid inputs for allocate() across all 4 split modes."""
    participants = draw(participants_strategy())
    n = len(participants)
    amount_paise = draw(st.integers(min_value=0, max_value=100_000_000))
    mode = draw(st.sampled_from(["equal", "exact", "percentage", "parts"]))

    weights = None

    if mode == "exact":
        if n == 1:
            weights = [amount_paise]
        elif amount_paise == 0:
            weights = [0] * n
        else:
            cut_points = sorted(
                draw(
                    st.lists(
                        st.integers(min_value=0, max_value=amount_paise),
                        min_size=n - 1,
                        max_size=n - 1,
                    )
                )
            )
            points = [0] + cut_points + [amount_paise]
            weights = [points[i + 1] - points[i] for i in range(n)]

    elif mode == "percentage":
        if n == 1:
            weights = [100.0]
        else:
            # Cut points in [0, 10000] (basis points) for 2 decimal places
            cuts = sorted(
                draw(
                    st.lists(
                        st.integers(min_value=0, max_value=10000),
                        min_size=n - 1,
                        max_size=n - 1,
                    )
                )
            )
            points = [0] + cuts + [10000]
            pcts = [(points[i + 1] - points[i]) / 100.0 for i in range(n)]
            pcts[-1] = round(100.0 - sum(pcts[:-1]), 2)
            if pcts[-1] < 0:
                pcts = [100.0 / n] * n
            weights = pcts

    elif mode == "parts":
        weights = draw(
            st.lists(st.integers(min_value=1, max_value=100), min_size=n, max_size=n)
        )

    return amount_paise, participants, mode, weights


@st.composite
def ledger_scenario_strategy(
    draw,
) -> Tuple[List[ExpenseRecord], List[SettlementRecord], List[str]]:
    """Generate an arbitrary sequence of valid expenses and settlements."""
    group_size = draw(st.integers(min_value=2, max_value=6))
    group_members = MEMBER_IDS[:group_size]

    num_expenses = draw(st.integers(min_value=1, max_value=5))
    expenses: List[ExpenseRecord] = []

    for _ in range(num_expenses):
        part_size = draw(st.integers(min_value=1, max_value=group_size))
        participants = draw(
            st.lists(
                st.sampled_from(group_members),
                min_size=part_size,
                max_size=part_size,
                unique=True,
            )
        )
        amount_paise = draw(st.integers(min_value=1, max_value=5_000_000))
        mode = draw(st.sampled_from(["equal", "parts"]))
        weights = None
        if mode == "parts":
            weights = draw(
                st.lists(
                    st.integers(min_value=1, max_value=20),
                    min_size=len(participants),
                    max_size=len(participants),
                )
            )

        shares = allocate(amount_paise, participants, mode, weights)

        payer_mode = draw(st.sampled_from(["single", "mixed"]))
        if payer_mode == "single":
            payer = draw(st.sampled_from(group_members))
            expenses.append(
                ExpenseRecord(
                    paid_by=payer,
                    amount_paise=amount_paise,
                    shares=shares,
                )
            )
        else:
            payer1, payer2 = draw(
                st.lists(
                    st.sampled_from(group_members),
                    min_size=2,
                    max_size=2,
                    unique=True,
                )
            )
            pay1 = draw(st.integers(min_value=0, max_value=amount_paise))
            pay2 = amount_paise - pay1
            expenses.append(
                ExpenseRecord(
                    payments={payer1: pay1, payer2: pay2},
                    shares=shares,
                )
            )

    num_settlements = draw(st.integers(min_value=0, max_value=3))
    settlements: List[SettlementRecord] = []
    for _ in range(num_settlements):
        u1, u2 = draw(
            st.lists(
                st.sampled_from(group_members),
                min_size=2,
                max_size=2,
                unique=True,
            )
        )
        amt = draw(st.integers(min_value=1, max_value=500_000))
        settlements.append(
            SettlementRecord(
                from_user=u1,
                to_user=u2,
                amount_paise=amt,
            )
        )

    return expenses, settlements, group_members


# ── Property Tests ───────────────────────────────────────────────────────


class TestLedgerProperties:
    """Hypothesis property-based tests covering >= 10,000 cases."""

    @settings(max_examples=10000, deadline=None)
    @given(allocate_case_strategy())
    def test_property_allocate_conservation_and_invariants(self, case):
        """Invariant 1, 3, 4: Conservation, determinism, and non-negativity."""
        amount_paise, participants, mode, weights = case

        shares = allocate(amount_paise, participants, mode, weights)

        # 1. Invariant: Conservation of Shares (sum(shares) == amount_paise)
        assert sum(shares.values()) == amount_paise, (
            f"Shares sum to {sum(shares.values())}, expected {amount_paise} "
            f"(mode={mode})"
        )

        # 2. Invariant: Non-Negativity (all shares >= 0)
        for p, s in shares.items():
            assert s >= 0, f"Negative share for {p}: {s}"

        # 3. Invariant: Deterministic Output
        shares_repeat = allocate(amount_paise, participants, mode, weights)
        assert shares == shares_repeat, (
            "Identical inputs produced different allocations"
        )

        # 4. Mode-specific property checks
        if mode == "equal" and len(participants) > 1 and amount_paise > 0:
            diff = max(shares.values()) - min(shares.values())
            assert diff <= 1, (
                f"Equal split difference between max and min share is {diff} (> 1)"
            )

    @settings(max_examples=1000, deadline=None)
    @given(ledger_scenario_strategy())
    def test_property_net_positions_zero_sum_and_simplification(self, scenario):
        """Invariant 2 & 5: Zero-sum net positions and debt simplification."""
        expenses, settlements, group_members = scenario

        positions = net_positions(expenses, settlements)

        # 1. Invariant: Zero-Sum Conservation of Money
        total_balance = sum(positions.values())
        assert total_balance == 0, (
            f"Net positions do not sum to zero: sum = {total_balance} paise"
        )

        # 2. Invariant: Simplification resolves all balances to zero
        transfers = simplify(positions)

        # Number of transfers <= N - 1
        non_zero_count = sum(1 for v in positions.values() if v != 0)
        if non_zero_count > 0:
            assert len(transfers) <= non_zero_count - 1, (
                f"Simplification produced {len(transfers)} transfers for "
                f"{non_zero_count} debtors/creditors"
            )
        else:
            assert len(transfers) == 0

        # Verify applying transfers completely zeros out all positions
        tentative = dict(positions)
        for t in transfers:
            assert t.amount_paise > 0, "Transfer amount must be positive"
            assert t.from_user != t.to_user, "Transfer cannot be to self"
            tentative[t.from_user] += t.amount_paise
            tentative[t.to_user] -= t.amount_paise

        for user_id, bal in tentative.items():
            assert bal == 0, (
                f"Member {user_id} balance was not zero after simplification: {bal}"
            )
