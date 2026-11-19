import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.category import Category
from app.models.expense import AuditEvent, Expense, ExpensePayment, ExpenseShare
from app.models.group import (
    Group,
    GroupMember,
    GroupMemberRole,
    GroupMemberStatus,
    GroupType,
)
from app.models.user import User
from tests.notification_fakes import (
    clear_emitted_notifications,
    get_emitted_notifications,
)
from tests.test_shared_expenses import (
    FakeExpenseDB,
    FakeResult,
    FakeSharedExpenseAsyncSession,
)


# ==============================================================================
# Fixtures for Edit & Delete Tests
# Group: Flat Expenses
# user_admin: Group creator & admin
# user_creator: Regular member who created the expense
# user_member: Regular member who did NOT create the expense
# user_stranger: Non-member stranger
# ==============================================================================

@pytest.fixture(autouse=True)
def reset_notifications():
    clear_emitted_notifications()
    yield
    clear_emitted_notifications()


@pytest.fixture
def edit_delete_db():
    db = FakeExpenseDB()
    return db


@pytest.fixture
def user_admin(edit_delete_db):
    user = User(
        id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
        email="admin@example.com",
        name="Admin User",
        hashed_password="hashed_pw",
        is_active=True,
    )
    edit_delete_db.users[user.id] = user
    return user


@pytest.fixture
def user_creator(edit_delete_db):
    user = User(
        id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
        email="creator@example.com",
        name="Creator Member",
        hashed_password="hashed_pw",
        is_active=True,
    )
    edit_delete_db.users[user.id] = user
    return user


@pytest.fixture
def user_member(edit_delete_db):
    user = User(
        id=uuid.UUID("33333333-3333-3333-3333-333333333333"),
        email="member@example.com",
        name="Regular Member",
        hashed_password="hashed_pw",
        is_active=True,
    )
    edit_delete_db.users[user.id] = user
    return user


@pytest.fixture
def user_stranger(edit_delete_db):
    user = User(
        id=uuid.UUID("99999999-9999-9999-9999-999999999999"),
        email="stranger@example.com",
        name="Stranger User",
        hashed_password="hashed_pw",
        is_active=True,
    )
    edit_delete_db.users[user.id] = user
    return user


@pytest.fixture
def sample_category(edit_delete_db):
    cat = Category(
        id=uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        name="Groceries & Food",
        is_default=True,
    )
    edit_delete_db.categories[cat.id] = cat
    return cat


@pytest.fixture
def alt_category(edit_delete_db):
    cat = Category(
        id=uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
        name="Utilities & Bills",
        is_default=True,
    )
    edit_delete_db.categories[cat.id] = cat
    return cat


@pytest.fixture
def sample_group(edit_delete_db, user_admin, user_creator, user_member):
    now = datetime.now(UTC)
    grp = Group(
        id=uuid.UUID("55555555-5555-5555-5555-555555555555"),
        name="Flat Expenses",
        description="Shared apartment expenses",
        type=GroupType.FLAT.value,
        created_by=user_admin.id,
        created_at=now,
    )
    edit_delete_db.groups[grp.id] = grp

    m1 = GroupMember(
        group_id=grp.id,
        user_id=user_admin.id,
        role=GroupMemberRole.ADMIN.value,
        status=GroupMemberStatus.ACTIVE.value,
        joined_at=now,
    )
    m2 = GroupMember(
        group_id=grp.id,
        user_id=user_creator.id,
        role=GroupMemberRole.MEMBER.value,
        status=GroupMemberStatus.ACTIVE.value,
        joined_at=now + timedelta(seconds=1),
    )
    m3 = GroupMember(
        group_id=grp.id,
        user_id=user_member.id,
        role=GroupMemberRole.MEMBER.value,
        status=GroupMemberStatus.ACTIVE.value,
        joined_at=now + timedelta(seconds=2),
    )
    edit_delete_db.group_members[(grp.id, user_admin.id)] = m1
    edit_delete_db.group_members[(grp.id, user_creator.id)] = m2
    edit_delete_db.group_members[(grp.id, user_member.id)] = m3
    grp.members = [m1, m2, m3]
    grp.creator = user_admin
    return grp


@pytest.fixture
def sample_expense(edit_delete_db, sample_group, sample_category, user_creator, user_admin, user_member):
    """Initial shared expense of ₹60.00 (6000 paise) paid by user_creator, split equally among all 3."""
    now = datetime.now(UTC)
    exp = Expense(
        id=uuid.UUID("77777777-7777-7777-7777-777777777777"),
        group_id=sample_group.id,
        user_id=user_creator.id,
        category_id=sample_category.id,
        amount_minor=6000,
        description="Weekly Groceries",
        expense_date=now.date(),
        version=1,
        created_at=now,
        updated_at=now,
    )
    edit_delete_db.expenses[exp.id] = exp

    # Payment: user_creator paid 6000
    p = ExpensePayment(
        expense_id=exp.id,
        user_id=user_creator.id,
        amount_paise=6000,
    )
    edit_delete_db.expense_payments[(exp.id, user_creator.id)] = p

    # Shares: 2000 each
    s1 = ExpenseShare(
        expense_id=exp.id,
        user_id=user_admin.id,
        amount_paise=2000,
        rule="equal",
    )
    s2 = ExpenseShare(
        expense_id=exp.id,
        user_id=user_creator.id,
        amount_paise=2000,
        rule="equal",
    )
    s3 = ExpenseShare(
        expense_id=exp.id,
        user_id=user_member.id,
        amount_paise=2000,
        rule="equal",
    )
    edit_delete_db.expense_shares[(exp.id, user_admin.id)] = s1
    edit_delete_db.expense_shares[(exp.id, user_creator.id)] = s2
    edit_delete_db.expense_shares[(exp.id, user_member.id)] = s3

    exp.payments = [p]
    exp.shares = [s1, s2, s3]

    # Creation audit event
    audit_init = AuditEvent(
        id=uuid.uuid4(),
        actor_id=user_creator.id,
        entity_type="expense",
        entity_id=exp.id,
        action="expense_created",
        before_after=json.dumps({"amount_paise": 6000, "description": "Weekly Groceries"}),
        created_at=now,
    )
    edit_delete_db.audit_events[audit_init.id] = audit_init
    return exp


@pytest.fixture
def auth_headers_admin(user_admin):
    token = create_access_token(user_id=user_admin.id, email=user_admin.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_creator(user_creator):
    token = create_access_token(user_id=user_creator.id, email=user_creator.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_member(user_member):
    token = create_access_token(user_id=user_member.id, email=user_member.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_stranger(user_stranger):
    token = create_access_token(user_id=user_stranger.id, email=user_stranger.email)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(edit_delete_db):
    fake_session = FakeSharedExpenseAsyncSession(edit_delete_db)

    async def override_get_db():
        yield fake_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    ac = AsyncClient(transport=transport, base_url="http://testserver")
    yield ac
    app.dependency_overrides.clear()


# ==============================================================================
# 1. Creator and Admin Edit/Delete Permission Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_creator_can_edit_expense(
    client, sample_group, sample_expense, auth_headers_creator, edit_delete_db
):
    """US-23 AC1: Original expense creator can edit the expense."""
    payload = {
        "description": "Weekly Groceries & Organic Fruit",
        "amount_paise": 9000,
        "split_mode": "equal",
        "version": 1,
    }
    response = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json=payload,
        headers=auth_headers_creator,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["description"] == "Weekly Groceries & Organic Fruit"
    assert data["amountPaise"] == 9000
    assert data["version"] == 2

    # Verify actual database state
    db_exp = edit_delete_db.expenses[sample_expense.id]
    assert db_exp.description == "Weekly Groceries & Organic Fruit"
    assert db_exp.amount_minor == 9000
    assert db_exp.version == 2


@pytest.mark.asyncio
async def test_group_admin_can_edit_expense(
    client, sample_group, sample_expense, auth_headers_admin, edit_delete_db
):
    """US-23 AC1: Group admin can edit an expense created by another member."""
    payload = {
        "description": "Admin Adjusted Groceries",
        "amount_paise": 7500,
        "version": 1,
    }
    response = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json=payload,
        headers=auth_headers_admin,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["description"] == "Admin Adjusted Groceries"
    assert data["amountPaise"] == 7500
    assert data["version"] == 2

    # Verify database state
    db_exp = edit_delete_db.expenses[sample_expense.id]
    assert db_exp.description == "Admin Adjusted Groceries"
    assert db_exp.amount_minor == 7500


@pytest.mark.asyncio
async def test_creator_can_delete_expense(
    client, sample_group, sample_expense, auth_headers_creator, edit_delete_db
):
    """US-23 AC1: Original expense creator can delete the expense."""
    response = await client.delete(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}?version=1",
        headers=auth_headers_creator,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["deleted"] is True
    assert data["version"] == 2

    # Verify actual database state: soft-deleted with deleted_at preserved
    db_exp = edit_delete_db.expenses[sample_expense.id]
    assert db_exp.deleted_at is not None
    assert db_exp.version == 2


@pytest.mark.asyncio
async def test_group_admin_can_delete_expense(
    client, sample_group, sample_expense, auth_headers_admin, edit_delete_db
):
    """US-23 AC1: Group admin can delete an expense created by another member."""
    response = await client.delete(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        headers=auth_headers_admin,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["deleted"] is True
    assert data["version"] == 2

    # Verify database state
    db_exp = edit_delete_db.expenses[sample_expense.id]
    assert db_exp.deleted_at is not None


# ==============================================================================
# 2. Unauthorized Member and Non-Member Access Rejection Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_unauthorized_group_member_cannot_edit_expense(
    client, sample_group, sample_expense, auth_headers_member, edit_delete_db
):
    """Non-creator regular member is rejected with 403 when trying to edit."""
    payload = {
        "description": "Unauthorized Modification",
        "amount_paise": 1000,
        "version": 1,
    }
    response = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json=payload,
        headers=auth_headers_member,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "INSUFFICIENT_PERMISSIONS"

    # Verify DB was NOT mutated
    db_exp = edit_delete_db.expenses[sample_expense.id]
    assert db_exp.description == "Weekly Groceries"
    assert db_exp.amount_minor == 6000
    assert db_exp.version == 1


@pytest.mark.asyncio
async def test_unauthorized_group_member_cannot_delete_expense(
    client, sample_group, sample_expense, auth_headers_member, edit_delete_db
):
    """Non-creator regular member is rejected with 403 when trying to delete."""
    response = await client.delete(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        headers=auth_headers_member,
    )
    assert response.status_code == 403
    assert response.json()["code"] == "INSUFFICIENT_PERMISSIONS"

    # Verify DB was NOT deleted
    db_exp = edit_delete_db.expenses[sample_expense.id]
    assert db_exp.deleted_at is None
    assert db_exp.version == 1


@pytest.mark.asyncio
async def test_non_member_stranger_cannot_edit_or_delete(
    client, sample_group, sample_expense, auth_headers_stranger
):
    """Stranger non-member is rejected with 403 GROUP_ACCESS_DENIED."""
    # Edit attempt
    edit_resp = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json={"description": "Hacked", "version": 1},
        headers=auth_headers_stranger,
    )
    assert edit_resp.status_code == 403
    assert edit_resp.json()["code"] == "GROUP_ACCESS_DENIED"

    # Delete attempt
    del_resp = await client.delete(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        headers=auth_headers_stranger,
    )
    assert del_resp.status_code == 403
    assert del_resp.json()["code"] == "GROUP_ACCESS_DENIED"


# ==============================================================================
# 3. Balance Recalculation Tests (Edit and Deletion)
# ==============================================================================

@pytest.mark.asyncio
async def test_balance_recalculation_after_edit(
    client, sample_group, sample_expense, auth_headers_creator, user_admin, user_creator, user_member, edit_delete_db
):
    """US-23 AC2: Balances are recalculated immediately after an edit.

    Initial state:
      user_creator paid 6000; shares: admin 2000, creator 2000, member 2000
      Net positions: creator: +4000, admin: -2000, member: -2000
    Edit to 9000 paise (equal split among same 3):
      Each share: 3000
      Net positions: creator: +6000, admin: -3000, member: -3000
    """
    payload = {
        "amount_paise": 9000,
        "split_mode": "equal",
        "version": 1,
    }
    response = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json=payload,
        headers=auth_headers_creator,
    )
    assert response.status_code == 200

    # Query group balances endpoint to verify recalculated net positions
    bal_resp = await client.get(
        f"/api/v1/groups/{sample_group.id}/balances",
        headers=auth_headers_creator,
    )
    assert bal_resp.status_code == 200
    balances = bal_resp.json()["net_positions"]

    assert balances[str(user_creator.id)] == 6000
    assert balances[str(user_admin.id)] == -3000
    assert balances[str(user_member.id)] == -3000
    # Zero-sum invariant
    assert sum(balances.values()) == 0


@pytest.mark.asyncio
async def test_balance_recalculation_after_deletion(
    client, sample_group, sample_expense, auth_headers_creator, user_admin, user_creator, user_member
):
    """US-23 AC2: Balances are recalculated immediately after expense deletion.

    Initial state:
      Net positions: creator: +4000, admin: -2000, member: -2000
    After deleting this sole expense:
      All balances return to 0 (completely settled / empty).
    """
    del_resp = await client.delete(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        headers=auth_headers_creator,
    )
    assert del_resp.status_code == 200
    del_data = del_resp.json()
    del_balances = del_data.get("netPositions") or del_data.get("net_positions") or {}
    assert del_balances == {} or all(v == 0 for v in del_balances.values())

    # Verify through balances endpoint
    bal_resp = await client.get(
        f"/api/v1/groups/{sample_group.id}/balances",
        headers=auth_headers_creator,
    )
    assert bal_resp.status_code == 200
    bal_json = bal_resp.json()
    balances = bal_json.get("net_positions") or bal_json.get("netPositions") or {}
    assert all(v == 0 for v in balances.values())


# ==============================================================================
# 4. Expense Share Validation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_edit_expense_unbalanced_shares_rejected(
    client, sample_group, sample_expense, auth_headers_creator, user_admin, user_creator
):
    """Exact split whose shares do not sum to total is strictly rejected."""
    payload = {
        "amount_paise": 5000,
        "split_mode": "exact",
        "participant_user_ids": [str(user_admin.id), str(user_creator.id)],
        "split_weights": {
            str(user_admin.id): 2000,
            str(user_creator.id): 2000,  # Sum = 4000 != 5000
        },
        "version": 1,
    }
    response = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json=payload,
        headers=auth_headers_creator,
    )
    assert response.status_code == 400
    assert response.json()["code"] in ("INVALID_SPLIT", "UNBALANCED_SHARES")


@pytest.mark.asyncio
async def test_edit_expense_external_participant_rejected(
    client, sample_group, sample_expense, auth_headers_creator, user_stranger
):
    """Adding a participant who is not an active member of the group is rejected."""
    payload = {
        "participant_user_ids": [str(user_stranger.id)],
        "version": 1,
    }
    response = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json=payload,
        headers=auth_headers_creator,
    )
    assert response.status_code == 400
    assert response.json()["code"] == "PARTICIPANT_NOT_MEMBER"


# ==============================================================================
# 5. Transaction History & Audit Logs Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_audit_logs_recorded_with_before_and_after_state(
    client, sample_group, sample_expense, auth_headers_creator, edit_delete_db
):
    """US-23 AC4: Edits and deletions record before-and-after states in AuditEvent."""
    # 1. Edit
    await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json={"description": "Updated Title", "amount_paise": 7500, "version": 1},
        headers=auth_headers_creator,
    )

    update_audits = [
        a for a in edit_delete_db.audit_events.values() if a.action == "expense_updated"
    ]
    assert len(update_audits) == 1
    edit_audit = update_audits[0]
    payload = json.loads(edit_audit.before_after)
    assert "before" in payload
    assert "after" in payload
    assert payload["before"]["amount_paise"] == 6000
    assert payload["after"]["amount_paise"] == 7500
    assert payload["after"]["description"] == "Updated Title"
    assert "balances" in payload["before"]
    assert "balances" in payload["after"]

    # 2. Delete
    await client.delete(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}?version=2",
        headers=auth_headers_creator,
    )

    delete_audits = [
        a for a in edit_delete_db.audit_events.values() if a.action == "expense_deleted"
    ]
    assert len(delete_audits) == 1
    del_audit = delete_audits[0]
    del_payload = json.loads(del_audit.before_after)
    assert del_payload["after"]["deleted"] is True
    assert "balances" in del_payload["after"]

    # 3. Verify group history endpoint retrieves audit logs even after deletion
    history_resp = await client.get(
        f"/api/v1/groups/{sample_group.id}/history",
        headers=auth_headers_creator,
    )
    assert history_resp.status_code == 200
    history = history_resp.json()
    actions = [h["action"] for h in history]
    assert "expense_created" in actions
    assert "expense_updated" in actions
    assert "expense_deleted" in actions


# ==============================================================================
# 6. Notifications After Successful Operations Only Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_notifications_emitted_to_all_group_members_on_edit_and_delete(
    client, sample_group, sample_expense, auth_headers_creator, user_admin, user_creator, user_member
):
    """US-23 AC3: Other group members are notified after commit on edit and deletion; the actor is not."""
    clear_emitted_notifications()

    # 1. Edit
    edit_resp = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json={"description": "Notified Edit", "version": 1},
        headers=auth_headers_creator,
    )
    assert edit_resp.status_code == 200

    notifs_edit = get_emitted_notifications()
    # Expect 2 notifications: every active member except the actor (the creator)
    assert len(notifs_edit) == 2
    notified_users = {n.user_id for n in notifs_edit}
    assert str(user_admin.id) in notified_users
    assert str(user_creator.id) not in notified_users
    assert str(user_member.id) in notified_users
    assert all(n.kind == "group_expense_updated" for n in notifs_edit)

    clear_emitted_notifications()

    # 2. Delete
    del_resp = await client.delete(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}?version=2",
        headers=auth_headers_creator,
    )
    assert del_resp.status_code == 200

    notifs_del = get_emitted_notifications()
    assert len(notifs_del) == 2
    del_users = {n.user_id for n in notifs_del}
    assert str(user_admin.id) in del_users
    assert str(user_creator.id) not in del_users
    assert str(user_member.id) in del_users
    assert all(n.kind == "group_expense_deleted" for n in notifs_del)

@pytest.mark.asyncio
async def test_second_edit_of_the_same_expense_notifies_again_with_versioned_key(
    client, sample_group, sample_expense, auth_headers_creator, user_admin, user_member
):
    """The new version is part of the dedupe key, so legitimate repeat edits are not suppressed."""
    clear_emitted_notifications()
    for version, text in ((1, "First edit"), (2, "Second edit")):
        resp = await client.patch(
            f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
            json={"description": text, "version": version},
            headers=auth_headers_creator,
        )
        assert resp.status_code == 200
    notifs = get_emitted_notifications()
    assert len(notifs) == 4  # two recipients (admin, member) x two edits
    assert {n.ref for n in notifs} == {f"{sample_expense.id}:v2", f"{sample_expense.id}:v3"}



# ==============================================================================
# 7. Optimistic Concurrency and Stale Version Rejection Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_stale_version_rejected_with_409_conflict(
    client, sample_group, sample_expense, auth_headers_creator
):
    """Reject stale updates with 409 CONFLICT rather than overwriting."""
    # Record starts at version 1; supply stale version 0
    payload = {
        "description": "Stale Update",
        "version": 0,
    }
    response = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json=payload,
        headers=auth_headers_creator,
    )
    assert response.status_code == 409
    assert response.json()["code"] == "VERSION_CONFLICT"

    # Test If-Match header with stale version
    response_header = await client.patch(
        f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
        json={"description": "Stale Header Update"},
        headers={**auth_headers_creator, "If-Match": '"0"'},
    )
    assert response_header.status_code == 409
    assert response_header.json()["code"] == "VERSION_CONFLICT"


# ==============================================================================
# 8. Database Rollback on Failure Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_database_rollback_on_failure_leaves_no_partial_writes(
    client, sample_group, sample_expense, auth_headers_creator, edit_delete_db
):
    """Simulated failure during save triggers full rollback; no notifications or audit events written."""
    clear_emitted_notifications()

    # Create session with simulated failure
    failing_session = FakeSharedExpenseAsyncSession(edit_delete_db)
    failing_session.fail_on_commit = True

    async def override_failing_db():
        yield failing_session

    app.dependency_overrides[get_db] = override_failing_db

    with pytest.raises(RuntimeError, match="Simulated database failure"):
        await client.patch(
            f"/api/v1/groups/{sample_group.id}/expenses/{sample_expense.id}",
            json={"description": "This Must Fail", "amount_paise": 9999, "version": 1},
            headers=auth_headers_creator,
        )

    # Verify database state was preserved (NOT mutated)
    db_exp = edit_delete_db.expenses[sample_expense.id]
    assert db_exp.description == "Weekly Groceries"
    assert db_exp.amount_minor == 6000
    assert db_exp.version == 1

    # Zero audit events added for this failed operation
    assert not any(a.action == "expense_updated" for a in edit_delete_db.audit_events.values())

    # ZERO notifications emitted because transaction failed
    assert len(get_emitted_notifications()) == 0
