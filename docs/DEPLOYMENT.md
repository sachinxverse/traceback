# DEPLOYMENT.md — hosting limits, backups and the demo-day checklist (Issue 4)

Limits verified **2026-11-17** from the Render dashboard
(dashboard.render.com) and https://render.com/docs/free.

## 1. Current verified limits

| What | Limit (verified 2026-11-17) | Source |
|---|---|---|
| Free web service | 0.1 CPU, **512 MB RAM**, sleeps after ~15 min idle, wake ≈ 50 s | Render dashboard service page |
| Free PostgreSQL 16 | 1 GB storage, **expires 2026-12-16** unless upgraded | Render DB page ("expires Dec 16 2026 on free plan") |
| Free tier instances | One free web service + one free Postgres per workspace | render.com/docs/free |
| Build | pip install, no Docker build on free plan (torch image too heavy) | observed deploys |

## 2. If the database expires — continuity plan

`DATABASE_URL` is the only switch. Migration to a non-expiring external
Postgres (e.g. Neon free tier, or Supabase): create the target DB → run
`pg_dump` of the current DB (`scripts/backup_db.sh`) → `psql`/`pg_restore`
into the target (`scripts/restore_db.sh`) → update `DATABASE_URL` in
Render → redeploy → verify `/api/v1/health`. **Rollback:** flip
`DATABASE_URL` back to the old value and redeploy (the old DB is untouched
during migration).

Steps must be verified against the provider's current free-tier terms
before migrating — limits change.

## 3. Backups

- `scripts/backup_db.sh` — `pg_dump` of `DATABASE_URL` (custom format).
- `.github/workflows/backup.yml` — daily scheduled + manual dispatch;
  the dump is uploaded as a workflow artifact (14-day retention).
- `scripts/restore_db.sh` — restore into a fresh database; **verify with
  row counts before/after** (see the script's output).
- GitHub secret required: `DATABASE_URL` (Settings → Secrets → Actions).

## 4. Cold-start UX (implemented)

The frontend detects slow first responses (free tier sleeps after ~15 min
idle; waking takes up to ~50 s) and shows a "Waking up the server…"
banner with automatic retries instead of a silent hang or an error — see
`app/static/js/coldstart.js` and the banner markup in `base.html`.

## 5. Optional keep-alive — documented workaround, not hidden

An external uptime monitor (e.g. UptimeRobot) pinging
`/api/v1/health` every 10 minutes prevents sleeping. **This is a
workaround that may violate the spirit of the free tier** — use only
during demo days, do not leave it running permanently.

## 6. Migration safety

`flask init-db` runs `alembic upgrade head` only, is idempotent, and
**fails loudly** (non-zero exit) on any migration error — the deploy
stops instead of starting an app against a half-migrated schema.

## 7. Demo-day checklist

- [ ] Wake the app 2 minutes before the demo (open the URL, watch the
      cold-start banner clear).
- [ ] Verify `/api/v1/health` → `{"status":"ok"}`.
- [ ] Verify OTP email arrives (Brevo sender configured via env, code NOT
      shown in logs when `OTP_SENDER=email`).
- [ ] Have a local fallback ready: `.venv`, `flask run -p 5001` with
      SQLite + seed-demo, in case the venue wifi is down.
- [ ] Screenshot fallbacks in `docs/screenshots/` if everything fails.
- [ ] Check the DB expiry date in the Render dashboard before the event;
      if within 2 weeks, migrate per §2 first.
