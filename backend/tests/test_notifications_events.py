"""Notification events for shared expenses and settlements (US-38 / T-36).

Reuses the fake shared-expense / settlement database; notifications go to the
in-memory store from tests/notification_fakes.py.
"""

from __future__ import annotations

import pytest

from tests import notification_fakes as fakes
from tests import test_settlements as s

# Re-use the settlement fixtures (fake DB with settlements, users, group, headers, client).
expense_db = s.expense_db
fake_session = s.fake_session
user_a = s.user_a
user_b = s.user_b
user_c = s.user_c
sample_category = s.sample_category
sample_group = s.sample_group
auth_headers_user_a = s.auth_headers_user_a
auth_headers_user_b = s.auth_headers_user_b
client = s.client


def sent(kind: str) -> list:
    return [n for n in fakes.get_emitted_notifications() if n.kind == kind]


@pytest.mark.asyncio
async def test_settlement_recorded_notifies_the_other_party_not_the_actor(
    client, sample_group, sample_category, user_a, user_b, auth_headers_user_a, auth_headers_user_b
):
    await s.add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    fakes.clear_emitted_notifications()

    resp = await s.settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=100000)
    assert resp.status_code == 201, resp.text
    got = sent("settlement_recorded")
    assert [n.user_id for n in got] == [str(user_a.id)]
    assert got[0].payload["amount_paise"] == 100000
    assert "₹1,000" in got[0].body


@pytest.mark.asyncio
async def test_admin_who_is_the_payee_notifies_only_the_payer(
    client, sample_group, sample_category, user_a, user_c, auth_headers_user_a
):
    await s.add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    fakes.clear_emitted_notifications()
    resp = await s.settle(client, sample_group, auth_headers_user_a, user_c, user_a, amount_paise=100)
    assert resp.status_code == 201
    assert [n.user_id for n in sent("settlement_recorded")] == [str(user_c.id)]


@pytest.mark.asyncio
async def test_rejected_settlement_sends_nothing(
    client, sample_group, sample_category, user_a, user_b, auth_headers_user_a, auth_headers_user_b
):
    await s.add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    fakes.clear_emitted_notifications()
    resp = await s.settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=999999999)
    assert resp.status_code >= 400
    assert fakes.get_emitted_notifications() == []


@pytest.mark.asyncio
async def test_settlement_rollback_sends_nothing(
    client, sample_group, sample_category, user_a, user_b,
    auth_headers_user_a, auth_headers_user_b, fake_session,
):
    await s.add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    fakes.clear_emitted_notifications()
    fake_session.fail_on_commit = True
    with pytest.raises(RuntimeError, match="Simulated database failure"):
        await s.settle(client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=1000)
    assert fakes.get_emitted_notifications() == []


@pytest.mark.asyncio
async def test_settlement_idempotent_retry_notifies_once(
    client, sample_group, sample_category, user_a, user_b, auth_headers_user_a, auth_headers_user_b
):
    await s.add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    fakes.clear_emitted_notifications()
    for _ in range(2):
        resp = await s.settle(
            client, sample_group, auth_headers_user_b, user_b, user_a, amount_paise=1000, key="k-1"
        )
        assert resp.status_code == 201
    assert len(sent("settlement_recorded")) == 1


@pytest.mark.asyncio
async def test_expense_created_notifies_other_members_only(
    client, sample_group, sample_category, user_a, user_b, user_c, auth_headers_user_a
):
    await s.add_expense(client, sample_group, sample_category, auth_headers_user_a, 300000)
    assert {n.user_id for n in sent("group_expense_created")} == {str(user_b.id), str(user_c.id)}
