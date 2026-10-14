# Smart Expense Splitter & Tracker
**Group No:** 28 | **Lab Group:** 4

## 4. Requirements Conflicts and Resolutions

In software requirements engineering, different user needs, system features, and quality goals can conflict with each other. Below is the summary table of all identified conflicts, followed by a brief description and resolution for each.

### 4.1 Summary of Conflicts

| Conflict ID | Requirements in Conflict | Why Conflict Occurs (Issue) | Possible Resolution | Trade-off |
|---|---|---|---|---|
| **C-01** | Security/Privacy vs. Usability | Strong access controls add extra login steps. | Use biometric/persistent login for daily use; require extra auth only for sensitive actions. | Small setup effort for users. |
| **C-02** | Parental Mode vs. Family Privacy | Parents need spending data while family members expect privacy. | Allow parents to view category totals/budgets without revealing private personal items. | Reduced personal privacy for dependents. |
| **C-03** | OCR Convenience vs. Accuracy | Automatic receipt scanning may misread bill amounts or names. | Show a quick review/edit screen before saving extracted receipt data. | Adds a quick user check step. |
| **C-04** | AI Personalization vs. Data Privacy | AI analysis requires expense data, but financial data must stay private. | Make AI opt-in, send only anonymized data, and ensure AI services do not store or train on it. | Slightly limits personalized AI insights. |
| **C-05** | Notifications vs. Usability | Too many reminders and alerts can annoy users and cause alert fatigue. | Provide custom notification settings and send combined daily/weekly summaries. | Users might see low-priority alerts later. |
| **C-06** | Availability vs. Maintenance | 24/7 availability conflicts with the need to update and maintain the system. | Schedule updates during off-peak hours (late night) with advance notice and offline view. | Small scheduled downtime periods. |
| **C-07** | Group Admin Control vs. Member Autonomy | Admins manage groups, but members should not lose control of their records. | Admins manage members, but cannot edit or delete expenses entered by other members. | Members must correct their own mistakes. |
| **C-08** | Manual vs. AI Auto-Categorization | AI categorizer may overwrite user-chosen categories or misclassify items. | AI only suggests categories; user selection is final and corrections train suggestions. | Requires brief user verification. |
| **C-09** | Personal vs. Group Recurring Expenses | A recurring bill could be personal (gym) or shared (rent), causing wrong splits. | Let users select "Personal" or "Group" when creating recurring expenses with default split rules. | Adds one setup step during creation. |
| **C-10** | Customer Support vs. Financial Privacy | Support staff need account info to solve issues, exposing private finances. | Support staff see only account info by default; viewing financial data requires user consent. | Extra approval step during support. |
| **C-11** | Debt Simplification vs. Traceability | Simplifying group debts reduces transfers, but users may not recognize indirect payments. | Make debt simplification an optional toggle and show a clear breakdown of the calculation. | Requires displaying explanation steps. |
| **C-12** | Offline Entry vs. Data Consistency | Logging expenses offline can cause conflicts if multiple members edit at the same time. | Store entries locally with timestamps and prompt users to confirm if same expense was edited. | Rare collisions need manual confirmation. |
| **C-13** | Custom Bill Splitting vs. Rounding Precision | Unequal splits (e.g., 100 split 3 ways) create fractional cents that do not add up. | Round shares to 2 decimals and assign the leftover 1 cent to the payer with a note. | One user pays 1 cent more/less for exact closure. |

---

### 4.2 Details of Conflicts and Resolutions

#### C-01: Security/Privacy vs. Usability
- **Requirements:** NFR-03 (Security), NFR-08 (Data Privacy) vs. NFR-01 (Usability)
- **Issue:** Strict password and verification steps protect user data but slow down everyday expense logging.
- **Resolution:** Use biometric login or secure persistent sessions for daily use, requiring step-up verification only for critical actions like password reset or account deletion.
- **Trade-off:** Small initial setup effort for the user, but ensures daily convenience without lowering security.

#### C-02: Parental Mode vs. Family Member Privacy
- **Requirements:** FR-09 (Parental Mode), FR-14 (Family Expense Management) vs. NFR-08 (Data Privacy)
- **Issue:** Parents need visibility to monitor household spending, while dependent family members expect privacy for personal purchases.
- **Resolution:** Parents can view overall category budgets, spending caps, and alerts, but individual line-item details of personal allowances remain masked unless a limit is breached.
- **Trade-off:** Parents receive sufficient supervision without intruding on every personal purchase.

#### C-03: OCR Convenience vs. Accuracy
- **Requirements:** FR-12 (Bill/Receipt Scanning) vs. NFR-09 (Accuracy), DR-10 (Bill Data)
- **Issue:** Users want instant automatic bill entry, but scanning faded or handwritten receipts can result in incorrect amounts or categories.
- **Resolution:** Implement a quick review/edit screen after scanning where extracted details are displayed for user confirmation before saving.
- **Trade-off:** Adds a 3-second verification step, but prevents incorrect expense amounts in group ledgers.

#### C-04: AI Personalization vs. Data Privacy
- **Requirements:** FR-06 (AI Advisor) vs. NFR-03 (Security), NFR-08 (Data Privacy)
- **Issue:** GenAI features need expense data to provide personalized insights, but sending financial data to third-party AI services risks data leaks.
- **Resolution:** AI features are strictly opt-in. Data is anonymized (no names, emails, or account numbers sent), and agreements ensure the AI provider does not store or train on user data.
- **Trade-off:** Anonymized data slightly limits cross-context personalization, but protects user privacy.

#### C-05: Notifications vs. Usability
- **Requirements:** FR-08 (Reminders & Notifications), FR-10 (Budgeting & Alerts) vs. NFR-01 (Usability)
- **Issue:** Too many notifications for bills, split payments, and budget warnings can overwhelm users and lead them to disable alerts completely.
- **Resolution:** Provide user-controlled notification preferences, quiet hours, and aggregated daily or weekly digests instead of instant alerts for every event.
- **Trade-off:** Users who choose low-frequency alerts may see non-critical reminders later.

#### C-06: Availability vs. Maintenance
- **Requirements:** NFR-07 (Availability) vs. NFR-05 (Maintainability), NFR-04 (Reliability)
- **Issue:** Users expect the app to be available 24/7 to record expenses, but system upgrades and database fixes require downtime.
- **Resolution:** Schedule maintenance windows during off-peak hours (e.g., late night), notify users in advance, and allow offline view and expense logging during maintenance.
- **Trade-off:** Small scheduled downtime periods are accepted to keep the system reliable and updated.

#### C-07: Group Admin Control vs. Member Autonomy
- **Requirements:** FR-13 (Group Management) vs. FR-03 (Expense Tracking), DR-05 (Modification Permissions)
- **Issue:** Group admins need authority to manage groups, but giving them full power could let them edit or delete other members' personal expense entries.
- **Resolution:** Admins can manage group members and settings, but only the member who created an expense can edit or delete it. Any change notifies all group members.
- **Trade-off:** Stronger admin limits prevent unauthorized edits, requiring members to correct their own entries.

#### C-08: Manual Categorization vs. AI Auto-Categorization
- **Requirements:** FR-03 (Expense Tracking), DR-02 (Category Assignment) vs. FR-06 (AI Advisor)
- **Issue:** Users prefer their own expense categories, while AI auto-categorization might overwrite their choices or assign incorrect categories.
- **Resolution:** AI only suggests categories during entry. The user's choice is final, and any manual correction helps train the suggestion system for future entries.
- **Trade-off:** Requires a moment of user review rather than 100% hands-free automatic categorization.

#### C-09: Personal Recurring vs. Group Recurring Expenses
- **Requirements:** FR-11 (Recurring Expense Automation) vs. FR-05 (Group Expense Splitting)
- **Issue:** Recurring expenses can be personal (gym, subscriptions) or shared (rent, utilities). If not clearly defined, personal bills could be split across a group.
- **Resolution:** When setting up a recurring bill, the user explicitly chooses "Personal" or "Group" and sets default split rules with a pre-posting reminder.
- **Trade-off:** Adds an extra setup step during creation, but avoids wrong splits and member disputes.

#### C-10: Customer Support vs. Financial Privacy
- **Requirements:** FR-07 (Customer Support), FR-15 (System Admin) vs. NFR-08 (Data Privacy)
- **Issue:** Support staff need account information to troubleshoot user issues, which could expose private financial transactions.
- **Resolution:** Staff see only account metadata and ticket details by default. Viewing financial data requires temporary user consent and all access is logged.
- **Trade-off:** Troubleshooting may take an extra confirmation step from the user to maintain strict privacy.

#### C-11: Debt Simplification vs. Transaction Traceability
- **Requirements:** FR-05 (Group Expense Splitting) vs. DR-06 (Balance Tracking), NFR-09 (Accuracy)
- **Issue:** Simplifying group debts reduces the number of payments (e.g., A pays C directly), but members may be confused paying someone they did not borrow from.
- **Resolution:** Provide debt simplification as an optional toggle per group, and show a clear breakdown of how the simplified payments were calculated.
- **Trade-off:** Requires displaying an explanation breakdown in the UI, but avoids confusion and builds trust.

#### C-12: Offline Expense Entry vs. Data Consistency
- **Requirements:** NFR-01 (Usability), NFR-02 (Performance) vs. NFR-04 (Reliability)
- **Issue:** Users adding expenses offline (e.g., during travel) may cause sync conflicts if multiple members edit the same group expenses before reconnecting.
- **Resolution:** Save entries locally with timestamps, sync automatically upon reconnecting, and prompt users to review if the exact same expense was edited by two people.
- **Trade-off:** Rare simultaneous edits need a quick manual review to prevent overwritten data.

#### C-13: Custom Bill Splitting vs. Rounding Precision
- **Requirements:** FR-05 (Group Expense Splitting) vs. DR-03 (Split Sum Equals Total), DR-11 (Rounding)
- **Issue:** Splitting bills unequally or in percentages (e.g., $100 split 3 ways) creates fractional cents, causing individual shares not to match the bill total.
- **Resolution:** Round shares to 2 decimals and allocate the remaining 1 cent to the payer with an explicit note.
- **Trade-off:** One member pays 1 cent more or less to ensure the mathematical total is always exact.
