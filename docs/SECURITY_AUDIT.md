# SECURITY_AUDIT.md — secrets & personal-data scan (Issue 6)

Scan date: **2026-11-17**. Tool: `detect-secrets` 1.5 (all repo files) plus
targeted `git log --all -S` searches for every secret value used during
deployment (database password, Brevo key, admin password, both personal
email addresses).

## Scan result

- `detect-secrets scan --all-files`: **25 findings, all false positives**:
  - `app/templates/base.html` — CDN **SRI integrity hashes** (intended).
  - `migrations/versions/*` — Alembic revision hex ids (intended).
  - `tests/*` — the word "password" next to obviously fake test passwords
    (`Password1`), test fixtures only.
  - `scripts/restore_db.sh` — the word "backup" in a usage string.
  - `.pytest_cache` — cache metadata (not committed; gitignored).
- `git log --all -S <secret>` for the deployment-time database password,
  Brevo SMTP key, admin password and both personal Gmail addresses:
  **zero matches** — none of these were ever committed; they exist only in
  the Render dashboard environment and provider dashboards.
- Personal emails in code/docs/PDFs: none (grep for the two addresses in
  every tracked file returns nothing; PDF generators reference only
  "a verified sender address configured in the environment").

## Secrets that exist outside the repository (owner-managed)

| Secret | Where it lives | Rotation |
|---|---|---|
| Postgres password | Render dashboard env `DATABASE_URL` | rotate in Render DB page ("Credential rotation"), then update `DATABASE_URL` |
| `SECRET_KEY`, `JWT_SECRET_KEY` | Render dashboard env | replace with new `secrets.token_urlsafe(32)` values and redeploy |
| Brevo SMTP key | Brevo dashboard (SMTP & API) | regenerate key in Brevo, update `MAIL_PASSWORD` |
| Admin password | known to owner only | change via the profile page after first login |
| GitHub Actions `DATABASE_URL` secret | repo Settings → Secrets | update after DB rotation |

**Rotation is an owner task** (provider dashboards cannot be accessed by
the codebase). If any of these are ever exposed: rotate first, then purge
history with `git filter-repo`, then force-push.

## Prohibitions enforced by tests

- `tests/test_no_bypass.py::test_no_hardcoded_localhost_or_dummy_links` —
  fails on `localhost` strings, dead links and demo credentials in
  shipped templates/JS.
- `tests/test_no_passwordless.py` — wording guard (Issue 3); the file's own
  name embeds the banned term, so the guard whitelists its own filename.
- `.gitignore` covers `.env*` (`!*.env.example`), `*.db`, `instance/`,
  `uploads/`, `.venv/`, `*.pem`, `*.key`, `*.dump`, coverage and caches.
- `.github/workflows/backup.yml`'s `DATABASE_URL` is a GitHub **secret**,
  never echoed.

## Repository visibility

The repository is public (github.com/sachinxverse/traceback). Content
audit confirmed it contains no personal data beyond the author credit the
owner chose (the GitHub username). Demo accounts use `@example.com`.
