import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, List, Optional

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.group import (
    Group,
    GroupInvitation,
    GroupMember,
    GroupMemberRole,
    GroupMemberStatus,
    GroupType,
    InvitationStatus,
)
from app.models.user import User


# ==============================================================================
# In-Memory Test Database & Session Fixtures for Groups
# ==============================================================================

class FakeGroupDB:
    def __init__(self):
        self.users: dict[uuid.UUID, User] = {}
        self.groups: dict[uuid.UUID, Group] = {}
        self.group_members: dict[tuple[uuid.UUID, uuid.UUID], GroupMember] = {}
        self.invitations: dict[uuid.UUID, GroupInvitation] = {}


class FakeScalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None


class FakeResult:
    def __init__(self, items=None, rowcount=1, tuple_res=None):
        self._items = items or []
        self.rowcount = rowcount
        self._tuple_res = tuple_res

    def scalar_one_or_none(self):
        return self._items[0] if self._items else None

    def scalar_one(self):
        return self._items[0] if self._items else 0

    def scalar(self):
        return self._items[0] if self._items else None

    def scalars(self):
        return FakeScalars(self._items)

    def all(self):
        return list(self._items)

    def one(self):
        if self._tuple_res is not None:
            return self._tuple_res
        return self._items[0] if self._items else (0, 0)


class FakeGroupAsyncSession:
    def __init__(self, db: FakeGroupDB):
        self.db = db
        self.pending: list[object] = []

    def add(self, obj):
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        self.pending.append(obj)

    async def flush(self):
        await self.commit()

    async def commit(self):
        for obj in self.pending:
            if isinstance(obj, User):
                self.db.users[obj.id] = obj
            elif isinstance(obj, Group):
                self.db.groups[obj.id] = obj
            elif isinstance(obj, GroupMember):
                self.db.group_members[(obj.group_id, obj.user_id)] = obj
            elif isinstance(obj, GroupInvitation):
                self.db.invitations[obj.id] = obj
        self.pending.clear()

        # Wire bidirectional relationships for groups
        for grp in self.db.groups.values():
            grp_members = [
                m for m in self.db.group_members.values() if m.group_id == grp.id
            ]
            for m in grp_members:
                m.user = self.db.users.get(m.user_id)
            grp.members = grp_members
            grp.creator = self.db.users.get(grp.created_by)
            grp.invitations = [
                i for i in self.db.invitations.values() if i.group_id == grp.id
            ]

    async def rollback(self):
        self.pending.clear()

    async def refresh(self, obj):
        pass

    async def execute(self, stmt):
        await self.commit()
        sql_str = str(stmt).lower()
        params = stmt.compile().params

        # 1. SELECT User
        if "from users" in sql_str:
            id_val = next(
                (v for k, v in params.items() if (k.startswith("id_") or k == "id" or k.endswith("_id")) and isinstance(v, uuid.UUID) and "group_id" not in k and "invited_user_id" not in k),
                None,
            )
            email_val = next(
                (v for k, v in params.items() if ("email" in k or "lower" in k) and isinstance(v, str)),
                None,
            )
            matched = list(self.db.users.values())
            if id_val is not None:
                matched = [u for u in matched if u.id == id_val]
            if email_val is not None:
                matched = [u for u in matched if u.email.lower() == email_val.lower()]
            return FakeResult(matched)

        # 2. SELECT Group
        if "from groups" in sql_str:
            if "join group_members" in sql_str:
                user_id = next(
                    (v for k, v in params.items() if ("user_id" in k) and isinstance(v, uuid.UUID)),
                    None,
                )
                items = []
                for (gid, uid), member in self.db.group_members.items():
                    if uid == user_id and member.status == GroupMemberStatus.ACTIVE.value:
                        grp = self.db.groups.get(gid)
                        if grp and grp.archived_at is None:
                            items.append((grp, member.role))
                return FakeResult(items)

            id_val = next(
                (v for k, v in params.items() if (k.startswith("id_") or k == "id" or "group_id" in k) and isinstance(v, uuid.UUID)),
                None,
            )
            matched = list(self.db.groups.values())
            if id_val is not None:
                matched = [g for g in matched if g.id == id_val and g.archived_at is None]
            return FakeResult(matched)

        # 3. SELECT GroupMember
        if "from group_members" in sql_str:
            if "count" in sql_str:
                gid = next(
                    (v for k, v in params.items() if "group_id" in k and isinstance(v, uuid.UUID)),
                    None,
                )
                cnt = sum(
                    1
                    for m in self.db.group_members.values()
                    if m.group_id == gid and m.status == GroupMemberStatus.ACTIVE.value
                )
                return FakeResult([cnt])

            gid = next(
                (v for k, v in params.items() if "group_id" in k and isinstance(v, uuid.UUID)),
                None,
            )
            uid = next(
                (v for k, v in params.items() if ("user_id" in k) and isinstance(v, uuid.UUID) and "group_id" not in k),
                None,
            )
            status_val = next(
                (v for k, v in params.items() if "status" in k and isinstance(v, str)),
                None,
            )
            matched = list(self.db.group_members.values())
            if gid is not None:
                matched = [m for m in matched if m.group_id == gid]
            if uid is not None:
                matched = [m for m in matched if m.user_id == uid]
            if status_val is not None:
                matched = [m for m in matched if m.status == status_val]
            return FakeResult(matched)

        # 4. SELECT GroupInvitation
        if "from group_invitations" in sql_str:
            if "join groups" in sql_str:
                uid = next(
                    (v for k, v in params.items() if "invited_user_id" in k and isinstance(v, uuid.UUID)),
                    None,
                )
                email_val = next(
                    (v for k, v in params.items() if ("email" in k or "lower" in k) and isinstance(v, str)),
                    None,
                )
                items = []
                now = datetime.now(UTC)
                for inv in self.db.invitations.values():
                    if inv.status == InvitationStatus.PENDING.value and inv.expires_at > now:
                        matches = False
                        if uid is not None and inv.invited_user_id == uid:
                            matches = True
                        if email_val is not None and inv.invited_email and inv.invited_email.lower() == email_val.lower():
                            matches = True
                        if matches:
                            grp = self.db.groups.get(inv.group_id)
                            if grp and grp.archived_at is None:
                                items.append((inv, grp.name, grp.type))
                return FakeResult(items)

            code_hash_val = next(
                (v for k, v in params.items() if "code_hash" in k and isinstance(v, str)),
                None,
            )
            inv_id = next(
                (v for k, v in params.items() if (k.startswith("id_") or k == "id") and isinstance(v, uuid.UUID)),
                None,
            )
            gid = next(
                (v for k, v in params.items() if "group_id" in k and isinstance(v, uuid.UUID)),
                None,
            )
            uid = next(
                (v for k, v in params.items() if "invited_user_id" in k and isinstance(v, uuid.UUID)),
                None,
            )
            status_val = next(
                (v for k, v in params.items() if "status" in k and isinstance(v, str)),
                None,
            )

            matched = list(self.db.invitations.values())
            if code_hash_val is not None:
                matched = [i for i in matched if i.code_hash == code_hash_val]
            if inv_id is not None:
                matched = [i for i in matched if i.id == inv_id]
            if gid is not None:
                matched = [i for i in matched if i.group_id == gid]
            if uid is not None:
                matched = [i for i in matched if i.invited_user_id == uid]
            if status_val is not None:
                matched = [i for i in matched if i.status == status_val]
            return FakeResult(matched)

        return FakeResult([])


@pytest.fixture
def group_db():
    return FakeGroupDB()


@pytest.fixture
def user_owner(group_db):
    user = User(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        email="owner@example.com",
        name="Owner Alice",
        hashed_password="hashed_pw",
        is_active=True,
    )
    group_db.users[user.id] = user
    return user


@pytest.fixture
def user_member(group_db):
    user = User(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        email="member@example.com",
        name="Member Bob",
        hashed_password="hashed_pw",
        is_active=True,
    )
    group_db.users[user.id] = user
    return user


@pytest.fixture
def user_stranger(group_db):
    user = User(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        email="stranger@example.com",
        name="Stranger Charlie",
        hashed_password="hashed_pw",
        is_active=True,
    )
    group_db.users[user.id] = user
    return user


@pytest.fixture
async def client(group_db):
    app.dependency_overrides[get_db] = lambda: FakeGroupAsyncSession(group_db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user.id, email=user.email)
    return {"Authorization": f"Bearer {token}"}


# ==============================================================================
# 1. Group Creation Tests & Group Types
# ==============================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("group_type", ["friends", "flat", "trip", "family"])
async def test_create_group_all_valid_types(client, user_owner, group_type, group_db):
    """
    US-17 AC1: Create groups with name, description, and required group type.
    Valid types: friends, flat, trip, family.
    Creator is automatically set as admin and an initial join code is returned.
    """
    payload = {
        "name": f"Test {group_type.title()} Group",
        "description": f"A shared group for {group_type}",
        "type": group_type,
    }
    resp = await client.post("/api/v1/groups", json=payload, headers=auth_headers(user_owner))
    assert resp.status_code == 201
    data = resp.json()

    assert data["name"] == payload["name"]
    assert data["description"] == payload["description"]
    assert data["type"] == group_type
    assert data["createdBy"] == str(user_owner.id)
    assert data["currentUserRole"] == "admin"
    assert len(data["members"]) == 1
    assert data["members"][0]["userId"] == str(user_owner.id)
    assert data["members"][0]["role"] == "admin"
    assert data["members"][0]["status"] == "active"

    # Join code returned once
    assert data["joinCode"] is not None
    assert len(data["joinCode"]) == 8

    # Verify plaintext code is NOT stored in DB; only hashed code is stored
    group_id = uuid.UUID(data["id"])
    invitations = [i for i in group_db.invitations.values() if i.group_id == group_id]
    assert len(invitations) == 1
    inv = invitations[0]
    assert inv.code_hash is not None
    assert inv.code_hash != data["joinCode"]
    expected_hash = hashlib.sha256(data["joinCode"].encode()).hexdigest()
    assert inv.code_hash == expected_hash
    assert inv.status == "pending"


@pytest.mark.asyncio
async def test_create_group_invalid_type_rejected(client, user_owner):
    """Rejects group creation with an unsupported group type."""
    payload = {
        "name": "Invalid Group",
        "type": "enterprise",
    }
    resp = await client.post("/api/v1/groups", json=payload, headers=auth_headers(user_owner))
    assert resp.status_code == 422
    data = resp.json()
    assert data["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_group_blank_name_rejected(client, user_owner):
    """Rejects group creation with empty or whitespace-only name."""
    payload = {
        "name": "   ",
        "type": "friends",
    }
    resp = await client.post("/api/v1/groups", json=payload, headers=auth_headers(user_owner))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_group_unauthenticated_rejected(client):
    """Unauthenticated group creation is rejected with 401."""
    resp = await client.post("/api/v1/groups", json={"name": "Secret", "type": "trip"})
    assert resp.status_code == 401


# ==============================================================================
# 2. Join Code: Hashing, Expiry, Revocation, and Validation
# ==============================================================================

@pytest.mark.asyncio
async def test_join_code_7_day_expiry(client, user_owner, user_stranger, group_db):
    """
    US-17 AC4: Join codes expire automatically after 7 days.
    Reject expired join codes with HTTP 400 JOIN_CODE_EXPIRED.
    """
    # Create group
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Expiring Group", "type": "trip"},
        headers=auth_headers(user_owner),
    )
    assert create_resp.status_code == 201
    join_code = create_resp.json()["joinCode"]
    group_id = uuid.UUID(create_resp.json()["id"])

    # Simulate code expiration: shift expires_at to 8 days in past
    inv = next(i for i in group_db.invitations.values() if i.group_id == group_id)
    inv.expires_at = datetime.now(UTC) - timedelta(days=1)

    # Stranger attempts to join with expired code
    join_resp = await client.post(
        "/api/v1/groups/join",
        json={"code": join_code},
        headers=auth_headers(user_stranger),
    )
    assert join_resp.status_code == 400
    data = join_resp.json()
    assert data["code"] == "JOIN_CODE_EXPIRED"
    assert "expired" in data["message"].lower()


@pytest.mark.asyncio
async def test_join_code_owner_revocation(client, user_owner, user_stranger, group_db):
    """
    US-17 AC4: Support owner-controlled revocation.
    Reject revoked join codes with HTTP 400 JOIN_CODE_REVOKED.
    """
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Revocable Group", "type": "friends"},
        headers=auth_headers(user_owner),
    )
    join_code = create_resp.json()["joinCode"]
    group_id = create_resp.json()["id"]

    # Owner revokes join code
    revoke_resp = await client.delete(
        f"/api/v1/groups/{group_id}/join-code",
        headers=auth_headers(user_owner),
    )
    assert revoke_resp.status_code == 204

    # Stranger tries to join with revoked code
    join_resp = await client.post(
        "/api/v1/groups/join",
        json={"code": join_code},
        headers=auth_headers(user_stranger),
    )
    assert join_resp.status_code == 400
    data = join_resp.json()
    assert data["code"] == "JOIN_CODE_REVOKED"


@pytest.mark.asyncio
async def test_join_code_rotation_by_owner(client, user_owner, user_stranger, group_db):
    """
    Owner generating a new join code revokes old code and issues a new active code.
    """
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Rotating Group", "type": "flat"},
        headers=auth_headers(user_owner),
    )
    old_code = create_resp.json()["joinCode"]
    group_id = create_resp.json()["id"]

    # Generate new join code
    rotate_resp = await client.post(
        f"/api/v1/groups/{group_id}/join-code",
        headers=auth_headers(user_owner),
    )
    assert rotate_resp.status_code == 201
    new_code = rotate_resp.json()["code"]
    assert new_code != old_code
    assert len(new_code) == 8

    # Old code is now revoked
    join_old = await client.post(
        "/api/v1/groups/join",
        json={"code": old_code},
        headers=auth_headers(user_stranger),
    )
    assert join_old.status_code == 400
    assert join_old.json()["code"] == "JOIN_CODE_REVOKED"

    # New code succeeds
    join_new = await client.post(
        "/api/v1/groups/join",
        json={"code": new_code},
        headers=auth_headers(user_stranger),
    )
    assert join_new.status_code == 200
    assert join_new.json()["group"]["id"] == group_id


@pytest.mark.asyncio
async def test_join_code_invalid_rejected(client, user_stranger):
    """Joining with an unrecognized join code returns 400 INVALID_JOIN_CODE."""
    resp = await client.post(
        "/api/v1/groups/join",
        json={"code": "NONEXIST"},
        headers=auth_headers(user_stranger),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_JOIN_CODE"


# ==============================================================================
# 3. Joining Groups and Duplicate Membership Prevention
# ==============================================================================

@pytest.mark.asyncio
async def test_join_group_success_and_duplicate_prevention(client, user_owner, user_member):
    """
    US-17 AC4: Users can join via code. Duplicate memberships are rejected.
    """
    # Owner creates group
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Roommates", "type": "flat"},
        headers=auth_headers(user_owner),
    )
    join_code = create_resp.json()["joinCode"]
    group_id = create_resp.json()["id"]

    # Member joins successfully
    join_resp = await client.post(
        "/api/v1/groups/join",
        json={"code": join_code},
        headers=auth_headers(user_member),
    )
    assert join_resp.status_code == 200
    data = join_resp.json()
    assert data["group"]["id"] == group_id
    assert any(m["userId"] == str(user_member.id) for m in data["group"]["members"])

    # Member attempts to join again -> 409 ALREADY_MEMBER
    dup_resp = await client.post(
        "/api/v1/groups/join",
        json={"code": join_code},
        headers=auth_headers(user_member),
    )
    assert dup_resp.status_code == 409
    assert dup_resp.json()["code"] == "ALREADY_MEMBER"

    # Owner attempts to join own group -> 409 ALREADY_MEMBER
    owner_dup = await client.post(
        "/api/v1/groups/join",
        json={"code": join_code},
        headers=auth_headers(user_owner),
    )
    assert owner_dup.status_code == 409
    assert owner_dup.json()["code"] == "ALREADY_MEMBER"


# ==============================================================================
# 4. In-App Invitations: Accept and Decline
# ==============================================================================

@pytest.mark.asyncio
async def test_invitation_accept_flow(client, user_owner, user_member):
    """
    US-17 AC2 & AC3: Members can be invited; invited user can accept.
    """
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Family Trip", "type": "family"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]

    # Owner invites user_member by email
    invite_resp = await client.post(
        f"/api/v1/groups/{group_id}/invitations",
        json={"email": user_member.email},
        headers=auth_headers(user_owner),
    )
    assert invite_resp.status_code == 201
    inv_data = invite_resp.json()
    assert inv_data["groupId"] == group_id
    assert inv_data["status"] == "pending"
    inv_id = inv_data["id"]

    # user_member lists pending invitations
    my_invites = await client.get("/api/v1/invitations", headers=auth_headers(user_member))
    assert my_invites.status_code == 200
    invite_list = my_invites.json()
    assert len(invite_list) == 1
    assert invite_list[0]["id"] == inv_id

    # user_member accepts invitation
    accept_resp = await client.post(
        f"/api/v1/invitations/{inv_id}/accept",
        headers=auth_headers(user_member),
    )
    assert accept_resp.status_code == 200
    group_data = accept_resp.json()["group"]
    assert any(m["userId"] == str(user_member.id) for m in group_data["members"])

    # Trying to accept again fails
    re_accept = await client.post(
        f"/api/v1/invitations/{inv_id}/accept",
        headers=auth_headers(user_member),
    )
    assert re_accept.status_code == 400
    assert re_accept.json()["code"] == "INVALID_INVITATION_STATUS"


@pytest.mark.asyncio
async def test_invitation_decline_flow(client, user_owner, user_member, group_db):
    """
    US-17 AC3: Users can decline invitations.
    """
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Goa Trip", "type": "trip"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]

    # Owner invites member
    invite_resp = await client.post(
        f"/api/v1/groups/{group_id}/invitations",
        json={"userId": str(user_member.id)},
        headers=auth_headers(user_owner),
    )
    assert invite_resp.status_code == 201
    inv_id = invite_resp.json()["id"]

    # user_member declines invitation
    decline_resp = await client.post(
        f"/api/v1/invitations/{inv_id}/decline",
        headers=auth_headers(user_member),
    )
    assert decline_resp.status_code == 204

    # Invitation status is now declined
    inv = group_db.invitations[uuid.UUID(inv_id)]
    assert inv.status == "declined"

    # User is NOT a member of the group
    group_resp = await client.get(
        f"/api/v1/groups/{group_id}",
        headers=auth_headers(user_owner),
    )
    assert not any(m["userId"] == str(user_member.id) for m in group_resp.json()["members"])


@pytest.mark.asyncio
async def test_stranger_cannot_accept_another_users_invitation(client, user_owner, user_member, user_stranger):
    """Stranger cannot accept an invitation issued to someone else."""
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Private Group", "type": "friends"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]

    # Invite user_member
    invite_resp = await client.post(
        f"/api/v1/groups/{group_id}/invitations",
        json={"email": user_member.email},
        headers=auth_headers(user_owner),
    )
    inv_id = invite_resp.json()["id"]

    # user_stranger attempts to accept it
    resp = await client.post(
        f"/api/v1/invitations/{inv_id}/accept",
        headers=auth_headers(user_stranger),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "INVITATION_NOT_FOUND"


# ==============================================================================
# 5. Member Removal (Owner-Only)
# ==============================================================================

@pytest.mark.asyncio
async def test_owner_removes_member(client, user_owner, user_member, group_db):
    """
    US-17 AC5: Group admin can remove members. Soft removal preserves ledger history.
    """
    # Create group and join member
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Flat 301", "type": "flat"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]
    join_code = create_resp.json()["joinCode"]

    await client.post(
        "/api/v1/groups/join",
        json={"code": join_code},
        headers=auth_headers(user_member),
    )

    # Owner removes member
    del_resp = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_member.id}",
        headers=auth_headers(user_owner),
    )
    assert del_resp.status_code == 204

    # Verify status in database is 'removed'
    membership = group_db.group_members[(uuid.UUID(group_id), user_member.id)]
    assert membership.status == "removed"

    # Member no longer shows up in active members
    get_resp = await client.get(f"/api/v1/groups/{group_id}", headers=auth_headers(user_owner))
    active_member_ids = [m["userId"] for m in get_resp.json()["members"]]
    assert str(user_member.id) not in active_member_ids


@pytest.mark.asyncio
async def test_owner_cannot_remove_self(client, user_owner):
    """Owner cannot remove themselves from their group."""
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Flat 301", "type": "flat"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_owner.id}",
        headers=auth_headers(user_owner),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "CANNOT_REMOVE_OWNER"


@pytest.mark.asyncio
async def test_non_owner_member_cannot_remove_members(client, user_owner, user_member, user_stranger):
    """Non-admin group member cannot remove another member."""
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Flat 301", "type": "flat"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]
    join_code = create_resp.json()["joinCode"]

    # Join member and stranger
    await client.post("/api/v1/groups/join", json={"code": join_code}, headers=auth_headers(user_member))
    await client.post("/api/v1/groups/join", json={"code": join_code}, headers=auth_headers(user_stranger))

    # user_member (regular member) attempts to remove user_stranger
    resp = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_stranger.id}",
        headers=auth_headers(user_member),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "INSUFFICIENT_PERMISSIONS"


# ==============================================================================
# 6. Authorization Policies: Owner, Member, and Stranger
# ==============================================================================

@pytest.mark.asyncio
async def test_stranger_cannot_view_group_details(client, user_owner, user_stranger):
    """Stranger cannot view group details or member list."""
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Private Club", "type": "friends"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/groups/{group_id}",
        headers=auth_headers(user_stranger),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "GROUP_ACCESS_DENIED"


@pytest.mark.asyncio
async def test_member_can_view_group_details(client, user_owner, user_member):
    """Authorized member can view group details."""
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Study Group", "type": "friends"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]
    join_code = create_resp.json()["joinCode"]

    await client.post("/api/v1/groups/join", json={"code": join_code}, headers=auth_headers(user_member))

    resp = await client.get(f"/api/v1/groups/{group_id}", headers=auth_headers(user_member))
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == group_id
    assert data["currentUserRole"] == "member"
    # Plaintext join code is NEVER exposed in GET responses
    assert data["joinCode"] is None


@pytest.mark.asyncio
async def test_member_cannot_rotate_or_revoke_join_code(client, user_owner, user_member):
    """Regular member cannot rotate or revoke join codes (admin-only)."""
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Trek Group", "type": "trip"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]
    join_code = create_resp.json()["joinCode"]

    await client.post("/api/v1/groups/join", json={"code": join_code}, headers=auth_headers(user_member))

    # Member tries to rotate code
    rot_resp = await client.post(
        f"/api/v1/groups/{group_id}/join-code",
        headers=auth_headers(user_member),
    )
    assert rot_resp.status_code == 403
    assert rot_resp.json()["code"] == "INSUFFICIENT_PERMISSIONS"

    # Member tries to revoke code
    rev_resp = await client.delete(
        f"/api/v1/groups/{group_id}/join-code",
        headers=auth_headers(user_member),
    )
    assert rev_resp.status_code == 403
    assert rev_resp.json()["code"] == "INSUFFICIENT_PERMISSIONS"


@pytest.mark.asyncio
async def test_list_user_groups_isolation(client, user_owner, user_member, user_stranger):
    """GET /api/v1/groups lists only groups the user is a member of."""
    # Owner creates two groups
    g1 = await client.post(
        "/api/v1/groups",
        json={"name": "Owner G1", "type": "friends"},
        headers=auth_headers(user_owner),
    )
    g2 = await client.post(
        "/api/v1/groups",
        json={"name": "Owner G2", "type": "flat"},
        headers=auth_headers(user_owner),
    )

    # Member joins g1 only
    await client.post(
        "/api/v1/groups/join",
        json={"code": g1.json()["joinCode"]},
        headers=auth_headers(user_member),
    )

    # Owner lists groups -> sees both
    owner_list = await client.get("/api/v1/groups", headers=auth_headers(user_owner))
    assert owner_list.status_code == 200
    assert len(owner_list.json()) == 2

    # Member lists groups -> sees only g1
    member_list = await client.get("/api/v1/groups", headers=auth_headers(user_member))
    assert member_list.status_code == 200
    assert len(member_list.json()) == 1
    assert member_list.json()[0]["id"] == g1.json()["id"]

    # Stranger lists groups -> sees empty list
    stranger_list = await client.get("/api/v1/groups", headers=auth_headers(user_stranger))
    assert stranger_list.status_code == 200
    assert len(stranger_list.json()) == 0


# ==============================================================================
# 7. Leaving a Group (US-22 / T-35)
# ==============================================================================

async def _group_with_member(client, owner, member):
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Flat 302", "type": "flat"},
        headers=auth_headers(owner),
    )
    group_id = create_resp.json()["id"]
    await client.post(
        "/api/v1/groups/join",
        json={"code": create_resp.json()["joinCode"]},
        headers=auth_headers(member),
    )
    return group_id, create_resp.json()["joinCode"]


@pytest.mark.asyncio
async def test_member_leaves_group_status_left_and_history_kept(client, user_owner, user_member, group_db):
    """US-22: a plain member can leave; membership becomes 'left', never deleted."""
    group_id, _ = await _group_with_member(client, user_owner, user_member)

    resp = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_member.id}",
        headers=auth_headers(user_member),
    )
    assert resp.status_code == 204

    membership = group_db.group_members[(uuid.UUID(group_id), user_member.id)]
    assert membership.status == "left"

    # No longer an active member for the owner
    get_resp = await client.get(f"/api/v1/groups/{group_id}", headers=auth_headers(user_owner))
    assert str(user_member.id) not in [m["userId"] for m in get_resp.json()["members"]]

    # The group disappears from the leaver's list and they lose access
    list_resp = await client.get("/api/v1/groups", headers=auth_headers(user_member))
    assert group_id not in [g["id"] for g in list_resp.json()]
    detail_resp = await client.get(f"/api/v1/groups/{group_id}", headers=auth_headers(user_member))
    assert detail_resp.status_code == 403


@pytest.mark.asyncio
async def test_owner_cannot_leave_group(client, user_owner, group_db):
    """The owner can't leave, so the group always keeps an admin."""
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Flat 302", "type": "flat"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_owner.id}",
        headers=auth_headers(user_owner),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "CANNOT_REMOVE_OWNER"
    assert "cannot leave" in resp.json()["message"]
    assert group_db.group_members[(uuid.UUID(group_id), user_owner.id)].status == "active"


@pytest.mark.asyncio
async def test_stranger_cannot_leave_group_they_are_not_in(client, user_owner, user_stranger, group_db):
    """A non-member passing their own ID is refused and nothing is written."""
    create_resp = await client.post(
        "/api/v1/groups",
        json={"name": "Private Club", "type": "friends"},
        headers=auth_headers(user_owner),
    )
    group_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_stranger.id}",
        headers=auth_headers(user_stranger),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "GROUP_ACCESS_DENIED"
    assert (uuid.UUID(group_id), user_stranger.id) not in group_db.group_members


@pytest.mark.asyncio
async def test_member_cannot_leave_twice(client, user_owner, user_member):
    """After leaving, the person is no longer an active member, so a second leave is refused."""
    group_id, _ = await _group_with_member(client, user_owner, user_member)
    first = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_member.id}",
        headers=auth_headers(user_member),
    )
    assert first.status_code == 204
    second = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_member.id}",
        headers=auth_headers(user_member),
    )
    assert second.status_code == 403


@pytest.mark.asyncio
async def test_member_who_left_can_rejoin_with_code(client, user_owner, user_member, group_db):
    """Leaving keeps the row; joining again with a valid code reactivates it."""
    group_id, join_code = await _group_with_member(client, user_owner, user_member)
    await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_member.id}",
        headers=auth_headers(user_member),
    )

    rejoin = await client.post(
        "/api/v1/groups/join",
        json={"code": join_code},
        headers=auth_headers(user_member),
    )
    assert rejoin.status_code == 200
    membership = group_db.group_members[(uuid.UUID(group_id), user_member.id)]
    assert membership.status == "active"
    assert membership.role == "member"


@pytest.mark.asyncio
async def test_admin_removing_someone_else_still_marks_removed(client, user_owner, user_member, group_db):
    """Removal by an admin is unchanged: status 'removed', not 'left'."""
    group_id, _ = await _group_with_member(client, user_owner, user_member)
    resp = await client.delete(
        f"/api/v1/groups/{group_id}/members/{user_member.id}",
        headers=auth_headers(user_owner),
    )
    assert resp.status_code == 204
    assert group_db.group_members[(uuid.UUID(group_id), user_member.id)].status == "removed"
