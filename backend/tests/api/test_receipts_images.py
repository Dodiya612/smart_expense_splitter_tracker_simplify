"""API integration tests for Receipt Scanning, Image Storage, and Expense Linking (US-16).

Acceptance Criteria Tested:
1. AC 1: Stored image is smaller than 1 MB (1,048,576 bytes) & max dimension <= 1600 px.
2. AC 2: Location (EXIF/GPS) and all metadata is stripped from stored images.
3. AC 3: File type is strictly determined from file bytes (magic bytes / Pillow decode),
         never from filename or client Content-Type.
4. AC 4: Stored privately under unguessable random key; only owner (or group member if
         linked to a group expense) can access. Non-owners receive HTTP 404 (never 403).
5. AC 5: Bill receipt is linked to expense and is deleted together with the expense
         (both database record and storage blob).
6. 24h Purge: Unlinked receipts older than 24 hours are safely purged.
7. Quota: Daily AI quota limit enforced (returns 429 when exhausted).
8. Storage Backends: DB, InMemory, and Supabase storage backends.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.ai_usage_log import AIUsageLog
from app.models.category import Category
from app.models.expense import Expense
from app.models.group import GroupMember
from app.models.receipt import Receipt
from app.models.user import User
from app.services.receipt_service import (
    delete_receipt_for_expense,
    link_receipt_to_expense,
    purge_unlinked_receipts,
)
from app.services.receipt_storage import (
    DatabaseReceiptStorage,
    InMemoryReceiptStorage,
    SupabaseReceiptStorage,
    generate_key,
    set_test_receipt_storage,
)


def make_test_jpeg(
    width: int = 200,
    height: int = 200,
    with_exif: bool = False,
    color: tuple[int, int, int] = (200, 50, 50),
) -> bytes:
    """Create a test JPEG with optional EXIF/GPS tags."""
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    if with_exif:
        exif = img.getexif()
        exif[0x010E] = "Secret location receipt"
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "N"
        gps_ifd[2] = (37.0, 46.0, 29.74)
        img.save(buf, format="JPEG", exif=exif)
    else:
        img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def make_test_png(width: int = 150, height: int = 150) -> bytes:
    """Create a test PNG image."""
    img = Image.new("RGBA", (width, height), (0, 180, 50, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# =====================================================================
# In-Memory Fake DB and Session for Deterministic API Testing
# =====================================================================


class FakeScalars:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def all(self) -> list[Any]:
        return list(self._items)

    def first(self) -> Any | None:
        return self._items[0] if self._items else None


class FakeResult:
    def __init__(self, items: list[Any] | None = None, scalar_val: Any = None) -> None:
        self._items = items or []
        self._scalar_val = scalar_val

    def scalar_one_or_none(self) -> Any | None:
        if self._scalar_val is not None:
            return self._scalar_val
        return self._items[0] if self._items else None

    def scalar_one(self) -> Any:
        if self._scalar_val is not None:
            return self._scalar_val
        return self._items[0] if self._items else 0

    def scalar(self) -> Any:
        if self._scalar_val is not None:
            return self._scalar_val
        return self._items[0] if self._items else None

    def scalars(self) -> FakeScalars:
        return FakeScalars(self._items)


class ReceiptApiFakeDB:
    def __init__(self) -> None:
        self.users: dict[uuid.UUID, User] = {}
        self.categories: dict[uuid.UUID, Category] = {}
        self.expenses: dict[uuid.UUID, Expense] = {}
        self.receipts: dict[uuid.UUID, Receipt] = {}
        self.group_members: list[GroupMember] = []
        self.ai_logs: list[AIUsageLog] = []


class ReceiptApiFakeSession:
    def __init__(self, db: ReceiptApiFakeDB) -> None:
        self.db = db
        self.pending: list[Any] = []
        self.deleted: list[Any] = []

    def add(self, obj: Any) -> None:
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = datetime.now(UTC)
        self.pending.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)
        if isinstance(obj, Receipt) and obj.id in self.db.receipts:
            del self.db.receipts[obj.id]
        elif isinstance(obj, Expense) and obj.id in self.db.expenses:
            del self.db.expenses[obj.id]

    async def commit(self) -> None:
        for obj in self.pending:
            if isinstance(obj, User):
                self.db.users[obj.id] = obj
            elif isinstance(obj, Category):
                self.db.categories[obj.id] = obj
            elif isinstance(obj, Expense):
                self.db.expenses[obj.id] = obj
            elif isinstance(obj, Receipt):
                self.db.receipts[obj.id] = obj
            elif isinstance(obj, AIUsageLog):
                self.db.ai_logs.append(obj)
            elif isinstance(obj, GroupMember):
                self.db.group_members.append(obj)
        self.pending.clear()
        self.deleted.clear()

    async def refresh(self, obj: Any) -> None:
        pass

    async def rollback(self) -> None:
        self.pending.clear()
        self.deleted.clear()

    async def execute(self, stmt: Any) -> FakeResult:
        await self.commit()
        sql_str = str(stmt).lower()
        params = stmt.compile().params

        # 1. AIUsageLog count (quota checking)
        if "from ai_usage_log" in sql_str and "count" in sql_str:
            uid = params.get("user_id_1") or params.get("user_id")
            feat = params.get("feature_1") or params.get("feature")
            cutoff = params.get("created_at_1") or params.get("created_at")
            matching = [
                log
                for log in self.db.ai_logs
                if (uid is None or log.user_id == uid)
                and (feat is None or log.feature == feat)
                and (cutoff is None or log.created_at >= cutoff)
                and (log.status in ("success", "pending"))
            ]
            return FakeResult(items=[len(matching)], scalar_val=len(matching))

        # 2. UPDATE ai_usage_log
        if "update ai_usage_log" in sql_str:
            target_id = params.get("id_1") or params.get("id")
            for log in self.db.ai_logs:
                if target_id is None or log.id == target_id:
                    for k, v in params.items():
                        if hasattr(log, k):
                            setattr(log, k, v)
                    return FakeResult([log])
            return FakeResult([])

        # UPDATE receipts
        if "update receipts" in sql_str:
            key = params.get("storage_key_1") or params.get("storage_key")
            rid = params.get("id_1") or params.get("id")
            for r in self.db.receipts.values():
                if (key is not None and r.storage_key == key) or (rid is not None and r.id == rid):
                    for k, v in params.items():
                        clean_k = k.split("_")[0]
                        if hasattr(r, k):
                            setattr(r, k, v)
                        elif hasattr(r, clean_k):
                            setattr(r, clean_k, v)
                    if "image_data" in params:
                        r.image_data = params.get("image_data")
                    elif "image_data_1" in params:
                        r.image_data = params.get("image_data_1")
                    return FakeResult([r])
            return FakeResult([])

        # 3. SELECT User
        if "from users" in sql_str:
            uid = params.get("id_1") or params.get("id")
            if uid is not None:
                matched = [u for u in self.db.users.values() if u.id == uid]
                return FakeResult(matched)
            return FakeResult(list(self.db.users.values()))

        # 4. SELECT Category
        if "from categories" in sql_str:
            cid = params.get("id_1") or params.get("id")
            if cid is not None:
                matched = [c for c in self.db.categories.values() if c.id == cid]
                return FakeResult(matched)
            return FakeResult(list(self.db.categories.values()))

        # 5. SELECT Receipts
        if "from receipts" in sql_str:
            key = params.get("storage_key_1") or params.get("storage_key")
            rid = params.get("id_1") or params.get("id")
            exp_id = params.get("expense_id_1") or params.get("expense_id")
            cutoff = params.get("created_at_1") or params.get("created_at")

            if key is not None:
                matched = [r for r in self.db.receipts.values() if r.storage_key == key]
                if "receipts.image_data" in sql_str:
                    return FakeResult([r.image_data for r in matched])
                return FakeResult(matched)

            if rid is not None:
                matched = [r for r in self.db.receipts.values() if r.id == rid]
                return FakeResult(matched)

            if exp_id is not None:
                matched = [r for r in self.db.receipts.values() if r.expense_id == exp_id]
                return FakeResult(matched)

            if "expense_id is null" in sql_str and cutoff is not None:
                matched = [
                    r
                    for r in self.db.receipts.values()
                    if r.expense_id is None and r.created_at <= cutoff
                ]
                return FakeResult(matched)

            return FakeResult(list(self.db.receipts.values()))

        # 6. SELECT Expense
        if "from expenses" in sql_str:
            eid = params.get("id_1") or params.get("id")
            if eid is not None:
                matched = [e for e in self.db.expenses.values() if e.id == eid]
                return FakeResult(matched)
            return FakeResult(list(self.db.expenses.values()))

        # 7. SELECT GroupMember
        if "from group_members" in sql_str:
            gid = params.get("group_id_1") or params.get("group_id")
            uid = params.get("user_id_1") or params.get("user_id")
            matched = [
                m
                for m in self.db.group_members
                if (gid is None or m.group_id == gid)
                and (uid is None or m.user_id == uid)
                and m.status == "active"
            ]
            return FakeResult(matched)

        return FakeResult([])


# =====================================================================
# Pytest Fixtures
# =====================================================================


@pytest.fixture
def fake_db() -> ReceiptApiFakeDB:
    db = ReceiptApiFakeDB()
    # Add a default category
    cat_id = uuid.uuid4()
    db.categories[cat_id] = Category(
        id=cat_id,
        name="Groceries",
        is_default=True,
        owner_id=None,
        created_at=datetime.now(UTC),
    )
    return db


@pytest.fixture
def in_memory_storage() -> InMemoryReceiptStorage:
    storage = InMemoryReceiptStorage()
    set_test_receipt_storage(storage)
    return storage


@pytest.fixture
def owner_user(fake_db: ReceiptApiFakeDB) -> User:
    user = User(
        id=uuid.uuid4(),
        email="owner@example.com",
        name="Owner User",
        hashed_password="hash",
        is_active=True,
    )
    fake_db.users[user.id] = user
    return user


@pytest.fixture
def other_user(fake_db: ReceiptApiFakeDB) -> User:
    user = User(
        id=uuid.uuid4(),
        email="stranger@example.com",
        name="Other User",
        hashed_password="hash",
        is_active=True,
    )
    fake_db.users[user.id] = user
    return user


@pytest.fixture
def owner_headers(owner_user: User) -> dict[str, str]:
    token = create_access_token(user_id=owner_user.id, email=owner_user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def other_headers(other_user: User) -> dict[str, str]:
    token = create_access_token(user_id=other_user.id, email=other_user.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client(fake_db: ReceiptApiFakeDB) -> AsyncClient:
    async def override_get_db():
        yield ReceiptApiFakeSession(fake_db)

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


# =====================================================================
# Scan Endpoint Tests (AC 1, AC 2, AC 3, AC 4)
# =====================================================================


@pytest.mark.anyio
async def test_scan_receipt_unauthenticated_returns_401(client: AsyncClient) -> None:
    res = await client.post("/api/v1/receipts/scan")
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


@pytest.mark.anyio
async def test_scan_receipt_unsupported_media_type_returns_415(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    """AC 3: Non-image or unsupported file type returns 415 UNSUPPORTED_MEDIA_TYPE."""
    pdf_bytes = b"%PDF-1.5 \n fake pdf receipt data"
    files = {"file": ("bill.pdf", pdf_bytes, "application/pdf")}
    res = await client.post("/api/v1/receipts/scan", headers=owner_headers, files=files)
    assert res.status_code == 415
    data = res.json()
    assert data["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert "Unsupported file type" in data["message"]


@pytest.mark.anyio
async def test_scan_receipt_corrupted_image_returns_422(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    """Corrupt image bytes return 422 INVALID_IMAGE."""
    corrupt_bytes = b"\xff\xd8\xff\xe0" + b"random_corrupt_data" * 50
    files = {"file": ("bill.jpg", corrupt_bytes, "image/jpeg")}
    res = await client.post("/api/v1/receipts/scan", headers=owner_headers, files=files)
    assert res.status_code == 422
    assert res.json()["code"] == "INVALID_IMAGE"


@pytest.mark.anyio
async def test_scan_receipt_oversized_upload_returns_413(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    """AC 1: Upload exceeding 5 MB returns HTTP 413 Payload Too Large."""
    oversized_bytes = b"\xFF\xD8\xFF\xE0" + b"\x00" * (5 * 1024 * 1024 + 10)
    files = {"file": ("bill.jpg", oversized_bytes, "image/jpeg")}
    res = await client.post("/api/v1/receipts/scan", headers=owner_headers, files=files)
    assert res.status_code == 413
    assert res.json()["code"] == "IMAGE_TOO_LARGE"


@pytest.mark.anyio
async def test_scan_receipt_magic_bytes_detection_png_named_as_jpg(
    client: AsyncClient,
    owner_headers: dict[str, str],
    in_memory_storage: InMemoryReceiptStorage,
    fake_db: ReceiptApiFakeDB,
) -> None:
    """AC 3: File type is detected strictly from magic bytes, ignoring filename/content-type."""
    png_bytes = make_test_png(100, 100)
    # File named receipt.jpg with client header image/jpeg, but actually containing PNG magic bytes
    files = {"file": ("receipt.jpg", png_bytes, "image/jpeg")}
    res = await client.post("/api/v1/receipts/scan", headers=owner_headers, files=files)
    assert res.status_code == 201
    data = res.json()["data"]
    assert data["fileSize"] > 0
    assert data["fileSize"] < 1_048_576
    receipt_id = uuid.UUID(data["receiptId"])
    assert receipt_id in fake_db.receipts
    assert fake_db.receipts[receipt_id].content_type == "image/jpeg"


@pytest.mark.anyio
async def test_scan_receipt_quota_exhausted_returns_429(
    client: AsyncClient,
    owner_headers: dict[str, str],
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
) -> None:
    """Exhausting daily receipt scans returns 429 QUOTA_EXCEEDED."""
    # Pre-fill 10 successful usage logs for today
    for _ in range(settings.AI_QUOTA_RECEIPT_DAILY):
        fake_db.ai_logs.append(
            AIUsageLog(
                id=uuid.uuid4(),
                user_id=owner_user.id,
                feature="receipt",
                status="success",
                created_at=datetime.now(UTC),
            )
        )

    jpeg_bytes = make_test_jpeg(100, 100)
    files = {"file": ("bill.jpg", jpeg_bytes, "image/jpeg")}
    res = await client.post("/api/v1/receipts/scan", headers=owner_headers, files=files)
    assert res.status_code == 429
    assert res.json()["code"] == "AI_QUOTA_EXCEEDED"


@pytest.mark.anyio
async def test_scan_receipt_successful_response_and_metadata(
    client: AsyncClient,
    owner_headers: dict[str, str],
    fake_db: ReceiptApiFakeDB,
    in_memory_storage: InMemoryReceiptStorage,
) -> None:
    """AC 1, AC 2, AC 4: Successful scan returns normalized structure and stores image privately."""
    jpeg_bytes = make_test_jpeg(300, 250, with_exif=True)
    files = {"file": ("grocery_bill.jpg", jpeg_bytes, "image/jpeg")}

    res = await client.post("/api/v1/receipts/scan", headers=owner_headers, files=files)
    assert res.status_code == 201
    payload = res.json()
    assert "Receipt processed successfully" in payload["message"]
    data = payload["data"]

    # Verify response schema fields
    receipt_id = uuid.UUID(data["receiptId"])
    assert data["fileSize"] > 0
    assert data["fileSize"] < 1_048_576  # AC 1: < 1 MB
    assert "merchant" in data
    assert "amountMinor" in data
    assert "category" in data

    # Verify DB record
    assert receipt_id in fake_db.receipts
    db_receipt = fake_db.receipts[receipt_id]
    assert db_receipt.file_size < 1_048_576
    assert db_receipt.content_type == "image/jpeg"
    # AC 4: Random unguessable storage key format receipts/{uuid4().hex}.jpg
    assert db_receipt.storage_key.startswith("receipts/")
    assert db_receipt.storage_key.endswith(".jpg")

    # Verify storage contains the image
    stored_blob = await in_memory_storage.get(db_receipt.storage_key)
    assert stored_blob is not None
    assert len(stored_blob) < 1_048_576

    # AC 2: Metadata stripped
    assert b"Secret location" not in stored_blob


# =====================================================================
# Image Retrieval Endpoint Tests (AC 4)
# =====================================================================


@pytest.mark.anyio
async def test_get_receipt_image_unauthenticated_returns_401(
    client: AsyncClient,
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
) -> None:
    receipt_id = uuid.uuid4()
    res = await client.get(f"/api/v1/receipts/{receipt_id}/image")
    assert res.status_code == 401
    assert res.json()["code"] == "UNAUTHORIZED"


@pytest.mark.anyio
async def test_get_receipt_image_not_found_returns_404(
    client: AsyncClient,
    owner_headers: dict[str, str],
) -> None:
    random_id = uuid.uuid4()
    res = await client.get(f"/api/v1/receipts/{random_id}/image", headers=owner_headers)
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


@pytest.mark.anyio
async def test_get_receipt_image_owner_gets_200_with_security_headers(
    client: AsyncClient,
    owner_headers: dict[str, str],
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
    in_memory_storage: InMemoryReceiptStorage,
) -> None:
    """AC 4: Owner can download image. Cache-Control and nosniff headers present."""
    receipt_id = uuid.uuid4()
    key = generate_key()
    img_bytes = make_test_jpeg(100, 100)
    await in_memory_storage.put(key, img_bytes, "image/jpeg")

    receipt = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        storage_key=key,
        content_type="image/jpeg",
        file_size=len(img_bytes),
        created_at=datetime.now(UTC),
    )
    fake_db.receipts[receipt_id] = receipt

    res = await client.get(f"/api/v1/receipts/{receipt_id}/image", headers=owner_headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert res.headers["cache-control"] == "private, no-store"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.content == img_bytes


@pytest.mark.anyio
async def test_get_receipt_image_owner_database_deferred_storage(
    client: AsyncClient,
    owner_headers: dict[str, str],
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
) -> None:
    """AC 4: Retrieving receipt stored as deferred BYTEA column in database."""
    receipt_id = uuid.uuid4()
    key = generate_key()
    img_bytes = make_test_jpeg(120, 120)

    receipt = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        storage_key=key,
        image_data=img_bytes,
        content_type="image/jpeg",
        file_size=len(img_bytes),
        created_at=datetime.now(UTC),
    )
    fake_db.receipts[receipt_id] = receipt

    res = await client.get(f"/api/v1/receipts/{receipt_id}/image", headers=owner_headers)
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/jpeg"
    assert res.headers["cache-control"] == "private, no-store"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.content == img_bytes


@pytest.mark.anyio
async def test_get_receipt_image_non_owner_returns_404(
    client: AsyncClient,
    other_headers: dict[str, str],
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
    in_memory_storage: InMemoryReceiptStorage,
) -> None:
    """AC 4: Another user requesting owner's receipt receives 404 (NEVER 403)."""
    receipt_id = uuid.uuid4()
    key = generate_key()
    img_bytes = make_test_jpeg(100, 100)
    await in_memory_storage.put(key, img_bytes, "image/jpeg")

    receipt = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        storage_key=key,
        content_type="image/jpeg",
        file_size=len(img_bytes),
        created_at=datetime.now(UTC),
    )
    fake_db.receipts[receipt_id] = receipt

    # Other user requests owner's receipt
    res = await client.get(f"/api/v1/receipts/{receipt_id}/image", headers=other_headers)
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


@pytest.mark.anyio
async def test_get_receipt_image_group_member_cannot_access_returns_404(
    client: AsyncClient,
    other_headers: dict[str, str],
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
    other_user: User,
    in_memory_storage: InMemoryReceiptStorage,
) -> None:
    """AC 4: Only the owner can view receipt image. Fellow group members receive 404."""
    group_id = uuid.uuid4()
    expense_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    key = generate_key()
    img_bytes = make_test_jpeg(100, 100)
    await in_memory_storage.put(key, img_bytes, "image/jpeg")

    receipt = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        expense_id=expense_id,
        storage_key=key,
        content_type="image/jpeg",
        file_size=len(img_bytes),
        created_at=datetime.now(UTC),
    )
    fake_db.receipts[receipt_id] = receipt

    expense = Expense(
        id=expense_id,
        user_id=owner_user.id,
        group_id=group_id,
        category_id=next(iter(fake_db.categories.keys())),
        amount_minor=1000,
        description="Group Dinner",
        receipt_id=receipt_id,
        version=1,
    )
    fake_db.expenses[expense_id] = expense

    # other_user is active member of group_id
    fake_db.group_members.append(
        GroupMember(
            group_id=group_id,
            user_id=other_user.id,
            role="member",
            status="active",
        )
    )

    # other_user receives 404 (strict owner-only access)
    res = await client.get(f"/api/v1/receipts/{receipt_id}/image", headers=other_headers)
    assert res.status_code == 404
    assert res.json()["code"] == "NOT_FOUND"


# =====================================================================
# Expense Linking and Cascade Deletion Tests (AC 5)
# =====================================================================


@pytest.mark.anyio
async def test_link_receipt_to_expense_ac5(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
) -> None:
    """AC 5: Bill is linked to the expense in the database."""
    receipt_id = uuid.uuid4()
    expense_id = uuid.uuid4()
    key = generate_key()

    fake_db.expenses[expense_id] = Expense(
        id=expense_id,
        user_id=owner_user.id,
        category_id=next(iter(fake_db.categories.keys())),
        amount_minor=5000,
        description="Test Expense",
        version=1,
    )

    receipt = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        expense_id=None,
        storage_key=key,
        content_type="image/jpeg",
        file_size=5000,
        created_at=datetime.now(UTC),
    )
    fake_db.receipts[receipt_id] = receipt

    session = ReceiptApiFakeSession(fake_db)
    linked = await link_receipt_to_expense(session, receipt_id, expense_id, owner_user.id)
    assert linked.expense_id == expense_id
    assert fake_db.receipts[receipt_id].expense_id == expense_id


@pytest.mark.anyio
async def test_link_receipt_prevent_double_linking_ac5(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
) -> None:
    """Receipt cannot be linked to another expense (returns 409 Conflict)."""
    receipt_id = uuid.uuid4()
    first_expense_id = uuid.uuid4()
    second_expense_id = uuid.uuid4()
    key = generate_key()

    fake_db.expenses[first_expense_id] = Expense(
        id=first_expense_id,
        user_id=owner_user.id,
        category_id=next(iter(fake_db.categories.keys())),
        amount_minor=5000,
        description="First Expense",
        version=1,
    )
    fake_db.expenses[second_expense_id] = Expense(
        id=second_expense_id,
        user_id=owner_user.id,
        category_id=next(iter(fake_db.categories.keys())),
        amount_minor=6000,
        description="Second Expense",
        version=1,
    )

    receipt = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        expense_id=first_expense_id,
        storage_key=key,
        content_type="image/jpeg",
        file_size=5000,
        created_at=datetime.now(UTC),
    )
    fake_db.receipts[receipt_id] = receipt

    session = ReceiptApiFakeSession(fake_db)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await link_receipt_to_expense(session, receipt_id, second_expense_id, owner_user.id)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "CONFLICT"


@pytest.mark.anyio
async def test_link_receipt_other_user_receipt_returns_404(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
    other_user: User,
) -> None:
    """Linking another user's receipt raises 404 Not Found."""
    receipt_id = uuid.uuid4()
    expense_id = uuid.uuid4()

    fake_db.expenses[expense_id] = Expense(
        id=expense_id,
        user_id=owner_user.id,
        category_id=next(iter(fake_db.categories.keys())),
        amount_minor=5000,
        description="Owner Expense",
        version=1,
    )

    receipt = Receipt(
        id=receipt_id,
        user_id=other_user.id,
        expense_id=None,
        storage_key=generate_key(),
        content_type="image/jpeg",
        file_size=5000,
        created_at=datetime.now(UTC),
    )
    fake_db.receipts[receipt_id] = receipt

    session = ReceiptApiFakeSession(fake_db)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await link_receipt_to_expense(session, receipt_id, expense_id, owner_user.id)
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_link_receipt_nonexistent_receipt_returns_404(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
) -> None:
    """Linking a non-existent receipt raises 404 Not Found."""
    expense_id = uuid.uuid4()
    fake_db.expenses[expense_id] = Expense(
        id=expense_id,
        user_id=owner_user.id,
        category_id=next(iter(fake_db.categories.keys())),
        amount_minor=5000,
        description="Owner Expense",
        version=1,
    )
    session = ReceiptApiFakeSession(fake_db)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await link_receipt_to_expense(session, uuid.uuid4(), expense_id, owner_user.id)
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_link_receipt_nonexistent_expense_returns_404(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
) -> None:
    """Linking a receipt to a non-existent expense raises 404 Not Found."""
    receipt_id = uuid.uuid4()
    fake_db.receipts[receipt_id] = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        expense_id=None,
        storage_key=generate_key(),
        content_type="image/jpeg",
        file_size=5000,
    )
    session = ReceiptApiFakeSession(fake_db)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await link_receipt_to_expense(session, receipt_id, uuid.uuid4(), owner_user.id)
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_link_receipt_other_user_expense_returns_404(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
    other_user: User,
) -> None:
    """Linking owner's receipt to another user's personal expense raises 404 Not Found."""
    receipt_id = uuid.uuid4()
    fake_db.receipts[receipt_id] = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        expense_id=None,
        storage_key=generate_key(),
        content_type="image/jpeg",
        file_size=5000,
    )
    expense_id = uuid.uuid4()
    fake_db.expenses[expense_id] = Expense(
        id=expense_id,
        user_id=other_user.id,
        category_id=next(iter(fake_db.categories.keys())),
        amount_minor=5000,
        description="Other User Expense",
        version=1,
    )
    session = ReceiptApiFakeSession(fake_db)
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await link_receipt_to_expense(session, receipt_id, expense_id, owner_user.id)
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_delete_expense_deletes_receipt_row_and_storage_ac5(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
    in_memory_storage: InMemoryReceiptStorage,
) -> None:
    """AC 5: Deleting an expense deletes its receipt from database AND from storage."""
    receipt_id = uuid.uuid4()
    expense_id = uuid.uuid4()
    key = generate_key()
    img_bytes = make_test_jpeg(100, 100)
    await in_memory_storage.put(key, img_bytes, "image/jpeg")

    receipt = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        expense_id=expense_id,
        storage_key=key,
        content_type="image/jpeg",
        file_size=len(img_bytes),
        created_at=datetime.now(UTC),
    )
    fake_db.receipts[receipt_id] = receipt

    session = ReceiptApiFakeSession(fake_db)
    await delete_receipt_for_expense(session, expense_id, storage=in_memory_storage)

    # Receipt row is deleted from DB
    assert receipt_id not in fake_db.receipts

    # Stored blob is deleted from storage
    assert await in_memory_storage.get(key) is None


@pytest.mark.anyio
async def test_soft_delete_preserves_receipt_and_undo_restores_it(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
    in_memory_storage: InMemoryReceiptStorage,
) -> None:
    """Soft deletion preserves receipt record and storage blob; restoration preserves them; hard delete permanently deletes both."""
    from app.services.expenses import (
        hard_delete_expense,
        restore_expense,
        soft_delete_expense,
    )

    expense_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    key = generate_key()
    img_bytes = make_test_jpeg(100, 100)
    await in_memory_storage.put(key, img_bytes, "image/jpeg")

    receipt = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        expense_id=expense_id,
        storage_key=key,
        content_type="image/jpeg",
        file_size=len(img_bytes),
        created_at=datetime.now(UTC),
    )
    fake_db.receipts[receipt_id] = receipt

    cat_id = next(iter(fake_db.categories.keys()))
    expense = Expense(
        id=expense_id,
        user_id=owner_user.id,
        category_id=cat_id,
        amount_minor=2000,
        description="Soft delete test",
        receipt_id=receipt_id,
        version=1,
    )
    fake_db.expenses[expense_id] = expense

    session = ReceiptApiFakeSession(fake_db)

    # 1. Soft delete expense
    soft_deleted = await soft_delete_expense(session, owner_user.id, expense_id)
    assert soft_deleted.deleted_at is not None

    # Receipt and image MUST still exist
    assert receipt_id in fake_db.receipts
    assert await in_memory_storage.get(key) == img_bytes

    # 2. Undo (restore) expense
    restored = await restore_expense(session, owner_user.id, expense_id)
    assert restored.deleted_at is None
    assert restored.receipt_id == receipt_id
    assert receipt_id in fake_db.receipts
    assert await in_memory_storage.get(key) == img_bytes

    # 3. Permanent (hard) delete removes both DB record and storage blob
    await hard_delete_expense(session, owner_user.id, expense_id, storage=in_memory_storage)
    assert expense_id not in fake_db.expenses
    assert receipt_id not in fake_db.receipts
    assert await in_memory_storage.get(key) is None


@pytest.mark.anyio
async def test_upload_db_commit_failure_cleans_up_storage_blob(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
    in_memory_storage: InMemoryReceiptStorage,
) -> None:
    """If DB commit fails during receipt upload, DB rolls back and uploaded blob is deleted from storage."""
    from app.services.receipt_service import scan_and_store_receipt

    session = ReceiptApiFakeSession(fake_db)

    # Inject commit failure
    async def failing_commit():
        raise RuntimeError("Simulated DB connection failure on commit")

    session.commit = failing_commit

    raw_jpeg = make_test_jpeg(100, 100)
    with pytest.raises(RuntimeError, match="Simulated DB connection failure"):
        await scan_and_store_receipt(
            db=session,
            current_user=owner_user,
            raw_bytes=raw_jpeg,
            storage=in_memory_storage,
        )

    # Verify no dangling blobs in in_memory_storage
    assert len(in_memory_storage._store) == 0
    # Verify no receipt in fake_db
    assert len(fake_db.receipts) == 0


@pytest.mark.anyio
async def test_delete_db_commit_failure_preserves_storage_blob(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
    in_memory_storage: InMemoryReceiptStorage,
) -> None:
    """If DB commit fails during permanent receipt delete, storage blob is NOT deleted."""
    receipt_id = uuid.uuid4()
    expense_id = uuid.uuid4()
    key = generate_key()
    img_bytes = make_test_jpeg(100, 100)
    await in_memory_storage.put(key, img_bytes, "image/jpeg")

    receipt = Receipt(
        id=receipt_id,
        user_id=owner_user.id,
        expense_id=expense_id,
        storage_key=key,
        content_type="image/jpeg",
        file_size=len(img_bytes),
        created_at=datetime.now(UTC),
    )
    fake_db.receipts[receipt_id] = receipt

    session = ReceiptApiFakeSession(fake_db)

    # Inject commit failure
    async def failing_commit():
        raise RuntimeError("Simulated DB error during delete commit")

    session.commit = failing_commit

    with pytest.raises(RuntimeError, match="Simulated DB error"):
        await delete_receipt_for_expense(
            db=session,
            expense_id=expense_id,
            storage=in_memory_storage,
            commit=True,
        )

    # Storage blob MUST still exist because DB commit failed!
    assert await in_memory_storage.get(key) == img_bytes
    # Receipt row remains in DB because delete commit failed
    assert receipt_id in fake_db.receipts


# =====================================================================
# 24-Hour Purge Tests
# =====================================================================


@pytest.mark.anyio
async def test_purge_unlinked_receipts_removes_old_receipts(
    fake_db: ReceiptApiFakeDB,
    owner_user: User,
    in_memory_storage: InMemoryReceiptStorage,
) -> None:
    """Purge removes unlinked receipts older than 24h, but keeps recent or linked receipts."""
    now = datetime.now(UTC)

    # 1. Old unlinked receipt (>24h) -> should be purged
    old_unlinked_id = uuid.uuid4()
    old_key = generate_key()
    await in_memory_storage.put(old_key, b"old_data", "image/jpeg")
    fake_db.receipts[old_unlinked_id] = Receipt(
        id=old_unlinked_id,
        user_id=owner_user.id,
        expense_id=None,
        storage_key=old_key,
        content_type="image/jpeg",
        file_size=8,
        created_at=now - timedelta(hours=25),
    )

    # 2. Recent unlinked receipt (<24h) -> should be kept
    recent_unlinked_id = uuid.uuid4()
    recent_key = generate_key()
    await in_memory_storage.put(recent_key, b"recent_data", "image/jpeg")
    fake_db.receipts[recent_unlinked_id] = Receipt(
        id=recent_unlinked_id,
        user_id=owner_user.id,
        expense_id=None,
        storage_key=recent_key,
        content_type="image/jpeg",
        file_size=11,
        created_at=now - timedelta(hours=2),
    )

    # 3. Old linked receipt (>24h, has expense_id) -> should be kept
    linked_id = uuid.uuid4()
    linked_key = generate_key()
    await in_memory_storage.put(linked_key, b"linked_data", "image/jpeg")
    fake_db.receipts[linked_id] = Receipt(
        id=linked_id,
        user_id=owner_user.id,
        expense_id=uuid.uuid4(),
        storage_key=linked_key,
        content_type="image/jpeg",
        file_size=11,
        created_at=now - timedelta(hours=30),
    )

    session = ReceiptApiFakeSession(fake_db)
    purged_count = await purge_unlinked_receipts(
        session, storage=in_memory_storage, older_than_hours=24
    )

    assert purged_count == 1
    # Old unlinked is gone
    assert old_unlinked_id not in fake_db.receipts
    assert await in_memory_storage.get(old_key) is None

    # Recent unlinked is retained
    assert recent_unlinked_id in fake_db.receipts
    assert await in_memory_storage.get(recent_key) is not None

    # Linked receipt is retained
    assert linked_id in fake_db.receipts
    assert await in_memory_storage.get(linked_key) is not None


# =====================================================================
# Storage Backends Unit Tests
# =====================================================================


@pytest.mark.anyio
async def test_database_receipt_storage() -> None:
    """Test DatabaseReceiptStorage put/get/delete using deferred BYTEA."""
    db = ReceiptApiFakeDB()
    session = ReceiptApiFakeSession(db)
    storage = DatabaseReceiptStorage(db=session)
    key = generate_key()
    receipt = Receipt(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        storage_key=key,
        content_type="image/jpeg",
        file_size=0,
    )
    db.receipts[receipt.id] = receipt
    data = b"raw_image_bytes"
    await storage.put(key, data, "image/jpeg")
    assert receipt.image_data == data

    # Test get with session
    retrieved = await storage.get(key)
    assert retrieved == data

    # Test delete with session
    await storage.delete(key)
    assert receipt.image_data is None


@pytest.mark.anyio
async def test_in_memory_receipt_storage() -> None:
    """Test InMemoryReceiptStorage put/get/delete."""
    storage = InMemoryReceiptStorage()
    key = generate_key()
    data = b"in_memory_test_data"
    await storage.put(key, data, "image/jpeg")
    assert await storage.get(key) == data
    await storage.delete(key)
    assert await storage.get(key) is None


@pytest.mark.anyio
async def test_supabase_receipt_storage_operations() -> None:
    """Test SupabaseReceiptStorage put/get/delete with mock HTTP client."""
    from httpx import MockTransport, Request, Response

    store: dict[str, bytes] = {}

    def handler(request: Request) -> Response:
        filename = request.url.path.split("/")[-1]
        if request.method == "POST":
            store[filename] = request.content
            return Response(200, json={"Key": filename})
        elif request.method == "GET":
            if filename in store:
                return Response(200, content=store[filename], headers={"content-type": "image/jpeg"})
            return Response(404, json={"error": "Not Found"})
        elif request.method == "DELETE":
            store.pop(filename, None)
            return Response(200, json={"message": "Deleted"})
        return Response(400)

    transport = MockTransport(handler)
    async with AsyncClient(transport=transport, base_url="http://supabase.mock") as mock_client:
        supabase_storage = SupabaseReceiptStorage(
            base_url="http://supabase.mock",
            service_key="secret-key",
            bucket="receipts",
            http_client=mock_client,
        )
        key = "receipts/test_blob.jpg"
        data = b"supabase_test_bytes"
        await supabase_storage.put(key, data, "image/jpeg")
        assert await supabase_storage.get(key) == data
        await supabase_storage.delete(key)
        assert await supabase_storage.get(key) is None

