"""Demo Day Uptime Monitor and Server Warm-Up CLI (US-35 / T-61).

Usage:
    python scripts/uptime_check.py --warmup
    python scripts/uptime_check.py --once
    python scripts/uptime_check.py --interval 600 --demo-day
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import os
import sys
from pathlib import Path

# Ensure backend root is on Python sys.path
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import httpx

from app.services.uptime_service import perform_uptime_check, warmup_server


async def run_cli(args: argparse.Namespace) -> int:
    base_url = args.url or os.getenv("APP_BASE_URL", "http://127.0.0.1:8000")
    print(f"[COINSCIOUS UPTIME MONITOR] Target: {base_url}")

    async with httpx.AsyncClient() as client:
        if args.warmup:
            print("[WARMUP] Priming server caches, connection pools, and routes...")
            warmup_res = await warmup_server(client, base_url=base_url, probes=args.warmup_probes)
            if warmup_res.successful:
                print(
                    f"[WARMUP SUCCESS] Server warmed up in {warmup_res.warmup_duration_ms:.1f}ms. "
                    f"Final probe latency: {warmup_res.final_latency_ms:.1f}ms (target p95 < 500ms)."
                )
                return 0
            else:
                print(f"[WARMUP FAILED] One or more probes failed: {warmup_res.details}")
                return 1

        if args.once:
            result = await perform_uptime_check(client, base_url=base_url)
            status_str = "AVAILABLE" if result.is_available else "UNAVAILABLE"
            print(
                f"[{datetime.datetime.now().isoformat()}] [{status_str}] "
                f"HTTP {result.status_code} | Latency: {result.latency_ms:.1f}ms | DB: {result.database_status}"
            )
            return 0 if result.is_available else 1

        # Periodic monitor (Default: every 600 seconds / 10 minutes on demo days)
        interval = args.interval
        print(f"[MONITOR STARTED] Probing /health every {interval}s (10-minute demo schedule). Press Ctrl+C to exit.")
        iteration = 0
        try:
            while True:
                iteration += 1
                result = await perform_uptime_check(client, base_url=base_url)
                status_str = "HEALTHY" if result.is_available else "DEGRADED/DOWN"
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(
                    f"[{now_str}] Check #{iteration}: {status_str} "
                    f"(HTTP {result.status_code}, {result.latency_ms:.1f}ms, DB: {result.database_status})"
                )
                if args.max_checks and iteration >= args.max_checks:
                    break
                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            print("\n[MONITOR STOPPED] Uptime check stopped by user.")
            return 0

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Coinscious Uptime and Warmup Monitor")
    parser.add_argument("--url", type=str, default=None, help="Base API URL")
    parser.add_argument("--warmup", action="store_true", help="Warm up server before demo")
    parser.add_argument("--warmup-probes", type=int, default=3, help="Number of warmup probes")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=600, help="Check interval in seconds (default: 600s / 10 min)")
    parser.add_argument("--demo-day", action="store_true", help="Enable demo day monitoring mode")
    parser.add_argument("--max-checks", type=int, default=None, help="Maximum number of checks before exiting")

    args = parser.parse_args()
    code = asyncio.run(run_cli(args))
    sys.exit(code)


if __name__ == "__main__":
    main()
