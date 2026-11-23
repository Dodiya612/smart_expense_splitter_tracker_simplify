"""Recurring expenses (US-14 / T-44): rules, date maths and the generator.

Rules
-----
A rule stores a schedule (frequency, start date, optional end date, next run date,
status) and the expense template it creates. Only the owner can see or change it
(``RecurringRulePolicy``: anyone else gets 404). Every change is one transaction with
its audit event (and, on create, its idempotency record).

Dates
-----
All "today" decisions use Asia/Kolkata. Occurrence n is computed from ``start_date``
(never from the previous occurrence), so a monthly rule on the 31st falls on the last
day of shorter months and returns to the 31st afterwards (31 Jan -> 29 Feb -> 31 Mar),
and a yearly rule on 29 Feb falls on 28 Feb in common years. An occurrence is due from
00:00 on its date; its "upcoming" notice is sent from 00:00 the day before (24 hours).

Generator and duplicate safety
------------------------------
``run_due()`` handles each due occurrence in its own transaction:

1. ``SELECT ... FOR UPDATE`` on the rule serialises every writer of that rule (hourly
   task, startup catch-up, login catch-up, concurrent runs);
2. under the lock it re-checks that the rule is active and that ``next_run_date`` is
   still the date it expects (otherwise another run already handled it);
3. it stages the ``recurring_occurrences`` row (UNIQUE rule_id + occurrence_date) and
   moves ``next_run_date`` forward, then calls the EXISTING create service with a
   pre-assigned expense id; that service's single COMMIT writes the expense, its
   payments/shares/audit, the occurrence row and the rule update together.

If anything slips past the lock, the UNIQUE key fails the whole transaction, so an
expense can never exist without its occurrence row, and an occurrence row is never
written twice. The generator only ever looks at occurrence rows, never at expenses, so
deleting a generated expense never makes it come back.

A group occurrence the create service rejects (payer or participant no longer an active
member, owner left, group gone, category no longer usable) is recorded as ``skipped``
with that error code, ``next_run_date`` moves on, and the owner is notified.

Notifications are post-commit and deduplicated by the notification centre's unique
``(user_id, dedupe_key)``; a notice failure never undoes a saved expense.
"""

from __future__ import annotations

import asyncio
import calendar
import contextlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import GroupPolicy, RecurringRulePolicy
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.expense import AuditEvent
from app.models.group import Group, GroupMemberStatus
from app.models.recurring import RecurringOccurrence, RecurringRule
from app.models.user import User
from app.schemas.expense import ExpenseCreate
from app.schemas.recurring import (
    RecurringOccurrenceResponse,
    RecurringRuleCreate,
    RecurringRuleResponse,
    RecurringRuleUpdate,
)
from app.schemas.shared_expense import SharedExpenseCreateRequest
from app.services import expenses as expense_service
from app.services import idempotency, notifications, shared_expense_service
from app.services.group_service import get_group_or_404
from app.services.settlement_service import IST

logger = logging.getLogger("app.recurring")

ACTIVE, PAUSED, CANCELLED = "active", "paused", "cancelled"
MAX_START_AHEAD_DAYS = 366
TEMPLATE_FIELDS = ("amount_paise", "category_id", "description", "notes", "merchant", "payment_mode", "split")

# Plain-language reasons for the "skipped" notice; the stored reason is the error code.
SKIP_REASON_TEXT: dict[str, str] = {
    "PAYER_NOT_MEMBER": "the payer is no longer an active member of the group",
    "PARTICIPANT_NOT_MEMBER": "a participant is no longer an active member of the group",
    "GROUP_ACCESS_DENIED": "you are no longer an active member of the group",
    "GROUP_NOT_FOUND": "the group no longer exists",
    "NO_ACTIVE_MEMBERS": "the group has no active members",
    "INVALID_CATEGORY": "the category is no longer available",
    "CATEGORY_NOT_FOUND": "the category is no longer available",
}


# ==============================================================================
# Clock (replaced by tests)
# ==============================================================================


def _now() -> datetime:
    return datetime.now(UTC)


def today_in_kolkata(now: datetime | None = None) -> date:
    return (now or _now()).astimezone(IST).date()


# ==============================================================================
# Date maths (pure)
# ==============================================================================


def _add_months(anchor: date, months: int) -> date:
    """``anchor`` moved by ``months``, its day clamped to the length of the target month."""
    year, month0 = divmod(anchor.month - 1 + months, 12)
    year += anchor.year
    day = min(anchor.day, calendar.monthrange(year, month0 + 1)[1])
    return date(year, month0 + 1, day)


def occurrence_on_or_after(start: date, frequency: str, day: date) -> date:
    """The first scheduled date of a rule that is on or after ``day``."""
    if day <= start:
        return start
    if frequency == "daily":
        return day
    if frequency == "weekly":
        weeks = -(-(day - start).days // 7)  # ceiling division
        return start + timedelta(days=7 * weeks)
    if frequency == "monthly":
        months = (day.year - start.year) * 12 + (day.month - start.month)
        step = 1
    elif frequency == "yearly":
        months = (day.year - start.year) * 12
        step = 12
    else:
        raise ValueError(f"Unknown frequency: {frequency}")
    candidate = _add_months(start, months)
    return candidate if candidate >= day else _add_months(start, months + step)


def next_occurrence_after(start: date, frequency: str, day: date) -> date:
    return occurrence_on_or_after(start, frequency, day + timedelta(days=1))


def within_end(day: date | None, end_date: date | None) -> date | None:
    """``day`` unless it falls after the rule's end date (then there is no occurrence)."""
    if day is None or (end_date is not None and day > end_date):
        return None
    return day


def schedule_between(
    start: date, frequency: str, end_date: date | None, first: date, last: date
) -> list[date]:
    """Every scheduled date in [first, last] (inclusive), honouring the end date."""
    dates: list[date] = []
    current = within_end(occurrence_on_or_after(start, frequency, first), end_date)
    while current is not None and current <= last:
        dates.append(current)
        current = within_end(next_occurrence_after(start, frequency, current), end_date)
    return dates


def _following(rule: RecurringRule, day: date) -> date | None:
    return within_end(next_occurrence_after(rule.start_date, rule.frequency, day), rule.end_date)


# ==============================================================================
# State transitions (pure; the caller holds the row lock and commits)
# ==============================================================================


def _conflict(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"code": code, "message": message})


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail={"code": code, "message": message})


def _ensure_not_cancelled(rule: RecurringRule) -> None:
    if rule.status == CANCELLED:
        raise _conflict("RULE_CANCELLED", "This recurring rule is cancelled and can no longer be changed.")


def apply_pause(rule: RecurringRule, now: datetime) -> None:
    """active -> paused. No occurrence and no notice is produced while paused."""
    _ensure_not_cancelled(rule)
    if rule.status != ACTIVE:
        raise _conflict("RULE_NOT_ACTIVE", "Only an active rule can be paused.")
    rule.status = PAUSED
    rule.paused_at = now
    rule.updated_at = now


def apply_resume(rule: RecurringRule, now: datetime) -> None:
    """paused -> active, continuing from the next scheduled date on or after today.

    Dates that fell inside the paused period are not back-filled.
    """
    _ensure_not_cancelled(rule)
    if rule.status != PAUSED:
        raise _conflict("RULE_NOT_PAUSED", "Only a paused rule can be resumed.")
    if rule.next_run_date is not None:
        resume_from = max(today_in_kolkata(now), rule.next_run_date)
        rule.next_run_date = within_end(
            occurrence_on_or_after(rule.start_date, rule.frequency, resume_from), rule.end_date
        )
    rule.status = ACTIVE
    rule.paused_at = None
    rule.updated_at = now


def apply_cancel(rule: RecurringRule, now: datetime) -> None:
    """active/paused -> cancelled. Final: nothing is generated afterwards."""
    _ensure_not_cancelled(rule)
    rule.status = CANCELLED
    rule.next_run_date = None
    rule.cancelled_at = now
    rule.updated_at = now


def apply_end_date(
    rule: RecurringRule, end_date: date | None, today: date, last_handled: date | None
) -> None:
    """Change the end date; only future occurrences are affected.

    Shortening drops scheduled dates after the new end. Extending a rule that had already
    ended continues from the next scheduled date on or after today (no back-fill).
    """
    if end_date is not None and end_date < rule.start_date:
        raise _bad_request("INVALID_END_DATE", "end_date must be on or after start_date.")
    rule.end_date = end_date
    if rule.next_run_date is not None:
        rule.next_run_date = within_end(rule.next_run_date, end_date)
        return
    after = last_handled + timedelta(days=1) if last_handled else rule.start_date
    rule.next_run_date = within_end(
        occurrence_on_or_after(rule.start_date, rule.frequency, max(after, today)), end_date
    )


def notice_date(rule: RecurringRule, today: date) -> date | None:
    """The occurrence whose 24-hour notice is due now, if any (active rules only)."""
    if rule.status != ACTIVE or rule.next_run_date is None:
        return None
    return rule.next_run_date if rule.next_run_date == today + timedelta(days=1) else None


def due_date(rule: RecurringRule, today: date) -> date | None:
    """The next occurrence to create now, if any (active rules only)."""
    if rule.status != ACTIVE or rule.next_run_date is None or rule.next_run_date > today:
        return None
    return rule.next_run_date


# ==============================================================================
# Templates
# ==============================================================================


def personal_expense_request(rule: RecurringRule, day: date) -> ExpenseCreate:
    return ExpenseCreate.model_validate(
        {
            "amount_paise": rule.amount_paise,
            "description": rule.description,
            "category_id": rule.category_id,
            "expense_date": day,
            "notes": rule.notes,
            "merchant": rule.merchant,
            "payment_mode": rule.payment_mode,
        }
    )


def shared_expense_request(
    template: dict[str, Any], split: dict[str, Any] | None, day: date | None
) -> SharedExpenseCreateRequest:
    """The exact request the shared-expense create service receives for an occurrence."""
    data: dict[str, Any] = {
        "amount_paise": template["amount_paise"],
        "description": template["description"],
        "category_id": template["category_id"],
        "notes": template.get("notes"),
        "merchant": template.get("merchant"),
        "payment_mode": template.get("payment_mode"),
        **(split or {}),
    }
    if day is not None:
        data["expense_date"] = day
    return SharedExpenseCreateRequest.model_validate(data)


def _template_of(rule: RecurringRule) -> dict[str, Any]:
    return {name: getattr(rule, name) for name in TEMPLATE_FIELDS}


def _validation_error(exc: ValidationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={
            "code": "VALIDATION_ERROR",
            "message": "The expense template is not a valid expense.",
            "detail": [
                {"loc": [str(p) for p in err.get("loc", ())], "msg": str(err.get("msg", "")), "type": str(err.get("type", ""))}
                for err in exc.errors()
            ],
        },
    )


async def _owner_group_or_404(db: AsyncSession, owner: User, group_id: uuid.UUID) -> Group:
    """The group, if the owner is an active member; otherwise the same 404 for everyone."""
    group = await get_group_or_404(db, group_id)
    members = {m.user_id for m in group.members if m.status == GroupMemberStatus.ACTIVE.value}
    GroupPolicy.authorize_member_or_404(owner, group.id, members)
    return group


async def validate_template(
    db: AsyncSession, owner: User, group_id: uuid.UUID | None, template: dict[str, Any]
) -> None:
    """Reject a template the create services would reject when an occurrence is due.

    Personal: the ExpenseCreate schema and the owner's category access. Group: the
    SharedExpenseCreateRequest schema plus the shared-expense service's own payer,
    participant and ledger-allocation rules (``resolve_split``) against the current
    active members.
    """
    await expense_service.validate_category_ownership(db, owner.id, template["category_id"])
    try:
        if group_id is None:
            ExpenseCreate.model_validate(
                {k: template[k] for k in ("amount_paise", "description", "category_id", "notes", "merchant", "payment_mode")}
            )
            return
        request = shared_expense_request(template, template.get("split"), None)
    except ValidationError as exc:
        raise _validation_error(exc) from exc
    group = await _owner_group_or_404(db, owner, group_id)
    shared_expense_service.resolve_split(group, owner, request)


# ==============================================================================
# Rule CRUD (request session; one transaction per change)
# ==============================================================================


def to_response(rule: RecurringRule) -> RecurringRuleResponse:
    return RecurringRuleResponse.model_validate(rule)


def _audit(db: AsyncSession, actor_id: uuid.UUID, rule: RecurringRule, action: str, changes: dict[str, Any]) -> None:
    db.add(
        AuditEvent(
            id=uuid.uuid4(),
            actor_id=actor_id,
            entity_type="recurring_rule",
            entity_id=rule.id,
            action=action,
            before_after=json.dumps(changes, default=str),
            created_at=_now(),
        )
    )


async def _load_owned(
    db: AsyncSession, owner: User, rule_id: uuid.UUID, *, for_update: bool = False
) -> RecurringRule:
    stmt = RecurringRulePolicy.scope_query(select(RecurringRule).where(RecurringRule.id == rule_id), owner.id)
    if for_update:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    rule = (await db.execute(stmt)).scalar_one_or_none()
    return RecurringRulePolicy.authorize(owner, rule)


async def create_rule(
    db: AsyncSession,
    owner: User,
    payload: RecurringRuleCreate,
    idempotency_key: str | None = None,
) -> tuple[RecurringRuleResponse, bool]:
    """Create a rule. Returns (rule, is_replay). The first occurrence is ``start_date``."""
    key, hashed, replay = await idempotency.prepare(
        db, owner.id, idempotency_key, "recurring_rule_create", payload.group_id, payload, RecurringRuleResponse
    )
    if replay is not None:
        return replay, True

    now = _now()
    today = today_in_kolkata(now)
    if payload.start_date < today:
        raise _bad_request("START_DATE_IN_PAST", f"start_date cannot be before today ({today}).")
    if payload.start_date > today + timedelta(days=MAX_START_AHEAD_DAYS):
        raise _bad_request("START_DATE_TOO_FAR", f"start_date must be within {MAX_START_AHEAD_DAYS} days.")

    split = payload.split.model_dump(mode="json", exclude_none=True) if payload.split is not None else None
    template: dict[str, Any] = {
        "amount_paise": payload.amount_paise,
        "category_id": payload.category_id,
        "description": payload.description,
        "notes": payload.notes,
        "merchant": payload.merchant,
        "payment_mode": payload.payment_mode,
        "split": split,
    }
    await validate_template(db, owner, payload.group_id, template)

    rule = RecurringRule(
        id=uuid.uuid4(),
        owner_id=owner.id,
        group_id=payload.group_id,
        frequency=payload.frequency,
        start_date=payload.start_date,
        end_date=payload.end_date,
        next_run_date=payload.start_date,
        status=ACTIVE,
        created_at=now,
        updated_at=now,
        paused_at=None,
        cancelled_at=None,
        **template,
    )
    db.add(rule)
    response = to_response(rule)
    _audit(db, owner.id, rule, "recurring_rule_created", response.model_dump(mode="json"))
    if key and hashed:
        idempotency.stage_record(db, owner.id, key, hashed, response, rule.id)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        replay = await idempotency.replay_after_conflict(db, owner.id, key, hashed, RecurringRuleResponse)
        if replay is None:
            raise
        return replay, True
    return response, False


async def list_rules(
    db: AsyncSession, owner: User, rule_status: str | None, limit: int, offset: int
) -> tuple[list[RecurringRuleResponse], int]:
    base = RecurringRulePolicy.scope_query(select(RecurringRule), owner.id)
    count_stmt = RecurringRulePolicy.scope_query(select(func.count(RecurringRule.id)), owner.id)
    if rule_status:
        base = base.where(RecurringRule.status == rule_status)
        count_stmt = count_stmt.where(RecurringRule.status == rule_status)
    total = int((await db.execute(count_stmt)).scalar_one() or 0)
    rows = (
        await db.execute(
            base.order_by(RecurringRule.created_at.desc(), RecurringRule.id.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return [to_response(r) for r in rows], total


async def get_rule(db: AsyncSession, owner: User, rule_id: uuid.UUID) -> RecurringRuleResponse:
    return to_response(await _load_owned(db, owner, rule_id))


async def update_rule(
    db: AsyncSession, owner: User, rule_id: uuid.UUID, payload: RecurringRuleUpdate
) -> RecurringRuleResponse:
    """Edit the template and/or end date. Only future occurrences are affected."""
    rule = await _load_owned(db, owner, rule_id, for_update=True)
    _ensure_not_cancelled(rule)
    fields = payload.model_fields_set
    if "split" in fields and rule.group_id is None:
        raise _bad_request("SPLIT_NOT_ALLOWED", "A personal rule has no split.")

    before = to_response(rule).model_dump(mode="json")
    template = _template_of(rule)
    for name in TEMPLATE_FIELDS:
        if name in fields:
            value = getattr(payload, name)
            if name == "split" and value is not None:
                value = value.model_dump(mode="json", exclude_none=True)
            template[name] = value
    if fields & set(TEMPLATE_FIELDS):
        # Same rules as creating it: the stored template must stay creatable.
        await validate_template(db, owner, rule.group_id, template)
        for name in TEMPLATE_FIELDS:
            setattr(rule, name, template[name])

    now = _now()
    if "end_date" in fields:
        last_handled = (
            await db.execute(
                select(func.max(RecurringOccurrence.occurrence_date)).where(RecurringOccurrence.rule_id == rule.id)
            )
        ).scalar_one_or_none()
        apply_end_date(rule, payload.end_date, today_in_kolkata(now), last_handled)

    rule.updated_at = now
    after = to_response(rule)
    _audit(db, owner.id, rule, "recurring_rule_updated", {"before": before, "after": after.model_dump(mode="json")})
    await db.commit()
    return after


async def change_status(
    db: AsyncSession, owner: User, rule_id: uuid.UUID, action: Literal["pause", "resume", "cancel"]
) -> RecurringRuleResponse:
    rule = await _load_owned(db, owner, rule_id, for_update=True)
    now = _now()
    before = {"status": rule.status, "next_run_date": rule.next_run_date}
    transition, audit_action = _STATUS_ACTIONS[action]
    transition(rule, now)
    after = to_response(rule)
    _audit(
        db, owner.id, rule, audit_action,
        {"before": before, "after": {"status": after.status, "next_run_date": after.next_run_date}},
    )
    await db.commit()
    return after


_STATUS_ACTIONS = {
    "pause": (apply_pause, "recurring_rule_paused"),
    "resume": (apply_resume, "recurring_rule_resumed"),
    "cancel": (apply_cancel, "recurring_rule_cancelled"),
}


async def list_occurrences(
    db: AsyncSession, owner: User, rule_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[RecurringOccurrenceResponse], int]:
    rule = await _load_owned(db, owner, rule_id)
    where = RecurringOccurrence.rule_id == rule.id
    total = int((await db.execute(select(func.count(RecurringOccurrence.id)).where(where))).scalar_one() or 0)
    rows = (
        await db.execute(
            select(RecurringOccurrence)
            .where(where)
            .order_by(RecurringOccurrence.occurrence_date.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return [RecurringOccurrenceResponse.model_validate(r) for r in rows], total


# ==============================================================================
# Notices (post-commit, deduplicated by the notification centre)
# ==============================================================================


def _notice_payload(info: dict[str, Any], day: date) -> dict[str, Any]:
    return {
        "rule_id": str(info["rule_id"]),
        "occurrence_date": day.isoformat(),
        "description": info["description"],
        "amount_paise": info["amount_paise"],
    }


def _rule_info(rule: RecurringRule) -> dict[str, Any]:
    """Plain values captured before a rollback can expire the ORM object."""
    return {
        "rule_id": rule.id,
        "owner_id": rule.owner_id,
        "group_id": rule.group_id,
        "description": rule.description,
        "amount_paise": rule.amount_paise,
    }


async def send_upcoming_notice(info: dict[str, Any], day: date) -> bool:
    """The 24-hour notice for one occurrence; stored at most once per (rule, date)."""
    return await notifications.emit(
        info["owner_id"],
        "recurring_expense_upcoming",
        ref=f"{info['rule_id']}:{day.isoformat()}",
        dedupe_key=f"recurring_expense_upcoming:{info['rule_id']}:{day.isoformat()}",
        payload=_notice_payload(info, day),
        group_id=info["group_id"],
    )


async def send_skipped_notice(info: dict[str, Any], day: date, reason: str) -> bool:
    payload = _notice_payload(info, day)
    payload["reason"] = reason
    payload["reason_text"] = SKIP_REASON_TEXT.get(reason, "it could not be created")
    return await notifications.emit(
        info["owner_id"],
        "recurring_expense_skipped",
        ref=f"{info['rule_id']}:{day.isoformat()}",
        dedupe_key=f"recurring_expense_skipped:{info['rule_id']}:{day.isoformat()}",
        payload=payload,
        group_id=info["group_id"],
    )


# ==============================================================================
# Generator
# ==============================================================================


@dataclass
class RunStats:
    rules: int = 0
    created: int = 0
    skipped: int = 0
    notices: int = 0
    failed_rules: int = 0


Step = Literal["created", "skipped", "advanced", "none", "stop"]


async def _lock_rule(session: AsyncSession, rule_id: uuid.UUID) -> RecurringRule | None:
    stmt = (
        select(RecurringRule)
        .where(RecurringRule.id == rule_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _error_code(exc: HTTPException) -> str:
    detail = exc.detail
    code = detail.get("code") if isinstance(detail, dict) else None
    return str(code or f"HTTP_{exc.status_code}")[:64]


async def _create_next(rule_id: uuid.UUID, today: date) -> tuple[Step, date | None, str | None, dict[str, Any] | None]:
    """Create the rule's next due occurrence in ONE transaction (see module docstring).

    Returns (step, date, skip_reason, rule_info). A rejected template returns
    ("skipped", ...) WITHOUT writing anything; the caller records the skip.
    """
    async with AsyncSessionLocal() as session:
        rule = await _lock_rule(session, rule_id)
        day = due_date(rule, today) if rule is not None else None
        if rule is None or day is None:
            await session.rollback()
            return "none", None, None, None

        info = _rule_info(rule)
        handled = (
            await session.execute(
                select(RecurringOccurrence.id).where(
                    RecurringOccurrence.rule_id == rule.id, RecurringOccurrence.occurrence_date == day
                )
            )
        ).scalar_one_or_none()
        if handled is not None:
            # Already handled (e.g. created and its expense later deleted): never recreate.
            rule.next_run_date = _following(rule, day)
            rule.updated_at = _now()
            await session.commit()
            return "advanced", day, None, info

        expense_id = uuid.uuid4()
        session.add(
            RecurringOccurrence(
                id=uuid.uuid4(),
                rule_id=rule.id,
                occurrence_date=day,
                status="created",
                expense_id=expense_id,
                skip_reason=None,
                created_at=_now(),
            )
        )
        rule.next_run_date = _following(rule, day)
        rule.updated_at = _now()
        try:
            if rule.group_id is None:
                await expense_service.create_expense(
                    session, rule.owner_id, personal_expense_request(rule, day), expense_id=expense_id
                )
            else:
                owner = await session.get(User, rule.owner_id)
                if owner is None:  # pragma: no cover - owner rows cascade-delete their rules
                    await session.rollback()
                    return "skipped", day, "OWNER_NOT_FOUND", info
                request = shared_expense_request(_template_of(rule), rule.split, day)
                await shared_expense_service.create_shared_expense(
                    session, rule.group_id, owner, request, expense_id=expense_id
                )
        except HTTPException as exc:
            await session.rollback()
            code = _error_code(exc)
            if code == "INTEGRITY_ERROR":
                return "stop", day, None, info  # lost a race the lock should prevent; retry later
            return "skipped", day, code, info
        except ValidationError:
            await session.rollback()
            return "skipped", day, "INVALID_TEMPLATE", info
        except IntegrityError:
            await session.rollback()
            return "stop", day, None, info
        return "created", day, None, info


async def _record_skip(rule_id: uuid.UUID, day: date, reason: str) -> bool:
    """Store a skipped occurrence and move past it, if no other run handled it first."""
    async with AsyncSessionLocal() as session:
        rule = await _lock_rule(session, rule_id)
        if rule is None or rule.status != ACTIVE or rule.next_run_date != day:
            await session.rollback()
            return False
        inserted = (
            await session.execute(
                pg_insert(RecurringOccurrence)
                .values(
                    id=uuid.uuid4(),
                    rule_id=rule_id,
                    occurrence_date=day,
                    status="skipped",
                    expense_id=None,
                    skip_reason=reason,
                    created_at=_now(),
                )
                .on_conflict_do_nothing(index_elements=["rule_id", "occurrence_date"])
                .returning(RecurringOccurrence.id)
            )
        ).scalar_one_or_none()
        rule.next_run_date = _following(rule, day)
        rule.updated_at = _now()
        await session.commit()
        return inserted is not None


async def _process_rule(rule_id: uuid.UUID, today: date, limit: int, stats: RunStats) -> None:
    for _ in range(limit):
        step, day, reason, info = await _create_next(rule_id, today)
        if step in ("none", "stop"):
            break
        if step == "created":
            stats.created += 1
        elif step == "skipped" and day is not None and reason is not None and info is not None:
            if await _record_skip(rule_id, day, reason):
                stats.skipped += 1
                await send_skipped_notice(info, day, reason)

    async with AsyncSessionLocal() as session:
        rule = await session.get(RecurringRule, rule_id)
        day = notice_date(rule, today) if rule is not None else None
        info = _rule_info(rule) if rule is not None and day is not None else None
    if day is not None and info is not None and await send_upcoming_notice(info, day):
        stats.notices += 1


async def run_due(*, user_id: uuid.UUID | None = None, now: datetime | None = None) -> RunStats:
    """Create every due occurrence (up to the per-rule limit) and send due 24-hour notices.

    ``user_id`` limits the run to one owner's rules (login catch-up). Safe to run any
    number of times, concurrently, from any process. A failing rule is logged and the
    others continue.
    """
    today = today_in_kolkata(now)
    limit = settings.RECURRING_MAX_OCCURRENCES_PER_RULE_PER_RUN
    stmt = (
        select(RecurringRule.id)
        .where(
            RecurringRule.status == ACTIVE,
            RecurringRule.next_run_date.is_not(None),
            RecurringRule.next_run_date <= today + timedelta(days=1),
        )
        .order_by(RecurringRule.next_run_date, RecurringRule.id)
    )
    if user_id is not None:
        stmt = stmt.where(RecurringRule.owner_id == user_id)
    async with AsyncSessionLocal() as session:
        rule_ids = list((await session.execute(stmt)).scalars().all())

    stats = RunStats(rules=len(rule_ids))
    for rule_id in rule_ids:
        try:
            await _process_rule(rule_id, today, limit, stats)
        except Exception as exc:  # noqa: BLE001 - one broken rule must not stop the others
            stats.failed_rules += 1
            logger.error("Recurring rule run failed rule=%s (%s)", rule_id, type(exc).__name__)
            logger.debug("Recurring rule run failed - traceback", exc_info=exc)
    return stats


# ==============================================================================
# Triggers: login catch-up, startup + hourly background task
# ==============================================================================


async def catch_up_after_login(user_id: uuid.UUID) -> None:
    """Catch up one user's rules right after a successful login.

    Bounded by RECURRING_LOGIN_CATCHUP_TIMEOUT_SECONDS so login is never slowed down
    noticeably; a timeout or failure is logged and the next hourly run finishes the work
    (each occurrence is its own transaction, so a cut-off run leaves nothing half-written).
    Never raises.
    """
    if not settings.RECURRING_LOGIN_CATCHUP_ENABLED:
        return
    try:
        stats = await asyncio.wait_for(
            run_due(user_id=user_id), timeout=settings.RECURRING_LOGIN_CATCHUP_TIMEOUT_SECONDS
        )
        if stats.created or stats.skipped:
            logger.info("Login catch-up user=%s created=%d skipped=%d", user_id, stats.created, stats.skipped)
    except TimeoutError:
        logger.warning("Login catch-up timed out for user=%s; the next scheduled run finishes it", user_id)
    except Exception as exc:  # noqa: BLE001 - a failing generator must never break login
        logger.error("Login catch-up failed for user=%s (%s)", user_id, type(exc).__name__)
        logger.debug("Login catch-up failed - traceback", exc_info=exc)


scheduler_runs = 0  # completed scheduler iterations (observability and tests)


async def scheduler_loop(interval_seconds: float) -> None:
    """Startup catch-up, then a run every ``interval_seconds``. Never stops on errors."""
    global scheduler_runs
    while True:
        try:
            stats = await run_due()
            if stats.created or stats.skipped or stats.failed_rules:
                logger.info(
                    "Recurring run: rules=%d created=%d skipped=%d notices=%d failed=%d",
                    stats.rules, stats.created, stats.skipped, stats.notices, stats.failed_rules,
                )
        except Exception as exc:  # noqa: BLE001 - keep the loop alive; the next run retries
            logger.error("Recurring run failed (%s); retrying at the next interval", type(exc).__name__)
            logger.debug("Recurring run failed - traceback", exc_info=exc)
        scheduler_runs += 1
        await asyncio.sleep(interval_seconds)


def start_scheduler(interval_seconds: float | None = None) -> asyncio.Task[None]:
    """Start the background task without waiting for its first (catch-up) run."""
    interval = interval_seconds if interval_seconds is not None else settings.RECURRING_RUN_INTERVAL_SECONDS
    return asyncio.create_task(scheduler_loop(interval), name="recurring-expense-scheduler")


async def stop_scheduler(task: asyncio.Task[None] | None) -> None:
    """Cancel the background task and wait for it to finish (an open run rolls back)."""
    if task is None or task.done():
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
