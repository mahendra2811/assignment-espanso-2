# Evernine — Orders & Customers Analytics

Take-home for the Hive Full Stack Engineer (Backend) role.

A FastAPI + Postgres service that ingests a simulated e-commerce feed
(`orders.json` + `customers.csv`), treats it as untrusted third-party data,
and exposes analytics endpoints plus a small React dashboard.

The core design idea: **nothing about the messy feed is fixed silently.**
Every coercion, discard, and anomaly is recorded in a `data_quality_issues`
table during ingest and surfaced at `GET /api/data-quality`, so a business
owner (or the next engineer) can see exactly what the pipeline did.

---

## How to run

### Docker (recommended, one command)

```bash
docker compose up --build
```

That starts Postgres, runs the ingest (idempotent — safe to re-run), and
serves the API at **http://localhost:8000** (interactive docs at
`/docs`). Then, for the UI:

```bash
cd frontend
npm install
npm run dev        # → http://localhost:5173 (proxies /api to :8000)
```

<!-- ### Option B — no Docker (SQLite fallback)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./evernine.db   # any SQLAlchemy URL works
python -m app.ingest                          # prints the ingest summary
uvicorn app.main:app --port 8000
```

Postgres is the intended production database (and what docker-compose
runs); the code is dialect-portable so a reviewer without Docker can still
run everything, including tests. -->

### Tests

```bash
cd backend
.venv/bin/python -m pytest        # 29 tests, in-memory SQLite, < 1s
```

Tests are named after the feed's actual defects — e.g.
`test_conflicting_duplicate_keeps_latest_event`,
`test_refund_negative_total_is_valid_not_mismatch` — so the test list doubles
as a data-quality inventory.

---

## What's in the feed (found by inspection, none of it announced)

| Defect | Scale | Handling |
|---|---|---|
| Three `order_date` formats: ISO-8601 `Z`, `DD/MM/YYYY`, Unix epoch seconds as strings | 166 / 98 / 49 records | Explicit parser per format, everything normalised to UTC. Slash dates are day-first: 49 of 98 have day > 12, which is impossible month-first. |
| Duplicate `order_id`s | 28 (12 exact copies, 16 conflicting on `order_date` by minutes) | Simulates a re-delivered feed. Rule: **latest event wins** (max `order_date`, feed position as tie-break). Every discarded copy is logged (`duplicate_exact` / `duplicate_conflicting`). |
| Orders referencing customers absent from `customers.csv` | 5 orders (`CUST-9000`…) | Order kept (it's real revenue); a **flagged placeholder customer** (`is_placeholder = true`) is created so the FK holds. Logged as `unknown_customer`. |
| Refunded orders have negative `total_amount` (= −sum of line items) | all 12 refunds | Treated as feed semantics, **not** corruption: the stated total reverses the charge. Stored as-is; revenue metrics net refunds out. A total that disagrees with its line items in any other way is logged as `total_mismatch` (0 in this feed). |
| Blank customer emails | 4 rows | Stored as `NULL`, logged as `missing_email`. |
| Cancelled orders mixed in | 20 | Kept in the DB, excluded from all revenue metrics. |

Ingest summary for this feed: **313 order records → 285 unique orders**,
120 customers + 5 placeholders, 37 logged issues. Verify with
`GET /api/data-quality`.


## Schema decisions

```
customers            orders                order_items           (per ingest)
-----------          ------------------    ----------------      ingest_runs
customer_id PK  ←──  customer_id FK        order_id FK           data_quality_issues → run_id FK
name (nullable)      order_id PK           position, sku, name,
city (nullable)      order_date UTC tz     qty, unit_price
signup_date          status enum
email (nullable)     total_amount NUMERIC
is_placeholder       currency
```

- **Line items get their own table** rather than staying embedded JSON —
  that's what makes SKU-level questions ("top products", "units per order")
  answerable in SQL later.
- **`is_placeholder` on customers** keeps referential integrity without
  either dropping orphan orders or silently inventing customers — placeholder
  rows are visibly flagged and surface as `"Unknown"` in city analytics.
- **Stated `total_amount` is stored, not recomputed.** The feed's stated total
  is the financial fact; the line-item sum is a cross-check. Disagreements are
  flagged, never overwritten.
- **`data_quality_issues` + `ingest_runs`** make ingest observable and
  auditable across re-runs; issues are tied to the run that found them.
- **Ingest is an idempotent upsert** (merge + replace line items), because
  real feeds re-deliver — this one literally does. Re-running changes nothing
  but adds a new audit run.
- Schema is created via `metadata.create_all` — right-sized for a take-home;
  the first production step would be Alembic migrations.

## API

Interactive docs: http://localhost:8000/docs

| Endpoint | What it answers |
|---|---|
| `GET /api/metrics/revenue?granularity=day\|week\|month&from=&to=` | Revenue over time: gross, refunds, net per bucket + totals. Cancelled excluded, refunds netted. |
| `GET /api/customers/top?limit=&offset=` | Customers ranked by net spend (refunds subtract), paginated. |
| `GET /api/metrics/repeat-purchase-rate` | Share of purchasing customers with 2+ orders. |
| `GET /api/metrics/aov-by-city` | Average completed-order value per customer city. |
| `GET /api/orders?status=&customer_id=&from=&to=&limit=&offset=` | Paginated order browser with filters; `GET /api/orders/{id}` for line items. |
| `GET /api/data-quality?issue_type=` | Latest ingest run: summary, issue counts, individual issues. |
| `GET /health` | Liveness. |

Errors use a consistent envelope —
`{"error": {"code", "message", "details?"}}` — with correct status codes
(400 invalid range, 404 unknown order, 422 invalid params).

## Frontend

One screen (`frontend/`): net revenue over time with day/week/month toggle,
summary cards, a dependency-free bar chart, and the bucket table. It also
shows a banner with the ingest's data-quality issue count. Vite proxies
`/api` to the backend, so there's no CORS or host configuration.

## Project layout

```
backend/
  app/
    ingest/        parsers.py (date formats) · pipeline.py (validate/dedup/flag/upsert)
    routers/       metrics.py · customers.py · orders.py · data_quality.py
    models.py      SQLAlchemy schema        schemas.py   API response models
    errors.py      error envelope           main.py      app wiring
  tests/           parsers · ingest pipeline · API behaviour
frontend/          Vite + React + TS single screen
data/              orders.json · customers.csv (the provided feed)
docker-compose.yml Postgres + API (ingest runs on startup)
```

## Explicitly not done (per the brief)

Auth, deployment/hosting, visual polish, and extra data sources. Also
consciously skipped: Alembic migrations (noted above), and zero-filling empty
date buckets in the revenue endpoint (buckets exist only where orders exist).

## What I'd do next

1. Alembic migrations instead of `create_all`.
2. Incremental ingest keyed on a feed cursor + per-record content hash, so a
   nightly feed only touches changed orders.
3. A `products` dimension table derived from SKUs (top products endpoint).
4. Currency handling (minor-unit integers + conversion table) the moment a
   second currency appears.

<img width="1919" height="945" alt="Screenshot from 2026-07-23 12-28-44" src="https://github.com/user-attachments/assets/72496905-ebf8-45c6-b87e-3ce71c3f0cbb" />

<img width="1919" height="945" alt="Screenshot from 2026-07-23 12-29-06" src="https://github.com/user-attachments/assets/729e31c1-a964-469f-972d-22f9763bf9cb" /> 


<img width="1342" height="1289" alt="Screenshot from 2026-07-23 12-30-39" src="https://github.com/user-attachments/assets/1f2c747a-473b-47ba-b477-48c664390100" /> 
<img width="1342" height="1289" alt="Screenshot from 2026-07-23 12-30-44" src="https://github.com/user-attachments/assets/f2fca7ed-4e54-4d71-b69e-1c69c3dcaff5" />
<img width="1342" height="1289" alt="Screenshot from 2026-07-23 12-30-50" src="https://github.com/user-attachments/assets/3c60e7c7-c30e-4bbe-933b-463407a20b9a" />





