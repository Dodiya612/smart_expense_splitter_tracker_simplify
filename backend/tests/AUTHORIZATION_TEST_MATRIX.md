# US-37 Authorization Test Matrix

This document defines the comprehensive **Authorization Test Matrix** for the backend API based on the OpenAPI contract (`backend/openapi.json`), security policies (`app/core/policies/`), and endpoint implementations (`app/api/v1/`).

It validates strict enforcement of authentication, resource ownership, group membership, role-based admin permissions, IDOR defense, and zero unauthorized data leakage.

---

## 1. Authorization Test Matrix Table

| Endpoint | Stranger (Unauthenticated / Invalid / Expired) | Owner / Authorized User | Group Member | Admin | Test Reference |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GET** `/api/v1/health` | **200 OK**<br>Returns health status; no DB passwords or secrets leaked. | **200 OK**<br>Same sanitized status response. | **200 OK**<br>Same sanitized status response. | **200 OK**<br>Same sanitized status response. | `test_public_health_endpoint_accessible_to_all_actors` |
| **POST** `/api/v1/auth/signup` | **201 Created**<br>Can register without session. No password hash leaked. Tampering with `is_admin=True` or `role=admin` is discarded. | **201 Created**<br>Self-registration. | N/A (Public registration) | **201 Created**<br>Admins register via standard provision or role management. | `test_public_auth_signup_and_register_isolation_and_no_hash_leakage` |
| **POST** `/api/v1/auth/register` | **201 Created**<br>Alias to signup. Zero password hash or salt leakage. Privilege escalation blocked. | **201 Created**<br>Self-registration. | N/A (Public registration) | **201 Created**<br>Normal registration path. | `test_public_auth_signup_and_register_isolation_and_no_hash_leakage` |
| **POST** `/api/v1/auth/login` | **200 OK** on valid credentials; **401 INVALID_CREDENTIALS** on wrong password or unknown user. Zero hash leakage. | **200 OK**<br>Generates JWT access + refresh tokens for owner. | N/A (User authentication) | **200 OK**<br>Generates tokens with admin claims. | `test_public_auth_login_credential_verification_and_safety` |
| **POST** `/api/v1/auth/refresh` | **401 UNAUTHORIZED / INVALID_TOKEN** on forged, missing, or revoked refresh token. | **200 OK**<br>Rotates tokens for valid family. | N/A (Session token rotation) | **200 OK**<br>Rotates tokens for valid admin family. | `test_public_auth_refresh_token_validation` |
| **POST** `/api/v1/auth/logout` | **200 OK** if refresh token in body belongs to unauthenticated caller. **401** if invalid token. | **200 OK** on own refresh token; **403 CREDENTIAL_MISMATCH** when attempting to revoke another user's token. | N/A (Per-user session) | **200 OK**<br>Can revoke own sessions. | `test_logout_cross_user_credential_mismatch` |
| **GET** `/api/v1/auth/me` | **401 UNAUTHORIZED**<br>(Unauthenticated, invalid token, expired token, deactivated account). | **200 OK**<br>Returns strictly User A's profile. Zero cross-user profile exposure. | **200 OK**<br>Returns strictly Member B's profile. | **200 OK**<br>Returns strictly Admin's profile with verified `is_admin=True`. | `test_stranger_unauthenticated_requests_all_protected_endpoints`<br>`test_user_profile_me_access_and_isolation` |
| **GET** `/api/v1/auth/sessions` | **401 UNAUTHORIZED**<br>Rejected immediately without token. | **200 OK**<br>Returns strictly active sessions belonging to the requesting user. | **200 OK**<br>Returns strictly Member B's sessions. User A's sessions are omitted. | **200 OK**<br>Returns strictly Admin's sessions. | `test_sessions_listing_data_isolation` |
| **DELETE** `/api/v1/auth/sessions/{session_id}` | **401 UNAUTHORIZED**<br>Rejected without token. | **204 No Content** on own session; **403 FORBIDDEN / 404 NOT_FOUND** on foreign session IDOR. Database token remains unrevoked. | **403 FORBIDDEN** on other users' sessions. | **204 No Content** on own session; scoped revocation. | `test_session_revocation_idor_protection_and_db_integrity` |
| **POST** `/api/v1/expenses` | **401 UNAUTHORIZED**<br>Missing or invalid token. | **201 Created** for owner. If caller injects a foreign `user_id`, endpoint rejects with **403 FORBIDDEN** or forces authenticated user identity. | **201 Created** when posting group expenses if authorized member; **403 FORBIDDEN** if referencing foreign category. | **201 Created**<br>Can record expenses under authorized scope. | `test_expense_creation_ownership_enforcement`<br>`test_expense_creation_category_authorization` |
| **GET** `/api/v1/expenses` | **401 UNAUTHORIZED**<br>Missing or invalid token. | **200 OK**<br>Lists strictly User A's records. Query parameter tampering (`?user_id=B`) returns strictly User A's records or **403 FORBIDDEN**. | **200 OK**<br>Lists expenses belonging to Member B or shared groups. User A's private records are omitted. | **200 OK**<br>Can view expenses scoped to tenant/workspace. | `test_expense_listing_isolation_and_query_tampering` |
| **GET** `/api/v1/expenses/totals` | **401 UNAUTHORIZED**<br>Missing or invalid token. | **200 OK**<br>Computes aggregations strictly over User A's expenses. Query spoofing (`?user_id=B`) rejected or filtered to User A. | **200 OK**<br>Computes aggregations strictly for Member B. | **200 OK**<br>Computes aggregations for administrative scope. | `test_expense_totals_isolation_and_query_tampering` |
| **GET** `/api/v1/expenses/{expense_id}` | **401 UNAUTHORIZED**<br>Missing or invalid token. | **200 OK** for own expense; **403 FORBIDDEN / 404 NOT_FOUND** when User B or C attempts cross-user IDOR access. Zero body leakage. | **200 OK** if expense is shared in Member B's group; **403 / 404** if private to User A. | **200 OK** for accessible resources within admin scope. | `test_expense_read_idor_protection_and_data_leakage` |
| **PATCH** `/api/v1/expenses/{expense_id}` | **401 UNAUTHORIZED**<br>Missing or invalid token. | **200 OK** for own expense; **403 FORBIDDEN / 404 NOT_FOUND** on foreign IDOR. DB row remains unmodified. Protected fields (`user_id`, `id`) tampering rejected with **400 / 422**. Disallowed fields rejected. | **403 FORBIDDEN / 404** on other members' private expenses. DB row unmodified. | **200 OK** on permissible administrative updates. | `test_expense_update_idor_protection_and_db_integrity`<br>`test_expense_update_protected_fields_tampering_rejected`<br>`test_expense_update_disallowed_fields_rejected` |
| **DELETE** `/api/v1/expenses/{expense_id}` | **401 UNAUTHORIZED**<br>Missing or invalid token. | **204 No Content** on own expense. Soft-deletes row. Cross-user IDOR attempt by User B/C rejected with **403 / 404**; DB record is NOT deleted. | **403 FORBIDDEN** on other member's expenses. Record preserved. | **204 No Content** within authorized deletion scope. | `test_expense_deletion_idor_protection_and_db_integrity` |
| **POST** `/api/v1/expenses/{expense_id}/restore` | **401 UNAUTHORIZED**<br>Missing or invalid token. | **200 OK** restores own soft-deleted expense. Cross-user IDOR attempt rejected with **403 / 404**; foreign expense is NOT restored. | **403 FORBIDDEN** on non-member / other user's expense. | **200 OK** on authorized restoration. | `test_expense_restore_idor_protection_and_db_integrity` |
| **POST** `/api/v1/ai/category-suggestion` | **401 UNAUTHORIZED**<br>Missing or invalid token. | **200 OK** returns AI ML suggestion. History/context strictly isolated to authenticated user. | **200 OK** suggestions isolated to member. | **200 OK** operational for administrative users. | `test_ai_category_suggestion_authorization_and_isolation` |
| **POST** `/api/v1/ai/category-suggestion/feedback` | **401 UNAUTHORIZED**<br>Missing or invalid token. | **200 OK** / **201 Created** stores feedback for caller. Injecting foreign `user_id` or `expense_id` is rejected or rebound to caller. | **200 OK** feedback tied strictly to member identity. | **200 OK** admin feedback recorded properly. | `test_ai_category_feedback_authorization_and_spoofing_protection` |

---

## 2. Test Actor Personas

The automated authorization test suite initializes four realistic test personas and fixtures:

1. **User A (`Owner`)**:
   - `id`: `11111111-1111-1111-1111-111111111111`
   - `email`: `user_a@example.com`
   - `role`: Standard user; owner of primary expenses, categories, and active sessions.
2. **User B (`Group Member / Other User`)**:
   - `id`: `22222222-2222-2222-2222-222222222222`
   - `email`: `user_b@example.com`
   - `role`: Standard user; shares a group (`group_alpha`) with User A for group-scoped tests, but has separate private expenses and sessions.
3. **User C (`Stranger / Non-Member`)**:
   - `id`: `33333333-3333-3333-3333-333333333333`
   - `email`: `stranger_c@example.com`
   - `role`: Standard user; does NOT belong to `group_alpha`. Unrelated third-party actor.
4. **Admin User (`System Admin`)**:
   - `id`: `99999999-9999-9999-9999-999999999999`
   - `email`: `admin@example.com`
   - `role`: `admin`, `is_admin = True`. Possesses elevated platform permissions.

---

## 3. Important Security Rules & Invariants

1. **Zero Data Leakage**:
   - When an unauthorized actor attempts access to a protected resource (e.g., User B accessing User A's expense), the server responds with `403 Forbidden` or `404 Not Found`.
   - The response payload MUST NOT leak sensitive values (e.g., title, amount, category name, notes, or IDs of another user's expense).
   - Password hashes (`hashed_password`) and auth tokens are NEVER included in response representations (`/auth/me`, `/auth/signup`, `/auth/login`).
2. **Write & Mutation Integrity**:
   - When an unauthorized PATCH or DELETE request is rejected, the target database record MUST remain unmodified.
   - Soft-delete status (`is_deleted`) and data fields (`amount`, `description`) are verified before and after each attack to ensure zero tampering.
3. **IDOR & Parameter Spoofing Prevention**:
   - Endpoints that accept query parameters (such as `user_id` on `GET /api/v1/expenses` or `GET /api/v1/expenses/totals`) strictly ignore or reject foreign `user_id` values, bounding query results to `current_user.id`.
   - Request bodies (e.g. `POST /api/v1/expenses`, `POST /api/v1/ai/category-suggestion/feedback`) that include a `user_id` field are validated; providing a foreign `user_id` triggers `HTTP 403` or rebinds to `current_user.id`.
4. **Immutable Protected Fields**:
   - Attempting to mutate immutable fields on existing records (`user_id`, `id`, `created_at`) via PATCH triggers `HTTP 400 Bad Request` or `HTTP 422 Unprocessable Entity` with code `IMMUTABLE_FIELD_MODIFIED` via `validate_protected_fields`.
5. **Group Policy Scoping**:
   - Resources associated with a group (`group_id`) can be read by group members.
   - Non-members (Stranger C) attempting to read or write group resources are denied with `HTTP 403 / 404`.
   - Group administrative actions (e.g., removing members or changing group settings) are restricted to group owners/admins.

---

## 4. Discovered OpenAPI Endpoints & Coverage

Total Discovered Operations in `backend/openapi.json`: **16**
Total Additional Router Operations in `app/api/v1/api.py`: **2** (AI categorization)
Total Applicable Endpoints: **18**
Total Covered Endpoints: **18 (100% Coverage)**

Coverage Gaps: **0**. Every discovered operation has corresponding automated test cases.

---

## 5. Local Execution Instructions

To execute the automated authorization test matrix locally:

```bash
# Activate backend virtual environment
cd backend
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Run the US-37 authorization test matrix
python -m pytest tests/test_authorization.py -v

# Run with coverage report
python -m pytest tests/test_authorization.py --cov=app.api.v1 --cov=app.core.policies

# Run the complete backend test suite to verify zero regressions
python -m pytest tests/ -v
```

