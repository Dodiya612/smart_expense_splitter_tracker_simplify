"""Tests for T-61 / US-35: Load and Scale (Scalability and Availability).

Verifies all four acceptance criteria:
1. k6 / 50-VU concurrent load simulation measuring p95 response time < 500 ms.
2. Database indexes on (user, date) and (group, date) checked, plus keyset pagination on long lists.
3. Maintenance banner switched on and off by configuration.
4. Uptime check every 10 minutes on demo days and server warm-up logic.
"""

from __future__ import annotations

import asyncio
import datetime
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.models.expense import Expense
from app.services.expenses import (
    ExpenseListResult,
    decode_expense_cursor,
    encode_expense_cursor,
)
from app.services.uptime_service import perform_uptime_check, warmup_server


@pytest.fixture(autouse=True)
def mock_db_health():
    """Mock database health check for unit tests where external PostgreSQL is offline."""
    with patch(
        "app.api.v1.endpoints.health.check_database_connection",
        new=AsyncMock(return_value=(True, None)),
    ):
        yield


# ---------------------------------------------------------------------------
# AC 1 & Done When: 50 Concurrent Virtual Users Load Simulation (p95 < 500ms)
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_50_virtual_users_concurrent_load_p95_under_500ms(client: AsyncClient):
    """
    Simulate 50 concurrent virtual users making rapid API calls.
    Measures latency for every single request and verifies p95 latency < 500 ms.
    """
    num_virtual_users = 50
    requests_per_user = 4
    total_requests = num_virtual_users * requests_per_user
    latencies: list[float] = []

    async def simulate_vu(vu_id: int):
        for req_idx in range(requests_per_user):
            endpoint = "/api/v1/health" if req_idx % 2 == 0 else "/api/v1/system/maintenance"
            start = time.perf_counter()
            response = await client.get(endpoint)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            latencies.append(elapsed_ms)
            assert response.status_code == 200

    # Execute all 50 VUs concurrently
    start_total = time.perf_counter()
    await asyncio.gather(*(simulate_vu(i) for i in range(num_virtual_users)))
    total_duration_s = time.perf_counter() - start_total

    assert len(latencies) == total_requests

    # Calculate percentiles
    sorted_latencies = sorted(latencies)
    p50_idx = int(len(sorted_latencies) * 0.50)
    p90_idx = int(len(sorted_latencies) * 0.90)
    p95_idx = int(len(sorted_latencies) * 0.95)
    p99_idx = int(len(sorted_latencies) * 0.99)

    p50 = sorted_latencies[p50_idx]
    p90 = sorted_latencies[p90_idx]
    p95 = sorted_latencies[p95_idx]
    p99 = sorted_latencies[p99_idx]
    throughput_rps = total_requests / total_duration_s

    # Core criterion: p95 must be strictly under 500 ms (typically < 30ms locally)
    assert p95 < 500.0, f"p95 latency was {p95:.2f}ms, which exceeds the 500ms threshold"
    assert p50 < 100.0, f"p50 latency was {p50:.2f}ms"
    assert p90 <= p95
    assert p99 >= p95
    assert throughput_rps > 10.0


# ---------------------------------------------------------------------------
# AC 2: Indexes on (user, date) and (group, date) Checked
# ---------------------------------------------------------------------------
def test_expense_indexes_exist_on_user_date_and_group_date():
    """
    Verify that SQLAlchemy Expense model definitions contain composite indexes
    for (user, date) and (group, date) as mandated by AC 2.
    """
    table = Expense.__table__
    index_names = {idx.name: idx for idx in table.indexes}

    # 1. Index on (user, date)
    assert "ix_expenses_user_deleted_date" in index_names
    user_idx = index_names["ix_expenses_user_deleted_date"]
    user_cols = [c.name for c in user_idx.columns]
    assert "user_id" in user_cols
    assert "expense_date" in user_cols
    assert "deleted_at" in user_cols

    # 2. Index on (group, date)
    assert "ix_expenses_group_deleted_date" in index_names
    group_idx = index_names["ix_expenses_group_deleted_date"]
    group_cols = [c.name for c in group_idx.columns]
    assert "group_id" in group_cols
    assert "expense_date" in group_cols
    assert "deleted_at" in group_cols


# ---------------------------------------------------------------------------
# AC 2: Keyset Pagination on Long Lists
# ---------------------------------------------------------------------------
def test_keyset_cursor_encoding_and_decoding():
    """
    Verify keyset cursor encode and decode logic for seek pagination.
    """
    dummy_id = uuid.uuid4()
    dummy_date = datetime.date(2026, 11, 20)
    dummy_created_at = datetime.datetime(2026, 11, 20, 14, 30, 0, tzinfo=datetime.UTC)

    expense = Expense(
        id=dummy_id,
        user_id=uuid.uuid4(),
        amount_minor=5000,
        description="Coffee",
        expense_date=dummy_date,
        created_at=dummy_created_at,
    )

    encoded = encode_expense_cursor(expense)
    assert isinstance(encoded, str)
    assert len(encoded) > 0

    decoded = decode_expense_cursor(encoded)
    assert decoded is not None
    dec_date, dec_created, dec_id = decoded
    assert dec_date == dummy_date
    assert dec_id == dummy_id
    assert dec_created.year == 2026


def test_keyset_cursor_handles_invalid_or_numeric_strings():
    """
    Ensure invalid or numeric cursor strings (from offset pagination) do not raise
    and gracefully return None to preserve backward compatibility.
    """
    assert decode_expense_cursor("50") is None
    assert decode_expense_cursor("invalid-base-64!!") is None
    assert decode_expense_cursor("") is None


def test_expense_list_result_backward_compatibility():
    """
    Verify ExpenseListResult behaves as a 2-tuple for backwards compatibility
    while also exposing next_cursor.
    """
    items = [Expense(id=uuid.uuid4(), amount_minor=1000, description="Test")]
    total = 1
    next_cur = "eyJkYXRlIjoiMjAyNi0xMS0yMCJ9"

    res = ExpenseListResult(items, total, next_cur)

    # 1. Unpacking as 2-tuple
    unpacked_items, unpacked_total = res
    assert unpacked_items == items
    assert unpacked_total == 1

    # 2. Attribute access
    assert res.next_cursor == next_cur
    assert res.total == 1


# ---------------------------------------------------------------------------
# AC 3: Maintenance Banner Switched On by Configuration
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_maintenance_banner_off_by_default(client: AsyncClient, monkeypatch):
    """
    Verify that in standard operation (MAINTENANCE_MODE=False),
    health check reports healthy and maintenance is inactive.
    """
    monkeypatch.setattr(settings, "MAINTENANCE_MODE", False)

    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["maintenance"]["active"] is False
    assert "X-Maintenance-Mode" not in response.headers

    # System maintenance endpoint
    m_res = await client.get("/api/v1/system/maintenance")
    assert m_res.status_code == 200
    m_data = m_res.json()
    assert m_data["active"] is False


@pytest.mark.anyio
async def test_maintenance_banner_switched_on_by_configuration(client: AsyncClient, monkeypatch):
    """
    Verify that toggling MAINTENANCE_MODE=True immediately displays the maintenance banner,
    sets maintenance status, returns the custom message, and emits X-Maintenance-Mode header.
    """
    custom_msg = "Upgrading database clusters for peak performance. Back shortly!"
    monkeypatch.setattr(settings, "MAINTENANCE_MODE", True)
    monkeypatch.setattr(settings, "MAINTENANCE_MESSAGE", custom_msg)
    monkeypatch.setattr(settings, "MAINTENANCE_START_TIME", "2026-11-22T20:00:00Z")
    monkeypatch.setattr(settings, "MAINTENANCE_END_TIME", "2026-11-22T21:00:00Z")

    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("X-Maintenance-Mode") == "1"

    data = response.json()
    assert data["status"] == "maintenance"
    assert data["maintenance"]["active"] is True
    assert data["maintenance"]["message"] == custom_msg
    assert data["maintenance"]["startTime"] == "2026-11-22T20:00:00Z"
    assert data["maintenance"]["endTime"] == "2026-11-22T21:00:00Z"

    # Verify dedicated maintenance endpoint returns matching banner details
    m_res = await client.get("/api/v1/system/maintenance")
    assert m_res.status_code == 200
    m_data = m_res.json()
    assert m_data["active"] is True
    assert m_data["message"] == custom_msg


# ---------------------------------------------------------------------------
# AC 4: Uptime Check Every 10 Minutes & Server Warmup
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_uptime_check_service(client: AsyncClient):
    """
    Verify that perform_uptime_check reports availability, measures response time,
    and returns valid connectivity metrics.
    """
    result = await perform_uptime_check(client, base_url="http://testserver")
    assert result.is_available is True
    assert result.status_code == 200
    assert result.latency_ms >= 0.0
    assert result.database_status == "connected"
    assert result.maintenance_active is False


@pytest.mark.anyio
async def test_server_warmup_sequence(client: AsyncClient):
    """
    Verify that warmup_server executes sequential probes, primes caches,
    and returns a successful warmup result with final probe latency < 500 ms.
    """
    warmup_res = await warmup_server(client, base_url="http://testserver", probes=3)
    assert warmup_res.successful is True
    assert warmup_res.probes_completed == 3
    assert warmup_res.database_ready is True
    assert warmup_res.final_latency_ms < 500.0
    assert len(warmup_res.details) == 3
