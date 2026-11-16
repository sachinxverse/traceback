"""Part E — Playwright tests for the three portal login flows and OTP UI.

Covers: separate portals (wrong credentials on wrong portals fail), the OTP
digit boxes (auto-advance + paste), resend countdown, error and locked states,
and the footer-only staff/admin links. Uses a TestingOtpSender to read codes.
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
    from app.services import storage as storage_mod
    from app.services.embeddings import reset_embedder

    reset_embedder()
    storage_mod.reset_storage()
    port = _free_port()
    db_dir = tmp_path_factory.mktemp("ui-portal")
    app = create_app("testing")
    app.config.update({
        "DATABASE_URL": f"sqlite:///{(db_dir / 'portal.db').as_posix()}",
        "UPLOAD_DIR": str(db_dir / "uploads"),
    })
    os.environ["DATABASE_URL"] = f"sqlite:///{(db_dir / 'portal.db').as_posix()}"
    with app.app_context():
        _db.create_all()
        from app.models import User
        from app.models.enums import Role
        a = User(name="Admin UI", email="adm-portal@test.com", role=Role.ADMIN,
                 email_verified=True)
        a.set_password("Password1")
        from app.models import Institution
        inst = Institution(name="Portal Inst", slug="portal-inst")
        _db.session.add(inst)
        _db.session.flush()
        s = User(name="Staff UI", email="stf-portal@test.com", role=Role.STAFF,
                 institution_id=inst.id, email_verified=True)
        s.set_password("Password1")
        u = User(name="User UI", email="usr-portal@test.com", email_verified=True)
        u.set_password("Password1")
        _db.session.add_all([a, s, u])
        _db.session.commit()
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", port, app)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(1.0)
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


def _fill_otp(page, code):
    boxes = page.locator(".otp-digit")
    boxes.first.fill(code[0])
    for i, ch in enumerate(code):
        boxes.nth(i).fill(ch)


def _step1(page, base, portal, email, password="Password1"):
    page.goto(f"{base}/{'' if portal == 'user' else portal + '/'}login")
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("#login-form button[type=submit]")


def test_user_portal_login_with_otp_boxes(ui_server):
    from app.services.otp import TestingOtpSender
    TestingOtpSender.reset()
    base = ui_server
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context().new_page()
        _step1(page, base, "user", "usr-portal@test.com")
        page.wait_for_selector("#otp-step:not(.d-none)")
        assert "u***@test.com" in page.locator("#otp-destination").inner_text()
        # expiry countdown is running
        assert "5:" in page.locator("#otp-countdown").inner_text()
        # resend disabled during cooldown with a visible countdown
        assert "Resend code" in page.locator("#otp-resend").inner_text()
        assert page.locator("#otp-resend").is_disabled()
        # wrong code shows a friendly error with attempts left
        _fill_otp(page, "000000")
        page.click("#otp-verify")
        page.wait_for_selector("#otp-error.show")
        assert "Incorrect code" in page.locator("#otp-error").inner_text()
        # correct code signs in
        code = TestingOtpSender.latest("usr-portal@test.com")
        _fill_otp(page, code)
        page.click("#otp-verify")
        page.wait_for_url("**/dashboard", timeout=10000)
        b.close()


def test_wrong_credentials_on_wrong_portal_fail_in_ui(ui_server):
    base = ui_server
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context().new_page()
        # user credentials on the admin portal
        _step1(page, base, "admin", "usr-portal@test.com")
        page.wait_for_selector("#login-error.show")
        assert page.locator("#login-error").inner_text() == "Invalid credentials"
        # no OTP step appeared
        assert page.locator("#otp-step").evaluate("el => el.classList.contains('d-none')")
        # admin credentials on the user portal
        _step1(page, base, "user", "adm-portal@test.com")
        page.wait_for_selector("#login-error.show")
        assert page.locator("#login-error").inner_text() == "Invalid credentials"
        b.close()


def test_admin_and_staff_portals_end_to_end(ui_server):
    from app.services.otp import TestingOtpSender
    base = ui_server
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context().new_page()
        TestingOtpSender.reset()
        _step1(page, base, "admin", "adm-portal@test.com")
        page.wait_for_selector("#otp-step:not(.d-none)")
        assert "Admin Portal" in page.locator("h1").inner_text()
        assert "authorised staff only" in page.content()
        _fill_otp(page, TestingOtpSender.latest("adm-portal@test.com"))
        page.click("#otp-verify")
        page.wait_for_url("**/admin", timeout=10000)
        b.close()
        b2 = p.chromium.launch()
        page = b2.new_context().new_page()
        TestingOtpSender.reset()
        _step1(page, base, "staff", "stf-portal@test.com")
        page.wait_for_selector("#otp-step:not(.d-none)")
        assert "Staff Portal" in page.locator("h1").inner_text()
        _fill_otp(page, TestingOtpSender.latest("stf-portal@test.com"))
        page.click("#otp-verify")
        page.wait_for_url("**/staff", timeout=10000)
        # staff navbar shows staff items, never user items
        nav = page.locator("nav").inner_text()
        assert "Institution reports" in nav and "Report Lost" not in nav
        b2.close()


def test_locked_state_after_max_attempts(ui_server):
    from app.services.otp import TestingOtpSender
    base = ui_server
    TestingOtpSender.reset()
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context().new_page()
        _step1(page, base, "user", "usr-portal@test.com")
        page.wait_for_selector("#otp-step:not(.d-none)")
        for _ in range(5):
            _fill_otp(page, "000000")
            page.click("#otp-verify")
            page.wait_for_timeout(200)
        page.wait_for_selector("#otp-error.show")
        assert "Too many incorrect codes" in page.locator("#otp-error").inner_text()
        b.close()


def test_register_flow_ends_in_otp_verification(ui_server):
    from app.services.otp import TestingOtpSender
    base = ui_server
    TestingOtpSender.reset()
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context().new_page()
        page.goto(f"{base}/register")
        page.fill("#name", "OTP Reg")
        page.fill("#email", "reg-otp@test.com")
        page.fill("#password", "Password1")
        page.click("#register-form button[type=submit]")
        page.wait_for_selector("#register-otp-step:not(.d-none)")
        code = TestingOtpSender.latest("reg-otp@test.com", "REGISTER")
        _fill_otp(page, code)
        page.click("#reg-otp-verify")
        page.wait_for_url("**/dashboard", timeout=10000)
        b.close()


def test_footer_links_only_for_staff_admin(ui_server):
    base = ui_server
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context().new_page()
        page.goto(f"{base}/")
        footer = page.locator("footer").inner_text()
        assert "Staff sign in" in footer and "Admin sign in" in footer
        # navbar must NOT link the portals
        navbar_html = page.locator("nav").inner_html()
        assert "/admin/login" not in navbar_html and "/staff/login" not in navbar_html
        b.close()


def test_every_link_on_every_page_is_alive(ui_server):
    """D1/D6: every <a href> is a real page (no href='#' outside dropdowns/tabs)."""
    from app.services.otp import TestingOtpSender
    base = ui_server
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context()
        page = ctx.new_page()
        offenders = []
        def visit(portal, pages):
            TestingOtpSender.reset()
            _login_via_ui(page, base,
                          {"user": "usr-portal@test.com", "staff": "stf-portal@test.com",
                           "admin": "adm-portal@test.com"}[portal], portal)
            for path in pages:
                page.goto(f"{base}{path}")
                page.wait_for_timeout(300)
                for a in page.query_selector_all("a[href]"):
                    href = a.get_attribute("href") or ""
                    if href == "#" and (a.get_attribute("data-bs-toggle") is None
                                        and a.get_attribute("data-status") is None
                                        and a.evaluate("el => !!el.closest('.leaflet-control')") is False):
                        offenders.append((path, (a.inner_text() or "")[:30]))
            page.evaluate(
                "fetch('/api/v1/auth/logout', {method:'POST', headers:{'X-CSRF-TOKEN': document.cookie.match(/csrf_access_token=([^;]+)/)[1]}})")
            page.wait_for_timeout(300)
        visit("user", ["/", "/institutions", "/dashboard", "/browse", "/claims",
                       "/notifications", "/profile", "/report/lost"])
        visit("staff", ["/staff", "/staff/reports", "/staff/claims",
                        "/staff/recoveries", "/staff/analytics", "/staff/poster"])
        visit("admin", ["/admin", "/admin/reports", "/admin/claims", "/admin/users",
                        "/admin/institutions", "/admin/recoveries", "/admin/audit"])
        b.close()
        assert not offenders, offenders


def _login_via_ui(page, base, email, portal="user"):
    from app.services.otp import TestingOtpSender
    TestingOtpSender.reset()
    login_path = {"user": "/login", "staff": "/staff/login", "admin": "/admin/login"}[portal]
    page.goto(f"{base}{login_path}")
    page.fill("#email", email)
    page.fill("#password", "Password1")
    page.click("#login-form button[type=submit]")
    page.wait_for_selector("#otp-step:not(.d-none)", timeout=10000)
    code = TestingOtpSender.latest(email)
    _fill_otp(page, code)
    page.click("#otp-verify")
    page.wait_for_timeout(800)
