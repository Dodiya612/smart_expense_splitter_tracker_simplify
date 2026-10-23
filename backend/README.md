# Coinscious Backend API

FastAPI backend for Coinscious (Smart Expense Splitter & Tracker).

---

## 1. Tech Stack & Architecture

- **Runtime**: Python 3.12 (compatible with 3.11+)
- **Framework**: FastAPI + Uvicorn
- **Architecture**:
  - **Routers** (`app/api/v1/`): HTTP routing, dependency injection, and endpoint declarations.
  - **Services** (`app/services/`): Business logic domain services (e.g. `HealthService`).
  - **Repositories** (`app/repositories/`): Data access abstraction layer following `BaseRepository` interface.
  - **Schemas** (`app/schemas/`): Pydantic v2 data models for request and response contracts.
  - **Core** (`app/core/`): Global configuration, `RequestIDMiddleware` (tracing with `X-Request-ID`), custom exceptions, and centralized error handlers.
- **Contract & Errors**: Consistent error envelope adhering to `docs/API_Contract.html` section 5.
- **Code Quality & Testing**: Ruff (linter/formatter) + pytest (unit & contract testing).

---

## 2. Standard Error Response Envelope

All error responses across the API adhere to the unified envelope specification:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Please check the submitted fields.",
    "field_errors": {
      "amount_paise": "Must be greater than zero."
    }
  },
  "meta": {
    "request_id": "req_8a3d1f0b"
  }
}
```

Standard error codes:
- `400`: `BAD_REQUEST`
- `401`: `UNAUTHORIZED`
- `403`: `FORBIDDEN`
- `404`: `NOT_FOUND`
- `405`: `METHOD_NOT_ALLOWED`
- `409`: `CONFLICT`
- `422`: `VALIDATION_ERROR` (with `field_errors`)
- `429`: `RATE_LIMITED`
- `500`: `INTERNAL_SERVER_ERROR` (stack traces are never leaked)

---

## 3. Quick Start (Local Development)

1. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment**:
   ```bash
   cp .env.example .env
   ```

3. **Run the development server**:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

4. **Test the health endpoint**:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```
   Interactive OpenAPI documentation is available at `http://localhost:8000/api/v1/docs`.

5. **Run tests**:
   ```bash
   pytest
   ```

6. **Run linter and formatting checks**:
   ```bash
   ruff check .
   ruff format --check .
   ```

---

## 4. OpenAPI Specification Export

Export the live OpenAPI 3.1 specification to `backend/openapi.json`:

```bash
# From repository root
python backend/scripts/export_openapi.py

# Or with custom output target
python backend/scripts/export_openapi.py -o /path/to/custom/openapi.json
```

---

## 5. TypeScript API Client Generation

The TypeScript client in `packages/api-client` is generated directly from the exported `openapi.json` using `openapi-typescript`:

```bash
# Step 1: Export OpenAPI from backend
python backend/scripts/export_openapi.py

# Step 2: Generate TypeScript definitions
npx openapi-typescript backend/openapi.json -o packages/api-client/src/schema.d.ts

# Step 3: Run client verification against running backend
node packages/api-client/verify-health.mjs
```

---

## 6. Production Deployment (Render)

Render uses the declarative blueprint specified in `render.yaml` at repository root:
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Health Check Path**: `/api/v1/health`
- **Port**: Dynamically provided by Render via the `$PORT` environment variable.
