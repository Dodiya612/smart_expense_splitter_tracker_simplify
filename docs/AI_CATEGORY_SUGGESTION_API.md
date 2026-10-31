# AI Category Suggestion API Documentation (T-23 / US-26)

This document provides technical documentation for the Category Suggestion and Feedback API implemented in **T-23** (GitHub Issue #49) under **US-26** (AI Category Suggestion).

---

## 1. Overview & Architecture

The Category Suggestion API provides real-time, advisory expense categorization using a three-tier waterfall architecture:

```
[Incoming Request: description, merchant, user_id]
                       │
                       ▼
┌────────────────────────────────────────────────────────┐
│ Layer 1: User History Layer                            │
│ - Checks user-specific transaction history             │
│ - Bayesian probability blending: alpha = min(0.6, N/(N+3)) │
└──────────────────────┬─────────────────────────────────┘
                       │
                       ▼
┌────────────────────────────────────────────────────────┐
│ Layer 2: Local ML Classifier (T-22)                    │
│ - TF-IDF (word 1-2 & char_wb 2-5 n-grams)              │
│ - Regularized Logistic Regression (C=5.0)              │
│ - Evaluates confidence against 60% threshold           │
└──────────────────────┬─────────────────────────────────┘
                       │
       ┌───────────────┴───────────────┐
       │ Confidence >= 0.60            │ Confidence < 0.60
       ▼                               ▼
[Return Local Result]       ┌────────────────────────────────────┐
(source: "classifier"       │ Layer 3: Groq LLM Fallback         │
 or "history")              │ - Model: llama-3.1-8b-instant      │
                            │ - Timeout: 2.0 seconds             │
                            │ - Zero data retention agreement    │
                            │ - Strict 12 canonical category map │
                            └──────────────────┬─────────────────┘
                                               │
                               ┌───────────────┴───────────────┐
                               │ Valid LLM Output              │ Timeout / Error / Unconfigured
                               ▼                               ▼
                     [Return LLM Result]           [Keyword Rule Baseline]
                     (source: "llm")               (source: "rule_fallback")
```

---

## 2. API Endpoints

### 2.1 Suggest Category

- **Method & Path:** `POST /api/v1/ai/category-suggestion`
- **Compatibility Alias:** `POST /api/v1/ai/suggestions`
- **Authentication:** Required (`Bearer <JWT>`)
- **Headers:** `Content-Type: application/json`, `Authorization: Bearer <token>`

#### Request Payload
```json
{
  "description": "Starbucks cold brew coffee",
  "merchant": "Starbucks"
}
```

#### Response Payload (HTTP 200 OK)
```json
{
  "data": {
    "suggestedCategoryId": "00000000-0000-4000-8000-000000000001",
    "categoryId": "00000000-0000-4000-8000-000000000001",
    "categoryName": "Food & Dining",
    "confidence": 0.942,
    "requiresConfirmation": false,
    "source": "classifier"
  }
}
```

*Note:* Supports both `camelCase` (mobile client convention) and `snake_case` field names via Pydantic v2 `BaseSchema`. Both `suggestedCategoryId` (official API contract) and `categoryId` (mobile interface) are returned.

---

### 2.2 Record Feedback / Manual Selection

- **Method & Path:** `POST /api/v1/ai/category-suggestion/feedback`
- **Compatibility Alias:** `POST /api/v1/ai/suggestions/feedback`
- **Authentication:** Required (`Bearer <JWT>`)

#### Request Payload
```json
{
  "description": "Starbucks cold brew coffee",
  "merchant": "Starbucks",
  "suggestedCategoryId": "00000000-0000-4000-8000-000000000001",
  "chosenCategoryId": "00000000-0000-4000-8000-000000000001",
  "confidence": 0.942,
  "source": "classifier",
  "accepted": true
}
```

#### Response Payload (HTTP 200 OK)
```json
{
  "data": {
    "success": true,
    "message": "Feedback recorded successfully"
  }
}
```

---

## 3. Configuration & Environment Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | `Optional[str]` | `None` | Groq API key for LLM fallback. If omitted, falls back safely to `KeywordRuleBaseline`. |
| `GROQ_MODEL` | `str` | `llama-3.1-8b-instant` | Groq model identifier with zero data retention. |

---

## 4. The 60% Confidence Threshold & Fallback Rules

1. **Local ML Confidence $\ge 0.60$:**
   - Groq API is **never** invoked.
   - Response source is `"classifier"` or `"history"`.
   - Protects user privacy, eliminates network egress, and ensures sub-millisecond latency.
2. **Local ML Confidence $< 0.60$:**
   - If `GROQ_API_KEY` is configured: Groq is queried via `httpx.AsyncClient` with a strict `2.0s` timeout.
   - Response is parsed and strictly validated against the 12 canonical categories. If valid, returned with `source="llm"`.
   - If Groq is not configured, times out, encounters a network drop, returns an HTTP error, or outputs a non-canonical category: falls back safely to `KeywordRuleBaseline.predict()` with `source="rule_fallback"`.
   - **Zero Crash Guarantee:** LLM or network failure will never crash the endpoint.

---

## 5. Feedback Storage & User History Personalization

1. **Database Persistence:**
   - Saved to table `category_suggestion_feedback` via SQLAlchemy model `CategorySuggestionFeedback`.
   - Migration: `005_create_category_suggestion_feedback.py`.
   - Records: `id`, `user_id` (foreign key to `users.id`), `description`, `merchant`, `suggested_category_id`, `chosen_category_id`, `confidence`, `source`, `accepted`, `created_at`.
2. **User History Isolation & Synchronization:**
   - The user ID is strictly extracted from the validated JWT token; client-supplied user IDs are ignored.
   - The in-memory `UserHistoryLayer` is updated **only after** the database commit succeeds. If the database transaction aborts or fails, user history remains unchanged.
   - User histories are strictly segregated by user ID.
3. **Startup Restoration via FastAPI Lifespan:**
   - On application startup, `lifespan` in `backend/app/main.py` invokes `restore_user_history()`.
   - Restores historical category choices using the existing `AsyncSessionLocal` session factory.
   - Idempotent: tracks loaded feedback IDs in memory to avoid duplicate counts on repeated initialization or worker reloads.
   - Safe: catches database connection/query issues gracefully and logs a warning without crashing the server.

---

## 6. Verification & Latency Benchmark Results

### 6.1 Test Suite Status
- **T-22 Model & Normalizer Tests:** 18 passed.
- **T-23 Service, Groq & Restoration Tests:** 23 passed.
- **T-23 API Endpoint Integration Tests:** 9 passed.
- **T-23 Latency Benchmark Test:** 1 passed.
- **Total:** **51 passed, 0 failed, 0 warnings**.

### 6.2 Latency Benchmark (N=100 Requests on Local Path)
Measured on Apple Silicon using `time.perf_counter()` over 100 consecutive requests across diverse Indian merchant transactions:

- **Minimum:** `0.552 ms`
- **p50 (Median):** `0.588 ms`
- **Mean:** `0.601 ms`
- **p95:** `0.664 ms`
- **p99:** `0.877 ms`
- **Maximum:** `0.877 ms`
- **Target NFR:** $p95 < 300\text{ ms}$ (Achieved: **0.664 ms**, **~450x faster than requirement**).

---

## 7. Known Limitations

1. **Offline Development:** When `GROQ_API_KEY` is not set, requests with confidence $< 0.60$ fall back to the keyword heuristics (`rule_fallback`), ensuring complete offline operability.
2. **Cold-Start History:** On a completely new installation or cold start, the in-memory `UserHistoryLayer` starts with zero user history and personalizes organically as feedback requests are posted.

