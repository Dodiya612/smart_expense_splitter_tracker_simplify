# Coinscious Backend API

FastAPI backend for Coinscious (Smart Expense Splitter & Tracker).

## Tech Stack
- **Python**: 3.12 (compatible with 3.11+)
- **Framework**: FastAPI + Uvicorn
- **Schemas**: Pydantic v2 + Pydantic Settings
- **Testing**: pytest + httpx (TestClient)
- **Linting & Formatting**: Ruff

## Quick Start (Local Development)

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

6. **Run linter**:
   ```bash
   ruff check .
   ruff format --check .
   ```

## Production Deployment (Render)

Render uses the configuration specified in `render.yaml` at repository root:
- **Build Command**: `pip install -r requirements.txt`
- **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Health Check Path**: `/api/v1/health`
- **Port**: Dynamically provided by Render via the `$PORT` environment variable.
