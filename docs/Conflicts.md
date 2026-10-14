# Coinscious: Smart Expense Splitter & Tracker

**Course:** IT314 Software Engineering  
**Group:** 28 (10 members)  
**Document:** User Story Conflicts  
**Version:** 1.0  
**Date:** 14 October 2026

## 4. Requirements Conflicts and Resolutions

This document consolidates the conflict analysis for the 39 Coinscious user stories (US-01–US-39). It records the stories and acceptance criteria involved, conflict type, severity, resolution, and status. Sprint task IDs (for example, `S3-BE-03`) and Stretch items (`ST-xx`) refer to the Sprint Plan. Roadmap sections (§), deviations (`D1–D11`), and assumptions (`A1–A11`) refer to `docs/ROADMAP.md`.

### 4.1 How to Read a Conflict

- **Quality trade-off:** A functional story conflicts with a non-functional requirement such as privacy, security, performance, or reliability.
- **Functional contradiction:** Two functional stories require incompatible behaviour.
- **Overlap:** Stories describe the same capability in different ways.
- **Ambiguity:** A term has different or unclear meanings across stories.
- **Severity:** **High** means potential incorrect financial results or a security/privacy issue; **Medium** means a broken user journey or user confusion; **Low** means a wording or minor issue.
- **Status:** **Resolved in release** means the resolution is planned for implementation and testing by 30 November; **Accepted risk** means a known, mitigated trade-off; **Resolved by scope** means the feature is excluded from the release; **Design rule** means a rule is fixed now for a Stretch feature.

### 4.2 Summary

| Conflict type | Resolved in release | Accepted risk | Resolved by scope | Design rule | Total |
|---|---:|---:|---:|---:|---:|
| Quality trade-off | 4 | 1 | 0 | 1 | 6 |
| Functional contradiction | 4 | 0 | 1 | 1 | 6 |
| Overlap | 1 | 0 | 0 | 2 | 3 |
| Ambiguity | 2 | 0 | 0 | 1 | 3 |
| **Total** | **11** | **1** | **1** | **5** | **18** |

**By severity:** 4 High, 10 Medium, and 4 Low.

### 4.3 Conflict Index

| ID | Conflict | Stories involved | Type | Severity | Status |
|---|---|---|---|---|---|
| CF-01 | AI processing vs. privacy | US-16, US-24, US-25, US-26, US-33 | Quality trade-off | High | Resolved in release |
| CF-02 | Convenience vs. account security | US-01, US-05, US-33 | Quality trade-off | Medium | Resolved in release |
| CF-03 | Open invite links vs. group privacy | US-17, US-33 | Quality trade-off | Medium | Resolved in release |
| CF-04 | Parent view vs. group members' privacy | US-18, US-33, US-36 | Quality trade-off | Medium | Design rule |
| CF-05 | Bill image deletion vs. backups | US-16, US-34 | Quality trade-off | Low | Accepted risk |
| CF-06 | Live features vs. performance | US-05, US-14, US-26, US-32 | Quality trade-off | Medium | Resolved in release |
| CF-07 | Offline entry vs. online features | US-05, US-07, US-16, US-26 | Functional contradiction | Medium | Resolved by scope |
| CF-08 | Removing members/groups vs. balances and history | US-17, US-20, US-21, US-22, US-23 | Functional contradiction | High | Resolved in release |
| CF-09 | Editing expenses after settlement | US-20, US-23 | Functional contradiction | Medium | Resolved in release |
| CF-10 | Admin settings vs. fixed behaviour | US-11, US-12, US-16, US-20, US-24, US-25, US-26, US-30 | Functional contradiction | High | Resolved in release |
| CF-11 | Swipe actions vs. group expense permissions | US-13, US-23 | Functional contradiction | Medium | Resolved in release |
| CF-12 | Notification preferences vs. required alerts | US-14, US-36, US-37, US-39 | Functional contradiction | Medium | Design rule |
| CF-13 | Two ways to share and settle | US-10, US-18, US-20 | Overlap | Medium | Resolved in release |
| CF-14 | Savings baseline vs. budgets | US-11, US-25 | Overlap | Low | Design rule |
| CF-15 | Two alert rules for limits | US-25, US-37 | Overlap | Low | Design rule |
| CF-16 | “Admin” vs. “co-admin” | US-17, US-21, US-23 | Ambiguity | Medium | Resolved in release |
| CF-17 | Meaning of “spending” for group bills | US-11, US-12, US-18, US-19, US-25 | Ambiguity | High | Resolved in release |
| CF-18 | “Closed” vs. ticket statuses | US-28, US-29 | Ambiguity | Low | Design rule |

### 4.4 Detailed Conflicts and Resolutions

#### Quality Trade-offs

A functional story conflicts with a non-functional requirement such as privacy, security, performance, or reliability.

##### CF-01: AI Processing vs. Privacy

**Stories:** US-16 Scan Bill to Create Expense, US-24 AI Chat Assistant, US-25 AI Goal Setting, US-26 AI Category Suggestion, and US-33 Privacy and Security (AC1–2).  
**Severity:** High · **Status:** Resolved in release

**Conflict:** AI features may send bill images, expense descriptions, or spending totals to an external provider, while US-33 requires users' financial details to remain private.

**Resolution:** Send only the minimum necessary data. Do not include names or emails in prompts; use totals rather than transaction-level data for US-24 and US-25; send bill images only for extraction. Keep AI keys on the backend. Allow AI features to be disabled through `AI_ENABLED`, label AI-generated output, and explain data use in an “About AI & privacy” note (`S3-FE-05`).

##### CF-02: Convenience vs. Account Security

**Stories:** US-01 Registration (AC2), US-05 Remember Me and Multi-Device Sync (AC1), US-33 Privacy and Security.  
**Severity:** Medium · **Status:** Resolved in release

**Conflict:** The message “Account already exists. Please log in” reveals whether an email is registered. “Remember me” can also leave a lost or stolen phone logged in.

**Resolution:** Retain the required registration message as an accepted risk and rate-limit registration and login (`S3-BE-03`). The forgot-password Stretch feature (`ST-01`) should respond identically whether or not an email exists. Refresh tokens last 30 days with Remember Me and 24 hours without it, rotate on each use, and use encrypted Android storage. Changing a password (US-06) logs out other devices. Session management for US-05 AC3 is `ST-02`.

##### CF-03: Open Invite Links vs. Group Privacy

**Stories:** US-17 Create Group and Invite Members (AC2, AC4), US-33 Privacy and Security.  
**Severity:** Medium · **Status:** Resolved in release

**Conflict:** Anyone receiving a forwarded invitation link or code might join a group and see its financial information.

**Resolution:** Use random, expiring invitation codes. Admins can revoke invitations and remove members. Record every join in group history and notify members (`S2-BE-06`).

##### CF-04: Parent View vs. Group Members' Privacy

**Stories:** US-18 Add Shared Expense, US-33 Privacy and Security (AC1), US-36 Monitor Child Account (AC2).  
**Severity:** Medium · **Status:** Design rule (`ST-14`)

**Conflict:** A requirement allowing parents to view all child transactions could expose other group members' names, amounts, and group history.

**Resolution:** Parents can view the child's personal expenses and the child's own share of group expenses (amount, category, and date), but not other members' details or the group's history. The child sees exactly what the parent sees (US-38 AC2).

##### CF-05: Bill Image Deletion vs. Backups

**Stories:** US-16 Scan Bill to Create Expense (AC5), US-34 Data Integrity (AC1).  
**Severity:** Low · **Status:** Accepted risk

**Conflict:** A bill image should be deleted with its expense, but backups may retain a copy until the backup is deleted.

**Resolution:** Store backups privately, never in Git, and delete them when the course ends (§8.3). Restore backups only for disaster recovery.

##### CF-06: Live Features vs. Performance

**Stories:** US-05 Remember Me and Multi-Device Sync (AC2), US-14 Recurring Expenses (AC2), US-26 AI Category Suggestion (AC1), US-32 Performance and Responsiveness (AC1).  
**Severity:** Medium · **Status:** Resolved in release

**Conflict:** Syncing, creating due recurring expenses, and running AI analysis during startup or typing can make the app slow.

**Resolution:** Debounce AI suggestions by 600 ms without blocking the form. Add recurring expenses through a daily scheduled job; run the app's related call in the background after the first screen appears. Poll only open lists, every 30 seconds, and paginate lists. Hosting cold starts are covered by deviation D10.

#### Functional Contradictions

Two functional stories require incompatible behaviour.

##### CF-07: Offline Entry vs. Online Features

**Stories:** US-05 Remember Me and Multi-Device Sync (AC2), US-07 Add Expense (AC5), US-16 Scan Bill to Create Expense, US-26 AI Category Suggestion.  
**Severity:** Medium · **Status:** Resolved by scope

**Conflict:** Offline expenses cannot sync in real time, may conflict with edits on another device, and cannot use online bill scanning or AI suggestions.

**Resolution:** The release is online-only and syncs in about 30 seconds (D1). AI failures fall back to manual entry. Offline entry is Stretch item `ST-09` (D4); its design uses a client-generated idempotency key to prevent duplicates (US-34 AC3), applies the most recent edit, allows manual category selection offline, and disables bill scanning offline.

##### CF-08: Removing Members/Groups vs. Balances and History

**Stories:** US-17 Create Group and Invite Members (AC5), US-20 View Balances, US-21 Manage Group Details and Roles (AC3), US-22 Leave Group (AC2–3), US-23 Edit or Delete Group Expense (AC4).  
**Severity:** High · **Status:** Resolved in release

**Conflict:** Removing members, leaving a group with debt, or deleting a group must not corrupt balances or erase required history.

**Resolution:** Leaving or removal ends membership only (`left_at`). Former members remain in balances, can still settle debts, and retain visibility of past expenses. Show the balance in a warning before a member leaves or an admin removes them. Block group deletion while any balance is non-zero; after all balances are settled, notify members before deletion.

##### CF-09: Editing Expenses After Settlement

**Stories:** US-20 View Balances (AC3), US-23 Edit or Delete Group Expense (AC1–2).  
**Severity:** Medium · **Status:** Resolved in release

**Conflict:** Editing or deleting an expense after settlement could silently make a settled balance incorrect.

**Resolution:** Store settlements as payments rather than a “settled” flag. Recalculate balances from expenses and payments. Notify members when an edit changes the balance (US-23 AC3) and record the change in group history (US-23 AC4).

##### CF-10: Admin Settings vs. Fixed Behaviour

**Stories:** US-11 Monthly Savings, US-12 Total Spending Over Time, US-16 Scan Bill to Create Expense, US-20 View Balances, US-24 AI Chat Assistant, US-25 AI Goal Setting, US-26 AI Category Suggestion, US-30 Configure System Settings (AC1, AC3).  
**Severity:** High · **Status:** Resolved in release

**Conflict:** Admins can disable AI or bill scanning even though related stories require those capabilities. Changing supported currencies also affects totals, savings, balances, and budgets.

**Resolution:** Provide non-AI fallbacks: manual bill entry, keyword-based category rules, average-based budget suggestions, and a supported-question list for chat. The server setting `AI_ENABLED` controls AI; the admin screen is `ST-11`. The release supports INR only (assumption A2). Multi-currency support (`ST-15`) must keep totals, balances, and budgets separate by currency.

##### CF-11: Swipe Actions vs. Group Expense Permissions

**Stories:** US-13 Recent Expenses (AC4), US-23 Edit or Delete Group Expense (AC1).  
**Severity:** Medium · **Status:** Resolved in release

**Conflict:** Swipe-to-edit/delete in a recent-expenses list could allow any member to modify group expenses, although only the creator or an admin is permitted to do so.

**Resolution:** Show personal and group expenses in the recent list, but offer Edit/Delete only to authorized users: the owner for personal expenses, and the creator or an admin for group expenses. Enforce the same permissions on the server.

##### CF-12: Notification Preferences vs. Required Alerts

**Stories:** US-14 Recurring Expenses (AC3), US-36 Monitor Child Account (AC3), US-37 Set Spending Limits (AC3), US-39 Notification Preferences (AC1, AC3).  
**Severity:** Medium · **Status:** Design rule (`ST-14`, `ST-16`)

**Conflict:** Notification toggles and quiet hours could suppress required “due tomorrow” notices or alerts configured by a parent.

**Resolution:** Quiet hours delay only push and email notifications; in-app notifications are created immediately. A child cannot disable alerts set by a parent's limits; only the parent can change them (US-37 AC6).

#### Overlaps

Two stories describe the same capability differently.

##### CF-13: Two Ways to Share and Settle

**Stories:** US-10 Track Money Owed (AC1, AC4), US-18 Add Shared Expense, US-20 View Balances (AC3–4).  
**Severity:** Medium · **Status:** Resolved in release

**Conflict:** US-10 separately describes shared expenses and manual settlement, while US-18 handles shared expenses within groups and US-20 covers full and partial settlements.

**Resolution:** Every shared expense belongs to a group. The Add Expense form provides a “Split with a group” switch; sharing with one friend uses a two-person group. One settlement feature supports partial and full payments; a full settlement is a payment equal to the outstanding balance.

##### CF-14: Savings Baseline vs. Budgets

**Stories:** US-11 Monthly Savings (AC2), US-25 AI Goal Setting.  
**Severity:** Low · **Status:** Design rule (`ST-03`)

**Conflict:** US-11's budget baseline for users without income could create a second budget setting alongside US-25 budgets.

**Resolution:** When US-11 is implemented (`ST-03`), use the user's overall monthly budget from US-25 as the baseline rather than introducing a separate setting.

##### CF-15: Two Alert Rules for Limits

**Stories:** US-25 AI Goal Setting (AC2–3), US-37 Set Spending Limits (AC3).  
**Severity:** Low · **Status:** Design rule (`ST-14`)

**Conflict:** Parent-set limits alert at 75%, 90%, and 100%, while personal budget goals alert at the user's threshold (80% by default) and 100%.

**Resolution:** Keep the rules distinct: parent limits use fixed 75%/90%/100% thresholds, and personal budgets use their configured threshold. Both use the same notification centre.

#### Ambiguities

Stories use the same term with different or unclear meanings.

##### CF-16: “Admin” vs. “Co-admin”

**Stories:** US-17 Create Group and Invite Members (AC5), US-21 Manage Group Details and Roles (AC2–3), US-23 Edit or Delete Group Expense (AC1).  
**Severity:** Medium · **Status:** Resolved in release

**Conflict:** The stories use “group admin,” “co-admin,” and “admins” without clarifying whether they have different permissions.

**Resolution:** A co-admin is a member promoted to the admin role. All admins have the same powers, and the last admin cannot be demoted.

##### CF-17: Meaning of “Spending” for Group Bills

**Stories:** US-11 Monthly Savings, US-12 Total Spending Over Time, US-18 Add Shared Expense, US-19 Unequal Split, US-25 AI Goal Setting.  
**Severity:** High · **Status:** Resolved in release

**Conflict:** For a ₹900 group bill split among three people, it is unclear whether the payer's spending is ₹900 or only their ₹300 share. This ambiguity would make totals, savings, and budget alerts inconsistent.

**Resolution:** A user's spending equals personal expenses plus their own share of group expenses. Paying on behalf of others creates a balance owed, not additional personal spending. Use one `user_spending` query consistently.

##### CF-18: “Closed” vs. Ticket Statuses

**Stories:** US-28 Track Support Request (AC1, AC3), US-29 Manage Support Requests (AC2).  
**Severity:** Low · **Status:** Design rule (`ST-10`)

**Conflict:** US-28 defines ticket statuses as Open, In progress, and Resolved, while US-29 uses “closed,” which is not a defined status.

**Resolution:** “Close” sets the ticket status to Resolved. Reopening a ticket sets it back to Open (US-28 AC3).

### 4.5 Duplicate and Similar Conflict Review

The earlier `Conflicts.md` contained 13 broad conflicts. Several cover the same underlying issues as the 18 user-story conflicts in this document. To avoid maintaining two competing lists, the specific, story-linked conflicts from the User Story Conflicts source have been retained as the canonical set. The following broad entries are represented by more precise conflicts and are not repeated as separate items:

| Earlier broad conflict | Covered by canonical conflict(s) | Decision |
|---|---|---|
| Security/privacy vs. usability | CF-02 | Retained as the more specific account-security conflict |
| Parental mode vs. family privacy | CF-04 | Retained with explicit limits on group-member data visibility |
| OCR convenience vs. accuracy | CF-01, CF-10 | Bill-image processing and its fallback are covered in the user-story analysis; no separate generic entry retained |
| AI personalization vs. data privacy | CF-01, CF-10 | Consolidated into AI data minimization, privacy controls, and fallback behaviour |
| Notifications vs. usability | CF-12, CF-15 | Split into required-alert behaviour and distinct alert thresholds |
| Availability vs. maintenance | — | Not present as a conflict in the user-story source; omitted rather than added without source support |
| Group admin control vs. member autonomy | CF-08, CF-11, CF-16 | Covered by membership lifecycle, expense permissions, and role definitions |
| Manual vs. AI categorization | CF-01, CF-10 | Covered through AI privacy constraints and non-AI fallback behaviour; no separate duplicate entry retained |
| Personal vs. group recurring expenses | CF-06 | Recurring-expense timing/performance is addressed in the user-story source; the earlier standalone scope conflict is not duplicated |
| Customer support vs. financial privacy | — | Not present as a conflict in the user-story source; omitted rather than added without source support |
| Debt simplification vs. traceability | — | Not present as a conflict in the user-story source; omitted rather than added without source support |
| Offline entry vs. data consistency | CF-07 | Retained as the canonical offline/online scope conflict |
| Custom splitting vs. rounding precision | — | Not present as a conflict in the user-story source; omitted rather than added without source support |

**Canonical count: 18 conflicts (CF-01–CF-18).** The 13 broad conflicts are not appended as a second list because that would repeat or introduce conflicts not established in the user-story analysis. The detailed resolutions and statuses above follow the supplied User Story Conflicts document.

## Source

Compiled from `Final_User Story Conflicts_Group28.pdf` and cross-checked against the earlier `Conflicts.md`. Story IDs, severity, status, and resolution details are based on the supplied source documents. The older generic list was used only for the duplicate/overlap review.
