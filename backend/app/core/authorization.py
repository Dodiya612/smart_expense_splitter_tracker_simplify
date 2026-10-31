"""
Centralized Authorization Layer for Smart Expense Splitter & Tracker (Coinscious).
US-37 / Issue #42 (T-16).

This module provides:
1. Action and role definitions for authorization decisions.
2. Protected-field definitions and validation against unauthorized updates.
3. Record-level access policy checks for resources (Expense, Category, Session, Group).
4. Query scoping helpers to ensure handlers never query private records by raw ID.
5. Safe, sanitized error responses preventing IDOR and information leakage.
"""

from enum import Enum
from typing import Any, Sequence, Set
import uuid

from fastapi import HTTPException, status
from sqlalchemy import Select, select

from app.models.category import Category
from app.models.expense import Expense
from app.models.refresh_token import RefreshToken
from app.models.user import User


class Action(str, Enum):
    """Actions that can be performed on resources."""
    READ = "read"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    RESTORE = "restore"
    ADMIN = "admin"


class GroupRole(str, Enum):
    """Roles within a group for group-level authorization."""
    ADMIN = "admin"
    MEMBER = "member"


# ==============================================================================
# Protected Fields Specification
# ==============================================================================

# Fields that clients must NOT modify via ordinary update endpoints.
PROTECTED_FIELDS: Set[str] = {
    # Ownership and identification
    "id",
    "user_id",
    "userId",
    "owner_id",
    "ownerId",
    "creator_id",
    "creatorId",
    # Audit timestamps
    "created_at",
    "createdAt",
    "updated_at",
    "updatedAt",
    # Soft deletion state
    "deleted_at",
    "deletedAt",
    # Privileges and roles
    "is_admin",
    "isAdmin",
    "is_superuser",
    "isSuperuser",
    "role",
    "roles",
    "permissions",
    # Group association & roles
    "group_id",
    "groupId",
    "group_role",
    "groupRole",
    # Credentials & security
    "hashed_password",
    "hashedPassword",
    "email",
}

# Allowlisted fields permitted for expense updates
ALLOWED_EXPENSE_UPDATE_FIELDS: Set[str] = {
    "amount_minor",
    "amount_paise",
    "amountMinor",
    "amountPaise",
    "description",
    "category_id",
    "categoryId",
    "expense_date",
    "occurred_on",
    "expenseDate",
    "occurredOn",
    "notes",
    "merchant",
    "payment_mode",
    "paymentMode",
    "receipt_id",
    "receiptId",
    "version",  # Permitted for optimistic concurrency checks
}


def validate_protected_fields_update(
    payload: dict[str, Any],
    allowed_fields: Set[str] | None = None,
    protected_fields: Set[str] | None = None,
) -> None:
    """
    Validates that an update payload does not contain protected or unauthorized fields.

    Raises:
        HTTPException(400): If any protected or disallowed fields are present in the payload.
    """
    if not isinstance(payload, dict):
        return

    protected = protected_fields or PROTECTED_FIELDS
    violating_protected = [k for k in payload.keys() if k in protected]
    if violating_protected:
        violating_sorted = sorted(violating_protected)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PROTECTED_FIELD_MODIFICATION",
                "message": (
                    f"Modification of protected field(s) is not permitted: "
                    f"{', '.join(violating_sorted)}."
                ),
            },
        )

    if allowed_fields is not None:
        disallowed = [k for k in payload.keys() if k not in allowed_fields]
        if disallowed:
            disallowed_sorted = sorted(disallowed)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "DISALLOWED_FIELD_UPDATE",
                    "message": (
                        f"Update payload contains unsupported field(s): "
                        f"{', '.join(disallowed_sorted)}."
                    ),
                },
            )


# ==============================================================================
# Record-Level Access Policies
# ==============================================================================

class ExpensePolicy:
    """Record-level access policy for Personal Expenses."""

    @staticmethod
    def authorize(
        current_user: User,
        expense: Expense,
        action: Action = Action.READ,
        allow_deleted: bool = False,
    ) -> None:
        """
        Authorize access to an Expense record.

        - A user can only access an expense they created/own (expense.user_id == current_user.id).
        - To prevent IDOR and enumeration of private IDs, accessing another user's expense
          returns HTTP 404 NOT_FOUND rather than 403.
        - Soft-deleted records return 404 unless allow_deleted=True (or during Action.RESTORE).
        - Attempting to restore an active expense returns HTTP 400 BAD_REQUEST.
        """
        # Strict ownership check
        if expense.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Expense not found."},
            )

        if action == Action.RESTORE:
            if expense.deleted_at is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "EXPENSE_NOT_DELETED",
                        "message": "Expense is not deleted and cannot be restored.",
                    },
                )
            return

        if not allow_deleted and expense.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Expense not found."},
            )

    @staticmethod
    def scope_query(
        stmt: Select,
        user_id: uuid.UUID,
        include_deleted: bool = False,
    ) -> Select:
        """
        Scopes a SQLAlchemy select statement to the authenticated user.
        Ensures queries are never executed by raw ID alone.
        """
        scoped = stmt.where(Expense.user_id == user_id)
        if not include_deleted:
            scoped = scoped.where(Expense.deleted_at.is_(None))
        return scoped


class CategoryPolicy:
    """Access policy for Categories."""

    @staticmethod
    def authorize(
        current_user: User,
        category: Category,
        action: Action = Action.READ,
    ) -> None:
        """
        Authorize access to a Category.

        - Default categories (is_default=True) are readable by any active user.
        - Custom categories are accessible only by their creator (owner_id == current_user.id).
        - Default categories cannot be modified or deleted.
        """
        if action in (Action.READ, Action.CREATE):
            if category.is_default or (category.owner_id == current_user.id):
                return
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_CATEGORY",
                    "message": f"Category '{category.id}' does not exist or is not accessible.",
                },
            )

        # UPDATE or DELETE
        if category.is_default:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "FORBIDDEN",
                    "message": "Default system categories cannot be modified or deleted.",
                },
            )
        if category.owner_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "NOT_FOUND", "message": "Category not found."},
            )

    @staticmethod
    def scope_query(stmt: Select, user_id: uuid.UUID) -> Select:
        """Scopes category query to default categories or user-owned custom categories."""
        return stmt.where((Category.is_default.is_(True)) | (Category.owner_id == user_id))


class SessionPolicy:
    """Record-level access policy for Refresh Tokens / Active Sessions."""

    @staticmethod
    def authorize(
        current_user: User,
        session_token: RefreshToken,
        action: Action = Action.READ,
    ) -> None:
        """
        Authorize access to a session / refresh token.

        A user cannot view or revoke another user's session. Returns HTTP 404 NOT_FOUND.
        """
        if session_token.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "SESSION_NOT_FOUND", "message": "Session not found."},
            )

    @staticmethod
    def scope_query(stmt: Select, user_id: uuid.UUID) -> Select:
        """Scopes session query strictly to authenticated user's tokens."""
        return stmt.where(RefreshToken.user_id == user_id)


class GroupPolicy:
    """
    Authorization policy for shared groups.
    Prepares and unifies access control for future group features (US-17, US-18).
    """

    @staticmethod
    def authorize_member(
        current_user: User,
        group_id: uuid.UUID,
        member_user_ids: Sequence[uuid.UUID] | Set[uuid.UUID],
    ) -> None:
        """Ensures the authenticated user is an active member of the specified group."""
        if current_user.id not in member_user_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "GROUP_ACCESS_DENIED",
                    "message": "You are not a member of this group.",
                },
            )

    @staticmethod
    def authorize_admin(
        current_user: User,
        group_id: uuid.UUID,
        member_user_ids: Sequence[uuid.UUID] | Set[uuid.UUID],
        admin_user_ids: Sequence[uuid.UUID] | Set[uuid.UUID],
    ) -> None:
        """Ensures the authenticated user has administrator privileges in the specified group."""
        GroupPolicy.authorize_member(current_user, group_id, member_user_ids)
        if current_user.id not in admin_user_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INSUFFICIENT_PERMISSIONS",
                    "message": "Administrator privileges required for this action.",
                },
            )
