"""Receipt Storage Service Abstraction (US-16).

Provides an abstract ReceiptStorage protocol with:
- Random unguessable key generation: receipts/{uuid4().hex}.jpg
- DatabaseReceiptStorage: stores bytes in the receipts table image_data column (default)
- SupabaseReceiptStorage: stores objects in a private Supabase Storage bucket via httpx
- InMemoryReceiptStorage: in-memory store for isolated unit/API testing
"""

from __future__ import annotations

import logging
import uuid
from typing import Protocol

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.receipt import Receipt

logger = logging.getLogger(__name__)


def generate_key() -> str:
    """Generate a random, unguessable storage key containing zero PII or timestamps."""
    return f"receipts/{uuid.uuid4().hex}.jpg"


class ReceiptStorage(Protocol):
    """Protocol defining the storage contract for receipt image blobs."""

    async def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        """Store image bytes under the given unguessable key."""
        ...

    async def get(self, key: str) -> bytes | None:
        """Retrieve stored image bytes by key, returning None if not found."""
        ...

    async def delete(self, key: str) -> None:
        """Delete stored image bytes by key."""
        ...


class InMemoryReceiptStorage:
    """In-memory receipt storage for tests and offline local execution."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        self._store[key] = (data, content_type)

    async def get(self, key: str) -> bytes | None:
        entry = self._store.get(key)
        return entry[0] if entry else None

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


class DatabaseReceiptStorage:
    """Stores and retrieves receipt bytes directly in the PostgreSQL receipts BYTEA column."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        self.db = db

    async def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        """Store image bytes into the database record matching storage_key."""
        if self.db is None:
            logger.warning("No database session provided to DatabaseReceiptStorage.put")
            return

        stmt = (
            update(Receipt)
            .where(Receipt.storage_key == key)
            .values(image_data=data, content_type=content_type, file_size=len(data))
        )
        try:
            await self.db.execute(stmt)
            await self.db.commit()
        except SQLAlchemyError as exc:
            logger.warning("Failed to store receipt image data in database: %s", exc)
            raise

    async def get(self, key: str) -> bytes | None:
        """Retrieve image bytes from the database record matching storage_key."""
        if self.db is None:
            from app.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as session:
                stmt = select(Receipt.image_data).where(Receipt.storage_key == key)
                result = await session.execute(stmt)
                return result.scalar_one_or_none()

        stmt = select(Receipt.image_data).where(Receipt.storage_key == key)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete(self, key: str) -> None:
        """Clear image bytes from the database record."""
        if self.db is None:
            return

        stmt = update(Receipt).where(Receipt.storage_key == key).values(image_data=None)
        try:
            await self.db.execute(stmt)
            await self.db.commit()
        except SQLAlchemyError as exc:
            logger.warning("Failed to clear receipt image data from database: %s", exc)


class SupabaseReceiptStorage:
    """Stores receipt image blobs in a private Supabase Storage bucket via secure REST API.

    Uses server-side SUPABASE_SERVICE_KEY only. Generates zero public URLs.
    """

    def __init__(
        self,
        base_url: str | None = None,
        service_key: str | None = None,
        bucket: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or settings.SUPABASE_URL or "").rstrip("/")
        self.service_key = service_key or settings.SUPABASE_SERVICE_KEY or ""
        self.bucket = bucket or settings.RECEIPTS_BUCKET or "receipts"
        self._custom_client = http_client

    def _headers(self, content_type: str | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.service_key}",
            "apiKey": self.service_key,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    async def put(self, key: str, data: bytes, content_type: str = "image/jpeg") -> None:
        if not self.base_url or not self.service_key:
            raise RuntimeError("Supabase storage is unconfigured: SUPABASE_URL or SUPABASE_SERVICE_KEY is missing.")

        clean_key = key.removeprefix(f"{self.bucket}/")
        url = f"{self.base_url}/storage/v1/object/{self.bucket}/{clean_key}"

        client = self._custom_client
        if client is not None:
            res = await client.post(url, content=data, headers=self._headers(content_type))
            if res.status_code not in (200, 201):
                res = await client.put(url, content=data, headers=self._headers(content_type))
        else:
            async with httpx.AsyncClient(timeout=10.0) as default_client:
                res = await default_client.post(url, content=data, headers=self._headers(content_type))
                if res.status_code not in (200, 201):
                    res = await default_client.put(url, content=data, headers=self._headers(content_type))

        if res.status_code not in (200, 201):
            logger.warning("Supabase storage upload failed with status %s: %s", res.status_code, res.text[:200])
            raise RuntimeError(f"Failed to store receipt in private Supabase bucket: HTTP {res.status_code}")

    async def get(self, key: str) -> bytes | None:
        if not self.base_url or not self.service_key:
            logger.warning("Supabase storage get called but service is unconfigured.")
            return None

        clean_key = key.removeprefix(f"{self.bucket}/")
        # Private authenticated download endpoint
        url = f"{self.base_url}/storage/v1/object/authenticated/{self.bucket}/{clean_key}"

        client = self._custom_client
        if client is not None:
            res = await client.get(url, headers=self._headers())
        else:
            async with httpx.AsyncClient(timeout=10.0) as default_client:
                res = await default_client.get(url, headers=self._headers())

        if res.status_code == 200:
            return res.content
        elif res.status_code == 404:
            return None
        else:
            logger.warning("Supabase storage retrieval failed with status %s: %s", res.status_code, res.text[:200])
            return None

    async def delete(self, key: str) -> None:
        if not self.base_url or not self.service_key:
            return

        clean_key = key.removeprefix(f"{self.bucket}/")
        url = f"{self.base_url}/storage/v1/object/{self.bucket}/{clean_key}"

        try:
            client = self._custom_client
            if client is not None:
                await client.delete(url, headers=self._headers())
            else:
                async with httpx.AsyncClient(timeout=10.0) as default_client:
                    await default_client.delete(url, headers=self._headers())
        except Exception as exc:  # noqa: BLE001
            # Storage delete failure must not raise exception to user
            logger.warning("Failed to delete receipt object from Supabase bucket: %s", exc)


# Singleton fake storage for test overrides
_TEST_STORAGE: InMemoryReceiptStorage | None = None


def get_receipt_storage(db: AsyncSession | None = None) -> ReceiptStorage:
    """Factory retrieving the configured ReceiptStorage implementation."""
    if _TEST_STORAGE is not None:
        return _TEST_STORAGE

    storage_mode = (settings.RECEIPT_STORAGE or "db").lower()
    if storage_mode == "supabase":
        return SupabaseReceiptStorage()
    return DatabaseReceiptStorage(db=db)


def set_test_receipt_storage(storage: InMemoryReceiptStorage | None) -> None:
    """Override storage singleton with an in-memory test store."""
    global _TEST_STORAGE
    _TEST_STORAGE = storage
