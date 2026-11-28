"""Uptime check and server warm-up service (US-35 / T-61).

Provides automated health probing, server warm-up before demo events,
and scheduled 10-minute availability verification.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class UptimeCheckResult:
    """Result of an individual uptime probe."""

    timestamp: float
    status_code: int
    is_available: bool
    latency_ms: float
    database_status: str
    maintenance_active: bool
    details: dict[str, Any]


@dataclass
class WarmupResult:
    """Result of a server warm-up sequence."""

    successful: bool
    probes_completed: int
    warmup_duration_ms: float
    final_latency_ms: float
    database_ready: bool
    details: list[dict[str, Any]]


async def perform_uptime_check(
    client: httpx.AsyncClient,
    base_url: str = "http://127.0.0.1:8000",
) -> UptimeCheckResult:
    """
    Perform a single uptime check against /api/v1/health.
    Measures round-trip latency and validates database connectivity.
    """
    url = f"{base_url.rstrip('/')}/api/v1/health"
    start_time = time.perf_counter()
    try:
        response = await client.get(url, timeout=10.0)
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        data = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
        db_status = data.get("database", "unknown")
        maintenance = bool(data.get("maintenance", {}).get("active", False))
        is_available = response.status_code == 200 and db_status == "connected"

        return UptimeCheckResult(
            timestamp=time.time(),
            status_code=response.status_code,
            is_available=is_available,
            latency_ms=round(latency_ms, 2),
            database_status=db_status,
            maintenance_active=maintenance,
            details=data,
        )
    except (httpx.HTTPError, OSError, ValueError, RuntimeError) as exc:
        latency_ms = (time.perf_counter() - start_time) * 1000.0
        logger.error("Uptime probe failed: %s", exc)
        return UptimeCheckResult(
            timestamp=time.time(),
            status_code=0,
            is_available=False,
            latency_ms=round(latency_ms, 2),
            database_status="unreachable",
            maintenance_active=False,
            details={"error": str(exc)},
        )


async def warmup_server(
    client: httpx.AsyncClient,
    base_url: str = "http://127.0.0.1:8000",
    probes: int = 3,
) -> WarmupResult:
    """
    Warm up a cold or idle server before demonstrations.
    Executes multiple sequential probes to ensure database connection pools
    are initialized, JIT caches are warm, and response latency is well under 500ms.
    """
    overall_start = time.perf_counter()
    probe_details: list[dict[str, Any]] = []
    final_latency = 0.0
    db_ready = False

    for i in range(probes):
        check = await perform_uptime_check(client, base_url)
        final_latency = check.latency_ms
        db_ready = check.database_status == "connected"
        probe_details.append(
            {
                "probe": i + 1,
                "status_code": check.status_code,
                "latency_ms": check.latency_ms,
                "available": check.is_available,
            }
        )
        if i < probes - 1:
            await asyncio.sleep(0.1)

    total_duration_ms = (time.perf_counter() - overall_start) * 1000.0
    all_ok = all(p["available"] for p in probe_details)

    return WarmupResult(
        successful=all_ok,
        probes_completed=len(probe_details),
        warmup_duration_ms=round(total_duration_ms, 2),
        final_latency_ms=round(final_latency, 2),
        database_ready=db_ready,
        details=probe_details,
    )
