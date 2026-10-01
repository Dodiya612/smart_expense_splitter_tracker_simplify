# Smart Expense Splitter & Tracker
**Group No:** 28 | **Lab Group:** 4

## 4. Activity Diagram

**Swimlanes:** User | Group Admin | System

### 4.1 Flow Description

1. **User** logs in.
2. **System** authenticates the user.
   - *Not valid* → System shows an error.
   - *Valid* → System opens the system.
3. **User** selects or creates a group.
4. **Group Admin** manages / selects group members.
5. **User** enters expense details (amount, category, date, etc.).
6. **System** validates the details.
   - *No* → User corrects the answer and re-enters details.
   - *Yes* → continue.
7. **System** lets the user choose the split, then calculates shares.
8. **System** saves the expense.
9. **System** updates balances.
10. **System** sends notifications.
11. **User** views the updated balances.
12. End.

### 4.2 Diagram (Mermaid)

```mermaid
flowchart TD
    Start([Start]) --> Login

    subgraph User
        Login[Login]
        SelGrp[Select / Create Group]
        Enter[Enter expense details<br/>amount, category, date, etc.]
        Correct[Correct answer]
        View[View updated balances]
    end

    subgraph GroupAdmin[Group Admin]
        Manage[Manage / Select group members]
    end

    subgraph System
        Auth[Authenticate user]
        AuthD{Valid?}
        Err[Show error]
        Open[Open system]
        Validate[Validate details]
        ValD{Valid?}
        Split[Choose split]
        Calc[Calculate shares]
        Save[Save expense]
        Update[Update balance]
        Notify[Send notifications]
    end

    Login --> Auth --> AuthD
    AuthD -- Not valid --> Err
    AuthD -- Valid --> Open
    Open --> SelGrp --> Manage --> Enter --> Validate --> ValD
    ValD -- No --> Correct --> Enter
    ValD -- Yes --> Split --> Calc --> Save --> Update --> Notify --> View --> End([End])
```

### 4.3 Related Requirements

| Step | Requirement |
|---|---|
| Login / authenticate | FR-02 |
| Select/create group, manage members | FR-05, FR-13, DR-04 |
| Enter and validate expense | FR-03, DR-01, DR-02 |
| Choose split, calculate shares | FR-05, DR-03, DR-11 |
| Update balance | DR-06 |
| Send notifications | FR-08 |
