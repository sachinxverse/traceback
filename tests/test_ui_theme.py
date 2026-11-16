"""UI/UX redesign verification (addendum U1-U10 + theme acceptance checks).

- overflow check on every page at 375 / 768 / 1280 px
- theme toggle persistence (localStorage, survives reload)
- report stepper: forward/back navigation, autosave restoration
Skipped when Playwright browsers are not installed.
"""
import os
import socket
import threading
import time

import pytest

pw = pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def ui_server(tmp_path_factory):
    from app import create_app
    from app.extensions import db as _db
    from app.services.embeddings import reset_embedder
    from app.services import storage as storage_mod
    from app.models import User
    from app.models.enums import Role

    reset_embedder()
    storage_mod.reset_storage()
    port = _free_port()
    db_dir = tmp_path_factory.mktemp("ui")
    db_path = db_dir / "ui.db"
    app = create_app("testing")
    app.config.update({
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "UPLOAD_DIR": str(db_dir / "uploads"),
    })
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    with app.app_context():
        _db.create_all()
        a = User(name="Admin UI", email="ui-admin@test.com", role=Role.ADMIN,
                 email_verified=True)
        a.set_password("Password1")
        u = User(name="User UI", email="ui-user@test.com", email_verified=True)
        u.set_password("Password1")
        _db.session.add_all([a, u])
        _db.session.commit()
        _db_by_email["ui-admin@test.com"] = "admin"
        _db_by_email["ui-user@test.com"] = "user"
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", port, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(1.0)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    thread_deadline = 5
    del thread_deadline
    thread = None


PAGES_PUBLIC = ["/", "/institutions", "/login", "/register", "/how-it-works"]
WIDTHS = [375, 768, 1280]
_db_by_email = {}  # email -> portal, filled by the ui_server fixture


def _login(page, base, email):
    """Two-step login through the real UI (Part C), on the correct portal."""
    from app.services.otp import TestingOtpSender
    TestingOtpSender.reset()
    portal = _db_by_email.get(email, "user")
    login_path = {"user": "/login", "staff": "/staff/login", "admin": "/admin/login"}[portal]
    page.goto(f"{base}{login_path}")
    page.fill("#email", email)
    page.fill("#password", "Password1")
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#otp-step:not(.d-none)", timeout=10000)
    code = TestingOtpSender.latest(email)
    assert code, "no OTP recorded by TestingOtpSender"
    boxes = page.locator("#otp-step .otp-digit")
    for i, ch in enumerate(code):
        boxes.nth(i).fill(ch)
    page.click("#otp-verify")
    page.wait_for_url("**/admin" if portal == "admin" else "**/dashboard", timeout=10000)


def _no_overflow(page, url, width, base):
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{base}{url}")
    page.wait_for_timeout(350)
    scroll_w = page.evaluate("document.documentElement.scrollWidth")
    client_w = page.evaluate("window.innerWidth")
    if scroll_w > client_w + 2:
        offenders = page.evaluate(
            """(() => {
              const out = [];
              document.querySelectorAll('body *').forEach(e => {
                const r = e.getBoundingClientRect();
                if (r.right > window.innerWidth + 2 || r.left < -2)
                  out.push(e.tagName + '|' + String(e.className||'').slice(0,50) + '|r=' + Math.round(r.right));
              });
              return out.slice(0, 6);
            })()""")
    assert scroll_w <= client_w + 2, \
        f"{url} @ {width}px: horizontal overflow ({scroll_w}>{client_w}) {locals().get('offenders', '')}"


def test_no_horizontal_overflow_any_page_any_width(ui_server):
    base = ui_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        anon = browser.new_context().new_page()
        for url in PAGES_PUBLIC:
            for width in WIDTHS:
                _no_overflow(anon, url, width, base)
        # authed pages (one shared logged-in context)
        user = browser.new_context().new_page()
        _login(user, base, "ui-user@test.com")
        for url in ["/dashboard", "/report/lost", "/report/found", "/browse",
                    "/profile", "/claims", "/notifications"]:
            for width in WIDTHS:
                _no_overflow(user, url, width, base)
        # admin pages
        admin = browser.new_context().new_page()
        _login(admin, base, "ui-admin@test.com")
        for url in ["/admin", "/admin/reports", "/admin/claims", "/admin/users",
                    "/admin/institutions", "/admin/recoveries", "/admin/audit"]:
            for width in WIDTHS:
                _no_overflow(admin, url, width, base)
        browser.close()


def test_theme_toggle_persists_across_reload(ui_server):
    base = ui_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.goto(f"{base}/")
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") is None
        # the toggle lives in the account dropdown -> login first
        _login(page, base, "ui-user@test.com")
        page.goto(f"{base}/dashboard")
        page.click('.nav-item.dropdown a[data-bs-toggle="dropdown"]')
        page.wait_for_selector("#theme-toggle", state="visible", timeout=5000)
        page.click("#theme-toggle")
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
        try:
            stored = page.evaluate("localStorage.getItem('tb-theme')")
        except Exception:
            stored = None
        assert stored == "dark"
        # survives a reload (pre-paint script re-applies it)
        page.reload()
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "dark"
        # cycle back to light (reload closed the dropdown; reopen it)
        page.click('.nav-item.dropdown a[data-bs-toggle="dropdown"]')
        page.wait_for_selector("#theme-toggle", state="visible", timeout=5000)
        page.click("#theme-toggle")  # dark -> system
        page.click('.nav-item.dropdown a[data-bs-toggle="dropdown"]')
        page.wait_for_selector("#theme-toggle", state="visible", timeout=5000)
        page.click("#theme-toggle")  # system -> light
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") is None
        browser.close()


def test_stepper_navigation_back_and_draft_restore(ui_server):
    base = ui_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        _login(page, base, "ui-user@test.com")
        page.goto(f"{base}/report/lost")

        # step 1 visible, back disabled
        assert page.locator(".stepper-step[data-step='1']").is_visible()
        assert page.locator("#step-back").is_disabled()
        assert page.locator("#step-label").inner_text() == "Step 1 of 4"

        # forward to step 2, fill fields
        page.click("#step-next")
        assert page.locator(".stepper-step[data-step='2']").is_visible()
        page.click(".category-cell[data-value='WALLETS_CARDS']")
        page.fill("#title", "Silver watch with leather band")
        page.fill("#description", "A silver wristwatch with a brown leather band and a small scratch on the face.")
        page.click("#step-next")

        # step 3: date validation blocks empty submit
        page.click("#step-next")
        assert page.locator("#date-error").is_visible()
        page.fill("#incident_date", "2026-01-15T10:30")
        page.fill("#location_text", "near the fountain")
        page.click("#step-next")
        # step 4: review shows our data
        assert page.locator(".stepper-step[data-step='4']").is_visible()
        assert "Silver watch" in page.locator("#review-summary").inner_text()

        # back navigation works
        page.click("#step-back")
        assert page.locator(".stepper-step[data-step='3']").is_visible()
        page.click("#step-back")
        assert page.locator(".stepper-step[data-step='2']").is_visible()

        # draft survives a reload (autosave)
        page.reload()
        assert page.locator("#title").input_value() == "Silver watch with leather band"
        assert page.locator("#description").input_value().startswith("A silver wristwatch")
        assert page.locator(".category-cell.selected").get_attribute("data-value") == "WALLETS_CARDS"
        # progress restored to step 1 but data intact -> advance to review again
        page.click("#step-next")  # 1 -> 2
        page.click("#step-next")  # 2 -> 3
        page.click("#step-next")  # 3 -> 4
        assert page.locator("#review-summary").inner_text().count("2026-01-15") >= 1
        browser.close()


def test_aria_current_page_highlight(ui_server):
    base = ui_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        page.goto(f"{base}/institutions")
        current = page.locator('.site-navbar a[aria-current="page"]')
        assert current.count() == 1
        assert "/institutions" in current.get_attribute("href")
        browser.close()


def test_axe_core_no_critical_violations(ui_server):
    """axe-core audit: no critical/serious violations on key pages."""
    from axe_playwright_python.sync_playwright import Axe
    base = ui_server
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context().new_page()
        _login(page, base, "ui-user@test.com")
        offending = {}
        for url in ["/", "/dashboard", "/report/lost", "/browse", "/profile", "/login"]:
            page.goto(f"{base}{url}")
            page.wait_for_timeout(400)
            results = Axe().run(page)
            bad = [v for v in results.response["violations"]
                   if v.get("impact") in ("critical", "serious")]
            if bad:
                offending[url] = [(v["id"], v["impact"], len(v["nodes"])) for v in bad]
        browser.close()
        assert not offending, f"axe-core critical/serious violations: {offending}"
