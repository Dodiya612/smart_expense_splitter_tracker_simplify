"""Receipt Domain Service (US-16).

Handles:
- Receipt scanning, quota checks, image processing, storage, and extraction
- Secure access authorization (owner or group expense members; 404 for others)
- Expense linking and cascade cleanup of storage blobs on expense deletion
- Purging unlinked receipts older than 24 hours
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.ai.quota import get_quota_service
from app.ai.receipt import ExtractedReceiptData, extract_receipt_data
from app.core.errors import (
    image_too_large_error,
    invalid_image_error,
    not_found_error,
    unsupported_media_type_error,
)
from app.models.expense import Expense
from app.models.group import GroupMember
from app.models.receipt import Receipt
from app.models.user import User
from app.services.receipt_images import (
    ImageTooLargeError,
    InvalidImageError,
    ReceiptImageError,
    UnsupportedMediaTypeError,
    process_receipt_image,
)
from app.services.receipt_storage import (
    DatabaseReceiptStorage,
    ReceiptStorage,
    generate_key,
    get_receipt_storage,
)

logger = logging.getLogger(__name__)


async def scan_and_store_receipt(
    db: AsyncSession,
    current_user: User,
    raw_bytes: bytes,
    storage: ReceiptStorage | None = None,
) -> tuple[Receipt, ExtractedReceiptData]:
    """Execute receipt scanning pipeline: auth, quota reservation, processing, storage, and extraction."""
    quota_svc = get_quota_service()

    # 1. Quota reservation for "receipt" feature
    async with quota_svc.reserve(
        user_id=current_user.id,
        feature="receipt",
        db=db,
        raise_on_exceeded=True,
    ) as reservation:
        # 2. Process image through pipeline
        try:
            processed = process_receipt_image(raw_bytes)
        except UnsupportedMediaTypeError as exc:
            raise unsupported_media_type_error(exc.message) from exc
        except ImageTooLargeError as exc:
            raise image_too_large_error(exc.message) from exc
        except (InvalidImageError, ReceiptImageError) as exc:
            raise invalid_image_error(exc.message) from exc

        # 3. Generate unguessable random storage key
        storage_key = generate_key()

        # 4. Determine storage backend
        store = storage or get_receipt_storage(db=db)
        is_db_storage = isinstance(store, DatabaseReceiptStorage)

        # 5. Upload blob to external storage first (if not using DB BYTEA storage)
        uploaded_to_storage = False
        if not is_db_storage:
            try:
                await store.put(storage_key, processed.data, processed.content_type)
                uploaded_to_storage = True
            except Exception as exc:
                logger.warning("Failed to store receipt in external storage: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={"code": "STORAGE_ERROR", "message": "Failed to store receipt image."},
                ) from exc

        # 6. Create and persist DB record
        receipt = Receipt(
            user_id=current_user.id,
            storage_key=storage_key,
            image_data=processed.data if is_db_storage else None,
            content_type=processed.content_type,
            file_size=len(processed.data),
        )
        db.add(receipt)

        try:
            await db.commit()
            await db.refresh(receipt)
        except Exception:
            await db.rollback()
            # Clean up uploaded storage blob on DB commit failure to prevent orphaned blobs
            if uploaded_to_storage:
                try:
                    await store.delete(storage_key)
                except Exception as del_exc:  # noqa: BLE001
                    logger.warning("Failed to clean up storage blob %s on DB commit failure: %s", storage_key, del_exc)
            raise

        # 7. Call extraction stub (Parthiv's interface)
        extracted = await extract_receipt_data(processed.data)

        # 8. Finalize quota reservation
        await reservation.finalize(
            status="success",
            latency_ms=10.0,
            db=db,
        )

        return receipt, extracted


async def get_receipt_image(
    db: AsyncSession,
    receipt_id: uuid.UUID,
    current_user: User,
    storage: ReceiptStorage | None = None,
) -> tuple[bytes, str]:
    """Retrieve receipt image bytes with strict owner-only authorization (returns 404 for unauthorized users)."""
    stmt = (
        select(Receipt)
        .options(undefer(Receipt.image_data))
        .where(Receipt.id == receipt_id)
    )
    result = await db.execute(stmt)
    receipt = result.scalar_one_or_none()

    if receipt is None or receipt.user_id != current_user.id:
        # Return 404 rather than 403 to prevent leaking record existence
        raise not_found_error("Receipt not found.")

    # Retrieve image bytes
    if receipt.image_data is not None:
        return receipt.image_data, receipt.content_type

    store = storage or get_receipt_storage(db=db)
    blob = await store.get(receipt.storage_key)
    if not blob:
        raise not_found_error("Receipt image content not found.")

    return blob, receipt.content_type


async def link_receipt_to_expense(
    db: AsyncSession,
    receipt_id: uuid.UUID,
    expense_id: uuid.UUID,
    current_user_id: uuid.UUID,
) -> Receipt:
    """Verify ownership, validate target expense, prevent double-linking, and link receipt to expense."""
    stmt = select(Receipt).where(Receipt.id == receipt_id)
    result = await db.execute(stmt)
    receipt = result.scalar_one_or_none()

    if receipt is None or receipt.user_id != current_user_id:
        raise not_found_error("Receipt not found.")

    # Verify target expense exists and caller is authorized to link to it
    exp_stmt = select(Expense).where(Expense.id == expense_id)
    exp_res = await db.execute(exp_stmt)
    expense = exp_res.scalar_one_or_none()

    if expense is None:
        raise not_found_error("Expense not found.")

    is_authorized = (expense.user_id == current_user_id)
    if not is_authorized and expense.group_id is not None:
        member_stmt = select(GroupMember).where(
            GroupMember.group_id == expense.group_id,
            GroupMember.user_id == current_user_id,
            GroupMember.status == "active",
        )
        member_res = await db.execute(member_stmt)
        if member_res.scalar_one_or_none() is not None:
            is_authorized = True

    if not is_authorized:
        raise not_found_error("Expense not found.")

    if receipt.expense_id is not None and receipt.expense_id != expense_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "CONFLICT", "message": "Receipt is already linked to another expense."},
        )

    receipt.expense_id = expense_id
    db.add(receipt)
    return receipt


async def delete_receipt_for_expense(
    db: AsyncSession,
    expense_id: uuid.UUID,
    storage: ReceiptStorage | None = None,
    commit: bool = True,
) -> None:
    """Delete receipt database row and stored object when linked expense is permanently deleted.
    Ensures DB deletion commits before deleting the external storage object.
    """
    stmt = select(Receipt).where(Receipt.expense_id == expense_id)
    result = await db.execute(stmt)
    receipt = result.scalar_one_or_none()

    if receipt is None:
        # Also check if expense has receipt_id pointing to a receipt
        exp_stmt = select(Expense).where(Expense.id == expense_id)
        exp_res = await db.execute(exp_stmt)
        exp = exp_res.scalar_one_or_none()
        if exp and hasattr(exp, "receipt_id") and isinstance(exp.receipt_id, uuid.UUID):
            r_stmt = select(Receipt).where(Receipt.id == exp.receipt_id)
            r_res = await db.execute(r_stmt)
            receipt = r_res.scalar_one_or_none()

    if receipt is None or not isinstance(receipt, Receipt):
        return

    storage_key = receipt.storage_key
    is_db = receipt.image_data is not None

    await db.delete(receipt)
    if commit:
        await db.commit()

    # External storage blob is ONLY deleted after DB deletion commits
    if not is_db and storage_key:
        store = storage or get_receipt_storage(db=db)
        try:
            await store.delete(storage_key)
        except Exception as exc:  # noqa: BLE001
            # Storage deletion failure must not throw unhandled error to user
            logger.warning("Failed to delete receipt blob from storage: %s", exc)


async def purge_unlinked_receipts(
    db: AsyncSession,
    storage: ReceiptStorage | None = None,
    older_than_hours: int = 24,
) -> int:
    """Purge unlinked receipts older than 24 hours, committing DB deletes before removing external storage blobs."""
    cutoff = datetime.now(UTC) - timedelta(hours=older_than_hours)
    stmt = select(Receipt).where(
        Receipt.expense_id.is_(None),
        Receipt.created_at <= cutoff,
    )
    result = await db.execute(stmt)
    unlinked_receipts = result.scalars().all()

    store = storage or get_receipt_storage(db=db)
    purged_count = 0
    external_keys_to_delete: list[str] = []

    for r in unlinked_receipts:
        if r.storage_key and r.image_data is None:
            external_keys_to_delete.append(r.storage_key)
        await db.delete(r)
        purged_count += 1

    if purged_count > 0:
        await db.commit()
        for key in external_keys_to_delete:
            try:
                await store.delete(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error deleting blob %s for unlinked receipt during purge: %s", key, exc)

    return purged_count
