# Coinscious — Money & Ledger Rules Specification

**Document Version:** 1.0  
**Status:** Ready for Team Review (`#dev`)  
**Sprint:** Sprint 0  
**User Story:** US-36 (Ledger Engine & Money Rules)  
**Owning Department:** Backend + Database (Group 28)  
**Requirements Traceability:** FR-16, DR-03, DR-06, DR-11, DR-13, DR-14, NFR-09, NFR-12  

---

## 1. Overview & Purpose

Coinscious is built upon **one unified, honest ledger**. In traditional workflows, personal budget trackers and bill splitters operate in silos: when one person pays ₹3,000 for a shared grocery bill across three roommates, a naive budgeting app logs an erroneous ₹3,000 expense against their budget, while a splitting app tracks ₹2,000 owed without clarifying real individual consumption.

Coinscious resolves this conflict through a single source of truth:
1. Every transaction records **who paid cash** and **each member's allocated share**.
2. **Personal spending and budgets** reflect only the user's allocated share.
3. **Group balances and debts** reflect the net difference between payments, shares, and settlements.
4. **Code does all financial maths** strictly on integer paise using deterministic rules; AI components never compute money figures.

This document formalizes the arithmetic, precision, split allocation, net position, settlement, and adjustment rules that govern the backend ledger engine (`allocate()`, `net_positions()`, and `simplify()`).

---

## 2. Monetary Precision & Currency Standards

### 2.1 Currency & Integer Storage
- **Version 1 Currency:** Indian Rupees (`INR`, `₹`).
- **Precision:** Sub-unit is the **paisa** ($1\text{ INR} = 100\text{ paise}$).
- **Database Storage:** Stored as PostgreSQL `BIGINT` representing whole paise (e.g., ₹250.00 is stored as `25000` paise).
- **Backend & Network:** Represented strictly as 64-bit signed integers in Python and JSON API payloads (`amount_paise: int`).

### 2.2 Floating-Point Prohibition
- **Binary floating-point arithmetic (`float`, `double`) is strictly prohibited** in money code, database columns, and API contracts.
- Formatting into fractional rupee values (e.g., `"₹250.00"`) occurs **only at presentation boundaries** (frontend UI and formatted export strings).
- All intermediate calculations, quotas, allocations, and sums must operate directly on whole paise.

---

## 3. Core Ledger Concepts: Cash Paid vs. Personal Share

| Concept | Definition | Budget & Analytics Impact | Group Balance Impact |
| :--- | :--- | :--- | :--- |
| **Cash Paid** | The actual monetary amount transferred out of a user's possession at the time of payment. | Reported separately as cash outflow; **not** counted as spending for others' portions. | Increases the user's net position (+ credit). |
| **Personal Share** (Allocated Share) | The exact portion of an expense assigned to a specific user for their own consumption. | **Counts as personal spending.** Drives category analytics, monthly budgets, and limit alerts. | Decreases the user's net position (- liability). |

### 3.1 Personal vs. Shared Expenses
1. **Personal Expense:**
   - Single payer ($U$), single participant ($U$).
   - $\text{cash\_paid} = \text{personal\_share} = \text{total\_amount}$.
   - Group balances are untouched; personal spending increases by $\text{total\_amount}$.
2. **Shared Expense:**
   - Paid by one or more group members; shared among $N$ group participants.
   - For a payer $P$: Cash fronted for other members ($\text{cash\_paid} - \text{personal\_share}$) is **not** personal spending; it is an outstanding receivable (debt owed to $P$).
   - For a non-paying participant $M$: $\text{cash\_paid} = 0$, but their personal spending increases by their allocated share.

---

## 4. Net Position & Sign Conventions

### 4.1 Net Position Formula
For any member $i$ within a group, their **Net Position** ($\text{NP}_i$) is dynamically derived from all active transactional records:

$$\text{NP}_i = \sum \text{cash\_paid}_i + \sum \text{settlements\_paid}_i - \sum \text{allocated\_shares}_i - \sum \text{settlements\_received}_i$$

Where all variables are positive integers in paise.

### 4.2 Sign Conventions
- **Positive Net Position ($\text{NP}_i > 0$): Creditor**  
  The member has paid more than their consumption and repayments received. **Others owe this member money.**
- **Negative Net Position ($\text{NP}_i < 0$): Debtor**  
  The member's allocated consumption and received repayments exceed what they paid. **This member owes money to others.**
- **Zero Net Position ($\text{NP}_i = 0$): Settled**  
  The member is completely even with the group; they neither owe nor are owed any money.

### 4.3 Fundamental Invariant: Zero-Sum Conservation
Within any group, money cannot be created or destroyed. The sum of all members' net positions must always sum to zero to the exact paisa:

$$\sum_{i \in \text{Group}} \text{NP}_i = 0$$

Every rupee paid is accounted for as an allocated share or a pending balance.

---

## 5. Split Modes & Largest-Remainder Rounding

Coinscious supports four split modes for shared expenses:
1. **Equal (`equal`):** Divided equally across all participants.
2. **Exact (`exact`):** Specific integer paise allocated per participant. Sum of shares must strictly equal $\text{total\_amount\_paise}$.
3. **Percentage (`percentage`):** Specified as percentages per participant. Percentages must sum to exactly $100.00\%$.
4. **Parts (`parts`):** Whole-number ratios/weights per participant (positive integers).

### 5.1 The Largest-Remainder Method (Hare-Niemeyer Algorithm)
When dividing an integer amount $T$ (in paise) among $N$ participants with weights $w_i$ (where $W = \sum_{i=1}^N w_i$):

1. **Calculate Exact Quota:**  
   $$Q_i = \frac{T \times w_i}{W}$$
2. **Assign Base Shares:**  
   Take the integer floor of each quota:
   $$s_i = \lfloor Q_i \rfloor$$
3. **Calculate Fractional Remainders:**  
   $$r_i = Q_i - s_i = \frac{(T \times w_i) \bmod W}{W}$$
4. **Calculate Remaining Unallocated Paise:**  
   $$R = T - \sum_{i=1}^N s_i \quad (0 \le R < N)$$
5. **Distribute Leftover Paise ($R$ paise):**  
   - Sort participants in descending order of fractional remainder $r_i$.
   - Award $+1$ paisa to the top $R$ participants in this ranked list.
6. **Deterministic Tie-Breaking Rule (Fixed Tie Order):**  
   - If two or more participants have identical fractional remainders $r_i$ (standard in equal splits where $w_i = 1$ and all remainders equal $(T \bmod N)/N$), ties are broken using the **fixed member order** (the participant order as established in the group/request list).
   - The first participant in the group's fixed order receives the first leftover paisa, the second receives the next, until all $R$ paise are distributed.

### 5.2 Guarantee
The resulting shares $s_i$ are whole integers such that:

$$\sum_{i=1}^N s_i = T \quad \text{exactly to the paisa.}$$

No rounding discrepancy or lost fractional paise can ever occur.

---

## 6. Settlement Rules

### 6.1 Settlement Semantics (DR-13)
- A **settlement** is an explicit record of money repaid from one member (debtor) to another (creditor).
- **Settlements are never counted as spending or income.**
- A settlement adjusts net positions only:
  - Debtor's net position increases towards zero: $\text{NP}_{\text{debtor}} \leftarrow \text{NP}_{\text{debtor}} + \text{amount}$.
  - Creditor's net position decreases towards zero: $\text{NP}_{\text{creditor}} \leftarrow \text{NP}_{\text{creditor}} - \text{amount}$.
- Personal spending, monthly category budgets, and cash paid for expenses remain unchanged.

### 6.2 Settlement Constraints & Validation
- **Positive Amount:** $\text{amount\_paise} > 0$.
- **Partial Settlements Allowed:** Users may settle any portion of what they owe.
- **Maximum Ceiling:** A partial settlement cannot exceed the total balance owed between the parties.
- **Cross-Group Isolation:** Settlements apply strictly within the specific group context.

### 6.3 Debt Simplification (`simplify()`)
To minimize the total number of transactions required to settle a group:
- **Algorithm:** Greedy Debt Simplification.
  1. Identify the largest debtor (most negative net position $\text{NP}_{\min}$).
  2. Identify the largest creditor (most positive net position $\text{NP}_{\max}$).
  3. Propose a settlement from debtor to creditor of $\min(|\text{NP}_{\min}|, \text{NP}_{\max})$.
  4. Update tentative positions and repeat until all positions are zero.
- **Product Rule:** Debt simplification is offered as a **convenience suggestion**. Pairwise balances remain accessible and visible at all times.

### 6.4 Undoing or Correcting Settlements
- **Within 24 Hours:** The creator of a settlement or a group admin may delete the settlement record. Group balances immediately revert.
- **After 24 Hours:** Settlements become immutable audit records. Any correction must be recorded as a new compensating reverse settlement.

---

## 7. Expense Edits, Deletions & Refunds

### 7.1 Refunds Handled Through Edits (Version 1 Rule)
In Coinscious Version 1, refunds and merchant adjustments are recorded by **editing or deleting the original expense** rather than creating linked credit-note records (linked partial refund entities are scheduled for future versions).
- If an expense is partially refunded by a merchant: The creator edits the total amount down to reflect the net cost.
- If an expense is fully refunded or cancelled: The expense is deleted (soft-deleted).

### 7.2 Dynamic Calculation vs. Stored Running Totals
- The backend ledger **does not store static running balances** on member or group tables.
- Net positions, balances, and personal spending totals are **computed dynamically from ledger transaction records** (via pure functions and database aggregation).
- **Benefit:** An edit or deletion recalculates balances instantly and retroactively across all affected reporting periods, completely eliminating stale balance anomalies or reconciliation drifts.

### 7.3 Optimistic Concurrency Control
- All expense updates require an optimistic locking check via the `version` column.
- The client submits the known `version` in `PATCH /api/v1/groups/{id}/expenses/{eid}`.
- If another member updated the record concurrently, the server returns `409 Conflict`, preventing silent overwrites.

### 7.4 Transactional Integrity & Audit Logging
Every creation, edit, or deletion must execute in a single database transaction:
1. Update/delete the primary `expense` record (and increment `version`).
2. Delete previous `expense_shares` and insert newly computed shares from `allocate()`.
3. Insert an `audit_event` record capturing `user_id`, timestamp, and before-and-after snapshots.
4. If any step fails, the entire transaction rolls back.

---

## 8. Comprehensive Worked Examples

### 8.1 Worked Example 1: The Canonical Alex, Blair, Casey Lifecycle
*Participants:* Alex (A), Blair (B), Casey (C).  
*Fixed Tie Order:* A, B, C.  
*Initial Balances:* All 0 paise.

#### Step 1: Alex pays ₹3,000 for groceries, split equally among three
- **Total Amount:** ₹3,000.00 = `300000` paise.
- **Split:** $300000 / 3 = 100000$ paise (₹1,000.00) each.
- **Cash Paid:** Alex = `300000` paise; Blair = `0`; Casey = `0`.
- **Shares:** Alex = `100000` paise; Blair = `100000` paise; Casey = `100000` paise.
- **Net Positions:**
  - Alex: $+300000 - 100000 = \mathbf{+200000\text{ paise}}$ ($+₹2,000.00$, creditor)
  - Blair: $0 - 100000 = \mathbf{-100000\text{ paise}}$ ($-₹1,000.00$, debtor)
  - Casey: $0 - 100000 = \mathbf{-100000\text{ paise}}$ ($-₹1,000.00$, debtor)
- **Alex Spending:** ₹1,000.00 | **Alex Cash Paid:** ₹3,000.00.

#### Step 2: Blair repays Alex ₹1,000
- **Settlement:** Blair pays Alex ₹1,000.00 (`100000` paise).
- **Personal Spending:** Unchanged for all members.
- **Net Positions:**
  - Alex: $+200000 - 100000 = \mathbf{+100000\text{ paise}}$ ($+₹1,000.00$)
  - Blair: $-100000 + 100000 = \mathbf{0\text{ paise}}$ ($₹0.00$, settled)
  - Casey: $\mathbf{-100000\text{ paise}}$ ($-₹1,000.00$)
- **Alex Spending:** ₹1,000.00 | **Alex Cash Paid:** ₹3,000.00.

#### Step 3: Alex adds a personal ₹500 metro recharge
- **Total Amount:** ₹500.00 = `50000` paise.
- **Cash Paid:** Alex = `50000` paise | **Share:** Alex = `50000` paise.
- **Group Net Positions:** Unaffected (Alex $+₹1,000.00$, Blair $₹0.00$, Casey $-₹1,000.00$).
- **Alex Cumulative Spending:** $100000 + 50000 = \mathbf{150000\text{ paise}}$ ($₹1,500.00$).
- **Alex Cumulative Cash Paid:** $300000 + 50000 = \mathbf{350000\text{ paise}}$ ($₹3,500.00$).

#### Step 4: Casey pays ₹100 for chai, split equally among three (Rounding & Tie Rule)
- **Total Amount:** ₹100.00 = `10000` paise.
- **Payer:** Casey = `10000` paise.
- **Allocation Arithmetic:**
  - Raw quota: $10000 / 3 = 3333.333\dots$ paise.
  - Base share: $\lfloor 3333.333\dots \rfloor = 3333$ paise.
  - Unallocated remainder: $10000 - (3333 \times 3) = 1$ paisa.
  - All remainders are tied ($0.333\dots$). Fixed order assigns the $+1$ paisa to **Alex**.
  - Final shares:
    - Alex: $3333 + 1 = \mathbf{3334\text{ paise}}$ ($₹33.34$)
    - Blair: $\mathbf{3333\text{ paise}}$ ($₹33.33$)
    - Casey: $\mathbf{3333\text{ paise}}$ ($₹33.33$)
    - Sum: $3334 + 3333 + 3333 = 10000$ paise ($₹100.00$).
- **Net Position Changes for Chai:**
  - Alex: $0 - 3334 = -3334$ paise
  - Blair: $0 - 3333 = -3333$ paise
  - Casey: $+10000 - 3333 = +6667$ paise
- **Cumulative Group Net Positions:**
  - Alex: $+100000 - 3334 = \mathbf{+96666\text{ paise}}$ ($+₹966.66$)
  - Blair: $0 - 3333 = \mathbf{-3333\text{ paise}}$ ($-₹33.33$)
  - Casey: $-100000 + 6667 = \mathbf{-93333\text{ paise}}$ ($-₹933.33$)
  - Verification: $+96666 - 3333 - 93333 = 0$ paise.
- **Alex Cumulative Spending:** $150000 + 3334 = \mathbf{153334\text{ paise}}$ ($₹1,533.34$).
- **Alex Cumulative Cash Paid:** ₹3,500.00 (unchanged; Casey paid).

---

### 8.2 Worked Example 2: Unequal Split Modes

#### 8.2.1 Exact Split Mode
- **Total:** ₹150.00 = `15000` paise. Payer: Alex.
- **Inputs:** Alex ₹60.00 (`6000` paise), Blair ₹50.00 (`5000` paise), Casey ₹40.00 (`4000` paise).
- **Validation:** $6000 + 5000 + 4000 = 15000$ paise (valid).
- **Net Position Impact:**
  - Alex: $+15000 - 6000 = +9000$ paise ($+₹90.00$)
  - Blair: $0 - 5000 = -5000$ paise ($-₹50.00$)
  - Casey: $0 - 4000 = -4000$ paise ($-₹40.00$)

#### 8.2.2 Percentage Split Mode with Fractional Remainders
- **Total:** ₹55.55 = `5555` paise. Payer: Alex.
- **Weights:** Alex: 50.00%, Blair: 25.00%, Casey: 25.00% ($\sum = 100.00\%$).
- **Calculation:**
  - Alex: $5555 \times 0.50 = 2777.5$ paise $\to \text{base } 2777$, remainder $0.50$.
  - Blair: $5555 \times 0.25 = 1388.75$ paise $\to \text{base } 1388$, remainder $0.75$.
  - Casey: $5555 \times 0.25 = 1388.75$ paise $\to \text{base } 1388$, remainder $0.75$.
  - Sum of base shares: $2777 + 1388 + 1388 = 5553$ paise.
  - Leftover: $5555 - 5553 = 2$ paise.
  - Ranking remainders: Blair ($0.75$) and Casey ($0.75$) > Alex ($0.50$).
  - Top 2 (Blair and Casey) each receive $+1$ paisa.
- **Final Shares:**
  - Alex: `2777` paise ($₹27.77$)
  - Blair: `1389` paise ($₹13.89$)
  - Casey: `1389` paise ($₹13.89$)
  - Total: $2777 + 1389 + 1389 = 5555$ paise ($₹55.55$).

#### 8.2.3 Parts Split Mode
- **Total:** ₹100.00 = `10000` paise. Payer: Blair.
- **Ratios:** Alex 3 parts, Blair 2 parts, Casey 2 parts (Total parts = 7).
- **Calculation:**
  - Alex: $10000 \times 3 / 7 = 4285.714\dots \to \text{base } 4285$, remainder $5/7 \approx 0.714$.
  - Blair: $10000 \times 2 / 7 = 2857.142\dots \to \text{base } 2857$, remainder $2/7 \approx 0.286$.
  - Casey: $10000 \times 2 / 7 = 2857.142\dots \to \text{base } 2857$, remainder $2/7 \approx 0.286$.
  - Sum of base: $4285 + 2857 + 2857 = 9999$ paise.
  - Leftover: $10000 - 9999 = 1$ paisa.
  - Ranking remainders: Alex ($0.714$) is highest, receiving $+1$ paisa.
- **Final Shares:**
  - Alex: `4286` paise ($₹42.86$)
  - Blair: `2857` paise ($₹28.57$)
  - Casey: `2857` paise ($₹28.57$)
  - Total: $4286 + 2857 + 2857 = 10000$ paise ($₹100.00$).

---

### 8.3 Worked Example 3: Multiple Payers (Mixed Contributions)
- **Expense:** Weekend Villa Rental = ₹6,000.00 (`600000` paise).
- **Contributions:**
  - Alex pays: `400000` paise (₹4,000.00)
  - Blair pays: `200000` paise (₹2,000.00)
  - Casey pays: `0` paise (₹0.00)
  - Validation: $400000 + 200000 + 0 = 600000$ paise.
- **Split:** Equal across Alex, Blair, Casey $\to 200000$ paise (₹2,000.00) each.
- **Net Position Impact:**
  - Alex: $+400000 - 200000 = \mathbf{+200000\text{ paise}}$ ($+₹2,000.00$, creditor)
  - Blair: $+200000 - 200000 = \mathbf{0\text{ paise}}$ ($₹0.00$, settled)
  - Casey: $0 - 200000 = \mathbf{-200000\text{ paise}}$ ($-₹2,000.00$, debtor)
- **Spending Impact:** Alex, Blair, and Casey each record exactly ₹2,000.00 in spending.

---

### 8.4 Worked Example 4: Greedy Debt Simplification
Consider a 4-person flat with members A, B, C, D and the following computed net positions:
- Member A: $+300000$ paise ($+₹3,000.00$, Creditor)
- Member B: $+100000$ paise ($+₹1,000.00$, Creditor)
- Member C: $-250000$ paise ($-₹2,500.00$, Debtor)
- Member D: $-150000$ paise ($-₹1,500.00$, Debtor)
*(Sum: $+3000 + 1000 - 2500 - 1500 = 0$)*

**Greedy Simplification Iterations:**
1. **Iteration 1:**
   - Largest Debtor: C (owes `250000`)
   - Largest Creditor: A (owed `300000`)
   - Settlement: **C pays A ₹2,500.00 (`250000` paise)**
   - New tentative positions: $\text{NP}_C = 0$; $\text{NP}_A = +50000$; $\text{NP}_B = +100000$; $\text{NP}_D = -150000$.
2. **Iteration 2:**
   - Largest Debtor: D (owes `150000`)
   - Largest Creditor: B (owed `100000`)
   - Settlement: **D pays B ₹1,000.00 (`100000` paise)**
   - New tentative positions: $\text{NP}_D = -50000$; $\text{NP}_B = 0$; $\text{NP}_A = +50000$.
3. **Iteration 3:**
   - Largest Debtor: D (owes `50000`)
   - Largest Creditor: A (owed `50000`)
   - Settlement: **D pays A ₹500.00 (`50000` paise)**
   - New tentative positions: $\text{NP}_D = 0$; $\text{NP}_A = 0$.

**Result:** The group settles completely in **3 transactions** instead of up to 6 pairwise transfers.

---

### 8.5 Worked Example 5: Handling a Refund Through an Expense Edit
*Context:* Alex originally created a ₹3,000 grocery expense split equally among Alex, Blair, and Casey (from Step 1: Alex net $+₹2,000$, Blair net $-₹1,000$, Casey net $-₹1,000$, record `version: 1`).

- **Event:** A grocery store item is returned, resulting in a ₹600.00 refund back to Alex's card.
- **Action:** Alex edits the original expense via `PATCH /api/v1/groups/{id}/expenses/{eid}`:
  ```json
  {
    "version": 1,
    "amount_paise": 240000,
    "description": "Groceries (₹600 refund adjusted)"
  }
  ```
- **Backend Atomic Execution:**
  1. Concurrency verification: Existing version is 1; increments to `version = 2`.
  2. Ledger engine runs `allocate(240000, 3, equal)` $\to$ Alex: `80000` paise, Blair: `80000` paise, Casey: `80000` paise.
  3. Replaces previous share records with updated shares.
  4. Records `audit_event`: captures editor `usr_alex`, previous amount `300000`, new amount `240000`.
- **Immediate Balance Recomputation:**
  - Net Positions:
    - Alex: $+240000 - 80000 = \mathbf{+160000\text{ paise}}$ ($+₹1,600.00$)
    - Blair: $0 - 80000 = \mathbf{-80000\text{ paise}}$ ($-₹800.00$)
    - Casey: $0 - 80000 = \mathbf{-80000\text{ paise}}$ ($-₹800.00$)
  - Personal Spending:
    - Blair's and Casey's spending drops immediately from ₹1,000.00 to ₹800.00.
    - Alex's spending drops from ₹1,000.00 to ₹800.00.
  - Zero reconciliation drift: No orphaned balances or dangling refund records.

---

## 9. Architectural & Testing Invariants (US-36 / NFR-12)

### 9.1 Pure Python Engine Interfaces
The ledger engine is structured as pure, stateless Python functions with zero database or network dependencies:
```python
def allocate(
    amount_paise: int,
    participants: list[str],
    split_mode: str,
    weights: list[int] | list[float] | None = None,
) -> dict[str, int]:
    """Allocates integer paise across participants using largest-remainder with fixed tie order."""
    ...

def net_positions(
    expenses: list[ExpenseRecord],
    settlements: list[SettlementRecord],
) -> dict[str, int]:
    """Computes member net positions from raw payments, shares, and settlements."""
    ...

def simplify(
    net_positions: dict[str, int],
) -> list[SuggestedTransfer]:
    """Applies greedy debt simplification to propose minimal settlement transfers."""
    ...
```

### 9.2 Property-Based Test Specification (T-05 / US-36)
Before any group feature branch is merged, the ledger engine must pass a Hypothesis-driven property test suite executing **10,000 randomized cases** against the following invariants:
1. **Conservation of Shares:** $\sum \text{shares} == \text{amount\_paise}$ for all modes (`equal`, `exact`, `percentage`, `parts`).
2. **Zero-Sum Balance:** $\sum_{m \in \text{Group}} \text{net\_position}_m == 0$ after any arbitrary sequence of valid expenses, edits, and settlements.
3. **Deterministic Output:** Identical inputs must yield identical allocations regardless of system locale or runtime environment.
4. **Non-Negativity:** No allocated share may be negative ($\text{share}_i \ge 0$).

---

## 10. Review & Sign-Off Checklist for `#dev`

As specified in Sprint 0 Task T-04, this document must be reviewed and approved by all 10 team members in `#dev` before the group screen and database migration work commences.

| Team Member | Role | Review Focus | Approval Status |
| :--- | :--- | :--- | :--- |
| **Vishwa (M2)** | Backend + Database (Owner) | Arithmetic precision, pure ledger functions | [x] Author / Approved |
| **Jay (M1)** | Integration & Backend | API contracts, transactional rollback | [ ] Pending Review |
| **Riya (M3)** | Product & Frontend | User experience of spending vs cash paid | [ ] Pending Review |
| **Vishva (M4)** | Database Architecture | BIGINT paise schema, audit events | [ ] Pending Review |
| **Parthiv (M6)** | GenAI & Data | Receipt extraction boundary & integer conversion | [ ] Pending Review |
| **Ved (M7)** | Scrum Master & GenAI | Category budgets & grounding limits | [ ] Pending Review |
| **Harshul (M8)** | Frontend & UI | Unequal split UI preview & 409 conflict handling | [ ] Pending Review |
| **Aryan (M9)** | GenAI & Budgets | Goal recommendations & spending thresholds | [ ] Pending Review |
| **Vivek (M10)** | DevOps & QA | Property test suites & CI automation | [ ] Pending Review |
| **Yagnik (M5)** | Assistant & Queries | AI query grounding & tool boundaries | [ ] Pending Review |

> **Sign-Off Instruction:** Please reply in Slack `#dev` with:  
> `LGTM: docs/ledger.md rules confirmed for Sprint 0/US-36` or post specific line-item questions.
