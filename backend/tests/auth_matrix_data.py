"""
Authorization Matrix Specification for Smart Expense Splitter & Tracker (Coinscious).
Issue T-17 / US-37 (#43).

Provides a machine-readable, single source-of-truth table for every endpoint
in backend/openapi.json.  For each operation it records:
  - the required authentication level
  - the expected HTTP status for each actor (stranger, non-owner, owner)
  - the security invariant that must hold

The test suite in test_authorization_matrix.py drives its test cases
directly from OPENAPI_AUTHORIZATION_MATRIX so that adding a new endpoint
to openapi.json without updating this table causes the completeness check
to fail in CI.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class EndpointMatrixEntry:
    """Describes the authorization contract for a single OpenAPI operation."""

    method: str
    """HTTP method in uppercase."""

    path: str
    """Path as it appears in openapi.json, with {param} placeholders."""

    operation_id: str
    """operationId from openapi.json — used as a stable key."""

    category: str
    """Logical grouping: Health | Authentication | Expenses."""

    is_public: bool
    """True iff the endpoint is intentionally accessible without credentials."""

    auth_required: bool
    """True iff the endpoint requires a valid Bearer access token."""

    stranger_status: int
    """Expected HTTP status when the caller supplies no credentials at all."""

    stranger_code: Optional[str]
    """Expected error code in the JSON envelope for the stranger actor, or None."""

    non_owner_status: int
    """Expected HTTP status when an authenticated user accesses another user's record."""

    non_owner_code: Optional[str]
    """Expected error code for the non-owner actor, or None if a success response."""

    owner_status: int
    """Expected HTTP status when the legitimate owner/creator performs the action."""

    admin_required: bool
    """True iff an admin role is required (currently none exist in this codebase)."""

    security_invariant: str
    """Human-readable description of the authorisation rule this entry enforces."""


# ---------------------------------------------------------------------------
# Canonical Authorization Matrix
# Every (method, path) pair in backend/openapi.json must have exactly one
# entry here.  The completeness test in test_authorization_matrix.py asserts
# this bijection; add a row here whenever a new endpoint is introduced.
# ---------------------------------------------------------------------------

OPENAPI_AUTHORIZATION_MATRIX: List[EndpointMatrixEntry] = [

    # ── Health ────────────────────────────────────────────────────────────────
    EndpointMatrixEntry(
        method="GET",
        path="/api/v1/health",
        operation_id="health_check_api_v1_health_get",
        category="Health",
        is_public=True,
        auth_required=False,
        stranger_status=200,
        stranger_code=None,
        non_owner_status=200,
        non_owner_code=None,
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Public liveness probe. No authentication or authorisation is required."
        ),
    ),

    # ── Authentication & Registration (public) ─────────────────────────────
    EndpointMatrixEntry(
        method="POST",
        path="/api/v1/auth/signup",
        operation_id="signup_api_v1_auth_signup_post",
        category="Authentication",
        is_public=True,
        auth_required=False,
        stranger_status=201,
        stranger_code=None,
        non_owner_status=201,
        non_owner_code=None,
        owner_status=409,  # Duplicate e-mail → CONFLICT
        admin_required=False,
        security_invariant=(
            "Public registration. Password hashed with Argon2id. "
            "Duplicate e-mail rejected with 409 EMAIL_ALREADY_EXISTS."
        ),
    ),

    EndpointMatrixEntry(
        method="POST",
        path="/api/v1/auth/register",
        operation_id="register_api_v1_auth_register_post",
        category="Authentication",
        is_public=True,
        auth_required=False,
        stranger_status=201,
        stranger_code=None,
        non_owner_status=201,
        non_owner_code=None,
        owner_status=409,
        admin_required=False,
        security_invariant=(
            "Alias for /signup with identical contract. "
            "Duplicate e-mail rejected with 409."
        ),
    ),

    EndpointMatrixEntry(
        method="POST",
        path="/api/v1/auth/login",
        operation_id="login_api_v1_auth_login_post",
        category="Authentication",
        is_public=True,
        auth_required=False,
        stranger_status=401,   # wrong/absent credentials → INVALID_CREDENTIALS
        stranger_code="INVALID_CREDENTIALS",
        non_owner_status=401,
        non_owner_code="INVALID_CREDENTIALS",
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Public credential exchange. Returns generic 401 on wrong credentials "
            "without distinguishing missing account from wrong password "
            "(prevents user enumeration)."
        ),
    ),

    EndpointMatrixEntry(
        method="POST",
        path="/api/v1/auth/refresh",
        operation_id="refresh_token_api_v1_auth_refresh_post",
        category="Authentication",
        is_public=False,
        auth_required=True,   # requires a valid refresh token in the body
        stranger_status=401,
        stranger_code="INVALID_TOKEN",
        non_owner_status=401,
        non_owner_code="INVALID_TOKEN",
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Refresh-token rotation. Invalid / revoked / expired refresh tokens "
            "return 401. Reuse of a consumed token revokes the entire family."
        ),
    ),

    EndpointMatrixEntry(
        method="POST",
        path="/api/v1/auth/logout",
        operation_id="logout_api_v1_auth_logout_post",
        category="Authentication",
        is_public=True,
        auth_required=False,  # optional — works with token body or bearer header
        stranger_status=200,  # idempotent: no-op when nothing to revoke
        stranger_code=None,
        non_owner_status=403,  # authenticated user revoking someone else's token
        non_owner_code="CREDENTIAL_MISMATCH",
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Idempotent logout. When an authenticated user supplies a refresh "
            "token that belongs to another user, the server returns 403 "
            "CREDENTIAL_MISMATCH and leaves the foreign session intact."
        ),
    ),

    EndpointMatrixEntry(
        method="GET",
        path="/api/v1/auth/me",
        operation_id="get_me_api_v1_auth_me_get",
        category="Authentication",
        is_public=False,
        auth_required=True,
        stranger_status=401,
        stranger_code="UNAUTHORIZED",
        non_owner_status=200,  # every authenticated user can read their own profile
        non_owner_code=None,
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Returns the authenticated caller's profile based exclusively on the "
            "verified JWT sub. A user can never retrieve another user's profile "
            "through this endpoint."
        ),
    ),

    EndpointMatrixEntry(
        method="GET",
        path="/api/v1/auth/sessions",
        operation_id="list_active_sessions_api_v1_auth_sessions_get",
        category="Authentication",
        is_public=False,
        auth_required=True,
        stranger_status=401,
        stranger_code="UNAUTHORIZED",
        non_owner_status=200,  # each user sees their own session list — zero leakage
        non_owner_code=None,
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Active-session list scoped strictly to the authenticated user_id. "
            "No foreign session records are ever returned."
        ),
    ),

    EndpointMatrixEntry(
        method="DELETE",
        path="/api/v1/auth/sessions/{session_id}",
        operation_id="revoke_session_api_v1_auth_sessions__session_id__delete",
        category="Authentication",
        is_public=False,
        auth_required=True,
        stranger_status=401,
        stranger_code="UNAUTHORIZED",
        non_owner_status=404,  # conceals session existence across users
        non_owner_code="SESSION_NOT_FOUND",
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Revokes a single token family by family_id. Attempting to revoke "
            "another user's session returns 404 SESSION_NOT_FOUND and leaves "
            "the target session completely unmodified."
        ),
    ),

    # ── Expenses ───────────────────────────────────────────────────────────
    EndpointMatrixEntry(
        method="POST",
        path="/api/v1/expenses",
        operation_id="create_expense_endpoint_api_v1_expenses_post",
        category="Expenses",
        is_public=False,
        auth_required=True,
        stranger_status=401,
        stranger_code="UNAUTHORIZED",
        non_owner_status=201,  # non-owner creates their own expense — always OK
        non_owner_code=None,
        owner_status=201,
        admin_required=False,
        security_invariant=(
            "Ownership is bound to the authenticated user's id. "
            "Supplying a foreign user_id in the request body is rejected "
            "with 400 PROTECTED_FIELD_MODIFICATION."
        ),
    ),

    EndpointMatrixEntry(
        method="GET",
        path="/api/v1/expenses",
        operation_id="list_expenses_endpoint_api_v1_expenses_get",
        category="Expenses",
        is_public=False,
        auth_required=True,
        stranger_status=401,
        stranger_code="UNAUTHORIZED",
        non_owner_status=200,  # returns the caller's own expense list — zero leakage
        non_owner_code=None,
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Paginated expense list scoped exclusively to the caller. "
            "Passing a foreign user_id as a query parameter is rejected "
            "with 403 FORBIDDEN."
        ),
    ),

    EndpointMatrixEntry(
        method="GET",
        path="/api/v1/expenses/totals",
        operation_id="get_expense_totals_endpoint_api_v1_expenses_totals_get",
        category="Expenses",
        is_public=False,
        auth_required=True,
        stranger_status=401,
        stranger_code="UNAUTHORIZED",
        non_owner_status=200,  # aggregate is always scoped to the caller
        non_owner_code=None,
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Spending aggregate in paise strictly scoped to the caller. "
            "Passing a foreign user_id as a query parameter is rejected "
            "with 403 FORBIDDEN."
        ),
    ),

    EndpointMatrixEntry(
        method="GET",
        path="/api/v1/expenses/{expense_id}",
        operation_id="get_expense_endpoint_api_v1_expenses__expense_id__get",
        category="Expenses",
        is_public=False,
        auth_required=True,
        stranger_status=401,
        stranger_code="UNAUTHORIZED",
        non_owner_status=404,
        non_owner_code="NOT_FOUND",
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Single expense detail. Accessing another user's expense returns "
            "404 NOT_FOUND to conceal record existence (IDOR prevention)."
        ),
    ),

    EndpointMatrixEntry(
        method="PATCH",
        path="/api/v1/expenses/{expense_id}",
        operation_id="update_expense_endpoint_api_v1_expenses__expense_id__patch",
        category="Expenses",
        is_public=False,
        auth_required=True,
        stranger_status=401,
        stranger_code="UNAUTHORIZED",
        non_owner_status=404,
        non_owner_code="NOT_FOUND",
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Partial update with optimistic concurrency. Foreign user returns "
            "404 and the database record remains unchanged. Protected fields "
            "in the payload return 400 PROTECTED_FIELD_MODIFICATION."
        ),
    ),

    EndpointMatrixEntry(
        method="DELETE",
        path="/api/v1/expenses/{expense_id}",
        operation_id="delete_expense_endpoint_api_v1_expenses__expense_id__delete",
        category="Expenses",
        is_public=False,
        auth_required=True,
        stranger_status=401,
        stranger_code="UNAUTHORIZED",
        non_owner_status=404,
        non_owner_code="NOT_FOUND",
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Soft delete. Foreign user returns 404 and the target record's "
            "deleted_at remains None (record is not actually deleted)."
        ),
    ),

    EndpointMatrixEntry(
        method="POST",
        path="/api/v1/expenses/{expense_id}/restore",
        operation_id="restore_expense_endpoint_api_v1_expenses__expense_id__restore_post",
        category="Expenses",
        is_public=False,
        auth_required=True,
        stranger_status=401,
        stranger_code="UNAUTHORIZED",
        non_owner_status=404,
        non_owner_code="NOT_FOUND",
        owner_status=200,
        admin_required=False,
        security_invariant=(
            "Restore soft-deleted expense. Foreign user returns 404 and the "
            "target record remains soft-deleted."
        ),
    ),
]
