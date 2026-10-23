# Coinscious — Deployment & Environment Setup Guide

**Story:** US-39: Development & Production Environment Setup  
**Sprint:** Sprint 0  
**Department:** Integration & Deployment  
**Assignee:** Jay Vaghela  

---

## 1. Overview & Architecture

Coinscious utilizes a decoupled cloud architecture designed for scalability, security, and developer productivity:

```
┌────────────────────────────────────────────────────────────────────────┐
│                              CLIENT TIER                               │
│                                                                        │
│  [Mobile App (Expo/React Native)]      [Web Frontend (Future)]         │
│          (Inside mobile/)                       (Vercel)               │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   │                                 │
                   │ HTTPS API Requests              │ HTTPS API Requests
                   ▼                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                              BACKEND TIER                              │
│                                                                        │
│                      Render Web Service (FastAPI)                      │
│             uvicorn app.main:app --host 0.0.0.0 --port $PORT           │
│                   Health Check: GET /api/v1/health                     │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   │ PostgreSQL over SSL (Pooler 6543)
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                             DATABASE TIER                              │
│                                                                        │
│                     PostgreSQL 16 on Supabase                          │
│               (Separate Development & Production Projects)             │
│                     Row Level Security (RLS) Enforced                  │
└────────────────────────────────────────────────────────────────────────┘
```

### Environment Isolation

| Environment | Purpose | Hosting / Infrastructure | Database |
|---|---|---|---|
| **Development** | Local development & testing | Local workstation (`localhost:8000`) | Supabase Dev Project (`ap-south-1`) |
| **CI / PR Testing** | Automated pull request validation | GitHub Actions runner | Ephemeral throwaway PostgreSQL container |
| **Production** | Live end-user service | Render Web Service (`coinscious-backend.onrender.com`) | Supabase Production Project (Dedicated PostgreSQL 16) |

---

## 2. Environment Variables & Secrets Reference

### 2.1 Backend Environment Variables

All sensitive values must use secure placeholders in version control and be populated exclusively in hosting-provider secret stores.

| Variable Name | Required | Default | Scope | Description |
|---|---|---|---|---|
| `ENVIRONMENT` | Yes | `development` | Server | Environment identifier (`development`, `staging`, `production`). |
| `DEBUG` | No | `false` | Server | Enables debug mode and hot reloading (must be `false` in production). |
| `PORT` | Yes | `8000` | Server | HTTP port. In Render, `$PORT` is injected dynamically (e.g., `10000`). |
| `HOST` | Yes | `0.0.0.0` | Server | Network interface binding. Must be `0.0.0.0` for containerized hosting. |
| `CORS_ORIGINS` | Yes | `["*"]` | Server | JSON array or comma-separated list of allowed client origins. |
| `DATABASE_URL` | Yes | None | Server | PostgreSQL connection string using Supabase connection pooler (port 6543). |
| `DIRECT_URL` | No | None | Server | Direct PostgreSQL connection string (port 5432) for Alembic migrations. |
| `SUPABASE_URL` | Yes | None | Server | Base URL for Supabase API project (`https://<ref>.supabase.co`). |
| `SUPABASE_ANON_KEY` | Yes | None | Server/Client | Public client key subject to Supabase Row Level Security (RLS). |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | None | **Server ONLY** | Master key bypassing RLS. **NEVER expose to frontend or commit to Git.** |
| `JWT_SECRET` | Yes | None | **Server ONLY** | Cryptographic secret for signing and validating session JWTs (PyJWT). |
| `JWT_ALGORITHM` | No | `HS256` | Server | Signing algorithm for JWT tokens. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `15` | Server | Lifespan of short-lived session access tokens. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `30` | Server | Lifespan of rotating refresh tokens stored in HTTP-only cookies. |
| `OCR_SPACE_API_KEY` | No | None | Server | API key for OCR.space receipt text extraction service. |
| `GROQ_API_KEY` | No | None | Server | API key for Groq LLM assistance and fallback category tagging. |

### 2.2 Security Rules

1. **Zero Secret Commits**: Real `.env` files are ignored via the root `.gitignore`.
2. **Key Separation**:
   - `SUPABASE_ANON_KEY`: Allowed in client apps; protected by Row Level Security policies.
   - `SUPABASE_SERVICE_ROLE_KEY`: Restricted strictly to server-side background processes. Never expose to client bundles.
   - `DATABASE_URL`: Contains database passwords. Restricted to Render environment secrets.
3. **Secret Scanning**: Gitleaks runs in CI to reject any commits containing API keys or tokens.

---

## 3. Supabase Configuration

Coinscious uses managed PostgreSQL 16 hosted on Supabase.

### 3.1 Project Topology

- **Development Project**: Used by developers for local testing and feature branches.
- **Production Project**: Isolated project with strict access control and automated backups.

### 3.2 Connection Pooling (Supavisor)

Supabase utilizes **Supavisor** for connection pooling:
- **Transaction Mode (`port 6543`)**: Used for the FastAPI backend (`DATABASE_URL`). Supports hundreds of concurrent connections with minimal memory overhead.
  ```text
  postgresql://postgres.<project-ref>:<db-password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require
  ```
- **Session / Direct Mode (`port 5432`)**: Used for Alembic schema migrations (`DIRECT_URL`).
  ```text
  postgresql://postgres.<project-ref>:<db-password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
  ```

### 3.3 SSL Enforcement

All connections to Supabase PostgreSQL require SSL (`sslmode=require`). Unencrypted plaintext connections are rejected at the edge.

---

## 4. Backend Deployment on Render

### 4.1 Automated Blueprint Deployment (`render.yaml`)

The repository root includes a declarative Infrastructure-as-Code blueprint (`render.yaml`):

```yaml
services:
  - type: web
    name: coinscious-backend
    runtime: python
    rootDir: backend
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT
    healthCheckPath: /api/v1/health
    plan: free
    autoDeploy: true
    envVars:
      - key: PYTHON_VERSION
        value: 3.12.0
      - key: ENVIRONMENT
        value: production
      - key: HOST
        value: 0.0.0.0
      - key: PORT
        value: "10000"
      - key: DATABASE_URL
        sync: false
      - key: SUPABASE_URL
        sync: false
      - key: SUPABASE_ANON_KEY
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
```

### 4.2 Manual Render Setup Steps

If deploying via the Render web dashboard instead of the blueprint:

1. Log in to [Render Dashboard](https://dashboard.render.com).
2. Click **New +** → **Web Service**.
3. Connect the GitHub repository `Dodiya612/smart_expense_splitter_tracker_simplify`.
4. Configure service parameters:
   - **Name**: `coinscious-backend`
   - **Region**: Singapore or Frankfurt (closest to Supabase region `ap-south-1`)
   - **Branch**: `main`
   - **Root Directory**: `backend`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Under **Advanced**:
   - **Health Check Path**: `/api/v1/health`
   - **Auto-Deploy**: `Yes`
6. Add Environment Variables under **Environment**:
   - `ENVIRONMENT` = `production`
   - `DEBUG` = `false`
   - `HOST` = `0.0.0.0`
   - `DATABASE_URL` = `<supabase-production-connection-string>`
   - `SUPABASE_URL` = `<supabase-production-url>`
   - `SUPABASE_ANON_KEY` = `<supabase-production-anon-key>`
   - `SUPABASE_SERVICE_ROLE_KEY` = `<supabase-production-service-role-key>`
   - `JWT_SECRET` = `<cryptographic-random-secret>`
   - `CORS_ORIGINS` = `["https://coinscious.vercel.app"]`
7. Click **Create Web Service**.

### 4.3 Zero-Downtime Health Probing

Render automatically probes `GET /api/v1/health` before routing incoming production traffic to new deploys. If the health endpoint does not return HTTP `200 OK` within the timeout window, Render cancels the deploy and preserves the previously healthy instance.

---

## 5. Frontend Deployment on Vercel

### 5.1 Status & Blocker Documentation

> [!WARNING]
> **Vercel Web Frontend Blocker**  
> Per strict project constraints, the `mobile/` directory contains an Expo/React Native mobile application and must remain completely untouched and excluded from deployment workflows.  
> 
> Because **no web frontend exists outside `mobile/`**, automatic Vercel deployment of a web application is currently **blocked**. In accordance with US-39 requirements, no artificial frontend was created.

### 5.2 Future Vercel Setup (When Web Frontend Is Created)

Once a dedicated web frontend application is created outside `mobile/` (e.g. in `frontend/`):

1. **Connect Repository**: Import the repository in the Vercel dashboard.
2. **Framework Preset**: Select framework (e.g., Next.js, Vite).
3. **Root Directory**: Set to `frontend`.
4. **Build Command**: `npm run build` or framework default.
5. **Output Directory**: `dist` or `.next`.
6. **Environment Variables**:
   - `VITE_API_BASE_URL` or `NEXT_PUBLIC_API_URL` = `https://coinscious-backend.onrender.com/api/v1`
   - `NEXT_PUBLIC_SUPABASE_URL` = `https://<ref>.supabase.co`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` = `<anon-key>`
7. **Production Branch**: `main` (auto-deploys on every merge).

---

## 6. GitHub Actions & Deployment Automation

### 6.1 Workflows Summary

| Workflow File | Trigger | Purpose |
|---|---|---|
| `.github/workflows/deploy.yml` | `push` to `main` | Production deployment trigger for Render backend & health verification. |

### 6.2 Required GitHub Repository Secrets

Configure these secrets under **Settings** → **Secrets and variables** → **Actions**:

| Secret Name | Purpose | Example Value |
|---|---|---|
| `RENDER_DEPLOY_HOOK_URL` | Webhook URL to trigger Render build | `https://api.render.com/deploy/srv-xxxx?key=yyyy` |
| `RENDER_BACKEND_URL` | Live URL for post-deployment health check | `https://coinscious-backend.onrender.com` |
| `VERCEL_TOKEN` | (Future) Token for Vercel deployment | `vercel_token_placeholder` |

---

## 7. Local Development & Verification Commands

### 7.1 Setup Local Environment

```bash
# Navigate to backend directory
cd backend

# Create virtual environment (optional)
python -m venv .venv
source .venv/bin/activate    # On Linux/macOS
.venv\Scripts\activate       # On Windows

# Install dependencies
pip install -r requirements.txt

# Copy environment template
cp .env.example .env
```

### 7.2 Run Backend Locally

```bash
# Start server with auto-reload
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 7.3 Test Local Health Endpoint

```bash
# Test GET /api/v1/health
curl -i http://127.0.0.1:8000/api/v1/health

# Expected HTTP 200 response:
# {
#   "status": "ok",
#   "environment": "development",
#   "version": "0.1.0",
#   "timestamp": "2026-10-22T18:06:36.093553+00:00"
# }
```

### 7.4 Run Automated Tests

```bash
cd backend
python -m pytest
```

### 7.5 Run Linter and Formatter Checks

```bash
python -m ruff check backend
python -m ruff format --check backend
```

### 7.6 OpenAPI Export & TypeScript Client Generation

```bash
# 1. Export OpenAPI 3.1 specification from FastAPI
python backend/scripts/export_openapi.py

# 2. Generate TypeScript client definitions via openapi-typescript
npx openapi-typescript backend/openapi.json -o packages/api-client/src/schema.d.ts

# 3. Verify client health endpoint call against running backend
node packages/api-client/verify-health.mjs
```

---

## 8. Health Endpoint (`GET /api/v1/health`) Specification

- **Path**: `/api/v1/health` (with root alias `/health`)
- **HTTP Method**: `GET`
- **Authentication**: None (public liveness probe)
- **Response Status**: `200 OK`
- **Response Schema**:
  ```json
  {
    "status": "ok",
    "environment": "production",
    "version": "0.1.0",
    "timestamp": "2026-10-22T18:06:36.093553+00:00"
  }
  ```
- **Security Guarantees**:
  - Does not leak database connection strings, passwords, or hostnames.
  - Does not reveal internal infrastructure paths or stack traces.
  - Excluded from CSRF checks and session middleware to prevent false liveness failures.

---

## 9. Common Deployment Errors & Troubleshooting

### 9.1 Render Service Failing to Bind to Port
- **Symptom**: `Port 8000 is unavailable` or `Service failed to bind to $PORT within timeout`.
- **Cause**: Hardcoding port `8000` instead of reading the dynamic `$PORT` environment variable injected by Render.
- **Fix**: The start command in `render.yaml` must use `--port $PORT`. The application code uses `int(os.environ.get("PORT", settings.PORT))`.

### 9.2 Container Not Reachable (Host Binding)
- **Symptom**: Service boots but health check times out at `0.0.0.0` or `127.0.0.1`.
- **Cause**: Binding to `127.0.0.1` (localhost only) restricts access inside the Docker/container boundary.
- **Fix**: Always bind to `0.0.0.0` using `--host 0.0.0.0`.

### 9.3 Supabase Connection Pool Exhaustion / Timeout
- **Symptom**: `asyncpg.exceptions.TooManyConnectionsError` or `SSL connection has been closed unexpectedly`.
- **Cause**: Connecting directly to `port 5432` without pooling under high concurrency.
- **Fix**: Use the Supavisor connection pooler URL on `port 6543` for `DATABASE_URL`. Reserve direct `port 5432` only for Alembic migrations.

### 9.4 CORS Origin Blocked in Browser
- **Symptom**: `Access to fetch at ... has been blocked by CORS policy`.
- **Cause**: Frontend origin not included in `CORS_ORIGINS`.
- **Fix**: Update the `CORS_ORIGINS` environment variable in the Render dashboard to include the frontend URL (e.g., `["https://coinscious.vercel.app"]`).

### 9.5 Missing Gitleaks Pre-commit Hook / Leaked Canary
- **Symptom**: Gitleaks flags leaked credentials in pull request.
- **Cause**: Accidental commit of `.env` file containing real API keys.
- **Fix**: Ensure `.env` is listed in `.gitignore`. Run `git rm --cached .env` if accidentally staged.
