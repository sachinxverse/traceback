# Implementation decisions log

Every assumption made while implementing the specification is recorded here,
as required by Section 1.2 and acceptance criterion A16.

| # | Topic | Decision | Rationale |
|---|-------|----------|-----------|
| 1 | marshmallow version | Pinned to 3.26.x as the spec requires; 4.x changed enough APIs to risk subtle validation differences. | Spec Section 4 pins marshmallow 3. |
| 2 | Python version | Implemented and tested on Python 3.14 (local machine). Code targets 3.11+; Dockerfile uses python:3.11-slim. | Spec requires 3.11+; local env had 3.14. |
| 3 | Heavy AI dependencies | `torch`, `open_clip_torch`, `sentence-transformers` are **not** in `requirements.txt`; the app imports them lazily inside `RealEmbedder` only when `EMBEDDING_BACKEND=real`. Install commands are documented in `requirements.txt` comments and the README. | The stub backend must run without downloading models; keeping GB-sized GPU/CPU wheels out of the default install keeps `pip install` and CI fast. `EMBEDDING_BACKEND=real` requires the documented extras. |
| 4 | Claim reviewer for AT_INSTITUTION custody | Any active STAFF member of the found report's institution may review (the claim's `reviewer_id` records who acted). ADMIN may always review/resolve. | Spec Section 6 "Who reviews a claim". |
| 5 | Lost-report status on claim rejection | The lost report returns to ACTIVE only if no other live claim exists on the match; otherwise it stays CLAIM_PENDING. | Spec 10.1 state machine; keeps consistency with the found report. |
| 6 | Multipart parsing | `POST /reports` and `POST /matches/{id}/claims` accept `multipart/form-data`; scalar fields are validated through the same marshmallow schemas as JSON requests. | Spec 7.4/7.5. |
| 7 | Report edit re-queue | Editing any matching-relevant field (category/title/description/date/coordinates/location_text) sets `processing_status=PENDING` and re-runs the synchronous processing job in tests / enqueues in dev. | Spec 7.4. |
| 8 | Stub image embedder | Literal implementation of the spec formula (8×8×3 downsample projected to 512-d, L2-normalised). Note: solid single-colour images produce proportional vectors (cosine 1.0), so demo/test images use a coloured field with a small white mark to give distinct directions. | Spec 9.2 formula kept verbatim; test imagery adjusted instead of changing the specified algorithm. |
| 9 | Rate-limit tests | Flask-Limiter skips registering hooks when disabled at init, so rate-limit tests create a dedicated app via `create_app("testing", ratelimit_enabled=True)`. | Flask-Limiter 4.x behaviour. |
| 10 | Logout semantics | `POST /auth/logout` requires a valid access *or* refresh token; both jtis are blocklisted and cookies are cleared. | Spec 7.3 "Revokes current access and refresh tokens". |
| 11 | Refresh endpoint | Uses `@jwt_required(refresh=True)` + `get_jwt_identity()` directly (calling `current_user()` would re-verify as an access token and trip CSRF double-submit with the refresh header). | Flask-JWT-Extended cookie semantics. |
| 12 | Timeseries range | `from`/`to` are ISO dates; the range is filled day-by-day from `from` up to and including `to`. | Sensible interpretation of Section 14. |
| 13 | Geocode proxy | In-memory 1 req/sec throttle + per-query cache keyed on the query string; failures return an empty result list rather than erroring the page. | Spec 11.3. |
| 14 | Messaging lifecycle | Messages remain queryable; `flask purge-old-messages` deletes those on COMPLETED claims older than 30 days. | Spec 10.4. |
| 15 | QR landing prefill | `/i/{slug}` links to `/report/lost?institution={slug}` and `/report/found?institution={slug}`; the report form preselects the institution and its coordinates as the map pin. | Spec 11.3/13. |
| 16 | Institution analytics scoping | STAFF analytics endpoints automatically filter by their institution; `institution_id` query params are accepted for ADMIN only. | Spec 14. |
| 17 | Report close rule | A report with an APPROVED claim cannot be closed (409). Closing expires SUGGESTED matches. | Spec 7.4. |
| 18 | Public report payload | Includes `owner_first_name` (first name only) and institution summary; never email/phone/private_details. | Spec Section 6 public fields list. |
| 19 | Emails | When `MAIL_ENABLED=false` the email step is skipped entirely (notifications still land in-app); failures during send are logged and swallowed. | Spec Section 12. |
| 21 | SQLAlchemy build | The dev/test venv installs SQLAlchemy from source (`pip install --no-binary sqlalchemy SQLAlchemy==2.0.48`) because the pre-built Cython wheel of `sqlalchemy.sql._cache_key_cy` crashes under coverage tracing on some Python builds ('InternalTraversal' object is not callable). The pinned version runs fine from wheels in normal operation. | Allows the required `pytest --cov` runs. |
| 20 | testing debug artifact | `tests/test_zdebug3.py` was reduced to a placeholder comment after debugging (safe to delete). It contains no active tests. | Cleanup during development. |

## Decisions from the independent review fixes (2026-11-16)

22. **Single APPROVED claim per found item (A1).** `approve_claim` re-checks
    APPROVED claims on the same found report inside a row-locked transaction
    (`with_for_update()`; a no-op on SQLite, a real lock on PostgreSQL). A
    second approval returns 409 CONFLICT.
23. **Recovered items are terminal (A2).** `dispute_claim` and `approve_claim`
    refuse when the found or lost report is RECOVERED (409 "Item already
    recovered"). Approving a previously-released (DISPUTED/REJECTED) claim
    re-locks the item: both reports -> CLAIM_PENDING, match -> CLAIMED.
24. **Closing/removing a report cancels its live claims (A3).** PENDING and
    DISPUTED claims are auto-rejected with the note "Item report was closed",
    the counterpart report returns to ACTIVE, matches expire and claimants
    are notified. Closing with an APPROVED claim stays blocked (409).
25. **Dispute holds the item (A5).** While a claim is DISPUTED the found
    report stays CLAIM_PENDING and the match CLAIMED; new claims on the held
    item are refused (409). Admin REJECT releases the lock; admin APPROVE
    keeps it through the approve path.
26. **Audit from/to capture (A4).** Every claim transition logs
    `{"from": old_status, "to": new_status}` captured BEFORE the change; the
    rejection notification carries `related_match_id = claim.match_id`.
27. **Registration reveals existing emails (C4).** Kept the spec's 409
    CONFLICT on duplicate email: the UX benefit for the target user outweighs
    the enumeration leak, and the register endpoint is rate-limited
    (5/min) which blunts enumeration attempts.
28. **Login lockout (C4).** After 5 failed logins for one (email, IP) within
    15 minutes the account is locked for 15 minutes (429 with
    retry_after_seconds). In-memory per-app store; successful login resets.
29. **Alembic is the only schema path (B3).** The committed initial migration
    creates the full schema; `flask init-db` runs `upgrade()` only and fails
    loudly (no create_all fallback, no swallowed errors).
30. **Production refuses weak secrets (B2).** `ProductionConfig.validate()`
    rejects placeholder values and keys < 32 chars; docker-compose requires
    SECRET_KEY / JWT_SECRET_KEY / POSTGRES_PASSWORD via `${VAR:?}` and does
    not publish the database port.
31. **Stub embedder colour signature (C2).** The stub image vector combines a
    muted 8x8 RGB block with a strong one-hot border-colour signature so
    different-coloured items no longer look near-identical (identical images
    still score 1.0).
32. **Real-backend FPR accepted (C2).** The real backend's 0.188 false-positive
    rate comes from wallet-vs-wallet hard negatives; matches only notify —
    the claims workflow remains the human confirmation step.
33. **CDN assets pinned with SRI (C4).** All libraries pinned to exact
    versions with sha384 integrity + crossorigin; Leaflet moved to
    cdn.jsdelivr.net so the CSP allows a single script/style host.
34. **Design system in a token layer (theme).** All colours/radii/shadows/fonts
    live in `static/css/tokens.css` (`:root` + `[data-theme="dark"]`);
    `app.css` consumes only the variables. Dark mode is applied before first
    paint by `theme-init.js` (set in `<head>` before any CSS) and persisted in
    `localStorage['tb-theme']` (light / dark / system).
35. **CSP forbids inline scripts — externalised all JS (theme).** The CSP
    (`script-src 'self' cdn.jsdelivr.net`) silently blocked every inline
    `<script type="module">` (theme bootstrap, notifications read-all,
    institutions search, register validation) and the old theme-init inline
    script never ran in production. All moved to files under `static/js/`;
    the theme bootstrap is a classic script in `<head>`.
36. **Shared 1200px container on every page (U1-U3).** `.tb-container` /
    `.container` share one rule (max-width 1200px, fluid padding). Pages that
    lacked a wrapper (browse, claims, profile, notifications, dashboard,
    report/match detail, QR landing) were wrapped; `.section-pad` uses
    `padding-block` so the shorthand cannot zero the container's horizontal
    padding again (that exact bug caused an 8px overflow on the landing page).
37. **Tables scroll inside their card (U-restart).** Admin tables are wrapped
    in `.table-scroll` (min-width 640px inside a horizontally scrolling
    container) so the page itself never scrolls horizontally at 375px.
38. **Report form is a 4-step wizard with autosave (theme).** Steps: Photos →
    What is it → Where/when → Review. Progress bar, Back/Next with inline
    per-step validation, review summary, sticky bottom action row on phones;
    text/category/custody draft autosaves to localStorage (photos cannot be
    persisted and are treated as optional), draft cleared after submit.
    Leaflet gets `invalidateSize()` when the map step becomes visible.
39. **Profile page rebuilt (theme).** The committed profile.html was truncated
    mid-attribute (no closing tags, no `{% endblock %}`) — /profile could not
    render. Rewritten as a two-column card layout (details + change password)
    matching auth.js's `profile-form` / `password-form` ids.
40. **AA contrast verified with axe-core (theme).** axe-core runs in
    `tests/test_ui_theme.py` and fails on any critical/serious violation on 6
    key pages; fixes applied: amber buttons/badges use `--amber-700`
    (#92400E), muted text #5A6472, underline on auth links, aria-label on the
    browse category select. Playwright tests also assert zero horizontal
    overflow on every page at 375/768/1280 and theme persistence across
    reload.
41. **Three separate login portals (Part B).** `/login` (user), `/staff/login`,
    `/admin/login`, each with its own branding strip, copy and API
    (`/api/v1/auth/{user,staff,admin}/*` sharing one service). Wrong-portal
    credentials fail with the same generic "Invalid credentials" as a wrong
    password and are written to `audit_logs` (`login_wrong_portal`). The JWT
    carries a `portal` claim; `/api/v1/admin/*` requires `portal=admin`,
    `/api/v1/staff/*` requires `portal=staff` (blueprint `before_request`
    guards), and staff-only dashboards moved from `/admin` to `/staff`
    (institution-scoped reports/claims/recoveries/analytics/QR poster).
    Admin > Users can now create staff/admin accounts
    (`POST /api/v1/admin/users`) with an institution selector for staff.
42. **Mandatory OTP on every login (Part C).** Two-step login: step 1 returns
    `otp_required` + challenge id and sets NO cookies; step 2 verifies the
    code and is the only path that issues session cookies. Codes: 6 digits
    from `secrets.randbelow`, stored as HMAC-SHA256 (key = SECRET_KEY, message
    = challenge_id:code), verified with `hmac.compare_digest`, single-use,
    5-minute expiry, 5 wrong attempts → challenge locked, 30 s resend cooldown,
    3 resends max, 5 requests per email per hour, bound to portal + purpose +
    IP/UA hash. Only LOGIN/REGISTER challenges can complete a login (a
    PASSWORD_RESET challenge can never sign someone in). Registration creates
    unverified accounts and requires an OTP; unverified users cannot log in.
    Forgot-password and password/phone changes require fresh
    SENSITIVE_ACTION/PASSWORD_RESET OTPs; a reset bumps `token_version` so all
    existing sessions die. OTP_DEV_ECHO exists only for development and
    production refuses to start when it is set (or when MAIL_ENABLED=false
    without an alternative sender).
43. **Session revocation model.** Logging into a second portal blocklists the
    browser's current token jti before issuing the new session (B1.4);
    password reset/change bumps `users.token_version` which is embedded as the
    `tv` claim and checked in `current_user()` — one int bump revokes tokens
    across all devices without per-jti bookkeeping.
44. **OTP delivery channel interface (C3).** `OtpSender` with `EmailOtpSender`
    (Flask-Mail, default), `ConsoleOtpSender` (development: prints to the
    server console only), `SmsOtpSender` (pluggable adapter; needs a paid
    provider and E.164 numbers) and `TestingOtpSender` (test double recording
    codes in memory). There is no skip-OTP switch anywhere.
45. **Data-driven UI (Part D).** New `GET /api/v1/meta` serves
    categories/institution types/statuses/map centre/limits to JS;
    `GET /api/v1/stats/public` (5-minute cache) feeds the landing counters.
    The localhost fallback in the QR builder was removed, `MAP_DEFAULT_CENTER`
    moved to config, login lockout thresholds moved to config. Admin
    institutions verified toggle is now wired end-to-end; admin Users edit
    uses a real modal (no browser `prompt`); admin claims filter tabs are
    real buttons. `seed-demo` refuses to run in production.
46. **UI audit (Part A).** Full Playwright crawl of every page × role × 375/1280
    with per-element classification is in `docs/UI_AUDIT.md`; final state: every
    element WORKS or was implemented-for-real; a guard test
    (`test_no_bypass.py::test_no_hardcoded_localhost_or_dummy_links`) fails the
    build on `localhost`, `javascript:` URLs, dead `href="#"` anchors, and demo
    credentials in templates/JS.

## Decisions from the Render production deployment (2026-11-17)

47. **Portable migration backfill.** The portals/OTP migration backfilled
    `UPDATE users SET email_verified = 1`, which SQLite accepts but PostgreSQL
    rejects (`DatatypeMismatch`: boolean vs integer). Fixed to
    `SET email_verified = TRUE`, valid on both. Local SQLite tests masked the
    bug — production staging caught it.
48. **Render free-tier hosting.** Web service runs Python 3 (not Docker:
    free plan cannot build torch) with build `pip install -r requirements.txt`
    and start `flask init-db && gunicorn -w 2 -k gthread --threads 4
    --timeout 120 -b 0.0.0.0:$PORT wsgi:app`. Env: `APP_CONFIG=production`,
    managed Postgres via `DATABASE_URL`, `COOKIE_SECURE=true`,
    `EMBEDDING_BACKEND=stub` (real torch needs a paid plan; stub preserves
    P@1=1.0), `OTP_SENDER=console` (codes appear in server logs — upgrade to
    an SMTP sender for real email delivery). Production config validation
    (32+ char secrets, mail checks) is active and proved itself: two deploys
    failed fast until real secrets were set.
49. **Admin bootstrap without SSH.** Free tier has no shell access, so the
    first admin was inserted directly into Postgres (via the external DB
    URL) using the app's own `werkzeug` password hashing, mirroring
    `flask create-admin`. Subsequent admins can be created the same way or
    by upgrading the plan for SSH.
