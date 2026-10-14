# Smart Expense Splitter & Tracker
**Group No:** 28 | **Lab Group:** 4

## 4. Requirements Conflicts and Resolutions

### 4.1 Overview

In software engineering, requirements elicitation inevitably reveals tensions between competing stakeholder expectations, functional capabilities, and non-functional quality constraints. Identifying, documenting, and resolving these conflicts early in the requirements engineering phase ensures a coherent system architecture, prevents costly redesigns during development, and preserves a balanced user experience.

This document synthesizes and resolves all identified requirement conflicts for the **Smart Expense Splitter & Tracker** application, removing redundancies and mapping each conflict to our formal Functional Requirements (**FR**), Non-Functional Requirements (**NFR**), Domain Requirements (**DR**), and Stakeholder roles.

---

### 4.2 Summary Matrix of Conflicts

| Conflict ID | Requirement / Stakeholders in Conflict | Why Conflict Occurs (Issue) | Proposed Resolution | Trade-off |
|---|---|---|---|---|
| **C-01** | **Security / Privacy vs. Usability**<br>*(NFR-03, NFR-08 vs. NFR-01)* | Strict access controls, frequent multi-factor prompts, and re-authentication add user friction during quick daily expense logging. | Use modern secure authentication (e.g., biometric login on mobile, secure persistent JWT sessions) and require step-up authentication only for sensitive actions (password change, exporting data, account deletion). | Balances strong account protection with ease of daily use; minor initial setup effort for users. |
| **C-02** | **Parental Mode vs. Family Member Privacy**<br>*(FR-09, FR-14 vs. NFR-08, DR-12)* | Parents require visibility to monitor dependent spending and set limits, while family members and teenage dependents expect privacy over specific personal purchase details. | Allow parents to view aggregate category budgets, spending thresholds, and shared family expenses. Individual line-item details for personal allowances remain masked unless explicitly shared by the dependent or when a budget cap is breached. | Parents receive sufficient supervisory control, while dependents maintain appropriate personal privacy. |
| **C-03** | **OCR Convenience vs. Data Accuracy**<br>*(FR-12 vs. NFR-09, DR-10)* | Users want instant, one-click automatic receipt data entry, but OCR scanning of crumpled, handwritten, or low-light receipts can extract inaccurate amounts or merchants. | OCR parses the receipt into an editable pre-save preview screen where extracted fields (amount, merchant, date, category) are highlighted for quick user verification and one-tap corrections before committing to the database. | Adds a short 3-second verification step for the user, but completely eliminates corrupted balances and erroneous splits. |
| **C-04** | **AI Personalization & Insights vs. Data Privacy**<br>*(FR-06 vs. NFR-03, NFR-08, DR-12)* | Generative AI analysis and budget suggestions require processing financial transaction history, but sending unencrypted personal data to external LLMs risks confidentiality leaks. | AI features are strictly opt-in. Data transmitted to the external GenAI service is pseudonymized and scrubbed of PII (no names, emails, bank accounts, or exact geolocation; only description and amount). Enforce zero-retention and no-training agreements with the AI provider. | Protecting user identity limits cross-app contextual personalization, but guarantees compliance with financial privacy standards. |
| **C-05** | **Reminders & Notifications vs. Usability (Notification Fatigue)**<br>*(FR-08, FR-10 vs. NFR-01)* | Frequent notifications for bill reminders, recurring payments, split balance updates, and budget thresholds can overwhelm users and lead them to disable notifications altogether. | Provide granular notification preferences (push, in-app, email), configurable alert thresholds (e.g., alert only at 80% and 100% budget utilization), smart quiet hours, and aggregated daily/weekly summary digests. | Users who configure low-frequency alerts may receive reminders later, but overall user satisfaction and notification retention increase significantly. |
| **C-06** | **Continuous Availability vs. Necessary System Maintenance**<br>*(NFR-07 vs. NFR-05, NFR-04)* | Users expect 24/7 uninterrupted system availability to record expenses on the fly, but database schema updates, server patching, and security maintenance necessitate system updates. | Employ zero-downtime deployment strategies (blue-green deployments, database migrations with backward compatibility). When unavoidable, schedule maintenance during off-peak hours (e.g., 02:00–04:00 local time) with 48-hour advance in-app notice and an offline read-only fallback mode. | Occasional minimal scheduled maintenance windows are accepted to guarantee long-term system stability and data integrity. |
| **C-07** | **Group Admin Authority vs. Member Autonomy & Data Integrity**<br>*(FR-13 vs. FR-03, DR-05, DR-06)* | Group admins need control to organize groups and settle debts, but unrestricted admin powers could permit modifying or deleting expenses added by other members, distorting financial balances. | Establish strict role permissions: Admins can manage membership, group names, and default split rules, but cannot edit or delete expenses entered by other members. Any post-entry expense change requires an approval notification to all affected group members. | Prevents unilateral tampering and disputes; requires collaborative consensus for expense modifications. |
| **C-08** | **Manual Expense Categorization vs. Automated AI Categorization**<br>*(FR-03, DR-02 vs. FR-06)* | Users manually categorize their spending according to personal mental models. An automated AI categorizer could overwrite manual selections or misclassify ambiguous transactions. | AI classification acts purely as an assistive suggestion engine during expense creation. The user's explicit manual selection always takes final precedence. Corrections made by the user are saved locally to tune future category suggestions. | Ensures users stay in complete control of their budgets while still benefiting from AI automation. |
| **C-09** | **Personal Recurring Expenses vs. Group Recurring Expenses**<br>*(FR-11 vs. FR-05, DR-09)* | Recurring expense automation can apply to individual subscriptions (e.g., personal gym, streaming) or shared recurring bills (e.g., apartment rent, shared Wi-Fi). Ambiguity in configuration could result in personal expenses being erroneously split across groups. | When configuring a recurring expense, the system presents an explicit scope selection: **Personal** or **Group**. For group recurring expenses, the user specifies the target group, members involved, and default split method, with an automated confirmation reminder before each cycle is posted. | Adds an initial explicit setup step, but eliminates accidental group splits and unauthorized member debt creation. |
| **C-10** | **Customer Support / Admin Access vs. Financial Confidentiality**<br>*(FR-07, FR-15 vs. NFR-08, DR-12)* | Support personnel need account access to diagnose split discrepancies and bug reports, but viewing customer records risks exposing private financial data to support staff. | Implement Role-Based Access Control (RBAC) with Least Privilege: Support staff only view user account metadata and diagnostic error logs by default. Access to transaction data requires time-limited, explicit user consent (e.g., one-time support access token) and generates an immutable audit log. | Support troubleshooting may require an extra user authorization step, but customer financial data remains strictly confidential. |
| **C-11** | **Debt Simplification (Minimum Cash Flow) vs. Transaction Traceability**<br>*(FR-05 vs. DR-06, NFR-01, NFR-09)* | Debt simplification algorithms minimize the total number of transactions in a group (e.g., Member A pays Member C instead of A→B and B→C). However, members who did not interact directly may be confused or distrust the settlement path. | Provide debt simplification as an optional toggle per group. When enabled, the settlement screen displays an interactive breakdown ("Why is this simplified?") detailing the underlying original expense chains. | Clarifying the calculation path requires additional UI documentation, but eliminates settlement skepticism while minimizing transactions. |
| **C-12** | **Offline Expense Logging vs. Multi-User Concurrency & Balance Consistency**<br>*(NFR-01, NFR-02 vs. NFR-04, DR-06)* | Mobile users often add expenses in areas with poor internet connectivity. When multiple group members edit expenses or settle debts offline, conflicting updates occur upon reconnection. | Implement local optimistic offline caching with vector clocks / event timestamps. Upon reconnection, non-conflicting records are synced automatically. In case of direct collisions on the same expense, the system flags the conflict and prompts members to select the authoritative record. | Users can always record expenses without delay; rare simultaneous edits require a quick manual reconciliation prompt. |
| **C-13** | **Custom / Percentage Bill Splitting vs. Mathematical Exactness & Rounding**<br>*(FR-05 vs. DR-03, DR-11, NFR-09)* | Splitting expenses unequally or by percentages (e.g., 100 split 3 ways = 33.333...) produces fractional cents/paisa. If not properly handled, the sum of split shares fails to equal the total bill amount (violating DR-03). | Enforce standard financial rounding (Largest Remainder Method / Banker's Rounding) where the residual cent is systematically assigned to the payer or the first payee, and display an explicit rounding note on the summary screen. | Minor 1-cent/paisa adjustment on an individual share, ensuring strict mathematical closure and balanced ledgers. |

---

### 4.3 Detailed Conflict Analysis & Resolution Strategies

#### C-01: Security / Privacy vs. Usability
- **Epics / Requirements in Conflict:** NFR-03 (Security), NFR-08 (Data Privacy) vs. NFR-01 (Usability), FR-02 (User Login & Session Management).
- **Stakeholders Involved:** Individual Users, Group Users, IT / Security Teams.
- **Problem Description:** Stringent security mechanisms (mandatory 2FA, short session timeouts, repeated password entries) ensure high data safety but degrade everyday usability for users attempting to log small, routine expenses quickly.
- **Resolution Strategy:** Deploy a tiered authentication model. Standard interactions utilize secure biometric authentication (Face ID / Fingerprint) and persistent encrypted tokens on personal devices. High-risk administrative actions (changing recovery credentials, exporting raw financial statements, deleting accounts) trigger step-up multi-factor authentication.
- **Trade-off:** Minimal friction during everyday use; security friction is concentrated only where high-impact risk exists.

#### C-02: Parental Mode vs. Family Member Privacy
- **Epics / Requirements in Conflict:** FR-09 (Parental Mode), FR-14 (Family/Household Expense Management) vs. NFR-08 (Data Privacy), DR-12 (Access Permissions).
- **Stakeholders Involved:** Parents/Guardians, Dependent Family Members (teens/students).
- **Problem Description:** Parents funding accounts require assurance that money is spent responsibly, whereas dependents expect personal privacy regarding specific items purchased.
- **Resolution Strategy:** Provide configurable privacy boundaries. Parents have visibility into high-level budget categories, total expenditure totals, and balance limits. Line-item descriptions for personal allowances remain private to the dependent unless budget limits are exceeded or the dependent voluntarily shares the receipt.
- **Trade-off:** Parents receive high-level fiscal oversight without intrusive surveillance over every personal line-item purchase.

#### C-03: OCR Convenience vs. Data Accuracy
- **Epics / Requirements in Conflict:** FR-12 (Bill/Receipt Scanning & Data Extraction) vs. NFR-09 (Accuracy), DR-10 (Extracted Bill Data Requirements).
- **Stakeholders Involved:** All End Users, Bill/OCR Service, Development Team.
- **Problem Description:** Automatic receipt parsing is designed to minimize manual data entry. However, real-world receipts are often crinkled, faded, or formatted irregularly. Unchecked auto-commit leads to erroneous ledger amounts, corrupting group balances.
- **Resolution Strategy:** Implement a mandatory two-step "Scan & Confirm" interaction. The OCR extracts merchant, date, tax, and itemized amounts, presenting them in a pre-populated review form with low-confidence fields visually highlighted. The user must tap "Confirm & Save" before data is committed.
- **Trade-off:** A brief review step prevents data entry errors and saves significant time compared to resolving faulty historical balances.

#### C-04: AI Personalization & Insights vs. Data Privacy
- **Epics / Requirements in Conflict:** FR-06 (AI Advisor & Insights) vs. NFR-03 (Security), NFR-08 (Data Privacy), DR-12 (Access Permissions).
- **Stakeholders Involved:** Individual Users, GenAI Service, Security & Compliance Teams.
- **Problem Description:** Generative AI capabilities (spending summaries, pattern discovery, budget advice) require contextual data. Sending raw financial records to external LLM APIs risks exposing sensitive financial behavior and Personally Identifiable Information (PII).
- **Resolution Strategy:**
  1. AI features are disabled by default and require explicit user opt-in.
  2. Data scrubbed on-device/in-transit: Strip all PII (names, emails, account IDs, merchant addresses) before payload dispatch. Only generic expense tuples (`category`, `amount`, `date_offset`) are sent.
  3. External enterprise API contracts guarantee zero data retention and exclude user data from model training.
- **Trade-off:** Eliminating raw merchant names may slightly generalize AI advice, but guarantees strict regulatory compliance and user trust.

#### C-05: Reminders & Notifications vs. Usability (Notification Fatigue)
- **Epics / Requirements in Conflict:** FR-08 (Reminders & Notifications), FR-10 (Budgeting & Alerts) vs. NFR-01 (Usability).
- **Stakeholders Involved:** Group Users, Individual Users, Notification Service.
- **Problem Description:** As group activities grow, automated notifications for every added expense, settlement, upcoming bill, and budget alert can lead to notification overload, resulting in users turning off notifications entirely.
- **Resolution Strategy:** Incorporate a smart notification center:
  - Users customize push notification triggers per category (e.g., immediate alerts for settlements; batched digests for routine group additions).
  - Configurable threshold triggers (e.g., alert once at 80% and once at 100% of budget).
  - Quiet-hours scheduling.
- **Trade-off:** Users with aggressive alert throttling may receive updates in batches rather than instantaneously, preserving overall engagement.

#### C-06: Continuous High Availability vs. System Maintenance & Upgrades
- **Epics / Requirements in Conflict:** NFR-07 (Availability) vs. NFR-05 (Maintainability), NFR-04 (Reliability).
- **Stakeholders Involved:** All End Users, Developers / IT Teams, Company Owners.
- **Problem Description:** Users demand uninterrupted 24/7 service to record split bills in real-time at restaurants or venues, but database indexing, critical bug hotfixes, and architectural upgrades require maintenance windows.
- **Resolution Strategy:** Design a decoupled backend leveraging blue-green continuous deployments. When scheduled maintenance is unavoidable, execute during off-peak hours (02:00 to 04:00 AM local time), alert users 48 hours in advance, and allow clients to record expenses locally in read-only/offline mode.
- **Trade-off:** Occasional brief off-peak maintenance intervals maintain long-term system stability and performance.

#### C-07: Group Admin Authority vs. Member Autonomy & Data Integrity
- **Epics / Requirements in Conflict:** FR-13 (Group Management) vs. FR-03 (Expense Tracking), DR-05 (Modification Permissions), DR-06 (Group Balances).
- **Stakeholders Involved:** Group Admin / Creator, Group Users.
- **Problem Description:** Admins need authority to manage group membership and maintain order. However, allowing admins unrestricted ability to edit or delete any member's expense invites fraud, accidental deletions, or disputed debts.
- **Resolution Strategy:** Establish immutable expense ownership:
  - Only the user who created an expense (or the designated payer) can edit or delete it.
  - Admins can archive groups, invite/remove members (provided the member has a zero net balance), and trigger settlement reminders.
  - If an expense must be corrected by someone else, an explicit adjustment entry must be submitted with notification to all group members.
- **Trade-off:** Prevents rogue admin modifications at the cost of requiring the original creator to amend mistaken entries.

#### C-08: Manual User Categorization vs. Automated AI Categorization
- **Epics / Requirements in Conflict:** FR-03 (Personal Expense Tracking), DR-02 (Mandatory Category Assignment) vs. FR-06 (AI Advisor & Smart Categorization).
- **Stakeholders Involved:** Individual Users, GenAI Service.
- **Problem Description:** Users often develop idiosyncratic budgeting categories. An autonomous AI model might re-categorize an expense contrary to the user's intent (e.g., classifying a book purchased for work as "Entertainment" instead of "Professional Development").
- **Resolution Strategy:** The AI categorizer acts strictly as an advisory feature. It proposes a suggested category during entry; if the user selects a category manually, that choice is immutable by the AI. Furthermore, manual corrections update a user-specific preference dictionary to enhance future suggestions.
- **Trade-off:** Relies on user interaction for ambiguous cases rather than 100% hands-free automatic classification.

#### C-09: Personal Recurring Expenses vs. Group Recurring Expenses
- **Epics / Requirements in Conflict:** FR-11 (Recurring Expense Automation) vs. FR-05 (Group Expense Splitting), DR-09 (Recurring Schedule).
- **Stakeholders Involved:** Individual Users, Group Users.
- **Problem Description:** Recurring expenses can be private (e.g., personal cloud storage, gym membership) or collective (e.g., shared apartment rent, streaming family plan). Without clear distinction, automated schedule runs could mistakenly distribute personal charges across a group or miss shared split schedules.
- **Resolution Strategy:** Formally separate recurring expense definitions into two distinct creation flows:
  1. **Personal Recurring:** Debited strictly from the user's individual dashboard.
  2. **Group Recurring:** Bound to a specific group, assigning default split ratios among selected participants. Group members receive an in-app notice 24 hours prior to automated posting.
- **Trade-off:** Adds an explicit setup step during creation, preventing erroneous shared debt calculations.

#### C-10: Customer Support / Admin Access vs. Financial Confidentiality
- **Epics / Requirements in Conflict:** FR-07 (Customer Support), FR-15 (System Administration) vs. NFR-08 (Data Privacy), DR-12 (Data Access Permissions).
- **Stakeholders Involved:** Customer Support Teams, System Administrators, End Users.
- **Problem Description:** Support agents need contextual transaction data to resolve customer complaints regarding split errors or sync bugs, but granting open access exposes sensitive user finances to internal employees.
- **Resolution Strategy:**
  - Customer support dashboards show only redacted account statuses, ticket records, and non-financial telemetry by default.
  - If deep investigation is required, the user must approve a temporary, time-bounded support grant (valid for 2 hours) directly from their app.
  - Every access by support agents is logged in a tamper-proof audit trail.
- **Trade-off:** Increases response time slightly for support tickets requiring user approval, but completely preserves user privacy and regulatory compliance.

#### C-11: Debt Simplification (Minimum Cash Flow) vs. Transaction Traceability
- **Epics / Requirements in Conflict:** FR-05 (Group Expense Splitting) vs. DR-06 (Balance Tracking), NFR-01 (Usability), NFR-09 (Accuracy).
- **Stakeholders Involved:** Group Users, Group Admin.
- **Problem Description:** Minimum cash flow algorithms simplify multi-party debts (e.g., if User A owes User B $20, and User B owes User C $20, the algorithm directs User A to pay User C directly). While mathematically optimal, users frequently object because User A never participated in an expense with User C.
- **Resolution Strategy:** Debt simplification is implemented as an optional, transparent feature. It can be toggled on or off per group. When active, an interactive ledger breakdown clearly illustrates how indirect balances were computed and matched.
- **Trade-off:** Maintaining both direct debt and simplified debt calculation modes increases UI and algorithmic complexity, but guarantees user trust.

#### C-12: Offline Expense Logging vs. Multi-User Concurrency & Balance Consistency
- **Epics / Requirements in Conflict:** NFR-01 (Usability), NFR-02 (Performance) vs. NFR-04 (Reliability), DR-06 (Accurate Balances).
- **Stakeholders Involved:** Group Users, Mobile Users, IT / Backend Team.
- **Problem Description:** In offline scenarios (travel, remote venues), multiple members may log expenses or mark debts as settled simultaneously without internet access. When devices reconnect, conflicting states and balance mismatches emerge.
- **Resolution Strategy:** Employ client-side event sourcing with idempotent UUIDs and timestamps. When syncing:
  - Additive records (new expenses) are merged chronologically without conflict.
  - Conflicting edits on the same entry prompt the group with a visual diff resolution modal, highlighting conflicting edits for one-tap consensus.
- **Trade-off:** Occasional manual verification needed for rare simultaneous offline edits on the exact same expense.

#### C-13: Custom / Percentage Bill Splitting vs. Mathematical Exactness & Rounding
- **Epics / Requirements in Conflict:** FR-05 (Group Expense Splitting) vs. DR-03 (Split Sum Equals Total), DR-11 (Monetary Precision), NFR-09 (Accuracy).
- **Stakeholders Involved:** Group Users, Development Team.
- **Problem Description:** Splitting an uneven expense (e.g., $100.00 split 3 ways results in $33.3333... per person). In percentage-based or shares-based splitting, rounding fractions of a cent can cause the sum of shares to deviate from the total bill, violating domain rules DR-03 and DR-11.
- **Resolution Strategy:** Implement standard financial remainder distribution (Largest Remainder Method):
  - Shares are rounded to 2 decimal places.
  - The remaining 1-cent discrepancy is automatically allocated to the payer (or the first member in the split list).
  - The breakdown displays a transparent note: *"Includes $0.01 rounding adjustment."*
- **Trade-off:** One participant pays a single cent more or less, ensuring absolute mathematical integrity across all balance ledgers.

---

### 4.4 Conclusion

By systematically identifying these 13 core requirements conflicts and defining balanced, technically sound resolution strategies, the **Smart Expense Splitter & Tracker** project maintains a robust equilibrium between usability, security, financial accuracy, and data privacy. These resolutions will directly guide the system design, database schemas, and user interface workflows in the upcoming development phases.
