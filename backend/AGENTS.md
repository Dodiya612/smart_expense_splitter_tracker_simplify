# Backend Agent Instructions — Smart Expense Splitter & Tracker

## 1. Scope and authority

These instructions apply to files under `backend/`. Repository-level contributor rules and the user's explicit instructions also apply. If instructions conflict, stop and explain the conflict instead of guessing.

This backend serves the existing Expo React Native app. It is not a separate product. Preserve the mobile app and its working state.

### Mandatory workflow
1. Inspect the repository, current API contract, mobile API types/client, requirements, existing backend files, and git status before proposing changes.
2. Summarize findings and propose a small, ordered plan. Identify decisions that block implementation.
3. **Wait for explicit user approval before modifying project files, installing packages, changing configuration, creating migrations, or running commands that mutate data.**
4. Implement one approved phase at a time. Do not silently expand scope.
5. Before calling a phase complete, run relevant tests/checks and report exact commands and outcomes. Distinguish verified results from assumptions.
6. Never commit, push, reset, clean, stash, rebase, delete, or overwrite user work unless explicitly asked. Never use destructive cleanup commands.
7. Preserve unrelated changes and untracked files. Inspect `git status` before and after work.
8. Ask one focused question when a decision blocks progress. Do not make up product decisions.

## 2. Product and domain invariants

- Currency is INR only for the MVP. Do not add multi-currency behavior.
- Represent money as integer paise throughout calculations and persisted monetary fields. Never use `float` for money. Validate positive/non-negative ranges and database limits.
- API field names and documentation must make units explicit, e.g. `amount_paise`; never silently mix rupees and paise.
- Every expense split must sum exactly to the expense total. Define deterministic remainder allocation and test it.
- Avoid double counting expenses, reimbursements, settlements, and analytics totals. Document each aggregate's meaning.
- Groups contain registered users only. No guest members in the MVP.
- The app records settlement information; it does not move money. Never imply that recording a settlement proves a real payment occurred.
- Keep an auditable history for financial changes. Do not implement edits, deletions, reversals, or balance mutations until their rules are explicitly decided.
- Agree and document the balance sign convention, payer-participation rule, split rounding, date/timezone rules, expense ownership, and settlement semantics before relying on them.
- Keep the provisional API contract and `mobile/src/services/api/types.ts` aligned. Inspect current files; paths or types may have changed. Do not force a mismatch just to preserve a draft contract.

## 3. Architecture and implementation

- Use the repository's existing choices where sound. Do not introduce a second backend framework, ORM, database, auth system, or dependency manager without approval.
- If no backend stack exists, propose FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, and a relational database; wait for approval of the database, Python version, sync/async strategy, and auth strategy before scaffolding.
- Prefer a simple modular monolith. No microservices, Redis, task queues, event buses, or extra infrastructure without a concrete approved need.
- Keep route handlers thin. Separate request/response schemas, domain/business logic, persistence access, and authentication/authorization dependencies.
- Use dependency injection for database sessions and authenticated-user context.
- Keep business rules testable without an HTTP server or database when practical.
- Use explicit types; avoid `Any`, broad exception swallowing, hidden global state, and circular imports.
- Use async I/O only when the selected libraries and code path are genuinely asynchronous. Do not mix sync and async database access casually.
- Never fabricate data to make endpoints look complete. Do not add placeholder endpoints that return success without implementing the promised behavior.
- Keep configuration in environment variables/settings. Validate required configuration at startup; never commit secrets or real credentials.
- Use migrations for schema changes. Review generated migrations manually; do not auto-apply a migration to a shared/production database.

## 4. Security baseline — required, not optional

Security is a design and verification requirement, not a claim that the app is “secure.” Apply defense in depth and report remaining risks.

### Authentication and credentials
- Never store, log, return, or expose plaintext passwords. Use a maintained password-hashing library with a currently recommended password-hashing algorithm and parameters.
- Never implement custom cryptography or token formats.
- Use a maintained authentication/token library. Validate signature, allowed algorithm, issuer/audience where applicable, expiry, and other required claims. Do not accept unsigned or algorithm-confused tokens.
- Define token expiry, refresh/logout behavior, and client storage expectations before integration. Do not put secrets or tokens in URLs.
- Return generic login failures that do not reveal whether an account exists.
- Apply sensible password length limits and request-size limits; avoid arbitrary complexity rules unless required.
- Never log passwords, bearer tokens, session secrets, database URLs with credentials, or other secrets.

### Authorization and IDOR prevention
- Authentication alone is not authorization. Enforce authorization on every protected operation on the server.
- Derive the acting user from validated authentication context, not from a client-supplied `user_id`, `owner_id`, `created_by`, or similar field.
- For every resource ID, verify that the authenticated user owns the resource or has the required group membership/role before returning or mutating it.
- Apply the same checks to nested resources, lists, filters, exports, balances, analytics, settlements, and related-object IDs. Avoid insecure direct object references (IDOR/BOLA).
- Do not trust the mobile client to enforce permissions. Test cross-user and cross-group access explicitly.
- Validate that every payer and split participant is an eligible registered user and, for group expenses, a current member under the agreed membership rules.
- Do not expose password hashes, internal secrets, or unnecessary personal data in responses.

### Validation, database, and transactions
- Validate all request input with typed schemas, strict domain constraints, length limits, and allowlisted enum values where applicable.
- Use parameterized ORM/query APIs; never build SQL by concatenating untrusted input.
- Use database foreign keys, uniqueness constraints, and transactions for multi-row expense/split/settlement operations.
- Handle concurrent writes correctly. Do not read-modify-write financial balances outside a transaction when correctness depends on atomicity.
- Add idempotency protection for operations where retries could create duplicate financial records, if required by the agreed API design.
- Do not trust client-calculated totals, splits, balances, permissions, or analytics; recompute/verify on the backend.
- Avoid leaking stack traces, SQL errors, filesystem paths, environment details, or secrets to clients. Return stable, sanitized error responses.

### API and operational security
- Restrict CORS to the approved client origins/configuration; do not use wildcard origins with credentials.
- Configure trusted hosts/proxy behavior only for the actual deployment topology. Do not assume local development settings are production-safe.
- Keep interactive API docs and debug mode appropriate to the environment.
- Add rate limits or abuse controls for login/signup and other sensitive endpoints before public deployment; choose the mechanism based on the actual deployment.
- Set upload limits and content validation if file upload is introduced. File upload is not MVP scope unless approved.
- Use secure production secret management and HTTPS at deployment. Do not place production secrets in source control, example files, screenshots, logs, or agent prompts.
- Pin/lock dependencies and check advisories before deployment. Do not blindly upgrade or downgrade dependencies.
- Do not run untrusted scripts, install unreviewed agent skills, or paste secrets into external services.
- Do not claim that a checklist, linter, scan, or passing test proves the absence of vulnerabilities.

## 5. Database and migrations

- Confirm database engine and Python/dependency compatibility before scaffolding.
- Prefer PostgreSQL for a shared/concurrent environment unless the user explicitly chooses another option. SQLite is acceptable for a local prototype only when its limitations and migration plan are understood.
- Use Alembic for SQLAlchemy schema migrations unless an existing approved migration system is in place.
- Every schema change must have a reviewed migration. Inspect autogenerated SQL and data-loss implications before applying.
- Never run migrations against production/shared data without explicit approval and a verified backup/rollback plan.
- Use constraints and indexes to reinforce invariants, not just application checks.
- Define deletion/retention behavior for users, groups, expenses, splits, and settlements before implementing cascades.

## 6. Testing and quality gates

For each approved phase, run applicable checks and report outcomes:
- Unit tests for pure domain rules, especially money arithmetic, split remainder allocation, balances, and analytics.
- API tests for success, invalid input, unauthenticated access, forbidden access, missing resources, and error responses.
- Cross-user/cross-group authorization tests for each protected resource class.
- Database tests for constraints, transactions, uniqueness, and concurrent/idempotent behavior where applicable.
- Migration validation against a clean database and, where practical, an upgrade path from the prior schema.
- Static checks/linting/formatting using the project's selected tools.
- Verify OpenAPI and compare request/response schemas with the mobile API contract.
- Run the mobile type check or relevant contract checks when backend API types change and the environment allows it.

Never report a check as passed unless it was actually run and its exit status/result was observed. If a check could not be run, state why and what remains unverified.

## 7. Scope and dependencies

- Do not install dependencies, add MCP servers, change global Antigravity settings, or copy external skills without user approval.
- Prefer the smallest maintained dependency set. Explain why each new dependency is needed.
- Do not add Docker, Redis, observability vendors, deployment configuration, or CI changes until requested or justified by an approved phase.
- Keep secrets out of `.env` files tracked by Git; provide `.env.example` with safe placeholders only.
- Do not loosen typing, linting, tests, or security checks merely to make the build pass.
- Do not automatically apply formatter fixes across unrelated files.

## 8. Definition of done

A backend phase is done only when:
1. The approved scope is implemented and unrelated work remains untouched.
2. Domain and authorization rules are covered by tests appropriate to the phase.
3. Relevant checks pass, or failures and unverified checks are clearly reported.
4. API contract/OpenAPI changes are documented and mobile impact is identified.
5. No secrets are exposed and migrations are reviewed.
6. The user receives a concise summary of changed files, commands/results, known limitations, and the next proposed phase.

These rules reduce risk but cannot guarantee that the application is vulnerability-free. Perform security review and deployment-specific hardening before exposing the service publicly.
