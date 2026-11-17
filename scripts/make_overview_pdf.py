# Generate TRACEBACK_Project_Overview.pdf from the project explanation.
# Run: .venv/Scripts/python.exe scripts/make_overview_pdf.py
from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONT_R = "C:/Windows/Fonts/segoeui.ttf"
FONT_B = "C:/Windows/Fonts/segoeuib.ttf"
FONT_I = "C:/Windows/Fonts/segoeuii.ttf"
FONT_M = "C:/Windows/Fonts/consola.ttf"

NAVY = (11, 31, 58)
BLUE = (29, 78, 216)
TEAL = (13, 148, 136)
AMBER = (146, 64, 14)
GREY = (90, 100, 114)
LIGHT = (245, 247, 250)


class PDF(FPDF):
    def __init__(self):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_auto_page_break(auto=True, margin=18)
        self.add_font("seg", "", FONT_R)
        self.add_font("seg", "B", FONT_B)
        self.add_font("seg", "I", FONT_I)
        self.add_font("mono", "", FONT_M)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("seg", "B", 9)
        self.set_text_color(*NAVY)
        self.cell(0, 8, "TRACEBACK — Project Overview", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(220, 226, 236)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-14)
        self.set_font("seg", "", 8)
        self.set_text_color(*GREY)
        self.cell(0, 8, f"Page {self.page_no()}/{{nb}}", align="C")

    # ---- building blocks -------------------------------------------------
    def h1(self, text):
        self.ln(2)
        self.set_font("seg", "B", 16)
        self.set_text_color(*NAVY)
        self.multi_cell(0, 8, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*BLUE)
        self.set_line_width(0.5)
        self.line(self.l_margin, self.get_y(), self.l_margin + 42, self.get_y())
        self.ln(3)

    def h2(self, text):
        self.ln(1.5)
        self.set_font("seg", "B", 11.5)
        self.set_text_color(*BLUE)
        self.multi_cell(0, 6.5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(0.5)

    def body(self, text, size=9.5):
        self.set_font("seg", "", size)
        self.set_text_color(40, 46, 56)
        self.multi_cell(0, 5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def bullet(self, text, indent=4):
        self.set_font("seg", "", 9.5)
        self.set_text_color(40, 46, 56)
        self.set_x(self.l_margin + indent)
        self.cell(4, 5, "\u2022")
        self.multi_cell(self.epw - indent - 4, 5, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def code(self, text):
        self.set_font("mono", "", 8.2)
        self.set_text_color(30, 41, 59)
        self.set_fill_color(*LIGHT)
        self.set_draw_color(214, 222, 235)
        self.multi_cell(0, 4.4, text, fill=True, border=1,
                        new_x=XPos.LMARGIN, new_y=YPos.NEXT, markdown=False)
        self.ln(1.5)

    def table(self, headers, rows, widths, header_fill=NAVY):
        from fpdf.fonts import FontFace
        self.set_font("seg", "", 8.6)
        self.set_draw_color(205, 213, 226)
        with FPDF.table(self, align="LEFT", line_height=4.6, borders_layout="ALL",
                        col_widths=widths, padding=1.4,
                        headings_style=FontFace(family="seg", emphasis="B",
                                                color=(255, 255, 255),
                                                fill_color=NAVY,
                                                size_pt=9)) as t:
            row = t.row()
            for h in headers:
                row.cell(h)
            for r in rows:
                row = t.row()
                for val in r:
                    row.cell(val)
        self.ln(2)


pdf = PDF()

# ================================================================== TITLE
pdf.add_page()
pdf.ln(30)
pdf.set_font("seg", "B", 34)
pdf.set_text_color(*NAVY)
pdf.cell(0, 14, "TRACEBACK", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
pdf.set_font("seg", "", 15)
pdf.set_text_color(*BLUE)
pdf.cell(0, 10, "AI-Powered Lost & Found Platform", new_x=XPos.LMARGIN,
         new_y=YPos.NEXT, align="C")
pdf.ln(2)
pdf.set_font("seg", "I", 11)
pdf.set_text_color(*GREY)
pdf.cell(0, 8, "Lost. Found. Reconnected.", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
pdf.ln(10)
pdf.set_draw_color(*TEAL)
pdf.set_line_width(0.8)
pdf.line(60, pdf.get_y(), 150, pdf.get_y())
pdf.ln(10)
pdf.set_font("seg", "", 10.5)
pdf.set_text_color(40, 46, 56)
pdf.multi_cell(110, 6, "Complete project explanation: purpose, architecture, tech stack and its role in every layer, feature walk-through, security model, how to run it, and key engineering decisions.",
               align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
pdf.ln(16)
pdf.set_font("seg", "B", 10)
pdf.set_text_color(*GREY)
pdf.cell(0, 7, "Flask + SQLAlchemy + JWT cookies + vanilla JS + Playwright-tested",
         new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
pdf.cell(0, 7, "Documentation set: README.md, docs/DECISIONS.md, docs/UI_AUDIT.md",
         new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")

# ============================================================== 1. IDEA
pdf.add_page()
pdf.h1("1. What the app does (the core idea)")
pdf.body("TRACEBACK connects people who lose items with the people who find them. "
         "An AI matching engine proposes candidate pairs, but no item ever changes "
         "hands without a human verifying the claim. The tagline is \u201cLost. Found. Reconnected.\u201d")
pdf.code(
"Lost report --+\n"
"               +--> AI matching engine --> ranked matches --> owner claims it\n"
"Found report --+                                                    |\n"
"                              human reviews claim <-- claimant submits\n"
"                                        |\n"
"                        handover --> recovery confirmed (audited, timed)")
pdf.h2("The happy path, step by step")
pdf.bullet("Someone loses an item and files a LOST report: photos, category, "
           "description, date/time, GPS location picked on a map, and optional "
           "private identifying details (serial numbers, marks) visible only to the owner and the claim reviewer.")
pdf.bullet("Someone finds an item and files a FOUND report the same way, with "
           "\u201ccustody\u201d recorded: I'm keeping it, or it's held at an institution.")
pdf.bullet("The matching engine compares pairs on four signals - image similarity, "
           "text similarity, location proximity, time proximity - and stores a "
           "weighted total score with a per-signal breakdown that users can see.")
pdf.bullet("Both owners are notified when a match is strong enough. The owner "
           "submits a claim with details only the true owner would know.")
pdf.bullet("A human reviewer (institution staff or admin) compares the claim "
           "against the found report's private details side-by-side and approves, "
           "rejects, or disputes it.")
pdf.bullet("Approved claims move through handover: the finder marks the item "
           "handed over, the owner confirms received, the claim completes and the "
           "report becomes RECOVERED. Every transition is audited and time-stamped.")

# ========================================================== 2. TECH STACK
pdf.add_page()
pdf.h1("2. Tech stack and where each piece is used")
pdf.table(
    ["Technology", "Where it is used in this project"],
    [
        ["Python 3.11+", "Entire backend (developed and verified on Python 3.14)."],
        ["Flask 3.x", "Application core: create_app() factory wires blueprints, error handlers and security headers."],
        ["Flask-SQLAlchemy 2.0.48 (from source)", "ORM models: User, Institution, Report, ReportImage, Match, Claim, ClaimImage, Message, Notification, AuditLog, TokenBlocklist, OtpChallenge."],
        ["Alembic + Flask-Migrate", "Schema migrations; migrations/versions/ holds the initial schema and the portals+OTP migration. flask init-db runs upgrade() only and fails loudly."],
        ["Flask-JWT-Extended", "Authentication: JWTs in HttpOnly cookies with CSRF double-submit; portal and token-version claims; jti blocklist for revocation."],
        ["Flask-Limiter", "Rate limits: register 5/min, login 10/min, change-password 5/min, geocode 1/sec."],
        ["Flask-Mail", "Email delivery of OTP codes (EmailOtpSender)."],
        ["marshmallow 3.x (pinned)", "Strict request validation schemas; unknown fields rejected."],
        ["PyTorch / open_clip (optional)", "Real image embeddings with CLIP ViT-B-32; installed behind a Docker build ARG."],
        ["sentence-transformers (optional)", "Real text embeddings with all-MiniLM-L6-v2."],
        ["Stub embedders (built-in)", "Deterministic fake vectors (8x8 colour block + border-colour one-hot) so the app runs with zero heavy dependencies and fast tests."],
        ["qrcode + Pillow", "Institution QR posters: GET /api/v1/institutions/{id}/qr.png."],
        ["Chart.js (CDN, pinned + SRI)", "Admin analytics: reports-per-day line chart and category bar chart."],
        ["Leaflet + OpenStreetMap tiles (CDN)", "Report map picker, match side-by-side map, admin heatmap."],
        ["Bootstrap 5.3 + Bootstrap Icons (CDN)", "Layout and components underneath the custom design system."],
        ["Plus Jakarta Sans + Inter", "Heading and body typography of the design system."],
        ["Vanilla JS (ES modules)", "All interactivity: api.js, notify.js, reports.js, claims.js, matches.js, map.js, admin.js, portal-login.js, register.js, register-otp.js, forgot-password.js, theme-init.js."],
        ["pytest + coverage", "235 API tests plus 13 Playwright tests; 82% coverage on app/services and app/api."],
        ["Playwright (headless Chromium)", "Real-browser end-to-end: full recovery flow, three portal logins, OTP UI, overflow checks, axe-core accessibility audit."],
        ["ruff", "Linting - all checks pass."],
        ["gunicorn + Docker + docker-compose", "Production deployment: Postgres, required secrets, no published DB port."],
        ["PostgreSQL", "Production database (SQLite for development; production refuses SQLite unless explicitly allowed)."],
    ],
    widths=(52, 128),
)
pdf.body("Design rule: blueprints validate input with marshmallow and call services; "
         "services own all business rules; models are pure data.")

# ====================================================== 3. ARCHITECTURE
pdf.add_page()
pdf.h1("3. Project architecture")
pdf.code(
"app/\n"
"  __init__.py        create_app() factory: blueprints, CSP, error handlers\n"
"  config.py          Base/Development/Testing/Production configs + validate()\n"
"  cli.py             init-db, create-admin, seed-demo, purge-otp, reindex, expire-reports\n"
"  api/               REST API, everything under /api/v1\n"
"    auth.py          3 portal logins + 2-step OTP + register + forgot-password\n"
"    _auth.py         current_user(), roles_required(), portal_required()\n"
"    reports.py       CRUD, close, rematch, matches listing\n"
"    matches.py       match detail, dismiss\n"
"    claims.py        submit, approve, reject, dispute, handover, confirm\n"
"    messages.py      thread between participants during a live claim\n"
"    admin.py         users, moderation, claims, recoveries, audit, analytics\n"
"    staff.py         institution-scoped staff endpoints\n"
"    institutions.py  CRUD, verified toggle, QR PNG\n"
"    meta.py          /meta (enums, map centre) + /stats/public (5-min cache)\n"
"    images.py        image serving with privacy guards\n"
"    health.py        health + Nominatim geocode proxy (1 req/sec)\n"
"  services/          business logic layer\n"
"    matching.py      candidate generation + weighted scoring\n"
"    embeddings.py    image/text embedders (lazy real backends, stub default)\n"
"    claims.py        claim state machine (row-locked, single APPROVED claim)\n"
"    otp.py           OTP generation/hashing/verification + sender interface\n"
"    notifications.py audit.py jobs.py analytics.py geo.py images.py storage.py\n"
"  models/            SQLAlchemy models (one module per domain)\n"
"  schemas/           marshmallow schemas\n"
"  templates/         Jinja2: base + 16 user pages + 7 admin + 6 staff pages\n"
"  static/            tokens.css + app.css design system, vanilla JS modules\n"
"scripts/             seed_demo.py, evaluate_matching.py\n"
"migrations/versions/ Alembic migration scripts\n"
"tests/               235 API tests + Playwright e2e + UI/a11y/overflow tests\n"
"docs/                DECISIONS.md, UI_AUDIT.md")

# ======================================================= 4. FEATURES
pdf.add_page()
pdf.h1("4. Feature walk-through")

pdf.h2("4.1 Separate login portals + mandatory OTP")
pdf.bullet("Three portals: /login (users), /staff/login, /admin/login - each with its own branding strip and copy, footer-only cross-links.")
pdf.bullet("Two-step login: credentials first return an OTP challenge and set NO cookies; only after the 6-digit code is verified are session cookies issued.")
pdf.bullet("Codes are generated with secrets.randbelow, stored as HMAC-SHA256 hashes, single-use, expire in 5 minutes, lock the challenge after 5 wrong attempts, respect a 30-second resend cooldown (3 resends max, 5 per email per hour) and are bound to portal + purpose + IP/user-agent hash.")
pdf.bullet("Tokens carry a portal claim; /api/v1/admin/* needs portal=admin and /api/v1/staff/* needs portal=staff, enforced at blueprint level so it cannot be bypassed in the UI.")
pdf.bullet("Wrong-portal credentials fail with the same generic \u201cInvalid credentials\u201d message as a wrong password, and the attempt is written to audit_logs.")
pdf.bullet("Registration ends in an email-verification OTP; unverified accounts cannot log in. Forgot-password and password/phone changes require fresh OTPs; a password change bumps token_version, revoking every session.")
pdf.bullet("Delivery: SMTP email (default), a console sender for development, and a pluggable SMS adapter. Development may echo the code in the UI (OTP_DEV_ECHO); production refuses to start with that flag or without a mail sender.")

pdf.h2("4.2 Matching engine (app/services/matching.py)")
pdf.bullet("Candidate generation: lost vs found pairs filtered by status, category allow-list, MATCH_MAX_DAYS (90) and MATCH_MAX_DISTANCE_KM (50).")
pdf.bullet("Scoring: image (embedding cosine), text (embedding cosine), location (exponential decay by km), time (exponential decay by days), combined with configurable MATCH_WEIGHTS (default 0.40 / 0.25 / 0.20 / 0.15).")
pdf.bullet("Band thresholds (IMG_LOW/HIGH, TXT_LOW/HIGH) convert raw cosine values into intuitive 0-100 sub-scores shown to users with a visible breakdown.")
pdf.bullet("Top-N matches (default 10) above MATCH_MIN_SCORE (0.45) are persisted; those above NOTIFY_MIN_SCORE (0.55) notify both owners.")
pdf.bullet("Evaluation (Issue 2): the evaluation harness reports sample sizes, Precision@1/3, Recall@3, MRR, FPR and 95% bootstrap CIs over a tune/test split. Accuracy claims require the labelled eval set - demo-data metrics have been retracted (see docs/EVAL_RESULTS.md); matches only notify, the claims workflow is the human confirmation.")

pdf.h2("4.3 Claim state machine (app/services/claims.py)")
pdf.bullet("States: PENDING, APPROVED, REJECTED, DISPUTED, HANDED_OVER, COMPLETED.")
pdf.bullet("Row-locked (with_for_update): only one APPROVED claim per found report can exist; recovered items are terminal (409).")
pdf.bullet("Approving a DISPUTED/REJECTED claim re-locks the item; disputes hold the item in CLAIM_PENDING; closing a report auto-rejects live claims.")
pdf.bullet("The reviewer sees the claimant's details and the found report's private details side-by-side, privately.")

pdf.add_page()
pdf.h2("4.4 Institution network")
pdf.bullet("Colleges, stations, malls and airports run QR posters; scanning lands on /i/{slug} with the location pre-filled into the report form.")
pdf.bullet("The staff portal (/staff) is scoped to the staff member's institution: dashboard, institution reports, claims to review, recoveries, QR poster download and analytics.")
pdf.bullet("Admins create staff/admin accounts (Admin > Users > Create staff/admin account, with an institution selector for staff); registration is user-portal only.")

pdf.h2("4.5 Roles and privacy")
pdf.bullet("Roles: USER, STAFF, ADMIN. Contact details are never shown between users; private identifying details are visible only during claim review.")
pdf.bullet("Report visibility: owner, admin, own-institution staff, or match counterpart only. Removed reports are visible only to owner/admin.")
pdf.bullet("Every state-changing action writes an audit_logs row (actor, action, target, IP).")

pdf.h2("4.6 Frontend and design system")
pdf.bullet("Custom \u201cCalm Trust, Warm Reunion\u201d design system: tokens.css holds the exact palette (navy #0B1F3A, blue #1D4ED8, teal #0D9488, amber #D97706) and app.css consumes only those variables.")
pdf.bullet("Dark mode via [data-theme=\"dark\"], applied before first paint and persisted in localStorage (light / dark / system).")
pdf.bullet("4-step report wizard: Photos, What is it, Where/when, Review - with autosave, progress bar and inline validation.")
pdf.bullet("CSP-safe: zero inline scripts anywhere (audit-verified); all CDN assets pinned to exact versions with sha384 integrity attributes.")
pdf.bullet("Accessibility: axe-core test enforces no critical/serious violations; skip link, focus rings, 44px targets, WCAG AA contrast; Playwright asserts no horizontal overflow at 375 / 768 / 1280 px on every page.")
pdf.bullet("Every list, table and chart handles three states: loading (skeleton), empty (friendly message + action) and error (retry). UI data comes from /api/v1/meta and /api/v1/stats/public, never hard-coded literals.")

pdf.h2("4.7 Security highlights")
pdf.bullet("JWTs in HttpOnly SameSite cookies + CSRF double-submit header on every state-changing request.")
pdf.bullet("Session revocation: jti blocklist (logout, portal switch) + token_version claim (password reset kills all devices).")
pdf.bullet("Progressive lockout (5 failures -> 15 minutes) with audit log and email alert; rate limits on all auth endpoints.")
pdf.bullet("Strict CSP (default-src 'self', jsdelivr-only), X-Frame-Options: DENY, nosniff, referrer-policy.")
pdf.bullet("Production validate() refuses placeholder/short secrets, SQLite (unless explicitly allowed), OTP_DEV_ECHO=true, and MAIL_ENABLED=false without a configured sender; seed-demo refuses to run in production.")

# ======================================================== 5. HOW TO RUN
pdf.add_page()
pdf.h1("5. How to run it")
pdf.code(
"cd traceback\n"
"python -m venv .venv\n"
".venv/Scripts/pip install -r requirements.txt\n"
"set APP_CONFIG=development\n"
"flask init-db        # applies Alembic migrations\n"
"flask seed-demo      # 5 users, 3 institutions, 16 reports, matches, claims\n"
"flask run            # http://127.0.0.1:5001")
pdf.body("Portals: /login (users), /staff/login (institution staff), /admin/login (administrators).")
pdf.body("Demo accounts (development only, created by flask seed-demo): alice@example.com / "
         "User@12345, staff@traceback.local / Staff@12345, admin@traceback.local / Admin@12345. "
         "In development the OTP appears in the UI (OTP_DEV_ECHO=true) and is printed to the "
         "server console; in production set the MAIL_* SMTP variables and every code is emailed.")
pdf.body("Run the tests:")
pdf.code(".venv/Scripts/python.exe -m pytest -q\n"
         "# 235 API tests + 13 Playwright tests, 0 warnings, 82% coverage")
pdf.body("Production (Docker): docker compose up -d --build with SECRET_KEY, "
         "JWT_SECRET_KEY and POSTGRES_PASSWORD set to 32+ random bytes; gunicorn "
         "serves the app behind the compose network with PostgreSQL.")

# ======================================================== 6. DECISIONS
pdf.h1("6. Key engineering decisions (docs/DECISIONS.md #1-46)")
pdf.bullet("Stub-by-default AI: heavy model dependencies are lazy-loaded; the deterministic stub embedder keeps tests fast and lets the app run with no downloads.")
pdf.bullet("JWT cookie portal claim enforced at blueprint level instead of URL-based permission checks.")
pdf.bullet("Token-version revocation: one integer bump kills all sessions on password reset, without per-jti bookkeeping.")
pdf.bullet("OTP hashed with HMAC and challenge-bound: a password-reset OTP can never complete a login.")
pdf.bullet("Human-verified handover as the trust core: the engine recommends, humans decide; every transition is audited.")
pdf.bullet("No inline JavaScript anywhere (CSP), tokens-first CSS, database-driven UI data, config-driven thresholds.")
pdf.ln(4)
pdf.set_font("seg", "I", 9)
pdf.set_text_color(*GREY)
pdf.multi_cell(0, 5, "Full per-item evidence, command outputs and the UI audit tables live in docs/UI_AUDIT.md and docs/DECISIONS.md in the repository.")

pdf.output("docs/TRACEBACK_Project_Overview.pdf")
print("written: docs/TRACEBACK_Project_Overview.pdf")
