"""Comprehensive unit tests for the pure ledger engine based on docs/ledger.md."""

import pytest

from app.schemas.ledger import (
    ExpenseRecord,
    SettlementRecord,
    SplitMode,
    SuggestedTransfer,
)
from app.services.ledger import (
    allocate,
    net_positions,
    simplify,
)


class TestAllocateWorkedExamples:
    """Validate all worked examples specified in docs/ledger.md."""

    def test_example_1_step_1_equal_groceries(self):
        """Step 1: Alex pays ₹3,000 (300000 paise) split equally among 3."""
        participants = ["usr_alex", "usr_blair", "usr_casey"]
        shares = allocate(300000, participants, SplitMode.EQUAL)
        assert shares == {
            "usr_alex": 100000,
            "usr_blair": 100000,
            "usr_casey": 100000,
        }
        assert sum(shares.values()) == 300000

    def test_example_1_step_4_chai_tie_breaking(self):
        """Step 4: Casey pays ₹100 (10000 paise) split equally among 3.

        Alex receives the +1 paisa due to fixed tie order (Alex, Blair, Casey).
        """
        participants = ["usr_alex", "usr_blair", "usr_casey"]
        shares = allocate(10000, participants, "equal")
        assert shares == {
            "usr_alex": 3334,
            "usr_blair": 3333,
            "usr_casey": 3333,
        }
        assert sum(shares.values()) == 10000

    def test_example_2_exact_split(self):
        """Section 8.2.1: Exact split of ₹150 (15000 paise) - 6000, 5000, 4000."""
        participants = ["usr_alex", "usr_blair", "usr_casey"]
        weights = [6000, 5000, 4000]
        shares = allocate(15000, participants, "exact", weights=weights)
        assert shares == {
            "usr_alex": 6000,
            "usr_blair": 5000,
            "usr_casey": 4000,
        }
        assert sum(shares.values()) == 15000

    def test_example_2_percentage_split_fractional_remainders(self):
        """Section 8.2.2: ₹55.55 (5555 paise) with weights 50%, 25%, 25%.

        Blair and Casey receive +1 leftover paisa over Alex.
        """
        participants = ["usr_alex", "usr_blair", "usr_casey"]
        weights = [50.0, 25.0, 25.0]
        shares = allocate(5555, participants, "percentage", weights=weights)
        assert shares == {
            "usr_alex": 2777,
            "usr_blair": 1389,
            "usr_casey": 1389,
        }
        assert sum(shares.values()) == 5555

    def test_example_2_parts_split(self):
        """Section 8.2.3: ₹100.00 (10000 paise) with 3:2:2 parts.

        Alex receives 4286, Blair 2857, Casey 2857.
        """
        participants = ["usr_alex", "usr_blair", "usr_casey"]
        weights = [3, 2, 2]
        shares = allocate(10000, participants, "parts", weights=weights)
        assert shares == {
            "usr_alex": 4286,
            "usr_blair": 2857,
            "usr_casey": 2857,
        }
        assert sum(shares.values()) == 10000


class TestNetPositionsWorkedExamples:
    """Validate net positions lifecycle from docs/ledger.md."""

    def test_canonical_lifecycle_alex_blair_casey(self):
        """Follow steps 1 to 4 of Worked Example 1."""
        participants = ["usr_alex", "usr_blair", "usr_casey"]

        # Step 1: Alex pays 300000 for groceries, equal split
        groceries_shares = allocate(300000, participants, "equal")
        exp1 = ExpenseRecord(
            paid_by="usr_alex",
            amount_paise=300000,
            shares=groceries_shares,
        )
        pos1 = net_positions([exp1], [])
        assert pos1 == {
            "usr_alex": 200000,
            "usr_blair": -100000,
            "usr_casey": -100000,
        }
        assert sum(pos1.values()) == 0

        # Step 2: Blair repays Alex ₹1,000 (100000 paise)
        stl1 = SettlementRecord(
            from_user="usr_blair",
            to_user="usr_alex",
            amount_paise=100000,
        )
        pos2 = net_positions([exp1], [stl1])
        assert pos2 == {
            "usr_alex": 100000,
            "usr_blair": 0,
            "usr_casey": -100000,
        }
        assert sum(pos2.values()) == 0

        # Step 3: Alex adds personal expense (₹500 metro recharge)
        exp_personal = ExpenseRecord(
            paid_by="usr_alex",
            amount_paise=50000,
            shares={"usr_alex": 50000},
        )
        pos3 = net_positions([exp1, exp_personal], [stl1])
        # Personal expense has net impact 0 on Alex (+50000 paid - 50000 share)
        assert pos3 == {
            "usr_alex": 100000,
            "usr_blair": 0,
            "usr_casey": -100000,
        }

        # Step 4: Casey pays ₹100 for chai, equal split
        chai_shares = allocate(10000, participants, "equal")
        exp2 = ExpenseRecord(
            paid_by="usr_casey",
            amount_paise=10000,
            shares=chai_shares,
        )
        pos4 = net_positions([exp1, exp_personal, exp2], [stl1])
        assert pos4 == {
            "usr_alex": 96666,
            "usr_blair": -3333,
            "usr_casey": -93333,
        }
        assert sum(pos4.values()) == 0

    def test_example_3_mixed_contributions_multiple_payers(self):
        """Section 8.3: Weekend Villa Rental ₹6,000 (600000 paise).

        Alex pays 400000, Blair pays 200000. Equal split of 200000 each.
        """
        exp = ExpenseRecord(
            payments={"usr_alex": 400000, "usr_blair": 200000},
            shares={"usr_alex": 200000, "usr_blair": 200000, "usr_casey": 200000},
        )
        pos = net_positions([exp], [])
        assert pos == {
            "usr_alex": 200000,
            "usr_blair": 0,
            "usr_casey": -200000,
        }
        assert sum(pos.values()) == 0

    def test_example_5_refund_via_edit(self):
        """Section 8.5: Original ₹3,000 groceries edited to ₹2,400."""
        participants = ["usr_alex", "usr_blair", "usr_casey"]
        shares_after_refund = allocate(240000, participants, "equal")
        assert shares_after_refund == {
            "usr_alex": 80000,
            "usr_blair": 80000,
            "usr_casey": 80000,
        }
        exp_edited = ExpenseRecord(
            paid_by="usr_alex",
            amount_paise=240000,
            shares=shares_after_refund,
        )
        pos = net_positions([exp_edited], [])
        assert pos == {
            "usr_alex": 160000,
            "usr_blair": -80000,
            "usr_casey": -80000,
        }
        assert sum(pos.values()) == 0


class TestDebtSimplificationWorkedExamples:
    """Validate greedy debt simplification from Section 8.4."""

    def test_example_4_greedy_debt_simplification(self):
        """Section 8.4: 4-person flat with members A, B, C, D."""
        initial_positions = {
            "A": 300000,
            "B": 100000,
            "C": -250000,
            "D": -150000,
        }
        transfers = simplify(initial_positions)
        assert len(transfers) == 3

        # Iteration 1: C pays A 250000
        assert transfers[0].from_user == "C"
        assert transfers[0].to_user == "A"
        assert transfers[0].amount_paise == 250000

        # Iteration 2: D pays B 100000
        assert transfers[1].from_user == "D"
        assert transfers[1].to_user == "B"
        assert transfers[1].amount_paise == 100000

        # Iteration 3: D pays A 50000
        assert transfers[2].from_user == "D"
        assert transfers[2].to_user == "A"
        assert transfers[2].amount_paise == 50000

        # Verify that applying these transfers resolves every balance to 0
        resolved = dict(initial_positions)
        for t in transfers:
            resolved[t.from_user] += t.amount_paise
            resolved[t.to_user] -= t.amount_paise

        assert all(bal == 0 for bal in resolved.values())


class TestLedgerValidationAndErrors:
    """Validate input constraints and error behaviors."""

    def test_allocate_empty_participants(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            allocate(1000, [], "equal")

    def test_allocate_duplicate_participants(self):
        with pytest.raises(ValueError, match="duplicate"):
            allocate(1000, ["p1", "p2", "p1"], "equal")

    def test_allocate_negative_amount(self):
        with pytest.raises(ValueError, match="non-negative"):
            allocate(-500, ["p1", "p2"], "equal")

    def test_allocate_invalid_amount_type(self):
        with pytest.raises(ValueError, match="must be an integer"):
            allocate("1000", ["p1", "p2"], "equal")  # type: ignore[arg-type]

    def test_allocate_unsupported_mode(self):
        with pytest.raises(ValueError, match="Unsupported split mode"):
            allocate(1000, ["p1", "p2"], "random_mode")

    def test_allocate_exact_sum_mismatch(self):
        with pytest.raises(
            ValueError, match="sum to 900 paise, but total expense is 1000"
        ):
            allocate(1000, ["p1", "p2"], "exact", weights=[500, 400])

    def test_allocate_percentage_sum_mismatch(self):
        with pytest.raises(ValueError, match="must sum to 100.00%"):
            allocate(1000, ["p1", "p2"], "percentage", weights=[50.0, 40.0])

    def test_allocate_parts_zero_total(self):
        with pytest.raises(ValueError, match="greater than zero"):
            allocate(1000, ["p1", "p2"], "parts", weights=[0, 0])

    def test_allocate_weights_length_mismatch(self):
        with pytest.raises(ValueError, match="does not match participants"):
            allocate(1000, ["p1", "p2"], "exact", weights=[1000])

    def test_allocate_dict_weights(self):
        participants = ["alice", "bob"]
        shares = allocate(1000, participants, "parts", weights={"alice": 3, "bob": 1})
        assert shares == {"alice": 750, "bob": 250}

    def test_allocate_zero_amount(self):
        participants = ["alice", "bob", "charlie"]
        shares = allocate(0, participants, "equal")
        assert shares == {"alice": 0, "bob": 0, "charlie": 0}

    def test_simplify_non_zero_sum(self):
        with pytest.raises(ValueError, match="must be zero"):
            simplify({"A": 100, "B": -50})

    def test_simplify_already_settled(self):
        transfers = simplify({"A": 0, "B": 0, "C": 0})
        assert transfers == []

    def test_simplify_empty_positions(self):
        assert simplify({}) == []

    def test_settlement_same_user_error(self):
        with pytest.raises(ValueError, match="from and to the same user"):
            net_positions(
                [],
                [
                    SettlementRecord(
                        from_user="alice", to_user="alice", amount_paise=100
                    )
                ],
            )

    def test_settlement_negative_amount_error(self):
        with pytest.raises(Exception):
            SettlementRecord(from_user="alice", to_user="bob", amount_paise=-100)

    def test_suggested_transfer_iter_unpacking(self):
        t = SuggestedTransfer(from_user="alice", to_user="bob", amount_paise=500)
        from_u, to_u, amt = t
        assert from_u == "alice"
        assert to_u == "bob"
        assert amt == 500
