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
