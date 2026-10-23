# @coinscious/api-client — TypeScript API Client

Typed TypeScript client for the Coinscious FastAPI backend, generated automatically from the OpenAPI 3.1 specification via `openapi-typescript`.

---

## 1. Quick Start

### Import and Use

```typescript
import { createCoinsciousClient } from "@coinscious/api-client";

const client = createCoinsciousClient({
  baseUrl: process.env.API_BASE_URL || "http://localhost:8000",
});

// Call health check
const health = await client.health.check();
console.log(health.status);      // "ok"
console.log(health.environment); // "development" | "production"
console.log(health.version);     // "0.1.0"
```

### Error Handling

The client automatically unwraps server errors into typed `ErrorResponse` envelopes adhering to the Coinscious API Contract:

```typescript
try {
  await client.health.check();
} catch (err) {
  // err is typed as ErrorResponse
  console.error("Error Code:", err.error.code);
  console.error("Error Message:", err.error.message);
  console.error("Request ID:", err.meta.request_id);
}
```

---

## 2. Reproducible Generation Workflow

When backend schemas or routes change in FastAPI, follow this 2-step workflow to regenerate the TypeScript client:

### Step 1: Export OpenAPI Specification from FastAPI
Run the export script from the repository root:
```bash
python backend/scripts/export_openapi.py
```
This generates an up-to-date, formatted JSON schema at `backend/openapi.json`.

### Step 2: Regenerate TypeScript Types
From `packages/api-client` (or using `npx` from repository root):
```bash
npx openapi-typescript backend/openapi.json -o packages/api-client/src/schema.d.ts
```
Or simply run the package script:
```bash
cd packages/api-client
npm run generate
```

---

## 3. Verification

To verify that the client can communicate with the running backend:

1. Start the FastAPI backend:
   ```bash
   cd backend
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. Run the client verification script:
   ```bash
   node packages/api-client/verify-health.mjs
   ```
