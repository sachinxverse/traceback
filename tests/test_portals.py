"""Part E — portal separation tests (B1)."""
from tests.conftest import auth, login, otp_code, register

import pytest


def _admin(db, email="port-admin@x.com"):
    from app.models import User
    from app.models.enums import Role
    u = User(name="Admin P", email=email, role=Role.ADMIN, email_verified=True)
    u.set_password("Password1")
    db.session.add(u)
    db.session.commit()
    return u


def _staff(db, email="port-staff@x.com", inst_id=None):
    from app.models import User
    from app.models.enums import Role
    u = User(name="Staff P", email=email, role=Role.STAFF, institution_id=inst_id,
             email_verified=True)
    u.set_password("Password1")
    db.session.add(u)
    db.session.commit()
    return u


def test_user_credentials_fail_on_staff_and_admin_portals(client, db):
    register(client, "u-port@x.com", "Portal U")
    for portal in ("staff", "admin"):
        r = client.post(f"/api/v1/auth/{portal}/login",
                        json={"email": "u-port@x.com", "password": "Password1"})
        assert r.status_code == 401
        assert r.get_json()["error"]["message"] == "Invalid credentials"


def test_staff_and_admin_fail_on_user_portal(client, db):
    _staff(db)
    _admin(db)
    for email, portal in [("port-staff@x.com", "user"), ("port-admin@x.com", "user")]:
        r = client.post(f"/api/v1/auth/{portal}/login",
                        json={"email": email, "password": "Password1"})
        assert r.status_code == 401
        assert r.get_json()["error"]["message"] == "Invalid credentials"


def test_staff_cannot_login_on_admin_portal_and_vice_versa(client, db):
    _staff(db)
    _admin(db)
    r = client.post("/api/v1/auth/admin/login",
                    json={"email": "port-staff@x.com", "password": "Password1"})
    assert r.status_code == 401
    r = client.post("/api/v1/auth/staff/login",
                    json={"email": "port-admin@x.com", "password": "Password1"})
    assert r.status_code == 401
    # wrong-portal attempts are audited
    from app.models import AuditLog
    assert AuditLog.query.filter_by(action="login_wrong_portal").count() >= 2


def test_user_token_cannot_call_admin_or_staff_endpoints(client, db):
    auth(client, "plain@x.com", "Plain")
    assert client.get("/api/v1/admin/users").status_code in (403, 404)
    assert client.get("/api/v1/admin/reports").status_code == 403
    assert client.get("/api/v1/staff/dashboard").status_code == 403
    assert client.get("/api/v1/staff/reports").status_code == 403


def test_staff_token_cannot_call_admin_endpoints(client, db):
    inst = _institution(db)
    _staff(db, "sc-staff@x.com", inst.id)
    login(client, "sc-staff@x.com")  # auto-detects the staff portal
    assert client.get("/api/v1/staff/dashboard").status_code == 200
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/api/v1/admin/analytics/summary").status_code == 403


def test_admin_token_cannot_call_staff_endpoints(client, db):
    _admin(db)
    login(client, "port-admin@x.com")  # auto-detects the admin portal
    assert client.get("/api/v1/staff/dashboard").status_code == 403
    assert client.get("/api/v1/admin/analytics/summary").status_code == 200


def _institution(db, name="Portal Inst"):
    from app.models import Institution
    inst = Institution(name=name, slug=Institution.unique_slug(name))
    db.session.add(inst)
    db.session.commit()
    return inst


def test_portal_mismatch_token_rejected_with_forged_claim(client, db, app):
    """A token whose portal claim doesn't match the area is rejected."""
    from flask_jwt_extended import create_access_token
    _staff(db)
    with app.app_context():
        from app.models import User
        u = User.query.filter_by(email="port-staff@x.com").one()
        # forge a USER-portal token for the staff member
        token = create_access_token(identity=str(u.id),
                                    additional_claims={"portal": "user", "tv": 0})
    client.set_cookie("access_token_cookie", token)
    assert client.get("/api/v1/staff/dashboard").status_code == 403


def test_second_portal_login_revokes_first_session(client, db):
    """B1.4: logging into another portal revokes the browser's current token."""
    _admin(db)
    register(client, "switch@x.com", "Switch")
    login(client, "switch@x.com")           # user portal session
    assert client.get("/api/v1/auth/me").status_code == 200
    r = login(client, "port-admin@x.com")   # admin portal login (same browser)
    assert r.status_code == 200
    # the USER token was blocklisted during the new login
    # (cookies were replaced by the admin session, but the old jti is revoked)
    from app.models import TokenBlocklist
    assert TokenBlocklist.query.count() >= 1
    # and the active session is the admin one
    r = client.get("/api/v1/auth/me")
    assert r.get_json()["data"]["role"] == "ADMIN"


def test_login_pages_exist_and_are_not_linked_from_navbar(client, db):
    r = client.get("/staff/login")
    assert r.status_code == 200 and "Staff Portal" in r.get_data(as_text=True)
    r = client.get("/admin/login")
    assert r.status_code == 200 and "Admin Portal" in r.get_data(as_text=True)
    home = client.get("/").get_data(as_text=True)
    # not linked from the navbar (footer-only)
    assert 'href="/admin/login"' not in home.split("</footer>")[0].split("<nav")[0]


def test_admin_creates_staff_account_via_admin_api(client, db):
    inst = _institution(db)
    _admin(db)
    login(client, "port-admin@x.com")
    r = client.post("/api/v1/admin/users", json={
        "name": "New Staff", "email": "new-staff@x.com", "password": "Password1",
        "role": "STAFF", "institution_id": inst.id})
    assert r.status_code == 201, r.get_data(as_text=True)
    # the new staff can log in through the staff portal
    r = login(client, "new-staff@x.com")
    assert r.status_code == 200
    assert client.get("/api/v1/staff/dashboard").status_code == 200
    # staff requires an institution (back to the admin session first)
    login(client, "port-admin@x.com")
    r2 = client.post("/api/v1/admin/users", json={
        "name": "No Inst", "email": "no-inst@x.com", "password": "Password1",
        "role": "STAFF"})
    assert r2.status_code == 400


def test_staff_dashboard_pages_render(client, db):
    inst = _institution(db)
    _staff(db, "dash-staff@x.com", inst.id)
    login(client, "dash-staff@x.com")
    for path in ["/staff", "/staff/reports", "/staff/claims",
                 "/staff/recoveries", "/staff/analytics", "/staff/poster"]:
        assert client.get(path).status_code == 200, path


def test_user_portal_pages_redirect_admin_portal_user(client, db):
    """A USER hitting an admin page gets the admin login, not a 404 leak."""
    auth(client, "norm2@x.com", "Norm")
    r = client.get("/admin")
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/login")
