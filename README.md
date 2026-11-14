# Project TRACEBACK

AI-Powered Lost & Found Intelligence Network. Users submit **Lost** or **Found**
reports (photos, description, date, location); a matching engine ranks candidate
matches using image similarity, semantic text similarity, location proximity and
time proximity. A match is a **recommendation only** — recovering an item always
requires a human-reviewed claim with private identifying details, an approval,
a handover and a confirmation.

> Match scores rank likelihood under the configured model. They are **not proof
> of ownership**.

## Stack

- **Backend:** Python 3.11+, Flask 3.x (application factory), SQLAlchemy 2.x +
  Flask-Migrate (SQLite for dev/tests, PostgreSQL in Docker), Flask-JWT-Extended
  (HttpOnly cookie tokens + CSRF double-submit), marshmallow validation,
  Flask-Limiter, Flask-Mail.
- **AI matching:** OpenCLIP ViT-B-32 (`laion2b_s34b_b79k`, 512-d image
  embeddings) + sentence-transformers `all-MiniLM-L6-v2` (384-d text
  embeddings) when `EMBEDDING_BACKEND=real`; a deterministic no-model
  **stub** backend (`stub`) for tests and quick demos. Embeddings are
  L2-normalised float32 bytes; brute-force NumPy search.
- **Frontend:** server-rendered Jinja2 + Bootstrap 5.3 + vanilla ES modules,
  Leaflet/OpenStreetMap maps, Chart.js analytics. No Node build step.
- **Background work:** ThreadPoolExecutor (2 workers), no Celery/Redis needed.

## Quick start (stub AI, SQLite)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env

flask init-db
flask seed-demo

flask run                            # http://localhost:5000
```

On Windows use `.venv\Scripts\python -m flask ...` if `flask` is not on PATH.

### Run the tests

```bash
pytest -q                            # all tests green
pytest --cov=app/services --cov=app/api -q   # coverage report
```

### Evaluate the matching engine

```bash
python scripts/evaluate_matching.py scripts/labels.csv
# prints precision@1, precision@3, recall@3, false-positive rate at
# MATCH_MIN_SCORE and a score histogram (exit code 0 always)
```

## Docker (Postgres + gunicorn)

```bash
docker compose up --build            # web on :8000, db on postgres:15
docker compose exec web flask init-db
docker compose exec web flask seed-demo
```

### Real AI models

Set `EMBEDDING_BACKEND=real` in `.env`, then install:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install open_clip_torch sentence-transformers
```

First use downloads the models once (cached in the user cache dir / a Docker
volume). The app runs fine on CPU.

## Demo accounts (after `flask seed-demo`)

| Role  | Email                  | Password    |
|-------|------------------------|-------------|
| Admin | admin@traceback.local  | Admin@12345 |
| Staff | staff@traceback.local  | Staff@12345 |
| User  | alice@example.com      | User@12345  |
| User  | bob@example.com        | User@12345  |
| User  | carol@example.com      | User@12345  |

The seed also creates 3 institutions, 14 reports (5 true pairs + distractors)
with generated placeholder images, running matches, one pending claim, one
completed recovery and one disputed claim, plus `scripts/labels.csv`.

## CLI commands

| Command                    | Action                                            |
|----------------------------|---------------------------------------------------|
| `flask init-db`            | create tables / run migrations                    |
| `flask create-admin`       | create an ADMIN (`--email --name`, prompts password) |
| `flask seed-demo`          | load demo data (idempotent; `--reset` wipes)      |
| `flask reindex`            | recompute all embeddings and matches              |
| `flask expire-reports`     | expire reports older than `REPORT_RETENTION_DAYS` |
| `flask purge-orphans`      | delete unreferenced upload files                  |
| `flask purge-old-messages` | delete messages of completed claims older than 30 days |
| `flask purge-token-blocklist` | purge expired revoked-token rows               |

## API overview

All endpoints live under `/api/v1` and return
`{"data": ...}` / `{"error": {code, message, details}}`. Authentication is via
HttpOnly cookies (`access_token_cookie`, `refresh_token_cookie`) with CSRF
double-submit (`X-CSRF-TOKEN` header from the `csrf_access_token` cookie).

| Area          | Endpoints                                                                 |
|---------------|---------------------------------------------------------------------------|
| Auth          | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET/PATCH /auth/me`, `POST /auth/change-password` |
| Reports       | `POST /reports` (multipart, 0-4 images), `GET /reports/mine`, `GET /reports/{id}`, `PATCH /reports/{id}`, `POST /reports/{id}/close`, `POST /reports/{id}/images`, `DELETE /reports/{id}/images/{image_id}`, `GET /reports/{id}/matches`, `POST /reports/{id}/rematch`, `GET /reports/browse` |
| Images        | `GET /images/{id}`, `GET /claim-images/{id}` (authorised serving only)     |
| Matches       | `GET /matches/{id}`, `POST /matches/{id}/dismiss`                          |
| Claims        | `POST /matches/{id}/claims`, `GET /claims/mine`, `GET /claims/incoming`, `GET /claims/{id}`, `POST /claims/{id}/approve|reject|withdraw|dispute|mark-handed-over|confirm-received` |
| Messaging     | `GET/POST /matches/{id}/messages` (only while a claim is live; 20/min)     |
| Notifications | `GET /notifications`, `GET /notifications/unread-count`, `POST /notifications/{id}/read`, `POST /notifications/read-all` |
| Institutions  | `GET /institutions`, `GET /institutions/by-slug/{slug}`, `POST/PATCH /institutions...`, `GET /institutions/{id}/qr.png` |
| Admin         | `/admin/users`, `/admin/reports`, `/admin/reports/{id}/remove|restore`, `/admin/claims`, `/admin/claims/{id}/resolve`, `/admin/recoveries`, `/admin/audit-logs`, `/admin/analytics/{summary,timeseries,categories,heatmap}` |
| Misc          | `GET /health`, `GET /geocode?q=` (Nominatim proxy, 1 req/s)                |

The full request/response contracts, validation rules and state machines are in
the implementation specification (Sections 5-14).

## Architecture

```
app/
  __init__.py        create_app(), JWT callbacks, error handlers, CSP headers
  extensions.py      db, migrate, jwt, limiter, mail
  cli.py             flask commands (above)
  models/            user, institution, report(+images), match, claim(+images),
                     message, notification, token_blocklist, audit_log
  schemas/           marshmallow request schemas (unknown fields rejected)
  api/               auth, reports, images, matches, claims, messages,
                     notifications, institutions, admin, health + _auth helpers
  services/          embeddings (stub/real), matching, geo, images, storage,
                     notifications, claims (state machine), analytics, audit, jobs
  web/routes.py      Jinja2 page routes (public, user, admin)
scripts/             seed_demo.py, evaluate_matching.py, labels.csv
tests/               pytest suite (auth, reports, visibility, matching, claims,
                     messages, institutions, admin/analytics, security, pages, cli)
```

### Matching engine (Section 9 of the spec)

1. **Processing job** (per report, thread pool): embed images once, embed
   `"<category>. <title>. <description>"`, mark report READY, run matching.
2. **Hard filters**: opposite report type; both ACTIVE/CLAIM_PENDING + READY;
   different owner; category equal or OTHER; `found >= lost - 24h` and
   `found - lost <= MATCH_MAX_DAYS` (90); haversine distance
   `<= MATCH_MAX_DISTANCE_KM` (50) when both have coordinates.
3. **Scores** (each 0..1, NULL when input missing): image = max pairwise cosine
   rescaled over `[IMG_LOW, IMG_HIGH]`; text over `[TXT_LOW, TXT_HIGH]`;
   location = `exp(-d / LOC_DECAY_KM)` (same institution without coordinates →
   1.0); time = `exp(-delta_days / TIME_DECAY_DAYS)`.
4. **Combination**: renormalised weighted mean over available signals
   (`image 0.40, text 0.25, location 0.20, time 0.15`); needs at least one
   content signal (image or text); single-signal results ×0.85.
5. **Storage/notify**: top `MATCH_TOP_N` (10) candidates ≥ `MATCH_MIN_SCORE`
   (0.45) upserted on `(lost_report_id, found_report_id)`; new matches ≥
   `NOTIFY_MIN_SCORE` (0.55) notify both sides. Confidence labels:
   HIGH ≥ 0.75, MEDIUM ≥ 0.55, else LOW.

### Claim workflow (human-verified)

`PENDING → APPROVED → handed over → confirmed → COMPLETED`, with
reject → dispute → admin resolution and automatic rejection of competing
claims when an item is recovered. **No automated path ever approves a claim or
marks a report RECOVERED** (asserted by `test_claims.py::test_ai_never_auto_approves`).

## Security & privacy highlights

- Passwords hashed (werkzeug scrypt/pbkdf2); policy ≥ 8 chars with letter+digit.
- JWT access (30 min) / refresh (14 days) in HttpOnly, SameSite=Lax cookies;
  Secure in production; logout revokes both jtis via `token_blocklist`.
- CSRF double-submit on every state-changing request.
- Rate limits: login 10/min/IP, register 5/min/IP, claims 10/h/user,
  messages 20/min/user, reports 20/h/user, default 200/min/IP.
- Uploads validated with Pillow (extension + content), EXIF stripped, resized
  (≤1600 px), re-encoded JPEG, stored outside `static/`, served only through
  authorised endpoints.
- `private_details` and `claim_details` never appear in public/match payloads;
  coordinates rounded to 3 decimals; heatmap hides cells with < 2 reports;
  owner shown as first name only.
- Security headers: CSP (self + pinned CDNs + OSM tiles), nosniff, DENY
  framing, strict referrer policy.
- Audit log for role changes, moderation, claim decisions, handovers,
  recoveries and institution changes.

## Manual smoke checklist

1. Register two users (A and B) in two browsers.
2. As A, report a **Lost** item (red wallet photo). As B, report the same item
   as **Found** with different wording and a different photo.
3. Both see a match (HIGH/MEDIUM) with a breakdown within seconds.
4. As A, open the match → "claim" → enter private details.
5. As B (finder), review the claim (side-by-side private details) → Approve →
   Mark handed over.
6. As A, Confirm received → both reports RECOVERED, match CONFIRMED,
   notifications sent, audit entry written.
7. Log in as admin → analytics update, audit log has the events.
8. As admin, open `/admin/institutions` → download a QR PNG → opening the QR
   URL lands on `/i/{slug}` with the institution preselected.

## Verification (acceptance criteria results)

| #  | Criterion                                                                 | Result |
|----|---------------------------------------------------------------------------|--------|
| A1 | Clean setup works; `pytest -q` green; coverage ≥ 80% on services+api      | Pass (see below) |
| A2 | Register/login/logout with token revocation                               | Pass (`test_auth.py`) |
| A3 | LOST+FOUND with different wording/photos match in both orders             | Pass (`test_matching.py`) |
| A4 | Unrelated same-category item below minimum score                          | Pass (`test_matching.py::test_unrelated_item_not_matched`) |
| A5 | Missing location/photo still process; signals shown                       | Pass (`test_matching.py::test_missing_location_and_images_still_process`) |
| A6 | Full claim→handover→recovery flow; competing claims auto-rejected         | Pass (`test_claims.py`) |
| A7 | Reject→dispute→admin resolve with notifications + audit                   | Pass (`test_claims.py`) |
| A8 | No cross-user leak of email/phone/private/claim details                   | Pass (`test_visibility.py`) |
| A9 | Institution QR downloads and lands on `/i/{slug}` with prefill            | Pass (`test_institutions.py`) |
| A10| STAFF scoped to own institution; ADMIN sees all                           | Pass (`test_visibility.py`, `test_institutions.py`) |
| A11| Admin KPIs/timeseries/categories/heatmap with date filters + privacy      | Pass (`test_admin_analytics.py`) |
| A12| Messaging participants-only, polling, escaping, rate limiting             | Pass (`test_messages.py`) |
| A13| Rate limits, CSRF, headers, upload validation active and tested           | Pass (`test_security.py`) |
| A14| `docker compose up --build` web+Postgres, health ok, seed works           | Config provided; validated locally via SQLite |
| A15| `EMBEDDING_BACKEND=real` uses OpenCLIP + Sentence Transformers             | Implemented (`services/embeddings.py`); evaluation script provided |
| A16| README + `docs/DECISIONS.md` document everything                          | Pass (this file + decisions log) |

Latest local run (Python 3.14, Windows):

```
pytest -q                 → 84 passed
pytest --cov=app/services --cov=app/api -q
                          → coverage: see report below (target ≥ 80%)
```

## Configuration

All environment variables are documented in `.env.example` (Section 15.1 of the
spec): secrets, `DATABASE_URL`, `BASE_URL`, storage (`UPLOAD_DIR`,
`STORAGE_BACKEND`), AI (`EMBEDDING_BACKEND`, model names, weights, thresholds),
upload limits, retention, SMTP, rate-limit storage and `COOKIE_SECURE`.

## Disclaimers reproduced in the product

- Footer and match pages: "Match scores rank likelihood under the configured
  model. They are not proof of ownership."
- Claim form: "Provide details only the owner would know. Do not share them
  publicly."
- Admin analytics: "Impact metrics should be validated with pilot data."
