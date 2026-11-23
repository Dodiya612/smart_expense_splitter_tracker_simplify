"""Bill image clean-up (US-16 / T-54): "the bill image is deleted along with the expense".

Deleting an expense is a soft delete with a short Undo (T-20), so the image cannot go at
that moment. This background task (started like the recurring scheduler, T-44) runs at
startup and then every RECEIPT_CLEANUP_INTERVAL_SECONDS and:

1. deletes the bill image of every expense that has been deleted for longer than
   RECEIPT_RETENTION_HOURS (the expense row stays soft-deleted, its receipt link cleared);
2. deletes scans that were never confirmed as an expense after the same time
   (``purge_unlinked_receipts`` from T-46).

Database rows are committed first; stored files are removed only after that commit, so a
failure never leaves a row pointing at a missing file. A failing run is logged and the
next run retries.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.expense import Expense
from app.models.receipt import Receipt
from app.services.receipt_service import purge_unlinked_receipts
from app.services.receipt_storage import (
    DatabaseReceiptStorage,
    ReceiptStorage,
    get_receipt_storage,
)

logger = logging.getLogger(__name__)


@dataclass
class CleanupStats:
    deleted_expense_receipts: int = 0
    unconfirmed_scans: int = 0


async def purge_deleted_expense_receipts(
    db: AsyncSession,
    storage: ReceiptStorage | None = None,
    older_than_hours: int = 24,
    now: datetime | None = None,
) -> int:
    """Delete the bill image of expenses soft-deleted more than ``older_than_hours`` ago."""
    cutoff = (now or datetime.now(UTC)) - timedelta(hours=older_than_hours)
    stmt = (
        select(Receipt, Expense)
        .join(Expense, or_(Receipt.expense_id == Expense.id, Expense.receipt_id == Receipt.id))
        .where(Expense.deleted_at.is_not(None), Expense.deleted_at <= cutoff)
    )
    rows = (await db.execute(stmt)).all()

    # Images kept in the database go with the row; anything else is a file to remove after the commit.
    # (Checked by storage type: reading the deferred image column here would load every image.)
    store = storage or get_receipt_storage(db=db)
    external = not isinstance(store, DatabaseReceiptStorage)

    seen: set[object] = set()
    external_keys: list[str] = []
    for receipt, expense in rows:
        expense.receipt_id = None
        if receipt.id in seen:
            continue
        seen.add(receipt.id)
        if external and receipt.storage_key:
            external_keys.append(receipt.storage_key)
        await db.delete(receipt)

    if not seen:
        return 0
    await db.commit()

    for key in external_keys:
        try:
            await store.delete(key)
        except Exception as exc:  # noqa: BLE001 - a leftover file is retried by nobody, but never breaks the run
            logger.warning("Could not delete bill image %s of a deleted expense (%s)", key, type(exc).__name__)
    return len(seen)


async def run_cleanup(now: datetime | None = None) -> CleanupStats:
    """One clean-up run in its own session."""
    hours = settings.RECEIPT_RETENTION_HOURS
    stats = CleanupStats()
    async with AsyncSessionLocal() as db:
        stats.deleted_expense_receipts = await purge_deleted_expense_receipts(db, older_than_hours=hours, now=now)
    async with AsyncSessionLocal() as db:
        stats.unconfirmed_scans = await purge_unlinked_receipts(db, older_than_hours=hours)
    return stats


async def cleanup_loop(interval_seconds: float) -> None:
    """Run at startup, then every ``interval_seconds``. Never stops on errors."""
    while True:
        try:
            stats = await run_cleanup()
            if stats.deleted_expense_receipts or stats.unconfirmed_scans:
                logger.info(
                    "Bill image clean-up: deleted-expense images=%d unconfirmed scans=%d",
                    stats.deleted_expense_receipts,
                    stats.unconfirmed_scans,
                )
        except Exception as exc:  # noqa: BLE001 - keep the loop alive; the next run retries
            logger.error("Bill image clean-up failed (%s); retrying at the next interval", type(exc).__name__)
        await asyncio.sleep(interval_seconds)


def start_cleanup(interval_seconds: float | None = None) -> asyncio.Task[None]:
    interval = interval_seconds if interval_seconds is not None else settings.RECEIPT_CLEANUP_INTERVAL_SECONDS
    return asyncio.create_task(cleanup_loop(interval), name="bill-image-cleanup")


async def stop_cleanup(task: asyncio.Task[None] | None) -> None:
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
