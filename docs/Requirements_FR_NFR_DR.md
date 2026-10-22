# Smart Expense Splitter & Tracker
**Group No:** 28 | **Lab Group:** 4

## 2. Requirements

### 2.1 Functional Requirements (FR)

| ID | Requirement | Description | Identified By |
|---|---|---|---|
| FR-01 | User Registration | Users can create an account using required personal info and credentials | User surveys, user stories |
| FR-02 | User Login & Session Management | Registered users can securely log in, log out and keep authenticated sessions | User stories |
| FR-03 | All-in-One Expense Tracking | Record, edit, delete, categorize and view personal expenses in one place | Existing-system analysis, user interviews |
| FR-04 | Data Analysis & Visualization | Charts, summaries and spending insights from recorded expenses | User surveys, interviews, prototyping |
| FR-05 | Group Expense Splitting | Create shared expenses, split bills among members, track contributions and balances | Existing-system analysis, interviews, surveys| 
| FR-06 | AI Advisor | GenAI analyses spending patterns, categorizes expenses, gives summaries and suggestions | Brainstorming, interviews, surveys |
| FR-07 | Customer Support | Users can report problems, raise support requests and get assistance | Stakeholder analysis |
| FR-08 | Budgeting & Alerts | Create category budgets; notify when nearing or exceeding limits | User surveys, interviews |
| FR-09 | Recurring Expense Automation | Create recurring expenses that are auto-recorded on schedule | User interviews |
| FR-10 | Bill/Receipt Scanning & Data Extraction | Upload bills/receipts and extract amount, date, merchant, category | Bill/OCR analysis, brainstorming |
| FR-11 | Group Management | Admins create groups, add/remove members, manage group expenses | Group-user interviews, stakeholder analysis |
| FR-12 | Family/Household Expense Management | Family users manage shared expenses and monitor household budgets | Family interviews, contextual inquiry |
| FR-13 | System Administration | Authorized admins manage users, handle reported issues, configure system settings | Administrator interviews, stakeholder analysis|

### 2.2 Non-Functional Requirements (NFR)

| ID | Requirement | Description | Identified By | 
|---|---|---|---|
| NFR-01 | Usability | Simple, intuitive UI; record and manage expenses with minimal effort | User surveys |
| NFR-02 | Performance | Fast response for adding expenses, viewing dashboards, loading history | User experience analysis |
| NFR-03 | Security | Protect accounts and financial info via authentication, authorization, secure data handling | Data privacy/security standards|
| NFR-04 | Reliability | Store and retrieve expense data without loss or corruption | Stakeholder expectations |
| NFR-05 | Maintainability | Clean, modular, well-organized code | Development-team practices|
| NFR-06 | Scalability | Support growing users, groups, expenses and transactions without major slowdown | Brainstorming, management expectations|
| NFR-07 | Availability | Available whenever required, except planned maintenance | User and management expectations |
| NFR-08 | Data Privacy | Personal/financial data visible only to authorized users | User concerns, security analysis |
| NFR-09 | Accuracy | Accurate splits, balances, budgets and extracted bill info | User interviews, system analysis |
| NFR-10 | Compatibility | Works across common web browsers and supported devices | User interviews, system analysis |

### 2.3 Domain Requirements (DR)

| ID | Requirement | Source | 
|---|---|---|
| DR-01 | Every expense must have a valid positive monetary amount | Expense-management analysis | 
| DR-02 | Each expense must be assigned a category (Food, Travel, Shopping, Bills, Entertainment, etc.) | User interviews, existing-system analysis |
| DR-03 | For a shared expense, the sum of all members' shares equals the total (subject to rounding rule) | Group-expense analysis |
| DR-04 | Only group members can participate in that group's shared expenses | Group-user analysis | 
| DR-05 | Users can modify/delete only expenses they are authorized to manage | Stakeholder analysis |
| DR-06 | System maintains the amount each member owes or is owed, based on shared expenses and settlements | Group-expense analysis |
| DR-07 | A budget has a defined amount and time period (weekly, monthly, etc.) | Budgeting requirements | 
| DR-08 | Alert generated when spending reaches a configured threshold or exceeds the budget | User surveys, interviews | 
| DR-09 | Recurring expenses follow the user-configured frequency (daily, weekly, monthly, yearly) | User interviews |
| DR-10 | For uploaded bills, extract merchant, date, amount, items where the OCR service supports it | Bill/OCR analysis | 
| DR-11 | Totals, balances, splits and budgets use proper monetary precision and rounding | Expense-management analysis | 
| DR-12 | Users access financial info only for themselves and groups/families they have permission for | Security and privacy analysis |

> **Status:** *Final* = sufficiently confirmed. *Provisional* = identified but may change as elicitation continues.
