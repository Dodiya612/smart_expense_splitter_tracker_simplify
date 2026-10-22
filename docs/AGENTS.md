# Coinscious — Agent Instructions

This repository belongs to Coinscious, the Smart Expense Splitter & Tracker (Group 28).

## Before changing code
- Read the assigned GitHub issue and its acceptance criteria. Work ONLY on that issue.
- Inspect the current repository, branch, working-tree changes, relevant code, tests, and project docs before editing.
- Reuse working code. Make the smallest change that satisfies the issue. Do not add extras, duplicate features, or refactor unrelated code.
- Preserve other contributors' changes. Do not discard work, run destructive Git commands, or modify unrelated files.
- If the issue is unavailable or a required change conflicts with another member's work, stop and ask for clarification.

## Project technology
- Frontend: React Native + Expo, TypeScript (strict), Expo Router.
- Data fetching: TanStack Query.
- Forms/validation: React Hook Form + Zod on the frontend.
- Backend: Python 3.12, FastAPI, Uvicorn.
- API schemas/contracts: Pydantic v2; OpenAPI; generated TypeScript client via openapi-typescript.
- Database: PostgreSQL 16 on Supabase.
- Data access/migrations: SQLAlchemy 2.0 and Alembic.
- Authentication/security: Argon2id via argon2-cffi, PyJWT, HTTP-only refresh cookies; follow existing CSRF/session/authorization implementation.
- Charts: react-native-gifted-charts.
- CI: GitHub Actions.
Read `docs/TECH_STACK.md` for the fuller project reference.

## Non-negotiable project rules
- The existing code, dependency manifests, migrations, and generated OpenAPI schema are the implementation truth. If they disagree with docs, report the mismatch; do not silently replace the stack or invent an API.
- Keep frontend fields, Pydantic schemas, OpenAPI, and database fields consistent. Do not change shared contracts without coordination.
- Store monetary amounts as integer paise (BIGINT in PostgreSQL); do not use floating-point for money calculations.
- Follow existing validation, record-level authorization, session/CSRF protections, and error conventions.
- Mock data must be clearly separated from real API calls. Never claim a mock operation was persisted.
- Add or update relevant tests and run available checks. Report exact commands/results; never claim unrun tests passed.
- Do not add dependencies or change architecture unless the issue requires it and the change is approved.
- Do not commit, push, merge, switch branches, or perform destructive Git actions unless explicitly authorized.

## Completion report
Summarize: files changed, why each change was needed, acceptance criteria met, tests actually run/results, blockers or pre-existing failures, and unrelated findings left untouched.
