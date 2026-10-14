IT314 Software Engineering · Group 28

# Coinscious: Smart Expense Splitter & Tracker

| **Document** | User Stories |
|---|---|
| **Project** | Coinscious: Smart Expense Splitter & Tracker |
| **Course** | IT314 Software Engineering |
| **Team** | Group 28 (10 members) |
| **Version** | 1.0 |
| **Date** | 14 October 2026 |

This document is the product backlog of Coinscious. It holds all 39 user stories, grouped by epic. Each story

says who wants something, what they want and why, followed by the acceptance criteria that must pass

before the story is complete. Story statements and acceptance criteria are taken word for word from

Final_User Stories.docx (US-01 to US-35) and from the four stories the team added on 14 October 2026 (US-36

to US-39).

## 1. How to read a user story

- **Story statement.** Written as “As a type of user, I want a goal, so that a benefit.”

- **Acceptance criteria.** Clear checks that must all pass before the story is accepted at the sprint review.

- **Priority.** Uses the MoSCoW method: Must (the product cannot work without it), Should (important, but the

product still works without it) and Could (useful, done if time allows).

- **Story points.** The relative size of the work: the sum of the backlog estimates of the tasks that build the

story (a task that serves several stories is split between them). For Stretch stories, the Stretch backlog

estimate.

- **Sprint.** The sprint or sprints in which the story is built (Sprint 0 to Sprint 4).

- **Tier.** Core stories are committed for the release on 30 November. Stretch stories are done only if time

allows.

- **Requirements.** The requirements from the Requirements Specification that the story builds, as tagged in

the stories document.

- **Notes in square brackets.** An acceptance criterion followed by a note in square brackets is deferred to a

Stretch item or delivered with a stated limit.

### Backlog summary

| **Tier** | **Stories** | **Story points** |
|---|---:|---:|
| Core | 28 | 179 |
| Stretch | 11 | 34 |
| **Total** | **39** | **213** |

By priority: 28 Must, 2 Should and 9 Could.

## Epics

| **Epic** | **Name and purpose** | **Stories** | **Points** |
|---|---|---:|---:|
| EP-01 | **Account & Access** — Create an account and keep using it securely. | 6 | 24 |
| EP-02 | **Personal Expense Tracking** — Record, correct and find every personal expense with little effort. | 6 | 37 |
| EP-03 | **Smart Capture & AI Assistant** — Let AI fill in details and answer questions about my money. | 3 | 29 |
| EP-04 | **Spending Insights & Budgets** — Understand my spending and stay within my goals. | 3 | 38 |
| EP-05 | **Groups & Membership** — Form groups (including families) and control who is in them. | 3 | 20 |
| EP-06 | **Shared Expenses & Settlements** — Split shared costs fairly and settle up. | 5 | 30 |
| EP-07 | **Customer Support** — Get help with problems and track the answers. | 3 | 8 |
| EP-08 | **Administration & Oversight** — Run and monitor the system without code changes. | 2 | 5 |
| EP-09 | **Quality & Trust (cross-cutting)** — A fast, secure, reliable app I can trust with my money. | 4 | 11 |
| EP-10 | **Parental Mode** — Let a parent guide a child's spending, with the child's consent. | 3 | 8 |
| EP-11 | **Notifications** — Get only the alerts that matter to me. | 1 | 3 |

EP-09 holds the non-functional stories; they apply to every other epic.

## 2. List of user stories

### EP-01: Account & Access

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-01 | Registration | Must | 5 | 1 | Core |
| US-02 | Login | Must | 5 | 1 | Core |
| US-03 | Password Visibility Toggle | Must | 2 | 1, 3 | Core |
| US-04 | Forgot Password | Should | 5 | — | Stretch |
| US-05 | Remember Me and Multi-Device Sync | Must | 4 | 1 | Core |
| US-06 | Change Password | Must | 3 | 3 | Core |

### EP-02: Personal Expense Tracking

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-07 | Add Expense | Must | 10 | 1 | Core |
| US-08 | Delete Expense | Must | 3 | 1 | Core |
| US-09 | Edit Expense | Must | 3 | 1 | Core |
| US-13 | Recent Expenses | Must | 6 | 2 | Core |
| US-14 | Recurring Expenses | Must | 11 | 3 | Core |
| US-15 | Search and Filter Transactions | Must | 4 | 2 | Core |

### EP-03: Smart Capture & AI Assistant

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-16 | Scan Bill to Create Expense | Must | 15 | 2–3 | Core |
| US-24 | AI Chat Assistant | Must | 6 | 3 | Core |
| US-26 | AI Category Suggestion | Must | 8 | 1 | Core |

### EP-04: Spending Insights & Budgets

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-11 | Monthly Savings | Should | 5 | — | Stretch |
| US-12 | Total Spending Over Time | Must | 12 | 2 | Core |
| US-25 | AI Goal Setting | Must | 21 | 2–3 | Core |

### EP-05: Groups & Membership

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-17 | Create Group and Invite Members | Must | 8 | 1–2 | Core |
| US-21 | Manage Group Details and Roles | Must | 7 | 3 | Core |
| US-22 | Leave Group | Must | 5 | 2 | Core |

### EP-06: Shared Expenses & Settlements

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-10 | Track Money Owed | Must | 6 | 2 | Core |
| US-18 | Add Shared Expense | Must | 4 | 2 | Core |
| US-19 | Unequal Split | Must | 6 | 2 | Core |
| US-20 | View Balances | Must | 7 | 2 | Core |
| US-23 | Edit or Delete Group Expense | Must | 7 | 1–3 | Core |

### EP-07: Customer Support

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-27 | Raise Support Request | Could | 3 | — | Stretch |
| US-28 | Track Support Request | Could | 3 | — | Stretch |
| US-29 | Manage Support Requests | Could | 2 | — | Stretch |

### EP-08: Administration & Oversight

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-30 | Configure System Settings | Could | 3 | — | Stretch |
| US-31 | Application Usage Overview | Could | 2 | — | Stretch |

### EP-09: Quality & Trust (cross-cutting)

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-32 | Performance and Responsiveness | Must | 2 | 1–4 | Core |
| US-33 | Privacy and Security | Must | 3 | 1–4 | Core |
| US-34 | Data Integrity | Must | 4 | 2–4 | Core |
| US-35 | Scalability and Availability | Must | 2 | 3 | Core |

### EP-10: Parental Mode

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-36 | Monitor Child Account | Could | 3 | — | Stretch |
| US-37 | Set Spending Limits | Could | 3 | — | Stretch |
| US-38 | Child Consent | Could | 2 | — | Stretch |

### EP-11: Notifications

| **ID** | **Title** | **Priority** | **Points** | **Sprint** | **Tier** |
|---|---|---:|---:|---|---|
| US-39 | Notification Preferences | Could | 3 | — | Stretch |

## 3. User stories in full

### EP-01: Account & Access

Create an account and keep using it securely.

#### **US-01: Registration**

**Priority:** Must | **Story points:** 5 | **Sprint:** 1 | **Tier:** Core | **Requirements:** FR-01

As a new user, I want to register using my email and password, but if I already have an account, I want to be easily guided to

the login page.

**Acceptance criteria**

1. The signup form must include fields for email, password, and confirm password.

2. The system checks if the email already exists and, if so, displays an error: "Account already exists. Please log in," with a

direct link to the login page.

3. Successful signup creates an account and redirects the user to their dashboard.

4. The form must include a clear link that says, "Already have an account? Login."

#### **US-02: Login**

**Priority:** Must | **Story points:** 5 | **Sprint:** 1 | **Tier:** Core | **Requirements:** FR-02

As a registered user, I want to log in with my email and password so I can securely access my expense dashboard.

**Acceptance criteria**

1. The login form includes fields for email and password.

2. Credentials are validated against the database.

3. If correct, the user is redirected to the dashboard; otherwise, an error message is shown.

#### **US-03: Password Visibility Toggle**

**Priority:** Must | **Story points:** 2 | **Sprint:** 1, 3 | **Tier:** Core | **Requirements:** NFR-01

As a user filling out any form with a password, I want to toggle the password's visibility so I can confirm I entered it correctly.

**Acceptance criteria**

1. All password and "confirm password" fields must have an "eye" icon.

2. By default, the password text is masked (dots or asterisks).

3. Clicking the icon reveals the password in plain text; clicking again re-masks it.

#### **US-04: Forgot Password**

**Priority:** Should | **Story points:** 5 | **Sprint:** — | **Tier:** Stretch | **Requirements:** FR-02, NFR-03 | Stretch item: ST-01**

As a user who has forgotten my password, I want a simple and secure way to reset it so that I can regain access to my

account.

**Acceptance criteria**

1. The login form displays a "Forgot password?" link.

2. Clicking the link takes the user to a page where they can enter their registered email.

3. The system sends a time-sensitive password reset link to that email.

4. Following the link allows the user to set a new password and log in.

#### **US-05: Remember Me and Multi-Device Sync**

**Priority:** Must | **Story points:** 4 | **Sprint:** 1 | **Tier:** Core | **Requirements:** FR-02

As a user, I want the option to stay logged in and access my data in real-time from multiple devices.

**Acceptance criteria**

1. A "Remember me" checkbox on the login form will maintain the user's session after the app is closed.

2. The system supports concurrent logins, and any data changes (like a new expense) will sync in real-time across all active

devices. [delivered as near real-time, within about 30 s]

3. A user can view and manage their active sessions from their account settings. [Stretch ST-02]

#### **US-06: Change Password**

**Priority:** Must | **Story points:** 3 | **Sprint:** 3 | **Tier:** Core | **Requirements:** FR-02, NFR-03

As a user, I want to change my password while logged in so that I can keep my account secure.

**Acceptance criteria**

1. The form requires the current password, a new password and a confirmation.

2. The new password must meet strength rules, with real-time feedback.

3. A confirmation message or email is sent after a successful change.

### EP-02: Personal Expense Tracking

Record, correct and find every personal expense with little effort.

#### **US-07: Add Expense**

**Priority:** Must | **Story points:** 10 | **Sprint:** 1 | **Tier:** Core | **Requirements:** FR-03, DR-01

As a user, I want to add an expense with details so I can maintain a complete record of my spending.

**Acceptance criteria**

1. Must allow entry of amount, category, date, payment mode, and optional notes.

2. The expense should appear instantly in the transaction history.

3. Prevents saving if the amount is invalid.

4. Supports quick-add for frequent expenses. [Stretch ST-04]

5. If offline, expenses must be stored locally and synced later. [Stretch ST-09]

#### **US-08: Delete Expense**

**Priority:** Must | **Story points:** 3 | **Sprint:** 1 | **Tier:** Core | **Requirements:** FR-03, DR-05

As a user, I want to delete expenses so that I can correct mistakes or remove old entries.

**Acceptance criteria**

1. Must allow deletion from history.

2. The system must confirm before deletion.

3. Once deleted, the expense is removed from reports.

4. Deleted entries can be undone briefly.

#### **US-09: Edit Expense**

**Priority:** Must | **Story points:** 3 | **Sprint:** 1 | **Tier:** Core | **Requirements:** FR-03, DR-01, DR-05

As a user, I want to edit the details of an expense I've already logged, so that I can correct any mistakes or update

information without having to delete and re-enter the entire transaction.

**Acceptance criteria**

1. The user must be able to access an "Edit" option from the transaction history list or the detailed expense view.

2. Clicking "Edit" must open a pre-filled form with all the existing expense details.

3. The user can change any of the fields in the form.

4. Upon saving, the changes must be instantly reflected in the transaction history and all related reports or charts.

5. The system must re-validate the new information before saving.

6. There must be a clear "Cancel" button to discard any changes and return to the previous screen.

#### **US-13: Recent Expenses**

**Priority:** Must | **Story points:** 6 | **Sprint:** 2 | **Tier:** Core | **Requirements:** FR-03

As a user, I want to view my most recent expenses so that I don't lose track of new entries.

**Acceptance criteria**

1. Must display at least the last 5-10 entries.

2. Each entry shows date, amount, category, and notes.

3. Clicking a transaction shows full details.

4. Must allow swipe actions like delete or edit.

#### **US-14: Recurring Expenses**

**Priority:** Must | **Story points:** 11 | **Sprint:** 3 | **Tier:** Core | **Requirements:** FR-11, DR-09

As a user, I want recurring expenses to be managed automatically so that I don't need to add them manually each time.

**Acceptance criteria**

1. Must allow marking an expense as recurring (daily, weekly, monthly).

2. Recurring expenses are added automatically to the history.

3. Notification must be sent before adding a recurring expense.

4. Must allow pausing or cancelling recurring expenses.

#### **US-15: Search and Filter Transactions**

**Priority:** Must | **Story points:** 4 | **Sprint:** 2 | **Tier:** Core | **Requirements:** FR-03, NFR-01

As a user, I want to search and filter my transactions so that I can quickly find a specific expense.

**Acceptance criteria**

1. A search bar matches notes, category, or merchant.

2. Filters cover date range, category, amount range and payment mode.

3. Filters can be combined and cleared with one tap.

4. A friendly "No results found" message appears when nothing matches.

### EP-03: Smart Capture & AI Assistant

Let AI fill in details and answer questions about my money.

#### **US-16: Scan Bill to Create Expense**

**Priority:** Must | **Story points:** 15 | **Sprint:** 2–3 | **Tier:** Core | **Requirements:** FR-12, DR-10

As a user, I want to upload or photograph a bill so that the expense details are filled in automatically.

**Acceptance criteria**

1. The user can take a photo or upload an image or PDF. [PDF part: Stretch ST-06]

2. The system extracts merchant, date, amount and items where the OCR supports it.

3. The extracted data is shown in a pre-filled expense form.

4. The user can edit any value before saving.

5. The bill image is stored and linked to the expense, viewable from the expense details, and deleted along with the

expense.

6. The expense is saved only after the user confirms the extracted details.

#### **US-24: AI Chat Assistant**

**Priority:** Must | **Story points:** 6 | **Sprint:** 3 | **Tier:** Core | **Requirements:** FR-06

As a user, I want to chat with an AI assistant so that I can quickly get answers about my expenses.

**Acceptance criteria**

1. An AI chatbot is integrated into the app for expense-related queries.

2. Respond to questions like "How much did I spend on food last week?"

3. Displays text answers and shows fallback suggestions if it cannot answer.

#### **US-26: AI Category Suggestion**

**Priority:** Must | **Story points:** 8 | **Sprint:** 1 | **Tier:** Core | **Requirements:** FR-06, DR-02

As a user adding an expense, I want the AI to intelligently suggest a category based on my description so that I can save time

and keep my records consistent.

**Acceptance criteria**

1. The AI must analyse the transaction description in real-time to suggest the most likely expense category.

2. The user must always have the final choice to accept the AI's suggestion or manually select a different category.

### EP-04: Spending Insights & Budgets

Understand my spending and stay within my goals.

#### **US-11: Monthly Savings**

**Priority:** Should | **Story points:** 5 | **Sprint:** — | **Tier:** Stretch | **Requirements:** FR-04 | Stretch item: ST-03**

As a user, I want to see how much I saved each month so I can track progress toward my goals.

**Acceptance criteria**

1. Must compare income vs expenses.

2. If no income, allow setting a budget baseline.

3. Shows savings as a number and a percentage.

4. Highlights months with negative savings.

5. Displays trend over past months.

#### **US-12: Total Spending Over Time**

**Priority:** Must | **Story points:** 12 | **Sprint:** 2 | **Tier:** Core | **Requirements:** FR-04

As a user, I want to check my total spending over time so that I can reflect on my habits.

**Acceptance criteria**

1. Must display cumulative total.

2. Allows filtering by time range.

3. Updates dynamically as expenses change.

4. Supports breakdown by category over history.

#### **US-25: AI Goal Setting**

**Priority:** Must | **Story points:** 21 | **Sprint:** 2–3 | **Tier:** Core | **Requirements:** FR-06, FR-10

As a user, I want to set goals with AI assistance so that I can stick to my budget.

**Acceptance criteria**

1. AI recommends realistic budget goals based on spending patterns.

2. Tracks progress and sends timely reminders.

3. Notifies me if I exceed the budget and congratulates me on achieving goals.

### EP-05: Groups & Membership

Form groups (including families) and control who is in them.

#### **US-17: Create Group and Invite Members**

**Priority:** Must | **Story points:** 8 | **Sprint:** 1–2 | **Tier:** Core | **Requirements:** FR-13, DR-04, FR-14

As a user, I want to create groups and invite members so that we can manage shared expenses.

**Acceptance criteria**

1. Must allow group creation with name and description.

2. Members can be invited via email, phone, or link. [invite emails delivered in-app; sending email: Stretch ST-08]

3. Users can accept or decline invitations.

4. Must support joining via link or code.

5. Group admin can remove members.

#### **US-21: Manage Group Details and Roles**

**Priority:** Must | **Story points:** 7 | **Sprint:** 3 | **Tier:** Core | **Requirements:** FR-13

As a group admin, I want to edit group details and manage roles so that the group stays organised.

**Acceptance criteria**

1. The admin can change group name, description and photo. [photo: Stretch ST-07]

2. The admin can promote members to co-admin or demote them.

3. Only admins can remove members or delete the group.

4. Members are notified when roles or details change.

#### **US-22: Leave Group**

**Priority:** Must | **Story points:** 5 | **Sprint:** 2 | **Tier:** Core | **Requirements:** FR-13, DR-06

As a group member, I want to leave a group so that I am no longer part of expenses that don't concern me.

**Acceptance criteria**

1. Leaving requires confirmation.

2. If the user has unsettled balances, a warning is shown first.

3. Past expenses involving the user remain visible in the group history.

### EP-06: Shared Expenses & Settlements

Split shared costs fairly and settle up.

#### **US-10: Track Money Owed**

**Priority:** Must | **Story points:** 6 | **Sprint:** 2 | **Tier:** Core | **Requirements:** FR-05, FR-08, DR-06

As a user, I want to track money I owe or money owed to me so I can settle balances easily.

**Acceptance criteria**

1. Must allow tagging expenses as 'paid by me' or 'shared'.

2. The system automatically calculates balances.

3. Shows clear labels such as 'You owe X' or 'Y owes you'.

4. Allows manual settlement once payment is made.

5. Sends optional reminders for pending settlements.

#### **US-18: Add Shared Expense**

**Priority:** Must | **Story points:** 4 | **Sprint:** 2 | **Tier:** Core | **Requirements:** FR-05, DR-01, DR-04, FR-14

As a group member, I want to add shared expenses so that everyone's contributions are visible.

**Acceptance criteria**

1. Must allow entry of amount, payer, participants, and category.

2. By default, it is split equally among all members.

3. Appears instantly in the group transaction list.

4. Invalid entries must be blocked.

5. Must allow attaching notes or receipts. [receipts: Stretch ST-06]

#### **US-19: Unequal Split**

**Priority:** Must | **Story points:** 6 | **Sprint:** 2 | **Tier:** Core | **Requirements:** FR-05, DR-03

As a group member, I want to split costs unequally so that amounts reflect real spending.

**Acceptance criteria**

1. Must allow manual split by percentages or fixed amounts or even by parts.

2. The system must validate totals.

3. Supports mixed contributions. [multiple-payer screen: Stretch ST-05]

4. Displays how much each member owes.

#### **US-20: View Balances**

**Priority:** Must | **Story points:** 7 | **Sprint:** 2 | **Tier:** Core | **Requirements:** FR-05, DR-06, FR-14

As a group member, I want to view balances so that we can settle easily.

**Acceptance criteria**

1. The system must auto-calculate balances.

2. Balances are shown in simple terms.

3. Allows marking balances as settled.

4. Supports partial settlements.

5. Updates balance dynamically.

#### **US-23: Edit or Delete Group Expense**

**Priority:** Must | **Story points:** 7 | **Sprint:** 1–3 | **Tier:** Core | **Requirements:** FR-05, DR-05, DR-06

As a group member, I want to edit or delete an expense I added so that mistakes can be corrected.

**Acceptance criteria**

1. Only the creator or a group admin can edit or delete a group expense.

2. Balances are recalculated immediately after a change.

3. All members are notified of the change.

4. The change is recorded in the group's transaction history.

### EP-07: Customer Support

Get help with problems and track the answers.

#### **US-27: Raise Support Request**

**Priority:** Could | **Story points:** 3 | **Sprint:** — | **Tier:** Stretch | **Requirements:** FR-07 | Stretch item: ST-10**

As a user, I want to report a problem or raise a support request so that I can get help.

**Acceptance criteria**

1. A "Help & Support" section has a form with issue type, description and an optional screenshot.

2. The user receives a ticket number on submission.

3. A confirmation appears in-app and by email.

#### **US-28: Track Support Request**

**Priority:** Could | **Story points:** 3 | **Sprint:** — | **Tier:** Stretch | **Requirements:** FR-07, FR-08 | Stretch item: ST-10**

As a user, I want to check the status of my support request so that I know when it will be resolved.

**Acceptance criteria**

1. Tickets show a status (Open, In progress, Resolved).

2. The user gets a notification when support replies.

3. The user can reply and reopen a ticket.

#### **US-29: Manage Support Requests**

**Priority:** Could | **Story points:** 2 | **Sprint:** — | **Tier:** Stretch | **Requirements:** FR-07, FR-15, DR-12 | Stretch item: ST-10**

As a customer support representative or system admin, I want to view, respond to and update support requests so that

users' problems get resolved.

**Acceptance criteria**

1. All requests are listed with issue details, priority and status (Open, In progress, Resolved).

2. Requests can be assigned, replied to and closed.

3. Only authorised staff can see the user information attached to a request.

4. Statistics show the number of open and resolved requests.

### EP-08: Administration & Oversight

Run and monitor the system without code changes.

#### **US-30: Configure System Settings**

**Priority:** Could | **Story points:** 3 | **Sprint:** — | **Tier:** Stretch | **Requirements:** FR-15 | Stretch item: ST-11**

As a system admin, I want to configure system settings so that the app can be adjusted without code changes.

**Acceptance criteria**

1. The admin can manage default categories, supported currencies and notification templates.

2. Changes are validated and audit-logged.

3. The admin can enable or disable features such as OCR or AI.

#### **US-31: Application Usage Overview**

**Priority:** Could | **Story points:** 2 | **Sprint:** — | **Tier:** Stretch | **Requirements:** NFR-06, NFR-08 | Stretch item: ST-11**

As a company owner, I want to see aggregated usage statistics so that I can plan improvements and resources.

**Acceptance criteria**

1. Management can see the number of registered users and general usage trends.

2. Only aggregated data is shown; individual users' financial details are never exposed.

3. Access is restricted to authorised management users.

### EP-09: Quality & Trust (cross-cutting)

A fast, secure, reliable app I can trust with my money.

#### **US-32: Performance and Responsiveness**

**Priority:** Must | **Story points:** 2 | **Sprint:** 1–4 | **Tier:** Core | **Requirements:** NFR-02

As a user, I want the app to open quickly and feel responsive so that I don't get frustrated waiting.

**Acceptance criteria**

1. The system must launch and display the main dashboard within a few seconds. [free hosting may sleep when idle;

warmed up before demos]

2. Navigating between main screens (e.g., Dashboard, Transactions, Reports) must be smooth.

3. Scrolling through long lists, such as transaction history, must remain fluid and responsive.

#### **US-33: Privacy and Security**

**Priority:** Must | **Story points:** 3 | **Sprint:** 1–4 | **Tier:** Core | **Requirements:** NFR-03, NFR-08

As a user, I want my account to stay private so that nobody else can see my money details.

**Acceptance criteria**

1. All user passwords and data must be stored securely.

2. All transfers must be encrypted in order to prevent any sensitive information from being exposed.

3. The system must offer optional two-factor authentication (2FA) for users who want an extra layer of security. [Stretch

ST-12]

#### **US-34: Data Integrity**

**Priority:** Must | **Story points:** 4 | **Sprint:** 2–4 | **Tier:** Core | **Requirements:** NFR-04

As a user, I want my data to never be lost or corrupted so that I can trust the app.

**Acceptance criteria**

1. Data is backed up regularly and can be recovered.

2. Failed saves show an error rather than silently losing data.

3. Offline changes sync without duplicates. [Stretch ST-09]

#### **US-35: Scalability and Availability**

**Priority:** Must | **Story points:** 2 | **Sprint:** 3 | **Tier:** Core | **Requirements:** NFR-06, NFR-07

As a user, I want the app to stay fast and available as more people use it so that my experience does not degrade.

**Acceptance criteria**

1. The system supports growing numbers of users, groups and transactions without noticeable slowdown.

2. Planned maintenance is announced in advance.

3. The system stays available outside maintenance windows. [free hosting may sleep when idle; warmed up before demos]

### EP-10: Parental Mode

Let a parent guide a child's spending, with the child's consent.

#### **US-36: Monitor Child Account**

**Priority:** Could | **Story points:** 3 | **Sprint:** — | **Tier:** Stretch | **Requirements:** FR-09, DR-12 | Stretch item: ST-14**

As a parent, I want to monitor my child's account so that I can guide their spending.

**Acceptance criteria**

1. Must allow linking child accounts with email or ID.

2. Parents can view all child transactions.

3. The system generates alerts for limits set by parents.

4. Parents can see categorised reports of the child's expenses.

5. Parents are notified of unusual transactions.

6. Linking requires consent from both parent and child.

#### **US-37: Set Spending Limits**

**Priority:** Could | **Story points:** 3 | **Sprint:** — | **Tier:** Stretch | **Requirements:** FR-09, DR-07, DR-08 | Stretch item: ST-14**

As a parent, I want to set spending limits so that I can teach responsible usage.

**Acceptance criteria**

1. Must allow setting weekly or monthly caps.

2. Parents can apply category restrictions.

3. The system alerts the parent and child at 75, 90, and 100 per cent.

4. Transactions over limits are blocked or flagged.

5. Attempts to bypass are logged and notified.

6. Parents can edit or remove restrictions anytime.

#### **US-38: Child Consent**

**Priority:** Could | **Story points:** 2 | **Sprint:** — | **Tier:** Stretch | **Requirements:** FR-09, NFR-08 | Stretch item: ST-14**

As a child user, I want to give or withdraw consent for linking so that I know who can see my spending.

**Acceptance criteria**

1. A link request from a parent must be accepted by the child.

2. The child can see what the parent can view.

3. Unlinking requires the parent to be notified.

### EP-11: Notifications

Get only the alerts that matter to me.

#### **US-39: Notification Preferences**

**Priority:** Could | **Story points:** 3 | **Sprint:** — | **Tier:** Stretch | **Requirements:** FR-08 | Stretch item: ST-16**

As a user, I want to control my notification preferences so that I only get alerts that matter to me.

**Acceptance criteria**

1. Toggles are available per type: budgets, reminders, groups, recurring, AI tips.

2. Channels can be chosen: push, in-app, email.

3. Quiet hours can be set.

4. A failed notification never causes the underlying expense action to fail.
