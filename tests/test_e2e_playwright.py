"""End-to-end browser test with Playwright (review D).

Runs a real Flask server on an ephemeral port (werkzeug make_server thread)
against a temp SQLite DB and drives a headless Chromium through the full
happy path: register two users, create LOST and FOUND reports with similar
descriptions, see the match, claim, approve, hand over, confirm, and view
analytics as admin. Skipped when Playwright browsers are not installed.
"""
import os
import socket
import threading
import time

import pytest

pw = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    from app import create_app
    from app.extensions import db as _db
    from app.services import storage as storage_mod
    from app.services.embeddings import reset_embedder

    reset_embedder()
    storage_mod.reset_storage()
    port = _free_port()
    db_dir = tmp_path_factory.mktemp("e2e")
    db_path = db_dir / "e2e.db"
    app = create_app("testing")
    app.config.update({
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "UPLOAD_DIR": str(db_dir / "uploads"),
    })
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    with app.app_context():
        _db.create_all()
        # pre-seed the admin account (registration-through-UI is exercised
        # with the two regular users; the admin is a setup concern)
        from app.models import User
        from app.models.enums import Role
        a = User(name="Admin E2E", email="e2e-admin@test.com", role=Role.ADMIN,
                 email_verified=True)
        a.set_password("Password1")
        _db.session.add(a)
        _db.session.commit()
    # NOTE: the Flask app runs in "testing" config (rate limiter off, sync jobs)
    # so the scripted flow is not throttled; the limiter itself is covered by
    # dedicated API tests.
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", port, app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(1.0)
    yield {"base": f"http://127.0.0.1:{port}", "app": app}
    server.shutdown()
    thread.join(timeout=5)


def _register(page, base, email, name):
    """Register through the UI and finish the OTP verification step (Part C)."""
    from app.services.otp import TestingOtpSender
    TestingOtpSender.reset()
    page.goto(f"{base}/register")
    page.fill("#name", name)
    page.fill("#email", email)
    page.fill("#password", "Password1")
    page.click("#register-form button[type=submit]")
    page.wait_for_selector("#register-otp-step:not(.d-none)", timeout=10000)
    code = TestingOtpSender.latest(email, "REGISTER")
    assert code, "no OTP recorded"
    boxes = page.locator("#register-otp-step .otp-digit")
    for i, ch in enumerate(code):
        boxes.nth(i).fill(ch)
    page.click("#reg-otp-verify")
    page.wait_for_url("**/dashboard", timeout=10000)


def _login(page, base, email, portal="user"):
    """Two-step login through the UI (Part C)."""
    from app.services.otp import TestingOtpSender
    TestingOtpSender.reset()
    login_path = {"user": "/login", "staff": "/staff/login", "admin": "/admin/login"}[portal]
    page.goto(f"{base}{login_path}")
    page.fill("#email", email)
    page.fill("#password", "Password1")
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#otp-step:not(.d-none)", timeout=10000)
    code = TestingOtpSender.latest(email)
    assert code, "no OTP recorded"
    boxes = page.locator("#otp-step .otp-digit")
    for i, ch in enumerate(code):
        boxes.nth(i).fill(ch)
    page.click("#otp-verify")
    page.wait_for_url("**/dashboard" if portal == "user" else
                      ("**/admin" if portal == "admin" else "**/staff"), timeout=10000)


def _logout(page):
    page.evaluate(
        "fetch('/api/v1/auth/logout', {method:'POST', headers:{'X-CSRF-TOKEN': document.cookie.match(/csrf_access_token=([^;]+)/)[1]}})")
    page.wait_for_timeout(400)


def _fill_report(page, base, rtype, title, description):
    page.goto(f"{base}/report/{rtype}")
    # 4-step wizard: photos -> item -> where/when -> review
    page.click("#step-next")                       # step 1: photos (optional)
    page.click(".category-cell[data-value='WALLETS_CARDS']")
    page.fill("#title", title)
    page.fill("#description", description)
    if rtype == "found":
        page.check("#custody1")
    page.click("#step-next")                       # step 3
    page.fill("#incident_date", "2026-01-10T12:30")
    page.click("#step-next")                       # step 4: review
    page.click("#submit-btn")
    page.wait_for_url("**/reports/*", timeout=15000)
    # wait for processing to finish (sync jobs in testing config)
    page.wait_for_timeout(800)


@pytest.mark.e2e
def test_e2e_full_recovery_flow(live_server):
    base = live_server["base"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx_a = browser.new_context()
        ctx_b = browser.new_context()
        ctx_admin = browser.new_context()
        alice, bob, admin = ctx_a.new_page(), ctx_b.new_page(), ctx_admin.new_page()

        # 1) register the two users via the UI
        _register(alice, base, "e2e-alice@test.com", "Alice E2E")
        _register(bob, base, "e2e-bob@test.com", "Bob E2E")

        # 2) create the LOST and FOUND reports (similar descriptions)
        _fill_report(alice, base, "lost",
                     "Blue leather wallet lost near library",
                     "Lost my blue leather wallet near the library lawn with a student ID inside.")
        lost_url = alice.url
        _logout(alice)
        _fill_report(bob, base, "found",
                     "Blue leather wallet found at library",
                     "A blue leather wallet was found on a bench near the library with an ID card inside.")

        # 3) alice logs in, opens the match and submits a claim
        _login(alice, base, "e2e-alice@test.com")
        alice.goto(lost_url)
        alice.wait_for_selector("a[href*='/matches/']", timeout=10000)
        alice.click("a[href*='/matches/']")
        alice.wait_for_selector("#claim-form", timeout=10000)
        alice.fill("#claim_details",
                   "It is my wallet: blue leather, initials A.R. inside, student ID with my photo, cash inside.")
        alice.click("#claim-form button[type=submit]")
        # after reload the match page shows the pending claim -> open it
        alice.wait_for_selector("a:has-text('Open claim')", timeout=15000)
        alice.click("a:has-text('Open claim')")
        alice.wait_for_url("**/claims/*", timeout=10000)
        claim_url = alice.url

        # 4) bob (finder) approves and marks handover
        _logout(bob)
        _login(bob, base, "e2e-bob@test.com")
        bob.goto(claim_url)
        bob.wait_for_selector("[data-action='approve']", timeout=10000)
        bob.click("[data-action='approve']")
        bob.wait_for_selector("[data-action='mark-handed-over']", timeout=10000)
        bob.click("[data-action='mark-handed-over']")
        # after reload the timeline shows Submitted + Reviewed + Handed over done
        # (polling instead of wait_for_function: our CSP forbids eval)
        for _ in range(20):
            if bob.locator(".step-timeline .step.done").count() >= 3:
                break
            bob.wait_for_timeout(500)
        assert bob.locator(".step-timeline .step.done").count() >= 3

        # 5) alice confirms receipt -> recovery completed
        _logout(alice)
        _login(alice, base, "e2e-alice@test.com")
        alice.goto(claim_url)
        alice.wait_for_selector("[data-action='confirm-received']", timeout=10000)
        alice.click("[data-action='confirm-received']")
        alice.wait_for_selector("text=recovered", timeout=10000)

        # 6) the pre-seeded admin logs in and checks analytics
        _login(admin, base, "e2e-admin@test.com", portal="admin")
        admin.goto(f"{base}/admin")
        admin.wait_for_selector("h1:has-text('Admin portal')", timeout=10000)
        # KPI cards load from the analytics summary API
        admin.wait_for_selector("#kpi-cards .col-lg-3, #kpi-cards .col-md-6, #kpi-cards > div",
                                timeout=10000)
        admin.goto(f"{base}/admin/recoveries")
        admin.wait_for_selector("text=Blue leather wallet", timeout=10000)

        # 7) responsive sanity: no horizontal scroll at 375px
        for page_, name in ((alice, "alice"), (bob, "bob"), (admin, "admin")):
            page_.set_viewport_size({"width": 375, "height": 800})
            page_.goto(f"{base}/dashboard" if name != "admin" else f"{base}/admin")
            page_.wait_for_timeout(300)
            scroll_w = page_.evaluate("document.documentElement.scrollWidth")
            client_w = page_.evaluate("document.documentElement.clientWidth")
            if scroll_w > client_w + 2:
                offenders = page_.evaluate(
                    """(() => { const out = [];
                       document.querySelectorAll('body *').forEach(e => {
                         const r = e.getBoundingClientRect();
                         if (r.right > 377) out.push(e.tagName + '|' + (e.className||'').toString().slice(0,40) + '|w=' + Math.round(r.width) + '|r=' + Math.round(r.right)); });
                       return out.slice(0, 8); })()""")
                print("OFFENDERS", name, offenders, flush=True)
            assert scroll_w <= client_w + 2, \
                f"{name}: horizontal scroll at 375px ({scroll_w}>{client_w})"

        browser.close()


@pytest.mark.e2e
def test_e2e_coldstart_link_interception(live_server):
    """Internal link clicks wake a sleeping instance first (Issue 4.4 UX).

    Warm path: /health answers fast -> the click navigates immediately.
    Simulated cold path: /health is delayed via Playwright routing -> the
    coldstart banner must appear BEFORE navigation completes.
    """
    base = live_server["base"]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        # warm path: clicking the hero CTA navigates straight to the login
        # redirect (the report form requires auth)
        page.goto(f"{base}/")
        page.click("a[href='/report/lost']")
        page.wait_for_url("**/login?next=/report/lost", timeout=10000)

        # simulated cold path: delay the health endpoint 3s so the click
        # handler takes the banner branch
        page.route("**/api/v1/health", lambda route: (
            page.wait_for_timeout(3000) or route.continue_()))
        page.goto(f"{base}/")
        page.click("a[href='/report/found']")
        page.wait_for_selector("#coldstart-banner", timeout=8000)
        # navigation still completes once the health check answers
        page.wait_for_url("**/login?next=/report/found", timeout=15000)

        browser.close()
