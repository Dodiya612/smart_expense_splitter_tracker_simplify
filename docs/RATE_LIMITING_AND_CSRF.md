# Rate Limiting and CSRF (T-39 / US-33, issue #97)

This document describes what the backend actually does today. Where issue #97 asks for something
that does not apply to the current architecture, that is stated explicitly rather than implied.

## 1. Authentication model (verified in code)

| Aspect | Current behaviour |
|---|---|
| Access token | 15-minute JWT, sent as `Authorization: Bearer <token>` on every protected route |
| Refresh token | Random, rotating, stored hashed; sent and returned in the **JSON body** of `/auth/login`, `/auth/refresh`, `/auth/logout` |
| Cookies | **None.** The backend never sends `Set-Cookie` and never reads a cookie |
| Mobile storage | Expo SecureStore (`mobile/src/services/auth/tokenStorage.ts`) |
| Browser client | None exists in this repository |
| CORS | Explicit origin allow-list (`CORS_ORIGINS`), `allow_credentials=True`; `Retry-After` is exposed |

Older documents (`docs/AGENTS.md`, the product document) describe an HTTP-only refresh cookie with
`SameSite=Strict` and a double-submit token. **That design was not implemented**; the code is
bearer-only.

## 2. CSRF threat model

**Classic CSRF does not apply to this API.** CSRF works because browsers attach *ambient*
credentials (cookies, HTTP auth) to cross-site requests automatically. Here every protected request
must carry an explicit `Authorization` header, which a malicious page cannot make a victim's
browser add, and the one credential that looks like a cookie (the refresh token) is sent in a request
body. The mobile app has no ambient credentials and sends no `Origin` header, so there is nothing
for a CSRF token to protect and requiring one would only break it.

What this does **not** cover:

* **XSS / token theft** is a separate threat. A CSRF token does not stop script running in the page
  from reading a token. A web client would need its own mitigations (CSP, token storage choices).
* **Issue #97 acceptance criteria "SameSite cookie protection is configured" and "double-submit
  CSRF token protection is implemented" are not applicable** to the current architecture and are
  **not implemented**. Adding them without any cookie-authenticated route would be dormant code
  protecting nothing. They would be misleading to claim.

### If cookie authentication is ever introduced

Before any cookie can authenticate a request, all of the following are required, and must be
designed and tested at that time:

* `HttpOnly`, `Secure`, and `SameSite=Strict` (or `Lax` with a clear reason) on the cookie;
* a CSRF defence on every state-changing route that accepts the cookie (double-submit token or
  synchronizer token, plus `Origin` / `Fetch-Metadata` validation);
* a decision on how the mobile client (no cookie jar semantics, no `Origin`) keeps using bearer
  tokens without a CSRF requirement;
* CORS review: never `allow_credentials=True` with a wildcard origin.

## 3. Rate limits

Counters are stored in PostgreSQL (`rate_limit_buckets`, migration `012`), so a limit holds across
every worker and instance. No Redis and no extra dependency are used.

| Category | Routes | Scope | Default limit | Config (env) | If the limiter is unavailable |
|---|---|---|---|---|---|
| Login | `POST /auth/login` | account + address | 5 / 15 min | `LOGIN_RATE_LIMIT_MAX_ATTEMPTS`, `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | **HTTP 503** |
| | | address, all accounts | 20 / 15 min | `RATE_LIMIT_LOGIN_IP_MAX` | 503 |
| | | account, all addresses | 30 / 15 min | `RATE_LIMIT_LOGIN_ACCOUNT_MAX` | 503 |
| Signup | `POST /auth/signup`, `/auth/register` (shared) | address | 5 / hour | `RATE_LIMIT_SIGNUP_IP_MAX`, `RATE_LIMIT_SIGNUP_WINDOW_SECONDS` | 503 |
| Refresh | `POST /auth/refresh` | address | 120 / 15 min | `RATE_LIMIT_REFRESH_IP_MAX`, `RATE_LIMIT_REFRESH_WINDOW_SECONDS` | 503 |
| Invitations | `POST /groups/{id}/invitations` | user | 20 / hour | `RATE_LIMIT_INVITE_USER_MAX`, `RATE_LIMIT_INVITE_WINDOW_SECONDS` | **503** |
| Join by code | `POST /groups/join` | user | 10 / 15 min | `RATE_LIMIT_JOIN_USER_MAX`, `RATE_LIMIT_JOIN_WINDOW_SECONDS` | 503 |
| Join-code rotation | `POST /groups/{id}/join-code` | user | 10 / hour | `RATE_LIMIT_JOIN_CODE_USER_MAX`, `RATE_LIMIT_JOIN_CODE_WINDOW_SECONDS` | 503 |
| Accept / decline | `POST /invitations/{id}/accept`, `/decline` (shared) | user | 30 / 15 min | `RATE_LIMIT_INVITE_RESPOND_USER_MAX`, `RATE_LIMIT_INVITE_RESPOND_WINDOW_SECONDS` | 503 |
| AI suggestions | `POST /ai/category-suggestion`, `/ai/suggestions` (shared) | user | 20 / min | `RATE_LIMIT_AI_BURST_USER_MAX`, `RATE_LIMIT_AI_WINDOW_SECONDS` | 503 |
| AI feedback | `POST /ai/category-suggestion/feedback`, `/ai/suggestions/feedback` (shared) | user | 60 / min | `RATE_LIMIT_AI_FEEDBACK_USER_MAX` | 503 |
| Uploads | *(none exist)* | | | | **Deferred**, see below |

The existing **daily AI quotas** (`AI_QUOTA_*_DAILY`, `app/ai/quota.py`) are unchanged; the burst
limit is an additional short-window control that also covers the local classifier path, which has
no daily quota. `RATE_LIMIT_ENABLED` defaults to `true`; `false` is accepted **only when `ENVIRONMENT=development`**.
Any other environment refuses to start with `RATE_LIMIT_ENABLED=false` (a startup validation error),
and `render.yaml` does not set it.

### How it works

* Each request **reserves a slot first** with one atomic
  `INSERT ... ON CONFLICT DO UPDATE SET count = count + 1 RETURNING count`, then proceeds only if the
  returned count is within the limit. Concurrent requests on any connection get distinct counts, so
  the limit cannot be exceeded by racing requests.
* **Every limited route fails closed.** If the counters cannot be read or written, the request is
  refused with HTTP 503 `RATE_LIMITER_UNAVAILABLE` before any business logic runs. There is no
  fail-open path in the code, so a limit is never silently skipped during a database problem.
* Counters are written in their own session, so a request that fails and rolls back still counts.
* Fixed windows aligned to the Unix epoch. A caller can in principle use up to twice the limit by
  straddling a window boundary; this is an accepted trade-off of fixed windows.
* **Login:** every attempt is counted before the password is checked. After a successful login
  (once the session is saved) the **account-and-address** bucket and the **account-only** bucket for
  that account are cleared. The **address-only** bucket is shared with other users behind the same
  address, so it is *not* cleared; only the one successful attempt is given back. Failed and blocked
  attempts never clear anything. A single attacker therefore cannot lock out a victim who logs in
  from elsewhere.
* Identifiers are stored only as keyed HMAC-SHA256 hashes (key derived from `JWT_SECRET_KEY`); no
  email, user id or address is stored in clear. Rotating the JWT secret resets all counters.
* **Cleanup:** about 1% of counter writes (`RATE_LIMIT_PURGE_PROBABILITY`) also delete a batch of up
  to `RATE_LIMIT_PURGE_BATCH` expired rows (`expires_at` = window end + 60 s, indexed).
* Authenticated routes are limited **after** authentication, so a stranger cannot spend someone's
  budget; invalid-token floods are not counted per user.

### Responses

* **429**: standard envelope with code `RATE_LIMIT_EXCEEDED`, `isRetryable: true`, a message that
  names the wait, and a positive integer `Retry-After` header (seconds left in the window; the
  largest across the exceeded counters). `Retry-After` is exposed through CORS.
* The daily AI quota keeps its own 429 with code `AI_QUOTA_EXCEEDED` and `isRetryable: false`
  (retrying cannot help until midnight UTC).
* **503** `RATE_LIMITER_UNAVAILABLE` (retryable, no `Retry-After`): the counters could not be read or
  written. This applies to every limited route. Infrastructure failure is never reported as 429.
* Existing invitation error codes (`ALREADY_MEMBER`, `INVITATION_ALREADY_EXISTS`, ...) are unchanged.

## 4. Client address and trusted proxies (UNRESOLVED deployment dependency)

**Address-scoped limits are not production-ready until this is resolved.**

* `render.yaml` used to start uvicorn with `--proxy-headers --forwarded-allow-ips='*'`. With `*`,
  uvicorn copies the **leftmost** `X-Forwarded-For` entry, which the caller controls, into
  `request.client`. **That wildcard has been removed** (T-39). uvicorn's own default now applies:
  forwarded headers are honoured only from loopback (`127.0.0.1`, `::1`, or whatever the
  `FORWARDED_ALLOW_IPS` environment variable says; **do not set that variable to `*` in the Render
  dashboard**). No trusted IP or hop count was guessed.
* The application never uses `request.client`, `X-Forwarded-For` or `X-Real-IP` for rate limiting,
  so its limits do not depend on the start command at all.
* Impact of removing the wildcard, checked in the code: the app builds no absolute URLs, uses no
  `url_for` / `base_url` / host header, and sets HSTS from `ENVIRONMENT`, not from the request
  scheme. The only effect is Starlette's automatic `307` redirect for a request that adds or drops a
  trailing slash (for example `/api/v1/groups/`): its `Location` is built from the request scheme and
  host, and behind Render's TLS termination the scheme now appears as `http`. The mobile client calls
  exact paths, so it is unaffected; a browser or tool that follows such a redirect would be sent to
  `http://` once (Render redirects HTTP to HTTPS at the edge is an assumption, not verified). If this
  ever matters, the safe fix is to set `FORWARDED_ALLOW_IPS` to Render's *verified* proxy ranges, not
  to a guess.
* Without a trusted client address the socket peer behind Render's load balancer is shared by all
  clients, so a naive per-address limit would throttle everybody together; that is why address-scoped
  limits stay off until a header is verified.
* The app reads the client address **only** from the header named by `TRUSTED_CLIENT_IP_HEADER`
  (unset by default). The header must contain exactly one valid IP; lists and garbage are treated as
  unknown. A proxy that you control must set it and **overwrite any client-supplied value**.
* While it is unset, the address-scoped counters (login account-and-address, login per-address,
  signup, refresh) are **skipped** and a warning is logged once per process. The per-account login
  ceiling (30 / 15 min) and all user-scoped limits still apply, so brute force on one account is
  capped at 30 guesses per window instead of 5. This is the interim trade-off between brute-force
  protection and lockout abuse. **Client-IP protection is not production-ready until the deployment
  task below is done.**

What is **known**: Render's [web services docs](https://render.com/docs/web-services) say nothing
about client-IP headers; Render's articles describe reading `X-Forwarded-For` and warn that Cloudflare
*appends* to it (so the leftmost value is spoofable), and recommend `CF-Connecting-IP`.
What is **not verified** for this service: whether it is reached through Cloudflare, which header
Render's edge actually sets, and whether a direct request can reach the container with a forged value.

To finish (owner action, needs the real deployment):

1. In a staging or temporary deployment, log the raw request headers for one request that carries a
   forged `X-Forwarded-For` and `CF-Connecting-IP`, and see which are overwritten by the edge.
2. Set `TRUSTED_CLIENT_IP_HEADER` to the header the edge **always overwrites**.
3. (Done in T-39) `--forwarded-allow-ips='*'` was removed from `render.yaml`. Confirm no
   `FORWARDED_ALLOW_IPS=*` is set in the Render dashboard.

## 5. Uploads

There are no upload endpoints (no `UploadFile`, no multipart dependency); only `receipt_id`
reference fields exist. Upload rate limiting is **deferred until upload endpoints exist**. When they
do, add a user-scoped policy in `app/core/rate_limiter.py:get_policy`, attach `limit_by_user(...)`
to the routes, and cap request body size.

## 6. Deployment checklist

1. **Apply migration `012_create_rate_limit_buckets` before deploying this code.** Signup, login and
   refresh, and every other limited route, return 503 when the table is missing. It also requires `011` (T-36) to be applied.
2. The migration enables RLS with no policies and revokes `anon`/`authenticated`/`PUBLIC` access; the
   backend (table owner, same `DATABASE_URL` as Alembic) is unaffected. Confirm the production
   runtime role is the migration role.
3. Review the limits above and set `TRUSTED_CLIENT_IP_HEADER` once verified (section 4). If the
   limiter database is unavailable, signup, login, refresh, invitations, joining, join-code rotation
   and the AI routes all return 503 until it recovers.
4. Do not rely on address-scoped protection until step 3 is done.

## 7. Tests

`tests/test_rate_limiter.py`, `test_rate_limits_auth.py`, `test_rate_limits_routes.py`,
`test_rate_limits_ai.py` (in-memory counters, frozen clock) and `tests/test_rate_limit_pg.py`
(real PostgreSQL: concurrency, SQL, end-to-end login, 503, migration). Tests that would use the
configured `DATABASE_URL` (`test_auth_integration.py`, `test_health.py::test_genuine_postgresql_integration`)
must be run with a disposable `DATABASE_URL`, never the shared Supabase one.
