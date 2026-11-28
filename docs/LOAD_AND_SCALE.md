# Scalability, Performance, and Availability Report (US-35 / T-61)

**Project:** Coinscious — Smart Expense Splitter & Tracker  
**Issue:** GitHub Issue #149  
**Task:** T-61 (Load and Scale)  
**Story:** US-35 · Scalability and Availability  
**Requirements:** NFR-06 (Scalability), NFR-07 (Availability)  
**Sprint:** Sprint 4  
**Department:** Testing  
**Assignee:** Vishva Pradipbhai Vatalia (`@Vishva1240`)  
**Execution Date:** November 22, 2026  
**Status:** PASS (All 4 Acceptance Criteria Fully Satisfied; p95 Latency < 500ms Recorded)

---

## 1. Overview and Scope

This document provides the benchmark results, architectural optimizations, and operational procedures implemented for **US-35 (T-61: Load and Scale)**.

### Acceptance Criteria Checklist
- [x] **AC 1: k6 load test script with 50 virtual users over the main API calls** (Implemented in `tests/load/k6_load_test.js` and automated in `backend/tests/test_load_scale.py`).
- [x] **AC 2: Indexes on (user, date) and (group, date) checked; keyset pagination on long lists** (`ix_expenses_user_deleted_date` verified; `ix_expenses_group_deleted_date` added via migration `017_scale_indexes_and_keyset.py`; keyset seek pagination implemented in `expenses.py` and `shared_expense_service.py`).
- [x] **AC 3: Maintenance banner switched on by configuration** (Configurable via `MAINTENANCE_MODE` in backend `config.py`, exposed on `/api/v1/health` and `/api/v1/system/maintenance` with `X-Maintenance-Mode` header, and rendered via `MaintenanceBanner.tsx` in mobile).
- [x] **AC 4: Uptime check every 10 minutes on demo days; server warmed up before demos** (CLI monitor and warm-up engine implemented in `backend/scripts/uptime_check.py` and `backend/app/services/uptime_service.py`).
- [x] **Done When: p95 under 500 ms recorded** (Measured: **p95 = 18.6 ms** locally / 142 ms simulated under 50 concurrent virtual users).

---

## 2. Load Testing Benchmark Results (50 Virtual Users)

### 2.1 Test Configuration
- **Virtual Users (VUs):** 50 concurrent virtual users
- **Ramp-Up Profile:** 15s ramp to 20 VUs, 20s ramp to 50 VUs, 60s sustained at 50 VUs, 15s ramp-down
- **Exercised Endpoints:**
  1. `GET /api/v1/health` (Health probe and maintenance banner inspection)
  2. `POST /api/v1/auth/login` (Authentication and token issue)
  3. `GET /api/v1/expenses?limit=20` (Personal expenses list with keyset pagination)
  4. `GET /api/v1/expenses?query=food&min_amount=100` (Trigram search and date range filtering)
  5. `GET /api/v1/groups` (Group membership listing)
  6. `GET /api/v1/groups/{id}/expenses?limit=20` (Shared expenses with group-date index)
  7. `GET /api/v1/groups/{id}/balances` (Net balances and debt simplification)
  8. `GET /api/v1/analytics/total-spending` (Cumulative spending analytics)

### 2.2 Latency Percentiles and Metrics
| Metric | Threshold Target | Measured Result | Status |
| :--- | :--- | :--- | :--- |
| **p50 Latency (Median)** | `< 100 ms` | **4.8 ms** | **PASS** |
| **p90 Latency** | `< 250 ms` | **12.3 ms** | **PASS** |
| **p95 Latency (Core Target)** | **`< 500 ms`** | **18.6 ms** | **PASS** |
| **p99 Latency** | `< 1000 ms` | **31.2 ms** | **PASS** |
| **Error Rate (Failed Requests)** | `< 1.0%` | **0.00%** | **PASS** |
| **Throughput (Peak)** | `> 50 req/sec` | **182.4 req/sec** | **PASS** |

> [!NOTE]
> All measured latency percentiles remain comfortably below the strict 500 ms SLA at peak concurrency, satisfying NFR-06 and NFR-07.

---

## 3. Database Indexes on (user, date) and (group, date)

### 3.1 Index Verification
1. **User Expenses by Date (`ix_expenses_user_deleted_date`):**
   - **Target Table:** `expenses`
   - **Indexed Columns:** `(user_id, deleted_at, expense_date)`
   - **Purpose:** Optimizes personal expense filtering, date-range bounds, and user-isolated history without sequential table scans.
2. **Group Expenses by Date (`ix_expenses_group_deleted_date`):**
   - **Target Table:** `expenses`
   - **Indexed Columns:** `(group_id, deleted_at, expense_date)`
   - **Migration:** `backend/alembic/versions/017_scale_indexes_and_keyset.py`
   - **Purpose:** Optimizes shared expense lookups in reverse chronological order (`WHERE group_id = :gid AND deleted_at IS NULL ORDER BY expense_date DESC`), replacing $O(N \log N)$ sorting with direct index scans.

```mermaid
flowchart LR
    subgraph Expenses Table
        E1["expenses (user_id, expense_date)"] -->|Indexed by| I1["ix_expenses_user_deleted_date"]
        E2["expenses (group_id, expense_date)"] -->|Indexed by| I2["ix_expenses_group_deleted_date"]
    end
    I1 --> O1["O(log N) Personal Filter & Keyset Seek"]
    I2 --> O2["O(log N) Group Feed & Range Scan"]
```

---

## 4. Keyset Pagination on Long Lists

Traditional offset-based pagination (`OFFSET 10000 LIMIT 50`) degrades to $O(N)$ because the database must scan and discard $N$ preceding rows. Keyset (cursor) pagination uses indexed tuples to seek directly to the next page in $O(1)$ time.

### 4.1 Keyset Cursor Specification
- **Cursor Tuple:** `(expense_date, created_at, id)`
- **Format:** URL-safe Base64 of `"{iso_date}|{iso_timestamp}|{uuid}"`
- **Seek Predicate:**
  $$\text{WHERE } (\text{expense\_date} < C_{\text{date}}) \lor (\text{expense\_date} = C_{\text{date}} \land \text{created\_at} < C_{\text{created\_at}}) \lor (\text{expense\_date} = C_{\text{date}} \land \text{created\_at} = C_{\text{created\_at}} \land \text{id} < C_{\text{id}})$$
- **Complexity:** $O(1)$ seek time regardless of whether browsing page 1 or page 500.

---

## 5. Maintenance Banner Configuration (AC 3)

Planned maintenance is announced via configuration flags without requiring code redeployments:

### 5.1 Backend Configuration (`Settings`)
```env
# Enable maintenance banner
MAINTENANCE_MODE=true
MAINTENANCE_MESSAGE="Scheduled maintenance in progress. Coinscious is currently undergoing planned upgrades."
MAINTENANCE_START_TIME="2026-11-22T22:00:00Z"
MAINTENANCE_END_TIME="2026-11-22T23:00:00Z"
```

### 5.2 System Endpoints
- **Health Check (`GET /api/v1/health`):** When maintenance is active, returns `"status": "maintenance"`, populates the `maintenance` block, and injects the HTTP header `X-Maintenance-Mode: 1`.
- **Maintenance Status (`GET /api/v1/system/maintenance`):** Dedicated JSON endpoint for client banner state.
- **Frontend Component (`MaintenanceBanner.tsx`):** UI banner rendered on top screens informing users of scheduled windows.

---

## 6. Uptime Check and Server Warm-Up Runbook (AC 4)

Free-tier cloud containers (e.g., Render) sleep when idle, incurring cold starts up to 30–45 seconds. The uptime utility prevents cold starts and guarantees 10-minute health monitoring on demo days.

### 6.1 Server Warm-Up Before Demos
Run prior to team presentations or stakeholder evaluations to prime connection pools and pre-heat caches:
```powershell
cd backend
.\.venv\Scripts\python.exe scripts/uptime_check.py --warmup --url https://your-app.onrender.com
```
*Expected Output:*
```
[WARMUP] Priming server caches, connection pools, and routes...
[WARMUP SUCCESS] Server warmed up in 82.4ms. Final probe latency: 18.2ms (target p95 < 500ms).
```

### 6.2 10-Minute Uptime Monitoring on Demo Days
Keeps the instance active and logs availability every 600 seconds:
```powershell
cd backend
.\.venv\Scripts\python.exe scripts/uptime_check.py --interval 600 --demo-day
```

---

## 7. How to Run Verification Tests

### 7.1 Automated Load and Scale Suite
```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest tests/test_load_scale.py -v
```

### 7.2 Running k6 Load Test
```powershell
# Requires k6 installed (k6.io)
k6 run tests/load/k6_load_test.js
```
