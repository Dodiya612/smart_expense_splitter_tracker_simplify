# Assistant Evaluation Set (Task T-57 / Story US-24)

This directory holds the **frozen set of 60 questions** for the expense assistant (`POST /api/v1/ai/ask`). Done-when for T-57: **at least 90% correct on the 60 questions, and zero invented numbers**.

---

## Files

```
evals/assistant/
├── README.md        # This guide
├── questions.json   # The 60 questions with the expected tool, slots, period and figures
└── run_eval.py      # Live run against the Groq model (or --stub offline)
```

Each question in `questions.json` has:

| Field | Meaning |
|---|---|
| `question` | The question as a user would type it |
| `expected_tool` | One of the eight query tools, or `null` when no tool fits (another user's data, off-topic, prompt injection) |
| `expected_slots` | The slots that tool should get (`period`, `a`/`b`, `category`, `measure`, `n`, `limit`, `group`, `days`, `filters`, `sort`) |
| `expected_answer` | `tool` for an answer with figures, `fallback` when the assistant must decline with suggestions |
| `expected_reason` | For a fallback that states why (for example a group the user is not in) |
| `expected_period` | The inclusive range `{from, to, label}` for `reference_date` (2026-11-24, Asia/Kolkata); `null` for balances and several budgets |
| `expected_figures` | `[label, paise]` for every figure in the answer, for the dataset in `backend/tests/test_assistant_eval_pg.py` |
| `expected_counts` | `[label, value]` for every count in the answer |

Distribution: `spend_total` 8, `spend_by_category` 7, `compare_periods` 7, `top_merchants` 7, `budget_status` 7, `owed_summary` 7 (one for a group the user is not in), `recurring_upcoming` 7, `list_expenses` 7, no tool 3.

The expected figures were checked by hand against the dataset (for example this month's spending is ₹6,013.34: the personal expenses plus Alex's shares of the Swiggy dinner, the DMart bill and the chai; the deleted order, the settlement and other users' expenses never count).

---

## How it is measured

**In the test suite (no model, real PostgreSQL)**: `backend/tests/test_assistant_eval_pg.py` builds a throwaway database from the Alembic migrations, seeds personal and shared expenses, a settlement, a deleted expense, budgets, recurring rules and other users' data, and then for every question:

1. with a stubbed model that returns the expected tool call, it checks the tool, the slots, the exact period, and that every figure equals both the frozen value and the services (analytics, budgets, recurring, group balances) for that user and period (exact paise), and that no other user's data appears;
2. with the offline question parser (no model), it runs the same checks, which must pass for at least 54 of 60;
3. with an adversarial model that rewrites answers with wrong numbers (amounts divided by 100, paise shown as rupees, made-up percentages, number words, extra counts, wrong dates, shorthand, negative amounts, Devanagari digits, made-up Indian-grouped amounts), it checks that none reaches the user, while the right figure in Indian or western grouping is kept.

**Live, with the real model**: `run_eval.py` asks the Groq model to pick the tool for each question and to word each answer, then checks the choice and the final answer exactly as production does. It exits non-zero below 90% or if any invented number reaches an answer.

```bash
cd backend
GROQ_API_KEY=your-key PYTHONPATH=.. .venv/bin/python ../evals/assistant/run_eval.py
```

Options: `--timeout` seconds per call (default 10), `--delay` seconds between questions to stay under rate limits (default 2.5), `--stub` to check the runner offline without a key.
