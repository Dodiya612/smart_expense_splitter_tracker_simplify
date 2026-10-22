# Coinscious Technology Stack & Implementation Reference

**Project:** Coinscious — Smart Expense Splitter & Tracker  
**Team:** Group 28  
**Purpose:** Shared reference for developers and AI coding agents. This document describes the stack chosen in the product document; it does not prove that every component is already implemented.

## 1. Technology by layer

| Layer | Chosen technology | How to use it |
|---|---|---|
| Frontend app and web | React Native (Expo), TypeScript strict, Expo Router | Reuse the existing shared app structure and navigation. |
| Data fetching/cache | TanStack Query | Follow existing query/mutation patterns and cache invalidation rules. |
| Forms and client validation | React Hook Form + Zod | Keep client validation aligned with backend validation. |
| Backend API | Python 3.12, FastAPI, Uvicorn | Follow the current router/service structure. |
| API schemas | Pydantic v2, OpenAPI | API request/response schemas are the contract; do not invent shapes. |
| TypeScript API client | openapi-typescript-generated client | Regenerate/use it according to the repository's current workflow. |
| Database | PostgreSQL 16 on Supabase | Use existing database configuration and schema. |
| ORM and migrations | SQLAlchemy 2.0, Alembic | Make schema changes through the established migration workflow. |
| Password security | argon2-cffi (Argon2id) | Follow existing password hashing implementation. |
| Tokens/session | PyJWT and HTTP-only refresh cookies | Preserve existing session, CSRF, and authorization protections. |
| Charts | react-native-gifted-charts | Use the existing chart components and accessible table alternatives where present. |
| CI | GitHub Actions | Run and preserve existing checks; do not replace workflows casually. |
| Receipt OCR | OCR.space, after image shrinking and location metadata removal | Follow the product's privacy and receipt-processing flow. |
| AI text/category assistance | History lookup / TF-IDF classifier; Groq when uncertain | AI suggestions must remain reviewable and allow manual user choice. |

## 2. Core product and data rules

- Version 1 currency is Indian rupees.
- Store money as integer paise, using PostgreSQL `BIGINT` where specified. Example: ₹250.00 = `25000` paise.
- Never use binary floating-point for money arithmetic.
- Use ISO 8601 date/time formats where the API contract specifies them; use the project time-zone rule `Asia/Kolkata` for reporting periods.
- IDs are opaque strings unless the actual schema says otherwise.
- Keep frontend validation, Pydantic validation, and database constraints aligned.
- The backend must enforce authentication and record-level authorization; hiding a UI control is not authorization.
- Follow the documented transaction and ledger rules for expense splits, shares, settlements, and audit/history records.
- Do not log secrets or sensitive personal/receipt data.
- Never commit `.env`, credentials, API keys, or tokens.

## 3. API contract workflow

1. Inspect the existing FastAPI routes and generated OpenAPI specification.
2. Check the product/API documentation and current Pydantic schemas.
3. Treat the implementation and OpenAPI schema as evidence of what currently exists.
4. If documentation and implementation differ, report the mismatch to the issue owner before changing a shared contract.
5. Coordinate any shared endpoint, request/response, or database-schema change with the relevant members.
6. Update tests and generated client artifacts only using the repository's established commands.

An endpoint or example shown in a planning document is not proof that it is already implemented. Do not invent endpoint paths, fields, response shapes, or status codes.

## 4. Working on an assigned issue

- Work only on the supplied GitHub issue and its acceptance criteria.
- Inspect first; make the smallest complete change.
- Reuse existing code and tests.
- Leave unrelated bugs for their owner; report them rather than fixing them silently.
- Preserve all pre-existing working-tree changes.
- Do not run destructive Git commands, commit, push, merge, or switch branches without authorization.
- Run relevant tests/checks and report the exact outcomes. Do not claim success without evidence.
- Keep mock data visibly separate from real backend calls and never present it as persisted data.

## 5. Source of truth when there is a mismatch

Use this order to investigate, not to silently override one source with another:

1. Existing implementation, dependency manifests, migrations, and actual test results.
2. Generated OpenAPI specification and current Pydantic schemas for API behaviour.
3. Product document and API contract documentation for intended behaviour.
4. Assigned GitHub issue and acceptance criteria for the current task's scope.

If sources conflict, stop before a risky shared change and report the exact mismatch to the issue owner.

## 6. Repository setup and commands

Do not assume commands or folder names. First inspect `package.json`, lockfiles, Python dependency files (`pyproject.toml` or `requirements*.txt`), environment examples, and CI workflows. Use the commands actually defined by this repository. Never print or expose secret values from environment files.

## 7. Completion report format

- Issue and acceptance criteria
- Existing behaviour discovered
- Files changed and reason
- Tests/checks run and exact results
- Remaining blockers, failures, and limitations
- Out-of-scope findings left unchanged
- Git actions performed (only if authorized)
